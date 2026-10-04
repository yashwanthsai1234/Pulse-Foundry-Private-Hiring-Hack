"""End to end through the REAL pipeline (no fakes): PLAN §10 example -> issues + PBJ of expected.json."""
from datetime import date

import pytest

from sot.exports.pbj import build_pbj
from sot.pipeline.orchestrator import Pipeline
from sot.store import repo

FILES = ["hr_roster.csv", "payroll.csv", "licenses.csv", "schedule.pdf"]


@pytest.fixture
def run(settings, e1_dir, monkeypatch):
    settings.agents = "off"
    settings.as_of = date(2026, 9, 21)
    p = Pipeline(settings)
    summary = p.ingest([e1_dir / f for f in FILES], run_id="r1")
    return p, summary


def _active(p):
    return repo.load_issues(p.db)


def test_e1_persons_and_records(run):
    p, summary = run
    persons = {r["person_id"]: r for r in p.db.query("SELECT * FROM persons")}
    assert set(persons) == {"P-E201", "P-E202"}
    counts = {r["person_id"]: r["n"] for r in p.db.query(
        "SELECT person_id, count(*) n FROM person_records GROUP BY 1")}
    assert counts == {"P-E201": 4, "P-E202": 4}
    assert summary.persons == 2 and summary.quarantined == 0


def test_e1_expected_issues(run, e1_expected):
    p, _ = run
    issues = _active(p)
    got = {(i.check_id, i.severity, i.facility_id if i.check_id == "COV-RN-DAILY" else tuple(sorted(i.entity_ids)))
           for i in issues if i.severity in ("CRITICAL", "HIGH", "MEDIUM")}
    want = {(e["check_id"], e["severity"], e.get("facility_id") if e["check_id"] == "COV-RN-DAILY"
             else tuple(sorted(e.get("entity_ids", [])))) for e in e1_expected["issues"] if e["severity"] != "INFO"}
    assert got == want
    assert any(i.check_id == "ID-FUZZY-LINK" for i in issues)


def test_e1_pbj(run, e1_expected):
    p, _ = run
    df = build_pbj(p.db, p.pack, p.settings)
    rows = [{k: r[k] for k in ("employee_id", "work_date", "job_code", "hours", "status")}
            for r in df.sort(["employee_id", "work_date"]).iter_rows(named=True)]
    for r in rows:
        r["work_date"] = str(r["work_date"])
        r["job_code"] = int(r["job_code"])
    assert rows == e1_expected["pbj"]


def test_e1_evidence_has_pdf_cell_with_bbox(run):
    p, _ = run
    (lic,) = [i for i in _active(p) if i.check_id == "LIC-WORKED-EXPIRED"]
    cells = [e for e in lic.evidence if e.kind == "cell" and e.loc and e.loc.bbox]
    assert cells and all(e.loc.page == 2 for e in cells)


def test_reingest_is_idempotent(run, e1_dir):
    p, _ = run
    before = {i.fingerprint for i in _active(p)}
    n_records = p.db.query("SELECT count(*) n FROM source_records")[0]["n"]
    s2 = p.ingest([e1_dir / f for f in FILES], run_id="r2")
    assert s2.skipped == 4
    assert {i.fingerprint for i in _active(p)} == before
    assert p.db.query("SELECT count(*) n FROM source_records")[0]["n"] == n_records
