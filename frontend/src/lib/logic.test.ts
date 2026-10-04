import { groupEvents } from "./groupEvents";
import { filterPbj, parsePbj } from "./pbj";
import { groupBySeverity, sortIssues } from "./issues";
import { bucketCredentials } from "./credentials";
import { parseHighlight } from "./highlight";
import type { Credential, IssueListItem, PipelineEvent } from "../api/types";

let seq = 0;
const ev = (type: PipelineEvent["type"], file_name: string | null, data: Record<string, unknown> = {}, message = ""): PipelineEvent =>
  ({ run_id: "r", seq: ++seq, ts: "t", type, file_name, message, data });

describe("groupEvents", () => {
  const events = [
    ev("run.started", null, {}, "go"),
    ev("file.sniffed", "a.csv", { parser: "csv", score: 0.97, bids: [{ parser: "csv", score: 0.97, reason: "" }, { parser: "xlsx", score: 0, reason: "" }] }),
    ev("table.extracted", "a.csv", { table_id: "t1", method: "csv", score: 0.97, rows: 3 }),
    ev("table.mapped", "a.csv", { table_id: "t1", template_id: "hr_roster", confidence: 0.9, matches: [{ column: "First", field_id: "person.given_name", score: 0.9 }] }),
    ev("file.quarantined", "b.bin", {}, "unreadable"),
    ev("agent.task_created", "c.csv", { task_id: "x", kind: "new_source_modeler" }),
    ev("agent.task_accepted", "c.csv", { task_id: "x", kind: "new_source_modeler" }),
    ev("agent.task_created", "c.csv", { task_id: "y", kind: "page_reader" }),
    ev("agent.task_rejected", "c.csv", { task_id: "y", kind: "page_reader" }),
    ev("agent.task_created", "c.csv", { task_id: "z", kind: "schema_mapper" }),
    ev("resolve.done", null, {}, "8 records -> 2 people"),
  ];
  const { files, globals } = groupEvents(events);

  it("groups per file in first-seen order and keeps global events apart", () => {
    expect(files.map((f) => f.fileName)).toEqual(["a.csv", "b.bin", "c.csv"]);
    expect(globals.map((g) => g.message)).toEqual(["go", "8 records -> 2 people"]);
  });
  it("collects winner, bids, tables and attaches mappings by table_id", () => {
    const a = files[0];
    expect(a.parser).toBe("csv");
    expect(a.score).toBe(0.97);
    expect(a.bids).toHaveLength(2);
    expect(a.tables).toHaveLength(1);
    expect(a.tables[0].rows).toBe(3);
    expect(a.tables[0].mapping?.template_id).toBe("hr_roster");
  });
  it("marks quarantine and agent states", () => {
    expect(files[1].quarantined).toBe(true);
    expect(files[2].agents.map((x) => x.state)).toEqual(["validator OK", "rejected", "waiting for agent"]);
  });
});

describe("pbj", () => {
  const csv = 'employee_id,person_id,facility_id,work_date,job_code,hours,status,note\n' +
    'E201,P-E201,FAC-BAY,2026-09-14,7,8.0,ready,\n' +
    'E202,P-E202,FAC-RVD,2026-09-14,10,8.0,needs_signoff,"paid 48, scheduled 40"\n';
  it("parses quoted fields", () => {
    const rows = parsePbj(csv);
    expect(rows).toHaveLength(2);
    expect(rows[1].note).toBe("paid 48, scheduled 40");
    expect(rows[0].note).toBe("");
  });
  it("filters by status", () => {
    const rows = parsePbj(csv);
    expect(filterPbj(rows, "needs_signoff").map((r) => r.employee_id)).toEqual(["E202"]);
    expect(filterPbj(rows, "all")).toHaveLength(2);
  });
});

describe("issues", () => {
  const mk = (fingerprint: string, severity: IssueListItem["severity"], title: string) => ({ fingerprint, severity, title }) as IssueListItem;
  const list = [mk("1", "LOW", "b"), mk("2", "CRITICAL", "z"), mk("3", "CRITICAL", "a"), mk("4", "INFO", "c")];
  it("sorts by severity then title", () => {
    expect(sortIssues(list).map((i) => i.fingerprint)).toEqual(["3", "2", "1", "4"]);
  });
  it("groups by severity, skipping empty groups", () => {
    expect(groupBySeverity(list).map(([s, items]) => [s, items.length])).toEqual([["CRITICAL", 2], ["LOW", 1], ["INFO", 1]]);
  });
});

describe("bucketCredentials", () => {
  const c = (id: string, days_left: number | null) => ({ credential_id: id, days_left }) as Credential;
  it("puts credentials in overdue / 30 / 60 / 90 and drops the rest", () => {
    const b = bucketCredentials([c("a", -1), c("b", 0), c("c", 30), c("d", 31), c("e", 60), c("f", 90), c("g", 91), c("h", null)]);
    expect(b.overdue.map((x) => x.credential_id)).toEqual(["a"]);
    expect(b.d30.map((x) => x.credential_id)).toEqual(["b", "c"]);
    expect(b.d60.map((x) => x.credential_id)).toEqual(["d", "e"]);
    expect(b.d90.map((x) => x.credential_id)).toEqual(["f"]);
  });
});

describe("parseHighlight", () => {
  it("turns the relative X-Highlight x,y,w,h into percentage CSS", () => {
    expect(parseHighlight("0.1,0.25,0.5,0.4")).toEqual({ left: "10%", top: "25%", width: "50%", height: "40%" });
  });
  it("returns null for a missing or malformed header", () => {
    expect(parseHighlight(null)).toBeNull();
    expect(parseHighlight("a,b")).toBeNull();
  });
});
