-- id: PAY-DUPLICATE
-- severity: HIGH
-- title: "One pay period appears twice with different ids or hours"
-- action: "Payroll: check whether the person was paid twice for the period and void the wrong row."
-- Sources: https://en.wikipedia.org/wiki/Data_deduplication
-- Rows read from source_records: gold keeps one pay period per person, facility and dates. The same row exported twice
-- (same payroll id, same hours) is a harmless copy and is not reported.
WITH pay AS (
  SELECT r.record_id, pr.person_id, json_extract_string(r.fields, '$."person.facility"') AS fac,
         try_cast(json_extract_string(r.fields, '$."pay.period_start"') AS DATE) AS d0,
         try_cast(json_extract_string(r.fields, '$."pay.period_end"') AS DATE) AS d1,
         coalesce(json_extract_string(r.fields, '$."pay.payroll_id"'), '') AS pid,
         json_extract_string(r.fields, '$."pay.hours_paid"') AS hours
  FROM source_records r JOIN person_records pr USING (record_id) WHERE r.template_id = 'payroll')
SELECT [pay.person_id] AS entity_ids, fac AS facility_id, d0 AS period_start, d1 AS period_end,
       printf('%s has %d payroll rows for %s to %s (ids %s; hours %s).', coalesce(any_value(per.display_name), '(no name)'), count(*), d0, d1,
              array_to_string(list(DISTINCT pid), ', '), array_to_string(list(DISTINCT hours), ', ')) AS message,
       json_object('records', list(record_id ORDER BY record_id), 'field', 'pay.hours_paid') AS evidence,
       strftime(d0, '%Y-%m-%d') || coalesce(fac, '') AS key
FROM pay JOIN persons per USING (person_id) WHERE d0 IS NOT NULL AND d1 IS NOT NULL
GROUP BY pay.person_id, fac, d0, d1
HAVING count(DISTINCT pid) > 1 OR count(DISTINCT hours) > 1
