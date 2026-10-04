"""A browser tab that outlived a server reset reconnects with a `since` ahead of the new event log."""
from sot.api.sse import replay_since
from sot.core.events import EventBus, db_persister


def test_client_ahead_of_the_log_replays_from_the_start(db):
    bus = EventBus(persist=db_persister(db))
    bus.emit("r1", "run.started", "run started")
    bus.emit("r1", "run.completed", "done")
    assert replay_since(db, 999) == 0      # server was reset: replay everything
    assert replay_since(db, 1) == 1        # normal reconnect: continue after the last seen event
    assert replay_since(db, 0) == 0
