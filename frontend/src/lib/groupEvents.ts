import type { FieldMatch, PipelineEvent, SniffResult } from "../api/types";

export interface TableState {
  table_id: string; page?: number; sheet?: string; method: string; score: number; rows: number;
  mapping?: { template_id: string | null; confidence: number; matches: FieldMatch[]; unmapped_columns: string[] };
}
export interface AgentState { task_id: string; kind: string; state: "waiting for agent" | "validating" | "validator OK" | "rejected" }
export interface FileGroup {
  fileName: string; parser?: string; score?: number; bids: SniffResult[]; tables: TableState[];
  agents: AgentState[]; quarantined: boolean; skipped: boolean; messages: string[];
}

const AGENT_STATE: Record<string, AgentState["state"]> = {
  "agent.task_created": "waiting for agent",
  "agent.task_done": "validating",
  "agent.task_accepted": "validator OK",
  "agent.task_rejected": "rejected",
};

/** Folds the event stream into one group per file (first-seen order); events without a file go to `globals`. */
export function groupEvents(events: PipelineEvent[]): { files: FileGroup[]; globals: PipelineEvent[] } {
  const byName = new Map<string, FileGroup>();
  const globals: PipelineEvent[] = [];
  for (const e of events) {
    if (!e.file_name) { globals.push(e); continue; }
    let g = byName.get(e.file_name);
    if (!g) {
      g = { fileName: e.file_name, bids: [], tables: [], agents: [], quarantined: false, skipped: false, messages: [] };
      byName.set(e.file_name, g);
    }
    const d = e.data;
    if (e.type === "file.sniffed") { g.parser = d.parser; g.score = d.score; g.bids = d.bids ?? []; }
    else if (e.type === "file.quarantined") { g.quarantined = true; g.messages.push(e.message); }
    else if (e.type === "file.skipped") { g.skipped = true; g.messages.push(e.message); }
    else if (e.type === "table.extracted") g.tables.push({ table_id: d.table_id, page: d.page, sheet: d.sheet, method: d.method, score: d.score, rows: d.rows });
    else if (e.type === "table.mapped" || e.type === "table.drift" || e.type === "table.unmapped") {
      const t = g.tables.find((x) => x.table_id === d.table_id);
      if (t) t.mapping = { template_id: d.template_id ?? null, confidence: d.confidence ?? 0, matches: d.matches ?? [], unmapped_columns: d.unmapped_columns ?? [] };
    } else if (e.type in AGENT_STATE) {
      const state = AGENT_STATE[e.type];
      const a = g.agents.find((x) => x.task_id === d.task_id);
      if (a) a.state = state; else g.agents.push({ task_id: d.task_id, kind: d.kind, state });
    }
  }
  return { files: [...byName.values()], globals };
}
