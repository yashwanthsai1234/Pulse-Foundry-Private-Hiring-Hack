"""R1-04..R1-07: schedule year inference, ambiguous dates, fingerprints, entity ids."""
from datetime import date

from sot.normalize.silver import day_date
from tests.review.r1_support import HR, gold_issues, issues, run_pipeline


def test_weekday_header_year_not_pulled_to_old_hire_date():
    """Payroll weeks (Sun-Sat) around 2026-09-14 plus an HR hire date on 2020-09-14 (also a Monday)."""
    anchors = [date(2020, 9, 14), date(2026, 9, 13), date(2026, 9, 19)]
    assert day_date("Mon 09/14", anchors)[0] == date(2026, 9, 14)


def test_weekday_less_header_year_uses_the_recent_cluster_not_the_median_of_all_dates():
    """HR + licence file only: hire dates 2018-2021, expirations 2027-2028; the schedule is for the as-of year."""
    anchors = [date(2018, 1, 1), date(2019, 5, 5), date(2021, 3, 3), date(2027, 5, 31), date(2028, 1, 1)]
    got = day_date("09/14", anchors)[0]
    assert got is not None and got.year >= 2026


def test_single_us_style_date_in_iso_column_is_flagged_ambiguous(tmp_path):
    hr = (HR.splitlines()[0] + "\nE101,Ann,Lee,Registered Nurse,Harborview Bayside,718-555-0101,RN-123456,2027-05-31,2020-03-02\n"
          "E102,Bo,Kim,Registered Nurse,Harborview Bayside,718-555-0102,RN-123457,2027-06-30,03/04/2021\n"
          "E103,Cy,Fox,Registered Nurse,Harborview Bayside,718-555-0103,RN-123458,2027-06-30,2021-04-05\n")
    pipe = run_pipeline(tmp_path, {"hr_roster.csv": hr})
    assert any(i.check_id == "PARSE-DATE-AMBIGUOUS" for i in issues(pipe))  # 03/04/2021 is 3 Mar or 4 Apr


def test_issue_fingerprint_survives_a_later_shift(tmp_path):
    """Triage state (status) belongs to the problem, not to the date span of the data seen so far."""
    from sot.checks.engine import run_checks
    from sot.config import load_settings
    from sot.core.pack import load_pack
    from sot.store import repo
    from sot.store.db import DB

    settings = load_settings(runtime=tmp_path / "rt")
    settings.as_of = date(2026, 9, 21)
    db = DB(":memory:")
    base = {"person_id": "P-E1", "facility_id": "FAC-RVD", "role": "RN", "start_ts": None, "end_ts": None, "hours": 8.0,
            "record_id": "r", "loc": {"file_id": "f", "file_name": "f"}}
    db.insert("persons", [{"person_id": "P-E1", "employee_id": "E1", "has_hr": True, "display_name": "Pat Doe", "role": "RN",
                           "home_facility_id": "FAC-BAY", "phone": None, "hire_date": None}])
    db.insert("shifts", [{**base, "shift_id": "s1", "work_date": date(2026, 9, 14)}])
    pack = load_pack(settings.pack_dir)
    run_checks(db, pack, settings, "r1", [])
    (fm,) = [i for i in repo.load_issues(db) if i.check_id == "FAC-MISMATCH"]
    db.execute("UPDATE issues SET status = 'false_positive' WHERE fingerprint = ?", [fm.fingerprint])
    db.insert("shifts", [{**base, "shift_id": "s2", "work_date": date(2026, 9, 21)}])  # next week's schedule arrives
    run_checks(db, pack, settings, "r2", [])
    (fm2,) = [i for i in repo.load_issues(db) if i.check_id == "FAC-MISMATCH"]
    assert fm2.status == "false_positive"


def test_src_conflict_names_the_person_not_only_the_licence_number(tmp_path):
    from tests.conftest import FIXTURES

    e1 = FIXTURES / "example_e1"
    pipe = run_pipeline(tmp_path, {n: (e1 / n).read_bytes() for n in ("hr_roster.csv", "licenses.csv")})
    (c,) = [i for i in issues(pipe) if i.check_id == "SRC-CONFLICT"]
    assert any(e.startswith("P-") for e in c.entity_ids)  # the UI joins issues to people by person id
