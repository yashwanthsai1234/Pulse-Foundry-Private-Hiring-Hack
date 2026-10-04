# Task Graph and Dependency Graph

Read with `docs/PLAN.md` (what and why) and `docs/IMPLEMENTATION.md` (detailed spec).
**This file overrides IMPLEMENTATION.md where they differ** (it records the decisions taken during WP0).

## 1. Dependency graph (modules)

```
                         sot/core/models.py  sot/core/pack.py  sot/config.py  sot/store/{db,repo}.py   ◄── WP0 (DONE)
                                   │
   ┌──────────────┬───────────────┼────────────────┬──────────────┬───────────────┬──────────────┐
   ▼              ▼               ▼                ▼              ▼               ▼              ▼
 A1 sniff +     A2 pdf/*       A3 semantic/*    A4 names,      A5 truth/*      A6 agents/*    A8 tools/synth
 parsers/base   normalize/     normalize/       phones,        checks/*        pipeline/*     generator,
 csv/xlsx/json  shifts.py      dates,vocab      resolve/*      exports/*       api/*          mutators, chaos
   │              │               │                │              │               │              │
   └──────────────┴───────┬───────┴────────────────┘              │               │              │
                          ▼                                       │               │              │
                 W2 normalize/silver.py  ─────────────────────────┴───────────────┤              │
                          │                                                       ▼              │
                          └──────────────────────────────► W2 INTEGRATION (orchestrator wiring) ◄┘
                                                                  │
 A7 frontend (mock API) ──────────────────────────────────────────┤
                                                                  ▼
                                  W3 breakers (4 agents) → W4 fix fleet → W5 verify, A/B, live panel
```

## 2. Task graph (waves)

| Wave | Task | Owner | Blocks |
|---|---|---|---|
| W0 | Contracts, DB, pack, fixtures, renderer (grid/nogrid) | Opus | everything |
| W1 | A1 Sniff + tabular parsers | Sonnet | W2 |
| W1 | A2 PDF cascade + shift grammar + legend + PDF spike report | Sonnet | W2 |
| W1 | A3 Semantic mapping + dates + vocab | Sonnet | W2 |
| W1 | A4 Names + phones + resolver | Sonnet | W2 |
| W1 | A5 Truth + checks + exports | Sonnet | W2 |
| W1 | A6 Agent gateway + pipeline skeleton + API | Sonnet | W2 |
| W1 | A7 Front end on mocks | Sonnet | W2 UI wiring |
| W1 | A8 Synthetic generator + PDF variants + mutators + chaos runner | Sonnet | W3 |
| W2 | silver.py + integration + E2E (example_e1 through the real pipeline) | Opus (+ Sonnet helpers) | W3 |
| W3 | Breakers: wiring audit · edge-case attack · real-world files from the internet · simplicity/dead-code audit | 4 × Sonnet | W4 |
| W4 | Fix fleet (one agent per area with findings) | Sonnet | W5 |
| W5 | Verification, A/B tests, live panel tests, DECISIONS.md | Opus | — |

## 3. Rules for every agent (non-negotiable)

1. **Own your files.** Write only the files listed for your task (plus your own `backend/tests/test_<area>*.py` and `docs/research/<task>.md`). Do not edit `sot/core/*`, `sot/config.py`, `sot/store/*`, `tests/conftest.py`, `pyproject.toml`, or another agent's files. If a shared contract is wrong, say so in your final report — do not work around it silently.
2. **TDD (Karpathy style: think → test → implement).** Before writing code, write the tests from the spec and the fixtures. Run them and see them fail. Then implement the simplest code that passes. Then refactor.
3. **Evidence before proposals.** If you want to deviate from the spec or choose between approaches, run a quick experiment in the scratchpad (or a throw-away test) and record the numbers in `docs/research/<task>.md`.
4. **Research and cite.** Use WebSearch/WebFetch to check library APIs and better approaches (library docs, papers, well-known implementations). Every module docstring ends with a `Sources:` list of the URLs you relied on. Also list them in `docs/research/<task>.md` with one line on what each source decided.
5. **Simplicity.** Prefer 50 clear lines over 200 clever ones. No dead code, no unused params, no speculative abstraction, no commented-out code. Reuse the shared helpers in `sot/core` and `sot/store/repo.py`.
6. **No git commands.** No network calls inside tests.
7. **Run tests with** `cd backend && .venv/bin/python -m pytest -q tests/<your tests>`. Do not run `uv sync`. If a new dependency is unavoidable, run `cd backend && uv add <pkg>` once and report it.
8. **Import PyMuPDF as `import pymupdf`** (`fitz` is deprecated).
9. **Final report** (your last message): files written, tests (count, all passing?), deviations from the spec with evidence, open problems, contract issues.

## 4. Stage interfaces (exact signatures — the integration contract)

Field value conventions in `SourceRecord.fields`: dates → ISO `str`; numbers → `float`; vocab fields → code (`"RN"`, `"FAC-BAY"`); `credential.number` → upper case, spaces removed (`"RN-551203"`); `person.full_name` → the display text as in the source; `person.employee_id` → upper-case string.

```python
# A1 — sot/parsers/base.py
def detect_header_row(rows: list[list[str | None]], max_scan: int = 20) -> int
def build_raw_table(file: FileRef, parser: str, header: list[str], rows: list[list[str | None]],
                    src_rows: list[int], *, method: str, score: float, index: int = 0,
                    page: int | None = None, sheet: str | None = None, context: dict[str, str] | None = None,
                    cell_bboxes: dict[str, BBox] | None = None) -> RawTable
    # cleans: strips cells, drops empty rows/cols, uniquifies headers, builds Utf8 df + "_src_row"
# A1 — sot/sniff/auction.py
def run_auction(file: FileRef, parsers: list[Parser], min_score: float) -> AuctionResult
# A1 — parsers (each a class decorated with @register_parser; `name` ClassVar):
#   csv_parser.CsvParser.name = "csv"; xlsx_parser.XlsxParser.name = "xlsx"; json_parser.JsonParser.name = "json"
#   sniff(head: bytes, path: Path) -> SniffResult ; extract(file: FileRef, ctx: ExtractContext) -> list[RawTable]
#   ctx.sniff_details is the winning SniffResult.details (e.g. {"delimiter": ";", "encoding": "latin-1"})

# A2 — sot/normalize/shifts.py
@dataclass(frozen=True)
class ShiftToken: start: time | None; end: time | None; hours: float | None; off: bool; tag: str | None; note: str | None
def parse_shift_token(text: str) -> ShiftToken | None          # None = not recognized
# A2 — sot/parsers/pdf/legend.py
def parse_legend(text: str) -> dict[str, float]               # {"7a-3p": 8.0, ...}; keys = canonical token text
# A2 — parsers: pdf/text_parser.PdfTextParser.name = "pdf_text"; pdf/scan_parser.PdfScanParser.name = "pdf_scan"
#   PdfTextParser.extract -> one RawTable per page table. context keys: "title", "footnote", "facility_hint"
#   (raw title text; A2 does NOT map it to a code), "legend_json" (json of parse_legend), "page_text".
#   header = the table's header row verbatim; cell_bboxes for every cell; page = 1-based.
#   PdfScanParser.extract renders pages to PNG under settings.dir("agent_tasks/files") and, if ctx.submit_task
#   is set, submits one "page_reader" task per page (payload: {"image": path, "page": n}); returns [].

# A3 — sot/semantic/validators.py
def build_validators(pack: Pack) -> dict[str, Callable[[str], bool]]
# A3 — sot/semantic/profile.py
def profile_table(t: RawTable, validators: dict[str, Callable[[str], bool]], sample_rows: int = 2000) -> list[ColumnProfile]
# A3 — sot/semantic/mapper.py
def assign(profiles: list[ColumnProfile], fields: list[FieldSpec], no_field_score: float) -> list[FieldMatch]
# A3 — sot/semantic/classify.py
def classify(t: RawTable, profiles: list[ColumnProfile], pack: Pack, settings: Settings,
             forced: dict[str, str] | None = None) -> Mapping      # forced = column->field map from an agent
# A3 — sot/semantic/contracts.py
def header_fingerprint(header: list[str]) -> str
def map_table(t: RawTable, db: DB, pack: Pack, settings: Settings) -> Mapping   # contract → classify → drift; saves contract
def save_contract(db: DB, m: Mapping, t: RawTable, source: str) -> Contract
def approve_contract(db: DB, contract_id: str) -> None
# A3 — sot/normalize/dates.py
def infer_column_date_format(values: list[str]) -> tuple[str | None, bool]   # (format, ambiguous)
def parse_date(value: str, fmt: str | None = None) -> date | None
def resolve_weekday_date(dow: str, month: int, day: int, anchors: list[date]) -> date | None
def date_anchors(records: list[SourceRecord]) -> list[date]
# A3 — sot/normalize/vocab.py
def normalize_vocab(value: str, vocab: Vocab) -> tuple[str | None, bool]      # (code, fuzzy)

# A4 — sot/normalize/names.py
def parse_person_name(text: str, nick: dict[str, str]) -> PersonKey
def person_key_from_parts(given: str | None, family: str | None, nick: dict[str, str]) -> PersonKey
def compare_given(a: PersonKey, b: PersonKey) -> Literal["exact", "nickname", "fuzzy", "initial", "disagree", "unknown"]
# A4 — sot/normalize/phones.py
def normalize_phone(text: str) -> str | None
# A4 — sot/resolve/resolver.py
@dataclass
class ResolveResult: persons: list[Person]; links: list[Link]; drafts: list[IssueDraft]; gray_pairs: list[Link]
def resolve_all(records: list[SourceRecord], pack: Pack, settings: Settings,
                extra_links: list[Link] = ()) -> ResolveResult  # extra_links = accepted agent/human links

# A5 — sot/truth/claims.py
def build_claims(records: list[SourceRecord], persons: list[Person]) -> list[Claim]
# A5 — sot/truth/survivorship.py
def survive(claims: list[Claim], pack: Pack) -> tuple[list[GoldenValue], list[IssueDraft]]
# A5 — sot/truth/gold.py
def write_gold(db: DB, records: list[SourceRecord], shifts: list[ShiftRecord], persons: list[Person],
               links: list[Link], claims: list[Claim], golden: list[GoldenValue]) -> None
# A5 — sot/checks/engine.py
def run_checks(db: DB, pack: Pack, settings: Settings, run_id: str, extra_drafts: list[IssueDraft]) -> list[Issue]
# A5 — sot/checks/builtin.py
def builtin_drafts(records: list[SourceRecord], links: list[Link]) -> list[IssueDraft]   # PARSE-* from parse_issues, ID-FUZZY-LINK, LEGEND-MISMATCH
# A5 — sot/exports/pbj.py, issues_csv.py
def build_pbj(db: DB, pack: Pack, settings: Settings) -> pl.DataFrame
def issues_csv(db: DB) -> str

# A6 — sot/agents/gateway.py
class AgentGateway:
    def __init__(self, db: DB, settings: Settings, bus: EventBus): ...
    on_accept: Callable[[AgentTask, dict], None] | None          # set by the pipeline
    def make_task(self, kind: AgentKind, run_id: str, ref: str, payload: dict, input_files: list[str] = ()) -> AgentTask
    def submit(self, task: AgentTask) -> dict | None              # cache hit -> output (also calls on_accept)
    def poll(self) -> list[AgentResult]                           # read done/, schema + validator, accept/reject
# A6 — sot/agents/validators.py
def validate(task: AgentTask, output: dict, ctx: "ValidationContext") -> tuple[bool, list[str]]
# A6 — sot/pipeline/orchestrator.py
class Pipeline:
    def __init__(self, settings: Settings, db: DB | None = None, bus: EventBus | None = None): ...
    def ingest(self, paths: list[Path], run_id: str | None = None) -> RunSummary   # synchronous
    def rebuild(self, run_id: str) -> RunSummary                                    # stages 5-7 only
# A6 — sot/api/app.py
def create_app(settings: Settings | None = None) -> FastAPI
```

## 5. Decisions taken in WP0 (differences from IMPLEMENTATION.md)

- `IssueDraft.evidence_refs: dict` added: checks put raw ids there; the engine's enricher turns them into `EvidenceItem`s.
- `AgentTask.output_path` added (absolute path of `done/<task_id>.json`).
- `RunSummary` model added.
- `credential.doc_type` field added (vendor paperwork type; `credential.type` stays tied to the roles vocab).
- Vocab files use `codes:` / `names:` / `scope:` keys. Aliases are lower-case; the code itself is always an alias.
- Gold tables are cleared with `DB.clear_gold()` and re-inserted on each rebuild.
- Pipeline is synchronous; the API runs it in a worker thread. The `EventBus` must deliver to asyncio subscribers thread-safely (A6 owns this change in `sot/core/events.py`).
- Person ids: `P-<employee_id>` (e.g. `P-E202`).

## 6. Wave 4 — fix fleet (ownership + contracts)

Findings live in `docs/breakdowns/B1.md` (wiring), `B2.md` (edge cases), `B3.md` (real-world files), `B4.md` (chaos root causes RC1–RC18 + simplicity S1–S10), and `docs/BREAKDOWNS.md` (B-001…B-020). Failing tests that prove them: `backend/tests/breakers/`. **A finding is fixed only when its breaker test passes** (if a breaker test asserts something wrong, fix the test and explain why in your report). Rules of §3 still apply (TDD, research + cite, simplicity, no git, own files only).

| Agent | Owns (write only these) | Findings to fix |
|---|---|---|
| FX1 ingest | `sot/sniff/*`, `sot/parsers/**`, `sot/normalize/shifts.py`, `tools/synth/render.py` | B3-01 (score must check row completeness — no false 1.00), B3-05, B3-10, RC4 (validate UTF-8 after BOM, else cp1252), RC6/B-004 (header detection), RC10 (continued table inherits title/facility), B2-10 (drop rows equal to the header), B2-09 (double shift `7a-3p/3p-11p` → one token, hours summed, note "double"), letter-code legends (`D = 7a-3p`) via new `parse_legend_codes(text) -> dict[str, str]` in `legend.py`, B2-04 (consistent header+1 ragged rows from an unquoted `LAST, FIRST` → merge back, with evidence), S5, S7-like dupes in parsers, A1 B-005 (large CSV) only if ≤ 20 lines |
| FX2 semantic | `sot/semantic/*`, `sot/normalize/{dates.py,vocab.py}`, `packs/healthcare_snf/{fields.yaml,templates.yaml}` | B3-03/B3-07 (confidence × share of columns explained; min sample size), B3-06/RC5 (Unicode names; no token-subset 100s), B2-05 (hr_roster with one full-name column: support `one_of` groups in templates), B2-06 + B2-13 (date styles: `31.05.2027`, ISO datetime, `May 31, 2027`, `31 May 2027`, `20270531`; per-value fallback when the column format fails), B2-03 (schedule.day header_pattern also accepts `09/14`, `9/14/2026`, `2026-09-14`, `Mon\n09/14`, `Monday 14 Sep`), B2-17 (generic "Nurse" must not map to RN), B-001, B-002, RC3, B1-06 (agent contract reuse; validator-less fields), B1-07 (vendor policy numbers: separate loose `credential.policy_number` field for vendor_credential), S10 (one shared text normaliser) |
| FX3 resolve | `sot/normalize/{names.py,phones.py}`, `sot/resolve/*`, `packs/healthcare_snf/{resolution.yaml,vocab/nicknames.csv}` | B2-08 (keep `PersonKey.suffix`; suffix mismatch = cannot-link), B2-14/RC8 (kate, rick, sue, debbie + the 13 pairs), B2-15/RC9 (compound surnames, one-letter family typos → block + gray pair), B2-16 (strip parenthetical notes "(float)"), B3-09 (curly apostrophe, Ł ø đ ß folding), B2-21 (dedupe ID-CONFLICT), records without person_key and without ids are ignored (no crash), license hard-key on canonical form (see contract below) |
| FX4 truth/checks | `sot/truth/*`, `sot/checks/*`, `sot/exports/*`, `packs/healthcare_snf/{checks/*,survivorship.yaml,exports/*}` | RC1/B-009/B-019 (ID-FUZZY-LINK: one issue per fuzzy record, entity = person id, readable message), RC2/B-007 + contract below, RC11 (LEGEND-MISMATCH once per table+token), B2-01 + RC7 (no duplicate-key crashes: dedupe before insert; PAY-DUPLICATE / HR-DUP-ROW issues), B2-02 (gold never KeyErrors on missing fields), B1-04 (same shift / pay period from two files counted once; newest file wins), B2-11 (PAY-DUPLICATE, PAY-PERIOD-OVERLAP, PAY-PERIOD-INVALID), B2-12 (PAY-HOURS-INVALID for < 0 or > 100/week, blank), B2-13 (LIC-EXPIRY-MISSING HIGH), B2-18 (HR-HIRE-DATE: future, or after first pay/shift), B2-19 (LIC-TYPE-MISMATCH: number prefix vs type), B2-17 (unknown facility/role = MEDIUM), B-006 (claims observed_at from `files.received_at`: `build_claims(records, persons, file_times: dict[str, datetime] = {})`), B1-11 (raw + loc.col on CSV evidence), RC15 (stable tie-break), S4 |
| FX5 pipeline/API/agents | `sot/pipeline/*`, `sot/api/*`, `sot/agents/**`, `sot/core/events.py`, `.claude/commands/process-agent-tasks.md`, `Makefile`, root `.gitignore` | B1-01 (SPA fallback), B1-02 (agent events after run.completed reach the UI: a global `/api/events` SSE stream), B1-03/B3-08 (schedule before HR: rebuild schedule silver when anchors appear; fall back to settings.as_of + PARSE-SCHEDULE-DATES issue), B1-05, B1-09, B1-10, B1-12, B1-13, B1-14, B1-15, B1-16…B1-20, B3-02/B3-04/B-012 (low PDF score → PARSE-PDF-LOW-CONFIDENCE; < 0.5 or zero tables on a schedule-looking page → page_reader task), B-013, B-014 (task expiry), B-016, B-017, B-020, S2, S6 |
| FX6 front end | `frontend/**` | B1-02 client side (listen to the global stream; refetch on agent events), B1-10 chip, B1-11 column highlight, any UI defect B1 lists |
| FX7 synth/chaos | `tools/synth/{generator.py,mutators.py,chaos.py}` | RC13, RC14, RC16, RC17 (fake page_reader agent in chaos or drop raster expectations), RC18, S8, S9 (move test-only helpers to tests) |
| Opus | `sot/core/*`, `sot/store/*`, `sot/config.py`, `sot/normalize/silver.py` | B1-08/B2-20 bulk insert (DONE), PersonKey.suffix (DONE), silver: canonical license numbers, decimal-comma hours, RC12 decision, day headers without weekday, totals/incomplete rows, letter-code legends, double shifts, S1 (JSON decode once), S3 |

### Contract: parse-issue kinds (silver → builtin checks)

| silver emits (`kind:detail`) | check id | severity |
|---|---|---|
| `bad_date:<field>` | PARSE-DATE | MEDIUM (HIGH if field is `credential.expires_on`) |
| `date_ambiguous:<field>` | PARSE-DATE-AMBIGUOUS | MEDIUM |
| `bad_number:<field>` | PARSE-NUMBER | MEDIUM |
| `unknown_vocab:<field>` | PARSE-UNKNOWN-VALUE | MEDIUM |
| `vocab_fuzzy:<field>` | PARSE-FUZZY-VALUE | INFO |
| `bad_phone:<field>` | PARSE-PHONE | LOW |
| `shift_token:<text>` | PARSE-SHIFT-TOKEN | MEDIUM |
| `legend_mismatch:<token>` | LEGEND-MISMATCH | MEDIUM (one per table + token) |
| `row_incomplete:<missing fields>` | ROW-INCOMPLETE | MEDIUM (record kept, excluded from gold facts it cannot support) |
| `schedule_dates:<header>` | PARSE-SCHEDULE-DATES | HIGH |
| `day_mismatch:<header>` | PARSE-DATE-WEEKDAY | MEDIUM |

### Contract: canonical license numbers

`silver` writes `credential.number` as `PREFIX-DIGITS` when the value is letters + optional separators + digits (`RN551203`, `rn 551203`, `RN–551203`, `RN_551203` → `RN-551203`); otherwise upper case with whitespace removed. Resolver and claims compare this canonical form.

### Decision RC12 (shift hours)

Hours come from the shift times. The footnote legend is used only when the cell has no times (letter codes) and as a cross-check: a disagreement makes LEGEND-MISMATCH. Evidence: B4 RC12 (trusting a wrong legend → 82–118 false HRS-PAID-VS-SCHED per 30 worlds); README legend equals the computed hours.
