import { addEvent, groupByRun } from "./eventLog";
import type { PipelineEvent } from "../api/types";

const ev = (run_id: string, seq: number): PipelineEvent => ({ run_id, seq, ts: "", type: "log", message: "", data: {} });

describe("eventLog", () => {
  it("dedupes by (run_id, seq)", () => {
    const a = ev("r1", 1);
    expect(addEvent([a], ev("r1", 1))).toEqual([a]);
    expect(addEvent([a], ev("r2", 1))).toHaveLength(2);
  });
  it("groups by run, newest run first; late events join their own run", () => {
    const events = [ev("r1", 1), ev("r2", 2), ev("r1", 3)];
    const runs = groupByRun(events);
    expect(runs.map((r) => r.runId)).toEqual(["r2", "r1"]);
    expect(runs[1].events.map((e) => e.seq)).toEqual([1, 3]);
  });
});
