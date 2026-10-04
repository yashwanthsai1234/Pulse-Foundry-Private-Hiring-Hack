"""Model <-> row persistence shared by all stages. Stages never write SQL for silver data themselves.

JSON columns arrive decoded from DB.query, so rows validate straight into the models.

Sources:
- https://docs.pydantic.dev/latest/concepts/models/#model-validate (rows -> models)
- https://docs.pola.rs/api/python/stable/reference/api/polars.read_parquet.html (bronze tables live in Parquet)
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from sot.core.models import (
    ExtractionInfo, FileRef, Issue, Mapping, RawTable, ShiftRecord, SourceRecord,
)
from sot.store.db import DB


# ---------- files ----------
def save_file(db: DB, f: FileRef, run_id: str, status: str, parser: str | None = None,
              score: float | None = None, bids: list | None = None) -> None:
    db.insert("files", [{**f.model_dump(), "run_id": run_id, "parser": parser, "sniff_score": score,
                         "bids": bids or [], "status": status}], replace=True)


def known_file(db: DB, file_id: str) -> bool:
    """Already ingested? Quarantined and failed files may be retried (R1-06)."""
    return bool(db.query("SELECT 1 FROM files WHERE file_id = ? AND status NOT IN ('quarantined', 'failed')", [file_id]))


def load_file(db: DB, file_id: str) -> FileRef:
    r = db.query("SELECT file_id, file_name, path, size, received_at FROM files WHERE file_id = ?", [file_id])[0]
    return FileRef(**r)


# ---------- raw tables (data in Parquet, metadata in DuckDB) ----------
def save_raw_table(db: DB, t: RawTable, bronze_dir: Path) -> None:
    path = bronze_dir / f"{t.table_id.replace(':', '_')}.parquet"
    t.df.write_parquet(path)
    db.insert("raw_tables", [{
        "table_id": t.table_id, "file_id": t.file.file_id, "parser": t.parser, "page": t.page, "sheet": t.sheet,
        "header": t.header, "n_rows": t.df.height, "context": t.context, "extraction": t.extraction,
        "parquet_path": str(path), "cell_bboxes": t.cell_bboxes or {},
    }], replace=True)


def load_raw_table(db: DB, table_id: str) -> RawTable:
    r = db.query("SELECT * FROM raw_tables WHERE table_id = ?", [table_id])[0]
    bboxes = r["cell_bboxes"] or None
    return RawTable(
        table_id=r["table_id"], file=load_file(db, r["file_id"]), parser=r["parser"], page=r["page"],
        sheet=r["sheet"], header=r["header"], df=pl.read_parquet(r["parquet_path"]),
        cell_bboxes={k: tuple(v) for k, v in bboxes.items()} if bboxes else None,
        context=r["context"], extraction=ExtractionInfo(**r["extraction"]),
    )


# ---------- mappings ----------
def save_mapping(db: DB, m: Mapping, status: str) -> None:
    db.insert("mappings", [{
        "table_id": m.table_id, "template_id": m.template_id, "confidence": m.confidence,
        "matches": [x.model_dump() for x in m.matches], "unmapped": m.unmapped_columns,
        "missing_required": m.missing_required, "source": m.source, "contract_id": m.contract_id,
        "drift": m.drift, "status": status,
    }], replace=True)


# ---------- silver ----------
def save_records(db: DB, records: list[SourceRecord], shifts: list[ShiftRecord]) -> None:
    db.insert("source_records", [{
        "record_id": r.record_id, "table_id": r.record_id.rsplit(":", 1)[0], "template_id": r.template_id,
        "entity": r.entity, "fields": r.fields, "raw": r.raw,
        "person_key": r.person_key.model_dump() if r.person_key else None,
        "loc": r.loc, "parse_issues": r.parse_issues,
    } for r in records], replace=True)
    db.insert("shifts_silver", [{
        "shift_id": s.shift_id, "record_id": s.record_id, "facility_id": s.facility_id, "role": s.role,
        "work_date": s.work_date, "token": s.token, "start_t": s.start, "end_t": s.end, "hours": s.hours,
        "hours_source": s.hours_source, "loc": s.loc,
    } for s in shifts], replace=True)


def delete_table_records(db: DB, table_id: str) -> None:
    """Remove silver rows of one table (before it is re-mapped after an agent result)."""
    db.execute("DELETE FROM shifts_silver WHERE record_id IN (SELECT record_id FROM source_records WHERE table_id = ?)",
               [table_id])
    db.execute("DELETE FROM source_records WHERE table_id = ?", [table_id])


def load_records(db: DB) -> list[SourceRecord]:
    return [SourceRecord.model_validate(r) for r in db.query("SELECT * FROM source_records ORDER BY record_id")]


def load_shifts(db: DB) -> list[ShiftRecord]:
    rows = db.query('SELECT *, start_t AS start, end_t AS "end" FROM shifts_silver ORDER BY shift_id')
    return [ShiftRecord.model_validate(r) for r in rows]


# ---------- issues ----------
def load_issues(db: DB, active_only: bool = True) -> list[Issue]:
    where = "WHERE active" if active_only else ""
    return [Issue(**{**r, "entity_ids": r["entity_ids"] or [], "evidence": r["evidence"] or []})
            for r in db.query(f"SELECT * FROM issues {where}")]
