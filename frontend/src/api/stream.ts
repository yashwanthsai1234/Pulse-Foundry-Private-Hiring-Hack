// One reconnecting EventSource for the whole app. The browser only retries by itself while the server keeps
// answering 200 text/event-stream, and it retries the ORIGINAL url, so we close on error and reopen with
// `since=<last seq>` ourselves; consumers also dedupe, so a replayed event is harmless.
// Sources:
// - https://html.spec.whatwg.org/multipage/server-sent-events.html (reconnection, Last-Event-ID, when the UA gives up)
// - https://developer.mozilla.org/en-US/docs/Web/API/EventSource
import { EVENT_TYPES, type PipelineEvent } from "./types";

interface Options { make?: (url: string) => EventSource; retryMs?: number }

/** Opens `url(since)`, calls `onEvent` per event (named SSE events need one listener per type). Returns a closer. */
export function openStream(url: (since: number) => string, onEvent: (e: PipelineEvent) => void, opts: Options = {}): () => void {
  const { make = (u) => new EventSource(u), retryMs = 1000 } = opts;
  let since = 0;
  let es: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const connect = () => {
    es = make(url(since));
    for (const t of EVENT_TYPES) {
      es.addEventListener(t, (m) => {
        const e = JSON.parse((m as MessageEvent).data) as PipelineEvent;
        since = Math.max(since, e.seq);
        onEvent(e);
      });
    }
    es.onerror = () => {
      es?.close();
      if (!stopped) timer = setTimeout(connect, retryMs);
    };
  };
  connect();
  return () => { stopped = true; clearTimeout(timer); es?.close(); };
}
