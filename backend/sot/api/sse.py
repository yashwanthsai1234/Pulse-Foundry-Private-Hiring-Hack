"""Server-sent events. Two streams over the same persisted events:

- one run (`/api/runs/{id}/events`): replay all of its events, then (if still running) live until it ends;
- all runs (`/api/events?since=<seq>`): replay everything after `since`, then live, never ends. Agent results
  arrive after run.completed, so the UI listens here; the client reconnects with the last seq it saw.

Sources:
- https://github.com/sysid/sse-starlette (EventSourceResponse: dict frames, pings, disconnect handling)
- https://html.spec.whatwg.org/multipage/server-sent-events.html (named events, reconnection)
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

from sot.core.models import Event

END_EVENTS = ("run.completed", "run.failed")


def _frame(ev: Event) -> dict:
    return {"event": ev.type, "data": ev.model_dump_json()}


async def _stream(request: Request, run_id: str | None, since: int) -> AsyncIterator[dict]:
    """run_id None = every run. Subscribing first means no event falls between replay and live."""
    bus, db = request.app.state.bus, request.app.state.db
    q = bus.subscribe(run_id or "*")
    try:
        where, params = ("seq > ?", [since]) if run_id is None else ("run_id = ? AND seq > ?", [run_id, since])
        last, ended = since, False
        for row in db.query(f"SELECT * FROM events WHERE {where} ORDER BY seq", params):
            ev = Event(**row)
            last, ended = ev.seq, ended or ev.type in END_EVENTS
            yield _frame(ev)  # replay the whole run, incl. agent events emitted after run.completed
        if run_id and (ended or db.query("SELECT 1 FROM runs WHERE run_id = ? AND status != 'running'", [run_id])):
            return  # the run is over: nothing more will come on this stream
        while True:
            ev = await q.get()
            if ev.seq <= last:
                continue
            last = ev.seq
            yield _frame(ev)
            if run_id and ev.type in END_EVENTS:
                return
    finally:
        bus.unsubscribe(run_id or "*", q)


def event_stream(request: Request, run_id: str | None = None, since: int = 0) -> EventSourceResponse:
    return EventSourceResponse(_stream(request, run_id, since))
