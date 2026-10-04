import type { IssueStatus, Severity } from "../api/types";

const COLORS: Record<Severity, string> = {
  CRITICAL: "bg-red-600 text-white",
  HIGH: "bg-orange-500 text-white",
  MEDIUM: "bg-amber-400 text-amber-950",
  LOW: "bg-slate-400 text-white",
  INFO: "bg-blue-500 text-white",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${COLORS[severity]}`}>{severity}</span>;
}

const STATUS: Record<IssueStatus, string> = {
  open: "bg-slate-100 text-slate-700",
  acknowledged: "bg-blue-100 text-blue-800",
  resolved: "bg-green-100 text-green-800",
  false_positive: "bg-slate-200 text-slate-500",
};

export function StatusPill({ status }: { status: IssueStatus }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS[status]}`}>{status.replace("_", " ")}</span>;
}
