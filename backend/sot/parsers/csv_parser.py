"""CSV parser: encoding by BOM / UTF-8 test / cp1252 / charset-normalizer, delimiter by row-shape consistency.

Extraction uses the stdlib `csv` module, not Polars: it tracks the true source line of each record
(including multi-line quoted fields) which `_src_row` needs, and parses 200k rows well under 1 s
(docs/research/A1.md).

Sources:
- https://duckdb.org/2023/10/27/csv-sniffer.html (delimiter = most columns with most consistent rows)
- https://arxiv.org/abs/1811.11242 (CleverCSV: consistency-based dialect detection beats csv.Sniffer)
- https://www.rfc-editor.org/rfc/rfc4180 (a field with a comma must be quoted; unquoted ones add a field)
- https://charset-normalizer.readthedocs.io/en/latest/ (encoding detection API)
"""
from __future__ import annotations

import codecs
import csv
import io
from collections import Counter
from pathlib import Path
from typing import ClassVar

from charset_normalizer import from_bytes

from sot.core.models import FileRef, RawTable, SniffResult
from sot.core.registry import ExtractContext, register_parser
from sot.parsers.base import detect_header_row, grid_to_table
from sot.sniff.auction import HEAD_BYTES

DELIMITERS = [",", ";", "\t", "|"]
BOMS = {codecs.BOM_UTF8: "utf-8-sig", codecs.BOM_UTF16_LE: "utf-16", codecs.BOM_UTF16_BE: "utf-16"}
MAX_LINES = 200


def _is_utf8(data: bytes) -> bool:
    try:
        codecs.getincrementaldecoder("utf-8")().decode(data)  # final=False: a cut multibyte tail is fine
        return True
    except UnicodeDecodeError:
        return False


def detect_encoding(head: bytes) -> str:
    """BOM wins, except a UTF-8 BOM in front of bytes that are not UTF-8 (Latin-1 export, BOM added by a tool)."""
    for bom, name in BOMS.items():
        if head.startswith(bom) and (name != "utf-8-sig" or _is_utf8(head[len(bom):])):
            return name
    head = head.removeprefix(codecs.BOM_UTF8)
    if _is_utf8(head):
        return "utf-8"
    try:
        head.decode("cp1252")  # charset-normalizer guessed cp1250 for Western accents (docs/research/A1.md)
        return "cp1252"
    except UnicodeDecodeError:
        best = from_bytes(head).best()
        return best.encoding if best else "latin-1"


def _decode(raw: bytes, encoding: str) -> str:
    return raw.removeprefix(codecs.BOM_UTF8).decode(encoding, errors="replace")  # a stray UTF-8 BOM is never data


def _consistency(text: str, delimiter: str) -> tuple[float, int]:
    """(share of non-empty records with the modal field count, that count)."""
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)):
        if i >= MAX_LINES:
            break
        if any(c.strip() for c in row):
            rows.append(len(row))
    if not rows:
        return 0.0, 0
    count, n = Counter(rows).most_common(1)[0]
    return n / len(rows), count


def _merge_unquoted_names(grid: list[list[str]]) -> None:
    """Rows that all have one field more than the header, always split at a ", " ("REYES, SOFIA" typed without
    quotes), get that pair joined again. Ragged files that do not follow this pattern stay untouched."""
    if not grid:
        return
    width = len(grid[detect_header_row(grid)])
    wide = [r for r in grid if len(r) == width + 1]
    body = [r for r in grid if any(c.strip() for c in r)]
    if len(wide) < 3 or len(wide) < 0.8 * (len(body) - 1):
        return
    cut = Counter(j for r in wide for j in range(width) if r[j].strip() and r[j + 1].startswith(" "))
    if not cut or cut.most_common(1)[0][1] < len(wide):
        return
    j = cut.most_common(1)[0][0]
    for r in wide:
        r[j:j + 2] = [f"{r[j]},{r[j + 1]}"]


@register_parser
class CsvParser:
    name: ClassVar[str] = "csv"

    def sniff(self, head: bytes, path: Path) -> SniffResult:
        def no(reason: str) -> SniffResult:
            return SniffResult(parser=self.name, score=0.0, reason=reason)

        encoding = detect_encoding(head)
        if (b"\x00" in head and not encoding.startswith("utf-16")) or head.startswith((b"%PDF", b"PK")):
            return no("binary")
        text = _decode(head, encoding)
        if text.lstrip("﻿").lstrip()[:1] in ("{", "["):
            return no("looks like JSON")
        if len(head) >= HEAD_BYTES:
            text = text[:text.rfind("\n") + 1]  # drop the line cut by the 64 KB window
        best = max(((*_consistency(text, d), d) for d in DELIMITERS), key=lambda t: (t[0] if t[1] >= 2 else -1, t[1]))
        consistency, count, delimiter = best
        if count < 2:
            return no("no delimiter gives 2+ columns")
        return SniffResult(parser=self.name, score=0.5 + 0.5 * consistency,
                           reason=f"delimiter {delimiter!r}, {count} fields, {encoding}, consistency {consistency:.2f}",
                           details={"delimiter": delimiter, "encoding": encoding})

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]:
        text = _decode(Path(file.path).read_bytes(), ctx.sniff_details["encoding"])
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=ctx.sniff_details["delimiter"])
        grid, src_rows, prev = [], [], 0
        for row in reader:
            grid.append(row)
            src_rows.append(prev + 1)  # first line of this record
            prev = reader.line_num
        _merge_unquoted_names(grid)
        table = grid_to_table(file, self.name, grid, src_rows, score=1.0)
        return [table] if table else []
