import { useEffect, useState } from "react";
import { apiText } from "../api/client";
import { ApiError } from "../components/ApiError";
import { PBJ_COLUMNS, type PbjRow, type PbjStatus } from "../api/types";
import { filterPbj, parsePbj } from "../lib/pbj";
import { useRun } from "../lib/RunContext";

export default function Exports() {
  const { version } = useRun();
  const [rows, setRows] = useState<PbjRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<PbjStatus | "all">("all");
  useEffect(() => {
    apiText("/api/exports/pbj.csv").then((t) => { setRows(parsePbj(t)); setError(null); }, (e) => setError(String(e)));
  }, [version]);
  const shown = filterPbj(rows, status);
  const link = "rounded bg-blue-600 px-3 py-1 text-sm text-white";
  return (
    <div className="space-y-3">
      <ApiError error={error} />
      <div className="flex flex-wrap items-center gap-3">
        <select aria-label="status" className="rounded border border-slate-300 bg-white px-2 py-1 text-sm" value={status} onChange={(e) => setStatus(e.target.value as PbjStatus | "all")}>
          <option value="all">all statuses</option><option value="ready">ready</option><option value="needs_signoff">needs sign-off</option>
        </select>
        <span className="text-sm text-slate-500">{shown.length} of {rows.length} rows</span>
        <a className={`${link} ml-auto`} href="/api/exports/pbj.csv" download="pbj.csv">Download pbj.csv</a>
        <a className={link} href="/api/exports/issues.csv" download="issues.csv">Download issues.csv</a>
      </div>
      <table className="w-full rounded border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-500"><tr>{PBJ_COLUMNS.map((c) => <th key={c} className="p-2">{c}</th>)}</tr></thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className={`border-t ${r.status === "needs_signoff" ? "bg-amber-50" : ""}`}>{PBJ_COLUMNS.map((c) => <td key={c} className="p-2">{r[c]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
