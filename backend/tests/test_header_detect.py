from datetime import datetime

from sot.core.models import FileRef
from sot.parsers.base import build_raw_table, detect_header_row

FILE = FileRef(file_id="abcdef1234567890", file_name="f.csv", path="f.csv", size=1, received_at=datetime(2026, 1, 1))
HEAD = ["id", "name", "start"]
DATA = [["1", "Ann", "2026-01-02"], ["2", "Bob", "2026-02-03"], ["3", "Cy", "2026-03-04"]]


def test_header_in_first_row():
    assert detect_header_row([HEAD, *DATA]) == 0


def test_title_rows_and_blank_row_above_header():
    rows = [["Harborview export", None, None], ["Run 2026-09-01", None, None], [None, None, None], HEAD, *DATA]
    assert detect_header_row(rows) == 3


def test_all_text_table_falls_back_to_first_full_row():
    rows = [["Title", None, None], ["a", "b", "c"], ["x", "y", "z"], ["p", "q", "r"]]
    assert detect_header_row(rows) == 1


def test_empty_rows_returns_zero():
    assert detect_header_row([]) == 0


def _table(header, rows, src_rows=None):
    return build_raw_table(FILE, "csv", header, rows, src_rows or list(range(2, 2 + len(rows))), method="csv", score=0.9)


def test_build_cleans_and_uniquifies():
    t = _table(["name", " name ", "", "x"], [[" Ann ", "b", None, "1"], [None, "", None, ""], ["C", "d", None, "2"]])
    assert t.header == ["name", "name_2", "x"]
    assert t.df.columns == ["name", "name_2", "x", "_src_row"]
    assert t.df["name"].to_list() == ["Ann", "C"]
    assert t.df["_src_row"].to_list() == [2, 4]
    assert t.table_id == "abcdef123456:0:0"
    assert t.extraction.method == "csv"


def test_build_pads_ragged_rows_and_sheet_id():
    t = build_raw_table(FILE, "xlsx", ["a", "b"], [["1"], ["2", "3", "4"]], [5, 6], method="xlsx", score=0.9, sheet="S1", index=2)
    assert t.df["b"].to_list() == [None, "3"]
    assert t.table_id == "abcdef123456:S1:2"
