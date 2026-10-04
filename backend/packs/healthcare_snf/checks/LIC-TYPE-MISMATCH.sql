-- id: LIC-TYPE-MISMATCH
-- severity: MEDIUM
-- title: "License type contradicts the license number prefix"
-- action: "HR: check the license with the state board. One of the type and the number is wrong."
-- Sources: https://www.law.cornell.edu/cfr/text/42/483.35
-- A number such as CNA-771045 typed as RN would silently authorise the holder for RN shifts.
SELECT [c.holder_id] AS entity_ids, NULL AS facility_id, NULL::DATE AS period_start, NULL::DATE AS period_end,
       printf('License %s is typed %s but its number prefix says %s.', c.number, c.credential_type,
              regexp_extract(c.number, '^([A-Z]+)-?[0-9]', 1)) AS message,
       json_object('claims', (SELECT list(claim_id) FROM claims WHERE entity_id = c.credential_id
                              AND attribute IN ('number', 'credential_type'))) AS evidence,
       c.credential_id AS key
FROM credentials c
WHERE c.holder_type = 'person' AND c.credential_type IS NOT NULL
  AND regexp_extract(c.number, '^([A-Z]+)-?[0-9]', 1) IN (SELECT license_type FROM role_scope)
  AND regexp_extract(c.number, '^([A-Z]+)-?[0-9]', 1) <> c.credential_type
