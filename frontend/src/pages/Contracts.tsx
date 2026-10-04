import { useState } from "react";
import { api } from "../api/client";
import type { AgentTask, Contract } from "../api/types";
import { ApiError } from "../components/ApiError";
import { useRun } from "../lib/RunContext";
import { useApi } from "../lib/useApi";

export default function Contracts() {
  const { refresh } = useRun();
  const { data: contracts, error } = useApi<Contract[]>("/api/contracts");
  const { data: tasks, error: tasksError } = useApi<AgentTask[]>("/api/agent-tasks");
  const [open, setOpen] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const approve = async (id: string) => {
    try { await api(`/api/contracts/${encodeURIComponent(id)}/approve`, "POST"); setActionError(null); refresh(); }
    catch (e) { setActionError(String(e)); }
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="md:col-span-2"><ApiError error={error ?? tasksError ?? actionError} /></div>
      <section>
        <h2 className="mb-2 font-semibold">Contracts</h2>
        {contracts?.length === 0 && <p className="text-sm text-slate-500">No contracts yet.</p>}
        <ul className="space-y-2">
          {(contracts ?? []).map((c) => (
            <li key={c.contract_id} className="rounded border border-slate-200 bg-white p-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm">{c.contract_id}</span>
                <span className="rounded bg-slate-100 px-1.5 text-xs">{c.source}</span>
                {c.approved ? <span className="text-xs text-green-700">approved</span>
                  : <button className="ml-auto rounded bg-green-600 px-2 py-0.5 text-xs text-white" onClick={() => approve(c.contract_id)}>Approve</button>}
              </div>
              <button className="text-xs text-blue-700" onClick={() => setOpen(open === c.contract_id ? null : c.contract_id)}>
                {open === c.contract_id ? "hide" : "show"} column_map
              </button>
              {open === c.contract_id && <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(c.column_map, null, 2)}</pre>}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 font-semibold">Agent tasks</h2>
        {tasks?.length === 0 && <p className="text-sm text-slate-500">No agent tasks.</p>}
        <ul className="space-y-2">
          {(tasks ?? []).map((t) => (
            <li key={t.task_id} className="rounded border border-slate-200 bg-white p-3 text-sm">
              <span className="font-mono text-xs">{t.task_id}</span> <span className="font-medium">{t.kind}</span>
              <span className="ml-2 rounded bg-slate-100 px-1.5 text-xs">{t.status}</span>
              <div className="text-xs text-slate-500">ref {t.ref}</div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
