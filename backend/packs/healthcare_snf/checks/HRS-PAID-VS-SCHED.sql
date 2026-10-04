-- id: HRS-PAID-VS-SCHED
-- severity: HIGH
-- title: "Paid hours do not match scheduled hours"
-- action: "Payroll: confirm the timecard. Scheduler: confirm the schedule."
-- Sources: https://duckdb.org/docs/stable/sql/statements/set_variable.html
WITH sched AS (
  SELECT p.pay_id, coalesce(sum(s.hours), 0) AS hours, list(s.shift_id ORDER BY s.work_date) FILTER (WHERE s.shift_id IS NOT NULL) AS shift_ids
  FROM pay_periods p LEFT JOIN shifts s ON s.person_id = p.person_id AND s.facility_id IS NOT DISTINCT FROM p.facility_id AND s.work_date BETWEEN p.period_start AND p.period_end
  GROUP BY p.pay_id)
SELECT [p.person_id] AS entity_ids, p.facility_id, p.period_start, p.period_end,
       printf('%s paid %.1f h, scheduled %.1f h (%+.1f h).', coalesce(per.display_name, '(no name)'), coalesce(p.hours_paid, 0), s.hours, coalesce(p.hours_paid, 0) - s.hours) AS message,
       json_object('records', [p.record_id], 'shifts', coalesce(s.shift_ids, []), 'field', 'pay.hours_paid') AS evidence, p.pay_id AS key
FROM pay_periods p JOIN sched s USING (pay_id) JOIN persons per ON per.person_id = p.person_id
WHERE abs(p.hours_paid - s.hours) > greatest(getvariable('hours_tol_abs'), getvariable('hours_tol_rel') * p.hours_paid)
