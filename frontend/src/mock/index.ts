// In-memory stand-in for the backend (VITE_MOCK=1). Data is the PLAN.md section 10 example.
import issuesJson from "./issues.json";
import peopleJson from "./people.json";
import shiftsJson from "./shifts.json";
import credentialsJson from "./credentials.json";
import contractsJson from "./contracts.json";
import agentTasksJson from "./agent_tasks.json";
import eventsJson from "./events.json";
import pbjCsv from "./pbj.csv?raw";
import type { AgentTask, Contract, IssueDetail, IssueListItem, PersonDetail, PipelineEvent, Settings, Summary } from "../api/types";

const issues = structuredClone(issuesJson) as unknown as IssueDetail[];
const contracts = structuredClone(contractsJson) as unknown as Contract[];
const people = peopleJson as unknown as PersonDetail[];
let settings: Settings = { as_of: "2026-10-04" };

const toListItem = ({ evidence, ...rest }: IssueDetail): IssueListItem => ({ ...rest, evidence_count: evidence.length });

function summary(): Summary {
  const bySeverity: Record<string, number> = {};
  for (const i of issues) bySeverity[i.severity] = (bySeverity[i.severity] ?? 0) + 1;
  const tasks: Record<string, number> = {};
  for (const t of agentTasksJson) tasks[t.status] = (tasks[t.status] ?? 0) + 1;
  return { files: 5, skipped: 0, quarantined: 0, tables: 6, records: 9, persons: people.length, issues_by_severity: bySeverity, agent_tasks: tasks };
}

export function mockRequest(method: string, url: string, body?: unknown): unknown {
  const [path, qs] = url.split("?");
  const q = new URLSearchParams(qs);
  const id = decodeURIComponent(path.split("/")[3] ?? "");
  if (path === "/api/summary") return summary();
  if (path === "/api/runs") return [];
  if (path === "/api/settings") {
    if (method === "PUT") settings = body as Settings;
    return settings;
  }
  if (path === "/api/issues") {
    const match = (i: IssueDetail) =>
      (!q.get("severity") || i.severity === q.get("severity")) &&
      (!q.get("status") || i.status === q.get("status")) &&
      (!q.get("check_id") || i.check_id === q.get("check_id"));
    return issues.filter(match).map(toListItem);
  }
  if (path.startsWith("/api/issues/")) {
    const issue = issues.find((i) => i.fingerprint === id);
    if (!issue) throw new Error(`no issue ${id}`);
    if (method === "PATCH") Object.assign(issue, body);
    return issue;
  }
  if (path === "/api/people") return people.map((p) => p.person);
  if (path.startsWith("/api/people/")) return people.find((p) => p.person.person_id === id);
  if (path === "/api/shifts") return shiftsJson;
  if (path === "/api/credentials") return credentialsJson;
  if (path === "/api/contracts") return contracts;
  if (path.startsWith("/api/contracts/") && path.endsWith("/approve")) {
    const c = contracts.find((x) => x.contract_id === id);
    if (!c) throw new Error(`no contract ${id}`);
    c.approved = true;
    return c;
  }
  if (path === "/api/agent-tasks") return agentTasksJson as unknown as AgentTask[];
  if (path === "/api/exports/pbj.csv") return pbjCsv;
  throw new Error(`mock: no route for ${method} ${path}`);
}

const listeners = new Set<(e: PipelineEvent) => void>();
let seq = 0;

/** Mock of the global event stream: receives the events of every mock ingest. Returns an unsubscribe function. */
export function mockEventStream(onEvent: (e: PipelineEvent) => void): () => void {
  listeners.add(onEvent);
  return () => { listeners.delete(onEvent); };
}

/** Mock ingest: replays the fixture events on the global stream with a short delay between them. */
export function mockIngest(delayMs = 350): { run_id: string } {
  const run_id = `run-${Date.now()}`;
  eventsJson.forEach((e, i) =>
    setTimeout(() => {
      const ev = { data: {}, ...e, run_id, seq: ++seq, ts: new Date().toISOString() } as PipelineEvent;
      listeners.forEach((l) => l(ev));
    }, (i + 1) * delayMs));
  return { run_id };
}

/** SVG stand-in for a PyMuPDF crop. The highlight is relative to the image, like the real X-Highlight header. */
export function mockCrop(): { url: string; highlight: string } {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="196"><rect width="300" height="196" fill="#fff"/>' +
    '<g stroke="#999" fill="none"><rect x="20" y="40" width="260" height="36"/><rect x="20" y="76" width="260" height="36"/></g>' +
    '<g font-family="sans-serif" font-size="13" fill="#333"><text x="30" y="62">Sofia Reyes   RN   7a-3p   OFF</text>' +
    '<text x="108" y="102">Marc Bell | CNA | 3p-11p</text></g></svg>';
  return { url: `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`, highlight: "0.36,0.40,0.5,0.19" };
}
