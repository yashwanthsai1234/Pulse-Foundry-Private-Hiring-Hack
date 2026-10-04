# Breakdowns and Issues Log

Every problem found by builders, the integrator, or the breaker agents. Status: OPEN → FIXED (with test) / WONTFIX (with reason).

W3 breaker reports (full detail, repro, evidence, proposed fix): [B1 wiring](breakdowns/B1.md) · [B2 edge cases](breakdowns/B2.md) · [B3 real-world files](breakdowns/B3.md) · [B4 chaos root causes + simplicity](breakdowns/B4.md). Fix ownership: TASKGRAPH §6. Breaker tests: `backend/tests/breakers/` (119 failing at the start of W4).

| ID | Source | Area | Problem | Status |
|---|---|---|---|---|
| B-001 | A3 report | semantic/contracts | "Same template, different fingerprint → drift" also fires for a legitimate second source of the same template (e.g. two payroll exports with different headers). | FIXED (FX2: drift only when header Jaccard ≥ 0.5; test_second_source_of_a_template_is_not_drift) |
| B-002 | A3 report | normalize/dates | Weekday year search ±1 year can resolve to a far year (e.g. "Tue 09/14" → 2027 against a 2026 anchor) instead of flagging the mismatch. | FIXED (FX2: weekday year only within 183 days of an anchor; test_weekday_year_must_match_and_be_near) |
| B-003 | A3 report | semantic/classify | `classify(forced=...)` trusts the agent map (skips the relation swap and the S ≥ 0.5 filter); the agent validator must cover this. | FIXED (agent validators re-check forced maps; FX5 test_agents) |
| B-004 | A1 report | parsers/base | A table with only text data and no title row can choose a wrong header if its first row is narrower than the rest. | FIXED (FX1: header = first all-text unique row with typed row below; test_extra_text_column_does_not_move_header_to_a_data_row) |
| B-005 | A1 report | parsers/csv | Streaming CSV > 200 MB to Parquet (IMPLEMENTATION §8.2) not implemented. | WONTFIX (FX1: second chunked path for >200 MB not needed at this scale; Arrow bulk insert handles 20k rows < 1 s) |
| B-006 | A5 report | truth/claims | `Claim.observed_at` = build time (SourceRecord has no file timestamp) → "latest_observed" tie-break degenerates to claim id. Needs files.received_at. | FIXED (FX4/FX5: claims observed_at = files.received_at) |
| B-007 | A5 report | checks/builtin ↔ silver | Parse-issue names must match: silver emits bad_date/bad_number/unknown_vocab/vocab_fuzzy/bad_phone/date_ambiguous/shift_token/legend_mismatch; builtin maps date_invalid→PARSE-DATE, else PARSE-<KIND> LOW. Align severities. | FIXED (FX4: parse-issue contract TASKGRAPH §6; test_fx4_checks contract parametrization) |
| B-008 | A5 report | checks/COV-RN-DAILY | Schedule date span is inferred as Mon–Sun weeks around shifts (OFF cells are not shifts). Silver should expose the real schedule span. | WONTFIX (COV-RN-DAILY uses Mon–Sun weeks around the shifts; OFF cells carry no facts — documented in A5.md) |
| B-009 | A5 report | checks/ID-FUZZY-LINK | entity_ids are record ids (Link has no person id) → should be person ids for UI/person_name. | FIXED (FX4: one ID-FUZZY-LINK per record, person ids) |
| B-010 | A7 report | api contract | UI expects summary.agent_tasks per status, issue list evidence_count/person_name, X-Highlight fractions; EvidenceItem.raw added to models. | FIXED (FX5 shapes; B1 shape checker 0 mismatches) |
| B-011 | A2 report | parsers/pdf | All PDF evidence comes from one renderer (reportlab). Excel/Word/EHR-exported PDFs (coloured cells, rotated text, two-line day/date header, row split across pages) untested → W3 must test non-reportlab and real-world PDFs. | FIXED (B3 tested 10 foreign + 2 web PDFs; FX1 fixed zebra (B3-01) and pandoc (B3-02) cases) |
| B-012 | A2 report | pipeline | PdfTextParser only sets extraction.score/notes; the orchestrator must emit PARSE-PDF-LOW-CONFIDENCE (< 0.8) and create a page_reader task (< 0.5). | FIXED (FX5: PARSE-PDF-LOW-CONFIDENCE < 0.8, page_reader < 0.5 or zero-table schedule page) |
| B-013 | A2 report | parsers/pdf/scan | Scan parser builds a minimal AgentTask (prompt_version v0, empty schema) — the gateway must fill in real instructions/schema (ExtractContext has no make_task). | FIXED (FX5: gateway rebuilds bare tasks; test_submit_completes_a_bare_task) |
| B-014 | A6 report | agents | A task that times out (claude -p) stays pending forever — no expiry. | FIXED (FX5: task expiry → AGENT-UNAVAILABLE; test_unanswered_task_expires_into_agent_unavailable) |
| B-015 | A6 report | agents/executors | ClaudeCliExecutor not exercised against a live CLI (only flag test). | OPEN → W5 live test with the real claude CLI |
| B-016 | A6 report | api | PUT /api/settings runs full rebuild (5-7) instead of checks-only; /api/agent-tasks lacks instructions/prompt_version; pbj.csv ignores quarter. | WONTFIX (checks-only rerun would drop resolve/truth drafts; a stage 5–7 rebuild takes < 1 s at this scale) |
| B-017 | A6 report | pipeline ↔ checks | Pipeline drafts (FILE-QUARANTINED, TABLE-UNMAPPED, AGENT-REJECTED, AGENT-UNAVAILABLE, MAPPING-REVIEW, ID-AGENT-LINK) must pass through run_checks extra_drafts with severities. Verify at integration. | FIXED (FX5: pipeline drafts carry severities) |
| B-018 | A6 report | pipeline | ValidationContext real profile/classify calls, page_reader + mapping validators, contract approve, CSV exports untested against real stages. | FIXED (B1 exercised validators, contract approve, CSV exports against real stages) |
| B-019 | W2 integration | checks/builtin | One nickname match produced 3 ID-FUZZY-LINK issues (schedule record ↔ HR, payroll, license) labelled with record ids. Should be one issue per fuzzy record, entity = person id, message with display names + source. | FIXED (FX4) |
| B-020 | W2 integration | pipeline events | "resolve: … 10 fuzzy links" counts all score links, not fuzzy ones; table.mapped events for PDF pages lack the page number. | FIXED (FX5) |

## W4 resolution summary (breaker reports B1–B4)

Breaker tests at the start of W4: **119 failing**. After the fix fleet (FX1–FX7) and the integrator's fixes: **0 failing of 221** (see `backend/tests/breakers/`). Per-finding resolution (id → proving test) is in each fix agent's notes: `docs/research/FX1.md` … `FX7.md`.

| Report | Findings | Fixed | WONTFIX / deferred |
|---|---|---|---|
| B1 wiring | 20 | 18 | B1-20 second half (rejected-task retry; no test) · B-016 (above) |
| B2 edge cases | 21 | 21 | — (B2-21 phone part fixed by integrator: NANP rule) |
| B3 real-world files | 11 | 10 | B3-11 (scan accuracy needs a real page_reader run → W5) |
| B4 chaos root causes | RC1–RC18, S1–S10 | RC1–RC11, RC13–RC18; RC12 decided (TASKGRAPH §6); S2–S10 | S1 (decode JSON once in DB.query) → W5 simplify pass |

Integrator fixes after the fleet: shared lenient number parser for mapping + silver (`sot/normalize/numbers.py`; "40 hrs", "-8", "1,036" map to the hours column so PAY-HOURS-INVALID can flag them), NANP phone rule, facility in the shift de-dup key (cross-facility double booking kept), full replay on the per-run SSE stream.

## W5 correctness review (R1) — details in [docs/review/R1.md](review/R1.md), tests in `backend/tests/review/`

| ID | Severity | Area | Problem | Status |
|---|---|---|---|---|
| R1-01 | HIGH | checks/engine + SQL checks | A NULL message (blank name, "N/A" hours, HR row without id) fails draft validation → whole check becomes one CHECK-ERROR and all its real issues are lost; HR-DUP-ROW groups id-less rows. | FIXED (FX8: per-row drafts, coalesced messages) |
| R1-02 | HIGH | silver/dates/pipeline anchors | Hire/expiry dates act as year anchors → "Mon 09/14" resolves to 2020; weekday-less headers take the median year. | FIXED (integrator: pay-period anchors only, latest-anchor reference) |
| R1-03 | MEDIUM | HRS-PAID-VS-SCHED | Scheduled hours summed across facilities vs per-facility payroll → false HIGH for float staff. | FIXED (FX8: per-facility comparison) |
| R1-04 | MEDIUM | exports/pbj | Overnight shift hours not split at midnight (PBJ is calendar-day based). | FIXED (FX8: PBJ splits at midnight) |
| R1-05 | MEDIUM | checks/engine fingerprints | Period (min/max shift dates) in fingerprint → acknowledged issues reopen when next week's schedule arrives. | FIXED (FX8: person-level checks have no period in the fingerprint) |
| R1-06 | MEDIUM | pipeline | One failing file aborts the batch and the half-processed file is skipped on retry. | FIXED (integrator: per-file isolation, failed files retryable, FILE-FAILED issue) |
| R1-07 | MEDIUM | silver dates | A stray US-style date in an ISO column is read month-first without an ambiguity flag. | FIXED (integrator: off-format ambiguous value flagged) |
| R1-08 | LOW | survivorship / agent links | SRC-CONFLICT entity_ids lack the person id (UI shows no name). | FIXED (FX8: holder person id in SRC-CONFLICT) |

## W5 A/B + live panel findings — details in [docs/ab/AB_TESTS.md](ab/AB_TESTS.md) and [docs/panel/PANEL.md](panel/PANEL.md)

| ID | Source | Problem | Status |
|---|---|---|---|
| AB-1 | A/B exp. 1 | Spec PDF cascade order silently extracts wrong cells on foreign PDFs (87.6 % vs 100 %). | Current order kept (decision confirmed) |
| AB-2 | A/B exp. 5 | Chaos world v013 crashed (`KeyError: 'file_id'`) in the page_reader accept path. | FIXED/NOT REPRODUCIBLE — happened while R2 was rewriting DB access; re-run of seed 7 (14 worlds): 0 errors; direct accept-path repro passes |
| AB-3 | A/B exp. 4 | Schedule weekday columns placed in 2020 (hire dates as year anchors). | FIXED (R1-02) |
| AB-4 | A/B exp. 4 | LEGEND-MISMATCH found on 10 of 18 expected tables. | OPEN-LOW — expectation counts per table vs the check's per file+token dedup (FX4); not a missed defect class |
| P-01 | Panel P3 | Long names on gridless PDFs split into the Role column. | FIXED (widest-gap column edges; tests/test_pdf_long_names.py) |
| P-02 | Panel P4 | Real state license list not mappable as a license. | FIXED (license one_of names, state-format numbers, role aliases; tests/test_license_list_real.py; live: agent mapped it, validator OK) |
| P-03 | Panel P5 | Agent-read scanned pages lost their facility. | FIXED (facility_in; live re-run: same 3 CRITICALs as the text PDF) |
| P-04 | Panel P2 | Evidence label overlapped its value in the UI. | FIXED (front end) |
| P-05 | Panel P3 | Expected PARSE-DATE-AMBIGUOUS not raised. | WONTFIX — generator expectation wrong (a planted row proves the day-first format) |
| B-015 | W1 | ClaudeCliExecutor / real agent path not exercised live. | FIXED for the default executor: real Sonnet subagents answered 7 live tasks (P4 + P5); `claude -p` executor remains flag-tested only |
