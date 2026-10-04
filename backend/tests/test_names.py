import pytest
from hypothesis import given, strategies as st

from sot.normalize.names import compare_given, parse_person_name, person_key_from_parts
from sot.normalize.phones import normalize_phone

NICK = {"marc": "marcus", "bob": "robert", "liz": "elizabeth"}


def p(text):
    return parse_person_name(text, NICK)


def test_last_comma_first():
    k = p("BELL, MARCUS")
    assert (k.family, k.given, k.given_initial, k.nick_key) == ("bell", "marcus", "m", "marcus")
    assert k.display == "BELL, MARCUS"


def test_first_middle_last_and_nickname_key():
    k = p("Marc A. Bell")
    assert (k.given, k.middle, k.family, k.nick_key) == ("marc", "a", "bell", "marcus")
    assert k.soundex_family == "B400"


def test_particles_join_family():
    assert p("Maria de la Cruz").family == "de la cruz"
    assert p("van Dyke, Peter").family == "van dyke"


@pytest.mark.parametrize("text", ["Marcus Bell Jr.", "Marcus Bell, RN", "Dr. Marcus Bell", "BELL JR, MARCUS"])
def test_suffixes_and_titles_removed(text):
    k = p(text)
    assert (k.given, k.family) == ("marcus", "bell")


def test_accents_stripped():
    k = p("José Muñoz")
    assert (k.given, k.family) == ("jose", "munoz")


def test_initial_only_given():
    k = p("M. Bell")
    assert (k.given, k.given_initial, k.family) == (None, "m", "bell")
    assert p("Bell, M.").given is None


def test_hyphenated_family_and_apostrophe():
    assert p("Ana Smith-Jones").family == "smith-jones"
    assert p("Pat O'Brien").family == "o'brien"


def test_single_token_and_empty():
    assert (p("Bell").family, p("Bell").given) == ("bell", None)
    k = p("  ")
    assert (k.family, k.given, k.soundex_family) == (None, None, None)


def test_person_key_from_parts():
    k = person_key_from_parts("Marcus", "Bell", NICK)
    assert (k.given, k.family, k.given_initial) == ("marcus", "bell", "m")
    assert person_key_from_parts(None, None, NICK).family is None


@pytest.mark.parametrize("a,b,expected", [
    ("Marcus Bell", "Marcus Bell", "exact"),
    ("Marc Bell", "Marcus Bell", "nickname"),
    ("Bob Bell", "Robert Bell", "nickname"),
    ("Sam Bell", "Samantha Bell", "nickname"),
    ("Marcus Bell", "Marcos Bell", "fuzzy"),
    ("M. Bell", "Marcus Bell", "initial"),
    ("M. Bell", "Maria Bell", "initial"),
    ("M. Bell", "Joan Bell", "disagree"),
    ("Marcus Bell", "Maria Bell", "disagree"),
    ("Mark Bell", "Marcus Bell", "disagree"),
    ("Bell", "Marcus Bell", "unknown"),
])
def test_compare_given(a, b, expected):
    assert compare_given(p(a), p(b)) == expected


def test_nickname_table_is_conservative(pack):
    nick = pack.nicknames
    assert len(nick) >= 300
    assert nick["marc"] == "marcus" and nick["bob"] == "robert"
    assert "mark" not in nick
    assert not set(nick) & set(nick.values())


@pytest.mark.parametrize("text,expected", [
    ("718-555-0201", "+17185550201"),
    ("(718) 555 0201", "+17185550201"),
    ("1-718-555-0201", "+17185550201"),
    ("+1 718.555.0201 x45", "+17185550201"),
    ("555-0201", None),
    ("", None),
    ("n/a", None),
])
def test_normalize_phone(text, expected):
    assert normalize_phone(text) == expected


@given(st.text(max_size=40), st.text(max_size=40))
def test_parse_never_raises_and_compare_is_symmetric(x, y):
    a, b = p(x), p(y)
    assert compare_given(a, b) == compare_given(b, a)
