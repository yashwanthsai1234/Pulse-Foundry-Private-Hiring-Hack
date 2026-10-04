import { openStream } from "./stream";
import type { PipelineEvent } from "./types";

class FakeES {
  static all: FakeES[] = [];
  listeners: Record<string, (m: MessageEvent) => void> = {};
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeES.all.push(this); }
  addEventListener(t: string, f: (m: MessageEvent) => void) { this.listeners[t] = f; }
  close() { this.closed = true; }
  push(seq: number, type = "log") { this.listeners[type]?.({ data: JSON.stringify({ run_id: "r", seq, type, message: "", data: {} }) } as MessageEvent); }
}

describe("openStream", () => {
  beforeEach(() => { FakeES.all = []; vi.useFakeTimers(); });
  afterEach(() => vi.useRealTimers());
  const open = (got: PipelineEvent[]) =>
    openStream((since) => `/api/events?since=${since}`, (e) => got.push(e), { make: (u) => new FakeES(u) as unknown as EventSource, retryMs: 500 });

  it("starts at since=0 and reopens after an error with the last seen seq", () => {
    const got: PipelineEvent[] = [];
    open(got);
    expect(FakeES.all[0].url).toBe("/api/events?since=0");
    FakeES.all[0].push(4); FakeES.all[0].push(7, "run.completed");
    FakeES.all[0].onerror!();
    expect(FakeES.all[0].closed).toBe(true);
    vi.advanceTimersByTime(500);
    expect(FakeES.all[1].url).toBe("/api/events?since=7");
    expect(got.map((e) => e.seq)).toEqual([4, 7]);
  });

  it("close stops reconnecting", () => {
    const close = open([]);
    FakeES.all[0].onerror!();
    close();
    vi.advanceTimersByTime(5000);
    expect(FakeES.all).toHaveLength(1);
  });
});
