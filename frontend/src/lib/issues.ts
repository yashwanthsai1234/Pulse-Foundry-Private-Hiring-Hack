import { SEVERITIES, type IssueListItem, type Severity } from "../api/types";

const rank = (s: Severity) => SEVERITIES.indexOf(s);

export const sortIssues = (items: IssueListItem[]) =>
  [...items].sort((a, b) => rank(a.severity) - rank(b.severity) || a.title.localeCompare(b.title));

/** Severity-ordered groups; severities without issues are omitted. */
export function groupBySeverity(items: IssueListItem[]): [Severity, IssueListItem[]][] {
  const sorted = sortIssues(items);
  return SEVERITIES.map((s) => [s, sorted.filter((i) => i.severity === s)] as [Severity, IssueListItem[]]).filter(([, g]) => g.length > 0);
}
