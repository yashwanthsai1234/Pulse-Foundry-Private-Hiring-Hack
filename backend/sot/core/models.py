"""Shared contracts for every pipeline stage (docs/IMPLEMENTATION.md §3).

All modules import their types from here. Do not redefine these elsewhere.

Sources:
- https://docs.pydantic.dev/latest/concepts/models/ (BaseModel; extra keys in a row dict are ignored, so rows validate directly)
- https://docs.python.org/3/library/typing.html#typing.Literal
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

BBox = tuple[float, float, float, float]  # x0, top, x1, bottom in PDF points
Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEVERITY_ORDER: dict[str, int] = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


# ---------- files and locators ----------
class FileRef(BaseModel):
    file_id: str  # sha256 of content
    file_name: str
    path: str  # landing path
    size: int
    received_at: datetime


class Locator(BaseModel):
    file_id: str
    file_name: str
    page: int | None = None  # 1-based, PDF only
    sheet: str | None = None  # XLSX only
    row: int | None = None  # 1-based source row (line in file / row on page)
    col: str | None = None  # source header text
    bbox: BBox | None = None  # PDF cell box


# ---------- stage 1: sniff ----------
class SniffResult(BaseModel):
    parser: str
    score: float  # 0..1
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class AuctionResult(BaseModel):
    file: FileRef
    bids: list[SniffResult]  # all parsers, sorted desc
    winner: SniffResult | None  # None -> quarantine


# ---------- stage 2: extract ----------
class ExtractionInfo(BaseModel):
    method: str  # csv | xlsx | json | pdf.lines | pdf.text | pdf.mupdf | pdf.words | agent.page_reader
    score: float
    notes: list[str] = Field(default_factory=list)


class RawTable(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    table_id: str  # f"{file_id[:12]}:{page or sheet or 0}:{index}"
    file: FileRef
    parser: str
    page: int | None = None
    sheet: str | None = None
    header: list[str]
    df: pl.DataFrame  # all columns Utf8 in header order, plus "_src_row" (Int64)
    cell_bboxes: dict[str, BBox] | None = None  # key f"{df_row_index}:{col_index}"
    context: dict[str, str] = Field(default_factory=dict)  # title, footnote, facility_hint, legend_json
    extraction: ExtractionInfo


# ---------- stage 3: profile + map ----------
InferredType = Literal["string", "integer", "number", "date", "datetime", "bool", "empty"]


class ColumnProfile(BaseModel):
    column: str
    index: int
    n: int
    null_ratio: float
    distinct: int
    inferred_type: InferredType
    sample: list[str]  # max 20 distinct non-null values
    validator_hits: dict[str, float]  # field_id -> share of non-null values that pass


class FieldMatch(BaseModel):
    column: str
    field_id: str
    score: float
    header_score: float
    value_score: float
    type_score: float


class Mapping(BaseModel):
    table_id: str
    template_id: str | None  # None -> unknown
    confidence: float
    matches: list[FieldMatch]
    unmapped_columns: list[str]
    missing_required: list[str]
    source: Literal["auto", "contract", "agent", "human"]
    contract_id: str | None = None
    drift: bool = False


class Contract(BaseModel):
    contract_id: str  # f"{template_id}:v{version}:{fingerprint[:8]}"
    template_id: str
    header_fingerprint: str
    version: int
    column_map: dict[str, str]  # source column -> field_id
    source: Literal["auto", "agent", "human"]
    approved: bool
    created_at: datetime


# ---------- stage 4: normalize ----------
class PersonKey(BaseModel):
    given: str | None = None
    family: str | None = None
    middle: str | None = None
    suffix: str | None = None  # jr | sr | ii | iii | iv — different suffix = different person
    given_initial: str | None = None
    nick_key: str | None = None  # canonical given name from nickname table
    soundex_family: str | None = None
    display: str  # original text


class SourceRecord(BaseModel):
    record_id: str  # f"{table_id}:{src_row}"
    template_id: str  # hr_roster | payroll | license | schedule | vendor_credential | ...
    entity: str  # person | pay_period | credential | shift_grid
    fields: dict[str, Any]  # canonical field_id -> normalized JSON-safe value
    raw: dict[str, str | None]  # source column -> raw text
    person_key: PersonKey | None = None
    loc: Locator
    parse_issues: list[str] = Field(default_factory=list)  # e.g. "date_ambiguous:person.hire_date"


class ShiftRecord(BaseModel):
    shift_id: str  # f"{record_id}:{date}"
    record_id: str  # schedule SourceRecord
    facility_id: str | None
    role: str | None
    work_date: date
    token: str  # raw "7a-3p"
    start: time | None
    end: time | None
    hours: float | None
    hours_source: Literal["legend", "computed", "both", "unknown"]
    loc: Locator


# ---------- stage 5: resolve ----------
class Link(BaseModel):
    a: str  # record_id
    b: str
    prob: float
    weight: float
    method: Literal["key", "score", "agent", "human"]
    reasons: list[str]


class Person(BaseModel):
    person_id: str  # "P-<employee_id>" if HR exists, else "P-X<hash8>"
    record_ids: list[str]
    employee_id: str | None
    has_hr: bool


# ---------- stage 6: truth ----------
class Claim(BaseModel):
    claim_id: str
    entity_type: str  # person | credential
    entity_id: str
    attribute: str
    value: Any
    value_type: str
    template_id: str  # source system
    record_id: str
    loc: Locator
    observed_at: datetime


class GoldenValue(BaseModel):
    entity_type: str
    entity_id: str
    attribute: str
    value: Any
    claim_id: str
    rule: str  # "priority:license>hr_roster"
    conflict: bool
    conflicting_claim_ids: list[str] = Field(default_factory=list)


# ---------- stage 7: checks ----------
class EvidenceItem(BaseModel):
    kind: Literal["cell", "link", "claim", "golden", "note"]
    label: str
    text: str
    loc: Locator | None = None
    claim_id: str | None = None
    link: Link | None = None
    is_golden: bool | None = None
    raw: dict[str, str | None] | None = None  # source row (column -> text) for CSV/XLSX cell evidence


class IssueDraft(BaseModel):
    check_id: str
    severity: Severity
    title: str
    message: str
    entity_ids: list[str] = Field(default_factory=list)
    facility_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    key: str = ""  # extra fingerprint discriminator
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_refs: dict[str, Any] = Field(default_factory=dict)  # raw ids for the evidence enricher
    action: str | None = None


IssueStatus = Literal["open", "acknowledged", "resolved", "false_positive"]


class Issue(IssueDraft):
    fingerprint: str
    status: IssueStatus = "open"
    owner: str | None = None
    note: str | None = None
    first_seen_run: str
    last_seen_run: str
    active: bool = True


# ---------- agents ----------
AgentKind = Literal["schema_mapper", "page_reader", "identity_adjudicator", "new_source_modeler"]
AgentStatus = Literal["pending", "done", "accepted", "rejected", "expired"]


class AgentTask(BaseModel):
    task_id: str  # "t-" + sha256(kind|prompt_version|payload)[:10]
    kind: AgentKind
    run_id: str
    ref: str  # table_id, file_id:page, or "recA|recB"
    prompt_version: str
    instructions: str
    payload: dict[str, Any]
    output_schema: dict[str, Any]
    output_path: str
    input_files: list[str] = Field(default_factory=list)
    status: AgentStatus = "pending"
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
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    files: int
    skipped: int
    quarantined: int
    tables: int
    records: int
    persons: int
    issues_by_severity: dict[str, int]
    agent_tasks: int
