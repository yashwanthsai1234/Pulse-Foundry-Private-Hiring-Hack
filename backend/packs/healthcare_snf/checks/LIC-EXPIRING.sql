-- id: LIC-EXPIRING
-- severity: HIGH
-- title: "Credential expires soon"
-- action: "Verify the renewal with the issuer now and upload the new expiration date."
-- Sources: https://duckdb.org/docs/stable/sql/statements/set_variable.html
SELECT [c.holder_id] AS entity_ids, NULL AS facility_id, c.expires_on AS period_start, c.expires_on AS period_end,
       printf('%s %s expires on %s, in %d day(s).', coalesce(c.holder_name, '(no name)'), c.credential_type, c.expires_on, c.expires_on - getvariable('as_of')) AS message,
       json_object('claims', (SELECT list(claim_id) FROM claims WHERE entity_id = c.credential_id AND attribute = 'expires_on')) AS evidence,
       c.credential_id AS key,
       CASE WHEN c.expires_on - getvariable('as_of') <= getvariable('expiry_high_days') THEN 'HIGH' ELSE 'MEDIUM' END AS severity
FROM credentials c
WHERE c.expires_on - getvariable('as_of') BETWEEN 0 AND getvariable('expiry_medium_days')
