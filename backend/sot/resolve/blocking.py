"""Blocking: cheap keys that bring likely matches together so we never compare all n^2 pairs.

Sources:
- https://moj-analytical-services.github.io/splink/topic_guides/blocking/blocking_rules.html (blocking rules, union of rules)
- https://en.wikipedia.org/wiki/Record_linkage#Blocking (why blocking, standard techniques)
"""
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from typing import Any
from collections.abc import Callable

from sot.core.models import SourceRecord

BUCKET_CAP = 200


def table_of(record_id: str) -> str:
    return record_id.rsplit(":", 1)[0]


def canonical_number(value: Any) -> str:
    """Silver's canonical licence form: letters + separators + digits -> 'PREFIX-DIGITS' ('rn 551203', 'RN–551203' -> 'RN-551203')."""
    text = str(value).upper()
    m = re.fullmatch(r"([A-Z]+)[\s\-–—_./]*(\d[\d\s\-–—_./]*)", text.strip())
    return f"{m[1]}-{re.sub(r'\D', '', m[2])}" if m else re.sub(r"\s", "", text)


PARTS: dict[str, Callable[[SourceRecord], Any]] = {
    "credential_number": lambda r: r.fields.get("credential.number"),
    "soundex_family": lambda r: r.person_key and r.person_key.soundex_family,
    "facility": lambda r: r.fields.get("person.facility"),
    "family3": lambda r: r.person_key and r.person_key.family and r.person_key.family[:3],  # survives a typo or a compound surname
    "given_initial": lambda r: r.person_key and r.person_key.given_initial,
}


def block(records: list[SourceRecord], rules: list[list[str]], cap: int = BUCKET_CAP) -> set[tuple[str, str]]:
    """Candidate record-id pairs (sorted tuples) sharing every part of at least one rule; never two records of one table.
    A bucket larger than `cap` is split by facility."""
    pairs: set[tuple[str, str]] = set()
    for rule in rules:
        buckets: dict[tuple, list[SourceRecord]] = defaultdict(list)
        for r in records:
            vals = tuple(PARTS[p](r) for p in rule)
            if all(vals):
                buckets[vals].append(r)
        for bucket in buckets.values():
            groups = [bucket]
            if len(bucket) > cap:
                by_fac: dict[Any, list[SourceRecord]] = defaultdict(list)
                for r in bucket:
                    by_fac[r.fields.get("person.facility")].append(r)
                groups = list(by_fac.values())
            for g in groups:
                pairs.update(
                    (min(a.record_id, b.record_id), max(a.record_id, b.record_id))
                    for a, b in combinations(g, 2)
                    if table_of(a.record_id) != table_of(b.record_id)
                )
    return pairs
