"""Column -> field scoring and one-to-one assignment (§9.3).

S = 0.45 header + 0.45 value + 0.10 type. Value gate: value_score < 0.5 caps S at 0.4, so a header alone
never wins. Repeatable fields (schedule.day) claim their header-pattern columns first; the rest are assigned
with the Hungarian algorithm over [columns x (fields + one dummy "no field" per column)].

Sources:
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html (rectangular, maximize)
- https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html#token-sort-ratio (order-insensitive, no subset 100 unlike
  token_set_ratio: "Type" vs "license type" is 0.5, "Number" vs "license number" is not a match) and
  https://rapidfuzz.github.io/RapidFuzz/Usage/distance/JaroWinkler.html (header similarity)
- https://arxiv.org/pdf/2010.07386 (Valentine: COMA-style combination of name and instance matchers)
- https://en.wikipedia.org/wiki/Hungarian_algorithm (why greedy per-column matching double-assigns a field)
"""
from __future__ import annotations

import re

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from scipy.optimize import linear_sum_assignment

from sot.core.models import ColumnProfile, FieldMatch
from sot.core.pack import FieldSpec
from sot.normalize.vocab import clean

W_HEADER, W_VALUE, W_TYPE = 0.45, 0.45, 0.10
GATE_VALUE, GATE_CAP = 0.5, 0.4
WEAK_HEADER_MIN = 0.8  # a non_empty validator proves nothing about values; it counts only behind a strong header
_EXPAND = {"no": "number", "exp": "expiration", "dt": "date"}
_TYPE_FIT = {
    "string": {"string": 1, "integer": 0.5}, "person_name": {"string": 1}, "vocab": {"string": 1},
    "phone": {"string": 1, "integer": 0.5}, "email": {"string": 1}, "shift_cell": {"string": 1},
    "date": {"date": 1}, "number": {"number": 1, "integer": 0.5},
}


def _norm(text: str) -> str:
    return " ".join(_EXPAND.get(w, w) for w in clean(text).split())


def header_similarity(col: str, field: FieldSpec) -> float:
    names = [*field.synonyms, field.id.split(".")[1].replace("_", " ")]
    c = _norm(col)
    return max(max(fuzz.token_sort_ratio(c, n) / 100, JaroWinkler.similarity(c, n)) for n in map(_norm, names))


def field_match(p: ColumnProfile, field: FieldSpec, header: float | None = None) -> FieldMatch:
    h = header_similarity(p.column, field) if header is None else header
    v = p.validator_hits.get(field.id, 0.0)
    if field.validator == {"non_empty": True} and h < WEAK_HEADER_MIN:
        v = 0.0
    t = _TYPE_FIT.get(field.type, {}).get(p.inferred_type, 0.0)
    s = W_HEADER * h + W_VALUE * v + W_TYPE * t
    return FieldMatch(column=p.column, field_id=field.id, score=min(s, GATE_CAP) if v < GATE_VALUE else s,
                      header_score=h, value_score=v, type_score=t)


def assign(profiles: list[ColumnProfile], fields: list[FieldSpec], no_field_score: float) -> list[FieldMatch]:
    """Best one-to-one column -> field matches; columns that prefer "no field" are omitted."""
    matches, rest = [], list(profiles)
    for f in (f for f in fields if f.repeatable and f.header_pattern):
        pattern = re.compile(f.header_pattern, re.I)
        matches += [field_match(p, f, header=1.0) for p in rest if pattern.fullmatch(p.column.strip())]
        rest = [p for p in rest if not pattern.fullmatch(p.column.strip())]
    singles = [f for f in fields if not f.repeatable]
    if not rest or not singles:
        return matches
    grid = [[field_match(p, f) for f in singles] for p in rest]
    s = np.array([[m.score for m in row] for row in grid])
    s = np.hstack([s, np.full((len(rest), len(rest)), no_field_score)])
    rows, cols = linear_sum_assignment(s, maximize=True)
    return matches + [grid[r][c] for r, c in zip(rows, cols) if c < len(singles)]
