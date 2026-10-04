import type { PipelineEvent } from "../api/types";

/** Appends `e` unless (run_id, seq) is already present (replays after a reconnect). */
export function addEvent(prev: PipelineEvent[], e: PipelineEvent): PipelineEvent[] {
  return prev.some((p) => p.seq === e.seq && p.run_id === e.run_id) ? prev : [...prev, e];
}

/** Events per run, newest run first (by first event); a late event joins the run it belongs to. */
export function groupByRun(events: PipelineEvent[]): { runId: string; events: PipelineEvent[] }[] {
  const by = new Map<string, PipelineEvent[]>();
  for (const e of events) by.set(e.run_id, [...(by.get(e.run_id) ?? []), e]);
  return [...by].map(([runId, evs]) => ({ runId, events: evs })).reverse();
}
