"""XLSX/XLS parser via python-calamine; every non-empty sheet is one table.

Calamine detects the format from content, so an .xlsx saved with a .csv extension still opens
(docs/research/A1.md).

Sources:
- https://github.com/dimastbk/python-calamine (load_workbook, sheet.to_python)
- https://pypi.org/project/python-calamine/
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import ClassVar

from python_calamine import load_workbook

from sot.core.models import FileRef, RawTable, SniffResult
from sot.core.registry import ExtractContext, register_parser
from sot.parsers.base import cell_to_str, grid_to_table

OLE_MAGIC = bytes.fromhex("D0CF11E0")


@register_parser
class XlsxParser:
    name: ClassVar[str] = "xlsx"

    def sniff(self, head: bytes, path: Path) -> SniffResult:
        if head.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(path) as z:
                    if "xl/workbook.xml" in z.namelist():
                        return SniffResult(parser=self.name, score=0.98, reason="zip with xl/workbook.xml")
            except zipfile.BadZipFile:
                pass
            return SniffResult(parser=self.name, score=0.0, reason="zip without xl/workbook.xml")
        if head.startswith(OLE_MAGIC):
            return SniffResult(parser=self.name, score=0.90, reason="OLE2 container (legacy XLS)")
        return SniffResult(parser=self.name, score=0.0, reason="not a spreadsheet")

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]:
        wb = load_workbook(file.path)
        tables = []
        for name in wb.sheet_names:
            grid = [[cell_to_str(c) for c in r] for r in wb.get_sheet_by_name(name).to_python(skip_empty_area=False)]
            table = grid_to_table(file, self.name, grid, list(range(1, len(grid) + 1)), score=1.0, sheet=name)
            if table:
                tables.append(table)
        return tables
