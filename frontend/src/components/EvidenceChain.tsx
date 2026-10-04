import type { EvidenceItem } from "../api/types";
import { humanize, labelText, parsePairs } from "../lib/humanize";
import { LinkReasons } from "./LinkReasons";
import { PdfCrop } from "./PdfCrop";
import { SourceRow } from "./SourceRow";

function Item({ item }: { item: EvidenceItem }) {
  const mark = item.is_golden === true ? "✓ trusted value" : item.is_golden === false ? "✗ overruled" : null;
  const pairs = !item.raw && item.kind !== "link" ? parsePairs(item.text) : null;  // PDF rows: show as a table too
  const showText = item.kind !== "link" && !item.raw && !pairs;
  return (
    <li className="border-l-2 border-slate-300 py-1 pl-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-semibold text-slate-600">{labelText(item.label)}</span>
        {showText && <span className="text-sm">{humanize(item.text)}</span>}
        {mark && <span className={`text-xs font-semibold ${item.is_golden ? "text-green-700" : "text-red-700"}`}>{mark}</span>}
      </div>
      {item.kind === "cell" && item.loc?.bbox && item.loc.page != null && <div className="mt-1"><PdfCrop loc={item.loc} /></div>}
      {(item.raw || pairs) && <SourceRow raw={(item.raw ?? pairs)!} col={item.loc?.col} />}
      {item.link && <div className="mt-1"><LinkReasons link={item.link} /></div>}
    </li>
  );
}

export function EvidenceChain({ items, action }: { items: EvidenceItem[]; action?: string | null }) {
  return (
    <ul className="space-y-3">
      {items.map((it, i) => <Item key={i} item={it} />)}
      {action && (
        <li className="rounded border-l-4 border-blue-500 bg-blue-50 py-2 pl-3">
          <span className="mr-2 text-sm font-semibold text-blue-800">What to do:</span>
          <span className="text-sm">{humanize(action)}</span>
        </li>
      )}
    </ul>
  );
}
