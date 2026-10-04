-- id: HR-HIRE-DATE
-- severity: MEDIUM
-- title: "Hire date is in the future or after the person started working"
-- action: "HR: correct the hire date, or the pay and schedule rows if the person had not started yet."
-- Sources: https://en.wikipedia.org/wiki/Ghost_employee
-- First activity = the earlier of the end of the first pay period and the first scheduled shift (a hire in the
-- middle of a pay period is normal).
WITH first_work AS (
  SELECT p.person_id, p.display_name, p.hire_date,
         least((SELECT min(period_end) FROM pay_periods x WHERE x.person_id = p.person_id),
               (SELECT min(work_date) FROM shifts s WHERE s.person_id = p.person_id)) AS first_day
  FROM persons p WHERE p.hire_date IS NOT NULL)
SELECT [person_id] AS entity_ids, NULL AS facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       CASE WHEN hire_date > getvariable('as_of') THEN printf('%s: hire date %s is in the future.', coalesce(display_name, '(no name)'), hire_date)
            ELSE printf('%s: hire date %s is after the first pay period or shift (%s).', coalesce(display_name, '(no name)'), hire_date, first_day) END AS message,
       json_object('claims', (SELECT list(claim_id) FROM claims WHERE entity_id = person_id AND attribute = 'hire_date')) AS evidence,
       person_id AS key
FROM first_work WHERE hire_date > getvariable('as_of') OR hire_date > first_day
