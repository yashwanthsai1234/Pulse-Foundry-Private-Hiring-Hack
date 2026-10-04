"""Hand-built example_e1 pipeline inputs (silver + resolve output) for the A5 tests, per TASKGRAPH §4 conventions."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time

from sot.checks.builtin import builtin_drafts
from sot.checks.engine import run_checks
from sot.core.models import FileRef, Link, Locator, Person, PersonKey, ShiftRecord, SourceRecord
from sot.store import repo
from sot.truth.claims import build_claims
from sot.truth.gold import write_gold
from sot.truth.survivorship import survive

FILES = {n: FileRef(file_id=n * 3, file_name=f"{n}.csv", path=f"/x/{n}", size=1, received_at=datetime(2026, 9, 21))
         for n in ("hr_roster", "payroll", "licenses", "schedule")}


def _loc(file: str, row: int, **kw) -> Locator:
    return Locator(file_id=FILES[file].file_id, file_name=FILES[file].file_name, row=row, **kw)


def _rec(rid, template, entity, file, row, fields, display, **kw) -> SourceRecord:
    return SourceRecord(record_id=rid, template_id=template, entity=entity, fields=fields, raw={"x": str(row)},
                        person_key=PersonKey(display=display), loc=_loc(file, row, **kw))


def example_e1():
    records = [
        _rec("hr:2", "hr_roster", "person", "hr_roster", 2, {
            "person.employee_id": "E201", "person.given_name": "Sofia", "person.family_name": "Reyes",
            "person.role": "RN", "person.facility": "FAC-BAY", "person.phone": "+17185550201",
            "credential.number": "RN-551203", "credential.expires_on": "2027-05-31", "person.hire_date": "2020-03-02"},
             "Sofia Reyes"),
        _rec("hr:3", "hr_roster", "person", "hr_roster", 3, {
            "person.employee_id": "E202", "person.given_name": "Marcus", "person.family_name": "Bell",
            "person.role": "CNA", "person.facility": "FAC-RVD", "person.phone": "+13475550202",
            "credential.number": "CNA-771045", "credential.expires_on": "2026-12-31", "person.hire_date": "2022-09-12"},
             "Marcus Bell"),
        _rec("lic:2", "license", "credential", "licenses", 2, {
            "credential.number": "RN-551203", "person.full_name": "REYES, SOFIA", "credential.type": "RN",
            "credential.expires_on": "2027-05-31", "credential.last_verified": "2026-09-01"}, "REYES, SOFIA"),
        _rec("lic:3", "license", "credential", "licenses", 3, {
            "credential.number": "CNA-771045", "person.full_name": "BELL, MARCUS", "credential.type": "CNA",
            "credential.expires_on": "2026-09-15", "credential.last_verified": "2026-09-01"}, "BELL, MARCUS"),
        _rec("pay:2", "payroll", "pay_period", "payroll", 2, {
            "pay.payroll_id": "P-3001", "person.full_name": "REYES, SOFIA", "person.role": "RN",
            "person.facility": "FAC-BAY", "pay.period_start": "2026-09-14", "pay.period_end": "2026-09-20",
            "pay.hours_paid": 36.0}, "REYES, SOFIA"),
        _rec("pay:3", "payroll", "pay_period", "payroll", 3, {
            "pay.payroll_id": "P-3002", "person.full_name": "BELL, MARCUS", "person.role": "CNA",
            "person.facility": "FAC-RVD", "pay.period_start": "2026-09-14", "pay.period_end": "2026-09-20",
            "pay.hours_paid": 48.0}, "BELL, MARCUS"),
        _rec("sch:1", "schedule", "shift_grid", "schedule", 1, {
            "person.full_name": "Sofia Reyes", "person.role": "RN", "person.facility": "FAC-BAY"}, "Sofia Reyes",
             page=1, bbox=(10, 10, 60, 20)),
        _rec("sch:2", "schedule", "shift_grid", "schedule", 1, {
            "person.full_name": "Marc Bell", "person.role": "CNA", "person.facility": "FAC-RVD"}, "Marc Bell", page=2),
    ]
    tokens = {"7a-3p": (time(7), time(15), 8.0), "3p-11p": (time(15), time(23), 8.0), "7a-7p": (time(7), time(19), 12.0)}

    def shift(rid, fac, role, day, token):
        s, e, h = tokens[token]
        return ShiftRecord(shift_id=f"{rid}:2026-09-{day}", record_id=rid, facility_id=fac, role=role,
                           work_date=date(2026, 9, day), token=token, start=s, end=e, hours=h, hours_source="both",
                           loc=_loc("schedule", 1, page=1, bbox=(100.0, 10.0, 150.0, 30.0)))

    shifts = [shift("sch:1", "FAC-BAY", "RN", d, t) for d, t in ((14, "7a-3p"), (15, "7a-3p"), (17, "7a-7p"), (19, "7a-3p"))]
    shifts += [shift("sch:2", "FAC-RVD", "CNA", d, "3p-11p") for d in (14, 16, 17, 18, 19)]
    persons = [Person(person_id="P-E201", record_ids=["hr:2", "lic:2", "pay:2", "sch:1"], employee_id="E201", has_hr=True),
               Person(person_id="P-E202", record_ids=["hr:3", "lic:3", "pay:3", "sch:2"], employee_id="E202", has_hr=True)]
    links = [Link(a="hr:3", b="sch:2", prob=0.99, weight=11.0, method="score",
                  reasons=["family exact (+6.0)", "given nickname (+3.5)", "role agree (+1.5)"])]
    return records, shifts, persons, links


def run_e1(db, pack, settings, run_id="run-1", as_of=date(2026, 9, 21)):
    """Truth + checks over the hand-built inputs; returns (active issues, golden)."""
    records, shifts, persons, links = example_e1()
    repo.save_records(db, records, shifts)
    claims = build_claims(records, persons)
    golden, drafts = survive(claims, pack)
    write_gold(db, records, shifts, persons, links, claims, golden)
    issues = run_checks(db, pack, replace(settings, as_of=as_of), run_id, builtin_drafts(records, links, persons) + drafts)
    return issues, golden
