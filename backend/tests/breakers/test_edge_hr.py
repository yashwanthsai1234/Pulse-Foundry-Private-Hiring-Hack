"""B2 attacks on the HR roster CSV."""
import pytest

from tests.breakers.edge_world import HR, HR_H, NOISE, csv_text, hr_row, run

IDS = ["P-E201", "P-E202", "P-E203", "P-E204"]


def _ids(r):
    return [p["person_id"] for p in r.persons]


def test_duplicate_employee_id_with_different_data_is_hr_dup_row(tmp_path, settings):
    r = run(tmp_path, settings, hr=[*HR, hr_row(0, phone="718-555-9999", job_title="Licensed Practical Nurse", facility="Harborview Riverdale")])
    assert _ids(r) == IDS and r.ids("HR-DUP-ROW")


def test_duplicate_identical_hr_row_is_tolerated(tmp_path, settings):
    r = run(tmp_path, settings, hr=[*HR, list(HR[0])])
    assert _ids(r) == IDS and not r.about("P-E201", *NOISE)


def test_repeated_header_row_mid_file_is_not_a_person(tmp_path, settings):
    """Paginated HR exports repeat the header on every page; it became employee 'EMPLOYEE_ID' (person P-EMPLOYEE_ID)."""
    r = run(tmp_path, settings, hr=None, hr_text=csv_text(HR_H, [*HR[:2], HR_H, *HR[2:]]))
    assert _ids(r) == IDS, _ids(r)


def test_blank_rows_trailing_spaces_extra_columns_missing_optional_columns(tmp_path, settings):
    text = csv_text(HR_H, [HR[0], [""] * 9, [" "] * 9, *[[c + "  " for c in row] for row in HR[1:]]])
    r = run(tmp_path, settings, hr=None, hr_text=text)
    assert _ids(r) == IDS and not r.attention() - NOISE


def test_extra_unknown_columns_are_ignored(tmp_path, settings):
    r = run(tmp_path, settings, hr=[[*row, "x", "F"] for row in HR], hr_header=[*HR_H, "notes", "gender"])
    assert _ids(r) == IDS and not r.attention() - NOISE


def test_hr_without_phone_and_hire_date_columns(tmp_path, settings):
    keep = [0, 1, 2, 3, 4, 6, 7]
    r = run(tmp_path, settings, hr=[[row[i] for i in keep] for row in HR], hr_header=[HR_H[i] for i in keep])
    assert _ids(r) == IDS and not r.attention() - NOISE


def test_hr_license_expiration_blank_for_one_row(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, license_expiration=""), *HR[1:]])
    assert _ids(r) == IDS and not r.ids("SRC-CONFLICT")


@pytest.mark.parametrize("variant", ["bom_crlf", "semicolon", "tab", "title_lines"])
def test_csv_dialects(tmp_path, settings, variant):
    text = csv_text(HR_H, HR)
    text = {"bom_crlf": "﻿" + text.replace("\n", "\r\n"), "semicolon": text.replace(",", ";"),
            "tab": text.replace(",", "\t"), "title_lines": "Harborview HR Export\nRun date: 2026-09-20\n\n" + text}[variant]
    r = run(tmp_path, settings, hr=None, hr_text=text)
    assert _ids(r) == IDS and not r.attention() - NOISE


def test_renamed_hr_headers(tmp_path, settings):
    r = run(tmp_path, settings, hr_header=["Emp #", "Given", "Surname", "Position", "Location", "Tel", "Lic No", "Lic Exp", "Start Date"])
    assert _ids(r) == IDS


def test_hr_with_single_employee_name_column_is_still_the_hr_roster(tmp_path, settings):
    """'Employee Name' = 'Reyes, Sofia' in one column (very common HR export). It was auto-mapped as a LICENCE file."""
    hr = [[row[0], f"{row[2]}, {row[1]}", *row[3:]] for row in HR]
    r = run(tmp_path, settings, hr=hr, hr_header=["employee_id", "employee_name", *HR_H[3:]])
    assert _ids(r) == IDS, _ids(r)
    assert all(p["has_hr"] for p in r.persons)


def test_employee_ids_written_differently_still_one_person(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, employee_id=" e201 "), *HR[1:]])
    assert _ids(r) == IDS


def test_phone_spellings_are_normalised(tmp_path, settings):
    phones = ["(718) 555-0201", "7185550202", "+1 718 555 0203", "718.555.0204"]
    hr = [[*row[:5], phones[i], *row[6:]] for i, row in enumerate(HR)]
    r = run(tmp_path, settings, hr=hr)
    assert [p["phone"] for p in r.persons] == [f"+1718555020{i}" for i in range(1, 5)]


def test_all_zero_phone_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, phone="0000000000"), *HR[1:]])
    assert r.about("P-E201", *NOISE) or r.person("P-E201")["phone"] is None
