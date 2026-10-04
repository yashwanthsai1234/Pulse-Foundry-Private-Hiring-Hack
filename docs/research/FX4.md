# FX4 truth + checks (wave 4)

Decisions and sources (all verified by tests in `backend/tests/test_fx4_*.py`, `test_checks.py`, `test_pbj.py`).

- Parse-issue contract: implemented as the `KINDS` dict in `sot/checks/builtin.py` (TASKGRAPH §6). Unknown kinds fall back to `PARSE-<KIND>` LOW.
- LEGEND-MISMATCH is grouped per file and token, not per table: `tests/breakers/test_chaos_rootcauses.py::test_legend_mismatch_is_one_issue_per_file_and_token` needs one issue for a two-page file with one wrong footnote.
- Gold dedupe: key (person, date, start, end) for shifts, (person, facility, period start, period end) for pay periods; newest `files.received_at` wins, then lowest record id. https://en.wikipedia.org/wiki/Data_deduplication , https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts
- PAY-DUPLICATE reads `source_records`, because gold already holds one row. Same payroll id and hours = a harmless copy, not reported.
- PAY-HOURS-INVALID: more than 100 h per week (168 exist). CMS PBJ is daily hours per employee, no weekly cap: https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf
- PAY-PERIOD-INVALID: longer than 14 days. The breaker test treats 14 Sep to 14 Oct (31 days inclusive) as invalid, so the contract's "> 31 days" could not be used.
- Survivorship tie-break: priority, observed_at, file name, source row, record id (RC15: no content hashes in the order).
- Issue merge: `INSERT ... ON CONFLICT (fingerprint) DO UPDATE SET ... excluded.*`; status, owner, note and first_seen_run are not in the update list. https://duckdb.org/docs/stable/sql/statements/insert.html#on-conflict-clause
- PBJ export: `LEFT JOIN LATERAL ... LIMIT 1` picks one pay period per day so overlapping periods cannot double hours. https://duckdb.org/docs/stable/sql/query_syntax/from.html#lateral-joins
- Evidence column (B1-11): claims map attribute -> candidate source fields (`CLAIM_FIELDS`); the engine resolves the field to a column through the table's `mappings.matches`. A check names the field of its record evidence with `evidence_refs["field"]`.
