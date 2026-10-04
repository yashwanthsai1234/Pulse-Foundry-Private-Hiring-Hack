"""B2 attacks on the schedule PDF (hand-built specs through tools/synth/render.py)."""
from datetime import date, datetime

import pymupdf
import pytest

from tests.breakers.edge_world import NOISE, R0, R1, SCHED_PAGES, pages, run

DAY_HDR = ["Staff", "Role"]
ISO_HDR = [*DAY_HDR, *(f"2026-09-{d}" for d in range(14, 21))]
SLASH_HDR = [*DAY_HDR, *(f"09/{d}" for d in range(14, 21))]
FULL_HDR = [*DAY_HDR, *(f"{w} 9/{d}/2026" for w, d in zip("Mon Tue Wed Thu Fri Sat Sun".split(), range(14, 21)))]


def _count(r):
    return len(r.shifts())


def _baseline_shift_count():
    return sum(c != "OFF" for page in SCHED_PAGES for row in page["rows"] for c in row[2:])


def test_staff_missing_from_hr_is_sched_no_hr(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(R0 + [["Zelda Ghost", "RN", "7a-3p", *["OFF"] * 6]]))
    assert [i.severity for i in r.ids("SCHED-NO-HR")] == ["MEDIUM"]


def test_unknown_shift_tokens_are_flagged_not_dropped_silently(tmp_path, settings):
    row = ["Sofia Reyes", "RN", "7a-3:30p", "D", "N", "8-4", "OFF", "OFF", "OFF"]
    r = run(tmp_path, settings, sched=pages(rows0=[row, R0[1]]))
    assert len(r.ids("PARSE-SHIFT-TOKEN")) >= 3
    assert [s["hours"] for s in r.shifts("P-E201")] == [8.5]


def test_double_shift_cell_is_not_silently_truncated(tmp_path, settings):
    """'7a-3p/3p-11p' is 16 h. Today only 7a-3p (8 h) survives and nothing is flagged."""
    row = ["Sofia Reyes", "RN", "OFF", "OFF", "OFF", "OFF", "7a-3p/3p-11p", "OFF", "OFF"]
    r = run(tmp_path, settings, sched=pages(rows0=[row, R0[1]]))
    hours = sum(s["hours"] for s in r.shifts("P-E201"))
    assert hours == 16.0 or r.ids("PARSE-SHIFT-TOKEN"), (hours, sorted(r.checks()))


def test_overnight_shift_on_sunday_ends_next_week(tmp_path, settings):
    row = ["Sofia Reyes", "RN", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF", "11p-7a"]
    r = run(tmp_path, settings, sched=pages(rows0=[row, R0[1]]))
    (s,) = r.shifts("P-E201")
    assert s["work_date"] == date(2026, 9, 20) and s["end_ts"] == datetime(2026, 9, 21, 7, 0) and s["hours"] == 8.0


def test_same_person_on_both_facility_pages_same_day_overlaps(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(rows1=R1 + [["Sofia Reyes", "RN", "7a-3p", *["OFF"] * 6]]))
    assert r.ids("SHIFT-OVERLAP") and r.ids("FAC-MISMATCH")


def test_legend_contradicting_token_times_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(footnote="Shifts: 7a-3p, 3p-11p, 11p-7a are 7 hours. 7a-7p is 12 hours."))
    assert r.ids("LEGEND-MISMATCH")


def test_page_without_footnote_still_reads_shifts(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(footnote=""))
    assert _count(r) == _baseline_shift_count()


def test_cna_scheduled_as_rn_is_lic_scope(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(rows1=[["Marcus Bell", "RN", *R1[0][2:]], R1[1]]))
    assert [i.entity_ids for i in r.ids("LIC-SCOPE")] == [["P-E202"]]


def test_header_with_full_dates_mon_9_14_2026(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(header=FULL_HDR))
    assert _count(r) == _baseline_shift_count()


@pytest.mark.parametrize("header", [ISO_HDR, SLASH_HDR], ids=["iso_dates", "mm_dd_no_weekday"])
def test_header_dates_without_weekday_name_are_read_or_flagged(tmp_path, settings, header):
    """Explicit dates in the header are easier than 'Mon 09/14'; today the whole PDF yields 0 shifts and no PDF/table issue."""
    r = run(tmp_path, settings, sched=pages(header=header))
    assert _count(r) == _baseline_shift_count() or {"TABLE-UNMAPPED", "FILE-QUARANTINED", "PARSE-PDF-LOW-CONFIDENCE"} & r.checks(), (
        _count(r), sorted(r.attention()))


def test_header_weekdays_without_dates_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, sched=pages(header=[*DAY_HDR, "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
    assert _count(r) == _baseline_shift_count() or {"TABLE-UNMAPPED", "FILE-QUARANTINED", "PARSE-PDF-LOW-CONFIDENCE"} & r.checks()


@pytest.mark.parametrize("variant", ["grid", "nogrid", "wrapped_names", "portrait"])
def test_forty_rows_on_one_page_spill_over_without_losing_rows(tmp_path, settings, variant):
    first = ["Alexandria", "Priya", "Jonathan", "Dmitri", "Keisha", "Luis", "Mei", "Oluwaseun", "Grace", "Henry", "Isabel", "Tomas"]
    last = ["Montgomery", "Natarajan", "Okafor", "Kowalczyk", "Nguyen", "Alvarez", "Brown", "Chen", "Davis", "Evans"]
    cells = ["7a-3p", "OFF", "3p-11p", "OFF", "11p-7a", "7a-7p", "OFF"]
    rows = [[f"{first[i % 12]} {last[(i // 12 + i) % 10]}{'son' if i >= 60 else ''}", "CNA", *(cells[(i + d) % 7] for d in range(7))] for i in range(40)]
    expected = sum(c != "OFF" for row in rows for c in row[2:]) + sum(c != "OFF" for row in R1 for c in row[2:])
    r = run(tmp_path, settings, sched=pages(rows0=rows), variant=variant)
    assert _count(r) == expected, (_count(r), expected)


def test_text_only_pdf_without_a_table_is_flagged(tmp_path, settings):
    memo = tmp_path / "memo.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Staffing memo: please submit timesheets by Friday.")
    doc.save(memo)
    r = run(tmp_path, settings, extra=[memo])
    assert r.attention() - NOISE, "a PDF with no table at all was ingested with no issue"
