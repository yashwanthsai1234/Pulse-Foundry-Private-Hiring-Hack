"""Shared helper for the W3-B3 real-world breakers: ingest ONE file through the real Pipeline (agents off)."""
import json
from datetime import date
from pathlib import Path

from sot.config import load_settings
from sot.pipeline.orchestrator import Pipeline

RW = Path(__file__).parent.parent / "fixtures" / "realworld"


def ingest(path, runtime, as_of=date(2026, 9, 21)):
    s = load_settings(runtime=Path(runtime))
    s.agents = "off"
    s.as_of = as_of
    p = Pipeline(s)
    err = None
    try:
        summary = p.ingest([Path(path)], run_id="r1")
    except Exception as e:  # noqa
        summary, err = None, e
    return p, summary, err


def report(p):
    q = p.db.query
    out = {"files": q("SELECT file_name,status,parser,sniff_score FROM files"),
           "tables": q("SELECT table_id,parser,page FROM raw_tables"),
           "maps": [], "records": q("SELECT template_id,count(*) n FROM source_records GROUP BY 1"),
           "shifts": q("SELECT count(*) n FROM shifts_silver")[0]["n"],
           "tasks": q("SELECT kind,status FROM agent_tasks"),
           "issues": q("SELECT check_id,severity,count(*) n FROM issues GROUP BY 1,2")}
    for r in q("SELECT * FROM mappings"):
        out["maps"].append({"tpl": r["template_id"], "conf": round(r["confidence"], 3), "status": r["status"],
                            "matches": r["matches"], "missing": r["missing_required"]})
    return out


def truth_rows(truth):
    return [r for p in truth["pages"] for r in p["rows"]]


def extracted_rows(p):
    from sot.store import repo
    rows, meta = [], []
    for r in p.db.query("SELECT table_id, page FROM raw_tables ORDER BY page, table_id"):
        t = repo.load_raw_table(p.db, r["table_id"])
        rows += [list(x) for x in t.df.drop("_src_row").rows()]
        meta.append((t.page, t.extraction.method, round(t.extraction.score, 3), t.header))
    return rows, meta


def cell_acc(got, truth):
    total = max(len(got), len(truth)) * 9
    ok = sum(a == b for g, t in zip(got, truth) for a, b in zip(g, t))
    return ok / total


E1 = Path(__file__).parent.parent / "fixtures" / "example_e1"
E1_CSVS = [E1 / "hr_roster.csv", E1 / "payroll.csv", E1 / "licenses.csv"]


def ingest_with_anchors(pdf, runtime):
    """The schedule PDF plus the e1 CSVs (the week's date anchors). The e1 schedule itself is NOT ingested."""
    s = load_settings(runtime=Path(runtime))
    s.agents = "off"
    s.as_of = date(2026, 9, 21)
    p = Pipeline(s)
    err = None
    try:
        p.ingest([*E1_CSVS, Path(pdf)], run_id="r1")
    except Exception as e:  # noqa
        err = e
    return p, err


def shift_set(p):
    """{(staff name, iso date, token)} of the silver shifts of schedule records."""
    rows = p.db.query("SELECT s.work_date, s.token, r.raw FROM shifts_silver s JOIN source_records r USING (record_id) "
                      "WHERE r.template_id = 'schedule'")
    out = set()
    for r in rows:
        raw = json.loads(r["raw"]) if isinstance(r["raw"], str) else r["raw"]
        name = next((v for k, v in raw.items() if k.lower().startswith("staff")), None)
        out.add((name, str(r["work_date"]), r["token"]))
    return out


def truth_shifts(truth):
    days = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20"]
    return {(r[0], d, r[2 + i]) for r in truth_rows(truth) for i, d in enumerate(days) if r[2 + i] != "OFF"}
