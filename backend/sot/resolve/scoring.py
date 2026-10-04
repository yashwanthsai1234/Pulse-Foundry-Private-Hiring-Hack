"""Fellegi-Sunter style pair scoring: sum of log2 agreement weights plus a prior gives log2 odds of a match.

Sources:
- https://en.wikipedia.org/wiki/Record_linkage#Probabilistic_record_linkage (Fellegi-Sunter weights = log2(m/u))
- https://moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html (match weights, prior, probability from odds)
- https://rapidfuzz.github.io/RapidFuzz/Usage/distance/JaroWinkler.html (Jaro-Winkler for family names)
"""
from __future__ import annotations

from functools import lru_cache

from rapidfuzz.distance import JaroWinkler

from sot.core.models import Link, SourceRecord
from sot.normalize.names import PARTICLES, compare_given

FAMILY_FUZZY = 0.9
jaro_winkler = lru_cache(maxsize=None)(JaroWinkler.similarity)


def _agree(x, y, agree: str, disagree: str) -> str | None:
    return None if not x or not y else (agree if x == y else disagree)


def _family(a: SourceRecord, b: SourceRecord) -> str | None:
    fa, fb = a.person_key and a.person_key.family, b.person_key and b.person_key.family
    if not fa or not fb:
        return None
    if fa == fb:
        return "exact"
    if any(len(c) > 2 for c in _components(fa) & _components(fb)):
        return "part"
    return "fuzzy" if jaro_winkler(fa, fb) >= FAMILY_FUZZY else "disagree"


def _components(family: str) -> set[str]:
    return set(family.replace("-", " ").split()) - PARTICLES


def _role(r: SourceRecord):
    return r.fields.get("person.role") or r.fields.get("credential.type")


def score_pair(a: SourceRecord, b: SourceRecord, weights: dict[str, float], prior: float) -> Link:
    """Link (method "score") with weight = prior + sum of component weights and prob = 1 / (1 + 2^-weight)."""
    given = compare_given(a.person_key, b.person_key) if a.person_key and b.person_key else "unknown"
    outcomes = {
        "family": _family(a, b),
        "given": None if given == "unknown" else given,
        "suffix": _agree(a.person_key and a.person_key.suffix, b.person_key and b.person_key.suffix, "agree", "disagree"),
        "role": _agree(_role(a), _role(b), "agree", "disagree"),
        "facility": _agree(a.fields.get("person.facility"), b.fields.get("person.facility"), "agree", "disagree"),
    }
    reasons, total = [], prior
    for comp, outcome in outcomes.items():
        w = weights.get(f"{comp}_{outcome}", 0.0) if outcome else 0.0
        if outcome and w:
            reasons.append(f"{comp} {outcome} ({w:+.1f})")
            total += w
    return Link(a=a.record_id, b=b.record_id, prob=1 / (1 + 2.0**-total), weight=total, method="score", reasons=reasons)
