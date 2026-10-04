"""B2 attacks on date spellings, mixed date columns and impossible dates."""
from datetime import date

import pytest

from tests.breakers.edge_world import HR, LIC, NOISE, PAY, hr_row, run

EXP = [date(2027, 5, 31), date(2026, 12, 31), date(2027, 8, 31), date(2027, 2, 28)]
VERIFIED, P_START, P_END = date(2026, 9, 1), date(2026, 9, 14), date(2026, 9, 20)

STYLES = {
    "us": lambda d: d.strftime("%m/%d/%Y"),
    "day_first_dotted": lambda d: d.strftime("%d.%m.%Y"),
    "iso_datetime_T": lambda d: d.isoformat() + "T00:00:00",
    "iso_datetime_space": lambda d: d.isoformat() + " 00:00:00",
    "month_name_full": lambda d: d.strftime("%B %d, %Y"),
    "day_month_name_full": lambda d: d.strftime("%d %B %Y"),
    "compact": lambda d: d.strftime("%Y%m%d"),
    "excel_serial": lambda d: str((d - date(1899, 12, 30)).days),
    "slash_ymd": lambda d: d.strftime("%Y/%m/%d"),
    "mon_d_y": lambda d: f"{d.strftime('%b')} {d.day}, {d.year}",
    "iso_unpadded": lambda d: f"{d.year}-{d.month}-{d.day}",
    "d_mon_y": lambda d: d.strftime("%d-%b-%Y"),
}


@pytest.mark.parametrize("style", sorted(STYLES))
def test_whole_file_in_one_date_style_is_read(tmp_path, settings, style):
    """Every date column of HR, licence and payroll in one style: expiries and pay periods must come out right."""
    f = STYLES[style]
    hr = [hr_row(i, license_expiration=f(EXP[i]), hire_date=f(date(2020, 3, 2))) for i in range(4)]
    lic = [[*LIC[i][:3], f(EXP[i]), f(VERIFIED)] for i in range(4)]
    pay = [[*PAY[i][:4], f(P_START), f(P_END), PAY[i][6]] for i in range(4)]
    r = run(tmp_path, settings, hr=hr, lic=lic, pay=pay)
    got = [c["expires_on"] for pid in ("P-E201", "P-E202", "P-E203", "P-E204") for c in r.creds(pid)]
    assert got == EXP, (got, sorted(r.attention()))
    assert {(p["period_start"], p["period_end"]) for pid in ("P-E201", "P-E202") for p in r.pay_periods(pid)} == {(P_START, P_END)}
    assert "TABLE-UNMAPPED" not in r.checks()


def test_one_us_date_among_iso_dates_in_the_licence_column(tmp_path, settings):
    """One licence row exported as 09/14/2026 (unambiguous, 14 > 12) while the other rows are ISO."""
    lic = [["RN-551203", "REYES, SOFIA", "RN", "09/14/2026", "2026-09-01"], *LIC[1:]]
    hr = [hr_row(0, license_expiration="09/14/2026"), *HR[1:]]
    r = run(tmp_path, settings, hr=hr, lic=lic)
    assert [c["expires_on"] for c in r.creds("P-E201")] == [date(2026, 9, 14)]


@pytest.mark.parametrize("bad", ["TBD", "N/A", "pending renewal"])
def test_unreadable_license_expiry_is_at_least_medium(tmp_path, settings, bad):
    """A licence whose expiry cannot be read can never be tracked (problem #3 of the brief) - not a LOW parse note."""
    lic = [["RN-551203", "REYES, SOFIA", "RN", bad, "2026-09-01"], *LIC[1:]]
    hr = [hr_row(0, license_expiration=bad), *HR[1:]]
    r = run(tmp_path, settings, hr=hr, lic=lic)
    sev = [i.severity for i in r.issues if i.check_id.startswith(("PARSE", "LIC")) and i.severity != "INFO" and i.check_id != "COV-RN-DAILY"]
    assert any(s in ("MEDIUM", "HIGH", "CRITICAL") for s in sev), sev


def test_blank_license_expiry_is_flagged(tmp_path, settings):
    lic = [["RN-551203", "REYES, SOFIA", "RN", "", "2026-09-01"], *LIC[1:]]
    hr = [hr_row(0, license_expiration=""), *HR[1:]]
    r = run(tmp_path, settings, hr=hr, lic=lic)
    assert r.attention() - NOISE, "a licence with no expiry date raised nothing"


def test_future_hire_date_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, hire_date="2031-03-02"), *HR[1:]])
    assert r.about("P-E201", *NOISE), "hire date in 2031 (as_of 2026-09-21) raised nothing"


def test_paid_and_scheduled_before_hire_date_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, hire_date="2026-10-01"), *HR[1:]])
    assert r.about("P-E201", *NOISE), "pay and shifts in Sept 2026 for someone hired 2026-10-01 raised nothing"


def test_mixed_day_first_dates_in_payroll_are_not_silently_us(tmp_path, settings):
    """A whole payroll column in dd/mm/yyyy (14/09/2026 - 20/09/2026) is read day-first because 14 > 12."""
    pay = [[*r[:4], "14/09/2026", "20/09/2026", r[6]] for r in PAY]
    r = run(tmp_path, settings, pay=pay)
    assert {(p["period_start"], p["period_end"]) for p in r.p.db.query("SELECT * FROM pay_periods")} == {(P_START, P_END)}
