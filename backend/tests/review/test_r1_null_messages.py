"""R1-01..R1-03: a NULL in a printf() message makes IssueDraft validation fail, so the whole check becomes CHECK-ERROR."""
from datetime import date

from tests.review.r1_support import HR, LIC, PAY, gold_issues, issues, run_pipeline


def _no_check_error(found):
    return [i.message for i in found if i.check_id == "CHECK-ERROR"] == []


def test_hr_dup_row_two_hr_rows_without_employee_id(tmp_path):
    hr = HR + ",Dana,Cole,Registered Nurse,Harborview Bayside,,,,\n,Dora,Cole,Registered Nurse,Harborview Bayside,,,,\n"
    pipe = run_pipeline(tmp_path, {"hr.csv": hr})
    assert [i.message for i in issues(pipe, "CHECK-ERROR")] == []


def test_lic_expiring_license_row_with_blank_name(tmp_path):
    lic = LIC + "RN-900001,,RN,2026-10-05,2026-09-01\n"
    pipe = run_pipeline(tmp_path, {"hr_roster.csv": HR, "licenses.csv": lic})
    assert [i.message for i in issues(pipe, "CHECK-ERROR")] == []
    assert any(i.check_id == "LIC-EXPIRING" for i in issues(pipe))


def test_pay_no_hr_with_unreadable_hours(tmp_path):
    pay = PAY + "P-3009,\"NOBODY, NORA\",RN,BYS,2026-09-14,2026-09-20,N/A\n"
    pipe = run_pipeline(tmp_path, {"hr_roster.csv": HR, "payroll.csv": pay})
    assert [i.message for i in issues(pipe, "CHECK-ERROR")] == []
    assert any(i.check_id == "PAY-NO-HR" for i in issues(pipe))


def test_person_without_display_name_does_not_break_checks(tmp_path):
    found = gold_issues(
        tmp_path, persons=[{"person_id": "P-E1", "display_name": None}],
        shifts=[{"shift_id": "s1", "hours": 30}, {"shift_id": "s2", "work_date": date(2026, 9, 15), "hours": 30}],
        pay=[{"pay_id": "a", "hours_paid": None}])
    assert _no_check_error(found)
