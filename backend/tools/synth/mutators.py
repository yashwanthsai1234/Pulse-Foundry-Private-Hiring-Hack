"""Format mutators for chaos testing: each takes a CSV and returns a new file; data semantics stay identical.

`MUTATORS` is ordered so that header-level changes run before text-level ones (apply in dict order).
Date mutators only rewrite columns where some day is > 12, so the new format stays inferable.
Output name: `<root stem>.<mutator><suffix>` next to the input; the input is never modified.

Sources:
- https://docs.python.org/3/library/csv.html (dialects, QUOTE_ALL, delimiters)
- https://openpyxl.readthedocs.io/en/stable/ (xlsx writer)
- https://www.rfc-editor.org/rfc/rfc4180 (what a well-formed CSV is, so we know what we are breaking)
- https://hypothesis.readthedocs.io/ (property-based testing background for the chaos idea)
"""
from __future__ import annotations

import csv
import io
import random
import re
from pathlib import Path
from collections.abc import Callable

import openpyxl

BOM = b"\xef\xbb\xbf"
ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
NAME_COLUMNS = {"first_name", "last_name", "employee_name", "name_on_license"}
OPTIONAL = {"phone", "hire_date", "last_verified"}
SYNONYMS = {
    "employee_id": ["Emp ID", "Employee ID", "EmpID"], "first_name": ["First Name", "First", "Given Name"],
    "last_name": ["Last Name", "Surname"], "job_title": ["Job Title", "Title", "Position"],
    "facility": ["Facility", "Site", "Location"], "phone": ["Phone", "Phone Number", "Tel"],
    "license_number": ["License #", "License No", "Lic Number"],
    "license_expiration": ["License Expiration", "Lic Exp", "Expiry"],
    "hire_date": ["Hire Date", "Date Hired", "Start Date"], "payroll_id": ["Payroll ID", "Pay Ref", "Ref"],
    "employee_name": ["Employee Name", "Emp", "Name"], "job_code": ["Job Code", "Cls", "Class"],
    "facility_code": ["Facility Code", "Site Code", "Fac"], "period_start": ["Period Start", "Wk Beg", "Pay Start"],
    "period_end": ["Period End", "Wk End", "Pay End"], "hours_paid": ["Hours Paid", "Hrs", "Hours"],
    "name_on_license": ["Name on License", "Licensee", "Name"], "license_type": ["License Type", "Type", "Cert Type"],
    "expiration_date": ["Expiration Date", "Exp Date", "Expires"],
    "last_verified": ["Last Verified", "Verified On", "Verified"],
}

Rows = list[list[str]]


def decode(data: bytes) -> str:
    """Decode a CSV: optional UTF-8 BOM, then UTF-8, falling back to latin-1."""
    data = data.removeprefix(BOM)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _delimiter(text: str) -> str:
    def score(d: str) -> tuple[int, int]:
        widths = [len(r) for r in csv.reader(io.StringIO(text), delimiter=d) if len(r) > 1]
        return (max(map(widths.count, widths), default=0), max(widths, default=0))
    return max(",;\t", key=score)


def _load(path: Path) -> Rows:
    text = decode(path.read_bytes())
    return list(csv.reader(io.StringIO(text), delimiter=_delimiter(text)))


def _save(path: Path, rows: Rows, delimiter: str = ",", quoting: int = csv.QUOTE_MINIMAL) -> None:
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter, quoting=quoting, lineterminator="\n").writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _out(path: Path, name: str, suffix: str | None = None) -> Path:
    return path.with_name(f"{path.stem.split('.')[0]}.{name}{suffix or path.suffix}")


def _columns(rows: Rows, names: set[str]) -> list[int]:
    return [i for i, h in enumerate(rows[0]) if h in names]


def _csv_mutator(fn: Callable[[Rows, random.Random], Rows] | None = None, *, name: str | None = None, **save_kw):
    """Turn a rows -> rows function into a mutator (path, rng -> new path); `save_kw` goes to csv.writer (_save)."""
    def build(fn):
        def wrapper(path: Path, rng: random.Random) -> Path:
            out = _out(path, wrapper.__name__)
            _save(out, fn(_load(path), rng), **save_kw)
            return out
        wrapper.__name__ = name or fn.__name__
        return wrapper
    return build(fn) if fn else build


def _reformat_dates(rows: Rows, fmt: str) -> Rows:
    for c in range(len(rows[0])):
        cells = [ISO.match(r[c]) for r in rows[1:] if c < len(r)]
        if cells and all(cells) and any(int(m.group(3)) > 12 for m in cells):
            for r in rows[1:]:
                y, m, d = ISO.match(r[c]).groups()
                r[c] = fmt.format(y=y, m=m, d=d)
    return rows


@_csv_mutator
def drop_optional_column(rows, rng):
    cols = _columns(rows, OPTIONAL)
    drop = rng.choice(cols) if cols else None
    return [[v for i, v in enumerate(r) if i != drop] for r in rows]


@_csv_mutator
def upper_case_names(rows, rng):
    for c in _columns(rows, NAME_COLUMNS):
        for r in rows[1:]:
            r[c] = r[c].upper()
    return rows


@_csv_mutator
def date_format_us_slash(rows, rng):
    return _reformat_dates(rows, "{m}/{d}/{y}")


@_csv_mutator
def date_format_dmy_unambiguous(rows, rng):
    return _reformat_dates(rows, "{d}/{m}/{y}")


@_csv_mutator
def extra_unknown_columns(rows, rng):
    extras = rng.sample([("Notes", "n/a"), ("Dept Code", "D14"), ("Internal Flag", "0"), ("Batch", "B7")],
                        rng.randint(1, 2))
    return [r + [h for h, _ in extras] if i == 0 else r + [v for _, v in extras] for i, r in enumerate(rows)]


@_csv_mutator
def reorder_columns(rows, rng):
    order = list(range(len(rows[0])))
    rng.shuffle(order)
    return [[r[i] for i in order] for r in rows]


@_csv_mutator
def rename_headers_synonyms(rows, rng):
    rows[0] = [rng.choice(SYNONYMS[h]) if h in SYNONYMS else h for h in rows[0]]
    return rows


@_csv_mutator
def title_rows_above_header(rows, rng):
    titles = [["Harborview Care Group"], ["Export generated 2026-09-21"], [], ["Confidential"]][:rng.randint(1, 4)]
    return titles + rows


@_csv_mutator
def trailing_blank_rows(rows, rng):
    return rows + [[""] * len(rows[0])] * rng.randint(1, 3) + [[]]


def _same_rows(rows: Rows, rng: random.Random) -> Rows:
    return rows


quote_all = _csv_mutator(_same_rows, name="quote_all", quoting=csv.QUOTE_ALL)
delimiter_semicolon = _csv_mutator(_same_rows, name="delimiter_semicolon", delimiter=";")
delimiter_tab = _csv_mutator(_same_rows, name="delimiter_tab", delimiter="\t")


def encoding_latin1_bom(path: Path, rng: random.Random) -> Path:
    out = _out(path, "encoding_latin1_bom")
    out.write_bytes(BOM + decode(path.read_bytes()).encode("latin-1"))
    return out


def to_xlsx(path: Path, rng: random.Random) -> Path:
    wb = openpyxl.Workbook()
    for row in _load(path):
        wb.active.append(row)
    out = _out(path, "to_xlsx", ".xlsx")
    wb.save(out)
    return out


MUTATORS: dict[str, Callable[[Path, random.Random], Path]] = {f.__name__: f for f in (
    drop_optional_column, upper_case_names, date_format_us_slash, date_format_dmy_unambiguous,
    extra_unknown_columns, reorder_columns, rename_headers_synonyms, title_rows_above_header,
    trailing_blank_rows, quote_all, delimiter_semicolon, delimiter_tab, encoding_latin1_bom, to_xlsx)}
