-- id: ID-DUP-LICENSE
-- severity: CRITICAL
-- title: "One license number belongs to two people"
-- action: "HR: check both people against the state board. One record carries a wrong number or a duplicate identity."
-- Sources: https://en.wikipedia.org/wiki/Record_linkage
WITH n AS (
  SELECT json_extract_string(r.fields, '$."credential.number"') AS num, pr.person_id, r.record_id
  FROM source_records r JOIN person_records pr USING (record_id))
SELECT list(DISTINCT person_id ORDER BY person_id) AS entity_ids, NULL AS facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('License number %s appears for %d different people.', num, count(DISTINCT person_id)) AS message,
       json_object('records', list(record_id ORDER BY record_id)) AS evidence, num AS key
FROM n WHERE num IS NOT NULL GROUP BY num HAVING count(DISTINCT person_id) > 1
