// TypeScript mirrors of backend/sot/core/models.py (same names) plus the JSON shapes of each
// /api endpoint the UI consumes. docs/research/A7.md holds the same contract as a table.
// Sources:
// - https://developer.mozilla.org/en-US/docs/Web/API/EventSource (named SSE events need addEventListener per type)

export type BBox = [number, number, number, number]; // x0, top, x1, bottom (PDF points)
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
export type IssueStatus = "open" | "acknowledged" | "resolved" | "false_positive";
export const ISSUE_STATUSES: IssueStatus[] = ["open", "acknowledged", "resolved", "false_positive"];

export interface Locator {
  file_id: string;
  file_name: string;
  page?: number | null;
  sheet?: string | null;
  row?: number | null;
  col?: string | null;
  bbox?: BBox | null;
}

export interface SniffResult { parser: string; score: number; reason: string; details?: Record<string, unknown> }
export interface FieldMatch { column: string; field_id: string; score: number; header_score: number; value_score: number; type_score: number }

export interface Link { a: string; b: string; prob: number; weight: number; method: "key" | "score" | "agent" | "human"; reasons: string[] }

export interface EvidenceItem {
  kind: "cell" | "link" | "claim" | "golden" | "note";
  label: string;
  text: string;
  loc?: Locator | null;
  claim_id?: string | null;
  link?: Link | null;
  is_golden?: boolean | null;
  /** EXTENSION to models.py: source row (column -> raw text) so CSV cells render as a mini table. */
  raw?: Record<string, string | null> | null;
}

export interface Issue {
  check_id: string;
  severity: Severity;
  title: string;
  message: string;
  entity_ids: string[];
  facility_id?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  key: string;
  evidence: EvidenceItem[];
  action?: string | null;
  fingerprint: string;
  status: IssueStatus;
  owner?: string | null;
  note?: string | null;
  first_seen_run: string;
  last_seen_run: string;
  active: boolean;
}
/** GET /api/issues item: Issue without evidence, plus two derived fields. */
export type IssueListItem = Omit<Issue, "evidence"> & { evidence_count: number; person_name: string | null };
/** GET /api/issues/{fingerprint}: Issue with evidence[], plus person_name. */
export type IssueDetail = Issue & { person_name: string | null };

export type AgentKind = "schema_mapper" | "page_reader" | "identity_adjudicator" | "new_source_modeler";
export type AgentStatus = "pending" | "done" | "accepted" | "rejected" | "expired";
export interface AgentTask {
  task_id: string; kind: AgentKind; run_id: string; ref: string; prompt_version: string;
  instructions: string; payload: Record<string, unknown>; status: AgentStatus; created_at: string;
}
export interface Contract {
  contract_id: string; template_id: string; header_fingerprint: string; version: number;
  column_map: Record<string, string>; source: "auto" | "agent" | "human"; approved: boolean; created_at: string;
}

export const EVENT_TYPES = [
  "run.started", "file.landed", "file.skipped", "file.sniffed", "file.quarantined",
  "table.extracted", "table.mapped", "table.drift", "table.unmapped",
  "agent.task_created", "agent.task_done", "agent.task_accepted", "agent.task_rejected",
  "normalize.done", "resolve.done", "truth.done", "checks.done",
  "run.completed", "run.failed", "log",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

/**
 * SSE payload. `data` per type (all keys optional, UI tolerates absence):
 *  file.sniffed:      { parser, score, bids: SniffResult[] }
 *  table.extracted:   { table_id, page?, sheet?, method, score, rows }
 *  table.mapped:      { table_id, template_id, confidence, matches: FieldMatch[], unmapped_columns }
 *  agent.task_*:      { task_id, kind, ref, notes? }
 */
export interface PipelineEvent {
  run_id: string; seq: number; ts: string; type: EventType;
  file_name?: string | null; message: string; data: Record<string, any>;
}

// ---------- REST shapes (not in models.py) ----------
/** GET /api/summary: RunSummary without run_id; agent_tasks is a count per AgentStatus. */
export interface Summary {
  files: number; skipped: number; quarantined: number; tables: number; records: number; persons: number;
  issues_by_severity: Record<string, number>;
  agent_tasks: Record<string, number>;
}
export interface Settings { as_of: string }

/** GET /api/people item. */
export interface PersonRow {
  person_id: string; employee_id: string | null; has_hr: boolean; display_name: string; role: string | null;
  home_facility_id: string | null; phone: string | null; hire_date: string | null; issue_count: number;
}
export interface Claim {
  claim_id: string; entity_type: string; entity_id: string; attribute: string; value: unknown; value_type: string;
  template_id: string; record_id: string; loc: Locator; observed_at: string;
}
export interface GoldenField {
  attribute: string; value: unknown; claim_id: string; rule: string; conflict: boolean;
  conflicting_claim_ids: string[]; claims: Claim[];
}
export interface Credential {
  credential_id: string; holder_type: "person" | "organization"; holder_id: string; holder_name: string;
  credential_type: string; number: string | null; issued_on: string | null; expires_on: string | null;
  last_verified: string | null; days_left: number | null;
}
export interface PersonShift { shift_id: string; facility_id: string | null; role: string | null; work_date: string; token: string; hours: number | null; loc: Locator }
/** GET /api/people/{person_id}. */
export interface PersonDetail {
  person: PersonRow;
  golden: GoldenField[];
  links: Link[];
  credentials: Credential[];
  shifts: PersonShift[];
  issues: IssueListItem[];
}

/** GET /api/shifts. */
export interface ShiftCell { token: string; hours: number | null; license_valid: boolean }
export interface ShiftRow { person_id: string; display_name: string; role: string | null; cells: Record<string, ShiftCell> }
export interface ShiftFacility { facility_id: string; name: string; rows: ShiftRow[]; rn_coverage: Record<string, number> }
export interface ShiftGrid { days: string[]; facilities: ShiftFacility[] }

export const PBJ_COLUMNS = ["employee_id", "person_id", "facility_id", "work_date", "job_code", "hours", "status", "note"] as const;
export type PbjStatus = "ready" | "needs_signoff";
export type PbjRow = Record<(typeof PBJ_COLUMNS)[number], string>;
