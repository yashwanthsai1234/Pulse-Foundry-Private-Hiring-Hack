r"""Value validators: one predicate per canonical field, built from the pack's `validator:` specs (§9.1).

Sherlock/Valentine-style instance features: the share of a column's values that pass a field's validator
is the strongest evidence for that field (see profile.py / mapper.py).

Sources:
- https://arxiv.org/abs/1905.10688 (Sherlock: value-based semantic type detection)
- https://arxiv.org/pdf/2010.07386 (Valentine: instance-based matchers)
- https://docs.python.org/3/library/re.html#regular-expression-syntax (\w is Unicode for str patterns)
- https://www.w3.org/International/questions/qa-personal-names (names are not ASCII)
"""
from __future__ import annotations

import re
from collections.abc import Callable

from sot.core.pack import Pack
from sot.normalize.dates import parse_date
from sot.normalize.shifts import parse_shift_token
from sot.normalize.numbers import parse_number
from sot.normalize.vocab import vocab_matcher

Validator = Callable[[str], bool]
_LAST_FIRST = re.compile(r"(?:[^\W\d_]|['’.\- ])+,\s*(?:[^\W\d_]|['’.\- ])+")  # [^\W\d_] = any Unicode letter
_ALPHA_TOKEN = re.compile(r"(?:[^\W\d_]|['’.\-])+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def _number(spec: dict) -> Validator:
    """Form, not range: impossible values must still map to their column so the checks can flag them.
    Only magnitudes far outside the field's scale (> 10x max) count as 'not this column'."""
    limit = 10 * spec["max"] if "max" in spec else float("inf")

    def check(v: str) -> bool:
        n = parse_number(v)
        return n is not None and abs(n) <= limit
    return check


_SIMPLE: dict[str, Validator] = {
    "date": lambda v: parse_date(v) is not None,
    "phone": lambda v: len(re.sub(r"\D", "", v)) in (10, 11),
    "email": lambda v: bool(_EMAIL.fullmatch(v.strip())),
    "shift_token_or_off": lambda v: parse_shift_token(v.strip()) is not None,
    "non_empty": lambda v: bool(v.strip()),
}


def _build(kind: str, arg, pack: Pack, in_vocab: Validator) -> Validator:
    if kind in _SIMPLE:
        return _SIMPLE[kind]
    if kind == "regex":
        pattern = re.compile(arg)
        return lambda v: bool(pattern.fullmatch(v.strip().upper()))
    if kind == "vocab":
        match = vocab_matcher(pack.vocabs[arg])
        return lambda v: match(v)[0] is not None
    if kind == "number":
        return _number(arg if isinstance(arg, dict) else {})
    if kind == "person_name":
        return lambda v: not in_vocab(v) and bool(
            _LAST_FIRST.fullmatch(v.strip()) or (2 <= len(v.split()) <= 4 and all(_ALPHA_TOKEN.fullmatch(t) for t in v.split())))
    if kind == "single_name_token":
        return lambda v: not in_vocab(v) and 1 <= len(v.split()) <= 2 and all(_ALPHA_TOKEN.fullmatch(t) for t in v.split())
    raise ValueError(f"unknown validator kind: {kind}")


def build_validators(pack: Pack) -> dict[str, Validator]:
    """field_id -> predicate over a raw cell string."""
    matchers = [vocab_matcher(v) for v in pack.vocabs.values()]

    def in_vocab(v: str) -> bool:
        return any(m(v)[0] is not None for m in matchers)

    out: dict[str, Validator] = {}
    for fid, spec in pack.fields.items():
        if spec.validator:
            ((kind, arg),) = spec.validator.items()
            out[fid] = _build(kind, arg, pack, in_vocab)
    return out
