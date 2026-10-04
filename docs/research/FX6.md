# FX6 front end (wave 4)

## Sources
- https://html.spec.whatwg.org/multipage/server-sent-events.html : the browser stops reconnecting on any non-200 or wrong content type, and retries the ORIGINAL URL (with `Last-Event-ID` only if the server sends `id:`). Decision: `api/stream.ts` closes on error and reopens `/api/events?since=<last seq>` itself after 1 s; consumers dedupe by (run_id, seq) so a replay is harmless.
- https://developer.mozilla.org/en-US/docs/Web/API/EventSource : named SSE events need one `addEventListener` per type (kept).
- https://react.dev/reference/react/createContext, https://react.dev/learn/synchronizing-with-effects : one provider, one effect that opens and closes the stream.
- https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary : page-level error boundary.

## Changes
- B1-02: one global stream (`openEvents`), `RunProvider` no longer has `startRun`; refetch (debounced 100 ms) on run.completed, run.failed, agent.task_accepted, agent.task_rejected. Ingest feed groups events by run_id (newest run open), so late agent events land in their own run. Mock mode: `mockIngest` replays fixtures on a mock global stream.
- B1-10: `groupEvents` already groups by `file_name`; the chip appears now that the backend sets it (existing test covers it).
- B1-11: `SourceRow` component (raw row mini table, `loc.col` cell highlighted, "row N" caption); works for claim and cell items.
- Errors/empty: `ApiError` inline alert on every page and action, empty-state text, `ErrorBoundary`, catch-all not-found route. Backend outage shows a banner.
- Deep links: routes are client-side (BrowserRouter); Vite `base` is `/`, so assets resolve from nested paths. Needs the backend SPA fallback (FX5 B1-01) to serve index.html for non-/api paths.

## Needs from backend
`GET /api/events?since=N` returns events with seq > N (replay) then live, `event: <type>` lines, never ends. seq is the process-wide counter, so after a server restart the counter restarts; the UI dedupes by (run_id, seq) and reload sends since=0.
