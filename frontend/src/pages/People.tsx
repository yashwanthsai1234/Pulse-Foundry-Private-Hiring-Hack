import { useState } from "react";
import type { PersonDetail, PersonRow } from "../api/types";
import { ApiError } from "../components/ApiError";
import { ClaimTable } from "../components/ClaimTable";
import { LinkReasons } from "../components/LinkReasons";
import { SeverityBadge } from "../components/SeverityBadge";
import { useApi } from "../lib/useApi";

function Drawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: d, error } = useApi<PersonDetail>(`/api/people/${id}`);
  return (
    <aside className="fixed inset-y-0 right-0 w-full max-w-xl overflow-y-auto border-l border-slate-300 bg-white p-5 shadow-xl" aria-label="person detail">
      <button className="float-right text-slate-500" onClick={onClose} aria-label="close">✕</button>
      {error ? <ApiError error={error} /> : !d ? <p>Loading...</p> : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">{d.person.display_name} <span className="text-sm font-normal text-slate-500">{d.person.person_id}</span></h2>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Fields</h3>
            {d.golden.map((g) => (
              <div key={g.attribute} className={`mb-2 rounded border p-2 ${g.conflict ? "border-red-300 bg-red-50" : "border-slate-200"}`}>
                <div className="text-sm font-medium">{g.attribute} = <span className="font-mono">{String(g.value)}</span>{g.conflict && <span className="ml-2 text-xs text-red-700">conflict</span>}</div>
                <div className="mb-1 text-xs text-slate-500">{g.rule}</div>
                <ClaimTable claims={g.claims} goldenId={g.claim_id} conflict={g.conflict} />
              </div>
            ))}
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Links</h3>
            {d.links.map((l) => <LinkReasons key={l.a + l.b} link={l} />)}
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Credentials</h3>
            {d.credentials.map((c) => <p key={c.credential_id} className="text-sm">{c.credential_type} {c.number}, expires {c.expires_on} ({c.days_left}d)</p>)}
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Shifts</h3>
            {d.shifts.map((s) => <p key={s.shift_id} className="text-sm">{s.work_date} {s.facility_id} {s.token} ({s.hours} h)</p>)}
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Issues</h3>
            {d.issues.map((i) => <p key={i.fingerprint} className="flex items-center gap-2 text-sm"><SeverityBadge severity={i.severity} />{i.title}</p>)}
          </section>
        </div>
      )}
    </aside>
  );
}

export default function People() {
  const { data: people, error } = useApi<PersonRow[]>("/api/people");
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <ApiError error={error} />
      {people?.length === 0 && <p className="text-sm text-slate-500">No people yet. Ingest files first.</p>}
      <table className="w-full rounded border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-500">
          <tr><th className="p-2">Name</th><th>ID</th><th>Role</th><th>Facility</th><th>HR</th><th>Issues</th></tr>
        </thead>
        <tbody>
          {(people ?? []).map((p) => (
            <tr key={p.person_id} className="cursor-pointer border-t hover:bg-slate-50" onClick={() => setSelected(p.person_id)}>
              <td className="p-2 font-medium">{p.display_name}</td><td className="font-mono text-xs">{p.person_id}</td>
              <td>{p.role}</td><td>{p.home_facility_id}</td><td>{p.has_hr ? "yes" : "no"}</td><td>{p.issue_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <Drawer id={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
