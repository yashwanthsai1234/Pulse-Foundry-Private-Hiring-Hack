"""FX3: name normalisation, nicknames, blocking for typos, suffix cannot-link, ID-CONFLICT dedupe, canonical licences."""
import pytest
from test_resolve import Build, check_ids, group_of, rec

from sot.normalize.names import compare_given, parse_person_name
from sot.resolve.blocking import block
from sot.resolve.resolver import resolve_all


@pytest.fixture
def b(pack):
    return Build(pack.nicknames)


def p(text, nick=None):
    return parse_person_name(text, nick or {})


@pytest.mark.parametrize("text,suffix", [("Marcus Bell Jr.", "jr"), ("BELL SR, MARCUS", "sr"), ("Bell, Marcus III", "iii"),
                                         ("Marcus Bell, IV", "iv"), ("Marcus Bell II", "ii"), ("Marcus Bell, RN", None), ("Marcus Bell CNA", None)])
def test_generational_suffix_is_kept_credentials_are_not(text, suffix):
    k = p(text)
    assert (k.given, k.family, k.suffix) == ("marcus", "bell", suffix)


@pytest.mark.parametrize("text", ["Sofia Reyes (float)", "Sofia Reyes [agency]", "Reyes, Sofia (PRN)", "Sofia Reyes*"])
def test_parenthetical_notes_are_stripped(text):
    assert (p(text).given, p(text).family) == ("sofia", "reyes")


def test_curly_apostrophes_and_non_decomposable_letters():
    assert p("Renee O’Brien").family == "o'brien" == p("Renee O‘Brien").family
    assert (p("Łukasz Nowak").given, p("Bjørn Åberg").given, p("Strauß, Hans").family, p("Æsa Œuvre").given) == ("lukasz", "bjorn", "strauss", "aesa")
    assert p("Đorđe Ivanović").given == "dorde"


def test_hyphen_then_space_from_cell_wrap():
    assert p("Dorothy Washington- Greene").family == "washington-greene"


def test_sophia_and_sofia_are_fuzzy_given(pack):
    assert compare_given(p("Sofia Reyes", pack.nicknames), p("Sophia Reyes", pack.nicknames)) == "fuzzy"
    assert compare_given(p("Maria Reyes", pack.nicknames), p("Mario Reyes", pack.nicknames)) == "disagree"


@pytest.mark.parametrize("given,nick", [("Katherine", "Kate"), ("Richard", "Rick"), ("Susan", "Sue"), ("Deborah", "Debbie"), ("Margaret", "Peggy")])
def test_nickname_pairs_from_dataset(pack, given, nick):
    assert compare_given(p(f"{given} Lee", pack.nicknames), p(f"{nick} Lee", pack.nicknames)) == "nickname"


@pytest.mark.parametrize("hr_family,other", [("Reyes", "Reyes-Garcia"), ("Garcia", "García Lopez"), ("Watson", "Waton")])
def test_compound_or_typo_family_is_at_least_a_gray_pair(pack, settings, b, hr_family, other):
    recs = [b.hr(1, "E1", "Sofia", hr_family, "RN", "FAC-BAY"), b.pay(1, f"{other}, Sofia", "RN", "FAC-BAY")]
    res = resolve_all(recs, pack, settings)
    assert len(res.persons) == 1 or any(d.check_id == "ID-GRAY-PAIR" for d in res.drafts)


def test_different_generational_suffix_never_merges(pack, settings, b):
    recs = [b.hr(1, "E1", "Marcus", "Bell Sr.", "CNA", "FAC-BAY"), b.hr(2, "E2", "Marcus", "Bell Jr.", "CNA", "FAC-BAY"),
            b.pay(1, "BELL JR, MARCUS", "CNA", "FAC-BAY"), b.sch(1, "Marcus Bell Sr.", "CNA", "FAC-BAY")]
    res = resolve_all(recs, pack, settings)
    assert group_of(res, "pay:1").employee_id == "E2" and group_of(res, "sch:1").employee_id == "E1"
    assert "ID-CONFLICT" not in check_ids(res)


def test_cannot_link_blocks_suffix_clash_even_with_extra_link(pack, settings, b):
    from sot.core.models import Link
    recs = [b.pay(1, "BELL JR, MARCUS", "CNA", "FAC-BAY"), b.sch(1, "Marcus Bell Sr.", "CNA", "FAC-BAY")]
    res = resolve_all(recs, pack, settings, extra_links=[Link(a="pay:1", b="sch:1", prob=1.0, weight=20, method="agent", reasons=[])])
    assert len(res.persons) == 2 and "ID-CONFLICT" in check_ids(res)


def test_one_conflict_per_person_pair(pack, settings, b):
    recs = []
    for k, (emp, num) in enumerate([("E1", "CNA-1"), ("E2", "CNA-2")], 1):
        recs += [b.hr(k, emp, "Maria", "Santos", "CNA", "FAC-BAY", num), b.lic(k, "SANTOS, MARIA", num, "CNA")]
    recs += [b.pay(i, "SANTOS, MARIA", "CNA", "FAC-BAY", table=f"pay{i}") for i in range(3)]
    res = resolve_all(recs, pack, settings)
    pairs = [tuple(d.entity_ids) for d in res.drafts if d.check_id == "ID-CONFLICT"]
    assert len(pairs) == len(set(pairs))


def test_license_number_forms_are_one_credential_in_the_resolver(pack, settings, b):
    recs = [b.hr(1, "E3", "Dana", "Harris", "RN", "FAC-BAY", "RN551203"), b.lic(1, "harris, dana", "RN–551203", "RN"),
            b.lic(2, "harris, dana", "rn_551203", "RN", table="lic2")]
    res = resolve_all(recs, pack, settings)
    assert [p.person_id for p in res.persons] == ["P-E3"] and "ID-CONFLICT" not in check_ids(res)


def test_records_with_no_name_and_no_ids_are_ignored(pack, settings, b):
    totals = [rec("pay", 9, "payroll", {"person.full_name": "TOTAL"}, None), rec("pay", 10, "payroll", {}, p(""))]
    res = resolve_all([*totals, b.hr(1, "E1", "Marcus", "Bell", "CNA", "FAC-BAY")], pack, settings)
    assert [x.person_id for x in res.persons] == ["P-E1"]


def test_typo_family_shares_a_blocking_key(pack, b):
    a, c = b.hr(1, "E1", "Brian", "Watson", "CNA", "FAC-BAY"), b.sch(1, "Brian Waton", "CNA", "FAC-RVD")
    assert ("hr:1", "sch:1") in block([a, c], pack.resolution["blocking"])
