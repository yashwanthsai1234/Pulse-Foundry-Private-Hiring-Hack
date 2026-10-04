-- id: LIC-SCOPE
-- severity: CRITICAL
-- title: "Scheduled above the scope of the license held"
-- action: "DON: replace the person on these shifts or confirm the higher license with the state board."
-- Sources: https://www.law.cornell.edu/cfr/text/42/483.35
SELECT [s.person_id] AS entity_ids, CASE WHEN count(DISTINCT s.facility_id) = 1 THEN min(s.facility_id) END AS facility_id,
       NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s is scheduled as %s on %d shift(s) but holds only %s (%s to %s).', coalesce(any_value(p.display_name), '(no name)'), s.role, count(*),
              (SELECT string_agg(DISTINCT c.credential_type, ', ') FROM credentials c WHERE c.holder_id = s.person_id),
              min(s.work_date), max(s.work_date)) AS message,
       json_object('shifts', list(s.shift_id ORDER BY s.work_date)) AS evidence, s.role AS key
FROM shifts s JOIN persons p ON p.person_id = s.person_id
WHERE s.role IN (SELECT role FROM role_scope)
  AND EXISTS (SELECT 1 FROM credentials c WHERE c.holder_id = s.person_id)
  AND NOT EXISTS (SELECT 1 FROM credentials c JOIN role_scope r ON r.license_type = c.credential_type
                  WHERE c.holder_id = s.person_id AND r.role = s.role)
GROUP BY s.person_id, s.role
