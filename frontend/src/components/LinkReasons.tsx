import type { Link } from "../api/types";
import { reasonText } from "../lib/humanize";

/** Why two records were treated as one person, in plain words. */
export function LinkReasons({ link }: { link: Link }) {
  return (
    <p className="text-sm text-slate-700">
      <span className="font-medium">{Math.round(link.prob * 100)}% match</span>
      {" — "}{link.reasons.map(reasonText).join(" · ")}
    </p>
  );
}
