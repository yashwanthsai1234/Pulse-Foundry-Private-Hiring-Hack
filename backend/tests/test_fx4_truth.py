"""FX4: claims, survivorship and gold never crash on messy data and never count one fact twice."""
from datetime import date, datetime, time

import pytest

from a5_e1 import example_e1
from sot.core.models import Claim, Locator, Person, ShiftRecord, SourceRecord
from sot.truth.claims import build_claims
from sot.truth.gold import write_gold
from sot.truth.survivorship import survive

OLD, NEW = datetime(2026, 9, 1), datetime(2026, 9, 20)


def loc(file_id="f1", row=1, name=None):
    return Locator(file_id=file_id, file_name=name or f"{file_id}.csv", row=row)


def files(db, **times):
    db.insert("files", [{"file_id": f, "file_name": f"{f}.csv", "received_at": t} for f, t in times.items()])


def pay_rec(rid, file_id="f1", pay_id="P-1", hours=36.0, start="2026-09-14", end="2026-09-20", fac="FAC-BAY"):
    fields = {"pay.payroll_id": pay_id, "person.facility": fac, "pay.period_start": start, "pay.period_end": end,
              "pay.hours_paid": hours}
    return SourceRecord(record_id=rid, template_id="payroll", entity="pay_period", loc=loc(file_id),
                        fields={k: v for k, v in fields.items() if v is not None}, raw={})


def shift_rec(rid, file_id, start=time(7), end=time(15), day=date(2026, 9, 14)):
    return ShiftRecord(shift_id=f"{rid}:{day}", record_id=rid, facility_id="FAC-BAY", role="RN", work_date=day,
                       token="7a-3p", start=start, end=end, hours=8.0, hours_source="both", loc=loc(file_id))


def person(*rids, pid="P-E1"):
    return Person(person_id=pid, record_ids=list(rids), employee_id=pid[2:], has_hr=True)


def gold(db, records, shifts=(), persons=()):
    write_gold(db, records, list(shifts), list(persons), [], [], [])


# ---- B-006: observed_at is the time the file arrived ------------------------------------------------------------
def test_claims_are_observed_when_their_file_arrived():
    records, _, persons, _ = example_e1()
    claims = build_claims(records, persons, {"hr_rosterhr_rosterhr_roster": OLD})
    by_template = {c.template_id: c.observed_at for c in claims}
    assert by_template["hr_roster"] == OLD and by_template["license"] != OLD


def test_record_offering_one_attribute_from_two_fields_makes_one_claim():
    r = SourceRecord(record_id="v:1", template_id="vendor_credential", entity="credential", loc=loc(), raw={},
                     fields={"org.name": "Linen", "credential.type": "COI", "credential.doc_type": "COI",
                             "credential.number": "POL-9"})
    claims = build_claims([r], [])
    assert len({c.claim_id for c in claims}) == len(claims)


# ---- RC15: the tie-break does not depend on claim or record ids -------------------------------------------------
def _claim(cid, rid, file_name, row, value):
    return Claim(claim_id=cid, entity_type="person", entity_id="P-E1", attribute="phone", value=value,
                 value_type="string", template_id="hr_roster", record_id=rid,
                 loc=Locator(file_id="x", file_name=file_name, row=row), observed_at=OLD)


@pytest.mark.parametrize("ids", [("a", "z"), ("z", "a")])
def test_equal_claims_tie_break_on_file_then_row_not_on_ids(pack, ids):
    first, second = _claim(ids[0], "r" + ids[0], "hr.csv", 2, "111"), _claim(ids[1], "r" + ids[1], "hr.csv", 3, "222")
    golden, _ = survive([second, first], pack)
    assert golden[0].value == "111"


# ---- B2-01 / RC7: duplicate keys never crash gold ---------------------------------------------------------------
def test_two_persons_with_one_id_become_one_person(db):
    gold(db, [], persons=[person("h:2"), person("h:3")])
    assert db.query("SELECT count(*) n FROM persons")[0]["n"] == 1
    assert sorted(r["record_id"] for r in db.query("SELECT record_id FROM person_records")) == ["h:2", "h:3"]


def test_payroll_row_exported_twice_is_one_pay_period(db):
    recs = [pay_rec("p:2"), pay_rec("p:3")]
    gold(db, recs, persons=[person("p:2", "p:3")])
    assert db.query("SELECT count(*) n FROM pay_periods")[0]["n"] == 1


def test_same_payroll_id_for_two_periods_keeps_both(db):
    recs = [pay_rec("p:2"), pay_rec("p:3", start="2026-09-21", end="2026-09-27")]
    gold(db, recs, persons=[person("p:2", "p:3")])
    assert sorted(r["pay_id"] for r in db.query("SELECT pay_id FROM pay_periods")) == ["P-1", "p:3"]


# ---- B2-02: missing fields are skipped, not KeyErrors ------------------------------------------------------------
@pytest.mark.parametrize("missing", ["pay.period_start", "pay.period_end"])
def test_payroll_row_without_period_dates_is_skipped(db, missing):
    bad = pay_rec("p:9", start=None if missing == "pay.period_start" else "2026-09-14",
                  end=None if missing == "pay.period_end" else "2026-09-20")
    gold(db, [bad, pay_rec("p:2")], persons=[person("p:9", "p:2")])
    assert [r["record_id"] for r in db.query("SELECT record_id FROM pay_periods")] == ["p:2"]


def test_payroll_row_without_hours_or_person_does_not_crash(db):
    gold(db, [pay_rec("p:1", hours=None), pay_rec("p:7", start="2026-09-21", end="2026-09-27")],
         persons=[person("p:1")])
    assert db.query("SELECT record_id, hours_paid FROM pay_periods") == [{"record_id": "p:1", "hours_paid": None}]


# ---- B1-04: the same fact from two files counts once, the newest file wins ----------------------------------------
def test_same_shift_in_two_files_is_stored_once_from_the_newest_file(db):
    files(db, old=OLD, new=NEW)
    gold(db, [], [shift_rec("o:1", "old"), shift_rec("n:1", "new")], [person("o:1", "n:1")])
    assert [r["record_id"] for r in db.query("SELECT record_id FROM shifts")] == ["n:1"]


def test_different_shifts_of_one_person_are_all_kept(db):
    files(db, old=OLD)
    gold(db, [], [shift_rec("o:1", "old"), shift_rec("o:2", "old", start=time(15), end=time(23))], [person("o:1", "o:2")])
    assert db.query("SELECT count(*) n FROM shifts")[0]["n"] == 2


def test_same_pay_period_in_two_files_is_stored_once_from_the_newest_file(db):
    files(db, old=OLD, new=NEW)
    recs = [pay_rec("o:1", "old", "P-1", 30.0), pay_rec("n:1", "new", "P-9", 36.0)]
    gold(db, recs, persons=[person("o:1", "n:1")])
    assert [(r["record_id"], r["hours_paid"]) for r in db.query("SELECT record_id, hours_paid FROM pay_periods")] == [("n:1", 36.0)]


def test_pay_period_at_two_facilities_is_two_periods(db):
    gold(db, [pay_rec("p:1"), pay_rec("p:2", pay_id="P-2", fac="FAC-RVD")], persons=[person("p:1", "p:2")])
    assert db.query("SELECT count(*) n FROM pay_periods")[0]["n"] == 2
