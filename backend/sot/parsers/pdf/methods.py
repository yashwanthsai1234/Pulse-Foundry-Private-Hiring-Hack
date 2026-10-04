"""The four table-extraction methods of the cascade. Each takes a `PageView` and returns the schedule tables it found
as `Grid`s (header row first, one bbox per cell). Shared clean-up lives in `finish`.

  pdf.lines  pdfplumber, ruling lines as cell borders (ruled grids)
  pdf.mupdf  PyMuPDF Page.find_tables()
  pdf.words  own word clustering: rows by y, columns from x corridors (wrapped-name aware)
  pdf.text   pdfplumber, word alignment as virtual borders (last resort; never won in the spike)

Sources:
- pdfplumber table settings (lines/text strategies, snap/join tolerance): https://github.com/jsvine/pdfplumber#table-extraction-settings
- PyMuPDF Page.find_tables: https://pymupdf.readthedocs.io/en/latest/page.html#Page.find_tables
- Camelot Lattice (ruled) vs Stream (whitespace) flavors: https://github.com/camelot-dev/camelot
- Nurminen, thesis behind pdfplumber's text strategy: https://trepo.tuni.fi/handle/123456789/21520
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from functools import reduce
from itertools import pairwise

import pdfplumber
import pymupdf

from sot.core.models import BBox
from sot.normalize.shifts import parse_shift_token
from sot.parsers.pdf.context import Line, group_lines
from sot.parsers.pdf.scoring import day_columns, header_score, is_body_line


@dataclass
class PageView:
    plumber: pdfplumber.page.Page
    mupdf: pymupdf.Page


@dataclass
class Grid:
    rows: list[list[str]]  # rows[0] = header
    boxes: list[list[BBox]]

    @property
    def bbox(self) -> BBox:
        cells = [b for row in self.boxes for b in row]
        return (min(b[0] for b in cells), min(b[1] for b in cells), max(b[2] for b in cells), max(b[3] for b in cells))


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _fill_boxes(cells: list[list[BBox | None]]) -> list[list[BBox]]:
    """Replace missing (merged) cell boxes by column x-range x row y-range taken from the neighbours."""
    col_x: dict[int, tuple[float, float]] = {}
    for row in cells:
        for j, c in enumerate(row):
            if c:
                col_x.setdefault(j, (c[0], c[2]))
    out = []
    for row in cells:
        known = [c for c in row if c]
        top, bottom = min(c[1] for c in known), max(c[3] for c in known)
        out.append([c or (*col_x[j][:1], top, col_x[j][1], bottom) for j, c in enumerate(row)])
    return out


def _header_index(rows: list[list[str]]) -> int | None:
    """Row where the header block starts: the best-scoring of the first 4 rows, or an earlier row with day names."""
    best = max(range(min(4, len(rows))), key=lambda i: header_score(rows[i]), default=None)
    if best is None or header_score(rows[best]) == 0:
        return None
    return min(best, next((i for i in range(best) if day_columns(rows[i])), best))


def _stack_header(rows: list[list[str]], boxes: list[list[BBox]]) -> None:
    """A header drawn on several lines ("Mon" / "Staff Role" / "09/14", borderless text strategy) becomes one row:
    the rows above the first row holding shift tokens are joined cell by cell."""
    body = next((i for i, r in enumerate(rows) if sum(parse_shift_token(c) is not None for c in r if c) >= 3), 1)
    if body > 1:
        rows[:body] = [[" ".join(c for c in cells if c) for cells in zip(*rows[:body])]]
        boxes[:body] = [[reduce(_union, col) for col in zip(*boxes[:body])]]


def _is_token(cell: str) -> bool:
    tok = parse_shift_token(cell) if cell else None
    return tok is not None and not tok.note


def _drop_noise(rows: list[list[str]], boxes: list[list[BBox]]) -> None:
    """Drop trailing rows without shift tokens (a footnote that fell into the table)."""
    days = day_columns(rows[0])
    keep = list(range(len(rows)))
    while len(keep) > 1 and sum(_is_token(rows[keep[-1]][j]) for j in days) < 2:
        keep.pop()
    rows[:], boxes[:] = [rows[i] for i in keep], [boxes[i] for i in keep]


def _merge_wrapped(rows: list[list[str]], boxes: list[list[BBox]]) -> None:
    """A row with text only in the first column is the wrapped rest of a name: join it to the closer neighbour."""
    i = 1
    while i < len(rows):
        row = rows[i]
        if row[0] and not any(row[1:]) and len(rows) > 2:
            gap_prev = boxes[i][0][1] - boxes[i - 1][0][3] if i > 1 else float("inf")
            gap_next = boxes[i + 1][0][1] - boxes[i][0][3] if i + 1 < len(rows) else float("inf")
            if min(gap_prev, gap_next) != float("inf"):
                j = i - 1 if gap_prev <= gap_next else i + 1
                rows[j][0] = f"{rows[j][0]} {row[0]}" if j < i else f"{row[0]} {rows[j][0]}"
                boxes[j] = [_union(a, b) if k == 0 else a for k, (a, b) in enumerate(zip(boxes[j], boxes[i]))]
                del rows[i], boxes[i]
                continue
        i += 1


def finish(raw: list[list[str | None]], cells: list[list[BBox | None]]) -> list[Grid]:
    """Normalize one extracted table: clean text, drop empty columns, cut above the header, split at repeated headers."""
    rows = [[_clean(c) for c in r] for r in raw]
    keep = [j for j in range(len(rows[0])) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    boxes = [[r[j] for j in keep] for r in _fill_boxes(cells)]
    live = [i for i, r in enumerate(rows) if any(r)]  # blank spacer rows (zebra stripes, text strategy) go
    rows, boxes = [rows[i] for i in live], [boxes[i] for i in live]
    grids: list[Grid] = []
    start = _header_index(rows)
    while start is not None:
        nxt = next((i for i in range(start + 1, len(rows)) if len(day_columns(rows[i])) >= 4), len(rows))
        g_rows, g_boxes = rows[start:nxt], boxes[start:nxt]
        _stack_header(g_rows, g_boxes)
        _merge_wrapped(g_rows, g_boxes)
        _drop_noise(g_rows, g_boxes)
        if len(g_rows) > 1 and day_columns(g_rows[0]):  # header-only or day-less = not a schedule table
            grids.append(Grid(g_rows, g_boxes))
        start = nxt if nxt < len(rows) else None
    return grids


def _plumber(page: PageView, settings: dict) -> list[Grid]:
    grids = []
    for t in page.plumber.find_tables(settings):
        cells = [list(r.cells) for r in t.rows]
        grids += finish(t.extract(), cells)
    return grids


def lines(page: PageView) -> list[Grid]:
    return _plumber(page, {"vertical_strategy": "lines", "horizontal_strategy": "lines"})


def text(page: PageView) -> list[Grid]:
    return _plumber(page, {"vertical_strategy": "text", "horizontal_strategy": "text",
                           "snap_tolerance": 3, "join_tolerance": 3})


def mupdf(page: PageView) -> list[Grid]:
    grids = []
    for t in page.mupdf.find_tables().tables:
        grids += finish(t.extract(), [list(r.cells) for r in t.rows])
    return grids


def _is_header(line: Line) -> bool:
    return len(day_columns([w["text"] for w in line.words])) >= 5


def _x_clusters(words_: list[dict], size: float) -> list[tuple[float, float]]:
    """Merge the x-ranges of words closer than 0.6 x font size: gaps between clusters are column corridors."""
    spans: list[list[float]] = []
    for w in sorted(words_, key=lambda w: w["x0"]):
        if spans and w["x0"] - spans[-1][1] < 0.6 * size:
            spans[-1][1] = max(spans[-1][1], w["x1"])
        else:
            spans.append([w["x0"], w["x1"]])
    return [(a, b) for a, b in spans]


def _widest_gap(lo: float, hi: float, words_: list[dict]) -> float:
    """Middle of the widest x-range in [lo, hi] that no word covers; the plain midpoint when there is none.
    A long name ('Jessica Richardson') reaches far past its header but still leaves a gap before the next column."""
    covered = sorted((max(w["x0"], lo), min(w["x1"], hi)) for w in words_ if w["x1"] > lo and w["x0"] < hi)
    best, cursor = (0.0, (lo + hi) / 2), lo
    for a, b in [*covered, (hi, hi)]:
        if a - cursor > best[0]:
            best = (a - cursor, (cursor + a) / 2)
        cursor = max(cursor, b)
    return best[1]


def _table_lines(lines_: list[Line], h: int) -> list[Line]:
    """Lines under the header line that belong to the table: stop at a big vertical gap or the next header."""
    body, gaps = [], []
    prev = lines_[h]
    for line in lines_[h + 1:]:
        gap = line.top - prev.bottom
        limit = max(prev.size, 2 * statistics.median(gaps)) if gaps else 2 * prev.size
        if _is_header(line) or gap > limit:
            break
        body.append(line)
        gaps.append(gap)
        prev = line
    return body


def _mupdf_words(page: pymupdf.Page) -> list[dict]:
    """PyMuPDF words as pdfplumber-style dicts (size = box height). pdfplumber misreads ligature glyphs from
    LibreOffice/Word ("Sofiaa", "Thuu"); PyMuPDF decodes them correctly."""
    return [{"x0": x0, "x1": x1, "top": top, "bottom": bottom, "size": bottom - top, "text": text}
            for x0, top, x1, bottom, text, *_ in page.get_text("words")]


def words(page: PageView) -> list[Grid]:
    lines_ = group_lines(_mupdf_words(page.mupdf))
    grids = []
    for h in (i for i, ln in enumerate(lines_) if _is_header(ln)):
        table = [lines_[h], *_table_lines(lines_, h)]
        size = table[0].size
        n_head = max(1, next((k for k, ln in enumerate(table) if is_body_line(ln.text.split())), 1))  # header may span lines
        head = [w for ln in table[:n_head] for w in ln.words]
        body_words = [w for ln in table for w in ln.words]
        spans = _x_clusters(body_words, size)
        if len(spans) == len(_x_clusters(head, size)):
            inner = [(a[1] + b[0]) / 2 for a, b in pairwise(spans)]
        else:  # corridors blurred by long cells: cut each header gap at its widest whitespace across all rows
            spans = _x_clusters(head, size)
            rows_ = [w for ln in table if is_body_line(ln.text.split()) for w in ln.words]  # not footnotes/titles
            inner = [_widest_gap(a[1], b[0], rows_) for a, b in pairwise(spans)]
        x0 = min(w["x0"] for w in body_words) - 1
        x1 = max(w["x1"] for w in body_words) + 1
        edges = [x0, *inner, x1]
        raw, cells = [], []
        for line in table:
            row = [[] for _ in spans]
            for w in sorted(line.words, key=lambda w: w["x0"]):
                centre = (w["x0"] + w["x1"]) / 2
                row[max(k for k in range(len(spans)) if edges[k] <= centre)].append(w["text"])
            raw.append([" ".join(c) for c in row])
            cells.append([(edges[k], line.top, edges[k + 1], line.bottom) for k in range(len(spans))])
        grids += finish(raw, cells)
    return grids


# Order from docs/pdf_spike.md: exact ruled-grid methods first, generic word clustering next, pdf.text last.
METHODS = (("pdf.lines", lines), ("pdf.mupdf", mupdf), ("pdf.words", words), ("pdf.text", text))
