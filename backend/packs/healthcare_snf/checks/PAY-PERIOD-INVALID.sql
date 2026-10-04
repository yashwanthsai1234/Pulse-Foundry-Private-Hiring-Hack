-- id: PAY-PERIOD-INVALID
-- severity: MEDIUM
-- title: "Pay period ends before it starts or is longer than a bi-weekly period"
-- action: "Payroll: confirm the period dates in the export."
-- Sources: https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf
-- Longest normal period: 14 days (bi-weekly); the exports of this pack are weekly.
SELECT [p.person_id] AS entity_ids, p.facility_id, p.period_start, p.period_end,
       CASE WHEN p.period_end < p.period_start
            THEN printf('%s: pay period ends (%s) before it starts (%s).', coalesce(per.display_name, '(no name)'), p.period_end, p.period_start)
            ELSE printf('%s: pay period %s to %s is %d days long.', coalesce(per.display_name, '(no name)'), p.period_start, p.period_end,
                        p.period_end - p.period_start + 1) END AS message,
       json_object('records', [p.record_id], 'field', 'pay.period_end') AS evidence, p.pay_id AS key
FROM pay_periods p JOIN persons per USING (person_id)
WHERE p.period_end < p.period_start OR p.period_end - p.period_start + 1 > 14
