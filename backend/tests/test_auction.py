import json
import os
from datetime import datetime
from pathlib import Path

import openpyxl

from sot.core.models import FileRef
from sot.parsers.csv_parser import CsvParser
from sot.parsers.json_parser import JsonParser
from sot.parsers.xlsx_parser import XlsxParser
from sot.sniff.auction import run_auction

PARSERS = [CsvParser(), XlsxParser(), JsonParser()]
README = Path(__file__).parent / "fixtures" / "readme_sample"


def ref(path: Path) -> FileRef:
    return FileRef(file_id="f" * 64, file_name=path.name, path=str(path), size=path.stat().st_size, received_at=datetime(2026, 1, 1))


def win(path: Path):
    return run_auction(ref(path), PARSERS, 0.5)


def test_readme_csvs_go_to_csv():
    for name in ("hr_roster.csv", "licenses.csv", "payroll.csv"):
        r = win(README / name)
        assert r.winner.parser == "csv" and r.winner.score > 0.9
        assert r.winner.details["delimiter"] == ","
        assert [b.score for b in r.bids] == sorted((b.score for b in r.bids), reverse=True)
        assert len(r.bids) == 3


def test_xlsx_with_csv_extension_wins_as_xlsx(tmp_path):
    p = tmp_path / "x.csv"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.save(p)
    r = win(p)
    assert r.winner.parser == "xlsx" and r.winner.score == 0.98


def test_json_and_ndjson(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(json.dumps([{"x": 1}, {"x": 2}]))
    b.write_text('{"x": 1, "y": 2}\n{"x": 3, "y": 4}\n')
    assert win(a).winner.parser == "json"
    assert win(b).winner.parser == "json"


def test_binary_is_quarantined(tmp_path):
    p = tmp_path / "junk.bin"
    p.write_bytes(os.urandom(4096))
    assert win(p).winner is None


def test_empty_file_is_quarantined(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_bytes(b"")
    assert win(p).winner is None


def test_pdf_and_prose_are_not_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_bytes(b"%PDF-1.7\nhello, world\n")
    assert win(p).winner is None
    p.write_text("just some prose without structure\nsecond line\n")
    assert win(p).winner is None


def test_min_score_threshold_and_tie_order(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n")
    assert run_auction(ref(p), PARSERS, 1.01).winner is None
    assert run_auction(ref(p), [CsvParser(), CsvParser()], 0.5).bids[0].parser == "csv"


def test_failing_parser_does_not_break_auction(tmp_path):
    class Boom:
        name = "boom"

        def sniff(self, head, path):
            raise RuntimeError("x")

    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n")
    r = run_auction(ref(p), [Boom(), CsvParser()], 0.5)
    assert r.winner.parser == "csv" and r.bids[-1].score == 0
