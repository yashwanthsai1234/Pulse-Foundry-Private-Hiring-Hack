# Harborview Source of Truth — Plan

> Style: ASD-STE100 (Simplified Technical English). Short sentences. Active voice. One idea per sentence. Technical names stay as they are.
>
> Companion document: [`IMPLEMENTATION.md`](IMPLEMENTATION.md) (module specifications, interfaces, work packages, timeline).

## Contents

1. Problem analysis
2. Five obvious solutions (and why they fail)
3. Overlooked users, painful moments, assumptions
4. Three directions
5. Comparison
6. Recommendation and the weakest assumption
7. Part A — the spine: Adaptive Ingestion Engine
8. Part B — the payoff: Shift-Level Evidence Graph
9. Front end
10. End-to-end example

---

## 1. Problem analysis

Harborview Care Group has two skilled nursing facilities: Bayside and Riverdale. Its data is in four systems: HR, payroll, licensing and scheduling. The systems do not agree.

At judging, we get four unseen files. The files have the README structure. They have more records and more errors.

| File | Format | Key columns | Join key to a person |
|---|---|---|---|
| HR roster | CSV | employee_id, name, job_title, facility, license_number, license_expiration | `employee_id`, `license_number` |
| Payroll | CSV | payroll_id, `LAST, FIRST`, job_code, facility_code, period, hours_paid | **none** — name + role + facility only |
| Licenses | CSV | license_number, `LAST, FIRST`, type, expiration, last_verified | `license_number` |
| Schedule | PDF | name (`Marc Bell`), role, 7 day columns, page title = facility, footnote = shift legend | **none** — display name + role + page only |

Three facts set the design:

1. **Identity is the core problem.** Only HR and Licenses share a hard key. Payroll and the schedule need fuzzy identity resolution. Names change form (`REYES, SOFIA`, `Marc` vs `Marcus`). Facilities change form (`Harborview Bayside`, `BYS`, page title). Roles change form (`Registered Nurse`, `RN`).
2. **Truth is field-level, not file-level.** The license service owns expiration dates. Payroll owns paid hours. The schedule owns the daily split of hours. HR owns identity and contact data.
3. **Truth is temporal.** A license is valid or not valid **on the date of a shift**. "Expired today" is a different question.

This is not a CRM problem. It is master data management (MDM) with entity resolution, provenance and rule-based checks.

The three business problems:

| Problem | Data in the files? | What the SoT can do |
|---|---|---|
| Licenses, certifications and vendor paperwork expire too late | Yes (licenses, HR); vendor: no | Golden expiration per credential, checked per shift date; generic credential model for vendors |
| Quarterly state staffing report (CMS PBJ) takes weeks | Yes (payroll, schedule) | Daily hours per person and job code, reconciled to payroll |
| Hospital referrals are slow | **No** | The staffing half: licensed staff on shift per facility and role. A referral feed is one more source. |

## 2. Five obvious solutions (and why they fail)

1. **A pandas script per file + a Streamlit dashboard.** The script hardcodes the column names and merges on the name. It fails at live ingest when a header or a name format changes.
2. **"Chat with your data" (LLM or RAG over the files).** This is not a source of truth. The model can invent hours and dates. Nobody can defend a number.
3. **LLM as the ETL.** The team sends each file to an LLM and merges the JSON output. The output changes from run to run. It is slow at scale. It can invent values silently.
4. **A SQLite or Postgres star schema + an "expiring licenses" chart.** It is clean, but it checks each file alone. It does not reconcile across sources.
5. **An enterprise-stack diagram.** Airflow, dbt, Great Expectations and Docker give many boxes. The reconciliation logic is thin.

## 3. Overlooked users, painful moments, assumptions

**Users**
- The Director of Nursing (DON). The DON is accountable for licenses.
- The scheduler. The scheduler puts people on shifts.
- The PBJ coordinator. This person sends the quarterly staffing data.
- The payroll clerk.
- The admissions coordinator. This person answers referrals.
- The person who resolves the flags.
- **The Pulse Foundry engineer who onboards the next client.** This is the "reuse" user.

**Painful moments**
- A state surveyor arrives with no notice. The surveyor asks for license proof for each person on the 9/16 night shift.
- The PBJ deadline arrives. PBJ needs daily hours, but payroll is weekly. Only the schedule gives the daily split.
- The facility finds a lapsed license after the shifts were worked and billed.
- A referral arrives on Friday at 4 p.m. Admissions needs a staffing answer in hours.
- At the live demo, a renamed column stops the pipeline.

**Assumptions to challenge**
- "Single source of truth" does not mean one correct file. Each attribute has its own authoritative source.
- "Expired" must use the shift date, not today.
- Names are not keys. Nicknames, maiden names, `LAST, FIRST` order and typos occur.
- Scheduled ≠ paid is not always an error. Unpaid meal breaks, call-offs and swaps occur. Use a tolerance and a severity.
- A flag is not only a message. It needs evidence, an owner and a durable status.
- Ingest repeats each week. It must be idempotent and must detect schema drift.
- Referral and vendor data are not in the files. We say this. We model a generic credential with a person **or** an organization as the holder.

## 4. Three directions

### Direction A — Adaptive Ingestion Engine ("drop any file, get a reconciled model")
- **User and situation:** a Pulse Foundry engineer gets a zip of unknown exports. The engineer must give a trusted model by Monday.
- **Workaround and failure:** a custom pandas script per file. The next export renames a column, and the script fails silently.
- **Surprising capability:** a parser auction selects the parser from the bytes. A semantic mapper finds the meaning of each column from header synonyms and value signatures. The Hungarian algorithm finds the best column-to-field assignment. The system saves a versioned mapping contract and shows schema drift. A YAML domain pack holds all domain knowledge.
- **90-second demo:** ingest the four files. Then ingest a mangled set (renamed and reordered headers, `;` delimiter, XLSX, a PDF with no grid). The golden output does not change. Show the chaos report.

### Direction B — Shift-Level Evidence Graph ("every hour worked, proven")
- **User and situation:** the DON during a state survey.
- **Workaround and failure:** the paper schedule, license-board lookups and the HR binder. HR expiration dates are out of date.
- **Surprising capability:** each shift links to the resolved person, to the license validity on that date and to the role scope. Each flag has an evidence chain back to the source cell. The system makes a PBJ-ready file and checks the federal RN 8-hours-per-day rule.
- **90-second demo:** live ingest gives 3 critical issues. Answer the surveyor question with evidence. Export the PBJ file.

### Direction C — Claims Ledger with Learned Resolutions ("truth that gets cleaner each week")
- **User and situation:** an office manager fixes the same 20 discrepancies in Excel each week.
- **Workaround and failure:** spreadsheet comments. Decisions are lost. The same issues come back.
- **Surprising capability:** each source value is a claim with provenance. Survivorship rules select the golden value. A human decision becomes a durable rule. Time travel shows "what did we believe on 9/20?".
- **90-second demo:** week 1 gives 14 flags. Resolve 4. Week 2 shows only new issues.

## 5. Comparison

| | User value | Originality | Feasibility | Fit to judging |
|---|---|---|---|---|
| A | High for Pulse Foundry; indirect for Harborview | High | High | Strongest: live unseen ingest, auto parsing, robustness, reuse |
| B | Highest for Harborview; answers 2 of 3 problems directly | High | Medium-high | Strong on "how it solves the problems"; fragile if parsing fails live |
| C | High in the long term; low in a 90-second demo | Medium-high | High | Moderate; governance is not visible in one ingest |

Trade-offs:
- A alone can look like infrastructure with no outcome.
- B alone can become hardcoded domain logic that fails on messy live files.
- C gives its value over many weeks, not in one demo.

## 6. Recommendation and the weakest assumption

**Recommendation: A as the spine, B as the payoff, C's claim model as the storage.** Claims with provenance cost little. They make B's evidence chains possible.

**Locked decisions**
- Front end: a small web app that accepts the files and shows the results.
- AI: the deterministic pipeline does most of the work. Low-confidence tasks go to a queue. During the one-time live ingest, Claude Code processes the queue with parallel Sonnet subagents. `claude -p` is an optional executor for unattended runs.

**Weakest assumption:** "The unseen schedule PDF gives a clean table automatically." If the PDF is a scan, or has wrapped or merged cells, the shift-hours reconciliation fails. Then PBJ and the licensed-on-shift checks fail.

**Test before the build (30 minutes):**
1. Generate 6 PDFs with known content: ruled grid, no grid, wrapped names, landscape, two tables on one page, rasterized at 150 dpi.
2. Run the extraction cascade methods [1]–[4] on each PDF. Measure the cell accuracy.
3. Run the PageReader agent on the rasterized PDF. Measure the cell accuracy.
4. Set the cascade order and the 0.8 threshold from the results.

Second test: a name set (nickname, maiden name on a license, `LAST, FIRST`, typo, two people with one family name). The resolver must make no false merges.

---

## 7. Part A — the spine: Adaptive Ingestion Engine

### A.1 Purpose

The engine reads any file. It finds the format by itself. It finds the meaning of each column by itself. It puts all values into one model. It records the origin of each value. You do not tell the engine which parser to use.

### A.2 Architecture

```
 ┌──────────────────────────── WEB APP (React) ────────────────────────────┐
 │  Upload area  │  Live pipeline view (SSE)  │  Issues  │  People  │ Export │
 └───────┬─────────────────────────▲──────────────────────────────▲─────────┘
         │ POST /ingest            │ events                       │ GET /api/*
 ┌───────▼─────────────────────────┴──────────────────────────────┴─────────┐
 │                         FASTAPI  +  INGEST ORCHESTRATOR                   │
 │                                                                           │
 │  ① SNIFF ──► ② EXTRACT ──► ③ PROFILE+MAP ──► ④ NORMALIZE ──► ⑤ RESOLVE    │
 │  (parser     (tables +     (column→field,    (names, dates,   (who is    │
 │   auction)    locators)     file type)        roles, sites)    who)      │
 │                                                     │                     │
 │                         ⑥ CLAIMS + SURVIVORSHIP ◄───┘                     │
 │                                  │                                        │
 │                         ⑦ CHECKS (Part B) ──► ⑧ PUBLISH (gold + exports)  │
 │                                                                           │
 │   Low confidence at ②③⑤?  ──►  AGENT GATEWAY  (task queue → Claude Code   │
 │                                 Sonnet subagents; claude -p optional)     │
 │                                 cache by hash · JSON schema · validators  │
 └───────────────────────────────────┬───────────────────────────────────────┘
                                     │
 ┌───────────────────────────────────▼───────────────────────────────────────┐
 │ DuckDB:  landing │ bronze (raw rows) │ silver (typed) │ gold (golden)     │
 │          claims  │ links │ issues │ contracts │ agent_cache │ events       │
 └───────────────────────────────────────────────────────────────────────────┘
                     ▲
                     │ loads rules from
            packs/healthcare_snf/  (domain pack — YAML + SQL; replaceable)
```

### A.3 Stage ① Sniff — the parser auction

The system reads the first 64 KB of each file. It does not trust the file extension. Each parser examines the bytes and gives a score from 0 to 1. The parser with the highest score reads the file. If no score is more than 0.5, the file goes to quarantine.

```
             file bytes
                 │
    ┌────────────┼────────────┬────────────┬────────────┬────────────┐
    ▼            ▼            ▼            ▼            ▼            ▼
 CsvParser   XlsxParser   JsonParser  PdfTextParser PdfScanParser  ...plugin
 0.97        0.00         0.00        0.00         0.00
    │
    └──► WINNER (score, reason) ──► event: "hr_roster.csv → CSV (0.97):
                                    ',' gives 9 fields in 100% of rows"
```

Signals for each parser:
- Magic bytes: `%PDF-` = PDF. `PK\x03\x04` + `[Content_Types].xml` = XLSX/DOCX. `D0CF11E0` = XLS. `{` or `[` = JSON.
- Encoding: the system examines the BOM first. Then it uses charset-normalizer.
- Delimiter: the system tries `,` `;` `\t` `|`. It counts the fields in each line and respects quotes. The best delimiter gives the same field count in the most lines.
- PDF: the system counts text characters on each page. Many characters = text layer → PdfTextParser. Few characters = scanned image → PdfScanParser (agent).

A new format needs only a new parser class with two functions, `sniff()` and `extract()`. The engine does not change.

### A.4 Stage ② Extract — tables with locators

Each parser gives the same output: `RawTable` objects. Each cell keeps a **locator**: file hash, page, row, column and (for a PDF) a bounding box. Later, each flag points back to the exact cell.

**PDF extraction cascade.** The system tries each method in order. It stops at the first method with a good score.

```
 page ─► [1] pdfplumber "lines" (ruled grid)
           │ score < 0.8
           ▼
         [2] pdfplumber "text" (aligned columns)
           │ score < 0.8
           ▼
         [3] PyMuPDF find_tables()
           │ score < 0.8
           ▼
         [4] word clustering: put words in rows by y, put words in columns by x gaps
           │ score < 0.8
           ▼
         [5] AGENT task "PageReader": a Sonnet subagent reads the page image → rows as JSON (schema-checked)

 score = header match × % cells that are valid shift tokens (legend ∪ {OFF}) × 7 day columns
```

The page title gives the facility ("Harborview Bayside"). The footnote gives the shift legend. The system reads the legend as data: "7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours." The system also calculates each duration from the times. `11p-7a` crosses midnight: 23:00 → 07:00 = 8 h. If the legend and the calculation do not agree, the system makes a flag.

### A.5 Stage ③ Profile + Map — find the meaning of each column

The system makes a profile for each column:
- Header tokens ("license_expiration" → {license, expiration}).
- Value signatures: % of values that match each field validator. Examples: `^[A-Z]{2,4}-\d+$` = license number. `LAST, FIRST` = person name. Date. Phone. Role vocabulary. Facility vocabulary. Number from 0 to 100.
- Type, null %, distinct count.

The domain pack defines the canonical fields. Each field has synonyms and a validator. The system calculates a score for each pair (column, field):

```
 score = 0.45 × header similarity (synonyms, Jaro-Winkler)
       + 0.45 × value match (% of values that pass the field validator)
       + 0.10 × type match
```

Then the system uses the **Hungarian algorithm** (`scipy.optimize.linear_sum_assignment`). The algorithm finds the best one-to-one assignment for the full table. A greedy match per column can assign two columns to one field. The Hungarian algorithm prevents this error. A "no field" option catches unknown columns.

```
                 person.name  role  facility  period.start  period.end  hours  ext_id
 employee_name      0.93      0.05    0.02       0.00          0.00      0.00   0.10
 job_code           0.04      0.95    0.20       0.00          0.00      0.00   0.05
 facility_code      0.02      0.15    0.94       0.00          0.00      0.00   0.05
 period_start       0.00      0.00    0.00       0.91          0.62      0.00   0.00
 period_end         0.00      0.00    0.00       0.60          0.92      0.00   0.00
 hours_paid         0.00      0.00    0.00       0.00          0.00      0.96   0.00
 payroll_id         0.05      0.00    0.00       0.00          0.00      0.00   0.88
                                     ▲ optimal assignment = diagonal
```

**File type.** The system compares the mapped fields with each entity template in the pack (HR roster, Payroll, License, Schedule). The best coverage of required fields gives the type. If the confidence is less than 0.80, the agent gateway gets the column profiles. The agent proposes a mapping. A validator then tests the proposal against the real values. The system accepts the proposal only if the validator agrees.

**Mapping contract.** The system saves each accepted mapping as a versioned YAML contract. The key is the header fingerprint. The next file with the same shape uses the contract directly. If the shape changes, the system shows "schema drift" and maps the file again.

### A.6 Stage ④ Normalize

| Data | Input examples | Output |
|---|---|---|
| Name | `REYES, SOFIA` · `Sofia Reyes` · `Marc Bell` · `José` | `{given: sofia, family: reyes}`, accents removed, case folded, nickname key |
| Facility | `Harborview Bayside` · `BYS` · `Bayside` (page title) | `FAC-BAY` (alias table in pack) |
| Role | `Registered Nurse` · `RN` · `R.N.` | `RN` |
| Date | `2026-09-14` · `09/14/2026` · `Mon 09/14` | ISO date. The system finds the date format for the full column. If no value has a day > 12, the system shows "ambiguous". For `Mon 09/14` the year must make 09/14 a Monday. The system selects the matching year nearest to the other dates (→ 2026). |
| Phone | `(347) 555 0202` | `+13475550202` |
| Shift | `7a-7p` | start 07:00, end 19:00, 12.0 h |

Each change keeps the raw value and the normalized value.

### A.7 Stage ⑤ Resolve — who is who

Payroll and the schedule do not have an employee ID. Thus, entity resolution is the core of this problem.

```
  BLOCKING (prevents n² comparison)            SCORING (Fellegi-Sunter weights)
  ┌───────────────────────────────┐            family name exact     +6.0
  │ key 1: license_number (exact) │            given: exact / nickname / JW≥0.9  +3.5
  │ key 2: soundex(family)+site   │            role agrees           +1.5
  │ key 3: family + given initial │            facility agrees       +1.5
  └───────────────────────────────┘            role disagrees        −2.0
                │                                       │
                ▼                                       ▼
       candidate pairs  ─────────────────────►  match probability
                                                        │
              ≥ 0.95 auto-link │ 0.75–0.95 agent + human review │ < 0.75 no link
                                                        │
                                                        ▼
                         UNION-FIND clusters with CANNOT-LINK rules:
                         · two different employee_ids never merge
                         · two different license numbers of one type never merge
```

Each link keeps its reasons ("family exact; Marc≈Marcus nickname; CNA=CNA; RVD=RVD"). The UI shows these reasons.

### A.8 Stage ⑥ Claims + survivorship

The system does not overwrite values. Each source value is a **claim**:
`(entity, attribute, value, source, locator, observed_at)`.

A survivorship rule in the pack selects the golden value for each attribute:

| Attribute | Source priority | Reason |
|---|---|---|
| license expiration | license service › HR | The service verifies with the state board. |
| hours paid | payroll | Payroll is the legal record of payment. |
| daily hours worked | schedule (distribution) + payroll (total) | PBJ needs daily values. Payroll is weekly. |
| phone, hire date, home facility | HR | HR is the system of record for identity. |

If the claims do not agree, the system keeps the golden value **and** makes a conflict issue.

### A.9 Agent gateway (task queue → Claude Code Sonnet subagents)

The pipeline does not call a model directly. It writes an **agent task** to a queue. An **executor** completes the task. One task contract supports three executors.

```
 pipeline stage ──► AgentTask {id, kind, payload, output JSON schema, validator spec}
                         │
                 cache hit? (sha256 of kind+payload+prompt version) ──yes──► result
                         │ no
                         ▼
          runtime/agent_tasks/pending/<id>.json        UI: "waiting for agent"
                         │
     ┌───────────────────┼───────────────────────────────┬──────────────────────┐
     ▼ DEFAULT (one-time, live)                          ▼ OPTIONAL (recurring) ▼ OFF
  Claude Code session runs /process-agent-tasks      backend runs           task → "needs human"
  → one Sonnet subagent (Agent tool, model=sonnet)   claude -p --model sonnet
    for each pending task, all in parallel             --output-format json
  → each subagent reads its task file, writes          --json-schema '<schema>'
    runtime/agent_tasks/done/<id>.json                 --tools "Read" | ""
                                                       --no-session-persistence
                                                       --max-budget-usd 0.50
     │                                                   │  (pool of 4, timeout 90 s)
     └───────────────────┬───────────────────────────────┘
                         ▼
     backend watches done/ → JSON schema check → deterministic validator
       (values pass field checks? row counts? names in roster?)
                         │ pass → accept + cache + re-run the downstream stages for this file only
                         │        event: "agent proposed, validator OK"
                         │ fail → issue "needs human" (the agent output is kept as a suggestion)
```

Why the Claude Code subagents are the default: the judging ingest is a one-time event. The session already has Claude Code login, so the app needs no subprocess pool and no API key. Each subagent gets its own clean context, and the parallel fan-out is built in. The `claude -p` executor stays for a scheduled weekly ingest with no person present. `--bare` is not used because it requires `ANTHROPIC_API_KEY`.

The repository includes a project slash command, `.claude/commands/process-agent-tasks.md`. The command tells Claude Code to:
1. List `runtime/agent_tasks/pending/`.
2. Start one Sonnet subagent per task in one message (parallel).
3. Tell each subagent to write only its `done/<id>.json` file and to obey the task's JSON schema.
4. Report the count of completed and failed tasks.

Agent tasks:
1. **SchemaMapper**: column profiles (headers + max. 20 sample values) → field mapping.
2. **PageReader**: a scanned PDF page → schedule rows.
3. **IdentityAdjudicator**: gray-zone pairs (0.75–0.95) → same/different + reason. The agent never merges records by itself. It only adds evidence.
4. **NewSourceModeler**: a file that matches no entity → proposes a mapping to a generic entity (e.g. `Credential` with an organization holder).

**Caution:** Agents get column profiles, not full files (except the PageReader). The pipeline never blocks on an agent. Until a result arrives, the file is in the state "partially mapped". The golden tables and checks use all the data that is ready. If no executor is available, each agent task becomes a "needs human" issue. For a repeatable demo, the cache holds the agent results.

### A.10 Domain pack (the reuse mechanism)

```
packs/healthcare_snf/
  entities.yaml        Person, Facility, Credential, Shift, PayPeriod (+ templates per file type)
  fields.yaml          canonical fields: synonyms, validators, normalizers
  vocab/roles.yaml     RN: [Registered Nurse, R.N., RN]   CNA: [...]   LPN: [...]
  vocab/facilities.yaml FAC-BAY: [Harborview Bayside, Bayside, BYS]
  vocab/nicknames.csv  marc→marcus, bob→robert, ...
  survivorship.yaml    attribute → source priority
  checks/*.sql         one SQL rule per file: id, severity, message, evidence query
  exports/pbj.sql      PBJ daily hours export
```

For a new industry, you write a new pack. The engine code does not change. Example: a trucking pack has Driver, CDL credential, Dispatch log and Fuel card.

### A.11 Scale

- DuckDB is a vectorized engine on one machine. It reads CSV and Parquet in parallel. It holds millions of rows without a cloud system.
- The system reads PDF pages in parallel (ProcessPool).
- Blocking keeps entity resolution near linear (n × block size, not n²).
- The number of agent calls depends on the number of distinct schemas and gray-zone pairs, not on the number of rows.
- Ingest is idempotent. The system skips a file with a known content hash. Re-ingest makes no duplicates.
- Each issue has a stable fingerprint: `hash(check_id, entity ids, period)`. A re-run does not duplicate issues. Human status (acknowledged / resolved / false positive) stays.

---

## 8. Part B — the payoff: Shift-Level Evidence Graph

### B.1 Purpose

Part B uses the golden model. It answers one question for each hour of work: "Who did the work, where, in which role, and was the license valid on that date?" Each answer has an evidence chain back to the source cells.

### B.2 Gold data model

```
   FACILITY ─1───*─ SHIFT ─*───1─ PERSON ─1───*─ CREDENTIAL ─*───1─ (holder: PERSON | ORGANIZATION)
                     │               │
                     │               └─1───*─ PAY_PERIOD (hours_paid)
                     │
   SOURCE_RECORD ─*──┴── LINK (match prob, reasons) ──1─ PERSON
   CLAIM  (entity, attribute, value, source_record, locator, observed_at)
   ISSUE  (fingerprint, check_id, severity, message, entity_ids, evidence[claim ids], status, owner)
```

### B.3 Check catalogue (domain pack SQL)

| ID | Severity | Rule |
|---|---|---|
| LIC-WORKED-EXPIRED | CRITICAL | The person worked a shift after the golden license expiration date. |
| LIC-SCOPE | CRITICAL | The scheduled role needs a license type that the person does not hold (e.g. a CNA on an RN shift). |
| COV-RN-DAILY | CRITICAL | A facility has no RN on duty for 8 consecutive hours on a day (42 CFR 483.35(b)). |
| ID-DUP-LICENSE | CRITICAL | Two different people have one license number. |
| HRS-PAID-VS-SCHED | HIGH | Paid hours ≠ scheduled hours for one week. Tolerance: max(2 h, 5%). |
| PAY-NO-HR | HIGH | A payroll person has no HR record (possible ghost employee). |
| LIC-EXPIRING | HIGH/MED | The license expires in ≤ 30 / ≤ 60 days and the person is on the schedule. |
| SHIFT-OVERLAP | HIGH | Two shifts for one person overlap (including across facilities). |
| SRC-CONFLICT | MEDIUM | Sources do not agree on an attribute (e.g. expiration HR vs service). |
| FAC-MISMATCH | MEDIUM | A person works at a facility that is not their home facility (float). |
| LEGEND-MISMATCH | MEDIUM | The legend hours ≠ the calculated shift duration. |
| SCHED-NO-HR | MEDIUM | A person on the schedule cannot be resolved. |
| ID-FUZZY-LINK | INFO | A link came from a fuzzy or nickname match. You can examine the reasons. |
| PARSE-* | varies | Bad date, ambiguous date format, unknown shift token, quarantined file. |

The "as-of" date for expiry checks is a setting. The default is today. For shift checks, the reference date is always **the date of the shift**.

### B.4 Evidence chain (what the UI shows for one issue)

```
 CRITICAL  Marcus Bell worked 4 shifts after license CNA-771045 expired
 ├─ shift   schedule.pdf · page 2 · row 1 · Wed 09/16 "3p-11p"   [image crop of the cell]
 ├─ identity "Marc Bell" → PERSON P-0002 (p=0.99: family exact, Marc≈Marcus nickname, CNA=CNA, RVD=RVD)
 ├─ license  licenses.csv · row 3 · expiration_date = 2026-09-15 · last_verified 2026-09-01   ◄ golden
 ├─ conflict hr_roster.csv · row 3 · license_expiration = 2026-12-31                          ◄ not golden
 └─ action   DON: verify renewal with the state board today. If not renewed, remove from schedule.
```

The PDF crop comes from the cell bounding box (PyMuPDF renders the region as a PNG). The judges see the printed cell.

### B.5 PBJ export

The PBJ report needs daily hours for each employee and job code. Payroll gives weekly totals. The schedule gives the daily split. The system makes one row per person per day.
- If the schedule total = the payroll total → status `ready`.
- If they do not agree → status `needs sign-off`. The system does not invent a split.

Job codes come from the pack (e.g. RN = 7, CNA = 10; **verify against the CMS PBJ specification during the build**).

### B.6 How the SoT helps with the three problems (grounded in what we build)

1. **Licenses expire too late** → `CREDENTIAL` is generic (person or organization holder). The expiry horizon view (30/60/90 days) and LIC-WORKED-EXPIRED use golden expiration dates from the verification service. Vendor paperwork uses the same engine (demo: vendor file via NewSourceModeler).
2. **The quarterly staffing report takes weeks** → the PBJ export is made from reconciled, linked data. Only `needs sign-off` rows need a human. The quarter becomes 13 weekly ingests.
3. **Referrals are slow** → we have no referral data, and we say so. The SoT gives the staffing half of the decision: "Which licensed staff are on shift at each facility, by role, for the next 7 days?" A referral feed is one more source for the auction and one more pack entity.

---

## 9. Front end (small web app)

React + Vite + TypeScript + Tailwind. FastAPI serves the API and the built static files. Server-Sent Events (SSE) send live pipeline events.

```
┌─ Harborview SoT ───────────────────────────────────────────── as-of: 2026-10-04 ▾ ┐
│ [Ingest]  Issues (12)  People  Shifts  Credentials  Exports  Contracts            │
├──────────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────┐   LIVE PIPELINE                   │
│  │   Drop files here (any format)              │   hr_roster.csv   CSV 0.97  ✓ map │
│  │   or click to select                        │   payroll.csv     CSV 0.98  ✓ map │
│  └────────────────────────────────────────────┘   licenses.csv    CSV 0.97  ✓ map │
│                                                   schedule.pdf    PDF-text 0.95   │
│                                                     p1 Bayside  lines  ✓ 1 row    │
│                                                     p2 Riverdale lines ✓ 1 row    │
│                                                   resolve: 8 records → 2 people   │
│                                                   checks: 5 issues (2 CRITICAL)   │
└──────────────────────────────────────────────────────────────────────────────────┘

┌─ Issues ────────────────────────────┬─ Evidence ─────────────────────────────────┐
│ ● CRITICAL Worked on expired license│ Marcus Bell · CNA · Riverdale              │
│ ● CRITICAL No RN coverage (10 days) │ [PDF crop: "Marc Bell | CNA | 3p-11p"]     │
│ ● HIGH     Paid 48h vs sched 40h    │ identity p=0.99  reasons ▾                 │
│ ● MEDIUM   Expiration conflict      │ license 2026-09-15 (service) ✓ golden      │
│ ○ INFO     Fuzzy link Marc→Marcus   │ HR says 2026-12-31 ✗                       │
│                                     │ [Acknowledge] [Resolve] [False positive]   │
└─────────────────────────────────────┴────────────────────────────────────────────┘
```

Screens: Ingest (upload + live events), Issues (inbox + evidence drawer + status), People (golden records; each field shows its source), Shifts (person × day grid; red = license not valid on that date), Credentials (expiry horizon), Exports (PBJ CSV, issues CSV), Contracts (approve or edit low-confidence mappings).

---

## 10. End-to-end example

### E.1 Input (README rows + 3 planted defects)

```
hr_roster.csv
E201,Sofia,Reyes,Registered Nurse,Harborview Bayside,718-555-0201,RN-551203,2027-05-31,2020-03-02
E202,Marcus,Bell,Certified Nursing Assistant,Harborview Riverdale,347-555-0202,CNA-771045,2026-12-31,2022-09-12

payroll.csv
P-3001,"REYES, SOFIA",RN,BYS,2026-09-14,2026-09-20,36
P-3002,"BELL, MARCUS",CNA,RVD,2026-09-14,2026-09-20,48        ◄ D2: schedule gives 40

licenses.csv
RN-551203,"REYES, SOFIA",RN,2027-05-31,2026-09-01
CNA-771045,"BELL, MARCUS",CNA,2026-09-15,2026-09-01             ◄ D1: HR says 2026-12-31

schedule.pdf  page 1 "Harborview Bayside"
Sofia Reyes | RN  | 7a-3p | 7a-3p | OFF   | 7a-7p | OFF   | 7a-3p | OFF
              page 2 "Harborview Riverdale"
Marc Bell   | CNA | 3p-11p| OFF   | 3p-11p| 3p-11p| 3p-11p| 3p-11p| OFF  ◄ D3: "Marc" not "Marcus"
footnote: Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours.
```

### E.2 Walk-through

**Step 1 — Upload.** Drop the four files on the upload area. The system writes each file to the landing zone. The file name is its SHA-256 hash.

**Step 2 — Sniff.** The auction runs for each file.
```
hr_roster.csv   CsvParser 0.97   (',' → 9 fields in 3/3 lines, UTF-8)
payroll.csv     CsvParser 0.98   (',' → 7 fields, quotes respected for "REYES, SOFIA")
licenses.csv    CsvParser 0.97
schedule.pdf    PdfTextParser 0.95  (%PDF-, 2 pages, 410 text chars/page)
```

**Step 3 — Extract.** The CSV parser gives three tables. The PDF cascade uses method [1] "lines" on both pages (score 0.96). The system reads the page titles → `FAC-BAY`, `FAC-RVD`. The system reads the footnote → legend `{7a-3p:8, 3p-11p:8, 11p-7a:8, 7a-7p:12}`. The calculated durations agree with the legend.

**Step 4 — Profile + map.** The Hungarian assignment maps all columns (see matrix in A.5). File types: HR roster (0.97), Payroll (0.96), License (0.98), Schedule (0.95). All scores are above 0.80. Thus, no agent call. The system saves four contracts.

**Step 5 — Normalize.**
```
"REYES, SOFIA"        → {given: sofia,  family: reyes}
"Marc Bell"           → {given: marc,   family: bell, nick_key: marcus}
"Certified Nursing Assistant" → CNA        "BYS" → FAC-BAY        "RVD" → FAC-RVD
"Mon 09/14"           → 2026-09-14   (Monday in 2026 ✓; payroll period 09-14..09-20 ✓)
"7a-7p"               → 07:00–19:00, 12.0 h
```

**Step 6 — Resolve.**
```
 HR:E201 ──license RN-551203 (exact)── LIC:RN-551203
    │ family exact + given exact + RN + BYS (p=0.999)
 PAY:P-3001        SCH:p1r1 "Sofia Reyes" (p=0.999)          ══► PERSON P-0001

 HR:E202 ──license CNA-771045 (exact)── LIC:CNA-771045
    │ family exact + given exact + CNA + RVD (p=0.999)
 PAY:P-3002        SCH:p2r1 "Marc Bell": family exact +6.0, Marc≈Marcus +3.5,
                   CNA +1.5, RVD +1.5  → p=0.99 ≥ 0.95 auto-link       ══► PERSON P-0002
```
8 source records → 2 people. No record is left unresolved.

**Step 7 — Claims + survivorship.**
```
P-0002.license_expiration
  claim A: 2026-12-31  source=hr_roster.csv row 3
  claim B: 2026-09-15  source=licenses.csv row 3 (verified 2026-09-01)
  rule: license_service › hr  →  golden = 2026-09-15   + conflict recorded

P-0002.hours week 2026-09-14
  payroll: 48.0      schedule: 8+8+8+8+8 = 40.0   → mismatch recorded
P-0001.hours week 2026-09-14
  payroll: 36.0      schedule: 8+8+12+8 = 36.0    → agree
```

**Step 8 — Checks.** The SQL rules run on the gold tables.
```
CRITICAL LIC-WORKED-EXPIRED  P-0002 worked 09/16, 09/17, 09/18, 09/19 (32 h) after 2026-09-15.
                             Note: last_verified (09/01) is before expiry → a renewal can exist → human must verify.
CRITICAL COV-RN-DAILY        FAC-RVD: no RN on 7 of 7 days. FAC-BAY: no RN on 09/16, 09/18, 09/20.
                             (The sample is very small. Real files have more staff.)
HIGH     HRS-PAID-VS-SCHED   P-0002 paid 48 h, scheduled 40 h (+8 h, +20%).
MEDIUM   SRC-CONFLICT        P-0002 license expiration: HR 2026-12-31 vs service 2026-09-15.
INFO     ID-FUZZY-LINK       "Marc Bell" → P-0002 by nickname (p=0.99).
```

**Step 9 — Publish.** The UI shows the issues with evidence (B.4). The PBJ export:
```
employee  facility  date        job_code  hours  status
E201      FAC-BAY   2026-09-14  7 (RN)    8.0    ready
E201      FAC-BAY   2026-09-15  7         8.0    ready
E201      FAC-BAY   2026-09-17  7         12.0   ready
E201      FAC-BAY   2026-09-19  7         8.0    ready      Σ 36 = payroll 36 ✓
E202      FAC-RVD   2026-09-14  10 (CNA)  8.0    needs sign-off
E202      FAC-RVD   2026-09-16 … 09-19    8.0 ×4 needs sign-off  Σ 40 ≠ payroll 48 ✗
```

### E.3 Variant 1 — mangled file, no agent needed (robustness)

The judges give `payroll.xlsx` with headers `Emp | Cls | Site | Wk Beg | Wk End | Hrs | Ref`. The sheet has two title rows above the header.
1. The auction selects XlsxParser (PK magic + `xl/workbook.xml`).
2. The header detector skips the two title rows. It selects the first row followed by typed values.
3. The header scores are low. The value scores are high: `Emp` 100% `LAST, FIRST`, `Cls` 100% role vocab, `Site` 100% facility vocab, `Ref` 100% `P-\d+`.
4. `Wk Beg` and `Wk End` are both dates. The rule "end ≥ start in 100% of rows" puts them in order.
5. Confidence 0.91 → no agent. The UI shows "schema drift: new contract v2 for Payroll".

### E.4 Variant 2 — new source type, agent path (reuse + vendor paperwork)

The judges give `vendor_docs.csv`: `Vendor, Doc Type, Policy #, Eff, Exp, Contact`.
```
profile → no entity template ≥ 0.80 (best: License 0.41)
        → AgentTask NewSourceModeler → runtime/agent_tasks/pending/t-017.json   (UI: "waiting for agent")
        → in Claude Code: /process-agent-tasks → Sonnet subagent writes done/t-017.json
        ◄── {entity: Credential, holder_type: Organization,
             map: {Vendor: holder_name, Doc Type: credential_type, Policy #: credential_number,
                   Eff: issued_on, Exp: expires_on, Contact: contact_email}}
validator: Exp parses as date 100% ✓, Exp ≥ Eff 100% ✓, Contact email 100% ✓ → ACCEPT (flag: review contract)
checks run with no new code → HIGH LIC-EXPIRING "Linen vendor certificate of insurance expires in 12 days"
```

---

