"""JSON parser: list of objects, object of lists of objects (one table per key), or NDJSON.

Nested objects are flattened to dotted keys and lists are kept as JSON text. Own flattening is
used instead of pl.json_normalize: that returns typed columns (i64, list, "1.0" floats) that would
need a per-column cast back to text, as much code as flattening directly (docs/research/A1.md).

Sources:
- https://docs.pola.rs/api/python/stable/reference/api/polars.json_normalize.html (considered, rejected)
- https://github.com/ndjson/ndjson-spec (newline-delimited JSON)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from sot.core.models import FileRef, RawTable, SniffResult
from sot.core.registry import ExtractContext, register_parser
from sot.parsers.base import build_raw_table, cell_to_str

Records = list[tuple[int, dict]]  # (1-based source row, object)


def _records(items: list) -> Records | None:
    return [(i, o) for i, o in enumerate(items, 1)] if items and all(isinstance(o, dict) for o in items) else None


def load_tables(path: Path) -> list[Records]:
    """Record sets found in the file; [] when it is not tabular JSON."""
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        found = [_records(data)]
    elif isinstance(data, dict) and any(isinstance(v, list) for v in data.values()):
        found = [_records(v) for v in data.values() if isinstance(v, list)]
    else:
        try:
            objs = [(i, json.loads(line)) for i, line in enumerate(text.splitlines(), 1) if line.strip()]
        except json.JSONDecodeError:
            return []
        found = [objs if all(isinstance(o, dict) for _, o in objs) else None]
    return [r for r in found if r]


def _flatten(obj: dict, prefix: str = "") -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for k, v in obj.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = json.dumps(v) if isinstance(v, list) else cell_to_str(v)
    return out


@register_parser
class JsonParser:
    name: ClassVar[str] = "json"

    def sniff(self, head: bytes, path: Path) -> SniffResult:
        if head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] not in (b"{", b"[") or not load_tables(path):
            return SniffResult(parser=self.name, score=0.0, reason="not tabular JSON")
        return SniffResult(parser=self.name, score=0.95, reason="JSON records")

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]:
        tables = []
        for index, records in enumerate(load_tables(Path(file.path))):
            flat = [_flatten(o) for _, o in records]
            header = list(dict.fromkeys(k for r in flat for k in r))
            rows = [[r.get(h) for h in header] for r in flat]
            tables.append(build_raw_table(file, self.name, header, rows, [n for n, _ in records],
                                          method=self.name, score=1.0, index=index))
        return tables
