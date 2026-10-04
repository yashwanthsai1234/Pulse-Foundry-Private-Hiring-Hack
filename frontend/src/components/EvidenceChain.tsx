import type { EvidenceItem } from "../api/types";
import { LinkReasons } from "./LinkReasons";
import { PdfCrop } from "./PdfCrop";
import { SourceRow } from "./SourceRow";

function Item({ item }: { item: EvidenceItem }) {
  const mark = item.is_golden === true ? "✓ golden" : item.is_golden === false ? "✗ not golden" : null;
  return (
    <li className="border-l-2 border-slate-300 py-1 pl-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="w-32 shrink-0 break-words text-xs font-semibold uppercase text-slate-500">{item.label.replaceAll("_", " ")}</span>
        <span className="text-sm">{item.text}</span>
        {mark && <span className={`text-xs font-semibold ${item.is_golden ? "text-green-700" : "text-red-700"}`}>{mark}</span>}
      </div>
      {item.kind === "cell" && item.loc?.bbox && item.loc.page != null && <div className="mt-1"><PdfCrop loc={item.loc} /></div>}
      {item.raw && <SourceRow raw={item.raw} col={item.loc?.col} row={item.loc?.row} />}
      {item.link && <div className="mt-1"><LinkReasons link={item.link} /></div>}
    </li>
  );
}

export function EvidenceChain({ items, action }: { items: EvidenceItem[]; action?: string | null }) {
  return (
    <ul className="space-y-2">
      {items.map((it, i) => <Item key={i} item={it} />)}
      {action && (
        <li className="border-l-2 border-blue-400 py-1 pl-3">
          <span className="mr-2 text-xs font-semibold uppercase text-slate-500">action</span>
          <span className="text-sm">{action}</span>
        </li>
      )}
    </ul>
  );
}
