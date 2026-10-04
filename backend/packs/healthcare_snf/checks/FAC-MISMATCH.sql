-- id: FAC-MISMATCH
-- severity: MEDIUM
-- title: "Works at a facility that is not the home facility"
-- action: "Scheduler: confirm the float assignment or correct the schedule."
-- Sources: https://en.wikipedia.org/wiki/Record_linkage
SELECT [s.person_id] AS entity_ids, s.facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s works %d shift(s) at %s, home facility is %s: float or schedule error (%s to %s).', coalesce(any_value(p.display_name), '(no name)'), count(*), s.facility_id, any_value(p.home_facility_id), min(s.work_date), max(s.work_date)) AS message,
       json_object('shifts', list(s.shift_id ORDER BY s.work_date)) AS evidence, s.facility_id AS key
FROM shifts s JOIN persons p ON p.person_id = s.person_id
WHERE s.facility_id IS NOT NULL AND p.home_facility_id IS NOT NULL AND s.facility_id <> p.home_facility_id
GROUP BY s.person_id, s.facility_id
