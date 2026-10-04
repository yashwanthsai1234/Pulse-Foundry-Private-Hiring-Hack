-- id: LIC-NONE-FOR-ROLE
-- severity: CRITICAL
-- title: "Works a licensed role with no credential on file"
-- action: "Registration: obtain the license number and verify it with the state board before the next shift."
-- Sources: https://www.law.cornell.edu/cfr/text/42/483.35
SELECT [s.person_id] AS entity_ids, CASE WHEN count(DISTINCT s.facility_id) = 1 THEN min(s.facility_id) END AS facility_id,
       NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s is scheduled as %s on %d shift(s) but has no credential on file (%s to %s).', coalesce(any_value(p.display_name), '(no name)'), s.role, count(*), min(s.work_date), max(s.work_date)) AS message,
       json_object('shifts', list(s.shift_id ORDER BY s.work_date)) AS evidence, s.role AS key
FROM shifts s JOIN persons p ON p.person_id = s.person_id
WHERE s.role IN (SELECT role FROM role_scope)
  AND NOT EXISTS (SELECT 1 FROM credentials c WHERE c.holder_id = s.person_id)
GROUP BY s.person_id, s.role
