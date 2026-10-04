"""A/B harness: each experiment runs variant A (current system) and B on the SAME inputs, by monkeypatching `sot` at runtime.

    python -m tools.ab_tests --out docs/ab [--only pdf,mapping,er,hours,chaos,nick] [--quick]

Writes docs/ab/<experiment>.json (raw numbers) and docs/ab/AB_TESTS.md (tables; the interpretation paragraphs come from
docs/ab/notes/<experiment>.md when present). `sot/**` is only imported, never edited.

Sources (methodology cited in AB_TESTS.md):
- ER: pairwise precision/recall/F1 over record pairs (same cluster vs same true person); Hand & Christen 2018,
  https://openresearch-repository.anu.edu.au/items/e3bc0e58-14c1-43a5-b1fa-78b3fdbdcd10
- Tables: cell accuracy = cells equal to ground truth / max(rows) x columns (as tests/test_pdf_cascade.py); the
  literature scores cell content/topology, e.g. GriTS https://arxiv.org/pdf/2203.12555 and the ICDAR 2013 table
  competition's adjacency relations (cited in https://arxiv.org/pdf/2603.18652).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import random
import re
import shutil
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest import mock

from sot.config import load_settings
from sot.core.ids import sha256_bytes
from sot.core.models import FileRef
from sot.core.pack import load_pack
from sot.core.registry import ExtractContext
from sot.parsers.pdf import text_parser
from sot.parsers.pdf.methods import METHODS
from sot.pipeline.orchestrator import Pipeline
from sot.resolve.resolver import resolve_all
from sot.semantic import classify as classify_mod
from sot.semantic import mapper
from sot.store import repo
from sot.store.db import DB
from tools.synth import chaos, mutators, render
from tools.synth.generator import CATALOG, generate_world, plant_defects, write_world

BACKEND = Path(__file__).resolve().parents[1]
FIX = BACKEND / "tests" / "fixtures"
RW = FIX / "realworld"
ROOT = Path(tempfile.mkdtemp(prefix="ab_"))


# ---------------------------------------------------------------- helpers

def pipeline(as_of, tag: str, values: dict | None = None) -> Pipeline:
    """Fresh pipeline with agents off and its own runtime dir; `values` overrides settings (e.g. link.auto)."""
    s = load_settings(runtime=Path(tempfile.mkdtemp(dir=ROOT, prefix=tag)))
    s = replace(s, agents="off", as_of=as_of, values={**s.values, **(values or {})})
    return Pipeline(s, DB(s.db_path))


def build_world(seed: int, catalog, n_staff: int = 40, weeks: int = 1):
    """(world, expected, dir) with clean files written; one dir per call."""
    rng = random.Random(seed)
    world, expected = plant_defects(generate_world(seed, n_staff=n_staff, weeks=weeks), list(catalog), rng.randrange(10**6))
    d = Path(tempfile.mkdtemp(dir=ROOT, prefix="world"))
    write_world(world, d, "grid")
    return world, expected, d


def world_files(d: Path) -> list[Path]:
    return [d / "hr_roster.csv", d / "payroll.csv", d / "licenses.csv", *sorted(d.glob("schedule*.pdf"))]


def file_ref(path: Path) -> FileRef:
    data = path.read_bytes()
    return FileRef(file_id=sha256_bytes(data), file_name=path.name, path=str(path), size=len(data), received_at=datetime(2026, 9, 14))


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def prf(tp, fp, fn):
    p, r = tp / (tp + fp) if tp + fp else 1.0, tp / (tp + fn) if tp + fn else 1.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def pair_counts(pred: dict[str, str], truth: dict[str, str]) -> tuple[int, int, int]:
    """Pairwise TP/FP/FN over the records that have a truth label (pred: record -> cluster, truth: record -> person)."""
    ids = [r for r in truth if r in pred]
    c2 = lambda n: n * (n - 1) // 2  # noqa: E731
    from collections import Counter
    pc, tc = Counter(pred[r] for r in ids), Counter(truth[r] for r in ids)
    both = Counter((pred[r], truth[r]) for r in ids)
    tp = sum(map(c2, both.values()))
    return tp, sum(map(c2, pc.values())) - tp, sum(map(c2, tc.values())) - tp


def winner(rows: list[dict], key: str, higher: bool = True, tol: float = 1e-9) -> str:
    best = (max if higher else min)(r[key] for r in rows)
    w = [r["variant"] for r in rows if abs(r[key] - best) <= tol]
    return "tie (" + ", ".join(w) + ")" if len(w) > 1 else w[0]


# ---------------------------------------------------------------- 1. PDF cascade order

ORDERS = {"A current: lines, mupdf, words, text": METHODS,
          "B spec: lines, text, mupdf, words": tuple(sorted(METHODS, key=lambda m: ["pdf.lines", "pdf.text", "pdf.mupdf", "pdf.words"].index(m[0])))}
norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731  (pandoc PDFs hard-wrap inside words)


def pdf_inputs(quick: bool) -> list[tuple[str, Path, list[list[str]] | None]]:
    """(label, pdf, truth rows or None). reportlab variants (3 specs), e1, readme sample, real-world generated + web PDFs."""
    out = []
    work = Path(tempfile.mkdtemp(dir=ROOT, prefix="pdfs"))
    e1 = json.loads((FIX / "example_e1" / "schedule.json").read_text())
    specs = {"e1": e1, "mid": render.make_spec(4, 6, seed=1), "big": render.make_spec(2, 25, seed=2)}
    for v in render.VARIANTS:
        if v == "raster_150dpi":
            continue  # no text layer: goes to the scan parser, not the cascade
        for name, spec in specs.items():
            if name == "big" and (v.startswith("wrapped") or v == "two_tables_one_page"):
                continue  # 25 rows do not fit one page there
            p = render.render_schedule_pdf(spec, work / f"{v}_{name}.pdf", v)
            out.append((f"reportlab/{v}/{name}", p, [r for pg in spec["pages"] for r in pg["rows"]]))
    for d in ("example_e1", "readme_sample"):
        spec = json.loads((FIX / d / "schedule.json").read_text())
        out.append((f"fixture/{d}", FIX / d / "schedule.pdf", [r for pg in spec["pages"] for r in pg["rows"]]))
    truth = json.loads((RW / "pdf" / "truth.json").read_text())
    rows = [r for pg in truth["pages"] for r in pg["rows"]]
    for p in sorted((RW / "pdf").glob("*.pdf")):
        if p.name.startswith("scan_"):
            continue
        out.append((f"foreign/{p.stem}", p, None if p.name.startswith("web_") else rows))
    return out[::4] if quick else out


def cell_accuracy(tables, truth) -> float:
    got = [[norm(c) for c in row] for t in tables for row in t.df.drop("_src_row").rows()]
    want = [[norm(c) for c in r] for r in truth]
    total = max(len(got), len(want)) * (len(want[0]) if want else 1)
    return sum(a == b for g, t in zip(got, want) for a, b in zip(g, t)) / total


def exp_pdf(quick=False) -> dict:
    s = load_settings(runtime=Path(tempfile.mkdtemp(dir=ROOT, prefix="pdfrt")))
    pack = load_pack(s.pack_dir)
    inputs, per_doc = pdf_inputs(quick), []
    for label, path, truth in inputs:
        row = {"input": label}
        for variant, order in ORDERS.items():
            with mock.patch.object(text_parser, "METHODS", order):
                times, tables = [], []
                for _ in range(3):
                    t0 = time.perf_counter()
                    tables = text_parser.PdfTextParser().extract(
                        file_ref(path), ExtractContext(settings=s, pack=pack, run_id="r", sniff_details={}, submit_task=None))
                    times.append(time.perf_counter() - t0)
            row[variant] = {"accuracy": cell_accuracy(tables, truth) if truth else None, "ms": min(times) * 1000,
                            "methods": sorted({t.extraction.method for t in tables}),
                            "score": min((t.extraction.score for t in tables), default=0.0)}
        per_doc.append(row)
    groups = {"reportlab variants": "reportlab/", "foreign PDFs (truth.json)": "foreign/", "fixtures e1/readme": "fixture/"}
    table = []
    for gname, prefix in groups.items():
        docs = [d for d in per_doc if d["input"].startswith(prefix) and d[next(iter(ORDERS))]["accuracy"] is not None]
        for variant in ORDERS:
            table.append({"group": gname, "variant": variant, "n": len(docs),
                          "cell_accuracy": mean(d[variant]["accuracy"] for d in docs), "ms_per_doc": mean(d[variant]["ms"] for d in docs),
                          "docs_below_100pct": sum(d[variant]["accuracy"] < 0.9999 for d in docs)})
    web = [d for d in per_doc if d["input"].startswith("foreign/web_")]
    return {"table": table, "web_pdfs_no_truth": [{"input": d["input"], **{v: {k: d[v][k] for k in ("methods", "score", "ms")} for v in ORDERS}} for d in web],
            "per_doc": per_doc}


# ---------------------------------------------------------------- 2. column mapping

README_MAP = {
    "hr_roster": ("hr_roster", {"employee_id": "person.employee_id", "first_name": "person.given_name", "last_name": "person.family_name",
                                "job_title": "person.role", "facility": "person.facility", "phone": "person.phone",
                                "license_number": "credential.number", "license_expiration": "credential.expires_on",
                                "hire_date": "person.hire_date"}),
    "payroll": ("payroll", {"payroll_id": "pay.payroll_id", "employee_name": "person.full_name", "job_code": "person.role",
                            "facility_code": "person.facility", "period_start": "pay.period_start", "period_end": "pay.period_end",
                            "hours_paid": "pay.hours_paid"}),
    "licenses": ("license", {"license_number": "credential.number", "name_on_license": "person.full_name",
                             "license_type": "credential.type", "expiration_date": "credential.expires_on",
                             "last_verified": "credential.last_verified"}),
}
FM = {"A current: header+value, value gate": None, "B header-only": "header", "C value-only": "value"}


def patched_field_match(mode):
    orig = mapper.field_match

    def fm(p, field, header=None):
        m = orig(p, field, header)
        s = m.header_score if mode == "header" else m.value_score
        return m.model_copy(update={"score": s})
    return fm


@contextlib.contextmanager
def mapping_variant(mode):
    if mode is None:
        yield
        return
    fm = patched_field_match(mode)
    with mock.patch.object(mapper, "field_match", fm), mock.patch.object(classify_mod, "field_match", fm):
        yield


def truth_for(path: Path, kind: str) -> tuple[str, dict[str, str]]:
    """(template, column header as written -> field id) for a (possibly mutated) file of README kind `kind`."""
    tpl, cols = README_MAP[kind]
    names = {}
    for orig, field in cols.items():
        for n in [orig, *mutators.SYNONYMS.get(orig, [])]:
            names[n.casefold()] = field
    return tpl, names


MAP_AS_OF = datetime(2026, 9, 21).date()


def map_file(path: Path, mode, as_of=MAP_AS_OF):
    with mapping_variant(mode):
        p = pipeline(as_of, "map")
        p.ingest([path], run_id="r1")
        rows = p.db.query("SELECT table_id, template_id, matches, status, confidence FROM mappings")
        headers = {r["table_id"]: repo.load_raw_table(p.db, r["table_id"]).header for r in rows}
    return rows, headers


def exp_mapping(quick=False) -> dict:
    cases = []  # (label, group, path, kind or None for unrelated)
    for kind in README_MAP:
        cases.append((f"readme/{kind}", "README CSVs", FIX / "readme_sample" / f"{kind if kind != 'licenses' else 'licenses'}.csv", kind))
    rng = random.Random(5)
    work = Path(tempfile.mkdtemp(dir=ROOT, prefix="mut"))
    for i in range(3 if quick else 10):
        _, _, d = build_world(100 + i, [])
        for kind in README_MAP:
            src = d / f"{kind}.csv" if kind != "licenses" else d / "licenses.csv"
            names = rng.sample(sorted(mutators.MUTATORS), rng.randint(1, 3))
            cases.append((f"mutated/w{i}/{kind}+{'+'.join(names)}", "mutated CSVs (1-3 mutators)",
                          chaos.apply_chain(src, names, rng, work / f"w{i}_{kind}"), kind))
    for kind in README_MAP:  # each mutator alone, so a failing one is named
        _, _, d = build_world(200, [])
        for name in sorted(mutators.MUTATORS):
            out = mutators.MUTATORS[name](d / f"{kind}.csv", random.Random(1))
            cases.append((f"single/{kind}+{name}", "single mutator", out, kind))
    related = ["hr_roster_cp1252_crlf.csv", "hr_roster_cp1252_crlf_10rows.csv", "hr_roster_utf8_control.csv"]
    for n in related:
        cases.append((f"realworld/{n}", "real-world HR roster (must map)", RW / n, "hr_roster"))
    for n in ["pbj_daily_nurse_sample.csv", "co_nurse_licenses.csv", "tx_rn_active.csv", "nyc_payroll.csv", "chicago_employees.csv", "tx_rn_cp1252_crlf.csv"]:
        cases.append((f"realworld/{n}", "real-world unrelated (must NOT auto-map)", RW / n, None))
    results = []
    for label, group, path, kind in cases:
        row = {"case": label, "group": group}
        for variant, mode in FM.items():
            rows, headers = map_file(path, mode)
            m = rows[0] if rows else {"template_id": None, "matches": [], "status": "none", "confidence": 0.0}
            pred = {x["column"]: x["field_id"] for x in m["matches"]} if m["template_id"] else {}
            hdr = next(iter(headers.values()), [])
            if kind is None:
                row[variant] = {"auto_mapped": m["status"] == "mapped", "template": m["template_id"], "confidence": m["confidence"]}
                continue
            tpl, names = truth_for(path, kind)
            if kind == "hr_roster" and group.startswith("real-world"):
                tpl, names = truth_for(path, "hr_roster")
            if kind == "licenses":
                tpl = "license"
            want = {c: names.get(c.casefold()) for c in hdr}
            ok = sum(pred.get(c) == f for c, f in want.items())
            row[variant] = {"template_ok": m["template_id"] == tpl, "cols_ok": ok, "cols": len(hdr), "auto_mapped": m["status"] == "mapped",
                            "confidence": m["confidence"], "wrong": {c: pred.get(c) for c, f in want.items() if pred.get(c) != f}}
        results.append(row)
    return {"table": _mapping_table(results), "cases": results}


def _mapping_table(results: list[dict]) -> list[dict]:
    table = []
    for group in dict.fromkeys(r["group"] for r in results):
        rs = [r for r in results if r["group"] == group]
        for variant in FM:
            if group.startswith("real-world unrelated"):
                table.append({"group": group, "variant": variant, "n": len(rs),
                              "false_auto_maps": sum(r[variant]["auto_mapped"] for r in rs), "template_acc": None, "col_acc": None, "auto_rate": None})
            else:
                v = [r[variant] for r in rs]
                table.append({"group": group, "variant": variant, "n": len(rs), "template_acc": mean(x["template_ok"] for x in v),
                              "col_acc": sum(x["cols_ok"] for x in v) / sum(x["cols"] for x in v),
                              "auto_rate": mean(x["auto_mapped"] for x in v), "false_auto_maps": None})
    return table


# ---------------------------------------------------------------- 3 & 6. entity resolution / nicknames

def truth_labels(records, truth_persons) -> tuple[dict[str, str], int]:
    """record_id -> employee_id for records whose identity is unambiguous in truth.json; second value = records skipped."""
    by_key: dict[tuple, set[str]] = {}
    for p in truth_persons:
        e = p["employee_id"]
        by_key.setdefault(("hr_roster", e), set()).add(e)
        by_key.setdefault(("license", p["license_number"], p["names"]["license"]), set()).add(e)
        by_key.setdefault(("payroll", p["names"]["payroll"]), set()).add(e)
        by_key.setdefault(("schedule", p["names"]["schedule"]), set()).add(e)
    out, skipped = {}, 0
    for r in records:
        raw = r.raw
        key = {"hr_roster": ("hr_roster", raw.get("employee_id", "").strip().upper()),
               "license": ("license", raw.get("license_number", "").strip(), raw.get("name_on_license", "")),
               "payroll": ("payroll", raw.get("employee_name", "")),
               "schedule": ("schedule", next((v for k, v in raw.items() if k.lower().startswith("staff")), ""))}.get(r.template_id)
        ids = by_key.get(key, set())
        if len(ids) == 1:
            out[r.record_id] = next(iter(ids))
        else:
            skipped += 1
    return out, skipped


def er_worlds(n_small: int, n_big: int):
    """(seed, n_staff) list; all defects planted."""
    return [(300 + i, 40) for i in range(n_small)] + [(400 + i, 80) for i in range(n_big)]


def ingest_world(seed, n_staff, catalog, tag, patches=()):
    world, expected, d = build_world(seed, catalog, n_staff=n_staff)
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        p = pipeline(world.as_of, tag)
        p.ingest(world_files(d), run_id="r1")
    truth = json.loads((d / "truth.json").read_text())["persons"]
    return world, expected, p, truth


def exp_er(quick=False) -> dict:
    variants = {"A current link.auto 0.95": 0.95, "B link.auto 0.90": 0.90, "C link.auto 0.98": 0.98}
    worlds = er_worlds(3, 1) if quick else er_worlds(10, 4)
    per_world = []
    for seed, n in worlds:
        _, _, p, truth = ingest_world(seed, n, CATALOG, "er")
        records = repo.load_records(p.db)
        labels, skipped = truth_labels(records, truth)
        row = {"seed": seed, "n_staff": n, "records": len(records), "labelled": len(labels), "skipped_ambiguous": skipped}
        for name, auto in variants.items():
            s = replace(p.settings, values={**p.settings.values, "link.auto": auto})
            res = resolve_all(records, p.pack, s)
            pred = {rid: pr.person_id for pr in res.persons for rid in pr.record_ids}
            tp, fp, fn = pair_counts(pred, labels)
            row[name] = {"tp": tp, "fp": fp, "fn": fn, "persons": len(res.persons), "gray_pairs": len(res.gray_pairs)}
        per_world.append(row)
    table = []
    for group, ws in (("40-staff worlds", [w for w in per_world if w["n_staff"] == 40]), ("80-staff worlds", [w for w in per_world if w["n_staff"] == 80]), ("all", per_world)):
        for name in variants:
            tp, fp, fn = (sum(w[name][k] for w in ws) for k in ("tp", "fp", "fn"))  # micro-average over worlds
            table.append({"group": group, "variant": name, "n": len(ws), **prf(tp, fp, fn), "fp": fp, "fn": fn,
                          "gray_pairs": sum(w[name]["gray_pairs"] for w in ws)})
    return {"table": table, "per_world": per_world}


def exp_nick(quick=False) -> dict:
    catalog = ["nickname_on_schedule", "last_first_in_payroll", "typo_family_name", "whitespace_case_noise", "maiden_name_on_license"]
    seeds = range(500, 504 if quick else 512)
    variants = {"A current: nickname table (325 pairs)": False, "B nickname table emptied": True}
    per_world = []
    for seed in seeds:
        row = {"seed": seed}
        for name, empty in variants.items():
            orig = load_pack
            patches = [mock.patch("sot.pipeline.orchestrator.load_pack", lambda d, _o=orig: _o(d).model_copy(update={"nicknames": {}}))] if empty else []
            _, _, p, truth = ingest_world(seed, 40, catalog, "nick", patches)
            records = repo.load_records(p.db)
            labels, _ = truth_labels(records, truth)
            links = p.db.query("SELECT person_id, record_id FROM person_records")
            pred = {r["record_id"]: r["person_id"] for r in links}
            tp, fp, fn = pair_counts(pred, labels)
            persons = p.db.query("SELECT count(*) n FROM persons")[0]["n"]
            row[name] = {"persons": persons, "true_persons": len(truth), "tp": tp, "fp": fp, "fn": fn}
        per_world.append(row)
    table = []
    for name in variants:
        tp, fp, fn = (sum(w[name][k] for w in per_world) for k in ("tp", "fp", "fn"))
        table.append({"variant": name, "n": len(per_world),
                      "person_count_abs_error": mean(abs(w[name]["persons"] - w[name]["true_persons"]) for w in per_world),
                      "person_count_signed_error": mean(w[name]["persons"] - w[name]["true_persons"] for w in per_world), **prf(tp, fp, fn)})
    return {"table": table, "per_world": per_world}


# ---------------------------------------------------------------- 4. shift hours source (RC12)

def legend_first(tok, legend_h):
    if legend_h is not None:
        return legend_h, "legend"
    return (tok.hours, "computed") if tok.hours is not None else (None, "unknown")


def exp_hours(quick=False) -> dict:
    from sot.normalize import silver
    n = 3 if quick else 10
    conds = {"legend_mismatch only": ["legend_mismatch_token"], "no defects": [],
             "legend_mismatch + paid_vs_scheduled_delta": ["legend_mismatch_token", "paid_vs_scheduled_delta"]}
    variants = {"A current: hours from times": [], "B legend-first": [mock.patch.object(silver, "_shift_hours", legend_first)]}
    per_world = []
    for cname, catalog in conds.items():
        for i in range(n):
            row = {"condition": cname, "seed": 600 + i}
            for vname, patches in variants.items():
                _, expected, p, truth = ingest_world(600 + i, 40, catalog, "hrs", patches=patches)
                aliases = {t["employee_id"]: {t["person_id"], t["license_number"]} for t in truth}
                issues = chaos._issues(p.db)
                hrs = [x for x in issues if x["check_id"] == "HRS-PAID-VS-SCHED"]
                m = chaos.match_issues([vars(e) for e in expected if e.check_id == "HRS-PAID-VS-SCHED"], hrs, aliases)
                row[vname] = {"hrs_issues": len(hrs), "hrs_expected": sum(e.check_id == "HRS-PAID-VS-SCHED" for e in expected),
                              "hrs_false": len(hrs) - m["matched"], "hrs_matched": m["matched"],
                              "legend_issues": sum(x["check_id"] == "LEGEND-MISMATCH" for x in issues),
                              "legend_expected": sum(e.check_id == "LEGEND-MISMATCH" for e in expected)}
            per_world.append(row)
    table = []
    for cname in conds:
        ws = [w for w in per_world if w["condition"] == cname]
        for vname in variants:
            v = [w[vname] for w in ws]
            table.append({"condition": cname, "variant": vname, "n": len(ws),
                          "false_HRS_PAID_VS_SCHED": sum(x["hrs_false"] for x in v),
                          "true_HRS_found": f"{sum(x['hrs_matched'] for x in v)}/{sum(x['hrs_expected'] for x in v)}",
                          "LEGEND_MISMATCH_found": f"{sum(x['legend_issues'] for x in v)}/{sum(x['legend_expected'] for x in v)}"})
    return {"table": table, "per_world": per_world}


# ---------------------------------------------------------------- 5. whole pipeline (chaos)

def exp_chaos(quick=False) -> dict:
    """chaos.run_variant per world (own aggregation, so a change in chaos.summarize cannot break the headline)."""
    n = 6 if quick else 24
    out = Path(tempfile.mkdtemp(dir=ROOT, prefix="chaos"))
    results = [chaos.run_variant(i, 7, out, True) for i in range(n)]
    ok = [r for r in results if "error" not in r]
    agg = lambda rs, num, den: sum(r[num] for r in rs) / max(sum(r[den] for r in rs), 1)  # noqa: E731
    clean = [r["clean"] for r in ok]
    table = [{"variant": "A current, clean files", "n": len(ok), "recall": agg(clean, "matched", "expected"),
              "precision": agg(clean, "matched", "actual_checked"), "golden_equality": None},
             {"variant": "A current, mutated files", "n": len(ok), "recall": agg(ok, "matched", "expected"),
              "precision": agg(ok, "matched", "actual_checked"), "golden_equality": mean(r["golden_equal"] for r in ok)}]
    count = lambda rs, key: {k: sum(k == m["check_id"] for r in rs for m in r[key]) for k in sorted({m["check_id"] for r in rs for m in r[key]})}  # noqa: E731
    return {"table": table, "errors": [r["error"] for r in results if "error" in r], "clean_missed_by_check": count(clean, "missed"),
            "clean_unexpected_by_check": count(clean, "unexpected"), "mutated_missed_by_check": count(ok, "missed"),
            "mutated_unexpected_by_check": count(ok, "unexpected"),
            "golden_failures": [{"variant": r["variant"], "mutators": r["mutators"], "diff": r["diff"][:3]} for r in ok if not r["golden_equal"]],
            "variants": results}


# ---------------------------------------------------------------- report

EXPS = {
    "pdf": ("1. PDF cascade order", exp_pdf, [("group", "variant"), ("n", "cell_accuracy", "ms_per_doc", "docs_below_100pct")], "variant", "cell_accuracy"),
    "mapping": ("2. Column mapping score", exp_mapping, None, None, None),
    "er": ("3. Entity-resolution threshold link.auto", exp_er, None, None, None),
    "hours": ("4. Shift hours source (RC12)", exp_hours, None, None, None),
    "chaos": ("5. Whole pipeline (chaos)", exp_chaos, None, None, None),
    "nick": ("6. Nickname table on/off", exp_nick, None, None, None),
}
WINNER_KEY = {"pdf": ("group", "cell_accuracy", True), "mapping": ("group", "col_acc", True), "er": ("group", "f1", True),
              "hours": ("condition", "false_HRS_PAID_VS_SCHED", False), "nick": (None, "f1", True)}


def fmt(v):
    return f"{v:.3f}" if isinstance(v, float) else "" if v is None else str(v)


def md_table(rows: list[dict], group_key: str | None, win_key: str | None, higher: bool) -> str:
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols + (["winner"] if win_key else [])) + " |", "|" + "---|" * (len(cols) + (1 if win_key else 0))]
    for r in rows:
        w = ""
        if win_key and r.get(win_key) is not None:
            keys = (group_key,) if isinstance(group_key, str) else group_key or ()
            peers = [x for x in rows if all(x[k] == r[k] for k in keys)]
            peers = [x for x in peers if x.get(win_key) is not None]
            w = "yes" if abs(r[win_key] - (max if higher else min)(x[win_key] for x in peers)) <= 1e-9 else ""
            if w and sum(abs(x[win_key] - r[win_key]) <= 1e-9 for x in peers) > 1:
                w = "tie"
        lines.append("| " + " | ".join(fmt(r[c]) for c in cols) + (f" | {w} |" if win_key else " |"))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("docs/ab"))
    ap.add_argument("--only", default=",".join(EXPS), help="comma list; empty = only rebuild AB_TESTS.md from the json")
    ap.add_argument("--quick", action="store_true", help="small sample, for a smoke test")
    a = ap.parse_args()
    if not a.out.is_absolute():
        a.out = BACKEND.parent / a.out  # relative to the repo root
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        for key in filter(None, a.only.split(",")):
            t0 = time.time()
            (a.out / f"{key}.json").write_text(json.dumps(EXPS[key][1](a.quick), indent=1, default=str))
            print(f"{key}: done in {time.time() - t0:.0f}s")
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    render_report(a.out)


def render_report(out: Path) -> None:
    """AB_TESTS.md from every docs/ab/<experiment>.json present (+ notes/<experiment>.md interpretation)."""
    md = ["# A/B tests", "", "Generated by `python -m tools.ab_tests --out docs/ab`. Raw numbers: `docs/ab/*.json`. Variant A is the current "
          "system; `winner` marks the best variant per group (`tie` = equal).", ""]
    if (out / "notes" / "_method.md").exists():
        md += [(out / "notes" / "_method.md").read_text().strip(), ""]
    for key, (title, *_) in EXPS.items():
        if not (out / f"{key}.json").exists():
            continue
        res = json.loads((out / f"{key}.json").read_text())
        gk, wk, higher = WINNER_KEY.get(key, (None, None, True))
        md += [f"## {title}", "", md_table(res["table"], gk, wk, higher), ""]
        if (out / "notes" / f"{key}.md").exists():
            md += [(out / "notes" / f"{key}.md").read_text().strip(), ""]
    (out / "AB_TESTS.md").write_text("\n".join(md))


if __name__ == "__main__":
    main()
