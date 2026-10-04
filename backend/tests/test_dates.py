from datetime import date

from sot.core.models import Locator, SourceRecord
from sot.normalize.dates import date_anchors, infer_column_date_format, parse_date, resolve_weekday_date


def test_iso_column():
    assert infer_column_date_format(["2026-09-14", "2026-09-20"]) == ("%Y-%m-%d", False)
    assert parse_date("2026-09-14", "%Y-%m-%d") == date(2026, 9, 14)


def test_us_slash_unambiguous():
    fmt, amb = infer_column_date_format(["09/14/2026", "10/01/2026"])
    assert (fmt, amb) == ("%m/%d/%Y", False)


def test_day_first_detected_by_part_over_12():
    assert infer_column_date_format(["14/09/2026", "01/10/2026"]) == ("%d/%m/%Y", False)


def test_two_digit_year():
    fmt, _ = infer_column_date_format(["09/14/26", "10/01/26"])
    assert parse_date("09/14/26", fmt) == date(2026, 9, 14)


def test_dmy_month_name_and_long_form():
    assert parse_date("14-Sep-2026") == date(2026, 9, 14)
    assert parse_date("Sep 14, 2026") == date(2026, 9, 14)


def test_excel_serial():
    fmt, amb = infer_column_date_format(["46279", "46285"])
    assert not amb
    assert parse_date("46279", fmt) == date(2026, 9, 14)


def test_ambiguous_column_defaults_to_us():
    fmt, amb = infer_column_date_format(["03/04/2026", "05/06/2026"])
    assert (fmt, amb) == ("%m/%d/%Y", True)
    assert parse_date("03/04/2026", fmt) == date(2026, 3, 4)


def test_garbage_and_empty():
    assert infer_column_date_format(["abc", "xyz"]) == (None, False)
    assert infer_column_date_format([]) == (None, False)
    assert parse_date("not a date") is None
    assert parse_date("2026-02-31") is None


def test_weekday_year_resolution():
    assert resolve_weekday_date("Mon", 9, 14, anchors=[date(2026, 9, 20)]) == date(2026, 9, 14)
    assert resolve_weekday_date("Mon", 2, 30, anchors=[date(2026, 9, 20)]) is None
    assert resolve_weekday_date("Mon", 9, 14, anchors=[]) is None


def test_date_anchors():
    loc = Locator(file_id="f", file_name="f.csv")
    rec = SourceRecord(record_id="f:0:0:2", template_id="payroll", entity="pay_period",
                       fields={"pay.period_end": "2026-09-20", "pay.hours_paid": 36.0, "person.full_name": "A"}, raw={}, loc=loc)
    assert date_anchors([rec]) == [date(2026, 9, 20)]
