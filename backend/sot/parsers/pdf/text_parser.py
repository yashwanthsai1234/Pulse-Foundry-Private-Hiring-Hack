"""PdfTextParser: text-layer PDFs -> one RawTable per schedule table, via the extraction cascade.

Per page the methods of `methods.METHODS` run in order; the first whose score (scoring.score_grid, the minimum over the
page's tables) reaches settings["pdf.method_min_score"] wins. Otherwise the best result is kept and the notes say so.
`_src_row` is the 1-based row number inside the table (header = 1). A first table without title on a later page
continues the previous page's last table and inherits its title, facility hint and legend (RC10).

Sources:
- pdfplumber (page.find_tables, extract_words): https://github.com/jsvine/pdfplumber
- PyMuPDF (Page.get_text, find_tables): https://pymupdf.readthedocs.io/en/latest/page.html
- Cascade rationale and measurements: docs/pdf_spike.md, docs/research/A2.md
"""
from __future__ import annotations

import json
from pathlib import Path

import pdfplumber
import pymupdf

from sot.core.models import ExtractionInfo, FileRef, RawTable, SniffResult
from sot.core.registry import ExtractContext, register_parser
from sot.parsers.base import build_raw_table
from sot.parsers.pdf.context import Line, group_lines, page_contexts
from sot.parsers.pdf.legend import parse_legend
from sot.parsers.pdf.methods import METHODS, Grid, PageView
from sot.parsers.pdf.scoring import completeness, score_grid

SAMPLE_PAGES = 5


def mean_text_chars(path: Path) -> float:
    """Mean characters of text layer per page over the first pages (0 for images, scans)."""
    with pymupdf.open(path) as doc:
        pages = [doc[i] for i in range(min(len(doc), SAMPLE_PAGES))]
        return sum(len(p.get_text().strip()) for p in pages) / max(len(pages), 1)


def run_cascade(page: PageView, lines: list[Line], min_score: float) -> tuple[str, float, list[Grid], list[str]]:
    """(method, score, grids, notes) of the first method that passes, else of the best one.

    score = worst grid score x completeness (extracted rows / row-like text lines of the page)."""
    texts = [ln.text.split() for ln in lines]
    best: tuple[str, float, list[Grid]] = ("none", 0.0, [])
    notes: list[str] = []
    for name, method in METHODS:
        grids = method(page)
        score = min((score_grid(g.rows) for g in grids), default=0.0)
        score *= completeness(texts, sum(len(g.rows) - 1 for g in grids))
        if score >= min_score:
            return name, score, grids, notes
        notes.append(f"{name}: score {score:.2f} < {min_score:.2f} ({len(grids)} tables)")
        if score > best[1]:
            best = (name, score, grids)
    return (*best, [*notes, "no method reached the minimum score; kept the best"])


def _raw_table(file: FileRef, page_no: int, index: int, grid: Grid, ctx: dict[str, str], info: ExtractionInfo) -> RawTable:
    boxes = {f"{i}:{j}": b for i, row in enumerate(grid.boxes[1:]) for j, b in enumerate(row)}
    return build_raw_table(file, "pdf_text", grid.rows[0], grid.rows[1:], list(range(2, len(grid.rows) + 1)),
                           method=info.method, score=info.score, notes=info.notes, index=index, page=page_no,
                           context=ctx, cell_bboxes=boxes)


@register_parser
class PdfTextParser:
    name = "pdf_text"

    def sniff(self, head: bytes, path: Path) -> SniffResult:
        if not head.startswith(b"%PDF-"):
            return SniffResult(parser=self.name, score=0.0, reason="not a PDF")
        chars = mean_text_chars(path)
        score = 0.95 if chars >= 100 else 0.6 if chars >= 20 else 0.1
        return SniffResult(parser=self.name, score=score, reason=f"PDF with {chars:.0f} text chars/page",
                           details={"chars_per_page": chars})

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]:
        min_score = ctx.settings["pdf.method_min_score"]
        tables: list[RawTable] = []
        with pdfplumber.open(file.path) as plumber, pymupdf.open(file.path) as mupdf:
            for n, (pp, mp) in enumerate(zip(plumber.pages, mupdf), start=1):
                lines = group_lines(pp.extract_words(extra_attrs=["size"]))
                method, score, grids, notes = run_cascade(PageView(pp, mp), lines, min_score)
                page_text = pp.extract_text() or ""
                info = ExtractionInfo(method=method, score=score, notes=notes)
                for i, (grid, around) in enumerate(zip(grids, page_contexts(lines, [g.bbox for g in grids]))):
                    meta = {**around, "facility_hint": around["title"], "page_text": page_text,
                            "legend_json": json.dumps(parse_legend(around["footnote"]))}
                    if tables and i == 0 and not around["title"]:  # table continued from the previous page
                        before = tables[-1].context
                        meta |= {k: before[k] for k in ("title", "subtitle", "facility_hint")}
                        if meta["legend_json"] == "{}":
                            meta["legend_json"] = before["legend_json"]
                    tables.append(_raw_table(file, n, i, grid, meta, info))
        return tables
