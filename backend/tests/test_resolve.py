import csv
import json
import random
import time

import pytest

from sot.core.models import Link, Locator, SourceRecord
from sot.normalize.names import parse_person_name, person_key_from_parts
from sot.resolve.blocking import block
from sot.resolve.resolver import resolve_all

FAC = {"Harborview Bayside": "FAC-BAY", "Harborview Riverdale": "FAC-RVD", "BYS": "FAC-BAY", "RVD": "FAC-RVD"}
ROLE = {"Registered Nurse": "RN", "Certified Nursing Assistant": "CNA"}
LOC = Locator(file_id="f", file_name="f.csv")


def rec(table, n, template, fields, key):
    entity = {"hr_roster": "person", "license": "credential", "payroll": "pay_period", "schedule": "shift_grid"}.get(template, "credential")
    return SourceRecord(record_id=f"{table}:{n}", template_id=template, entity=entity, fields=fields, raw={}, person_key=key, loc=LOC)


class Build:
    def __init__(self, nick):
        self.nick = nick

    def hr(self, n, emp, given, family, role, fac, number=None, table="hr"):
        f = {"person.employee_id": emp, "person.given_name": given, "person.family_name": family, "person.role": role, "person.facility": fac}
        if number:
            f["credential.number"] = number
        return rec(table, n, "hr_roster", f, person_key_from_parts(given, family, self.nick))

    def lic(self, n, name, number, typ, table="lic"):
        f = {"person.full_name": name, "credential.number": number, "credential.type": typ}
        return rec(table, n, "license", f, parse_person_name(name, self.nick))

    def pay(self, n, name, role, fac, table="pay"):
        f = {"person.full_name": name, "person.role": role, "person.facility": fac}
        return rec(table, n, "payroll", f, parse_person_name(name, self.nick))

    def sch(self, n, name, role, fac, table="sch"):
        f = {"person.full_name": name, "person.role": role}
        if fac:
            f["person.facility"] = fac
        return rec(table, n, "schedule", f, parse_person_name(name, self.nick))


@pytest.fixture
def b(pack):
    return Build(pack.nicknames)


def group_of(result, record_id):
    return next(p for p in result.persons if record_id in p.record_ids)


def check_ids(result):
    return [d.check_id for d in result.drafts]


def test_example_e1(e1_dir, pack, settings, b):
    recs = []
    for i, r in enumerate(csv.DictReader((e1_dir / "hr_roster.csv").open()), 1):
        recs.append(b.hr(i, r["employee_id"], r["first_name"], r["last_name"], ROLE[r["job_title"]], FAC[r["facility"]], r["license_number"]))
    for i, r in enumerate(csv.DictReader((e1_dir / "licenses.csv").open()), 1):
        recs.append(b.lic(i, r["name_on_license"], r["license_number"], r["license_type"]))
    for i, r in enumerate(csv.DictReader((e1_dir / "payroll.csv").open()), 1):
        recs.append(b.pay(i, r["employee_name"], r["job_code"], FAC[r["facility_code"]]))
    for i, page in enumerate(json.loads((e1_dir / "schedule.json").read_text())["pages"], 1):
        for r in page["rows"]:
            recs.append(b.sch(i, r[0], r[1], FAC[page["title"]]))
    res = resolve_all(recs, pack, settings)
    assert {p.person_id: len(p.record_ids) for p in res.persons} == {"P-E201": 4, "P-E202": 4}
    assert all(p.has_hr for p in res.persons)
    marc = next(link for link in res.links if "sch:2" in (link.a, link.b) and "hr:2" in (link.a, link.b))
    assert marc.prob >= 0.95 and marc.method == "score"
    assert any("nickname" in r for r in marc.reasons)
    assert any(r.startswith("family exact (+6.0)") for r in marc.reasons)
    assert any(link.method == "key" and link.prob == 1.0 for link in res.links)
    assert res.gray_pairs == [] and res.drafts == []


def test_two_bells_schedule_initial_links_to_maria_only(pack, settings, b):
    recs = [
        b.hr(1, "E1", "Marcus", "Bell", "CNA", "FAC-BAY"),
        b.hr(2, "E2", "Maria", "Bell", "RN", "FAC-BAY"),
        b.sch(1, "M. Bell", "RN", "FAC-BAY"),
    ]
    res = resolve_all(recs, pack, settings)
    assert "hr:2" in group_of(res, "sch:1").record_ids
    assert "hr:1" not in group_of(res, "sch:1").record_ids


def test_maiden_name_on_license_links_by_number_with_info_draft(pack, settings, b):
    recs = [
        b.hr(1, "E3", "Dana", "Whitfield", "RN", "FAC-BAY", "RN-100200"),
        b.lic(1, "HARRIS, DANA", "RN-100200", "RN"),
    ]
    res = resolve_all(recs, pack, settings)
    assert [p.person_id for p in res.persons] == ["P-E3"]
    assert res.links[0].method == "key" and res.links[0].prob == 1.0
    draft = next(d for d in res.drafts if d.check_id == "ID-NAME-DIFFERS-ON-LICENSE")
    assert draft.severity == "INFO" and draft.entity_ids == ["P-E3"]


def test_license_number_formatting_is_normalized(pack, settings, b):
    recs = [b.hr(1, "E3", "Dana", "Harris", "RN", "FAC-BAY", "RN-100200"), b.lic(1, "harris, dana", "rn 100200", "RN")]
    assert len(resolve_all(recs, pack, settings).persons) == 1


def test_chain_that_would_merge_two_employees_is_blocked(pack, settings, b):
    recs = [
        b.hr(1, "E401", "Marcus", "Bell", "CNA", "FAC-BAY", "CNA-1"),
        b.hr(2, "E402", "Marcus", "Bell", "CNA", "FAC-BAY", "CNA-2"),
        b.lic(1, "BELL, MARCUS", "CNA-1", "CNA"),
        b.lic(2, "BELL, MARCUS", "CNA-2", "CNA"),
        b.pay(1, "BELL, MARCUS", "CNA", "FAC-BAY"),
    ]
    res = resolve_all(recs, pack, settings)
    assert {"P-E401", "P-E402"} <= {p.person_id for p in res.persons}
    assert group_of(res, "hr:1") is not group_of(res, "hr:2")
    conflict = next(d for d in res.drafts if d.check_id == "ID-CONFLICT")
    assert conflict.severity == "HIGH" and set(conflict.entity_ids) == {"P-E401", "P-E402"}
    assert "ID-AMBIGUOUS" in check_ids(res)


def test_distinct_license_numbers_of_same_type_never_merge(pack, settings, b):
    recs = [b.lic(1, "BELL, MARCUS", "CNA-1", "CNA", table="l1"), b.lic(1, "BELL, MARCUS", "CNA-2", "CNA", table="l2")]
    res = resolve_all(recs, pack, settings)
    assert len(res.persons) == 2 and "ID-CONFLICT" in check_ids(res)


def test_gray_pair_is_reported_not_linked(pack, settings, b):
    recs = [b.hr(1, "E1", "Marcus", "Bell", "CNA", "FAC-BAY"), b.sch(1, "M. Bell", "CNA", None)]
    res = resolve_all(recs, pack, settings)
    assert len(res.persons) == 2 and res.links == []
    assert len(res.gray_pairs) == 1 and settings["link.gray"] <= res.gray_pairs[0].prob < settings["link.auto"]
    draft = next(d for d in res.drafts if d.check_id == "ID-GRAY-PAIR")
    assert draft.severity == "INFO" and draft.evidence_refs["record_ids"] == ["hr:1", "sch:1"]


def test_extra_link_joins_gray_pair_but_not_two_employees(pack, settings, b):
    recs = [b.hr(1, "E1", "Marcus", "Bell", "CNA", "FAC-BAY"), b.hr(2, "E2", "Maria", "Bell", "RN", "FAC-BAY", table="hr2"), b.sch(1, "M. Bell", "CNA", None)]
    human = [Link(a="hr:1", b="sch:1", prob=1.0, weight=20.0, method="human", reasons=["accepted"]),
             Link(a="hr:1", b="hr2:2", prob=1.0, weight=20.0, method="human", reasons=["bad"])]
    res = resolve_all(recs, pack, settings, extra_links=human)
    assert group_of(res, "sch:1") is group_of(res, "hr:1")
    assert res.gray_pairs == []
    assert group_of(res, "hr:1") is not group_of(res, "hr2:2")
    assert [x.method for x in res.links] == ["human"] and "ID-CONFLICT" in check_ids(res)


def test_payroll_person_not_in_hr_gets_x_id(pack, settings, b):
    recs = [b.hr(1, "E1", "Sofia", "Reyes", "RN", "FAC-BAY"), b.pay(1, "PARK, JIN", "LPN", "FAC-RVD"), b.pay(2, "PARK, JIN", "LPN", "FAC-RVD", table="pay2")]
    res = resolve_all(recs, pack, settings)
    x = next(p for p in res.persons if not p.has_hr)
    assert x.person_id.startswith("P-X") and x.employee_id is None and sorted(x.record_ids) == ["pay2:2", "pay:1"]


def test_same_table_records_are_never_paired(pack, settings, b):
    recs = [b.pay(1, "PARK, JIN", "LPN", "FAC-RVD"), b.pay(2, "PARK, JIN", "LPN", "FAC-RVD")]
    assert len(resolve_all(recs, pack, settings).persons) == 2


def test_one_to_one_guard_keeps_clearly_better_hr(pack, settings, b):
    recs = [
        b.hr(1, "E1", "Maria", "Bell", "RN", "FAC-BAY"),
        b.hr(2, "E2", "Maria", "Bell", "RN", "FAC-RVD", table="hr2"),
        b.pay(1, "BELL, MARIA", "RN", "FAC-BAY"),
    ]
    res = resolve_all(recs, pack, settings)
    assert group_of(res, "pay:1").person_id == "P-E1"
    assert "ID-AMBIGUOUS" not in check_ids(res)


def test_one_to_one_guard_near_tie_is_ambiguous(pack, settings, b):
    recs = [
        b.hr(1, "E1", "Maria", "Bell", "RN", "FAC-BAY"),
        b.hr(2, "E2", "Maria", "Bell", "RN", "FAC-BAY", table="hr2"),
        b.pay(1, "BELL, MARIA", "RN", "FAC-BAY"),
    ]
    res = resolve_all(recs, pack, settings)
    assert len(group_of(res, "pay:1").record_ids) == 1
    amb = next(d for d in res.drafts if d.check_id == "ID-AMBIGUOUS")
    assert amb.severity == "MEDIUM"


def test_vendor_credentials_are_not_people(pack, settings, b):
    vendor = rec("v", 1, "vendor_credential", {"org.name": "Bell Staffing", "credential.expires_on": "2027-01-01"}, parse_person_name("Bell Staffing", b.nick))
    res = resolve_all([vendor, b.hr(1, "E1", "Marcus", "Bell", "CNA", "FAC-BAY")], pack, settings)
    assert [p.person_id for p in res.persons] == ["P-E1"]


def test_records_without_names_or_ids_are_ignored(pack, settings, b):
    res = resolve_all([rec("pay", 1, "payroll", {"person.full_name": ""}, None)], pack, settings)
    assert res.persons == []


def synthetic(b, n_people, seed=1):
    rnd = random.Random(seed)
    firsts = ["marcus", "maria", "sofia", "john", "robert", "linda", "james", "susan", "david", "karen", "paul", "nancy", "tom", "alice", "peter", "grace"]
    lasts = [f"{a}{c}" for a in ["bel", "rey", "par", "kim", "ng", "ort", "wal", "hu", "sim", "tor"] for c in ["l", "es", "k", "son", "ez", "ley", "man", "ton", "ini", "berg"]]
    names = rnd.sample([(g, f) for g in firsts for f in lasts], n_people)  # unique names: truth is unambiguous
    recs, truth = [], {}
    for i, (g, f) in enumerate(names):
        fac = rnd.choice(["FAC-BAY", "FAC-RVD", "FAC-OAK"])
        role = rnd.choice(["RN", "CNA", "LPN"])
        emp, num = f"E{i:05d}", f"{role}-{i:06d}"
        rs = [b.hr(i, emp, g, f, role, fac, num), b.lic(i, f"{f.upper()}, {g.upper()}", num, role)]
        rs += [b.pay(i, f"{f.upper()}, {g.upper()}", role, fac, table=f"pay{k}") for k in range(2)]
        rs.append(b.sch(i, f"{g.title()[0]}. {f.title()}", role, fac, table=f"sch{i % 3}"))
        for r in rs:
            truth[r.record_id] = emp
        recs += rs
    return recs, truth


def test_scale_5000_records_under_5_seconds(pack, settings, b):
    recs, truth = synthetic(b, 1000)
    assert len(recs) == 5000
    t0 = time.perf_counter()
    res = resolve_all(recs, pack, settings)
    assert time.perf_counter() - t0 < 5.0
    wrong = [p for p in res.persons if len({truth[r] for r in p.record_ids}) > 1]
    assert not wrong


def test_oversized_bucket_is_split_by_facility(b):
    recs = [b.pay(i, "PARK, JIN", "LPN", "FAC-BAY" if i % 2 else "FAC-RVD", table=f"t{i}") for i in range(10)]
    assert len(block(recs, [["family3", "given_initial"]], cap=100)) == 45
    assert len(block(recs, [["family3", "given_initial"]], cap=5)) == 20
