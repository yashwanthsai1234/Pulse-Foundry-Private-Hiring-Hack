"""PBJ export: one row per person x facility x work date from gold shifts (IMPLEMENTATION §14).

Status: `ready` when the scheduled hours of the pay period match the paid hours within the hours tolerance
and the person has an HR record. Everything else is `needs_signoff` with a note. Hours are never redistributed, except that a shift crossing midnight is split by calendar day (CMS PBJ is calendar-day based). A day inside two overlapping pay periods is compared with the earlier one
(PAY-PERIOD-OVERLAP reports the overlap) and its hours are counted once.

Sources:
- https://download.cms.gov/pbj/pbj_employeedetailpuf_documentation_january_2022.pdf  (job codes 7 RN, 9 LPN, 10 CNA)
- https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf  (PBJ policy manual: daily hours per employee)
- https://www.simpleltc.com/?p=11898  (PBJ is calendar-day based: a shift across midnight is split between the two days)
- https://onshift.com/5-payroll-based-journal-gotchas-and-how-to-avoid-them  (PBJ gotchas: overnight shifts split at midnight)
- https://duckdb.org/docs/stable/sql/functions/timestamp.html#generate_seriestimestamp-timestamp-interval  (generate_series over days)
- https://duckdb.org/docs/stable/sql/query_syntax/from.html#lateral-joins  (LATERAL: at most one pay period per day)
"""
from __future__ import annotations

import polars as pl

from sot.config import Settings
from sot.core.pack import Pack
from sot.store.db import DB

SCHEMA = {"facility_id": pl.Utf8, "employee_id": pl.Utf8, "person_id": pl.Utf8, "work_date": pl.Date,
          "job_code": pl.Int64, "hours": pl.Float64, "status": pl.Utf8, "note": pl.Utf8}
SQL = """
WITH period AS (
  SELECT p.person_id, p.period_start, p.period_end, p.hours_paid,
         p.facility_id,
         (SELECT coalesce(sum(s.hours), 0) FROM shifts s
          WHERE s.person_id = p.person_id AND s.facility_id IS NOT DISTINCT FROM p.facility_id AND s.work_date BETWEEN p.period_start AND p.period_end) AS scheduled
  FROM pay_periods p),
-- a shift that crosses midnight is split by calendar day, in proportion to the time on each side
segment AS (
  SELECT facility_id, person_id, role, work_date AS day, hours FROM shifts
  WHERE start_ts IS NULL OR end_ts <= start_ts OR end_ts::DATE = start_ts::DATE
  UNION ALL
  SELECT s.facility_id, s.person_id, s.role, d::DATE,
         s.hours * epoch(least(s.end_ts, d + INTERVAL 1 DAY) - greatest(s.start_ts, d)) / epoch(s.end_ts - s.start_ts)
  FROM shifts s, unnest(generate_series(s.start_ts::DATE, (s.end_ts - INTERVAL 1 MICROSECOND)::DATE, INTERVAL 1 DAY)) AS u(d)
  WHERE s.end_ts > s.start_ts AND s.end_ts::DATE > s.start_ts::DATE),
day AS (
  SELECT facility_id, person_id, day AS work_date, sum(hours) AS hours, any_value(role) AS role FROM segment GROUP BY ALL)
SELECT d.facility_id, per.employee_id, per.person_id, per.has_hr, d.work_date, coalesce(per.role, d.role) AS role,
       d.hours, pd.hours_paid AS paid, pd.scheduled
FROM day d JOIN persons per ON per.person_id = d.person_id
LEFT JOIN LATERAL (SELECT hours_paid, scheduled FROM period p WHERE p.person_id = d.person_id
                   AND d.work_date BETWEEN p.period_start AND p.period_end
                   ORDER BY p.facility_id IS NOT DISTINCT FROM d.facility_id DESC, p.period_start LIMIT 1) pd ON TRUE
ORDER BY per.employee_id, d.work_date, d.facility_id
"""


def _status(row: dict, tol_abs: float, tol_rel: float, job_code: int | None) -> tuple[str, str | None]:
    if not row["has_hr"]:
        return "needs_signoff", "no HR record"
    if job_code is None:
        return "needs_signoff", f"no PBJ job code for role {row['role']}"
    if row["paid"] is None:
        return "needs_signoff", "no payroll for this period"
    if abs(row["paid"] - row["scheduled"]) > max(tol_abs, tol_rel * row["paid"]):
        return "needs_signoff", f"paid {row['paid']:g}, scheduled {row['scheduled']:g}"
    return "ready", None


def build_pbj(db: DB, pack: Pack, settings: Settings) -> pl.DataFrame:
    codes = pack.pbj["job_codes"]
    rows = []
    for r in db.query(SQL):
        job_code = codes.get(r["role"])
        status, note = _status(r, settings["hours.tolerance_abs"], settings["hours.tolerance_rel"], job_code)
        rows.append({**{c: r[c] for c in ("facility_id", "employee_id", "person_id", "work_date", "hours")},
                     "job_code": job_code, "status": status, "note": note})
    return pl.DataFrame(rows, schema=SCHEMA).select(pack.pbj["columns"])
