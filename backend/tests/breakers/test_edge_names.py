"""B2 attacks on person-name variants and entity resolution."""
import csv
from pathlib import Path

import pytest

from sot.normalize.names import compare_given, parse_person_name
from tests.breakers.edge_world import (HR, LIC, LIC_H, NOISE, PAY, R0, R1, SCHED_PAGES, hr_row, run, spec)

NICK = {r["nickname"]: r["canonical"] for r in csv.DictReader(
    (Path(__file__).resolve().parents[2] / "packs/healthcare_snf/vocab/nicknames.csv").open())}


def _pages(rows0=None, rows1=None):
    p0, p1 = dict(SCHED_PAGES[0]), dict(SCHED_PAGES[1])
    p0["rows"] = rows0 or p0["rows"]
    p1["rows"] = rows1 or p1["rows"]
    return spec([p0, p1])


def _pay(i, name, hours=None):
    rows = [list(r) for r in PAY]
    rows[i][1] = name
    if hours:
        rows[i][6] = hours
    return rows


def _sched_row(i, name, rows=SCHED_PAGES[0]["rows"]):
    return [[name, *rows[i][1:]] if k == i else r for k, r in enumerate(rows)]


# hr, payroll and schedule name this person differently from the licence, which has no number link (hr licence blank)
def _no_license_link(i=0, name="Katherine Nguyen"):
    first, last = name.split()
    return [hr_row(i, first_name=first, last_name=last, license_number="", license_expiration=""),
            *[r for k, r in enumerate(HR) if k != i]]


def _licenses_without(i=0):
    return [r for k, r in enumerate(LIC) if k != i]


COMMON_NICKNAMES = ["kate/katherine", "kathy/katherine", "katie/katherine", "peggy/margaret", "meg/margaret",
                    "rick/richard", "jack/john", "ted/edward", "sue/susan", "debbie/deborah", "larry/lawrence",
                    "jerry/gerald", "terry/terrence", "cindy/cynthia", "bob/robert", "bill/william", "liz/elizabeth"]


def test_common_nicknames_are_known():
    """compare_given must call each common US nickname/given-name pair a nickname match (vocab/nicknames.csv has 324 rows)."""
    missing = [p for p in COMMON_NICKNAMES
               if compare_given(*(parse_person_name(f"{n} Smith", NICK) for n in p.split("/"))) != "nickname"]
    assert not missing, missing


def test_kate_in_payroll_and_schedule_links_to_katherine_in_hr(tmp_path, settings):
    """README example: HR 'Katherine Nguyen', payroll 'NGUYEN, KATE', schedule 'Kate Nguyen' (no licence row to bridge)."""
    hr = _no_license_link(0, "Katherine Nguyen")
    r = run(tmp_path, settings, hr=hr, pay=_pay(0, "NGUYEN, KATE"), lic=_licenses_without(0),
            sched=_pages(rows0=_sched_row(0, "Kate Nguyen")))
    assert len(r.persons) == 4, [(p["person_id"], p["display_name"]) for p in r.persons]
    assert not r.ids("PAY-NO-HR") and not r.ids("SCHED-NO-HR")


def test_compound_surname_links_or_is_gray_pair(tmp_path, settings):
    """'Reyes-Garcia, Sofia' (payroll/schedule) vs HR 'Sofia Reyes': merge, or at least a gray pair for a human."""
    r = run(tmp_path, settings, hr=_no_license_link(0, "Sofia Reyes"), pay=_pay(0, "Reyes-Garcia, Sofia"),
            lic=_licenses_without(0), sched=_pages(rows0=_sched_row(0, "Sofia Reyes-Garcia")))
    assert len(r.persons) == 4 or {"ID-GRAY-PAIR", "ID-AMBIGUOUS"} & r.checks(), (
        "phantom no-HR person with PAY-NO-HR/SCHED-NO-HR and no hint that it may be Sofia Reyes: " + str(sorted(r.attention())))


def test_sophia_vs_sofia_is_not_a_silent_phantom(tmp_path, settings):
    r = run(tmp_path, settings, hr=_no_license_link(0, "Sofia Reyes"), pay=_pay(0, "REYES, SOPHIA"),
            lic=_licenses_without(0), sched=_pages(rows0=_sched_row(0, "Sophia Reyes")))
    assert len(r.persons) == 4 or {"ID-GRAY-PAIR", "ID-AMBIGUOUS"} & r.checks(), sorted(r.attention())


def test_schedule_annotation_in_name_cell_is_stripped(tmp_path, settings):
    """'Sofia Reyes (float)' is a very common roster annotation; it must not create a person without HR."""
    r = run(tmp_path, settings, hr=_no_license_link(0, "Sofia Reyes"), lic=_licenses_without(0),
            sched=_pages(rows0=_sched_row(0, "Sofia Reyes (float)")))
    assert len(r.persons) == 4 and not r.ids("SCHED-NO-HR"), sorted(r.attention())


@pytest.mark.parametrize("name", ["Reyes, Sofia M.", "SOFIA REYES", "Sofía Reyes", "Sofia  Reyes ", "Reyes, S.", "Mrs. Sofia Reyes"])
def test_name_spellings_link_through_payroll_and_schedule(tmp_path, settings, name):
    r = run(tmp_path, settings, hr=_no_license_link(0, "Sofia Reyes"), pay=_pay(0, name), lic=_licenses_without(0),
            sched=_pages(rows0=_sched_row(0, name)))
    assert len(r.persons) == 4, [(p["person_id"], p["display_name"]) for p in r.persons]
    assert len(r.pay_periods("P-E201")) == 1 and len(r.shifts("P-E201")) == 4


def test_bell_jr_and_sr_are_two_people_with_their_own_hours(tmp_path, settings):
    """Father and son on one roster: the generational suffix is the only difference in payroll/schedule/licence."""
    hr = [list(r) for r in HR] + [["E205", "Marcus", "Bell Jr.", "Certified Nursing Assistant", "Harborview Riverdale",
                                   "347-555-0299", "CNA-880001", "2027-01-31", "2024-01-01"]]
    hr[1][2] = "Bell Sr."
    pay = [list(r) for r in PAY]
    pay[1][1] = "BELL SR, MARCUS"
    pay.append(["P-3005", "BELL JR, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "16"])
    lic = [list(r) for r in LIC]
    lic[1][1] = "BELL SR, MARCUS"
    lic.append(["CNA-880001", "BELL JR, MARCUS", "CNA", "2027-01-31", "2026-09-01"])
    rows1 = [["Marcus Bell Sr.", *R1[0][1:]], ["Marcus Bell Jr.", "CNA", "7a-3p", "7a-3p", "OFF", "OFF", "OFF", "OFF", "OFF"], R1[1]]
    r = run(tmp_path, settings, hr=hr, pay=pay, lic=lic, sched=_pages(rows1=rows1))
    assert [p["hours_paid"] for p in r.pay_periods("P-E205")] == [16.0], "Jr's payroll row went to Sr"
    assert len(r.shifts("P-E205")) == 2 and len(r.shifts("P-E202")) == 5
    assert not r.ids("HRS-PAID-VS-SCHED")


def test_two_employees_same_name_two_facilities_stay_apart(tmp_path, settings):
    hr = [list(r) for r in HR] + [
        ["E205", "Maria", "Santos", "Certified Nursing Assistant", "Harborview Bayside", "718-555-0205", "CNA-111001", "2027-01-31", "2021-01-01"],
        ["E206", "Maria", "Santos", "Certified Nursing Assistant", "Harborview Riverdale", "347-555-0206", "CNA-111002", "2027-03-31", "2023-04-01"]]
    pay = [list(r) for r in PAY] + [["P-3005", "SANTOS, MARIA", "CNA", "BYS", "2026-09-14", "2026-09-20", "24"],
                                    ["P-3006", "SANTOS, MARIA", "CNA", "RVD", "2026-09-14", "2026-09-20", "32"]]
    lic = [list(r) for r in LIC] + [["CNA-111001", "SANTOS, MARIA", "CNA", "2027-01-31", "2026-09-01"],
                                    ["CNA-111002", "SANTOS, MARIA", "CNA", "2027-03-31", "2026-09-01"]]
    sched = _pages(R0 + [["Maria Santos", "CNA", "7a-3p", "7a-3p", "7a-3p", "OFF", "OFF", "OFF", "OFF"]],
                   R1 + [["Maria Santos", "CNA", "OFF", "OFF", "OFF", "7a-7p", "7a-7p", "7a-3p", "OFF"]])
    r = run(tmp_path, settings, hr=hr, pay=pay, lic=lic, sched=sched)
    assert len(r.persons) == 6
    assert [p["hours_paid"] for p in r.pay_periods("P-E205")] == [24.0] and [p["hours_paid"] for p in r.pay_periods("P-E206")] == [32.0]
    assert not r.ids("HRS-PAID-VS-SCHED")


def test_same_name_pair_raises_one_conflict_not_seven(tmp_path, settings):
    """The same two persons are reported as ID-CONFLICT once per record pair: 7 identical issues for Maria Santos x2."""
    hr = [list(r) for r in HR] + [
        ["E205", "Maria", "Santos", "Certified Nursing Assistant", "Harborview Bayside", "718-555-0205", "CNA-111001", "2027-01-31", "2021-01-01"],
        ["E206", "Maria", "Santos", "Certified Nursing Assistant", "Harborview Riverdale", "347-555-0206", "CNA-111002", "2027-03-31", "2023-04-01"]]
    pay = [list(r) for r in PAY] + [["P-3005", "SANTOS, MARIA", "CNA", "BYS", "2026-09-14", "2026-09-20", "24"],
                                    ["P-3006", "SANTOS, MARIA", "CNA", "RVD", "2026-09-14", "2026-09-20", "32"]]
    lic = [list(r) for r in LIC] + [["CNA-111001", "SANTOS, MARIA", "CNA", "2027-01-31", "2026-09-01"],
                                    ["CNA-111002", "SANTOS, MARIA", "CNA", "2027-03-31", "2026-09-01"]]
    r = run(tmp_path, settings, hr=hr, pay=pay, lic=lic)
    pairs = [tuple(sorted(i.entity_ids)) for i in r.ids("ID-CONFLICT")]
    assert len(pairs) == len(set(pairs)), pairs


def test_maiden_name_on_license_with_hr_license_number_links(tmp_path, settings):
    lic = [["RN-551203", "GARCIA, SOFIA", "RN", "2027-05-31", "2026-09-01"], *LIC[1:]]
    r = run(tmp_path, settings, lic=lic)
    assert len(r.persons) == 4 and r.ids("ID-NAME-DIFFERS-ON-LICENSE")


def test_maiden_name_on_license_without_number_is_for_human(tmp_path, settings):
    """No shared number, different surname: it must not silently vanish (an orphan RN licence + an RN with none)."""
    hr = [hr_row(0, license_number="", license_expiration=""), *HR[1:]]
    lic = [["RN-551203", "GARCIA, SOFIA", "RN", "2027-05-31", "2026-09-01"], *LIC[1:]]
    r = run(tmp_path, settings, hr=hr, lic=lic)
    assert r.attention() - NOISE


def test_swapped_first_last_columns_in_hr_row(tmp_path, settings):
    """HR row 'Reyes','Sofia' in first/last: still the same person as payroll 'REYES, SOFIA'."""
    r = run(tmp_path, settings, hr=[hr_row(0, first_name="Reyes", last_name="Sofia"), *HR[1:]])
    assert len(r.persons) == 4 and not r.ids("PAY-NO-HR")


def test_initial_only_schedule_name_with_two_candidates_is_not_guessed(tmp_path, settings):
    hr = [list(r) for r in HR] + [
        ["E205", "John", "Smith", "Certified Nursing Assistant", "Harborview Riverdale", "347-555-0205", "CNA-500001", "2027-01-31", "2021-01-01"],
        ["E206", "Jane", "Smith", "Certified Nursing Assistant", "Harborview Riverdale", "347-555-0206", "CNA-500002", "2027-01-31", "2022-01-01"]]
    lic = [list(r) for r in LIC] + [["CNA-500001", "SMITH, JOHN", "CNA", "2027-01-31", "2026-09-01"],
                                    ["CNA-500002", "SMITH, JANE", "CNA", "2027-01-31", "2026-09-01"]]
    r = run(tmp_path, settings, hr=hr, lic=lic,
            sched=_pages(rows1=R1 + [["J. Smith", "CNA", "7a-3p", "7a-3p", "OFF", "OFF", "OFF", "OFF", "OFF"]]))
    assert r.ids("ID-AMBIGUOUS") or r.ids("ID-GRAY-PAIR")
    assert not any(r.person_of(x.record_id) in ("P-E205", "P-E206") for x in r.records("schedule") if x.fields.get("person.full_name") == "J. Smith")
