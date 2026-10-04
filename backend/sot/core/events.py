"""In-process event bus. Events are persisted (for replay) and fanned out to SSE subscribers.

The pipeline runs in a worker thread while subscribers live on the API's event loop, so delivery goes
through loop.call_soon_threadsafe (asyncio.Queue is not thread-safe).

Sources:
- https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe
- https://docs.python.org/3/library/asyncio-dev.html#concurrency-and-multithreading
"""
from __future__ import annotations

import asyncio
import itertools
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sot.core.models import Event, EventType
from sot.store.db import DB


def next_seq(db: DB) -> int:
    return (db.query("SELECT max(seq) m FROM events")[0]["m"] or 0) + 1


def db_persister(db: DB) -> Callable[[Event], None]:
    """Persist callback writing every event to the events table (replayed after a page reload)."""
    return lambda ev: db.insert("events", [ev.model_dump()])


class EventBus:
    def __init__(self, persist: Callable[[Event], None] | None = None, first_seq: int = 1):
        """first_seq: continue after the last persisted event, so seq stays increasing across restarts."""
        self._persist = persist
        self._lock = threading.Lock()  # seq order = persisted order = delivery order, whatever thread emits
        self._subs: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Event]]]] = {}
        self._seq = itertools.count(first_seq)
        self.history: list[Event] = []

    def emit(self, run_id: str, type: EventType, message: str, file_name: str | None = None, **data: Any) -> Event:
        with self._lock:
            ev = Event(run_id=run_id, seq=next(self._seq), ts=datetime.now(), type=type,
                       file_name=file_name, message=message, data=data)
            self.history.append(ev)
            if self._persist:
                self._persist(ev)
            for loop, q in list(self._subs.get(run_id, [])) + list(self._subs.get("*", [])):
                loop.call_soon_threadsafe(q.put_nowait, ev)
        return ev

    def subscribe(self, run_id: str = "*") -> asyncio.Queue[Event]:
        """Call from the loop that will consume the queue."""
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subs.setdefault(run_id, []).append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[Event]) -> None:
        self._subs[run_id] = [s for s in self._subs.get(run_id, []) if s[1] is not q]
