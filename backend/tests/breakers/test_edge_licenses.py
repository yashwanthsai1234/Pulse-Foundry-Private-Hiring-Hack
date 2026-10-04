"""B2 attacks on licence numbers and licence rows (docs/breakdowns/B2.md)."""
import pytest

from tests.breakers.edge_world import HR, HR_H, LIC, NOISE, hr_row, run

EXPIRED_LIC = [["RN-551203", "REYES, SOFIA", "RN", "2026-09-15", "2026-09-01"], *LIC[1:]]


def _expired_hr(number):
    return [hr_row(0, license_number=number, license_expiration="2026-09-15"), *HR[1:]]


@pytest.mark.parametrize("hr_number", ["RN551203", "RN 551203", "rn-551203", "RN-551203 ", "RN–551203", "RN_551203", "RN.551203"])
def test_hr_license_number_written_differently_is_one_credential(tmp_path, settings, hr_number):
    """HR 'RN551203' / 'RN 551203' vs licence 'RN-551203' must hard-link AND collapse to ONE credential."""
    r = run(tmp_path, settings, hr=_expired_hr(hr_number), lic=EXPIRED_LIC)
    assert [p["person_id"] for p in r.persons] == ["P-E201", "P-E202", "P-E203", "P-E204"]
    assert len(r.creds("P-E201")) == 1, [c["number"] for c in r.creds("P-E201")]
    assert len(r.ids("LIC-WORKED-EXPIRED")) == 1


@pytest.mark.parametrize("lic_number", ["RN551203", "rn 551203", "RN 551203", "RN‑551203"])
def test_license_file_number_written_differently_is_one_credential(tmp_path, settings, lic_number):
    lic = [[lic_number, "REYES, SOFIA", "RN", "2026-09-15", "2026-09-01"], *LIC[1:]]
    r = run(tmp_path, settings, hr=_expired_hr("RN-551203"), lic=lic)
    assert len(r.creds("P-E201")) == 1, [c["number"] for c in r.creds("P-E201")]
    assert len(r.ids("LIC-WORKED-EXPIRED")) == 1


def test_license_type_contradicting_number_prefix_is_flagged(tmp_path, settings):
    """CNA-771045 typed as an RN licence would silently authorise Marcus to work as an RN."""
    lic = [LIC[0], ["CNA-771045", "BELL, MARCUS", "RN", "2026-12-31", "2026-09-01"], *LIC[2:]]
    r = run(tmp_path, settings, lic=lic)
    assert r.about("P-E202", *NOISE, "HRS-PAID-VS-SCHED"), "type RN on a CNA- number raised nothing"


def test_expired_before_last_verified_still_critical(tmp_path, settings):
    r = run(tmp_path, settings, hr=_expired_hr("RN-551203"), lic=EXPIRED_LIC)
    (issue,) = r.ids("LIC-WORKED-EXPIRED")
    assert issue.severity == "CRITICAL" and issue.entity_ids == ["P-E201"]


def test_same_license_on_two_hr_employees_is_dup_license(tmp_path, settings):
    r = run(tmp_path, settings, hr=[HR[0], hr_row(1, license_number="RN-551203"), *HR[2:]])
    assert [p["person_id"] for p in r.persons] == ["P-E201", "P-E202", "P-E203", "P-E204"]
    assert r.ids("ID-DUP-LICENSE")
