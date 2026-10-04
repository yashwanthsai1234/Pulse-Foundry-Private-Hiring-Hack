import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pymupdf
import pytest

from sot.core.ids import sha256_bytes
from sot.core.models import FileRef
from sot.core.registry import ExtractContext
from sot.parsers.pdf.scan_parser import PdfScanParser
from sot.parsers.pdf.text_parser import PdfTextParser
from tools.synth.render import VARIANTS, make_spec, render_schedule_pdf

E1 = Path(__file__).parent / "fixtures" / "example_e1"
TEXT_VARIANTS = [v for v in VARIANTS if v != "raster_150dpi"]


def file_ref(path: Path) -> FileRef:
    data = path.read_bytes()
    return FileRef(file_id=sha256_bytes(data), file_name=path.name, path=str(path), size=len(data),
                   received_at=datetime(2026, 9, 14))


def extract(path, settings, pack, parser=None, submit=None):
    ctx = ExtractContext(settings=settings, pack=pack, run_id="r1", sniff_details={}, submit_task=submit)
    return (parser or PdfTextParser()).extract(file_ref(path), ctx)


def cell_accuracy(tables, spec) -> float:
    """Flattened rows of all tables vs ground truth rows, cell by cell (extra/missing rows count as wrong)."""
    truth = [r for p in spec["pages"] for r in p["rows"]]
    got = [list(row) for t in tables for row in t.df.drop("_src_row").rows()]
    total = max(len(truth), len(got)) * len(spec["header"])
    ok = sum(a == b for g, t in zip(got, truth) for a, b in zip(g, t))
    return ok / total


def test_e1_two_tables(settings, pack):
    tables = extract(E1 / "schedule.pdf", settings, pack)
    assert [t.page for t in tables] == [1, 2]
    spec = json.loads((E1 / "schedule.json").read_text())
    for t in tables:
        assert t.header == spec["header"]
        assert t.parser == "pdf_text" and t.extraction.score >= 0.8
    assert tables[0].df.row(0, named=True)["Staff"] == "Sofia Reyes"
    assert list(tables[0].df.drop("_src_row").row(0)) == spec["pages"][0]["rows"][0]
    assert list(tables[1].df.drop("_src_row").row(0)) == spec["pages"][1]["rows"][0]
    assert [t.context["title"] for t in tables] == ["Harborview Bayside", "Harborview Riverdale"]
    assert tables[0].context["facility_hint"] == "Harborview Bayside"
    assert "Week of 09/14" in tables[0].context["subtitle"]
    assert tables[0].context["footnote"].startswith("Shifts:")
    assert json.loads(tables[0].context["legend_json"]) == {"7a-3p": 8.0, "3p-11p": 8.0, "11p-7a": 8.0, "7a-7p": 12.0}
    assert "Sofia Reyes" in tables[0].context["page_text"]


def test_e1_bboxes_inside_page(settings, pack):
    tables = extract(E1 / "schedule.pdf", settings, pack)
    with pymupdf.open(E1 / "schedule.pdf") as doc:
        for t in tables:
            w, h = doc[t.page - 1].rect.width, doc[t.page - 1].rect.height
            assert len(t.cell_bboxes) == t.df.height * len(t.header)
            for key, (x0, top, x1, bottom) in t.cell_bboxes.items():
                assert 0 <= x0 < x1 <= w and 0 <= top < bottom <= h, key


@pytest.mark.parametrize("variant", TEXT_VARIANTS)
@pytest.mark.parametrize("size", ["e1", "mid", "big"])
def test_variant_accuracy(variant, size, tmp_path, settings, pack):
    if size == "e1":
        spec = json.loads((E1 / "schedule.json").read_text())
    elif size == "mid":
        spec = make_spec(4, 6, seed=1)
    elif variant.startswith("wrapped") or variant == "two_tables_one_page":
        pytest.skip("25-row tables do not fit one page in this variant")
    else:
        spec = make_spec(2, 25, seed=2)
    pdf = render_schedule_pdf(spec, tmp_path / "s.pdf", variant)
    tables = extract(pdf, settings, pack)
    assert cell_accuracy(tables, spec) >= 0.98
    assert [t.context["title"] for t in tables] == [p["title"] for p in spec["pages"]]
    assert all(t.context["footnote"].startswith("Shifts:") != (variant == "no_footnote") for t in tables)
    assert all(json.loads(t.context["legend_json"]) != {} for t in tables if variant != "no_footnote")


def test_raster_goes_to_scan_parser(tmp_path, settings, pack):
    pdf = render_schedule_pdf(json.loads((E1 / "schedule.json").read_text()), tmp_path / "r.pdf", "raster_150dpi")
    head = pdf.read_bytes()[:4096]
    text_bid, scan_bid = PdfTextParser().sniff(head, pdf), PdfScanParser().sniff(head, pdf)
    assert text_bid.score <= 0.1 and scan_bid.score >= 0.9
    # text parser on an image-only page yields only a low-confidence result
    assert all(t.extraction.score < 0.5 for t in extract(pdf, settings, pack))
    tasks = []
    assert extract(pdf, settings, pack, PdfScanParser(), tasks.append) == []
    assert [t.kind for t in tasks] == ["page_reader"] * 2
    assert [t.payload["page"] for t in tasks] == [1, 2]
    assert all(Path(t.payload["image"]).exists() and t.payload["file_id"] for t in tasks)


def test_sniff_text_pdf_and_non_pdf(settings, pack):
    pdf = E1 / "schedule.pdf"
    assert PdfTextParser().sniff(pdf.read_bytes()[:4096], pdf).score >= 0.9
    assert PdfScanParser().sniff(pdf.read_bytes()[:4096], pdf).score <= 0.1
    assert PdfTextParser().sniff(b"a,b\n1,2\n", pdf).score == 0.0
    assert PdfScanParser().sniff(b"\x89PNG\r\n\x1a\n", pdf).score >= 0.9
    assert PdfScanParser().sniff(b"\xff\xd8\xff\xe0", pdf).score >= 0.9
