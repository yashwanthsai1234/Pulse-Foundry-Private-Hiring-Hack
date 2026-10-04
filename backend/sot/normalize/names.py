"""Person-name parsing and given-name comparison (IMPLEMENTATION §10.1).

Sources:
- https://github.com/carltonnorthern/nickname-and-diminutive-names-lookup (nickname dataset behind vocab/nicknames.csv)
- https://rapidfuzz.github.io/RapidFuzz/Usage/distance/JaroWinkler.html (Jaro-Winkler similarity API)
- https://jamesturk.github.io/jellyfish/functions/ (soundex)
- https://en.wikipedia.org/wiki/Jaro%E2%80%93Winkler_distance (why JW suits short person names)
- https://en.wikipedia.org/wiki/Suffix_(name) (generational suffixes Jr/Sr/II/III/IV identify different people; RN, CNA are post-nominal credentials)
- https://www.unicode.org/reports/tr15/ (NFKD does not decompose stroke letters such as Ł ø đ, so they need an explicit fold)
- https://en.wikipedia.org/wiki/Quotation_marks_in_English#Apostrophe (U+2019 is the typographic apostrophe)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

import jellyfish
from rapidfuzz.distance import JaroWinkler

from sot.core.models import PersonKey

GENERATIONAL = {"jr", "sr", "ii", "iii", "iv"}
DROPPED = {"rn", "cna", "lpn", "mr", "ms", "mrs", "dr"}  # credentials and titles carry no identity
FOLD = str.maketrans({"’": "'", "‘": "'", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D"})
FOLD_MULTI = {"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE"}
NOTE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
PARTICLES = {"de", "del", "la", "van", "von", "da", "di"}
FUZZY_GIVEN = 0.93  # marcus/marcos .933 passes; maria/mario .920 and michael/michelle .921 do not
MIN_PREFIX = 3


def _tokens(text: str) -> list[str]:
    """Notes in (...) / [...] removed, typographic letters folded, NFKD accents removed, lower-case,
    only letters ' - and spaces; "Washington- Greene" (cell wrap) rejoined; titles and credentials dropped."""
    text = NOTE.sub(" ", text).translate(FOLD)
    for src, dst in FOLD_MULTI.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\s*-\s+", "-", re.sub(r"[^a-z'\- ]", " ", text))
    return [t for t in text.split() if t.strip("'-") and t not in DROPPED]


def _split_suffix(tokens: list[str]) -> tuple[list[str], str | None]:
    """Generational suffix tokens are taken out of the name and returned (a lone token is a name, not a suffix)."""
    rest = [t for t in tokens if t not in GENERATIONAL]
    suffix = next((t for t in tokens if t in GENERATIONAL), None)
    return (rest, suffix) if rest else (tokens, None)


def _key(given: list[str], family: list[str], display: str, nick: dict[str, str], suffix: str | None = None) -> PersonKey:
    first = given[0] if given else None
    full_given = first if first and len(first) > 1 else None
    fam = " ".join(family) or None
    return PersonKey(
        given=full_given,
        family=fam,
        middle=" ".join(given[1:]) or None,
        suffix=suffix,
        given_initial=first[0] if first else None,
        nick_key=nick.get(full_given, full_given) if full_given else None,
        soundex_family=jellyfish.soundex(re.sub(r"[^a-z]", "", fam)) if fam else None,
        display=display,
    )


def parse_person_name(text: str, nick: dict[str, str]) -> PersonKey:
    """'BELL, MARCUS' / 'Marc A. Bell' / 'M. Bell' -> PersonKey. Particles (de, van, ...) join the family name."""
    before, comma, after = text.partition(",")
    (family, s1), (given, s2) = _split_suffix(_tokens(before)), _split_suffix(_tokens(after))
    if comma and family and given and not set(given) <= GENERATIONAL:
        return _key(given, family, text, nick, s1 or s2)
    toks, suffix = _split_suffix(_tokens(text))
    if not toks:
        return _key([], [], text, nick)
    start = len(toks) - 1
    while start > 1 and toks[start - 1] in PARTICLES:
        start -= 1
    return _key(toks[:start], toks[start:], text, nick, suffix)


def person_key_from_parts(given: str | None, family: str | None, nick: dict[str, str]) -> PersonKey:
    family_toks, suffix = _split_suffix(_tokens(family or ""))
    return _key(_tokens(given or ""), family_toks, f"{given or ''} {family or ''}".strip(), nick, suffix)


def compare_given(a: PersonKey, b: PersonKey) -> Literal["exact", "nickname", "fuzzy", "initial", "disagree", "unknown"]:
    if a.given and b.given:
        if a.given == b.given:
            return "exact"
        short, long_ = sorted((a.given, b.given), key=len)
        if a.nick_key == b.nick_key or (len(short) >= MIN_PREFIX and long_.startswith(short)):
            return "nickname"
        spelled_alike = a.given.replace("ph", "f") == b.given.replace("ph", "f")  # sophia / sofia
        return "fuzzy" if spelled_alike or JaroWinkler.similarity(a.given, b.given) >= FUZZY_GIVEN else "disagree"
    if a.given_initial and b.given_initial:
        return "initial" if a.given_initial == b.given_initial else "disagree"
    return "unknown"
