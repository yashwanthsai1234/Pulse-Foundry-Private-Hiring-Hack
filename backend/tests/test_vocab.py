import pytest

from sot.normalize.vocab import normalize_vocab


@pytest.mark.parametrize("value,expected", [
    ("RN", ("RN", False)),
    ("r.n.", ("RN", False)),
    ("  Registered   Nurse ", ("RN", False)),
    ("LVN", ("LPN", False)),
    ("Certified Nursing Assistant", ("CNA", False)),
    ("Registerd Nurse", ("RN", True)),
    ("Banana", (None, False)),
    ("", (None, False)),
])
def test_roles(pack, value, expected):
    assert normalize_vocab(value, pack.vocabs["roles"]) == expected


def test_facilities(pack):
    assert normalize_vocab("BYS", pack.vocabs["facilities"]) == ("FAC-BAY", False)
    assert normalize_vocab("Harborview Riverdale", pack.vocabs["facilities"]) == ("FAC-RVD", False)
