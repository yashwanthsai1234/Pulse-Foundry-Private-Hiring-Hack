-- id: SCHED-NO-HR
-- severity: MEDIUM
-- title: "Scheduled person has no HR record"
-- action: "HR: add the person to the roster, or fix the name on the schedule."
-- Sources: https://en.wikipedia.org/wiki/Record_linkage
SELECT [s.person_id] AS entity_ids, CASE WHEN count(DISTINCT s.facility_id) = 1 THEN min(s.facility_id) END AS facility_id,
       NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s is on the schedule (%d shift(s)) but cannot be matched to an HR record (%s to %s).', coalesce(any_value(p.display_name), '(no name)'), count(*), min(s.work_date), max(s.work_date)) AS message,
       json_object('shifts', list(s.shift_id ORDER BY s.work_date)) AS evidence, '' AS key
FROM shifts s JOIN persons p ON p.person_id = s.person_id WHERE NOT p.has_hr
GROUP BY s.person_id
