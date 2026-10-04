-- id: PAY-PERIOD-OVERLAP
-- severity: HIGH
-- title: "Two pay periods of one person overlap"
-- action: "Payroll: the same days are paid twice. Correct the period dates or void one row."
-- Sources: https://en.wikipedia.org/wiki/Interval_(mathematics)
SELECT [a.person_id] AS entity_ids, a.facility_id, greatest(a.period_start, b.period_start) AS period_start,
       least(a.period_end, b.period_end) AS period_end,
       printf('%s has overlapping pay periods %s to %s (%s) and %s to %s (%s).', coalesce(p.display_name, '(no name)'), a.period_start,
              a.period_end, a.pay_id, b.period_start, b.period_end, b.pay_id) AS message,
       json_object('records', [a.record_id, b.record_id], 'field', 'pay.period_start') AS evidence,
       a.pay_id || '|' || b.pay_id AS key
FROM pay_periods a JOIN pay_periods b ON a.person_id = b.person_id AND a.facility_id IS NOT DISTINCT FROM b.facility_id
     AND a.pay_id < b.pay_id AND a.period_start <= b.period_end AND b.period_start <= a.period_end
JOIN persons p ON p.person_id = a.person_id
WHERE a.period_start <= a.period_end AND b.period_start <= b.period_end
