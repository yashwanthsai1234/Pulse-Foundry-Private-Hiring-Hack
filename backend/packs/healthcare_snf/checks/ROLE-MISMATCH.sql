-- id: ROLE-MISMATCH
-- severity: MEDIUM
-- title: "Payroll or schedule role differs from the HR role"
-- action: "HR: confirm the job title. Payroll and scheduler: correct the role."
-- Sources: https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf
WITH seen AS (
  SELECT person_id, 'payroll' AS source, role, min(period_start) AS d0, max(period_end) AS d1, list(record_id) AS records, [] AS shifts FROM pay_periods GROUP BY person_id, role
  UNION ALL
  SELECT person_id, 'schedule', role, min(work_date), max(work_date), list(DISTINCT record_id), list(shift_id) FROM shifts GROUP BY person_id, role)
SELECT [s.person_id] AS entity_ids, NULL AS facility_id, s.d0 AS period_start, s.d1 AS period_end,
       printf('%s: %s role is %s, HR role is %s.', coalesce(p.display_name, '(no name)'), s.source, s.role, p.role) AS message,
       json_object('records', s.records, 'shifts', s.shifts) AS evidence, s.source || ':' || s.role AS key
FROM seen s JOIN persons p ON p.person_id = s.person_id
WHERE p.has_hr AND s.role IS NOT NULL AND p.role IS NOT NULL AND s.role <> p.role
