"""Silver builder: RawTable + Mapping -> typed SourceRecords and ShiftRecords (TASKGRAPH §4 conventions)."""
import json
from datetime import date, datetime, time

import polars as pl

from sot.core.models import ExtractionInfo, FieldMatch, FileRef, Mapping, RawTable
from sot.normalize.silver import build_silver

FILE = FileRef(file_id="f" * 64, file_name="x", path="/tmp/x", size=1, received_at=datetime(2026, 9, 21))


def table(header, rows, **kw) -> RawTable:
    df = pl.DataFrame({h: [r[i] for r in rows] for i, h in enumerate(header)}, schema={h: pl.Utf8 for h in header})
    df = df.with_columns(pl.Series("_src_row", list(range(2, 2 + len(rows))), dtype=pl.Int64))
    return RawTable(table_id="t:0:0", file=FILE, parser="csv", header=header, df=df,
                    extraction=ExtractionInfo(method="csv", score=1.0), **kw)


def mapping(template, cmap) -> Mapping:
    return Mapping(table_id="t:0:0", template_id=template, confidence=1.0, unmapped_columns=[],
                   missing_required=[], source="auto",
                   matches=[FieldMatch(column=c, field_id=f, score=1, header_score=1, value_score=1, type_score=1)
                            for c, f in cmap.items()])


def test_payroll_rows_are_typed(pack):
    t = table(["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"],
              [["P-3002", "BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "48"]])
    m = mapping("payroll", {"payroll_id": "pay.payroll_id", "employee_name": "person.full_name",
                            "job_code": "person.role", "facility_code": "person.facility",
                            "period_start": "pay.period_start", "period_end": "pay.period_end",
                            "hours_paid": "pay.hours_paid"})
    recs, shifts = build_silver(t, m, pack, anchors=[])
    assert shifts == []
    (r,) = recs
    assert r.record_id == "t:0:0:2" and r.template_id == "payroll" and r.entity == "pay_period"
    assert r.fields["person.role"] == "CNA" and r.fields["person.facility"] == "FAC-RVD"
    assert r.fields["pay.hours_paid"] == 48.0 and r.fields["pay.period_start"] == "2026-09-14"
    assert (r.person_key.family, r.person_key.given) == ("bell", "marcus")
    assert r.loc.row == 2 and r.raw["employee_name"] == "BELL, MARCUS"


def test_hr_parts_phone_license_and_bad_values(pack):
    t = table(["employee_id", "first_name", "last_name", "job_title", "facility", "phone", "license_number",
               "license_expiration"],
              [["e202", "Marcus", "Bell", "Certified Nursing Assistant", "Harborview Riverdale", "(347) 555 0202",
                "cna 771045", "not a date"]])
    m = mapping("hr_roster", {"employee_id": "person.employee_id", "first_name": "person.given_name",
                              "last_name": "person.family_name", "job_title": "person.role",
                              "facility": "person.facility", "phone": "person.phone",
                              "license_number": "credential.number", "license_expiration": "credential.expires_on"})
    (r,), _ = build_silver(t, m, pack, anchors=[])
    assert r.fields["person.employee_id"] == "E202"
    assert r.fields["person.phone"] == "+13475550202"
    assert r.fields["credential.number"] == "CNA-771045"
    assert "credential.expires_on" not in r.fields
    assert "bad_date:credential.expires_on" in r.parse_issues
    assert r.person_key.given == "marcus" and r.person_key.family == "bell"


def test_schedule_grid_becomes_shifts_with_legend_and_bbox(pack):
    header = ["Staff", "Role", "Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
    rows = [["Sofia Reyes", "RN", "7a-3p", "7a-3p", "OFF", "7a-7p", "OFF", "11p-7a", "zz"]]
    legend = {"7a-3p": 8.0, "3p-11p": 8.0, "11p-7a": 8.0, "7a-7p": 12.0}
    t = table(header, rows, page=1, cell_bboxes={"0:2": (10.0, 20.0, 30.0, 40.0)},
              context={"title": "Harborview Bayside", "facility_hint": "Harborview Bayside",
                       "legend_json": json.dumps(legend)})
    m = mapping("schedule", {"Staff": "person.full_name", "Role": "person.role",
                             **{h: "schedule.day" for h in header[2:]}})
    (r,), shifts = build_silver(t, m, pack, anchors=[date(2026, 9, 20)])
    assert r.fields["person.facility"] == "FAC-BAY" and r.fields["person.role"] == "RN"
    assert [s.work_date for s in shifts] == [date(2026, 9, d) for d in (14, 15, 17, 19)]
    assert [s.hours for s in shifts] == [8.0, 8.0, 12.0, 8.0]
    assert all(s.hours_source == "both" and s.facility_id == "FAC-BAY" and s.role == "RN" for s in shifts)
    assert shifts[3].start == time(23, 0) and shifts[3].end == time(7, 0)
    assert shifts[0].loc.bbox == (10.0, 20.0, 30.0, 40.0) and shifts[0].loc.col == "Mon 09/14"
    assert shifts[0].shift_id == "t:0:0:2:2026-09-14"
    assert "shift_token:zz" in r.parse_issues


def test_legend_mismatch_is_flagged(pack):
    header = ["Staff", "Role", "Mon 09/14"]
    t = table(header, [["Sofia Reyes", "RN", "7a-7p"]],
              context={"facility_hint": "Bayside", "legend_json": json.dumps({"7a-7p": 8.0})})
    m = mapping("schedule", {"Staff": "person.full_name", "Role": "person.role", "Mon 09/14": "schedule.day"})
    (r,), (s,) = build_silver(t, m, pack, anchors=[date(2026, 9, 20)])
    assert s.hours == 12.0 and s.hours_source == "computed"  # decision RC12: times win, legend is a cross-check
    assert "legend_mismatch:7a-7p" in r.parse_issues


def test_blank_rows_skipped_and_ambiguous_dates_flagged_once(pack):
    t = table(["license_number", "name_on_license", "license_type", "expiration_date"],
              [["RN-1", "REYES, SOFIA", "RN", "03/04/2027"], [None, None, None, None],
               ["RN-2", "BELL, MARIA", "RN", "05/06/2027"]])
    m = mapping("license", {"license_number": "credential.number", "name_on_license": "person.full_name",
                            "license_type": "credential.type", "expiration_date": "credential.expires_on"})
    recs, _ = build_silver(t, m, pack, anchors=[])
    assert len(recs) == 2
    assert recs[0].fields["credential.expires_on"] == "2027-03-04"
    assert sum("date_ambiguous:credential.expires_on" in r.parse_issues for r in recs) == 1


def test_canonical_license_numbers(pack):
    from sot.normalize.silver import canonical_license
    for raw in ["RN551203", "rn 551203", "RN–551203", "RN_551203", "RN-551203", "RN.551203", "RN\u2011551203",
                "RN\u00ad551203"]:
        assert canonical_license(raw) == "RN-551203"
    assert canonical_license("NTL-2025-0042") == "NTL-2025-0042"
    assert canonical_license(" 778812 ") == "778812"


def test_hours_decimal_comma_units_and_totals_row(pack):
    t = table(["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"],
              [["P-1", "REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36,5"],
               ["P-2", "BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40 hrs"],
               ["P-3", "BELL, MARIA", "RN", "RVD", "2026-09-14", "2026-09-20", "1,234"],
               ["TOTAL", None, None, None, None, None, "112.5"]])
    m = mapping("payroll", {"payroll_id": "pay.payroll_id", "employee_name": "person.full_name",
                            "job_code": "person.role", "facility_code": "person.facility",
                            "period_start": "pay.period_start", "period_end": "pay.period_end",
                            "hours_paid": "pay.hours_paid"})
    recs, _ = build_silver(t, m, pack, anchors=[])
    assert [r.fields["pay.hours_paid"] for r in recs] == [36.5, 40.0, 1234.0, 112.5]
    assert recs[3].person_key is None
    assert any(i.startswith("row_incomplete:") and "person.full_name" in i for i in recs[3].parse_issues)
    assert not any(i.startswith("row_incomplete") for r in recs[:3] for i in r.parse_issues)


def test_day_headers_without_weekday_and_mismatch(pack):
    header = ["Staff", "Role", "09/14", "9/15/2026", "2026-09-16", "Mon\n09/17", "Friday 18 Sep"]
    t = table(header, [["Sofia Reyes", "RN", "7a-3p", "7a-3p", "7a-3p", "7a-3p", "7a-3p"]],
              context={"facility_hint": "Bayside"})
    m = mapping("schedule", {"Staff": "person.full_name", "Role": "person.role",
                             **{h: "schedule.day" for h in header[2:]}})
    (r,), shifts = build_silver(t, m, pack, anchors=[date(2026, 9, 20)])
    assert [s.work_date for s in shifts] == [date(2026, 9, d) for d in (14, 15, 16, 17, 18)]
    assert "day_mismatch:Mon\n09/17" in r.parse_issues  # 2026-09-17 is a Thursday


def test_unresolvable_day_header_is_flagged(pack):
    header = ["Staff", "Role", "Day 1"]
    t = table(header, [["Sofia Reyes", "RN", "7a-3p"]], context={"facility_hint": "Bayside"})
    m = mapping("schedule", {"Staff": "person.full_name", "Role": "person.role", "Day 1": "schedule.day"})
    (r,), shifts = build_silver(t, m, pack, anchors=[date(2026, 9, 20)])
    assert shifts == [] and "schedule_dates:Day 1" in r.parse_issues


def test_letter_code_shifts_use_legend_codes(pack):
    header = ["Staff", "Role", "Mon 09/14", "Tue 09/15"]
    t = table(header, [["Sofia Reyes", "RN", "D", "N"]],
              context={"facility_hint": "Bayside", "footnote": "D = 7a-3p, E = 3p-11p, N = 11p-7a (8 hours each)"})
    m = mapping("schedule", {"Staff": "person.full_name", "Role": "person.role",
                             "Mon 09/14": "schedule.day", "Tue 09/15": "schedule.day"})
    (r,), shifts = build_silver(t, m, pack, anchors=[date(2026, 9, 20)])
    assert [(s.token, s.start, s.end, s.hours) for s in shifts] == [
        ("D", time(7), time(15), 8.0), ("N", time(23), time(7), 8.0)]
    assert r.parse_issues == []


def test_hr_row_missing_both_name_forms_is_incomplete(pack):
    t = table(["employee_id", "first_name", "last_name", "job_title", "facility"],
              [["E1", "Sofia", "Reyes", "RN", "Bayside"], ["E2", None, None, "RN", "Bayside"]])
    m = mapping("hr_roster", {"employee_id": "person.employee_id", "first_name": "person.given_name",
                              "last_name": "person.family_name", "job_title": "person.role",
                              "facility": "person.facility"})
    recs, _ = build_silver(t, m, pack, anchors=[])
    assert not any(i.startswith("row_incomplete") for i in recs[0].parse_issues)
    assert any(i.startswith("row_incomplete:") and "person.given_name" in i for i in recs[1].parse_issues)


def test_number_validator_is_about_form_not_range(pack):
    """Mapping asks 'is this the hours column?'; impossible values are a PAY-HOURS-INVALID matter for the checks."""
    from sot.semantic.validators import build_validators
    hours = build_validators(pack)["pay.hours_paid"]
    assert all(hours(v) for v in ["36", "36,5", "40 hrs", "16h", "-8", "400", "1,036"])
    assert not any(hours(v) for v in ["abc", "RN", "2026-09-14", ""])


def test_phone_rejects_invalid_nanp_numbers():
    from sot.normalize.phones import normalize_phone
    assert normalize_phone("718-555-0201") == "+17185550201"
    assert normalize_phone("0000000000") is None and normalize_phone("111-111-1111") is None


def test_facility_found_inside_a_longer_title(pack):
    """Live panel P5: an agent-read scanned page returned 'Harborview Riverdale - Weekly Staff Schedule - Week of 09/14'."""
    from sot.normalize.silver import facility_in
    fac = pack.vocabs["facilities"]
    assert facility_in("Harborview Riverdale - Weekly Staff Schedule - Week of 09/14", fac) == "FAC-RVD"
    assert facility_in("Harborview Bayside Weekly Staff Schedule", fac) == "FAC-BAY"
    assert facility_in("BYS night roster", fac) == "FAC-BAY"
    assert facility_in("Weekly Staff Schedule", fac) is None
    assert facility_in("Bayside", fac) == "FAC-BAY"
