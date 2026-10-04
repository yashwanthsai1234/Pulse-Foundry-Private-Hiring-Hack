"""Claims, survivorship and gold tables on the hand-built example_e1 inputs."""
from datetime import date, datetime, time

from a5_e1 import example_e1, run_e1
from sot.core.models import Claim, Locator, Person, ShiftRecord, SourceRecord
from sot.truth.claims import build_claims
from sot.truth.gold import write_gold
from sot.truth.survivorship import survive

LOC = Locator(file_id="f", file_name="f.csv", row=1)


def claim(cid, template, value, minute=0, attr="expires_on", eid="RN-1"):
    return Claim(claim_id=cid, entity_type="credential", entity_id=eid, attribute=attr, value=value,
                 value_type="date", template_id=template, record_id=cid, loc=LOC,
                 observed_at=datetime(2026, 9, 1, 0, minute))


def test_claims_cover_people_and_credentials():
    records, _, persons, _ = example_e1()
    claims = build_claims(records, persons)
    keys = {(c.entity_type, c.entity_id, c.attribute, c.template_id) for c in claims}
    assert ("person", "P-E202", "display_name", "schedule") in keys
    assert ("person", "P-E202", "home_facility", "schedule") not in keys
    assert ("credential", "CNA-771045", "expires_on", "hr_roster") in keys
    assert ("credential", "CNA-771045", "credential_type", "hr_roster") in keys
    assert len({c.claim_id for c in claims}) == len(claims)


def test_vendor_claims_use_org_ids():
    r = SourceRecord(record_id="v:1", template_id="vendor_credential", entity="credential",
                     fields={"org.name": "Sparkle Linen Co.", "credential.doc_type": "COI", "credential.expires_on": "2026-10-01"},
                     raw={}, loc=LOC)
    claims = build_claims([r], [])
    assert {c.entity_id for c in claims} == {"ORG:sparkle-linen-co:COI"}
    assert {c.attribute for c in claims} == {"expires_on", "credential_type", "holder_name"}


def test_license_beats_hr_and_conflict_becomes_issue(pack):
    claims = [claim("a", "hr_roster", "2026-12-31"), claim("b", "license", "2026-09-15")]
    golden, drafts = survive(claims, pack)
    g = golden[0]
    assert (g.value, g.claim_id, g.conflict, g.conflicting_claim_ids) == ("2026-09-15", "b", True, ["a"])
    assert g.rule == "priority:license>vendor_credential>hr_roster"
    assert [(d.check_id, d.severity, d.entity_ids) for d in drafts] == [("SRC-CONFLICT", "MEDIUM", ["RN-1"])]


def test_equal_values_do_not_conflict(pack):
    golden, drafts = survive([claim("a", "hr_roster", "2026-12-31"), claim("b", "license", "2026-12-31")], pack)
    assert not golden[0].conflict and drafts == []


def test_same_source_tie_breaks_on_latest_and_flags(pack):
    claims = [claim("old", "license", "2026-01-01", minute=1), claim("new", "license", "2026-02-02", minute=9)]
    golden, drafts = survive(claims, pack)
    assert golden[0].claim_id == "new" and golden[0].conflict and len(drafts) == 1


def test_string_conflict_is_case_insensitive_and_unchecked_attrs_make_no_issue(pack):
    a, b = claim("a", "hr_roster", "RN", attr="credential_type"), claim("b", "license", "rn", attr="credential_type")
    golden, drafts = survive([a, b], pack)
    assert not golden[0].conflict
    c = claim("c", "hr_roster", "X", attr="credential_type")
    golden, drafts = survive([a, c], pack)
    assert golden[0].conflict and drafts == []


def test_gold_tables(db, pack, settings):
    run_e1(db, pack, settings)
    assert db.query("SELECT person_id, display_name, role, home_facility_id, has_hr FROM persons ORDER BY 1") == [
        {"person_id": "P-E201", "display_name": "Sofia Reyes", "role": "RN", "home_facility_id": "FAC-BAY", "has_hr": True},
        {"person_id": "P-E202", "display_name": "Marcus Bell", "role": "CNA", "home_facility_id": "FAC-RVD", "has_hr": True}]
    cna = db.query("SELECT * FROM credentials WHERE credential_id = 'CNA-771045'")[0]
    assert (cna["holder_id"], cna["credential_type"], str(cna["expires_on"]), str(cna["last_verified"])) == (
        "P-E202", "CNA", "2026-09-15", "2026-09-01")
    assert db.query("SELECT count(*) n FROM shifts")[0]["n"] == 9
    assert db.query("SELECT count(*) n FROM pay_periods")[0]["n"] == 2
    assert db.query("SELECT count(*) n FROM person_records")[0]["n"] == 8
    conflict = db.query("SELECT conflict FROM golden_values WHERE entity_id='CNA-771045' AND attribute='expires_on'")
    assert conflict == [{"conflict": True}]


def test_overnight_shift_wraps_and_vendor_is_organization(db, pack):
    rec = SourceRecord(record_id="v:1", template_id="vendor_credential", entity="credential", loc=LOC, raw={},
                       fields={"org.name": "Sparkle Linen", "credential.expires_on": "2026-10-01", "credential.number": "POL-9"})
    sh = ShiftRecord(shift_id="s:1", record_id="sch:1", facility_id="FAC-BAY", role="RN", work_date=date(2026, 9, 14),
                     token="11p-7a", start=time(23), end=time(7), hours=8.0, hours_source="both", loc=LOC)
    claims = build_claims([rec], [])
    golden, _ = survive(claims, pack)
    write_gold(db, [rec], [sh], [Person(person_id="P-1", record_ids=["sch:1"], employee_id="E1", has_hr=True)], [],
               claims, golden)
    s = db.query("SELECT start_ts, end_ts, person_id FROM shifts")[0]
    assert (s["start_ts"].day, s["end_ts"].day, s["end_ts"].hour, s["person_id"]) == (14, 15, 7, "P-1")
    c = db.query("SELECT holder_type, holder_id, number FROM credentials")[0]
    assert c == {"holder_type": "organization", "holder_id": "ORG:sparkle-linen:POL-9", "number": "POL-9"}
