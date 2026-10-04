-- id: PAY-HOURS-INVALID
-- severity: HIGH
-- title: "Paid hours are missing, negative or impossible"
-- action: "Payroll: correct the hours in the export. A paid-vs-scheduled comparison is meaningless until then."
-- Sources: https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf
-- More than 100 paid hours per week is not credible for one employee (168 h exist in a week).
SELECT [p.person_id] AS entity_ids, p.facility_id, p.period_start, p.period_end,
       CASE WHEN p.hours_paid IS NULL THEN printf('%s: paid hours are missing for %s to %s.', coalesce(per.display_name, '(no name)'), p.period_start, p.period_end)
            ELSE printf('%s: %g paid hours for %s to %s is not credible.', coalesce(per.display_name, '(no name)'), p.hours_paid, p.period_start, p.period_end) END AS message,
       json_object('records', [p.record_id], 'field', 'pay.hours_paid') AS evidence, p.pay_id AS key
FROM pay_periods p JOIN persons per USING (person_id)
WHERE p.hours_paid IS NULL OR p.hours_paid < 0
   OR p.hours_paid > 100 * greatest(1, ceil((p.period_end - p.period_start + 1) / 7.0))
