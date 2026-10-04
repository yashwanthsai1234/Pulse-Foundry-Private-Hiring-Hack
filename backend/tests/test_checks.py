"""Check catalogue (one positive and one negative case per check), engine behaviour and example_e1 acceptance."""
import re
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from a5_e1 import example_e1, run_e1
from sot.checks.builtin import builtin_drafts
from sot.checks.engine import run_checks
from sot.core.models import Locator, SourceRecord
from sot.store.db import DB

AS_OF = date(2026, 9, 21)
LOC = {"file_id": "f", "file_name": "f.csv", "row": 1}
MON = date(2026, 9, 14)


# ---------- hand-made gold rows ----------
def person(db, pid="P1", has_hr=True, role="RN", home="FAC-BAY"):
    db.insert("persons", [{"person_id": pid, "employee_id": pid[1:], "has_hr": has_hr, "display_name": f"Name {pid}",
                           "role": role, "home_facility_id": home}])


def cred(db, cid="RN-1", holder="P1", ctype="RN", expires=MON, htype="person", name="Name P1"):
    db.insert("credentials", [{"credential_id": cid, "holder_type": htype, "holder_id": holder, "holder_name": name,
                               "credential_type": ctype, "number": cid, "expires_on": expires,
                               "last_verified": MON - timedelta(days=10)}])


def shift(db, sid, day=MON, pid="P1", fac="FAC-BAY", role="RN", start=7, end=15):
    t0 = datetime.combine(day, datetime.min.time()) + timedelta(hours=start)
    t1 = datetime.combine(day, datetime.min.time()) + timedelta(hours=end)
    db.insert("shifts", [{"shift_id": sid, "person_id": pid, "facility_id": fac, "role": role, "work_date": day,
                          "start_ts": t0, "end_ts": t1, "hours": float(end - start), "record_id": "sch:1", "loc": LOC}])


def pay(db, pid="P1", hours=40.0, role="RN", rid="pay:1"):
    db.insert("pay_periods", [{"pay_id": rid, "person_id": pid, "facility_id": "FAC-BAY", "role": role,
                               "period_start": MON, "period_end": MON + timedelta(days=6), "hours_paid": hours,
                               "record_id": rid}])


def record(db, rid, template, fields):
    db.insert("source_records", [{"record_id": rid, "table_id": "t", "template_id": template, "entity": "x",
                                  "fields": fields, "raw": {}, "loc": LOC, "parse_issues": []}])


def week(db, pid="P1", role="RN", fac="FAC-BAY", n=7, hours=(7, 15)):
    for i in range(n):
        shift(db, f"{pid}-{role}-{i}", MON + timedelta(days=i), pid, fac, role, *hours)


# ---------- scenarios: (positive, negative) per check ----------
def lic_worked_pos(db):
    person(db), cred(db, expires=MON - timedelta(days=1)), shift(db, "s1")


def lic_worked_neg(db):
    person(db), cred(db, expires=MON + timedelta(days=1)), shift(db, "s1")


def lic_worked_other_valid(db):  # an expired CNA license is covered by a valid RN license (RN scope includes CNA)
    person(db), cred(db, "CNA-1", ctype="CNA", expires=MON - timedelta(days=1)), cred(db, "RN-1", expires=AS_OF)
    shift(db, "s1", role="CNA")


def cov_pos(db):
    person(db, role="CNA"), week(db, role="CNA")


def cov_neg(db):
    person(db), week(db)


def cov_overnight_merge(db):  # 4p-11p + 11p-7a: Monday is covered 16:00-24:00 only because the spans touch
    person(db), shift(db, "a", start=16, end=23), shift(db, "b", start=23, end=31)


def dup_license(same_person):
    def setup(db):
        person(db, "P1"), person(db, "P2")
        record(db, "r1", "hr_roster", {"credential.number": "RN-1"})
        record(db, "r2", "license", {"credential.number": "RN-1"})
        db.insert("person_records", [{"person_id": "P1", "record_id": "r1"},
                                     {"person_id": "P1" if same_person else "P2", "record_id": "r2"}])
    return setup


def paid(hours):
    def setup(db):
        person(db), pay(db, hours=hours)
        for i in range(5):
            shift(db, f"s{i}", MON + timedelta(days=i))
    return setup


def overlap(second_start):
    def setup(db):
        person(db), shift(db, "a", fac="FAC-BAY", start=7, end=15), shift(db, "b", MON, fac="FAC-RVD", start=second_start, end=second_start + 8)
    return setup


def daily(n):
    def setup(db):
        person(db)
        for i in range(n):
            shift(db, f"s{i}", start=0, end=8)
    return setup


def expiring(days):
    def setup(db):
        person(db), cred(db, expires=AS_OF + timedelta(days=days))
    return setup


def expired_not_working(worked):
    def setup(db):
        person(db), cred(db, expires=AS_OF - timedelta(days=5))
        if worked:
            shift(db, "s1", AS_OF - timedelta(days=2))
    return setup


def none_for_role(has_cred):
    def setup(db):
        person(db), shift(db, "s1")
        if has_cred:
            cred(db, expires=AS_OF)
    return setup


def scope(ctype):
    def setup(db):
        person(db), cred(db, "X-1", ctype=ctype, expires=AS_OF + timedelta(days=500)), shift(db, "s1", role="RN")
    return setup


def sched_no_hr(has_hr):
    return lambda db: (person(db, has_hr=has_hr), shift(db, "s1"))


def pay_no_hr(has_hr):
    return lambda db: (person(db, has_hr=has_hr), pay(db))


def fac(fac_id):
    return lambda db: (person(db), shift(db, "s1", fac=fac_id))


def role_mismatch(role):
    return lambda db: (person(db), pay(db, role=role))


def hr_dup(second_phone):
    def setup(db):
        record(db, "h1", "hr_roster", {"person.employee_id": "E1", "person.phone": "1"})
        record(db, "h2", "hr_roster", {"person.employee_id": "E1", "person.phone": second_phone})
    return setup


def pay_rows(second_id, second_hours):
    def setup(db):
        person(db)
        for rid, pid, hours in (("p1", "P-1", 36.0), ("p2", second_id, second_hours)):
            record(db, rid, "payroll", {"pay.payroll_id": pid, "person.facility": "FAC-BAY", "pay.hours_paid": hours,
                                        "pay.period_start": "2026-09-14", "pay.period_end": "2026-09-20"})
            db.insert("person_records", [{"person_id": "P1", "record_id": rid}])
    return setup


def periods(*spans):
    def setup(db):
        person(db)
        for i, (a, b) in enumerate(spans):
            db.insert("pay_periods", [{"pay_id": f"pp{i}", "person_id": "P1", "facility_id": "FAC-BAY", "role": "RN",
                                       "period_start": MON + timedelta(days=a), "period_end": MON + timedelta(days=b),
                                       "hours_paid": 40.0, "record_id": f"pp{i}"}])
    return setup


def hours(value, days=6):
    def setup(db):
        person(db), db.insert("pay_periods", [{"pay_id": "pp", "person_id": "P1", "facility_id": "FAC-BAY", "role": "RN",
                                               "period_start": MON, "period_end": MON + timedelta(days=days),
                                               "hours_paid": value, "record_id": "pp"}])
    return setup


def hired(hire, shift_day=MON):
    def setup(db):
        person(db), db.execute("UPDATE persons SET hire_date = ?", [hire]), shift(db, "s1", shift_day)
    return setup


def typed(number, ctype):
    def setup(db):
        person(db), cred(db, number, ctype=ctype, expires=AS_OF)
    return setup


CASES = {
    "LIC-WORKED-EXPIRED": (lic_worked_pos, lic_worked_neg),
    "LIC-NONE-FOR-ROLE": (none_for_role(False), none_for_role(True)),
    "LIC-SCOPE": (scope("CNA"), scope("RN")),
    "COV-RN-DAILY": (cov_pos, cov_neg),
    "ID-DUP-LICENSE": (dup_license(False), dup_license(True)),
    "HRS-PAID-VS-SCHED": (paid(48.0), paid(41.0)),
    "PAY-NO-HR": (pay_no_hr(False), pay_no_hr(True)),
    "SHIFT-OVERLAP": (overlap(10), overlap(15)),
    "HRS-DAILY-EXCESS": (daily(3), daily(2)),
    "LIC-EXPIRING": (expiring(10), expiring(90)),
    "LIC-EXPIRED-NOT-WORKING": (expired_not_working(False), expired_not_working(True)),
    "SCHED-NO-HR": (sched_no_hr(False), sched_no_hr(True)),
    "FAC-MISMATCH": (fac("FAC-RVD"), fac("FAC-BAY")),
    "ROLE-MISMATCH": (role_mismatch("CNA"), role_mismatch("RN")),
    "HR-DUP-ROW": (hr_dup("2"), hr_dup("1")),
    "PAY-DUPLICATE": (pay_rows("P-2", 36.0), pay_rows("P-1", 36.0)),  # new id = paid twice; same row twice = a copy
    "PAY-PERIOD-OVERLAP": (periods((0, 6), (3, 9)), periods((0, 6), (7, 13))),
    "PAY-PERIOD-INVALID": (periods((6, 0)), periods((0, 6))),
    "PAY-HOURS-INVALID": (hours(None), hours(40.0)),
    "LIC-EXPIRY-MISSING": (lambda db: (person(db), cred(db, expires=None)), lambda db: (person(db), cred(db))),
    "HR-HIRE-DATE": (hired(MON + timedelta(days=20), MON + timedelta(days=21)), hired(MON - timedelta(days=30))),
    "LIC-TYPE-MISMATCH": (typed("CNA-771045", "RN"), typed("CNA-771045", "CNA")),
}


def fired(db, pack, settings, check_id):
    issues = run_checks(db, pack, replace(settings, as_of=AS_OF), "r1", [])
    assert not [i for i in issues if i.check_id == "CHECK-ERROR"], [i.message for i in issues]
    return [i for i in issues if i.check_id == check_id]


@pytest.mark.parametrize("check_id", CASES)
def test_positive_and_negative(db, pack, settings, check_id):
    positive, negative = CASES[check_id]
    positive(db)
    assert fired(db, pack, settings, check_id), "positive case did not fire"
    clean = DB(":memory:")
    negative(clean)
    assert fired(clean, pack, settings, check_id) == []


def test_every_catalogue_sql_and_py_check_has_cases(pack):
    ids = {p.stem for p in pack.checks_dir.iterdir() if p.suffix in (".sql", ".py")}
    assert ids == set(CASES)


def test_lic_worked_expired_ignores_expired_license_covered_by_valid_one(db, pack, settings):
    lic_worked_other_valid(db)
    assert fired(db, pack, settings, "LIC-WORKED-EXPIRED") == []


def test_cov_rn_daily_merges_overnight_spans(db, pack, settings):
    cov_overnight_merge(db)
    (issue,) = fired(db, pack, settings, "COV-RN-DAILY")
    assert "2026-09-14" not in issue.message and "2026-09-15" in issue.message


def test_lic_expiring_severity_bands(db, pack, settings):
    person(db), cred(db, "RN-1", expires=AS_OF + timedelta(days=10)), cred(db, "RN-2", expires=AS_OF + timedelta(days=45))
    assert sorted(i.severity for i in fired(db, pack, settings, "LIC-EXPIRING")) == ["HIGH", "MEDIUM"]


def test_lic_expiring_covers_organizations(db, pack, settings):
    cred(db, "ORG:linen:COI", holder="ORG:linen:COI", ctype="COI", htype="organization", expires=AS_OF + timedelta(days=12))
    (issue,) = fired(db, pack, settings, "LIC-EXPIRING")
    assert issue.severity == "HIGH" and issue.entity_ids == ["ORG:linen:COI"]


# ---------- builtin drafts ----------
def rec(issues):
    return SourceRecord(record_id="t:1:2", template_id="hr_roster", entity="person", fields={}, raw={},
                        loc=Locator(**LOC), parse_issues=issues)


def test_builtin_parse_and_legend_issues():
    drafts = builtin_drafts([rec(["date_ambiguous:person.hire_date", "legend_mismatch:7a-3p", "weird_thing:x"])], [])
    assert [(d.check_id, d.severity) for d in drafts] == [
        ("PARSE-DATE-AMBIGUOUS", "MEDIUM"), ("PARSE-WEIRD-THING", "LOW"), ("LEGEND-MISMATCH", "MEDIUM")]
    assert builtin_drafts([rec([])], []) == []


# ---------- engine ----------
def test_failing_check_becomes_check_error(db, pack, settings, tmp_path):
    bad = tmp_path / "pack"
    (bad / "checks").mkdir(parents=True)
    (bad / "checks" / "BAD.sql").write_text("-- id: BAD\n-- severity: LOW\n-- title: \"x\"\nSELECT * FROM no_such_table")
    issues = run_checks(db, pack.model_copy(update={'dir': bad}), settings, "r1", [])
    assert [(i.check_id, i.severity, i.entity_ids) for i in issues] == [("CHECK-ERROR", "HIGH", ["BAD"])]


def test_merge_keeps_status_and_deactivates_vanished_issues(db, pack, settings):
    lic_worked_pos(db)
    (first,) = fired(db, pack, settings, "LIC-WORKED-EXPIRED")
    db.execute("UPDATE issues SET status='acknowledged', owner='dana', note='called board'")
    (second,) = [i for i in run_checks(db, pack, replace(settings, as_of=AS_OF), "r2", []) if i.check_id == "LIC-WORKED-EXPIRED"]
    assert second.fingerprint == first.fingerprint
    assert (second.status, second.owner, second.note) == ("acknowledged", "dana", "called board")
    assert (second.first_seen_run, second.last_seen_run) == ("r1", "r2")
    db.execute("DELETE FROM shifts")
    assert fired(db, pack, settings, "LIC-WORKED-EXPIRED") == []
    assert db.query("SELECT active, status FROM issues WHERE check_id='LIC-WORKED-EXPIRED'") == [
        {"active": False, "status": "acknowledged"}]


def test_issues_are_sorted_by_severity(db, pack, settings):
    lic_worked_pos(db), db.execute("DELETE FROM shifts"), shift(db, "s1"), pay(db, hours=60)
    issues = run_checks(db, pack, replace(settings, as_of=AS_OF), "r1", [])
    order = [i.severity for i in issues]
    assert order == sorted(order, key=["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].index)


# ---------- acceptance: example_e1 ----------
def test_example_e1_issues_match_expected(db, pack, settings, e1_expected):
    issues, _ = run_e1(db, pack, settings)
    got = sorted((i.check_id, i.severity) for i in issues)
    want = sorted((e["check_id"], e["severity"]) for e in e1_expected["issues"])
    assert got == want
    by = {(i.check_id, i.facility_id or ",".join(i.entity_ids)): i for i in issues}
    by[("LIC-WORKED-EXPIRED", "P-E202")] = next(i for i in issues if i.check_id == "LIC-WORKED-EXPIRED")
    for e in e1_expected["issues"]:
        if "entity_ids" in e:
            assert any(i.check_id == e["check_id"] and i.entity_ids == e["entity_ids"] for i in issues), e
        if "facility_id" in e:
            assert (e["check_id"], e["facility_id"]) in by
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", by[("LIC-WORKED-EXPIRED", "P-E202")].message)
    assert dates[1:] == e1_expected["lic_worked_expired_dates"]
    rvd = re.findall(r"\d{4}-\d{2}-\d{2}", by[("COV-RN-DAILY", "FAC-RVD")].message)
    assert len(rvd) == e1_expected["cov_rn_missing_days"]["FAC-RVD"]
    assert re.findall(r"\d{4}-\d{2}-\d{2}", by[("COV-RN-DAILY", "FAC-BAY")].message) == e1_expected["cov_rn_missing_days"]["FAC-BAY"]
    assert not [i for i in issues if i.severity in ("CRITICAL", "HIGH")
                and (i.check_id, i.severity) not in {(e["check_id"], e["severity"]) for e in e1_expected["issues"]}]


def test_csv_record_evidence_carries_raw_row_and_pdf_cells_do_not(db, pack, settings):
    issues, _ = run_e1(db, pack, settings)
    conflict = next(i for i in issues if i.check_id == "SRC-CONFLICT")
    assert all(e.raw for e in conflict.evidence)  # CSV claims carry their source row
    fuzzy = next(i for i in issues if i.check_id == "ID-FUZZY-LINK")
    assert sorted((e.raw or {}).get("x", "pdf") for e in fuzzy.evidence if e.kind == "cell") == ["3", "pdf"]


def test_example_e1_evidence_has_locators_and_golden_flag(db, pack, settings):
    issues, _ = run_e1(db, pack, settings)
    lic = next(i for i in issues if i.check_id == "LIC-WORKED-EXPIRED")
    shifts = [e for e in lic.evidence if e.label.startswith("shift")]
    assert len(shifts) == 4 and all(e.loc.bbox and e.loc.page == 1 for e in shifts)
    claims = [e for e in lic.evidence if e.kind == "claim"]
    assert {e.is_golden for e in claims} == {True, False}


# ---------- FX4 additions ----------
@pytest.mark.parametrize(("setup", "n"), [
    (pay_rows("P-1", 20.0), 1),  # same payroll id, different hours
    (pay_rows("P-1", 36.0), 0),
])
def test_pay_duplicate_only_for_conflicting_rows(db, pack, settings, setup, n):
    setup(db)
    assert len(fired(db, pack, settings, "PAY-DUPLICATE")) == n


@pytest.mark.parametrize(("value", "days", "bad"), [(-8.0, 6, True), (101.0, 6, True), (100.0, 6, False), (0.0, 6, False),
                                                  (150.0, 13, False), (201.0, 13, True)])
def test_pay_hours_invalid_bounds(db, pack, settings, value, days, bad):
    hours(value, days)(db)
    assert bool(fired(db, pack, settings, "PAY-HOURS-INVALID")) == bad


def test_pay_period_invalid_covers_reversed_and_month_long(db, pack, settings):
    periods((6, 0), (0, 30))(db)
    assert len(fired(db, pack, settings, "PAY-PERIOD-INVALID")) == 2


def test_hire_date_in_the_future_and_mid_period_hire(db, pack, settings):
    hired(AS_OF + timedelta(days=3), AS_OF + timedelta(days=4))(db)
    (issue,) = fired(db, pack, settings, "HR-HIRE-DATE")
    assert "future" in issue.message
    clean = DB(":memory:")
    hired(MON + timedelta(days=2), MON + timedelta(days=2))(clean)  # hired on the first shift day
    assert fired(clean, pack, settings, "HR-HIRE-DATE") == []


def test_expiry_missing_severity_is_high(db, pack, settings):
    person(db), cred(db, expires=None)
    assert [i.severity for i in fired(db, pack, settings, "LIC-EXPIRY-MISSING")] == ["HIGH"]
