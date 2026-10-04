-- id: LIC-EXPIRY-MISSING
-- severity: HIGH
-- title: "Credential has no readable expiration date"
-- action: "HR: look up the expiration date with the state board and enter it. Until then the license is not tracked."
-- Sources: https://www.law.cornell.edu/cfr/text/42/483.35
SELECT [c.holder_id] AS entity_ids, NULL AS facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('%s %s %s has no readable expiration date: expiry checks cannot run for it.', coalesce(c.holder_name, '(no name)'), c.credential_type, c.number) AS message,
       json_object('records', (SELECT list(DISTINCT record_id) FROM claims WHERE entity_id = c.credential_id AND attribute = 'number'),
                   'field', 'credential.expires_on') AS evidence,
       c.credential_id AS key
FROM credentials c WHERE c.holder_type = 'person' AND c.expires_on IS NULL
