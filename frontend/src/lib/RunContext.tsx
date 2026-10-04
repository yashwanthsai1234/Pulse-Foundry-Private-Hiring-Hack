// Global event context: ONE app-wide event stream (every run, including agent events that arrive after
// run.completed). Holds the deduped event log and a `version` counter that bumps on events that change data,
// so pages refetch (no polling).
// Sources:
// - https://react.dev/reference/react/createContext
// - https://react.dev/learn/synchronizing-with-effects (effect cleanup closes the stream)
// - https://html.spec.whatwg.org/multipage/server-sent-events.html (reconnect semantics, see api/stream.ts)
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { openEvents } from "../api/client";
import type { PipelineEvent } from "../api/types";
import { addEvent } from "./eventLog";

interface RunState { events: PipelineEvent[]; version: number; refresh: () => void }

const Ctx = createContext<RunState | null>(null);
const REFETCH_ON = new Set(["run.completed", "run.failed", "agent.task_accepted", "agent.task_rejected"]);
const DEBOUNCE_MS = 100; // a replay delivers many such events at once; refetch once

export function RunProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [version, setVersion] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const refresh = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setVersion((v) => v + 1), DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    const close = openEvents((e) => {
      setEvents((prev) => addEvent(prev, e));
      if (REFETCH_ON.has(e.type)) refresh();
    });
    return () => { close(); clearTimeout(timer.current); };
  }, [refresh]);

  return <Ctx.Provider value={{ events, version, refresh }}>{children}</Ctx.Provider>;
}

export function useRun(): RunState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useRun outside RunProvider");
  return v;
}
