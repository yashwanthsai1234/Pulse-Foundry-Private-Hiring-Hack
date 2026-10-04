"""Extraction score = header_score x cell_validity x shape (IMPLEMENTATION §8.5), plus header helpers.

`completeness` is applied by the cascade: a grid is only as good as the share of the page's row-like text lines it
holds (a borderless zebra table read as a 2-row grid has every cell valid and must still not score 1.00).

Sources:
- Camelot (Lattice/Stream) reports a per-table quality score instead of trusting the extractor:
  https://github.com/camelot-dev/camelot
- Table-structure evaluation by cell comparison (Göbel et al., ICDAR 2013 table competition):
  https://doi.org/10.1109/ICDAR.2013.292
"""
from __future__ import annotations

import re

from sot.normalize.shifts import parse_shift_token

_DAY = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)", re.IGNORECASE)
_NAME = re.compile(r"staff|name|employee|nurse|worker", re.IGNORECASE)
_ROLE = re.compile(r"role|position|title|job|discipline", re.IGNORECASE)


def is_body_line(words: list[str]) -> bool:
    """A text line with at least 3 shift tokens/OFF marks is a schedule row (or a wrapped part of one)."""
    tokens = [parse_shift_token(w) for w in words if w != "-"]
    return sum(t is not None and not t.note for t in tokens) >= 3  # "7a-3p," in a footnote has a note


def completeness(lines: list[list[str]], body_rows: int) -> float:
    """Extracted body rows / row-like text lines on the page, at most 1.0 (1.0 when the page has no such line)."""
    row_like = sum(is_body_line(words) for words in lines)
    return min(1.0, body_rows / row_like) if row_like else 1.0


def day_columns(header: list[str]) -> list[int]:
    return [i for i, h in enumerate(header) if _DAY.match(h.strip())]


def header_score(header: list[str]) -> float:
    """Share of expected header roles found: a name column, a role column, at least 5 day columns."""
    has_name = any(_NAME.search(h) for h in header)
    has_role = any(_ROLE.search(h) for h in header)
    return (has_name + has_role + min(len(day_columns(header)), 5) / 5) / 3


def score_grid(rows: list[list[str]]) -> float:
    """rows[0] is the header. 0.0 when there is no data row."""
    header, body = rows[0], rows[1:]
    days = day_columns(header)
    if not body or not days:
        return 0.0
    cells = [row[i] for row in body for i in days]
    validity = sum(parse_shift_token(c) is not None for c in cells) / len(cells)
    shape = 1.0 if len(days) == 7 else 0.8 if len(days) >= 5 else 0.5
    return header_score(header) * validity * shape
