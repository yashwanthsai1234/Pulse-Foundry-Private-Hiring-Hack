"""Text around a table: title, subtitle, footnote, plus word->line grouping shared with the word-clustering method.

Layout rules: lines above a table are its title (largest font) and subtitle; lines below are its footnote. When two
tables share a page, the gap between them is split at the first line in the gap's largest font (the next title):
before = footnote of the upper table, from there = title block of the lower table.

Sources:
- pdfplumber extract_words(extra_attrs=["size"]): https://github.com/jsvine/pdfplumber#extracting-text
- Nurminen, "Algorithmic extraction of data in tables in PDF documents" (row/column clustering from word boxes):
  https://trepo.tuni.fi/handle/123456789/21520
"""
from __future__ import annotations

from dataclasses import dataclass

from sot.core.models import BBox


@dataclass
class Line:
    words: list[dict]
    top: float
    bottom: float
    size: float

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in sorted(self.words, key=lambda w: w["x0"]))


def group_lines(words: list[dict], tol: float = 3.0) -> list[Line]:
    """Cluster words (pdfplumber dicts with 'size') into lines by their top coordinate."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [Line(ws, min(w["top"] for w in ws), max(w["bottom"] for w in ws), max(w["size"] for w in ws))
            for ws in lines]


def _title_block(lines: list[Line]) -> tuple[str, str]:
    if not lines:
        return "", ""
    big = max(ln.size for ln in lines)
    title = [ln.text for ln in lines if ln.size >= big - 0.5]
    rest = [ln.text for ln in lines if ln.size < big - 0.5]
    return " ".join(title), " ".join(rest)


def _title_start(lines: list[Line]) -> int:
    """Index of the first line in the largest font (the title); len(lines) when there are no lines."""
    big = max((ln.size for ln in lines), default=0)
    return next((k for k, ln in enumerate(lines) if ln.size >= big - 0.5), len(lines))


def page_contexts(lines: list[Line], tables: list[BBox]) -> list[dict[str, str]]:
    """One context dict per table bbox (ordered top to bottom)."""
    contexts = []
    for i, (_, top, _, bottom) in enumerate(tables):
        upper = tables[i - 1][3] if i else 0
        above = [ln for ln in lines if upper <= ln.top and ln.bottom <= top]
        if i:  # the gap holds the upper table's footnote followed by this table's title block
            above = above[_title_start(above):]
        lower = tables[i + 1][1] if i + 1 < len(tables) else float("inf")
        below = [ln for ln in lines if ln.top >= bottom and ln.bottom <= lower]
        if i + 1 < len(tables):
            below = below[: _title_start(below)]
        title, subtitle = _title_block(above)
        contexts.append({"title": title, "subtitle": subtitle, "footnote": " ".join(ln.text for ln in below)})
    return contexts
