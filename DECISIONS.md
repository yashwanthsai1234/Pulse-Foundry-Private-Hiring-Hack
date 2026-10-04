# Harborview Source of Truth — Key Decisions

**What it is.** A source of truth that ingests whatever files a business hands over (CSV, XLSX, JSON, text PDFs, scanned PDFs), works out by itself what each file is and what each column means, resolves who is who across systems, keeps every value with its origin, and surfaces everything that is wrong, inconsistent or needs a human — with evidence down to the cell of the printed schedule. Healthcare knowledge lives in a replaceable **domain pack**; the engine knows no domain.

```
upload ─► ① parser auction ─► ② extract (tables + cell locators) ─► ③ profile + map (Hungarian) ─► ④ normalize
        ─► ⑤ resolve identities ─► ⑥ claims + survivorship ─► ⑦ checks ─► ⑧ UI · PBJ export · issues
                         low confidence anywhere ─► agent task queue ─► Claude Code Sonnet subagents ─► validators
```

Run it: `make dev` (API + UI on :8000, after `cd frontend && npm i && npm run build`), drop files on the Ingest page. Agent tasks: run `/process-agent-tasks` in Claude Code. Tests: `make test` (771 backend + 24 front-end tests). Design docs: `docs/PLAN.md`, `docs/IMPLEMENTATION.md`, `docs/TASKGRAPH.md`.

## Decisions and why

| # | Decision | Why (evidence) |
|---|---|---|
| 1 | **Parser auction on the bytes**, not the file extension. Each parser scores the file; the best bid wins; < 0.5 → quarantine with an issue. | Judges' files are unseen. An XLSX named `.csv`, a latin-1 file behind a UTF-8 BOM, `;`/tab delimiters, title rows — all handled (`tests/test_auction.py`, breaker suite). A new format = one new parser class. |
| 2 | **Columns are mapped by meaning, not by name**: header similarity + value signatures (license patterns, `LAST, FIRST`, dates, vocabularies) + type, solved jointly with the **Hungarian algorithm**; a value gate stops a good header from winning on bad values. | A/B (`docs/ab/AB_TESTS.md`): on 30 mutated files the combined score maps 100 % of columns vs 94.3 % header-only and 98.1 % value-only. Renamed/reordered headers (`Emp, Cls, Site, Wk Beg, Hrs`) map with no agent. |
| 3 | **Mapping contracts + drift detection.** Accepted mappings are saved; a changed header shape is reported as drift; a second legitimate source is not. | Recurring weekly ingests must not re-guess; humans approve contracts in the UI. |
| 4 | **PDF cascade ordered by measurement**: ruled grid → PyMuPDF tables → word clustering → pdfplumber text; the score multiplies cell validity by **page completeness**, so a partial table cannot score 1.00; low score → page sent to an agent. | Weakest assumption of the project ("the PDF yields a clean table"). Spike + A/B on 21 synthetic and 8 foreign-tool PDFs (Chrome, LibreOffice, PyMuPDF, pandoc): 100 % cell accuracy vs 87.6 % for the spec order, which silently extracted wrong cells. |
| 5 | **Identity resolution is probabilistic and explainable**: blocking (license number; soundex + site; family prefix + initial) → Fellegi–Sunter weights (nicknames, typos, compound surnames, Jr/Sr) → union-find with **cannot-link rules** (two employee ids, two licenses of one type, different generational suffix never merge). Gray zone → agent + human, never auto-merged. | Payroll and the schedule carry no employee id; this is the core of the problem. F1 0.999 on 14 synthetic worlds; on a high-collision set F1 0.900 → 0.927 after wave-4 fixes with precision flat. Every link shows its reasons in the UI. |
| 6 | **Claims with provenance + field-level survivorship.** Nothing is overwritten; each value is a claim with file/page/row/cell; the golden value follows per-attribute source priority (license service › HR for expiry; payroll for paid hours; schedule for daily split); disagreement = SRC-CONFLICT. | "Single source of truth" ≠ one correct file. Every flag can be defended back to the source cell (PDF crops in the UI). |
| 7 | **Licenses are judged on the shift date**, not today; role scope comes from the pack (CNA ⊂ LPN ⊂ RN). | The README's real risk: someone works after a license lapsed. LIC-WORKED-EXPIRED lists the dates and notes when a renewal may exist (last_verified < expiry). |
| 8 | **Shift hours come from the times; the footnote legend is a cross-check** (and the source for letter codes like `D`). | A/B: legend-first produced ~4 false paid-vs-scheduled issues per world with a wrong legend and gained no recall. |
| 9 | **Checks are pack SQL/Python**, one file each, with severity, message, action and evidence references; a bad row can never take a whole check down. 30+ checks incl. RN 8-hour coverage (42 CFR 483.35(b)), paid vs scheduled per facility, overlaps, duplicates, impossible hours, expiring/missing credentials, parse problems. | Reusable and reviewable; the catalogue is in `docs/IMPLEMENTATION.md §13.2`. |
| 10 | **PBJ-ready export**: daily hours per person × job code, overnight shifts split at midnight; rows whose week doesn't reconcile with payroll are `needs_signoff` — the system never invents a split. | The quarterly state staffing report becomes 13 weekly ingests plus a short sign-off list. |
| 11 | **AI only for the low-confidence remainder, behind deterministic validators.** The pipeline writes agent tasks (unknown schema, new source, scanned page, gray identity pair); Claude Code Sonnet subagents answer via `/process-agent-tasks`; schema + validators accept or reject; the pipeline never blocks. `claude -p` is an optional executor for unattended runs. | Live panel with real subagents: scanned schedule read and accepted; a real state license list mapped as `license`; a calendar template, CMS PBJ and a city payroll file rejected (no false mapping). |
| 12 | **DuckDB + Arrow bulk inserts, idempotent ingest** (content hash), stable issue fingerprints that keep human status across runs. | Single machine, no cloud; 20k rows insert in < 0.6 s (was 12 s with executemany); re-ingesting the same files changes nothing. |

## How it helps with the three problems

1. **Licenses, certifications, vendor paperwork expire too late** → golden expiry per credential (person or organization holder), checked per shift date (LIC-WORKED-EXPIRED, LIC-EXPIRING 30/60 days, LIC-EXPIRY-MISSING); vendor certificates of insurance land in the same model (`vendor_credential`) and the same checks; the Credentials page shows the 30/60/90-day horizon.
2. **Quarterly staffing report takes weeks** → the PBJ export is built from reconciled, identity-resolved data; only `needs_signoff` rows need a human; coverage gaps are flagged per facility and day.
3. **Referrals are slow** → no referral data was provided, and we say so. The SoT supplies the staffing half of the decision — which licensed staff are on shift at each facility, by role and day — and a referral feed is one more source for the auction and one more pack template.

**Reuse for another industry**: write a new pack (fields, templates, vocabularies, survivorship, checks). The engine, UI, agents and tests stay.

## How it was built and verified

Plan → task graph → 8 parallel build agents (TDD, research + cited sources in every module) → integration → 4 breaker agents (wiring, edge cases, real internet files, chaos root causes) logged ~70 breakdowns with 119 failing tests → 7 fix agents → correctness review (8 bugs, all fixed) + simplicity refactor (ruff-clean) → A/B tests → live panel (5 cases, real UI, real subagents). Logs: `docs/BREAKDOWNS.md`, `docs/breakdowns/`, `docs/review/`, `docs/ab/AB_TESTS.md`, `docs/panel/PANEL.md`, `docs/research/`.

**Known limits**: synthetic + a handful of real files are not the judges' files; mid-word wraps in some exported PDFs leave spacing inside names (matching still works); scanned pages depend on the agent; on heavily mutated synthetic files precision drops (A/B: 0.84 clean vs 0.55–0.71 mutated), mainly extra HRS-PAID-VS-SCHED / FAC-MISMATCH / SCHED-NO-HR issues.
