# Live Panel Tests

Five diverse cases, run against the **real** system: FastAPI server (`uvicorn sot.api.app:create_app --factory`), the built React UI, files uploaded through the UI's file input in headless Chrome (Playwright), agent tasks answered by **real Claude Code Sonnet subagents** via `/process-agent-tasks`. Per case: `<case>.json` (API snapshot: summary, issues, people, files, agent tasks, PBJ CSV, UI errors) and screenshots `<case>-*.png`.

Driver scripts: `scratchpad/pw/panel.mjs` (reset → upload → wait → screenshots → snapshot) and `shots.mjs`.

## Results

| Case | Input | Time | Records → people | Issues (C/H/M/I) | Agent tasks | UI errors |
|---|---|---|---|---|---|---|
| P1 README sample | the 4 README files as given (CSV ×3 + PDF) | 0.5 s | 8 → 2 | 2 / 0 / 0 / 1 | — | 0 |
| P2 Planted-defect example | PLAN §10 example (expired license, 48 h vs 40 h, "Marc") | 0.6 s | 8 → 2 | 3 / 1 / 1 / 1 | — | 0 |
| P3 Messy 40-staff world | 25 planted defects; HR latin-1 + `;` + renamed headers; payroll XLSX with reordered/renamed headers; licenses with title rows + US dates; gridless PDF | 1.7 s | 170 → 43 | 5 / 7 / 10 / 5 | — | 0 |
| P4 Real online files | e1 CSVs + Chrome borderless-zebra PDF + LibreOffice/pandoc PDF + real CalendarLabs template PDF + **fresh** WA DOH license list (data.wa.gov, 150 rows) + CMS PBJ public file + Chicago employee list | 11.7 s | 34 → 20 (before agents) | 21 / 5 / 21 / 2 | 4 → answered by real subagents | 0 |
| P5 Scan + agents | e1 CSVs + **scanned (image-only) schedule** + vendor paperwork + WA license list | 1.8 s | 9 → 2 before agents; **161 → 152 after** | after agents: 3 / 42 / … | 3 → **3 accepted** | 0 |

P1: the two CRITICALs are correct — the README sample has no RN at Riverdale at all, and Bayside's only RN is off three days (42 CFR 483.35(b)). P2 reproduces PLAN §10 exactly (LIC-WORKED-EXPIRED, 2 × COV-RN-DAILY, HRS-PAID-VS-SCHED, SRC-CONFLICT, ID-FUZZY-LINK).

## What the panel found (and what was fixed)

| ID | Case | Breakdown | Root cause | Fix (test) |
|---|---|---|---|---|
| P-01 | P3 | Long names on a gridless PDF ("Jessica Richardson") put the family name into the Role column → phantom schedule-only people, unknown roles, missed LIC-WORKED-EXPIRED | `pdf.words` fell back to header-midpoint column edges when corridors blurred; the midpoint (194) cut through the name although a 12 pt gap separated it from the role | Edge = middle of the widest whitespace gap across body rows (footnotes excluded) — `tests/test_pdf_long_names.py`. P3 after fix: persons 46 → 43, SCHED-NO-HR 4 → 1 (exactly the planted one), LIC-WORKED-EXPIRED found |
| P-02 | P4 | A real state license list (WA DOH) could not be mapped as a license even by the agent | License template demanded one full-name column; `credential.number` regex rejected state formats `RN.RN.00094584`; "Registered Nurse License" not in the roles vocab | `one_of` names on the license template, state-format regex, role aliases — `tests/test_license_list_real.py`. Live: the real subagent then mapped it as `license` (0.98), validator OK |
| P-03 | P5 | Agent-read scanned pages lost their facility → no COV-RN-DAILY CRITICALs | The agent returned "Harborview Riverdale - Weekly Staff Schedule - Week of 09/14"; silver matched the whole title against the vocab | `facility_in()` finds the longest facility alias inside a title — `tests/test_silver.py::test_facility_found_inside_a_longer_title`. Live re-run: the scanned path yields the same 3 CRITICALs as the text PDF |
| P-04 | P2 | Evidence note label overlapped its value ("DAYS_WITHOU3_RN") | fixed-width label column | wider wrapping label column, underscores shown as spaces (front end) |
| P-05 | P3 | Expected PARSE-DATE-AMBIGUOUS not raised | **Not a system bug**: a later planted row has "28/10/2024" (day > 12), which proves the column is day-first; the system inferred `%d/%m/%Y` correctly | Generator expectation issue (WONTFIX in the system) |

## Real agent path (B-015 / B3-11 closed)

P4 and P5 ran `/process-agent-tasks`: one Sonnet subagent per pending task, in parallel. Results:

- **Validators reject what does not fit.** The CalendarLabs template page was read faithfully by the agent ("Ana — Social Media statistical reporting — 3.00 …") and rejected (0 % shift tokens, 0 % known staff). CMS PBJ and Chicago payroll: the agents answered "no template fits" → rejected → stay TABLE-UNMAPPED for a human. No false mapping.
- **Validators accept what fits.** Scanned schedule pages → both `page_reader` answers accepted → shifts, coverage and license checks run on scanned data. WA license list → `license`, accepted, MAPPING-REVIEW for a human to approve the contract.
- **The pipeline never blocked**: CSVs were fully processed while the agent tasks were pending; results were applied by the backend poller without a restart.
