"""Render a schedule spec (see tests/fixtures/*/schedule.json) to a PDF like the one posted at a nurses' station.

Variants stress the PDF extraction cascade (docs/pdf_spike.md): ruled vs unruled, wrapped names, portrait,
two tables on one page, image-only (raster), no footnote, a merged title row above the header.

Sources:
- reportlab Table/TableStyle: https://docs.reportlab.com/reportlab/userguide/ch7_tables/
- PyMuPDF Pixmap / insert_image (raster variant): https://pymupdf.readthedocs.io/en/latest/page.html
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

VARIANTS = (
    "grid", "nogrid", "wrapped_names", "wrapped_nogrid", "portrait",
    "two_tables_one_page", "raster_150dpi", "no_footnote", "merged_header",
)

_SHIFTS = ["7a-3p", "3p-11p", "11p-7a", "7a-7p", "OFF", "OFF"]
_FIRST = ["Sofia", "Marc", "Alexandria", "Priya", "Jonathan", "Dmitri", "Keisha", "Luis", "Mei", "Oluwaseun"]
_LAST = ["Reyes", "Bell", "Montgomery Fitzgerald", "Natarajan", "Okafor", "Kowalczyk", "Nguyen", "Alvarez"]


def make_spec(pages: int, rows: int, seed: int = 0, font_size: int = 8) -> dict:
    """Random schedule spec shaped like example_e1/schedule.json (long names included, to exercise wrapping)."""
    rng = random.Random(seed)
    base = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/example_e1/schedule.json").read_text())
    facilities = ["Harborview Bayside", "Harborview Riverdale", "Harborview Northgate", "Harborview Hilltop"]
    return {
        **base,
        "font_size": font_size,
        "pages": [
            {"title": facilities[p % 4], "subtitle": "Weekly Staff Schedule - Week of 09/14",
             "rows": [[f"{rng.choice(_FIRST)} {rng.choice(_LAST)}", rng.choice(["RN", "LPN", "CNA"]),
                       *(rng.choice(_SHIFTS) for _ in range(7))] for _ in range(rows)]}
            for p in range(pages)
        ],
    }


def _table(spec: dict, page: dict, variant: str, styles) -> Table:
    size = spec.get("font_size", 10)
    wrapped = variant.startswith("wrapped")
    rows = [list(spec["header"]), *[list(r) for r in page["rows"]]]
    if variant == "merged_header":
        rows.insert(0, [f"Week of {spec['header'][2].split()[-1]}", *[""] * (len(rows[0]) - 1)])
    if wrapped:
        style = getSampleStyleSheet()["Normal"].clone("cell", fontSize=size, leading=size * 1.2)
        for r in rows[1:]:
            r[0] = Paragraph(r[0], style)
    widths = [size * 8] + [None] * (len(rows[0]) - 1) if wrapped else None
    table = Table(rows, colWidths=widths, repeatRows=1)
    cmds = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), size),
            ("LEADING", (0, 0), (-1, -1), size * 1.2), ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), size / 4), ("BOTTOMPADDING", (0, 0), (-1, -1), size / 4)]
    if variant == "merged_header":
        cmds += [("SPAN", (0, 0), (-1, 0)), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold")]
    if variant not in ("nogrid", "wrapped_nogrid"):
        cmds.append(("GRID", (0, 0), (-1, -1), 0.5, colors.black))
    table.setStyle(TableStyle(cmds))
    return table


def _build_vector(spec: dict, out: Path, variant: str) -> None:
    styles = getSampleStyleSheet()
    size = landscape(letter)
    if variant == "portrait":
        size = letter
    doc = SimpleDocTemplate(str(out), pagesize=size, title="Weekly Staff Schedule",
                            topMargin=30, bottomMargin=30)
    per_page = 2 if variant == "two_tables_one_page" else 1
    story = []
    for i, page in enumerate(spec["pages"]):
        if i and i % per_page == 0:
            story.append(PageBreak())
        story.append(Paragraph(page["title"], styles["Title"]))
        if page.get("subtitle"):
            story.append(Paragraph(page["subtitle"], styles["Normal"]))
        story += [Spacer(1, 12), _table(spec, page, variant, styles), Spacer(1, 12)]
        if variant != "no_footnote":
            story.append(Paragraph(f"<i>{spec['footnote']}</i>", styles["Normal"]))
    doc.build(story)


def render_schedule_pdf(spec: dict, out: Path, variant: str = "grid") -> Path:
    """One page per facility (two per page for two_tables_one_page): title, subtitle, staff x day table, footnote."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    if variant != "raster_150dpi":
        _build_vector(spec, out, variant)
        return out
    vector = out.with_name(out.stem + ".vector.pdf")
    _build_vector(spec, vector, "grid")
    with pymupdf.open(vector) as src, pymupdf.open() as dst:
        for page in src:
            png = page.get_pixmap(dpi=150).tobytes("png")
            dst.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=png)
        dst.save(out)
    vector.unlink()
    return out


if __name__ == "__main__":
    for d in sorted((Path(__file__).resolve().parents[2] / "tests" / "fixtures").iterdir()):
        if (d / "schedule.json").exists():
            print(render_schedule_pdf(json.loads((d / "schedule.json").read_text()), d / "schedule.pdf"))
