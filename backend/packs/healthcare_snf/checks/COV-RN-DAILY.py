"""COV-RN-DAILY: a facility needs a registered nurse on duty for 8 consecutive hours every day.

Rule: 42 CFR 483.35(b)(1). For each facility and each day of its schedule, the RN shift intervals are clipped to
the day and merged (touching intervals join, so 11p-7a followed by 7a-3p is one span). The longest merged span
must be at least 8 h. The schedule range is the Monday..Sunday weeks that contain the facility's shifts, because
OFF cells are not shifts and the schedule grids are weekly.

Sources:
- https://www.law.cornell.edu/cfr/text/42/483.35  (42 CFR 483.35(b): RN 8 consecutive hours a day, 7 days a week)
- https://www.govinfo.gov/content/pkg/CFR-2019-title42-vol5/pdf/CFR-2019-title42-vol5-sec483-35.pdf
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sot.core.models import IssueDraft

MIN_HOURS = 8.0


def _longest_span_hours(intervals: list[tuple[datetime, datetime]], day: date) -> float:
    lo, hi = datetime.combine(day, time()), datetime.combine(day + timedelta(days=1), time())
    clipped = sorted((max(a, lo), min(b, hi)) for a, b in intervals if a < hi and b > lo)
    best, cur_start, cur_end = timedelta(), None, None
    for a, b in clipped:
        if cur_end is not None and a <= cur_end:
            cur_end = max(cur_end, b)
        else:
            cur_start, cur_end = a, b
        best = max(best, cur_end - cur_start)
    return best.total_seconds() / 3600


def run(db, ctx) -> list[IssueDraft]:
    drafts = []
    unplaced = db.query("SELECT count(*) AS n FROM shifts WHERE facility_id IS NULL")[0]["n"]
    if unplaced:  # a shift without a facility cannot count towards any facility's RN coverage
        drafts.append(IssueDraft(
            check_id="COV-RN-DAILY", severity="MEDIUM", title="Shifts without a facility are not in the RN coverage check",
            message=f"{unplaced} scheduled shift(s) have no resolved facility, so RN coverage cannot count them.",
            key="no-facility", evidence_refs={"shifts": [r["shift_id"] for r in db.query(
                "SELECT shift_id FROM shifts WHERE facility_id IS NULL ORDER BY shift_id LIMIT 10")]},
            action="Scheduler: map the schedule title to a facility (or add the facility to the vocabulary)."))
    for fac in db.query("SELECT DISTINCT facility_id FROM shifts WHERE facility_id IS NOT NULL ORDER BY 1"):
        fid = fac["facility_id"]
        dates = db.query("SELECT min(work_date) d0, max(work_date) d1 FROM shifts WHERE facility_id = ?", [fid])[0]
        first = dates["d0"] - timedelta(days=dates["d0"].weekday())
        last = dates["d1"] + timedelta(days=6 - dates["d1"].weekday())
        rn = db.query("SELECT shift_id, start_ts, end_ts FROM shifts WHERE facility_id = ? AND role = 'RN' "
                      "AND start_ts IS NOT NULL ORDER BY start_ts", [fid])
        intervals = [(r["start_ts"], r["end_ts"]) for r in rn]
        n_days = (last - first).days + 1
        missing = [first + timedelta(days=i) for i in range(n_days)
                   if _longest_span_hours(intervals, first + timedelta(days=i)) < MIN_HOURS]
        if missing:
            drafts.append(IssueDraft(
                check_id="COV-RN-DAILY", severity="CRITICAL", title="No RN on duty for 8 consecutive hours",
                message=f"{fid}: no RN for 8 consecutive hours on {len(missing)} of {n_days} days: "
                        f"{', '.join(d.isoformat() for d in missing)}.",
                facility_id=fid, period_start=first, period_end=last, key=fid,
                evidence_refs={"shifts": [r["shift_id"] for r in rn][:10], "days_without_rn": len(missing)},
                action="DON: schedule an RN for 8 consecutive hours on each listed day (42 CFR 483.35(b))."))
    return drafts
