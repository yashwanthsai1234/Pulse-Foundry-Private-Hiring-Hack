-- id: LIC-EXPIRED-NOT-WORKING
-- severity: MEDIUM
-- title: "Credential expired and nobody worked on it"
-- action: "Confirm the person left or renewed. Remove or update the credential record."
-- Sources: https://duckdb.org/docs/stable/sql/statements/set_variable.html
SELECT [c.holder_id] AS entity_ids, NULL AS facility_id, c.expires_on AS period_start, c.expires_on AS period_end,
       printf('%s %s expired on %s and no shift is scheduled after that date.', coalesce(c.holder_name, '(no name)'), c.credential_type, c.expires_on) AS message,
       json_object('claims', (SELECT list(claim_id) FROM claims WHERE entity_id = c.credential_id AND attribute = 'expires_on')) AS evidence,
       c.credential_id AS key
FROM credentials c
WHERE c.expires_on < getvariable('as_of')
  AND NOT EXISTS (SELECT 1 FROM shifts s WHERE s.person_id = c.holder_id AND s.work_date > c.expires_on)
