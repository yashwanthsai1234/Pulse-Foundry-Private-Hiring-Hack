import { SEVERITIES, type IssueListItem, type Severity } from "../api/types";

const rank = (s: Severity) => SEVERITIES.indexOf(s);

export const sortIssues = (items: IssueListItem[]) =>
  [...items].sort((a, b) => rank(a.severity) - rank(b.severity) || a.title.localeCompare(b.title));

/** Severity-ordered groups; severities without issues are omitted. */
export function groupBySeverity(items: IssueListItem[]): [Severity, IssueListItem[]][] {
  const sorted = sortIssues(items);
  return SEVERITIES.map((s) => [s, sorted.filter((i) => i.severity === s)] as [Severity, IssueListItem[]]).filter(([, g]) => g.length > 0);
}

/** The selected issue, or null when it is no longer listed (data changed or the server was reset). */
export function keepSelection(selected: string | null, items: { fingerprint: string }[] | null): string | null {
  if (!selected || !items) return selected;
  return items.some((i) => i.fingerprint === selected) ? selected : null;
}
