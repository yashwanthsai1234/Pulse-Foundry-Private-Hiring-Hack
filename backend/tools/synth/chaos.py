"""Chaos runner: generate worlds, mutate the files, ingest, and compare with the baseline and the planted defects.

    python -m tools.synth.chaos --n 50 --seed 7 --out runtime/chaos [--clean]

Per variant: generate -> plant a random subset of defects -> ingest the clean files (baseline) -> mutate every CSV
with 1-3 mutators (+ a random PDF variant) and ingest again. Golden equality = persons and credentials equal the
baseline ignoring ids. Recall = expected issues found / expected; precision = matched / issues of the planted kinds.
Writes report.md and report.json. Matching rules: same check_id; facility must match when the expectation has one;
employee ids must overlap the issue's entity ids (person id P-<employee_id> or the license number) unless either side
has none (parse and coverage issues are not per person). Expectations with ids claim their issue first, the ones
without ids (wildcards) take what is left. `--clean` also scores the unmutated files (the baseline ingest), so the
report shows what the system gets wrong by itself next to what the format noise adds.

The agent paths are exercised too: the raster PDF variant is ingested with `SpecPageReader`, a deterministic stand-in for
the page_reader agent that answers every page from the schedule spec the PDF was rendered from; every other agent task
is rejected (agents off). Combinations that cannot work are not generated (see `allowed_mutators`, `pdf_variants`).

Sources:
- https://hypothesis.readthedocs.io/ (property-based testing: random inputs plus an invariant)
- https://hypothesis.readthedocs.io/en/latest/data.html (draw valid combinations by construction, not by filtering)
- https://dl.acm.org/doi/10.1145/3143561 (metamorphic testing: the same input in a different format must give the same output)
- https://aclanthology.org/2020.acl-main.442/ (CheckList: report invariance/directional tests per perturbation, not one score)
- https://docs.python.org/3/library/random.html (seeded, reproducible randomness)
- https://www.ssa.gov/oact/babynames/limits.html (name data behind the generator)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import tempfile
import traceback
from dataclasses import replace
from pathlib import Path

from tools.synth.generator import CATALOG, CHECKED, DEFECTS, generate_world, plant_defects, write_world
from tools.synth.mutators import MUTATORS

IGNORE_ON = {"drop_optional_column": {"phone", "hire_date", "last_verified"}}
ID_COLUMNS = {"person_id", "credential_id", "holder_id"}
NAME_COLUMNS = {"display_name", "holder_name"}  # upper_case_names changes only how a name is displayed
NEEDS_HR_COLUMN = {"hr_duplicate_row", "ambiguous_date_column", "bad_date_value"}  # a dropped phone/hire_date hides them


def allowed_mutators(file_name: str, catalog: list[str]) -> list[str]:
    """Mutators that cannot erase a planted defect from `file_name`."""
    banned = {"drop_optional_column"} if file_name == "hr_roster.csv" and NEEDS_HR_COLUMN & set(catalog) else set()
    return sorted(set(MUTATORS) - banned)


def pdf_variants(catalog: list[str]) -> list[str]:
    """Render variants that can still show the planted defects (a PDF without footnote has no legend to contradict)."""
    from tools.synth import render

    return [v for v in render.VARIANTS if not (v == "no_footnote" and "legend_mismatch_token" in catalog)]


class SpecPageReader:
    """Stands in for the page_reader agent: answers each page of a scanned PDF from the spec it was rendered from."""

    background = False

    def __init__(self, settings, specs: dict[str, dict]):
        self.settings, self.specs = settings, specs  # specs: sha256 of the PDF -> schedule spec

    async def submit(self, task) -> None:
        from sot.agents.executors import write_task

        write_task(self.settings, task)
        spec = self.specs[task.payload["file_id"]]
        page = spec["pages"][task.payload["page"] - 1]
        Path(task.output_path).write_text(json.dumps({
            "title": f"{page['title']} {page.get('subtitle', '')}".strip(), "header": spec["header"],
            "rows": page["rows"], "footnote": spec["footnote"]}))


def apply_chain(path: Path, names: list[str], rng: random.Random, out_dir: Path) -> Path:
    """Apply mutators in MUTATORS order (header-level first); the result keeps the original stem in `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    current = path
    for name in sorted(names, key=list(MUTATORS).index):
        nxt = MUTATORS[name](current, rng)
        if current != path:
            current.unlink()
        current = nxt
    final = out_dir / f"{path.stem}{current.suffix}"
    shutil.move(current, final)
    return final


def gold_snapshot(db) -> dict[str, list[tuple]]:
    """Persons and credentials as sorted tuples of (column, value) pairs without id columns."""
    def fold(k, v):
        return str(v).casefold() if k in NAME_COLUMNS else str(v)

    return {t: sorted(tuple(sorted((k, fold(k, v)) for k, v in row.items() if k not in ID_COLUMNS and v is not None))
                      for row in db.query(f"SELECT * FROM {t}")) for t in ("persons", "credentials")}


def gold_diff(base: dict, other: dict, ignore: set[str]) -> list[str]:
    """Rows present in only one snapshot (columns in `ignore` removed first)."""
    diff = []
    def strip(rows):
        return [tuple(p for p in r if p[0] not in ignore) for r in rows]

    for table, rows in base.items():
        a, b = strip(rows), strip(other[table])
        diff += [f"{table} only in baseline: {r}" for r in a if r not in b]
        diff += [f"{table} only in run: {r}" for r in b if r not in a]
    return diff


def match_issues(expected: list[dict], actual: list[dict], aliases: dict[str, set[str]]) -> dict:
    """One-to-one greedy matching of expected issues to actual ones; see module docstring for the rules."""
    free = [a for a in actual if a["check_id"] in CHECKED]
    missed, matched = [], 0
    for e in sorted(expected, key=lambda e: not e["employee_ids"]):  # wildcards last, so they cannot steal
        ids = set().union(*(aliases.get(i, {i}) for i in e["employee_ids"]))
        hit = next((a for a in free if a["check_id"] == e["check_id"]
                    and (not e.get("facility_id") or a.get("facility_id") == e["facility_id"])
                    and (not ids or not a["entity_ids"] or ids & set(a["entity_ids"]))), None)
        if hit is None:
            missed.append(e)
        else:
            free.remove(hit)
            matched += 1
    checked = sum(a["check_id"] in CHECKED for a in actual)
    return {"matched": matched, "expected": len(expected), "actual_checked": checked, "missed": missed,
            "unexpected": free, "recall": matched / len(expected) if expected else 1.0,
            "precision": matched / checked if checked else 1.0}


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if "error" not in r]

    def ratio(num: str, den: str, rs: list[dict] = ok) -> float:
        total = sum(r[den] for r in rs)
        return sum(r[num] for r in rs) / total if total else 1.0

    failures = [r for r in results if "error" in r or not r["golden_equal"] or r["matched"] < r["expected"]]
    summary = {"variants": len(results), "errors": len(results) - len(ok), "recall": ratio("matched", "expected"),
               "precision": ratio("matched", "actual_checked"),
               "golden_equality_rate": sum(r["golden_equal"] for r in ok) / len(ok) if ok else 0.0,
               "failures": [{"variant": r["variant"], "error": r.get("error"), "mutators": r["mutators"],
                             "diff": r.get("diff", [])[:5], "missed": [m["check_id"] for m in r.get("missed", [])]}
                            for r in failures]}
    clean = [r["clean"] for r in ok if "clean" in r]
    if clean:
        summary["clean"] = {"recall": ratio("matched", "expected", clean), "precision": ratio("matched", "actual_checked", clean),
                            "missed": sorted({m["check_id"] for c in clean for m in c["missed"]}),
                            "unexpected": sorted({u["check_id"] for c in clean for u in c["unexpected"]})}
    return summary


def render_md(summary: dict, results: list[dict]) -> str:
    lines = ["# Chaos report", "", f"{summary['variants']} variants, {summary['errors']} errors", "",
             "| files | recall | precision | golden equality |", "|---|---|---|---|"]
    if "clean" in summary:
        c = summary["clean"]
        lines.append(f"| clean (unmutated) | {c['recall']:.1%} | {c['precision']:.1%} | - |")
    lines += [f"| mutated | {summary['recall']:.1%} | {summary['precision']:.1%} | {summary['golden_equality_rate']:.1%} |",
              "", "## Failures", ""]
    for f in summary["failures"]:
        muts = "; ".join(f"{k}: {', '.join(v)}" for k, v in f["mutators"].items())
        what = f["error"] or f"missed {f['missed']} diff {f['diff']}"
        lines.append(f"- {f['variant']} ({muts}): {what}")
    lines += ["", "## Per variant", "", "| variant | pdf | golden | mutated matched/expected | clean matched/expected | defects |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {r['variant']} | {r.get('pdf_variant')} | {r.get('golden_equal')} | {r.get('matched')}/{r.get('expected')} | "
              f"{'{matched}/{expected}'.format(**r['clean']) if 'clean' in r else '-'} | {len(r.get('catalog', []))} |"
              for r in results]
    return "\n".join(lines) + "\n"


def _ingest(files: list[Path], as_of, runtime: Path, scans: dict[str, dict] | None = None):
    from sot.config import load_settings
    from sot.pipeline.orchestrator import Pipeline
    from sot.store.db import DB

    settings = replace(load_settings(runtime=runtime), agents="off", as_of=as_of)
    db = DB(settings.db_path)
    pipeline = Pipeline(settings, db)
    if scans:
        pipeline.gateway.executor = SpecPageReader(settings, scans)
    pipeline.ingest(files)
    if scans:
        pipeline.poll_agents()
    return db


def _issues(db) -> list[dict]:
    rows = db.query("SELECT check_id, entity_ids, facility_id FROM issues WHERE active")
    return [{**r, "entity_ids": r["entity_ids"] or []}
            for r in rows]


def run_variant(i: int, seed: int, out: Path, clean_too: bool = False) -> dict:
    from tools.synth import render

    rng = random.Random(seed * 1000 + i)
    name = f"v{i:03d}"
    result: dict = {"variant": name, "mutators": {}}
    try:
        catalog = rng.sample(sorted(DEFECTS), rng.randint(5, len(CATALOG)))
        world, expected = plant_defects(generate_world(rng.randrange(10**6), weeks=rng.randint(1, 2)), catalog, rng.randrange(10**6))
        clean, mutated = out / name / "clean", out / name / "mutated"
        write_world(world, clean, "grid")
        csvs = [clean / f for f in ("hr_roster.csv", "payroll.csv", "licenses.csv")]
        pdfs = sorted(clean.glob("schedule*.pdf"))
        pdf_variant = rng.choice(pdf_variants(catalog))
        files = []
        for src in csvs:
            names = rng.sample(allowed_mutators(src.name, catalog), rng.randint(1, 3))
            result["mutators"][src.name] = names
            files.append(apply_chain(src, names, rng, mutated))
        mutated.mkdir(exist_ok=True)
        scans = {}
        for src in pdfs:
            spec = json.loads(src.with_suffix(".json").read_text())
            files.append(render.render_schedule_pdf(spec, mutated / src.name, pdf_variant))
            scans[hashlib.sha256(files[-1].read_bytes()).hexdigest()] = spec
        result.update(catalog=catalog, pdf_variant=pdf_variant)
        want = [e for e in map(vars, expected) if e["kind"] != "no_merge"]
        truth = json.loads((clean / "truth.json").read_text())["persons"]
        aliases = {p["employee_id"]: {p["person_id"], p["license_number"]} for p in truth}
        base_db = _ingest(csvs + pdfs, world.as_of, Path(tempfile.mkdtemp(dir=out)))
        base = gold_snapshot(base_db)
        db = _ingest(files, world.as_of, Path(tempfile.mkdtemp(dir=out)), scans if pdf_variant == "raster_150dpi" else None)
        ignore = set().union(*(IGNORE_ON.get(m, set()) for ms in result["mutators"].values() for m in ms))
        result["diff"] = gold_diff(base, gold_snapshot(db), ignore)
        result["golden_equal"] = not result["diff"]
        result.update(match_issues(want, _issues(db), aliases))
        if clean_too:
            result["clean"] = match_issues(want, _issues(base_db), aliases)
        persons = {r["person_id"] for r in db.query("SELECT person_id FROM persons")}
        merged = [e.employee_ids for e in expected if e.kind == "no_merge"
                  and not all(f"P-{x}" in persons for x in e.employee_ids)]
        if merged:
            result["golden_equal"] = False
            result["diff"].append(f"wrongly merged: {merged}")
    except Exception:  # a crash is a finding, not a reason to stop the run
        result["error"] = traceback.format_exc(limit=3)
    return result


def run(n: int, seed: int, out: Path, clean: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    results = [run_variant(i, seed, out, clean) for i in range(n)]
    summary = summarize(results)
    (out / "report.json").write_text(json.dumps({"summary": summary, "variants": results}, indent=1, default=str))
    (out / "report.md").write_text(render_md(summary, results))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=Path, default=Path("runtime/chaos"))
    p.add_argument("--clean", action="store_true", help="also score the unmutated files (side by side in the report)")
    a = p.parse_args()
    s = run(a.n, a.seed, a.out, a.clean)
    if "clean" in s:
        print(f"clean:   recall {s['clean']['recall']:.1%} precision {s['clean']['precision']:.1%}")
    print(f"{s['variants']} variants: recall {s['recall']:.1%} precision {s['precision']:.1%} "
          f"golden {s['golden_equality_rate']:.1%} errors {s['errors']}")


if __name__ == "__main__":
    main()
