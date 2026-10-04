import type { Claim } from "../api/types";

/** Claims for one attribute. The golden claim is marked; others are shown red when the field is in conflict. */
export function ClaimTable({ claims, goldenId, conflict }: { claims: Claim[]; goldenId: string; conflict: boolean }) {
  return (
    <ul className="space-y-1">
      {claims.map((c) => {
        const golden = c.claim_id === goldenId;
        return (
          <li key={c.claim_id} className={`flex flex-wrap items-center gap-2 text-sm ${!golden && conflict ? "text-red-700" : ""}`}>
            <span className="w-4">{golden ? "✓" : conflict ? "✗" : ""}</span>
            <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-700">{c.template_id}</span>
            <span className="font-mono">{String(c.value)}</span>
            <span className="text-xs text-slate-500">
              {c.loc.file_name}{c.loc.page ? ` p${c.loc.page}` : ""}{c.loc.row ? ` row ${c.loc.row}` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
