-- id: SHIFT-OVERLAP
-- severity: HIGH
-- title: "Two shifts of one person overlap"
-- action: "Scheduler: a person cannot work two places at once. Correct one of the shifts."
-- Sources: https://en.wikipedia.org/wiki/Interval_(mathematics)
SELECT [a.person_id] AS entity_ids, CASE WHEN a.facility_id = b.facility_id THEN a.facility_id END AS facility_id,
       a.work_date AS period_start, b.work_date AS period_end,
       printf('%s has overlapping shifts: %s %s to %s at %s and %s %s to %s at %s.', coalesce(p.display_name, '(no name)'),
              a.work_date, strftime(a.start_ts, '%H:%M'), strftime(a.end_ts, '%H:%M'), a.facility_id,
              b.work_date, strftime(b.start_ts, '%H:%M'), strftime(b.end_ts, '%H:%M'), b.facility_id) AS message,
       json_object('shifts', [a.shift_id, b.shift_id]) AS evidence, a.shift_id || '|' || b.shift_id AS key
FROM shifts a JOIN shifts b ON a.person_id = b.person_id AND a.shift_id < b.shift_id
     AND a.start_ts < b.end_ts AND b.start_ts < a.end_ts
JOIN persons p ON p.person_id = a.person_id
