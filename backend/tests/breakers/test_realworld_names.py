"""W3-B3: typography that real PDFs/Word exports produce in names and shift tokens."""
import tempfile
from datetime import date
from pathlib import Path

from sot.config import load_settings
from sot.normalize.names import parse_person_name
from sot.normalize.shifts import parse_shift_token
from sot.pipeline.orchestrator import Pipeline


def test_curly_apostrophe_same_family_key():
    assert parse_person_name("Renee O’Brien", {}).family == parse_person_name("Renee O'Brien", {}).family


def test_hyphen_then_space_from_cell_wrap_same_family_key():
    """Chrome wraps 'Washington-Greene' in a narrow cell; pdfplumber/pymupdf join the lines with a space."""
    a = parse_person_name("Dorothy Washington- Greene", {})
    b = parse_person_name("Dorothy Washington-Greene", {})
    assert (a.given, a.family) == (b.given, b.family)


def test_non_decomposable_letters_kept_in_key():
    assert parse_person_name("Łukasz Nowak", {}).given != "ukasz"
    assert parse_person_name("Bjørn Åberg", {}).given != "bjrn"


def test_soft_hyphen_and_non_breaking_hyphen_in_shift_token():
    assert parse_shift_token("7a­-3p") is not None
    assert parse_shift_token("7a‑3p") is not None


def test_wrapped_hyphenated_name_does_not_create_phantom_person():
    d = Path(tempfile.mkdtemp())
    (d / "hr.csv").write_text(
        "employee_id,first_name,last_name,job_title,facility,phone,license_number,license_expiration,hire_date\n"
        "E302,Dorothy,Washington-Greene,Licensed Practical Nurse,Harborview Bayside,718-555-0302,LPN-331044,2027-05-31,2020-03-02\n")
    (d / "pay.csv").write_text(
        "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid\n"
        "P-2,Dorothy Washington- Greene,LPN,BYS,2026-09-14,2026-09-20,36\n")
    s = load_settings(runtime=d / "rt")
    s.agents = "off"
    s.as_of = date(2026, 9, 21)
    p = Pipeline(s)
    p.ingest([d / "hr.csv", d / "pay.csv"], run_id="r1")
    persons = p.db.query("SELECT person_id FROM persons")
    assert len(persons) == 1, persons
