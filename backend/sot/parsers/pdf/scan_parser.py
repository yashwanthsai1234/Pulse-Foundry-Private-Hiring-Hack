"""PdfScanParser: image-only PDFs and images. Renders each page at 150 dpi and hands it to a page_reader agent task.

The agent's rows re-enter the pipeline at stage 3 (the gateway builds the RawTable), so extract returns no tables.

Sources:
- PyMuPDF Page.get_pixmap(dpi=...) and opening images as documents: https://pymupdf.readthedocs.io/en/latest/pixmap.html
- IMPLEMENTATION.md §8.6, §15.4 (page_reader task)
"""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import pymupdf

from sot.core.ids import canonical_json, sha256_bytes
from sot.core.models import AgentTask, FileRef, RawTable, SniffResult
from sot.core.registry import ExtractContext, register_parser
from sot.parsers.pdf.text_parser import mean_text_chars

DPI = 150


@register_parser
class PdfScanParser:
    name = "pdf_scan"

    def sniff(self, head: bytes, path: Path) -> SniffResult:
        if head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            return SniffResult(parser=self.name, score=0.9, reason="PNG/JPEG image")
        if not head.startswith(b"%PDF-"):
            return SniffResult(parser=self.name, score=0.0, reason="not a PDF or image")
        chars = mean_text_chars(path)
        return SniffResult(parser=self.name, score=0.9 if chars < 20 else 0.05,
                           reason=f"PDF with {chars:.0f} text chars/page", details={"chars_per_page": chars})

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]:
        out = ctx.settings.dir("agent_tasks/files")
        with pymupdf.open(file.path) as doc:
            for n, page in enumerate(doc, start=1):
                image = out / f"{file.file_id[:12]}_p{n}.png"
                page.get_pixmap(dpi=DPI).save(image)
                if ctx.submit_task:
                    payload = {"image": str(image), "page": n, "file_id": file.file_id}
                    task_id = "t-" + sha256_bytes(f"page_reader|v0|{canonical_json(payload)}".encode())[:10]
                    ctx.submit_task(AgentTask(
                        task_id=task_id, kind="page_reader", run_id=ctx.run_id, ref=f"{file.file_id}:{n}",
                        prompt_version="v0", instructions="Read the schedule table on the page image.",
                        payload=payload, output_schema={}, input_files=[str(image)],
                        output_path=str(ctx.settings.dir("agent_tasks/done") / f"{task_id}.json"),
                        created_at=datetime.now(UTC)))
        return []
