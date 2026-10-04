-- id: HR-DUP-ROW
-- severity: MEDIUM
-- title: "Two HR rows share an employee id but differ"
-- action: "HR: keep one row for the employee and correct the other."
-- Sources: https://en.wikipedia.org/wiki/Data_deduplication
SELECT ['P-' || eid] AS entity_ids, NULL AS facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('Employee %s has %d HR rows with different values.', eid, count(*)) AS message,
       json_object('records', list(record_id ORDER BY record_id)) AS evidence, eid AS key
FROM (SELECT record_id, fields, upper(json_extract_string(fields, '$."person.employee_id"')) AS eid
      FROM source_records WHERE template_id = 'hr_roster')
WHERE eid IS NOT NULL
GROUP BY eid HAVING count(*) > 1 AND count(DISTINCT fields::VARCHAR) > 1
