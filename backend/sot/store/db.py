"""DuckDB access: one connection per process guarded by a lock (IMPLEMENTATION §5). query() decodes JSON columns.

Sources:
- DuckDB Python DB-API (execute, parameters): https://duckdb.org/docs/stable/clients/python/dbapi
- JSON type (columns come back as text, decoded in query): https://duckdb.org/docs/stable/data/json/overview
- Bulk loading: executemany is slow, insert from an Arrow table instead:
  https://duckdb.org/docs/stable/guides/performance/import and https://duckdb.org/docs/stable/guides/python/import_arrow
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
from pydantic import BaseModel

SCHEMA = Path(__file__).with_name("schema.sql")
GOLD_TABLES = ("links", "persons", "person_records", "credentials", "shifts", "pay_periods", "claims", "golden_values")


def _cell(v: Any) -> Any:
    """Python value -> DuckDB parameter. dict/list/BaseModel become JSON text."""
    if isinstance(v, BaseModel):
        return v.model_dump_json()
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, default=str)
    return v


class DB:
    def __init__(self, path: Path | str = ":memory:"):
        self.con = duckdb.connect(str(path))
        self.lock = threading.RLock()
        with self.lock:
            self.con.execute(SCHEMA.read_text())

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> None:
        with self.lock:
            self.con.execute(sql, list(params) if params is not None else None)

    def query(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with self.lock:
            cur = self.con.execute(sql, list(params) if params is not None else None)
            cols = [(d[0], str(d[1]) == "JSON") for d in cur.description]
            return [{c: json.loads(v) if is_json and v is not None else v for (c, is_json), v in zip(cols, row, strict=True)}
                    for row in cur.fetchall()]

    def insert(self, table: str, rows: list[dict[str, Any]], replace: bool = False) -> None:
        """Insert dict rows; keys are column names. replace=True -> INSERT OR REPLACE (needs a primary key)."""
        if not rows:
            return
        cols = list(rows[0])
        batch = pa.table({c: [_cell(r.get(c)) for r in rows] for c in cols})
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        with self.lock:
            self.con.register("_batch", batch)
            try:
                self.con.execute(f"{verb} INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _batch")
            finally:
                self.con.unregister("_batch")

    def clear_gold(self) -> None:
        with self.lock:
            for t in GOLD_TABLES:
                self.con.execute(f"DELETE FROM {t}")
