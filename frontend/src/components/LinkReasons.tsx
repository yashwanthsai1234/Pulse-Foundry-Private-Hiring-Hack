import type { Link } from "../api/types";

export function LinkReasons({ link }: { link: Link }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer">
        <span className="font-mono text-xs">{link.a}</span> to <span className="font-mono text-xs">{link.b}</span>{" "}
        <span className="text-slate-500">p={link.prob} ({link.method})</span>
      </summary>
      <ul className="ml-6 list-disc text-slate-600">
        {link.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
    </details>
  );
}
