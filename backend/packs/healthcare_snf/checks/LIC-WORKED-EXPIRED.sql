-- id: LIC-WORKED-EXPIRED
-- severity: CRITICAL
-- title: "Worked after the license expired"
-- action: "DON: verify renewal with the state board today. If not renewed, remove the person from the schedule."
-- Sources: https://www.law.cornell.edu/cfr/text/42/483.35
-- A shift counts when the credential's type is in the role scope and the person holds no other in-scope credential valid that day.
WITH late AS (
  SELECT c.credential_id, c.holder_id, c.number, c.expires_on, c.last_verified, s.shift_id, s.work_date, s.hours, s.facility_id
  FROM credentials c
  JOIN shifts s ON s.person_id = c.holder_id AND s.work_date > c.expires_on
  JOIN role_scope r ON r.role = s.role AND r.license_type = c.credential_type
  WHERE c.holder_type = 'person'
    AND NOT EXISTS (SELECT 1 FROM credentials o JOIN role_scope ro ON ro.license_type = o.credential_type
                    WHERE o.holder_id = c.holder_id AND ro.role = s.role AND o.credential_id <> c.credential_id
                      AND o.expires_on >= s.work_date))
SELECT [holder_id] AS entity_ids,
       CASE WHEN count(DISTINCT facility_id) = 1 THEN min(facility_id) END AS facility_id,
       NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s worked %d shift(s), %.1f h, after %s expired on %s: %s.%s', coalesce(any_value(p.display_name), '(no name)'), count(*),
              sum(hours), number, any_value(expires_on),
              array_to_string(list(printf('%s (%.1f h)', strftime(work_date, '%Y-%m-%d'), hours) ORDER BY work_date), ', '),
              CASE WHEN any_value(last_verified) < any_value(expires_on)
                   THEN ' Last verified before the expiry date: a renewal may exist.' ELSE '' END) AS message,
       json_object('shifts', list(shift_id ORDER BY work_date),
                   'claims', (SELECT list(claim_id) FROM claims WHERE entity_id = credential_id AND attribute = 'expires_on')) AS evidence,
       credential_id AS key
FROM late JOIN persons p ON p.person_id = holder_id
GROUP BY credential_id, holder_id, number
