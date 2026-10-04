"""PBJ export and issues CSV on the hand-built example_e1 inputs."""
import csv
import io
from datetime import date

from a5_e1 import run_e1
from sot.exports.issues_csv import issues_csv
from sot.exports.pbj import build_pbj


def test_example_e1_pbj_matches_expected(db, pack, settings, e1_expected):
    run_e1(db, pack, settings)
    df = build_pbj(db, pack, settings)
    assert df.columns == pack.pbj["columns"]
    got = [{"employee_id": r["employee_id"], "work_date": r["work_date"].isoformat(), "job_code": r["job_code"],
            "hours": r["hours"], "status": r["status"]} for r in df.iter_rows(named=True)]
    assert got == e1_expected["pbj"]
    notes = {r["employee_id"]: r["note"] for r in df.iter_rows(named=True)}
    assert notes == {"E201": None, "E202": "paid 48, scheduled 40"}


def test_hours_are_never_redistributed(db, pack, settings):
    run_e1(db, pack, settings)
    df = build_pbj(db, pack, settings)
    assert df.filter(df["employee_id"] == "E202")["hours"].sum() == 40.0


def test_no_hr_job_code_and_missing_payroll_need_signoff(db, pack, settings):
    run_e1(db, pack, settings)
    db.execute("UPDATE persons SET has_hr = FALSE WHERE person_id = 'P-E201'")
    db.execute("DELETE FROM pay_periods WHERE person_id = 'P-E202'")
    db.execute("UPDATE persons SET role = 'DON' WHERE person_id = 'P-E202'")
    rows = build_pbj(db, pack, settings).to_dicts()
    e201 = {r["note"] for r in rows if r["employee_id"] == "E201"}
    e202 = {(r["job_code"], r["note"]) for r in rows if r["employee_id"] == "E202"}
    assert e201 == {"no HR record"} and e202 == {(None, "no PBJ job code for role DON")}
    assert {r["status"] for r in rows} == {"needs_signoff"}


def test_tolerance_allows_small_difference(db, pack, settings):
    run_e1(db, pack, settings)
    db.execute("UPDATE pay_periods SET hours_paid = 41 WHERE person_id = 'P-E202'")
    assert {r["status"] for r in build_pbj(db, pack, settings).to_dicts() if r["employee_id"] == "E202"} == {"ready"}


def test_empty_gold_gives_empty_frame(db, pack, settings):
    assert build_pbj(db, pack, settings).height == 0


def test_issues_csv_lists_active_issues(db, pack, settings):
    issues, _ = run_e1(db, pack, settings)
    rows = list(csv.DictReader(io.StringIO(issues_csv(db))))
    assert len(rows) == len(issues) == 6
    assert rows[0]["severity"] == "CRITICAL" and "P-E202" in "".join(r["entities"] for r in rows)
    assert "licenses.csv" in rows[0]["evidence"] or "schedule" in rows[0]["evidence"]


def test_overlapping_pay_periods_do_not_double_the_hours(db, pack, settings):
    run_e1(db, pack, settings)
    db.insert("pay_periods", [{"pay_id": "dup", "person_id": "P-E202", "facility_id": "FAC-RVD", "role": "CNA",
                               "period_start": date(2026, 9, 16), "period_end": date(2026, 9, 22), "hours_paid": 40.0,
                               "record_id": "dup"}])
    df = build_pbj(db, pack, settings)
    assert df.filter(df["employee_id"] == "E202")["hours"].sum() == 40.0
