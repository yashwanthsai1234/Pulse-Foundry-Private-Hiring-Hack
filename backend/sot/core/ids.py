"""Stable identifiers: content hashes, fingerprints, task ids.

Sources:
- https://docs.python.org/3/library/hashlib.html (sha256 file ids, sha1 short ids)
- https://docs.python.org/3/library/json.html#json.dumps (sort_keys + separators give canonical JSON)
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short_hash(*parts: Any, n: int = 10) -> str:
    """Deterministic short sha1 over the string form of the parts."""
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:n]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def issue_fingerprint(check_id: str, entity_ids: list[str], period_start: Any, period_end: Any, key: str) -> str:
    return short_hash(check_id, ",".join(sorted(entity_ids)), period_start, period_end, key, n=16)
