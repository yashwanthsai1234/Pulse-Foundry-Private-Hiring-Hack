-- id: HRS-DAILY-EXCESS
-- severity: HIGH
-- title: "More than 16 hours scheduled in one day"
-- action: "Scheduler: confirm the shifts. Check for a duplicated row or a double shift."
-- Sources: https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf
SELECT [s.person_id] AS entity_ids, CASE WHEN count(DISTINCT s.facility_id) = 1 THEN min(s.facility_id) END AS facility_id,
       s.work_date AS period_start, s.work_date AS period_end,
       printf('%s is scheduled for %.1f h on %s.', coalesce(any_value(p.display_name), '(no name)'), sum(s.hours), s.work_date) AS message,
       json_object('shifts', list(s.shift_id)) AS evidence, strftime(s.work_date, '%Y-%m-%d') AS key
FROM shifts s JOIN persons p ON p.person_id = s.person_id
GROUP BY s.person_id, s.work_date HAVING sum(s.hours) > 16
