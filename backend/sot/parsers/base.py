"""Shared table helpers: header detection and RawTable construction (IMPLEMENTATION §8.1).

Header detection follows the DuckDB sniffer idea (a header row is text that the rows below
contradict by type) plus a title-row guard: rows much narrower than the table are skipped.

Wrapped hyphens ("Washington- Greene", "3p- 11p": a cell wrapped after the hyphen) are rejoined; the rule is the
usual de-hyphenation one, a hyphen followed by a space between two letters.

Sources:
- https://pymupdf.readthedocs.io/en/latest/recipes-text.html (text extraction; line-end hyphens stay in the text)
- https://duckdb.org/2023/10/27/csv-sniffer.html (header = first row whose types differ from the data below)
- https://arxiv.org/abs/1811.11242 (CleverCSV: consistency of row shapes beats csv.Sniffer on messy files)
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

import polars as pl

from sot.core.models import BBox, ExtractionInfo, FileRef, RawTable

_WRAPPED_HYPHEN = re.compile(r"(?<=[^\W\d_])- (?=[^\W\d_])|(?<=\d[ap])- (?=\d)", re.IGNORECASE)
_NUMBER = re.compile(r"^[-+]?\$?\d[\d,]*(\.\d+)?%?$")
_DATE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}([T ].*)?|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})$")


def _kind(cell: str | None) -> str:
    c = (cell or "").strip()
    if not c:
        return "empty"
    return "number" if _NUMBER.match(c) else "date" if _DATE.match(c) else "text"


def cell_to_str(v: object) -> str | None:
    """Source cell -> text: dates ISO, integral floats without ".0", blank -> None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def detect_header_row(rows: list[list[str | None]], max_scan: int = 20) -> int:
    """Index of the header row among the first `max_scan` rows.

    A header is the first row (not much narrower than the table) whose cells are all text and unique, and that some
    cell below contradicts by type (a number or date under a text header). An all-text table falls back to the first row
    with the modal width.
    """
    kinds = [[_kind(c) for c in r] for r in rows[:max_scan + 5]]
    widths = [sum(k != "empty" for k in ks) for ks in kinds[:max_scan]]
    if not any(widths):
        return 0
    modal = Counter(w for w in widths if w).most_common(1)[0][0]
    wide_enough = [i for i, w in enumerate(widths) if w * 2 >= modal]
    for i in wide_enough:
        cells = [(j, k) for j, k in enumerate(kinds[i]) if k != "empty"]
        texts = [(rows[i][j] or "").strip().lower() for j, _ in cells]
        if any(k != "text" for _, k in cells) or len(set(texts)) / len(texts) < 0.7:
            continue
        below = [ks for ks in kinds[i + 1:i + 6] if any(k != "empty" for k in ks)]
        if any(d in ("number", "date") for ks in below for j, _ in cells if (d := ks[j] if j < len(ks) else "empty")):
            return i
    return next((i for i in wide_enough if widths[i] >= modal), 0)


def _unique(names: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def build_raw_table(file: FileRef, parser: str, header: list[str], rows: list[list[str | None]],
                    src_rows: list[int], *, method: str, score: float, index: int = 0,
                    page: int | None = None, sheet: str | None = None, context: dict[str, str] | None = None,
                    cell_bboxes: dict[str, BBox] | None = None, notes: list[str] | None = None) -> RawTable:
    """Clean (strip, drop empty rows/cols, unique headers) and build the all-Utf8 DataFrame plus `_src_row`."""
    width = len(header)
    cleaned = [[_WRAPPED_HYPHEN.sub("-", c).strip() or None if c is not None else None for c in (r + [None] * width)[:width]]
               for r in rows]
    keep_rows = [i for i, r in enumerate(cleaned) if any(r)]
    names = [h.strip() for h in header]
    keep_cols = [j for j in range(width) if names[j] or any(cleaned[i][j] for i in keep_rows)]
    header_out = _unique([names[j] or f"column_{j + 1}" for j in keep_cols])
    data = {h: [cleaned[i][j] for i in keep_rows] for h, j in zip(header_out, keep_cols)}
    df = pl.DataFrame(data, schema={h: pl.Utf8 for h in header_out}).with_columns(
        pl.Series("_src_row", [src_rows[i] for i in keep_rows], dtype=pl.Int64))
    return RawTable(table_id=f"{file.file_id[:12]}:{page or sheet or 0}:{index}", file=file, parser=parser,
                    page=page, sheet=sheet, header=header_out, df=df, cell_bboxes=cell_bboxes,
                    context=context or {}, extraction=ExtractionInfo(method=method, score=score, notes=notes or []))


def grid_to_table(file: FileRef, parser: str, grid: list[list[str | None]], src_rows: list[int], *,
                  score: float, sheet: str | None = None) -> RawTable | None:
    """Header-detect a raw cell grid and build its table; None when the grid has no cells."""
    if not any(c and c.strip() for r in grid for c in r):
        return None
    h = detect_header_row(grid)
    width = max(len(r) for r in grid[h:])
    header = [(c or "") for c in grid[h]] + [""] * (width - len(grid[h]))
    norm = lambda r: [(c or "").strip().lower() for c in r]  # noqa: E731
    keep = [i for i in range(h + 1, len(grid)) if norm(grid[i]) != norm(grid[h])]  # paginated exports repeat the header
    return build_raw_table(file, parser, header, [grid[i] for i in keep], [src_rows[i] for i in keep],
                           method=parser, score=score, sheet=sheet)
