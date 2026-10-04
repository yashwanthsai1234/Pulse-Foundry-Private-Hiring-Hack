-- id: PAY-NO-HR
-- severity: HIGH
-- title: "Paid person has no HR record"
-- action: "HR and payroll: confirm the person exists. A payroll row without an HR record may be a ghost employee."
-- Sources: https://en.wikipedia.org/wiki/Ghost_employee
SELECT [p.person_id] AS entity_ids, p.facility_id, p.period_start, p.period_end,
       printf('%s was paid %.1f h but has no HR record.', coalesce(per.display_name, '(no name)'), coalesce(p.hours_paid, 0)) AS message,
       json_object('records', [p.record_id]) AS evidence, p.pay_id AS key
FROM pay_periods p JOIN persons per ON per.person_id = p.person_id WHERE NOT per.has_hr
