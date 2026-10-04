import { useState } from "react";
import type { PipelineEvent } from "../api/types";
import { groupEvents, type AgentState, type FileGroup, type TableState } from "../lib/groupEvents";
import { confidenceColor } from "../lib/confidence";

const AGENT_COLOR: Record<AgentState["state"], string> = {
  "waiting for agent": "bg-amber-100 text-amber-800",
  validating: "bg-blue-100 text-blue-800",
  "validator OK": "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
};

function Table({ t }: { t: TableState }) {
  const where = t.page ? `p${t.page}` : t.sheet ?? "table";
  return (
    <div className="ml-4 mt-1 text-sm">
      <span className="font-medium">{where}</span> <span className="text-slate-500">{t.method} {t.score.toFixed(2)}, {t.rows} rows</span>
      {t.mapping && (
        <span className="ml-2 text-xs text-slate-500">
          {t.mapping.template_id ?? "unknown source"} {t.mapping.confidence.toFixed(2)}
        </span>
      )}
      <div className="mt-0.5 flex flex-wrap gap-1">
        {t.mapping?.matches.map((m) => (
          <span key={m.column} className={`rounded px-1.5 py-0.5 text-xs ${confidenceColor(m.score)}`} title={`score ${m.score.toFixed(2)}`}>
            {m.column} → {m.field_id}
          </span>
        ))}
      </div>
    </div>
  );
}

function File({ g }: { g: FileGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-2">
        <span className="font-medium">{g.fileName}</span>
        {g.parser && (
          <button className="rounded bg-slate-100 px-1.5 text-xs text-slate-700 hover:bg-slate-200" onClick={() => setOpen(!open)} aria-expanded={open}>
            {g.parser} {g.score?.toFixed(2)} {open ? "▾" : "▸"}
          </button>
        )}
        {g.quarantined && <span className="rounded bg-red-100 px-1.5 text-xs text-red-800">quarantined</span>}
        {g.skipped && <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">skipped (known)</span>}
      </div>
      {open && (
        <ul className="ml-4 mt-1 text-xs text-slate-600">
          {g.bids.map((b) => <li key={b.parser}>{b.parser} {b.score.toFixed(2)}: {b.reason}</li>)}
        </ul>
      )}
      {g.messages.map((m) => <p key={m} className="ml-4 text-xs text-slate-500">{m}</p>)}
      {g.tables.map((t) => <Table key={t.table_id} t={t} />)}
      {g.agents.map((a) => (
        <p key={a.task_id} className="ml-4 mt-1 text-xs">
          agent {a.kind}: <span className={`rounded px-1.5 py-0.5 ${AGENT_COLOR[a.state]}`}>{a.state}</span>
        </p>
      ))}
    </li>
  );
}

export function PipelineFeed({ events }: { events: PipelineEvent[] }) {
  const { files, globals } = groupEvents(events);
  return (
    <div className="space-y-2">
      <ul className="space-y-2">{files.map((g) => <File key={g.fileName} g={g} />)}</ul>
      <ul className="text-sm text-slate-700">
        {globals.filter((e) => e.type !== "file.landed").map((e) => <li key={e.seq}><span className="text-xs uppercase text-slate-400">{e.type}</span> {e.message}</li>)}
      </ul>
    </div>
  );
}
