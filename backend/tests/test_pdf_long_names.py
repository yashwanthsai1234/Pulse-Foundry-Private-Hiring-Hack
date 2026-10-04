"""Live-panel regression: long names on a gridless schedule spilled their family name into the Role column."""
import pymupdf
import pytest

from sot.parsers.pdf.methods import words  # noqa: I001
from sot.parsers.pdf.methods import PageView
from tools.synth.render import render_schedule_pdf

DAYS = ["Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
NAMES = [("Jessica Richardson", "LPN"), ("Anthony Thompson", "RN"), ("Matthew Hernandez", "CNA"), ("Amy Li", "RN"),
         ("Christopher Montgomery", "CNA"), ("Bo Ng", "LPN")]


@pytest.mark.parametrize("variant", ["nogrid", "grid"])
def test_long_names_stay_in_the_staff_column(tmp_path, variant):
    spec = {"header": ["Staff", "Role", *DAYS], "footnote": "Shifts: 7a-3p, 3p-11p are 8 hours. 7a-7p is 12 hours.",
            "pages": [{"title": "Harborview Bayside", "rows": [[n, r, "7a-7p", "OFF", "3p-11p", "7a-3p", "OFF", "7a-3p", "OFF"]
                                                            for n, r in NAMES]}]}
    pdf = render_schedule_pdf(spec, tmp_path / "s.pdf", variant)
    with pymupdf.open(pdf) as doc:
        import pdfplumber
        with pdfplumber.open(pdf) as plumb:
            (grid,) = words(PageView(plumb.pages[0], doc[0]))
    body = grid.rows[1:]
    assert [(r[0], r[1]) for r in body] == NAMES
