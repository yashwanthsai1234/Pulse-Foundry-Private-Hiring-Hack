"""Text-PDF pages the extraction could not read: an empty placeholder table keeps the page visible, and a page that
looks like a schedule is worth a page_reader agent.

Sources:
- https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_text
"""
from __future__ import annotations

import re

import polars as pl
import pymupdf

from sot.core.models import ExtractionInfo, FileRef, RawTable

DAYS = re.compile(r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
SHIFT = re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]m?\s*[-\u2013]\s*\d{1,2}", re.I)


def looks_like_schedule(text: str) -> bool:
    return len({d.lower()[:3] for d in DAYS.findall(text)}) >= 3 or len(SHIFT.findall(text)) >= 3


def blank_pages(f: FileRef, tables: list[RawTable]) -> list[RawTable]:
    """One empty table for every page of a text PDF where extraction found no table, so the page stays visible."""
    found = {t.page for t in tables}
    out = []
    with pymupdf.open(f.path) as doc:
        for n, page in enumerate(doc, start=1):
            if n not in found:
                out.append(RawTable(
                    table_id=f"{f.file_id[:12]}:{n}:0", file=f, parser="pdf_text", page=n, header=[],
                    df=pl.DataFrame({"_src_row": []}, schema={"_src_row": pl.Int64}), context={"page_text": page.get_text()},
                    extraction=ExtractionInfo(method="none", score=0.0, notes=["no table found on the page"])))
    return out
