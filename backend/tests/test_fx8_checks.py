"""FX8: per-row check robustness, person-level fingerprints, unplaced shifts, PBJ facility-scoped status."""
from datetime import date

from tests.review.r1_support import gold_issues


def test_one_unreportable_row_keeps_the_other_rows(tmp_path):
    creds = [{"credential_id": "C1", "number": "RN-1", "holder_id": "P-E1", "holder_name": None, "expires_on": date(2026, 9, 25)},
             {"credential_id": "C2", "number": "RN-2", "holder_id": "P-E2", "holder_name": "Ann Lee", "expires_on": date(2026, 9, 26)}]
    found = gold_issues(tmp_path, persons=[{"person_id": "P-E1"}, {"person_id": "P-E2"}], credentials=creds)
    expiring = [i for i in found if i.check_id == "LIC-EXPIRING"]
    assert len(expiring) == 2 and any("(no name)" in i.message for i in expiring)
    assert [i for i in found if i.check_id == "CHECK-ERROR"] == []


def test_person_level_issue_has_no_period_so_a_later_week_keeps_one_issue(tmp_path):
    found = gold_issues(tmp_path, persons=[{"person_id": "P-E1"}], credentials=[],
                        shifts=[{"shift_id": "s1"}, {"shift_id": "s2", "work_date": date(2026, 9, 21)}])
    (i,) = [x for x in found if x.check_id == "LIC-NONE-FOR-ROLE"]
    assert i.period_start is None and "2026-09-14 to 2026-09-21" in i.message


def test_shift_without_facility_raises_an_issue(tmp_path):
    found = gold_issues(tmp_path, persons=[{"person_id": "P-E1"}], shifts=[{"shift_id": "s1", "facility_id": None}])
    assert any(i.check_id == "COV-RN-DAILY" and "no resolved facility" in i.message for i in found)


def test_src_conflict_ids_include_the_holder(tmp_path):
    from datetime import datetime, UTC
    from sot.core.models import Claim, Locator
    from sot.config import load_settings
    from sot.core.pack import load_pack
    from sot.truth.survivorship import survive

    loc = Locator(file_id="f", file_name="f", row=1)
    now = datetime.now(UTC)

    def claim(cid, etype, eid, attr, value, tpl, rec):
        return Claim(claim_id=cid, entity_type=etype, entity_id=eid, attribute=attr, value=value, value_type="date",
                     template_id=tpl, record_id=rec, loc=loc, observed_at=now)
    claims = [claim("a", "person", "P-E1", "display_name", "Pat", "hr_roster", "r1"),
              claim("b", "person", "P-E1", "display_name", "Pat", "license_registry", "r2"),
              claim("c", "credential", "RN-1", "expires_on", "2027-01-01", "hr_roster", "r1"),
              claim("d", "credential", "RN-1", "expires_on", "2027-02-01", "license_registry", "r2")]
    _, drafts = survive(claims, load_pack(load_settings(runtime=tmp_path / "rt").pack_dir))
    assert drafts and drafts[0].entity_ids == ["RN-1", "P-E1"]
