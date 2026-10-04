# Sample data

Ready-to-upload datasets in the judges' format (HR roster CSV, payroll CSV, licenses CSV, schedule PDF). Drop **all files of one folder** on the Ingest page (leave `answer_key/` out — it is the solution, not input).

| Folder | What it is | Files | Result (verified through the real pipeline) |
|---|---|---|---|
| `readme_given/` | The rows given in the challenge README. **Loaded automatically on first start** (empty database). | 4 | 8 records → 2 people; 2 CRITICAL (no RN at Riverdale all week; Bayside RN off 3 days), 1 INFO (Marc → Marcus) |
| `set1_weekly_light/` | 20 staff, 1 week, 6 planted problems, clean formats, ruled PDF | 4 | 80 records → 20 people; 1 CRITICAL, 2 HIGH, 1 MEDIUM, 1 INFO; planted problem types found 4/4 |
| `set2_two_weeks_messy/` | 40 staff, **2 weeks** (two schedule PDFs), 14 planted problems (typos, maiden name, payroll/schedule people not in HR, CNA on an RN shift, float staff, missing RN day, duplicate HR row, two people with one family name), gridless PDF | 5 | 252 records → 43 people; 3 CRITICAL, 4 HIGH, 4 MEDIUM, 5 INFO; found 10/10 |
| `set3_chaos_formats/` | 60 staff, **all 22 planted problem types**, mangled formats: HR is latin-1 with `;` and renamed headers, payroll is an **XLSX** with reordered/renamed headers, licenses have title rows and US dates, PDF with wrapped names | 4 | 250 records → 64 people; 6 CRITICAL, 8 HIGH, 13 MEDIUM, 6 INFO; found 16/17 (see note) |

`answer_key/` per set: `expected_issues.json` (planted problems with check ids and employee ids), `truth.json` (which source records belong to which person), `schedule*.json` (the PDF's content).

Note on set 3: the answer key expects PARSE-DATE-AMBIGUOUS for the hire-date column, but another planted row writes `14/10/2023` (day > 12), which proves the column is day-first — the system correctly infers `%d/%m/%Y` and does not flag ambiguity. The answer key is wrong there, not the system.

Regenerate (deterministic seeds): `cd backend && .venv/bin/python -m tools.synth.samples`.

Default data: on a first start the server ingests `readme_given/`. Use another folder with `SOT_SEED_DIR=/path/to/folder`, or disable with `SOT_SEED=0`. `make reset` empties the database (it stays empty until the next first start of a fresh runtime).
