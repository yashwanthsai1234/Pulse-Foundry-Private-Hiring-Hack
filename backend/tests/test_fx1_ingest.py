"""FX1: ingest fixes (encoding after BOM, header detection, repeated header, unquoted names, de-hyphenation, PDF score)."""
from datetime import datetime
from pathlib import Path

import pdfplumber
import pymupdf

from sot.core.models import FileRef
from sot.parsers.base import build_raw_table, detect_header_row, grid_to_table
from sot.parsers.csv_parser import CsvParser, detect_encoding
from sot.parsers.pdf.context import group_lines
from sot.parsers.pdf.methods import PageView
from sot.parsers.pdf.scoring import completeness, is_body_line
from sot.parsers.pdf.text_parser import run_cascade

FILE = FileRef(file_id="abcdef1234567890", file_name="f.csv", path="f.csv", size=1, received_at=datetime(2026, 1, 1))


def _csv_table(tmp_path: Path, text: str):
    path = tmp_path / "p.csv"
    path.write_text(text)
    sniff = CsvParser().sniff(path.read_bytes(), path)
    return CsvParser().extract(FILE.model_copy(update={"path": str(path)}), type("C", (), {"sniff_details": sniff.details})())[0]


def test_latin1_with_bom_extracts_without_bom_artifacts(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(b"\xef\xbb\xbfname,role\nMu\xf1oz,RN\nLee,CNA\n")
    sniff = CsvParser().sniff(path.read_bytes(), path)
    t = CsvParser().extract(FILE.model_copy(update={"path": str(path)}), type("C", (), {"sniff_details": sniff.details})())[0]
    assert t.header == ["name", "role"] and t.df["name"].to_list() == ["Muñoz", "Lee"]


def test_utf8_bom_before_latin1_bytes_falls_back_to_cp1252():
    data = b"\xef\xbb\xbfname\nMu\xf1oz\n"
    assert detect_encoding(data) == "cp1252"


def test_utf8_bom_with_valid_utf8_stays_utf8_sig():
    assert detect_encoding(b"\xef\xbb\xbfname\nMu\xc3\xb1oz\n") == "utf-8-sig"


def test_extra_text_column_does_not_move_header_to_a_data_row():
    head = ["id", "first", "phone", "hired", "notes"]
    rows = [[f"E{i}", "Ann", "718-555-01", "2020-01-0" + str(i), "n/a"] for i in range(1, 6)]
    assert detect_header_row([head, *rows]) == 0


def test_all_text_table_with_narrow_first_row_uses_modal_width():
    rows = [["a", None, None, None], ["name", "role", "unit", "shift"], ["x", "y", "z", "w"], ["p", "q", "r", "s"]]
    assert detect_header_row(rows) == 1


def test_repeated_header_rows_are_dropped():
    grid = [["id", "name"], ["1", "Ann"], ["ID", "Name"], ["2", "Bob"]]
    t = grid_to_table(FILE, "csv", grid, [1, 2, 3, 4], score=1.0)
    assert t.df["id"].to_list() == ["1", "2"]


def test_wrapped_hyphen_is_rejoined():
    t = build_raw_table(FILE, "x", ["name", "mon"], [["Dorothy Washington- Greene", "3p- 11p"], ["Mon - Fri", "a"]],
                        [2, 3], method="x", score=1.0)
    assert t.df["name"].to_list() == ["Dorothy Washington-Greene", "Mon - Fri"]
    assert t.df["mon"][0] == "3p-11p"


def test_unquoted_last_first_name_is_merged(tmp_path):
    t = _csv_table(tmp_path, "id,name,hours\n1,REYES, SOFIA,36\n2,BELL, MARC,40\n3,NG, TOM,32\n")
    assert t.header == ["id", "name", "hours"] and t.df["name"].to_list() == ["REYES, SOFIA", "BELL, MARC", "NG, TOM"]


def test_ragged_file_without_the_pattern_is_untouched(tmp_path):
    t = _csv_table(tmp_path, "id,name,hours\n1,Ann,36,extra\n2,Bob,40\n3,Cy,32\n")
    assert t.df["name"].to_list() == ["Ann", "Bob", "Cy"]


def test_completeness_penalises_a_two_row_grid_of_a_nine_row_page():
    row = "Sofia Reyes RN 7a-3p 3p-11p OFF OFF 7a-3p OFF OFF".split()
    lines = [["Staff", "Role"], *[row] * 9, "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours.".split()]
    assert is_body_line(row) and not is_body_line(lines[-1])
    assert completeness(lines, 1) < 0.2 and completeness(lines, 9) == 1.0


def test_borderless_zebra_page_is_extracted_completely_not_as_a_two_row_grid():
    path = Path(__file__).parent / "fixtures" / "realworld" / "pdf" / "chrome_borderless_zebra.pdf"
    with pdfplumber.open(path) as plumber, pymupdf.open(path) as mupdf:
        lines = group_lines(plumber.pages[0].extract_words(extra_attrs=["size"]))
        method, score, grids, notes = run_cascade(PageView(plumber.pages[0], mupdf[0]), lines, 0.8)
    assert method in ("pdf.words", "pdf.text") and score >= 0.8 and len(grids[0].rows) == 9
    assert any(n.startswith("pdf.lines: score 0.1") for n in notes)  # the 2-row grid scored low, not 1.00


def _cascade(tmp_path, text):
    path = tmp_path / "p.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 100), text)
    doc.save(path)
    with pdfplumber.open(path) as plumber, pymupdf.open(path) as mupdf:
        lines = group_lines(plumber.pages[0].extract_words(extra_attrs=["size"]))
        return run_cascade(PageView(plumber.pages[0], mupdf[0]), lines, 0.8)


def test_page_without_a_table_gives_no_grids_instead_of_raising(tmp_path):
    for text in ("", "Just one line of text", "Mon Tue Wed Thu Fri Sat Sun",
                 "Weekly: Mon Tue Wed Thu Fri Sat Sun 7a-3p 3p-11p 11p-7a OFF OFF"):  # day names and tokens on ONE line
        method, score, grids, notes = _cascade(tmp_path, text)
        assert grids == [] and score == 0.0
