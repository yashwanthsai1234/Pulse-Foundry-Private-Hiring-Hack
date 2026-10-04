import { useState } from "react";
import { api, qs } from "../api/client";
import { ISSUE_STATUSES, SEVERITIES, type IssueDetail, type IssueListItem, type IssueStatus } from "../api/types";
import { ApiError } from "../components/ApiError";
import { EvidenceChain } from "../components/EvidenceChain";
import { SeverityBadge, StatusPill } from "../components/SeverityBadge";
import { groupBySeverity } from "../lib/issues";
import { useRun } from "../lib/RunContext";
import { useApi } from "../lib/useApi";

const select = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";

export default function Issues() {
  const { refresh } = useRun();
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [check, setCheck] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data: all, error }  = useApi<IssueListItem[]>("/api/issues");
  const { data: items } = useApi<IssueListItem[]>(`/api/issues${qs({ severity, status, check_id: check })}`);
  const { data: detail, error: detailError } = useApi<IssueDetail>(selected ? `/api/issues/${selected}` : null);
  const checks = [...new Set((all ?? []).map((i) => i.check_id))].sort();

  async function setIssueStatus(s: IssueStatus) {
    try {
      await api(`/api/issues/${selected}`, "PATCH", { status: s });
      setActionError(null);
      refresh();
    } catch (e) {
      setActionError(String(e));
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-[22rem_1fr]">
      <section>
        <ApiError error={error} />
        <div className="mb-3 flex flex-wrap gap-2">
          <select aria-label="severity" className={select} value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">all severities</option>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select aria-label="status" className={select} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">all statuses</option>{ISSUE_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select aria-label="check" className={select} value={check} onChange={(e) => setCheck(e.target.value)}>
            <option value="">all checks</option>{checks.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        {groupBySeverity(items ?? []).map(([sev, group]) => (
          <div key={sev} className="mb-3">
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">{sev} ({group.length})</h3>
            <ul className="space-y-1">
              {group.map((i) => (
                <li key={i.fingerprint}>
                  <button onClick={() => setSelected(i.fingerprint)}
                    className={`w-full rounded border p-2 text-left ${selected === i.fingerprint ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                    <div className="flex items-center gap-2"><SeverityBadge severity={i.severity} /><StatusPill status={i.status} /></div>
                    <div className="mt-1 text-sm font-medium">{i.title}</div>
                    <div className="text-xs text-slate-500">
                      {[i.person_name ?? i.facility_id, i.period_start && `${i.period_start}${i.period_end ? ` to ${i.period_end}` : ""}`, `${i.evidence_count} evidence`].filter(Boolean).join(" · ")}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {items?.length === 0 && <p className="text-sm text-slate-500">No issues match.</p>}
      </section>
      <section className="rounded border border-slate-200 bg-white p-4">
        <ApiError error={detailError ?? actionError} />
        {!detail ? <p className="text-sm text-slate-500">Select an issue to see its evidence.</p> : (
          <>
            <div className="mb-1 flex items-center gap-2"><SeverityBadge severity={detail.severity} /><StatusPill status={detail.status} /><span className="font-mono text-xs text-slate-400">{detail.check_id}</span></div>
            <h2 className="text-lg font-semibold">{detail.title}</h2>
            <p className="mb-3 text-sm text-slate-600">{detail.message}</p>
            <EvidenceChain items={detail.evidence} action={detail.action} />
            <div className="mt-4 flex gap-2">
              <button className="rounded bg-blue-600 px-3 py-1 text-sm text-white" onClick={() => setIssueStatus("acknowledged")}>Acknowledge</button>
              <button className="rounded bg-green-600 px-3 py-1 text-sm text-white" onClick={() => setIssueStatus("resolved")}>Resolve</button>
              <button className="rounded bg-slate-500 px-3 py-1 text-sm text-white" onClick={() => setIssueStatus("false_positive")}>False positive</button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
