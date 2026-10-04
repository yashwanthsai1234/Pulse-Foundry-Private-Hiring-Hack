import { columnName } from "../lib/humanize";

/** The source row of an evidence item as a one-row table; the cell of column `col` is highlighted. */
export function SourceRow({ raw, col, row }: { raw: Record<string, string | null>; col?: string | null; row?: number | null }) {
  return (
    <div className="mt-1 overflow-x-auto">
      {row != null && <div className="text-xs text-slate-400">Row {row}</div>}
      <table className="text-xs">
        <thead><tr>{Object.keys(raw).map((k) => <th key={k} className="border px-2 py-0.5 text-left font-medium text-slate-500">{columnName(k)}</th>)}</tr></thead>
        <tbody>
          <tr>{Object.entries(raw).map(([k, v]) => (
            <td key={k} data-highlight={k === col ? "true" : undefined} className={`border px-2 py-0.5 ${k === col ? "bg-yellow-200 font-semibold" : ""}`}>{v}</td>
          ))}</tr>
        </tbody>
      </table>
    </div>
  );
}
