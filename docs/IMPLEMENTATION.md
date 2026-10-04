# Harborview Source of Truth — Implementation

> Style: ASD-STE100 for prose. Code blocks give exact names and signatures.
>
> Read [`PLAN.md`](PLAN.md) first. This document tells the builders **what to write, where, and how to test it**. Each work package (WP) has one owner, a set of folders, and acceptance tests. A builder writes only in the folders of its WP.

## Contents

1. Principles
2. Stack and repository layout
3. Shared contracts (`sot/core/models.py`)
4. Configuration and settings
5. Storage (DuckDB DDL)
6. Domain pack format
7. Stage ① Sniff — parser auction
8. Stage ② Extract — parsers and PDF cascade
9. Stage ③ Profile + Map
10. Stage ④ Normalize
11. Stage ⑤ Resolve
12. Stage ⑥ Claims + survivorship + gold
13. Stage ⑦ Checks
14. Stage ⑧ Exports (PBJ, issues)
15. Agent gateway
16. Pipeline orchestrator
17. API and SSE events
18. Front end
19. Synthetic data, chaos suite, tests
20. Work packages
21. Timeline
22. Demo script
23. Risks and fallbacks
24. Submission (`DECISIONS.md`)

---

## 1. Principles

1. **Deterministic first.** Code does the work. Agents work only on the low-confidence remainder. A deterministic validator checks each agent result.
2. **Never lose provenance.** Each value keeps its raw form, its normalized form and its locator.
3. **Never block.** A slow or failed step makes an issue. The pipeline continues with the data that is ready.
4. **Engine knows no domain.** Healthcare words occur only in `packs/healthcare_snf/`. The engine reads the pack.
5. **Idempotent.** A known file hash is skipped. An issue has a stable fingerprint. Human status on an issue stays after a re-run.
6. **One contract file.** All modules import shared types from `sot/core/models.py`. No module defines its own copy.

---

## 2. Stack and repository layout

**Backend:** Python 3.12, FastAPI, uvicorn, sse-starlette, DuckDB ≥ 1.1, Polars, pydantic v2, pdfplumber, PyMuPDF (fitz), python-calamine, openpyxl (write only, for test data), charset-normalizer, rapidfuzz, jellyfish (soundex), scipy, PyYAML, reportlab (test PDFs), pytest, hypothesis.

**Front end:** React 18, Vite, TypeScript, Tailwind CSS, TanStack Table, React Router. No UI kit is required.

```
.
├── backend/
│   ├── pyproject.toml
│   ├── sot/
│   │   ├── config.py                    settings + paths
│   │   ├── core/
│   │   │   ├── models.py                ALL shared pydantic types (WP0)
│   │   │   ├── events.py                EventBus (in-process pub/sub → SSE)
│   │   │   ├── registry.py              parser registry
│   │   │   ├── pack.py                  domain pack loader + typed pack model
│   │   │   └── ids.py                   sha256, fingerprints, stable ids
│   │   ├── sniff/auction.py             run_auction()
│   │   ├── parsers/
│   │   │   ├── base.py                  Parser protocol, helpers (header detection)
│   │   │   ├── csv_parser.py
│   │   │   ├── xlsx_parser.py
│   │   │   ├── json_parser.py
│   │   │   └── pdf/
│   │   │       ├── text_parser.py       PdfTextParser (cascade driver)
│   │   │       ├── methods.py           4 extraction methods
│   │   │       ├── scoring.py           table score for a PDF page
│   │   │       ├── context.py           page title + footnote extraction
│   │   │       ├── legend.py            shift legend parser
│   │   │       └── scan_parser.py       PdfScanParser (creates PageReader tasks)
│   │   ├── semantic/
│   │   │   ├── validators.py            field validators (regex, vocab, date, name, ...)
│   │   │   ├── profile.py               profile_table()
│   │   │   ├── mapper.py                score matrix + Hungarian
│   │   │   ├── classify.py              choose entity template
│   │   │   └── contracts.py             contract store, drift detection
│   │   ├── normalize/
│   │   │   ├── names.py  dates.py  vocab.py  phones.py  shifts.py
│   │   │   └── silver.py                RawTable + Mapping → SourceRecords (+ Shifts)
│   │   ├── resolve/
│   │   │   ├── blocking.py  scoring.py  cluster.py
│   │   │   └── resolver.py              resolve_all()
│   │   ├── truth/
│   │   │   ├── claims.py                SourceRecords → Claims
│   │   │   ├── survivorship.py          Claims → GoldenValues + conflicts
│   │   │   └── gold.py                  build gold tables
│   │   ├── checks/
│   │   │   ├── engine.py                run SQL + Python checks → Issues
│   │   │   └── builtin.py               domain-free checks (PARSE-*, ID-*)
│   │   ├── exports/pbj.py  issues_csv.py
│   │   ├── agents/
│   │   │   ├── gateway.py               submit(), cache, watcher, apply results
│   │   │   ├── executors.py             QueueExecutor, ClaudeCliExecutor, OffExecutor
│   │   │   ├── validators.py            per-task-kind deterministic validators
│   │   │   ├── prompts/*.md             one prompt per task kind
│   │   │   └── schemas/*.json           one output JSON schema per task kind
│   │   ├── store/
│   │   │   ├── schema.sql
│   │   │   └── db.py                    connection, migrations, helpers
│   │   ├── pipeline/orchestrator.py     run_ingest()
│   │   └── api/
│   │       ├── app.py                   FastAPI app, static files
│   │       ├── routes_ingest.py  routes_data.py  routes_agents.py
│   │       ├── sse.py
│   │       └── evidence.py              PDF crop renderer
│   ├── packs/healthcare_snf/            (see §6)
│   ├── tools/synth/
│   │   ├── generator.py                 synthetic world + planted defects + expected issues
│   │   ├── render.py                    CSV / XLSX / PDF writers (PDF variants)
│   │   ├── mutators.py                  chaos mutations
│   │   └── chaos.py                     run N variants, report precision/recall
│   └── tests/
│       ├── fixtures/readme_sample/      README rows (4 files)
│       ├── fixtures/example_e1/         PLAN §10 example (3 planted defects)
│       └── test_*.py
├── frontend/                            (see §18)
├── .claude/commands/process-agent-tasks.md
├── runtime/                             git-ignored: db, landing, bronze, agent_tasks, contracts
├── docs/PLAN.md  docs/IMPLEMENTATION.md
├── DECISIONS.md
└── Makefile                             make dev | test | chaos | demo | reset
```

---

## 3. Shared contracts (`sot/core/models.py`)

WP0 writes this file first. Other WPs do not change it without the integrator.

```python
from __future__ import annotations
from datetime import date, datetime, time
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict
import polars as pl

BBox = tuple[float, float, float, float]          # x0, top, x1, bottom in PDF points
Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

# ---------- files and locators ----------
class FileRef(BaseModel):
    file_id: str                 # sha256 of content
    file_name: str
    path: str                    # landing path
    size: int
    received_at: datetime

class Locator(BaseModel):
    file_id: str
    file_name: str
    page: int | None = None      # 1-based, PDF only
    sheet: str | None = None     # XLSX only
    row: int | None = None       # 1-based source row (line number in file / row on page)
    col: str | None = None       # source header text
    bbox: BBox | None = None     # PDF cell box

# ---------- stage ① ----------
class SniffResult(BaseModel):
    parser: str
    score: float                 # 0..1
    reason: str
    details: dict[str, Any] = {}

class AuctionResult(BaseModel):
    file: FileRef
    bids: list[SniffResult]      # all parsers, sorted desc
    winner: SniffResult | None   # None → quarantine

# ---------- stage ② ----------
class ExtractionInfo(BaseModel):
    method: str                  # "csv", "xlsx", "pdf.lines", "pdf.text", "pdf.mupdf", "pdf.words", "agent.page_reader"
    score: float
    notes: list[str] = []

class RawTable(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    table_id: str                # f"{file_id[:12]}:{page or sheet or 0}:{index}"
    file: FileRef
    parser: str
    page: int | None = None
    sheet: str | None = None
    header: list[str]
    df: pl.DataFrame             # all columns Utf8, same order as header, plus "_src_row" (Int64)
    cell_bboxes: dict[str, BBox] | None = None   # key f"{df_row_index}:{col_index}"
    context: dict[str, str] = {} # "title", "footnote", "facility_hint", "legend_json", ...
    extraction: ExtractionInfo

# ---------- stage ③ ----------
class ColumnProfile(BaseModel):
    column: str
    index: int
    n: int
    null_ratio: float
    distinct: int
    inferred_type: Literal["string", "integer", "number", "date", "datetime", "bool", "empty"]
    sample: list[str]            # max 20 distinct non-null values
    validator_hits: dict[str, float]   # field_id → share of non-null values that pass

class FieldMatch(BaseModel):
    column: str
    field_id: str
    score: float
    header_score: float
    value_score: float
    type_score: float

class Mapping(BaseModel):
    table_id: str
    template_id: str | None      # None → unknown
    confidence: float
    matches: list[FieldMatch]
    unmapped_columns: list[str]
    missing_required: list[str]
    source: Literal["auto", "contract", "agent", "human"]
    contract_id: str | None = None
    drift: bool = False

class Contract(BaseModel):
    contract_id: str             # f"{template_id}:v{version}:{fingerprint[:8]}"
    template_id: str
    header_fingerprint: str      # sha1 of sorted normalized header tokens
    version: int
    column_map: dict[str, str]   # source column → field_id
    source: Literal["auto", "agent", "human"]
    approved: bool
    created_at: datetime

# ---------- stage ④ ----------
class PersonKey(BaseModel):
    given: str | None
    family: str | None
    middle: str | None = None
    given_initial: str | None = None
    nick_key: str | None = None  # canonical given name from nickname table
    soundex_family: str | None = None
    display: str                 # original text

class SourceRecord(BaseModel):
    record_id: str               # f"{table_id}:{src_row}"
    template_id: str             # hr_roster | payroll | license | schedule | vendor_credential | ...
    entity: str                  # person | credential | ...
    fields: dict[str, Any]       # canonical field_id → normalized value (JSON-safe)
    raw: dict[str, str | None]   # source column → raw text
    person_key: PersonKey | None
    loc: Locator
    parse_issues: list[str] = [] # e.g. "date_ambiguous:hire_date"

class ShiftRecord(BaseModel):
    shift_id: str                # f"{record_id}:{date}"
    record_id: str               # schedule SourceRecord
    facility_id: str | None
    role: str | None
    work_date: date
    token: str                   # raw "7a-3p"
    start: time | None
    end: time | None
    hours: float | None
    hours_source: Literal["legend", "computed", "both", "unknown"]
    loc: Locator                 # includes bbox for PDF

# ---------- stage ⑤ ----------
class Link(BaseModel):
    a: str                       # record_id
    b: str
    prob: float
    weight: float
    method: Literal["key", "score", "agent", "human"]
    reasons: list[str]

class Person(BaseModel):
    person_id: str               # "P-<employee_id>" if HR exists, else "P-X<hash8>"
    record_ids: list[str]
    employee_id: str | None
    has_hr: bool

# ---------- stage ⑥ ----------
class Claim(BaseModel):
    claim_id: str
    entity_type: str             # person | credential | facility | pay_period
    entity_id: str
    attribute: str               # e.g. "expires_on"
    value: Any
    value_type: str
    template_id: str             # source system
    record_id: str
    loc: Locator
    observed_at: datetime

class GoldenValue(BaseModel):
    entity_type: str
    entity_id: str
    attribute: str
    value: Any
    claim_id: str
    rule: str                    # "priority:license>hr_roster"
    conflict: bool
    conflicting_claim_ids: list[str] = []

# ---------- stage ⑦ ----------
class EvidenceItem(BaseModel):
    kind: Literal["cell", "link", "claim", "golden", "note"]
    label: str
    text: str
    loc: Locator | None = None
    claim_id: str | None = None
    link: Link | None = None
    is_golden: bool | None = None

class IssueDraft(BaseModel):
    check_id: str
    severity: Severity
    title: str
    message: str
    entity_ids: list[str]
    facility_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    key: str = ""                # extra fingerprint discriminator
    evidence: list[EvidenceItem] = []
    action: str | None = None

class Issue(IssueDraft):
    fingerprint: str             # sha1(check_id|sorted(entity_ids)|period_start|period_end|key)
    status: Literal["open", "acknowledged", "resolved", "false_positive"] = "open"
    owner: str | None = None
    note: str | None = None
    first_seen_run: str
    last_seen_run: str

# ---------- agents ----------
AgentKind = Literal["schema_mapper", "page_reader", "identity_adjudicator", "new_source_modeler"]

class AgentTask(BaseModel):
    task_id: str                 # "t-" + sha256(kind+payload+prompt_version)[:10]
    kind: AgentKind
    run_id: str
    ref: str                     # table_id, file_id:page, or "recA|recB"
    prompt_version: str
    instructions: str            # rendered prompt
    payload: dict[str, Any]
    output_schema: dict[str, Any]
    input_files: list[str] = []  # absolute paths the agent may Read (PageReader only)
    status: Literal["pending", "done", "accepted", "rejected", "expired"] = "pending"
    created_at: datetime

class AgentResult(BaseModel):
    task_id: str
    output: dict[str, Any]
    accepted: bool
    validator_notes: list[str]

# ---------- events ----------
EventType = Literal[
    "run.started", "file.landed", "file.skipped", "file.sniffed", "file.quarantined",
    "table.extracted", "table.mapped", "table.drift", "table.unmapped",
    "agent.task_created", "agent.task_done", "agent.task_accepted", "agent.task_rejected",
    "normalize.done", "resolve.done", "truth.done", "checks.done",
    "run.completed", "run.failed", "log",
]

class Event(BaseModel):
    run_id: str
    seq: int
    ts: datetime
    type: EventType
    file_name: str | None = None
    message: str                 # human text for the live pipeline view
    data: dict[str, Any] = {}
```

---

## 4. Configuration and settings

`sot/config.py` reads environment variables and `packs/<pack>/settings.yaml`.

| Setting | Default | Meaning |
|---|---|---|
| `SOT_PACK` | `healthcare_snf` | Domain pack folder |
| `SOT_RUNTIME` | `./runtime` | Data folder |
| `SOT_AGENTS` | `queue` | `queue` \| `cli` \| `off` |
| `SOT_AS_OF` | today | As-of date for expiry checks (UI can change it) |
| `sniff.min_score` | 0.50 | Below → quarantine |
| `pdf.method_min_score` | 0.80 | Cascade stop score |
| `map.auto_min` | 0.80 | Auto-accept mapping |
| `map.agent_min` | 0.50 | 0.50–0.80 → SchemaMapper; < 0.50 → NewSourceModeler |
| `map.no_field_score` | 0.35 | Dummy "no field" score in the Hungarian matrix |
| `link.auto` | 0.95 | Auto-link |
| `link.gray` | 0.75 | Gray zone lower bound |
| `link.prior` | −5.0 | Prior log2-odds |
| `hours.tolerance_abs` | 2.0 | Hours |
| `hours.tolerance_rel` | 0.05 | Share |
| `expiry.high_days` | 30 | |
| `expiry.medium_days` | 60 | |
| `agent.cli.concurrency` | 4 | `cli` executor only |
| `agent.cli.timeout_s` | 90 | |

---

## 5. Storage (DuckDB DDL) — `sot/store/schema.sql`

One file: `runtime/sot.duckdb`. Raw tables go to Parquet: `runtime/bronze/<table_id>.parquet`. JSON columns use DuckDB `JSON`.

```sql
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP,
  status TEXT, file_count INT, summary JSON);

CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY, file_name TEXT, path TEXT, size BIGINT,
  received_at TIMESTAMP, run_id TEXT, parser TEXT, sniff_score DOUBLE,
  bids JSON, status TEXT);                      -- landed|parsed|quarantined|partial

CREATE TABLE IF NOT EXISTS raw_tables (
  table_id TEXT PRIMARY KEY, file_id TEXT, parser TEXT, page INT, sheet TEXT,
  header JSON, n_rows INT, context JSON, extraction JSON, parquet_path TEXT,
  cell_bboxes JSON);

CREATE TABLE IF NOT EXISTS mappings (
  table_id TEXT PRIMARY KEY, template_id TEXT, confidence DOUBLE,
  matches JSON, unmapped JSON, missing_required JSON, source TEXT,
  contract_id TEXT, drift BOOLEAN, status TEXT);  -- mapped|pending_agent|unmapped

CREATE TABLE IF NOT EXISTS contracts (
  contract_id TEXT PRIMARY KEY, template_id TEXT, header_fingerprint TEXT,
  version INT, column_map JSON, source TEXT, approved BOOLEAN, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS source_records (
  record_id TEXT PRIMARY KEY, table_id TEXT, template_id TEXT, entity TEXT,
  fields JSON, raw JSON, person_key JSON, loc JSON, parse_issues JSON);

CREATE TABLE IF NOT EXISTS shifts_silver (
  shift_id TEXT PRIMARY KEY, record_id TEXT, facility_id TEXT, role TEXT,
  work_date DATE, token TEXT, start_t TIME, end_t TIME, hours DOUBLE,
  hours_source TEXT, loc JSON);

-- gold (rebuilt each run from silver)
CREATE OR REPLACE TABLE links (a TEXT, b TEXT, prob DOUBLE, weight DOUBLE, method TEXT, reasons JSON);
CREATE OR REPLACE TABLE persons (person_id TEXT PRIMARY KEY, employee_id TEXT, has_hr BOOLEAN,
  display_name TEXT, role TEXT, home_facility_id TEXT, phone TEXT, hire_date DATE);
CREATE OR REPLACE TABLE person_records (person_id TEXT, record_id TEXT, template_id TEXT, link_prob DOUBLE);
CREATE OR REPLACE TABLE credentials (credential_id TEXT PRIMARY KEY, holder_type TEXT,
  holder_id TEXT, holder_name TEXT, credential_type TEXT, number TEXT,
  issued_on DATE, expires_on DATE, last_verified DATE);
CREATE OR REPLACE TABLE shifts (shift_id TEXT PRIMARY KEY, person_id TEXT, facility_id TEXT,
  role TEXT, work_date DATE, start_ts TIMESTAMP, end_ts TIMESTAMP, hours DOUBLE, loc JSON);
CREATE OR REPLACE TABLE pay_periods (pay_id TEXT PRIMARY KEY, person_id TEXT, facility_id TEXT,
  role TEXT, period_start DATE, period_end DATE, hours_paid DOUBLE, record_id TEXT);
CREATE OR REPLACE TABLE claims (claim_id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT,
  attribute TEXT, value JSON, value_type TEXT, template_id TEXT, record_id TEXT,
  loc JSON, observed_at TIMESTAMP);
CREATE OR REPLACE TABLE golden_values (entity_type TEXT, entity_id TEXT, attribute TEXT,
  value JSON, claim_id TEXT, rule TEXT, conflict BOOLEAN, conflicting_claim_ids JSON);

-- persistent across runs
CREATE TABLE IF NOT EXISTS issues (
  fingerprint TEXT PRIMARY KEY, check_id TEXT, severity TEXT, title TEXT, message TEXT,
  entity_ids JSON, facility_id TEXT, period_start DATE, period_end DATE,
  evidence JSON, action TEXT, status TEXT DEFAULT 'open', owner TEXT, note TEXT,
  first_seen_run TEXT, last_seen_run TEXT, active BOOLEAN);   -- active=false if not seen in last run

CREATE TABLE IF NOT EXISTS agent_tasks (
  task_id TEXT PRIMARY KEY, kind TEXT, run_id TEXT, ref TEXT, status TEXT,
  payload JSON, output JSON, validator_notes JSON, created_at TIMESTAMP, finished_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS agent_cache (cache_key TEXT PRIMARY KEY, kind TEXT, output JSON, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS events (run_id TEXT, seq INT, ts TIMESTAMP, type TEXT,
  file_name TEXT, message TEXT, data JSON);
```

**Rebuild rule.** Stages ①–④ run per new file and append to the persistent tables. Stages ⑤–⑦ rebuild all gold tables from all silver rows on each run. At the expected scale (≤ 100k records) a full rebuild takes seconds. This keeps the logic simple and correct. Issues merge by fingerprint: new → insert; seen → update `last_seen_run`, keep `status`; not seen → `active=false`.

**Concurrency.** One DuckDB connection per process with a lock in `store/db.py`. The API reads through the same module.

---

## 6. Domain pack format — `packs/healthcare_snf/`

```
packs/healthcare_snf/
├── pack.yaml                 name, version, description
├── settings.yaml             thresholds (override §4 defaults)
├── fields.yaml               canonical fields
├── templates.yaml            entity templates (file types)
├── vocab/roles.yaml
├── vocab/facilities.yaml
├── vocab/nicknames.csv       nickname,canonical
├── survivorship.yaml
├── resolution.yaml           blocking keys, weights, cannot-link rules
├── checks/                   *.sql and *.py
└── exports/pbj.yaml          job codes + column spec
```

### 6.1 `fields.yaml`

```yaml
fields:
  person.employee_id:
    type: string
    synonyms: [employee id, emp id, employee number, emp no, staff id, ee id]
    validator: {regex: '^[A-Z]{0,3}\d{2,8}$'}
  person.full_name:
    type: person_name
    synonyms: [employee name, name, staff, staff member, employee, name on license, emp]
    validator: {person_name: true}          # "LAST, FIRST" or "First [M.] Last"
  person.given_name:
    type: string
    synonyms: [first name, first, given name, fname]
    validator: {single_name_token: true}
  person.family_name:
    type: string
    synonyms: [last name, last, surname, family name, lname]
    validator: {single_name_token: true}
  person.role:
    type: vocab
    vocab: roles
    synonyms: [job title, title, role, job code, position, class, cls, license type, type]
    validator: {vocab: roles}
  person.facility:
    type: vocab
    vocab: facilities
    synonyms: [facility, facility code, site, location, building, campus]
    validator: {vocab: facilities}
  person.phone:
    type: phone
    synonyms: [phone, phone number, mobile, cell, telephone]
    validator: {phone: true}
  person.hire_date:
    type: date
    synonyms: [hire date, start date, date hired, doh]
    validator: {date: true}
  credential.number:
    type: string
    synonyms: [license number, license no, license #, lic no, cert number, credential number, policy #]
    validator: {regex: '^[A-Z]{2,5}-?\d{3,10}$'}
  credential.type:
    type: vocab
    vocab: roles
    synonyms: [license type, credential type, cert type, doc type]
    validator: {vocab: roles}
  credential.expires_on:
    type: date
    synonyms: [expiration, expiration date, license expiration, expires, exp, exp date, valid until]
    validator: {date: true}
  credential.last_verified:
    type: date
    synonyms: [last verified, verified on, verification date]
    validator: {date: true}
  credential.issued_on:
    type: date
    synonyms: [issued, issue date, effective, eff, effective date]
    validator: {date: true}
  pay.payroll_id:
    type: string
    synonyms: [payroll id, pay id, ref, reference, check no]
    validator: {regex: '^[A-Z]{1,3}-?\d{2,10}$'}
  pay.period_start:
    type: date
    synonyms: [period start, pay period start, week begin, wk beg, from, start]
    validator: {date: true}
  pay.period_end:
    type: date
    synonyms: [period end, pay period end, week end, wk end, to, end]
    validator: {date: true}
  pay.hours_paid:
    type: number
    synonyms: [hours paid, hours, hrs, paid hours, total hours]
    validator: {number: {min: 0, max: 120}}
  schedule.day:
    type: shift_cell
    repeatable: true                        # many columns map to this field
    header_pattern: '^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s+\d{1,2}/\d{1,2}(/\d{2,4})?$'
    validator: {shift_token_or_off: true}
  org.name:
    type: string
    synonyms: [vendor, vendor name, company, supplier, organization]
    validator: {non_empty: true}
  contact.email:
    type: email
    synonyms: [email, contact, contact email]
    validator: {email: true}
```

### 6.2 `templates.yaml`

```yaml
templates:
  hr_roster:
    entity: person
    required: [person.employee_id, person.given_name, person.family_name, person.role, person.facility]
    optional: [person.phone, credential.number, credential.expires_on, person.hire_date]
    anchor: true                            # system of record for identity
  payroll:
    entity: pay_period
    required: [person.full_name, person.role, person.facility, pay.period_start, pay.period_end, pay.hours_paid]
    optional: [pay.payroll_id]
    relations: [{gte: [pay.period_end, pay.period_start]}]
  license:
    entity: credential
    required: [credential.number, person.full_name, credential.type, credential.expires_on]
    optional: [credential.last_verified]
  schedule:
    entity: shift_grid
    required: [person.full_name, person.role, schedule.day]
    context: {facility_from: [title, facility_hint], legend_from: footnote}
  vendor_credential:                        # generic credential with an organization holder
    entity: credential
    holder: organization
    required: [org.name, credential.expires_on]
    optional: [credential.type, credential.number, credential.issued_on, contact.email]
    relations: [{gte: [credential.expires_on, credential.issued_on]}]
```

A template is format-free. A schedule as CSV or XLSX uses the same template as the PDF.

### 6.3 Vocabularies

```yaml
# vocab/roles.yaml
RN:  [registered nurse, rn, r.n., staff nurse]
LPN: [licensed practical nurse, lpn, l.p.n., lvn, licensed vocational nurse]
CNA: [certified nursing assistant, cna, c.n.a., nurse aide, nursing assistant]
# license scope: which license types may work which role
scope: {RN: [RN], LPN: [LPN, RN], CNA: [CNA, LPN, RN]}

# vocab/facilities.yaml
FAC-BAY: {name: Harborview Bayside,   aliases: [harborview bayside, bayside, bys, hv bayside]}
FAC-RVD: {name: Harborview Riverdale, aliases: [harborview riverdale, riverdale, rvd, hv riverdale]}
```

Vocab matching: lower-case, remove punctuation, collapse spaces, then exact alias match; else rapidfuzz `token_set_ratio ≥ 90` against aliases. A fuzzy vocab hit adds `parse_issues: vocab_fuzzy:<field>`.

### 6.4 `survivorship.yaml`

```yaml
person:
  display_name:   [hr_roster, license, payroll, schedule]
  role:           [hr_roster, payroll, schedule]
  home_facility:  [hr_roster, payroll]
  phone:          [hr_roster]
  hire_date:      [hr_roster]
credential:
  expires_on:     {priority: [license, hr_roster], conflict_check: true}
  credential_type: [license, hr_roster]
  holder_name:    [license, hr_roster]
tie_break: latest_observed     # same source, two values → newest file wins, conflict flagged
```

### 6.5 `resolution.yaml`

```yaml
anchor_template: hr_roster
hard_keys:
  - {field: credential.number, templates: [hr_roster, license]}
blocking:
  - [credential.number]
  - [soundex_family, facility]
  - [family, given_initial]
weights:                      # log2(m/u); recalibrated from hard-key pairs when ≥ 20 exist
  family_exact: 6.0
  family_fuzzy: 3.0           # Jaro-Winkler ≥ 0.92
  given_exact: 3.5
  given_nickname: 3.5
  given_fuzzy: 2.0            # JW ≥ 0.90
  given_initial: 1.0
  given_disagree: -3.0
  role_agree: 1.5
  role_disagree: -2.0
  facility_agree: 1.5
  facility_disagree: -0.5     # floats exist
prior: -5.0
cannot_link:
  - distinct: person.employee_id
  - distinct_per_type: [credential.number, credential.type]
```

### 6.6 `exports/pbj.yaml`

```yaml
job_codes: {RN: 7, LPN: 9, CNA: 10}   # VERIFY against the current CMS PBJ data specification
columns: [facility_id, employee_id, person_id, work_date, job_code, hours, status, note]
```

---

## 7. Stage ① Sniff — parser auction (`sot/sniff/auction.py`)

```python
class Parser(Protocol):
    name: ClassVar[str]
    def sniff(self, head: bytes, path: Path) -> SniffResult: ...
    def extract(self, file: FileRef, ctx: "ExtractContext") -> list[RawTable]: ...

def run_auction(file: FileRef, parsers: list[Parser], min_score: float) -> AuctionResult
```

`head` = first 64 KB. The registry (`core/registry.py`) holds parser instances. A decorator `@register_parser` adds a class.

| Parser | Score rules |
|---|---|
| `CsvParser` | Reject if binary (NUL bytes or `%PDF`/`PK`). Decode (BOM → charset-normalizer). For each delimiter in `, ; \t \|`: parse ≤ 200 lines with `csv.reader` (quotes respected); `consistency` = share of non-empty lines with the modal field count; require modal count ≥ 2. Score = `0.5 + 0.5 × consistency` for the best delimiter. Reason names the delimiter, field count, encoding. |
| `XlsxParser` | `PK\x03\x04` and the zip has `xl/workbook.xml` → 0.98. `D0CF11E0` (legacy XLS) → 0.90 (calamine reads it). |
| `JsonParser` | First non-space byte is `{` or `[` and `json.loads` works on the full file (or NDJSON: each line parses) → 0.95. |
| `PdfTextParser` | `%PDF-` → open with PyMuPDF. `chars_per_page` = mean text chars. ≥ 100 → 0.95; 20–99 → 0.6; < 20 → 0.1. |
| `PdfScanParser` | `%PDF-` with `chars_per_page < 20`, or image file (PNG/JPEG magic) → 0.9. Else 0.05. |

Tie → the parser listed first in the registry. Each bid goes into `files.bids` and into the `file.sniffed` event.

---

## 8. Stage ② Extract

### 8.1 Header detection (shared, `parsers/base.py`)

```python
def detect_header_row(rows: list[list[str | None]], max_scan: int = 20) -> int
```

For each candidate row `i` among the first 20: `header_like(i)` = share of non-empty cells that are text (not number, not date) × share of distinct values. `data_like(i+1..i+5)` = share of cells in the next 5 rows that are number, date or vocab-like, or that differ in type from row `i`. Select the first row with `header_like ≥ 0.7` and `data_like ≥ 0.3` and non-empty count ≥ 50% of the modal width. Fallback: row 0. Drop fully empty rows and fully empty columns. Strip whitespace. Make duplicate header names unique (`name`, `name_2`).

### 8.2 CSV (`csv_parser.py`)

Use the delimiter and encoding from the sniff details. Read with Polars `read_csv(..., separator=d, has_header=False, infer_schema_length=0, encoding="utf8-lossy", truncate_ragged_lines=True)` after transcoding to UTF-8 if needed. Apply header detection. Add `_src_row` = source line number. For files > 200 MB, use `pl.scan_csv` and stream to Parquet.

### 8.3 XLSX (`xlsx_parser.py`)

`python-calamine` → each non-empty sheet is a candidate table. Convert all cells to strings: dates as ISO, integers without `.0`. Apply header detection. `sheet` = sheet name.

### 8.4 JSON (`json_parser.py`)

A list of objects → one table (`pl.json_normalize`). An object with list values → one table per list key. NDJSON → one table.

### 8.5 PDF text (`parsers/pdf/`)

Each page is processed separately (`ProcessPoolExecutor` for > 4 pages).

**Context (`context.py`):**
- `title` = text lines above the table bbox (largest font first). `facility_hint` = the first vocab match for facilities in the title.
- `footnote` = text lines below the table bbox.
- `week_hint` = any date in the title ("Week of 09/14/2026").

**Methods (`methods.py`).** Each returns `(header, rows, cell_bboxes, table_bbox)` or `None`:
1. `pdf.lines`: `page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"})` (pdfplumber).
2. `pdf.text`: pdfplumber with `"text"` strategies, `snap_tolerance=3`, `join_tolerance=3`.
3. `pdf.mupdf`: `fitz.Page.find_tables()`.
4. `pdf.words`: `page.extract_words()`. Group into lines by `top` (tolerance 3 pt). Find the header line = the line with the most header-pattern hits (`Staff|Name`, `Role`, day pattern). Column boundaries = midpoints between header word x-ranges. Assign each word to a column by its x-center. Merge words in the same cell with spaces. A line with an empty first column and non-empty other columns is a continuation (wrapped name) → append to the previous row.

**Scoring (`scoring.py`):**
```
score = header_score × cell_validity × shape
header_score  = share of expected header roles found (name col, role col, ≥ 5 day cols)
cell_validity = share of day cells that are a valid shift token or OFF (or blank)
shape         = 1.0 if 7 day columns, 0.8 if 5–6, else 0.5
```
Run methods in order. Stop at the first score ≥ `pdf.method_min_score`. If none passes, keep the best result and create an issue `PARSE-PDF-LOW-CONFIDENCE` with the score. If the best score < 0.5 → create a `page_reader` agent task for that page.

**Legend (`legend.py`):**
```python
def parse_legend(text: str) -> dict[str, float]   # {"7a-3p": 8.0, "7a-7p": 12.0, ...}
```
Split the footnote into sentences. In each sentence, find all shift tokens and one number before `hour(s)/hrs/h`. Assign that number to each token. Store the result in `context["legend_json"]`.

**Shift token grammar (`normalize/shifts.py`):**
```
TOKEN  := TIME SEP TIME
TIME   := H[:MM] [a|p][m]  |  HH:MM (24h)
SEP    := "-" | "–" | "—" | "to"
OFF    := off | o | x | — | - | "" | pto | vac | lv   → not worked (pto/vac/lv kept as tags)
```
`hours_computed = (end - start) mod 24h`. If a legend exists and the token is in it: `hours = legend`, and `hours_source = "both"` when equal, else make `LEGEND-MISMATCH`. Tokens with a suffix (`7a-3p*`, `7a-3p (float BYS)`) keep the suffix as a note. Unknown token → `PARSE-SHIFT-TOKEN` issue, hours = null.

### 8.6 PDF scan (`scan_parser.py`)

Render each page to PNG at 150 dpi into `runtime/agent_tasks/files/`. Create one `page_reader` task per page. Return an empty table list with `extraction.method = "agent.page_reader.pending"`. When a task is accepted, the gateway builds the `RawTable` from the agent rows (method `agent.page_reader`) and re-enters the pipeline at stage ③.

---

## 9. Stage ③ Profile + Map

### 9.1 Validators (`semantic/validators.py`)

```python
Validator = Callable[[str], bool]
def build_validators(pack: Pack) -> dict[str, Validator]          # field_id → fn
```

| Kind | Rule |
|---|---|
| `regex` | `re.fullmatch` after strip/upper |
| `vocab` | normalized value in vocab aliases (exact or fuzzy ≥ 90) |
| `date` | parse with the multi-format parser (§10.2) |
| `number` | float within `[min, max]` |
| `person_name` | `^[A-Za-z'’.\- ]+,\s*[A-Za-z'’.\- ]+$` or 2–4 alphabetic tokens; not in any vocab |
| `single_name_token` | 1–2 alphabetic tokens |
| `phone` | 10–11 digits after removing non-digits |
| `email` | basic email regex |
| `shift_token_or_off` | the shift grammar accepts it |

### 9.2 Profile (`semantic/profile.py`)

```python
def profile_table(t: RawTable, validators: dict[str, Validator], sample_rows: int = 2000) -> list[ColumnProfile]
```
Use up to 2,000 non-null values per column (random sample with a fixed seed for big tables). `validator_hits[field] = passes / non_null`.

### 9.3 Mapper (`semantic/mapper.py`)

```python
def header_similarity(col: str, field: FieldSpec) -> float
def score_matrix(profiles: list[ColumnProfile], fields: list[FieldSpec]) -> np.ndarray
def assign(profiles, fields, no_field_score: float) -> list[FieldMatch]
```

- `header_similarity` = max over the synonyms and the field id words of `max(token_set_ratio/100, jaro_winkler)` after normalization (lower case; `_`, `-`, `#` → space; expand `no`→number, `exp`→expiration, `dt`→date).
- `value_score` = `validator_hits[field]`.
- `type_score` = 1 if the inferred type fits the field type, 0.5 if compatible (integer for number), else 0.
- `S = 0.45·header + 0.45·value + 0.10·type`. **Value gate:** if `value_score < 0.5`, cap `S` at 0.4. A header alone cannot win against bad values.
- **Repeatable fields first.** Columns whose header matches `header_pattern` (e.g. `schedule.day`) are pre-assigned and removed from the matrix.
- **Hungarian:** build the matrix `[n_cols × (n_fields + n_cols)]`. The extra `n_cols` columns are "no field" with the score `no_field_score`. Solve `linear_sum_assignment(-S)`.
- **Relations:** after the assignment, test each template relation (e.g. `period_end ≥ period_start`). If it fails in > 50% of rows, swap the two columns and re-test.

### 9.4 Classify (`semantic/classify.py`)

```python
def classify(profiles, pack) -> tuple[str | None, float, list[FieldMatch], list[str]]
```
For each template: run `assign` with only that template's fields (required + optional). Then:
```
coverage   = share of required fields matched with S ≥ 0.5
quality    = mean S over matched required fields
confidence = coverage × quality
```
The best template wins. Ties → higher coverage. Thresholds: `≥ map.auto_min` → auto; `map.agent_min..auto_min` → `schema_mapper` task (the table is stored with `status=pending_agent`); `< map.agent_min` → `new_source_modeler` task.

### 9.5 Contracts (`semantic/contracts.py`)

- `header_fingerprint` = sha1 of the sorted, normalized header tokens joined by `|`.
- **Lookup order:** (1) an exact fingerprint match → use the contract (`source="contract"`), but re-validate the value scores. If any mapped column now has `value_score < 0.5` → drift. (2) No match → classify. If a contract exists for the same template with a different fingerprint → `drift=True`, version + 1, event `table.drift`.
- Contracts are stored in DuckDB and exported as YAML to `runtime/contracts/<contract_id>.yaml` for review.
- Agent and auto contracts have `approved=False` until a human approves them in the UI. Unapproved contracts still apply. The UI shows them as "auto-applied, review".

---

## 10. Stage ④ Normalize (`sot/normalize/`)

### 10.1 Names (`names.py`)

```python
def parse_person_name(text: str, nick: dict[str, str]) -> PersonKey
```
1. NFKD, remove accents, case fold, keep letters, apostrophes, hyphens, spaces, commas and periods.
2. Remove suffixes and titles: `jr sr ii iii iv rn cna lpn mr ms mrs dr`.
3. If a comma exists: `family = before`, `given (+ middle) = after`. Else: the last token = family; the first token = given; the tokens in between = middle. Particles (`de, del, la, van, von, da, di`) join the family name.
4. `given_initial = given[0]`. `nick_key = nick.get(given, given)`. `soundex_family = jellyfish.soundex(family)`.
5. A one-letter given name (`M.`) sets only `given_initial`.

HR has separate first and last columns. `silver.py` builds the key from those two fields directly.

Nickname table: ship ≥ 300 common US pairs in `vocab/nicknames.csv` (marc→marcus, mark→marcus? **no**: mark and marcus are different names; keep mappings conservative). The matcher treats two given names as a nickname match if `nick_key(a) == nick_key(b)` or one name is a prefix of the other with length ≥ 3 (marc/marcus, sam/samantha).

### 10.2 Dates (`dates.py`)

```python
def infer_column_date_format(values: list[str]) -> tuple[str | None, bool]   # (format, ambiguous)
def parse_date(value: str, fmt: str | None) -> date | None
def resolve_weekday_date(dow: str, month: int, day: int, anchors: list[date]) -> tuple[date, list[int]]
```
- Candidate formats: `%Y-%m-%d`, `%m/%d/%Y`, `%m/%d/%y`, `%d/%m/%Y`, `%Y/%m/%d`, `%d-%b-%Y`, `%b %d, %Y`, `%m-%d-%Y`, Excel serial numbers (30000–60000).
- **Column-level inference:** select the format that parses the most values. If both `%m/%d` and `%d/%m` parse all values and no value has a part > 12 → `ambiguous=True`. Then use `%m/%d` (US default) and make a `PARSE-DATE-AMBIGUOUS` issue for the column.
- **Weekday dates** (`Mon 09/14`): for years in `[min(anchors).year - 1, max(anchors).year + 1]`, keep the years where the date has that weekday. Select the year nearest to the anchor dates (payroll periods, the file's other dates, today). If no year matches → `PARSE-DATE-WEEKDAY` issue.

### 10.3 Other normalizers

- `vocab.py`: `normalize_vocab(value, vocab) -> (code | None, fuzzy: bool)`.
- `phones.py`: digits only; 10 digits → `+1XXXXXXXXXX`; 11 digits starting with 1 → `+1...`; else keep the raw value + issue `PARSE-PHONE`.
- `shifts.py`: §8.5 grammar.

### 10.4 Silver builder (`silver.py`)

```python
def build_silver(t: RawTable, m: Mapping, pack: Pack, anchors: list[date]) -> tuple[list[SourceRecord], list[ShiftRecord]]
```
- One `SourceRecord` per row. `fields` keys are canonical field ids. Values: ISO strings for dates, floats for numbers, codes for vocab values.
- `person_key` from `person.full_name`, or from `given_name` + `family_name`.
- **Schedule template:** for each row, one `SourceRecord` (template `schedule`, fields: full_name, role, facility from `context.facility_hint`) plus one `ShiftRecord` per day column with a worked token. The day column header gives the date (§10.2). The bbox comes from `cell_bboxes`.
- All parse problems go into `parse_issues`. The builtin checks make issues from them.

---

## 11. Stage ⑤ Resolve (`sot/resolve/`)

```python
def block(records: list[SourceRecord], cfg) -> set[tuple[str, str]]
def score_pair(a: SourceRecord, b: SourceRecord, cfg) -> Link
def cluster(records, links, cfg) -> tuple[list[Person], list[IssueDraft]]
def resolve_all(records: list[SourceRecord], pack: Pack) -> tuple[list[Person], list[Link], list[IssueDraft], list[AgentTask]]
```

**Steps**

1. **Hard links.** HR ↔ License where `credential.number` is equal (normalized: upper case, no spaces, `-` optional) → `Link(method="key", prob=1.0)`. A name check runs on the pair. If the family names differ (JW < 0.85) → INFO `ID-NAME-DIFFERS-ON-LICENSE` (maiden name case). The link stays.
2. **Blocking.** Build an index dict per blocking key: key value → record ids. The candidate pairs are the pairs inside each bucket, excluding pairs of two records from the same table. Cap bucket size at 200. A larger bucket is split by `facility`.
3. **Scoring.** Use the weights in `resolution.yaml`. `total = prior + Σ weights`. `prob = 1 / (1 + 2**(-total))`. `reasons` = a list of strings such as `"family exact (+6.0)"`.
4. **Calibration** (optional, if ≥ 20 hard-key pairs): estimate `m` for each comparison from the hard-key pairs and `u` from 2,000 random cross-table pairs. Replace the weights with `log2(m/u)`, clipped to [−4, 8]. Log the new weights in the `resolve.done` event.
5. **Zones.** `prob ≥ link.auto` → link. `link.gray ≤ prob < link.auto` → create an `identity_adjudicator` task (the pair is not linked until a human or a validated agent result confirms it) and an INFO issue `ID-GRAY-PAIR`. `< link.gray` → no link.
6. **Cluster.** Union-find with path compression and union by size. Process links in descending `prob`. Before each union, check the `cannot_link` rules on the two groups (each group keeps the sets `employee_ids` and `{credential_type: number}`). If a rule fails → skip the union and create `ID-CONFLICT` (HIGH) with both groups as evidence.
7. **Persons.** A group with an HR record → `person_id = "P-" + employee_id`. A group without HR → `person_id = "P-X" + sha1(sorted record ids)[:8]`, `has_hr=False`. (PLAN.md examples use `P-0001`/`P-0002` for readability. The real ids are `P-E201`/`P-E202`. Ids derived from `employee_id` stay stable across runs.)
8. **One-to-one guard.** Each payroll row and each schedule row joins at most one HR person. If a record has two auto-links to two different HR persons → keep the higher one. If the difference is < 0.05 → keep neither and make `ID-AMBIGUOUS` (MEDIUM).

**Scale.** Blocking keeps the pair count near `n × bucket size`. Use rapidfuzz `process.cdist` for vectorized JW inside large buckets.

---

## 12. Stage ⑥ Claims + survivorship + gold (`sot/truth/`)

**Claims (`claims.py`).** For each `SourceRecord` in a person group, emit person claims (display_name, role, home_facility, phone, hire_date). For credential data (license rows, and HR `credential.number` + `credential.expires_on`), emit claims on `entity_type="credential"`, `entity_id = credential.number` (normalized). Vendor rows → `entity_id = "ORG:" + slug(org.name) + ":" + (number or type)`.

**Survivorship (`survivorship.py`).** For each `(entity, attribute)`: order the claims by the source priority in `survivorship.yaml`, then by `observed_at` desc. The first claim is golden. `conflict=True` if another claim has a different normalized value (dates: different day; numbers: |Δ| > 0; strings: case-folded, not equal). Each conflict on an attribute with `conflict_check: true` → `SRC-CONFLICT` issue draft.

**Gold (`gold.py`).** Rebuild: `persons`, `person_records`, `credentials` (golden values), `shifts` (shifts_silver joined to the schedule record's person; `start_ts`/`end_ts` with the overnight wrap), `pay_periods` (payroll records joined to persons).

---

## 13. Stage ⑦ Checks (`sot/checks/`)

### 13.1 Check file format

SQL checks: `packs/<pack>/checks/<ID>.sql`. A YAML header in a comment, then one SELECT:

```sql
-- id: HRS-PAID-VS-SCHED
-- severity: HIGH
-- title: "Paid hours do not match scheduled hours"
-- action: "Payroll: confirm the timecard. Scheduler: confirm the schedule."
-- required columns: entity_ids, facility_id, period_start, period_end, message, evidence, key
WITH sched AS (
  SELECT s.person_id, p.pay_id, p.period_start, p.period_end, p.facility_id,
         SUM(s.hours) AS sched_hours
  FROM pay_periods p
  LEFT JOIN shifts s ON s.person_id = p.person_id
       AND s.work_date BETWEEN p.period_start AND p.period_end
  GROUP BY ALL)
SELECT [p.person_id] AS entity_ids, p.facility_id, p.period_start, p.period_end,
       printf('%s paid %.1f h, scheduled %.1f h (%+.1f h)', per.display_name, p.hours_paid,
              coalesce(s.sched_hours,0), p.hours_paid - coalesce(s.sched_hours,0)) AS message,
       json_object('pay_record', p.record_id, 'paid', p.hours_paid, 'scheduled', s.sched_hours) AS evidence,
       p.pay_id AS key
FROM pay_periods p JOIN sched s USING (pay_id) JOIN persons per ON per.person_id = p.person_id
WHERE abs(p.hours_paid - coalesce(s.sched_hours,0))
      > greatest(getvariable('hours_tol_abs'), getvariable('hours_tol_rel') * p.hours_paid);
```

Python checks: `checks/<ID>.py` with `def run(con, ctx) -> list[IssueDraft]`. Use them for logic that is hard in SQL.

The engine sets DuckDB variables before each run: `as_of`, `hours_tol_abs`, `hours_tol_rel`, `expiry_high_days`, `expiry_medium_days`. The **evidence enricher** converts the IDs in `evidence` (record ids, claim ids, shift ids) into full `EvidenceItem`s with locators. Each check does not need to build evidence by hand.

### 13.2 Check catalogue (exact semantics)

| ID | Sev | Type | Logic |
|---|---|---|---|
| LIC-WORKED-EXPIRED | CRITICAL | SQL | Shift `work_date > credential.expires_on` for a credential of the person whose type is in the role scope. One issue per person × credential, listing all shift dates and hours. Note in the message if `last_verified < expires_on` ("renewal may exist"). |
| LIC-NONE-FOR-ROLE | CRITICAL | SQL | Person has shifts in a licensed role but no credential of a type in the scope for that role. |
| LIC-SCOPE | CRITICAL | SQL | Shift role (from the schedule) needs a license type that the person's golden credentials do not include (e.g. schedule role RN, credential CNA only). |
| COV-RN-DAILY | CRITICAL | Py | For each facility × day in the schedule's date range: build the union of RN shift intervals that overlap the day. If the longest consecutive covered span < 8 h → issue. One issue per facility, listing the days. |
| ID-DUP-LICENSE | CRITICAL | SQL | One `credential.number` appears in records that belong to ≥ 2 different persons. |
| ID-CONFLICT | HIGH | builtin | A cannot-link rule stopped a merge (from the resolver). |
| HRS-PAID-VS-SCHED | HIGH | SQL | §13.1. |
| PAY-NO-HR | HIGH | SQL | A pay period whose person has `has_hr = false`. |
| SHIFT-OVERLAP | HIGH | Py | Two shifts of one person overlap in time (all facilities). |
| HRS-DAILY-EXCESS | HIGH | SQL | > 16 h scheduled for one person in one day. |
| LIC-EXPIRING | HIGH / MEDIUM | SQL | `expires_on - as_of` in [0, 30] → HIGH; in (30, 60] → MEDIUM. Persons and organizations. |
| LIC-EXPIRED-NOT-WORKING | MEDIUM | SQL | Expired as of `as_of` and no shift after the expiry. |
| SRC-CONFLICT | MEDIUM | survivorship | Attribute conflict with `conflict_check`. |
| SCHED-NO-HR | MEDIUM | SQL | Schedule person with `has_hr = false`. |
| FAC-MISMATCH | MEDIUM | SQL | Shift facility ≠ golden home facility. Message says "float or schedule error". |
| ROLE-MISMATCH | MEDIUM | SQL | Payroll or schedule role ≠ HR role. |
| LEGEND-MISMATCH | MEDIUM | builtin | Legend hours ≠ computed hours for a token. |
| HR-DUP-ROW | MEDIUM | SQL | Two HR rows with one employee_id and different values. |
| ID-AMBIGUOUS | MEDIUM | builtin | §11 step 8. |
| ID-NAME-DIFFERS-ON-LICENSE | LOW | builtin | §11 step 1. |
| PARSE-* | LOW–HIGH | builtin | From `parse_issues` and the extract stage: `PARSE-DATE`, `PARSE-DATE-AMBIGUOUS`, `PARSE-SHIFT-TOKEN`, `PARSE-PHONE`, `PARSE-PDF-LOW-CONFIDENCE`, `FILE-QUARANTINED` (HIGH), `TABLE-UNMAPPED` (HIGH), `MAPPING-REVIEW` (INFO). |
| ID-FUZZY-LINK | INFO | builtin | An auto-link with a fuzzy, nickname or initial reason. |
| ID-GRAY-PAIR | INFO | builtin | §11 step 5. |
| PAY-DUPLICATE | HIGH | SQL | The same payroll id or the same person × facility × period appears twice (W4). |
| PAY-PERIOD-OVERLAP | HIGH | SQL | Two pay periods of one person overlap (W4). |
| PAY-PERIOD-INVALID | MEDIUM | SQL | period_end < period_start, or the period is longer than 14 days (weekly payroll) (W4). |
| PAY-HOURS-INVALID | HIGH | SQL | hours_paid < 0, missing, or > 100 per 7 days of the period (W4). |
| LIC-EXPIRY-MISSING | HIGH | SQL | A license/HR credential has no parseable expiration date (W4). |
| LIC-TYPE-MISMATCH | MEDIUM | SQL | License number prefix (CNA-…) disagrees with the license type (RN) (W4). |
| HR-HIRE-DATE | MEDIUM | SQL | Hire date in the future, or after the person's first pay period or shift (W4). |
| ROW-INCOMPLETE | MEDIUM | builtin | A row lacks required fields (totals/footer rows, blank dates) — kept, excluded from facts it cannot support (W4). |
| TABLE-EMPTY | LOW | pipeline | A table with a header and no data rows (W4). |
| PARSE-PDF-LOW-CONFIDENCE | MEDIUM | pipeline | PDF page extraction score < 0.8 or no table on a page (W4). |
| PARSE-NUMBER · PARSE-UNKNOWN-VALUE · PARSE-FUZZY-VALUE · PARSE-SCHEDULE-DATES · PARSE-DATE-WEEKDAY | see TASKGRAPH §6 | builtin | Parse-issue contract (W4). |

### 13.3 Engine (`checks/engine.py`)

```python
def run_checks(con, pack: Pack, run_id: str, extra_drafts: list[IssueDraft]) -> list[Issue]
```
Load all checks. Run each in a try/except (a failed check makes one `CHECK-ERROR` issue and does not stop the run). Enrich the evidence. Compute fingerprints. Merge into `issues` (§5 rule). Sort the output by severity, then by check id.

---

## 14. Stage ⑧ Exports (`sot/exports/`)

**PBJ (`pbj.py`).**
```python
def build_pbj(con, pack, quarter: str | None = None) -> pl.DataFrame
```
- One row per person × facility × work_date from gold `shifts`, `job_code` from the golden role via `pbj.yaml`.
- For each pay period: if `|Σ shift hours − hours_paid| ≤ tolerance` → `status="ready"`. Else → `status="needs_signoff"` and `note` = "paid X, scheduled Y". The system never re-distributes hours.
- Persons with `has_hr=false` → `status="needs_signoff"`, note "no HR record".
- Endpoint returns CSV. Stretch: PBJ XML.

**Issues CSV (`issues_csv.py`).** All active issues, flattened (evidence as a text summary).

---

## 15. Agent gateway (`sot/agents/`)

### 15.1 Task life cycle

```
create (stage) → cache lookup → [hit] apply
                              → [miss] write runtime/agent_tasks/pending/<task_id>.json
                                       status=pending, event agent.task_created
executor completes → runtime/agent_tasks/done/<task_id>.json
watcher (asyncio loop, polls every 1 s) → load → JSON-schema check (jsonschema lib)
   → validators.validate(kind, task, output) → accepted? 
        yes → cache + apply(kind) + event agent.task_accepted + re-run affected stages
        no  → status=rejected + issue AGENT-REJECTED (HIGH, includes the output as a suggestion)
```

**Task file** (`pending/<id>.json`) = `AgentTask.model_dump_json()`. It contains everything the subagent needs: `instructions`, `payload`, `output_schema`, `input_files`, and the exact output path.

### 15.2 Executors (`executors.py`)

```python
class Executor(Protocol):
    async def submit(self, task: AgentTask) -> None: ...

class QueueExecutor:      # default: writes pending/ file; Claude Code processes the queue
class ClaudeCliExecutor:  # runs claude -p per task (semaphore = agent.cli.concurrency)
class OffExecutor:        # immediately rejects → AGENT-UNAVAILABLE issue (needs human)
```

`ClaudeCliExecutor` command:
```bash
claude -p "$(cat instructions_with_payload.md)" \
  --model sonnet \
  --output-format json \
  --json-schema "$(cat schema.json)" \
  --tools "Read"            # page_reader only; otherwise --tools "" \
  --no-session-persistence \
  --max-budget-usd 0.50
```
`cwd` = a temp folder with only the task inputs. Parse the JSON envelope, take the structured result, and write it to `done/<id>.json`. Do not use `--bare` (it requires `ANTHROPIC_API_KEY`).

### 15.3 Claude Code slash command (`.claude/commands/process-agent-tasks.md`)

```markdown
---
description: Process pending Source-of-Truth agent tasks with parallel Sonnet subagents
---
1. List the files in `runtime/agent_tasks/pending/`. If there are none, say so and stop.
2. For EACH task file, start one subagent (Agent tool, model "sonnet") in ONE message so that all run in parallel.
   Give each subagent this prompt:
   "Read the task file <ABS_PATH>. Follow its `instructions` exactly, using its `payload`
    (and Read its `input_files` if any). Produce ONE JSON object that validates against its
    `output_schema`. Write it to runtime/agent_tasks/done/<task_id>.json with the Write tool.
    Write no other file. Do not modify the task file. Reply with 'done <task_id>' or 'failed <task_id>: <reason>'."
3. When all subagents finish, report: completed count, failed count, and the task ids.
   The running backend validates and applies the results automatically.
```

### 15.4 Task kinds — prompts and output schemas

Prompts live in `agents/prompts/<kind>.md` with a `prompt_version` line. Schemas live in `agents/schemas/<kind>.json`. Each prompt says: "You get column profiles, not full data. Return only JSON. Use `null` when not sure. Give a short reason for each choice."

**schema_mapper**
- Payload: `template_candidates` (top 3 templates with their fields, synonyms, descriptions), `profiles` (`ColumnProfile` list), `file_name`, `context`.
- Output:
```json
{"type":"object","additionalProperties":false,
 "required":["template_id","column_map","confidence","reasons"],
 "properties":{
   "template_id":{"type":["string","null"]},
   "column_map":{"type":"object","additionalProperties":{"type":["string","null"]}},
   "confidence":{"type":"number","minimum":0,"maximum":1},
   "reasons":{"type":"object","additionalProperties":{"type":"string"}}}}
```
- Validator: each mapped column's `validator_hits[field] ≥ 0.8`; all required fields are mapped; relations hold in ≥ 95% of rows; a field is used once (except repeatable). Then re-run classify with the map forced → confidence ≥ `map.agent_min`.

**new_source_modeler**
- Payload: profiles, file name, the list of generic templates (`vendor_credential`, `credential`, `person`, `pay_period`), the field catalogue.
- Output: the `schema_mapper` output + `"entity": string`, `"holder_type": "person" | "organization" | null`, `"proposed_template_id": string`.
- Validator: same as `schema_mapper`, against the selected generic template.

**page_reader**
- Payload: `page_image` (path in `input_files`), the expected header shape ("Staff, Role, 7 day columns"), the facility vocab, `legend_hint`.
- Output:
```json
{"type":"object","additionalProperties":false,"required":["title","header","rows","footnote"],
 "properties":{"title":{"type":"string"},"footnote":{"type":"string"},
   "header":{"type":"array","items":{"type":"string"}},
   "rows":{"type":"array","items":{"type":"array","items":{"type":["string","null"]}}}}}
```
- Validator: header width = row width for all rows; ≥ 90% of the day cells pass `shift_token_or_off`; ≥ 50% of the names resolve to a known person at `prob ≥ link.gray` (if HR is loaded). The rows get the locator `page=N` with no bbox. Their evidence says "read by agent from the page image".

**identity_adjudicator**
- Payload: the two records (`raw`, `person_key`, `fields`, template), the score breakdown, the other candidates in the block.
- Output: `{"decision": "same"|"different"|"unsure", "confidence": 0..1, "reason": string}`.
- Validator: `decision="same"` is accepted only if no cannot-link rule fails. Accepted "same" → `Link(method="agent", prob=max(prob, 0.95))`, flagged INFO `ID-AGENT-LINK` for human review. "unsure" → stays a gray pair.

**Cache key** = `sha256(kind | prompt_version | canonical_json(payload))`.

**Privacy.** Payloads hold column profiles (≤ 20 sample values per column), not full files. Only `page_reader` sends a full page image.

---

## 16. Pipeline orchestrator (`sot/pipeline/orchestrator.py`)

```python
async def run_ingest(paths: list[Path], run_id: str, bus: EventBus) -> RunSummary
async def rerun_from_table(table_id: str, bus: EventBus) -> None   # after agent results
async def rebuild_gold_and_checks(run_id: str, bus: EventBus) -> None
```

```
run_ingest
 ├─ for each file (asyncio.gather; CPU work in a ProcessPool):
 │    land (hash, copy to runtime/landing/<sha>.<ext>; skip if known → file.skipped)
 │    ① auction → file.sniffed | file.quarantined
 │    ② extract → table.extracted (per table; method, score, rows)
 │    ③ contract lookup / classify → table.mapped | table.drift | agent.task_created
 │    ④ build_silver (mapped tables only) → normalize.done
 ├─ anchors (all known dates) → second pass for weekday dates if needed
 ├─ ⑤ resolve_all → resolve.done ("N records → M people; K fuzzy; G gray")
 ├─ ⑥ claims + survivorship + gold → truth.done
 ├─ ⑦ checks → checks.done ("X issues: a CRITICAL, b HIGH ...")
 └─ run.completed (summary)
```

The order of files does not matter. Stage ④ for a schedule needs date anchors. If the schedule has no year and no other file is loaded yet, the weekday rule uses today as the anchor. Stages ⑤–⑦ always run after all files.

---

## 17. API and SSE events (`sot/api/`)

FastAPI on port 8000. The built front end is served from `/`. All API paths start with `/api`.

| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/api/ingest` | multipart `files[]` | `{run_id}` (work runs in a background task) |
| GET | `/api/runs` | | list of runs |
| GET | `/api/runs/{run_id}/events` | SSE | stream of `Event` (replays past events first, then live) |
| GET | `/api/summary` | | counts: files, tables, records, persons, issues by severity, agent tasks by status |
| GET | `/api/files` | | files with bids, parser, status, tables, mapping |
| GET | `/api/issues` | `severity, status, check_id, person_id, active=true` | list of issues (no evidence) |
| GET | `/api/issues/{fingerprint}` | | issue + evidence |
| PATCH | `/api/issues/{fingerprint}` | `{status, owner?, note?}` | updated issue |
| GET | `/api/evidence/crop` | `file_id, page, x0, top, x1, bottom, pad=40` | PNG + header `X-Highlight: x,y,w,h` (relative) |
| GET | `/api/people` | `q, facility, has_hr` | golden persons |
| GET | `/api/people/{person_id}` | | golden values + all claims (with conflicts) + links + records + credentials + shifts + issues |
| GET | `/api/shifts` | `start, end, facility` | grid data: persons × days with hours, token, license_valid flag |
| GET | `/api/credentials` | `horizon_days=90` | credentials with days_left, holder |
| GET | `/api/contracts` | | contracts |
| POST | `/api/contracts/{id}/approve` | | contract |
| GET | `/api/agent-tasks` | `status` | tasks |
| GET | `/api/exports/pbj.csv` | `quarter?` | CSV |
| GET | `/api/exports/issues.csv` | | CSV |
| GET | `/api/settings` / PUT | `{as_of}` | settings; PUT re-runs checks only |
| POST | `/api/reset` | | wipes runtime (demo only; needs `SOT_ALLOW_RESET=1`) |

**SSE format:** `event: <type>` and `data: <Event JSON>`. The front end uses `EventSource`. The bus keeps all events in DuckDB, so a page reload replays them.

**Evidence crop (`evidence.py`):** PyMuPDF opens the landed PDF, `clip = bbox ± pad`, `page.get_pixmap(clip=clip, dpi=144)`. The response includes the highlight rectangle relative to the crop. The front end draws the highlight with an absolutely positioned div.

---

## 18. Front end (`frontend/`)

```
frontend/src/
├── main.tsx  App.tsx  router.tsx
├── api/client.ts          fetch wrappers + EventSource helper
├── api/types.ts           TS mirrors of the pydantic models (hand-written, same names)
├── mock/                  JSON fixtures for every endpoint (VITE_MOCK=1)
├── components/
│   ├── SeverityBadge.tsx  StatusPill.tsx  ConfidenceBar.tsx
│   ├── EvidenceChain.tsx  PdfCrop.tsx  ClaimTable.tsx  LinkReasons.tsx
│   └── PipelineFeed.tsx   (live events grouped by file)
└── pages/
    ├── Ingest.tsx         drop zone (multi-file) + PipelineFeed + summary tiles
    ├── Issues.tsx         left: filterable list grouped by severity; right: EvidenceChain + actions
    ├── People.tsx         table of golden persons; drawer: fields with source chips, conflicts in red, links with reasons
    ├── Shifts.tsx         grid persons × days per facility; cell = token + hours; red if license not valid that day; RN coverage row per day
    ├── Credentials.tsx    expiry horizon: overdue / ≤30 / ≤60 / ≤90 buckets; persons and organizations
    ├── Exports.tsx        PBJ preview table (status filter) + download buttons
    └── Contracts.tsx      contracts + agent tasks; approve button; JSON preview of column_map
```

**UI rules**
- The header shows the as-of date picker and live counts (CRITICAL / HIGH).
- Each issue card shows: severity, title, person or facility, period, and evidence count. The evidence panel shows each `EvidenceItem` in order. A `cell` item with a bbox shows `PdfCrop`; a CSV cell shows the source row as a mini table with the column highlighted.
- The pipeline feed shows for each file: the winning parser and score (expand → all bids), each table (method, score, rows), the mapping chips (`column → field` with a confidence color), and agent states (`waiting for agent` → `validator OK` / `rejected`).
- Colors: CRITICAL red, HIGH orange, MEDIUM amber, LOW slate, INFO blue. Dark mode is not required.
- Polling: none. SSE drives the Ingest page. Other pages refetch on the `run.completed` and `agent.task_accepted` events (a small global event context).

---

## 19. Synthetic data, chaos suite, tests (`backend/tools/synth/`, `backend/tests/`)

### 19.1 Generator (`generator.py`)

```python
def generate_world(seed: int, n_staff: int = 40, weeks: int = 2, start: date = date(2026, 9, 14)) -> World
def plant_defects(world: World, catalog: list[str], seed: int) -> tuple[World, list[ExpectedIssue]]
def write_world(world: World, out_dir: Path, variant: RenderVariant) -> None
```

The world has staff with roles (RN 30%, LPN 15%, CNA 55%), home facilities, licenses, schedules that satisfy the RN rule by default, and payroll equal to the scheduled hours.

**Defect catalogue** (each defect writes an `ExpectedIssue{check_id, employee_ids, note}`):
`nickname_on_schedule`, `last_first_in_payroll` (always on), `typo_family_name`, `maiden_name_on_license`, `worked_after_expiry`, `expiring_in_20_days`, `hr_vs_license_expiry_conflict`, `paid_vs_scheduled_delta`, `payroll_person_not_in_hr`, `schedule_person_not_in_hr`, `duplicate_license_number`, `cna_on_rn_shift`, `float_to_other_facility`, `overlapping_shifts_two_facilities`, `missing_rn_day`, `legend_mismatch_token`, `bad_date_value`, `ambiguous_date_column`, `phone_format_mix`, `hr_duplicate_row`, `whitespace_case_noise`, `two_people_same_family_name` (must **not** merge).

### 19.2 Renderers (`render.py`)

CSV writer (README column names), XLSX writer, and a PDF writer (reportlab) with these variants: `grid`, `nogrid`, `wrapped_names`, `landscape`, `two_tables_one_page`, `raster_150dpi` (render the PDF and rebuild it as an image-only PDF with PyMuPDF).

### 19.3 Mutators (`mutators.py`)

```python
MUTATORS: dict[str, Callable[[Path, random.Random], Path]]
```
`rename_headers_synonyms`, `reorder_columns`, `delimiter_semicolon`, `delimiter_tab`, `encoding_latin1_bom`, `date_format_us_slash`, `date_format_dmy_unambiguous`, `to_xlsx`, `title_rows_above_header`, `extra_unknown_columns`, `trailing_blank_rows`, `quote_all`, `upper_case_names`, `drop_optional_column`.

### 19.4 Chaos runner (`chaos.py`)

```bash
python -m tools.synth.chaos --n 50 --seed 7 --out runtime/chaos
```
For each variant: generate → mutate (1–3 random mutators per file) → run the pipeline in-process (agents `off`) → compare.
- **Golden equality:** the persons and credentials tables equal the baseline (ignore ids).
- **Defect recall:** expected issues found / expected (match by check_id + employee_ids).
- **Precision:** issues that match a planted defect / all issues of the checked kinds.
- Output: `runtime/chaos/report.md` + `report.json`. The demo shows the summary line.

### 19.5 Tests

| File | Covers |
|---|---|
| `test_auction.py` | Each parser wins on its format; CSV with `;`, tab, BOM, latin-1; XLSX named `.csv`; quarantine of a random binary |
| `test_header_detect.py` | Title rows, blank rows, duplicate headers |
| `test_pdf_cascade.py` | Each PDF variant → expected cells (≥ 98% cell accuracy for text PDFs) |
| `test_legend_shifts.py` | Legend parsing; `11p-7a` = 8 h; `7a-7p` = 12 h; 24 h tokens; unknown token |
| `test_mapper.py` | README headers; mangled headers (`Emp, Cls, Site, Wk Beg, Wk End, Hrs, Ref`); swapped dates fixed by relation; value gate |
| `test_dates.py` | Column inference; ambiguous column; weekday year inference (Mon 09/14 → 2026) |
| `test_names.py` | `LAST, FIRST`; particles; suffixes; initials; accents; nickname match |
| `test_resolve.py` | E1 example → 2 persons; two Bells not merged; maiden name linked by license; cannot-link stops a chain merge; gray pair → task |
| `test_survivorship.py` | License service wins; conflict flagged |
| `test_checks.py` | E1 example → exactly the 5 issues of PLAN §10 Step 8 (by check id) |
| `test_pbj.py` | E1 example → PBJ rows and statuses of PLAN §10 Step 9 |
| `test_idempotent.py` | Ingest twice → same row counts, same fingerprints, statuses kept |
| `test_agents.py` | Queue round trip with a fake done file; schema reject; validator reject; cache hit; `off` executor |
| `test_api.py` | Ingest via TestClient; SSE replay; issue PATCH |

---

## 20. Work packages

Rules for every builder:
- Import shared types from `sot.core.models`. Do not redefine them.
- Write only in the folders listed for your WP. Put the tests for your WP in `backend/tests/test_<area>.py`.
- Each public function has a docstring and type hints. No network calls in tests.
- Finish = all acceptance tests pass (`pytest -q backend/tests/test_<area>.py`).

| WP | Owner | Folders | Depends on | Acceptance |
|---|---|---|---|---|
| **WP0 Contracts** | Opus | `sot/core/*`, `sot/config.py`, `sot/store/*`, `pyproject.toml`, `Makefile`, pack skeleton (`pack.yaml`, `fields.yaml`, `templates.yaml`, vocab, `settings.yaml`), fixtures `readme_sample` + `example_e1` (CSV parts) | — | `python -c "import sot.core.models"`; DB init creates all tables; pack loads into a typed `Pack` |
| **WP-S Synthetic + chaos** | Sonnet | `tools/synth/*`, `tests/fixtures/example_e1/schedule.pdf` | WP0 models | Generator writes 4 files + `expected_issues.json`; 6 PDF variants render; each mutator runs on the README sample |
| **WP-P PDF spike → cascade** | Sonnet | `parsers/pdf/*`, `normalize/shifts.py`, `tests/test_pdf_cascade.py`, `tests/test_legend_shifts.py` | WP0, WP-S PDFs | Cell accuracy table for the 6 variants (written to `docs/pdf_spike.md`); text variants ≥ 98% |
| **WP1 Sniff + tabular parsers** | Sonnet | `sniff/*`, `parsers/base.py`, `parsers/csv_parser.py`, `parsers/xlsx_parser.py`, `parsers/json_parser.py` | WP0 | `test_auction.py`, `test_header_detect.py` |
| **WP2 Semantic** | Sonnet | `semantic/*`, `normalize/dates.py`, `normalize/vocab.py` | WP0 | `test_mapper.py`, `test_dates.py` |
| **WP3 Normalize + resolve** | Sonnet | `normalize/names.py`, `normalize/phones.py`, `normalize/silver.py`, `resolve/*`, `packs/*/resolution.yaml`, `vocab/nicknames.csv` | WP0 | `test_names.py`, `test_resolve.py` |
| **WP4 Truth + checks + exports** | Sonnet | `truth/*`, `checks/*`, `exports/*`, `packs/*/checks/*`, `packs/*/survivorship.yaml`, `packs/*/exports/*` | WP0 (works on hand-made silver rows) | `test_survivorship.py`, `test_checks.py`, `test_pbj.py` |
| **WP5 Agents + API + orchestrator** | Sonnet | `agents/*`, `pipeline/*`, `api/*`, `.claude/commands/process-agent-tasks.md` | WP0 (stubs for stages until integration) | `test_agents.py`, `test_api.py` (with stage stubs) |
| **WP6 Front end** | Sonnet | `frontend/*` | §17 API table + mock JSON | `npm run build` passes; all pages render with `VITE_MOCK=1`; screenshots of the 7 pages |
| **WP7 Integration** | Opus | glue + fixes in any folder | all | `test_checks.py` and `test_pbj.py` pass through the **real** pipeline on `example_e1`; `test_idempotent.py`; chaos report; end-to-end demo in the browser |

**Interface stubs.** WP0 also writes empty function stubs (signatures from this document that raise `NotImplementedError`) in each module. Each WP replaces its own stubs. Thus, WP5 can wire the orchestrator before the stages are complete.

---

## 21. Timeline (3.5 hours)

```
0:00 ─ 0:30  WP0 (Opus): models, DB, pack skeleton, stubs, fixtures.
             In parallel from 0:05: WP-S (generator + PDF variants), WP6 starts on mock JSON.
0:30 ─ 0:50  WP-P spike: run the cascade on the 6 PDFs → fix order/threshold (weakest-assumption test).
0:30 ─ 2:00  WP1, WP2, WP3, WP4, WP5 in parallel (Sonnet ×5). WP-P continues to the full cascade. WP6 continues.
2:00 ─ 2:45  WP7 (Opus): integrate stages, run example_e1 end to end, fix, run the chaos suite, fix.
2:45 ─ 3:10  UI against the real API, evidence crops, agent queue demo with vendor_docs.csv, warm the agent cache.
3:10 ─ 3:30  DECISIONS.md, demo rehearsal (2 full runs), `make reset`.
```

Checkpoints: at 1:15, each WP posts a status (tests passing / blocked). At 2:00, a feature freeze for the stages. After 2:45, only fixes.

---

## 22. Demo script (≈ 5 minutes)

1. **(0:00)** `make demo` → browser on the Ingest page. Say: "The system does not know these files. It decides the format and the meaning by itself."
2. **(0:20)** Drop the four judge files. Narrate the feed: parser auction scores, the PDF method per page, the mapping chips, "N records → M people".
3. **(1:00)** Issues page. Open the top CRITICAL issue. Show the PDF crop of the shift cell, the identity reasons, and the golden vs not-golden license claims.
4. **(1:45)** Shifts page. Red cells = shifts without a valid license. The RN coverage row.
5. **(2:15)** Exports → PBJ preview: `ready` vs `needs sign-off`. "The quarter is 13 of these runs. Only the sign-off rows need a human."
6. **(2:45)** Robustness: drop a mangled payroll (XLSX, renamed headers, title rows) → "schema drift, contract v2", same golden data. Show the chaos report line ("50 variants, recall X%, precision Y%").
7. **(3:30)** Reuse: drop `vendor_docs.csv` → "waiting for agent" → run `/process-agent-tasks` in Claude Code → "validator OK" → a vendor certificate expiry issue appears. "A new client in a different industry is a new pack, not new code."
8. **(4:15)** Credentials page: the 30/60/90-day horizon. Close with the three business problems (PLAN §8 B.6).

---

## 23. Risks and fallbacks

| Risk | Sign | Fallback |
|---|---|---|
| The judge PDF has an unusual layout | Cascade score < 0.8 on all methods | `pdf.words` method + low-confidence issue; PageReader agent on the page image; worst case: the UI shows the extracted grid for a quick human fix (stretch) |
| The judge PDF is a scan | `chars_per_page < 20` | PdfScanParser → PageReader tasks → `/process-agent-tasks` |
| Many false fuzzy merges | Chaos precision drops; `ID-CONFLICT` issues | Raise `link.auto` to 0.97; the cannot-link rules stay |
| Names have no family match at all (e.g. initials only) | Many `SCHED-NO-HR` | Gray-zone agent; the role + facility + shift date overlap with payroll as extra evidence (stretch weight) |
| `claude` is not available at judging | Executor errors | `SOT_AGENTS=off` → "needs human" issues; cached results still apply |
| DuckDB lock errors under the API | Errors in the logs | One writer task with a queue; readers use a read-only connection |
| Time overrun | Checkpoint at 1:15 shows red | Cut order: JSON parser → PBJ XML → Contracts page edit → calibration → SHIFT-OVERLAP. Never cut: auction, mapper, resolver, checks of §10, evidence crop |

---

## 24. Submission — `DECISIONS.md` (outline)

1. What we built (one paragraph + the architecture diagram).
2. Key decisions and why:
   - parser auction instead of extension routing
   - value-signature mapping with the Hungarian algorithm instead of fixed headers
   - mapping contracts and drift detection
   - probabilistic entity resolution with blocking and cannot-link rules
   - claims with provenance and field-level survivorship
   - shift-date license validity
   - checks as pack SQL
   - AI only for the low-confidence remainder, behind validators
   - DuckDB for single-machine scale
3. What the system flags at ingest (the check catalogue).
4. How it helps with each business problem (grounded: names of tables, checks, exports).
5. Reuse for another industry (what a new pack contains).
6. Limits and next steps (referral feed, PBJ XML, human correction UI, incremental resolve, scheduled ingest with the `claude -p` executor).
