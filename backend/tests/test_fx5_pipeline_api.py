"""FX5: SPA fallback, global event stream, reset guard, crop edge cases, task expiry, PDF page routing, restarts."""
import asyncio
import json
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pymupdf
from fastapi.testclient import TestClient

from sot.api import app as app_module
from sot.api.app import create_app
from sot.api.sse import _stream
from sot.core.events import EventBus, db_persister, next_seq
from sot.pipeline.orchestrator import Pipeline
from tests.breakers.wiring_support import E1, make_client, upload


def frames(app, run_id, since, n):
    """The first n SSE frames of a stream (a global stream never ends on its own)."""
    async def go():
        gen = _stream(SimpleNamespace(app=app), run_id, since)
        return [await asyncio.wait_for(gen.__anext__(), 2) for _ in range(n)]
    return asyncio.run(go())


# ---- B1-01 SPA fallback ----
def test_spa_deep_link_serves_index_but_api_and_assets_stay_404(settings, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    c = TestClient(create_app(settings))
    assert 'id="root"' in c.get("/issues").text and 'id="root"' in c.get("/people/P-E1").text
    assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").json() == {"detail": "Not Found"}
    assert c.get("/assets/missing.js").status_code == 404


# ---- B1-02 global stream, seq across restarts ----
def test_global_stream_replays_since_and_delivers_events_after_run_completed(settings):
    app = create_app(settings)
    bus = app.state.bus
    bus.emit("r1", "run.started", "a")
    bus.emit("r1", "run.completed", "b")
    late = bus.emit("r1", "agent.task_accepted", "late")
    got = frames(app, None, since=1, n=2)  # skips seq 1, does not stop at run.completed
    assert [json.loads(f["data"])["seq"] for f in got] == [2, late.seq]


def test_run_stream_of_a_finished_run_without_end_event_terminates(settings):
    app = create_app(settings)
    app.state.db.insert("runs", [{"run_id": "r9", "started_at": datetime.now(), "status": "failed"}])
    assert frames_until_end(app, "r9") == []


def frames_until_end(app, run_id):
    async def go():
        return [f async for f in _stream(SimpleNamespace(app=app), run_id, 0)]
    return asyncio.run(asyncio.wait_for(go(), 2))


def test_event_seq_continues_after_restart(db):
    bus = EventBus(persist=db_persister(db))
    bus.emit("r", "log", "x")
    assert next_seq(db) == 2
    assert EventBus(persist=db_persister(db), first_seq=next_seq(db)).emit("r", "log", "y").seq == 2


def test_sse_unknown_run_is_404(settings):
    _, c = make_client(settings)
    assert c.get("/api/runs/run-nope/events").status_code == 404


# ---- B1-14 reset during a run ----
def test_reset_while_a_run_holds_the_lock_is_409(settings, monkeypatch):
    monkeypatch.setenv("SOT_ALLOW_RESET", "1")
    app, c = make_client(settings)
    held, release = threading.Event(), threading.Event()

    def hold():
        with app.state.pipeline.lock:
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    assert c.post("/api/reset").status_code == 409
    release.set()
    t.join()
    assert c.post("/api/reset").status_code == 200


# ---- B1-16 crop edge cases ----
def test_crop_inverted_box_nan_and_csv(settings):
    app, c = make_client(settings)
    upload(c, [E1 / "hr_roster.csv", E1 / "schedule.pdf"])
    pdf = app.state.db.query("SELECT file_id FROM files WHERE file_name = 'schedule.pdf'")[0]["file_id"]
    csv = app.state.db.query("SELECT file_id FROM files WHERE file_name = 'hr_roster.csv'")[0]["file_id"]
    r = c.get(f"/api/evidence/crop?file_id={pdf}&page=1&x0=300&top=300&x1=100&bottom=100")
    hx, hy, hw, hh = (float(v) for v in r.headers["X-Highlight"].split(","))
    assert r.status_code == 200 and 0 <= hx and 0 <= hy and hx + hw <= 1.0001 and hy + hh <= 1.0001
    assert c.get(f"/api/evidence/crop?file_id={pdf}&page=1&x0=nan&top=1&x1=10&bottom=10").status_code == 400
    assert c.get(f"/api/evidence/crop?file_id={csv}&page=1&x0=1&top=1&x1=10&bottom=10").status_code == 415


# ---- B-014 expiry, B1-09, B1-10 ----
def test_unanswered_task_expires_into_agent_unavailable(settings, db):
    settings.values["agent.expire_min"] = 5
    p = Pipeline(settings, db)
    task = p.gateway.make_task("schema_mapper", "r1", "tbl:0:0", {"file_name": "x.csv"})
    p.gateway.submit(task)
    assert p.gateway.poll() == []  # not old enough
    db.execute("UPDATE agent_tasks SET created_at = ?", [datetime.now() - timedelta(minutes=6)])
    [res] = p.gateway.poll()
    assert not res.accepted and "no result after 5 minutes" in res.validator_notes[0]
    assert db.query("SELECT status FROM agent_tasks")[0]["status"] == "expired"
    assert not (settings.dir("agent_tasks/pending") / f"{task.task_id}.json").exists()
    p.rebuild("r1")
    assert [i.check_id for i in __import__("sot.store.repo", fromlist=["x"]).load_issues(db)] == ["AGENT-UNAVAILABLE"]


# ---- B3-02 / B3-04 / B-012 / B1-15 / B1-20 ----
def run_one(settings, path):
    settings.agents = "queue"
    settings.as_of = date(2026, 9, 21)
    p = Pipeline(settings)
    p.ingest([path], "r1")
    return p


def pdf_with(tmp_path, text, name="p.pdf"):
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 500, 400), text)
    doc.save(tmp_path / name)
    return tmp_path / name


def test_text_page_without_table_gets_an_issue_but_no_task_unless_it_looks_like_a_schedule(settings, tmp_path):
    p = run_one(settings, pdf_with(tmp_path, "Staffing memo: please submit timesheets by Friday."))
    assert [r["check_id"] for r in p.db.query("SELECT check_id FROM issues")] == ["PARSE-PDF-LOW-CONFIDENCE"]
    assert p.db.query("SELECT count(*) n FROM agent_tasks")[0]["n"] == 0


def test_schedule_looking_page_without_table_goes_to_page_reader_with_hints(settings, tmp_path):
    text = "Week schedule for the nursing floor, posted by the unit manager.\n" + "\n".join(
        f"{d} Sofia Reyes 7a-3p" for d in ("Mon", "Tue", "Wed", "Thu", "Fri"))
    p = run_one(settings, pdf_with(tmp_path, text))
    [t] = p.db.query("SELECT payload FROM agent_tasks WHERE kind = 'page_reader'")
    payload = t["payload"]
    assert {"image", "page", "expected_header", "facility_vocab", "legend_hint"} <= set(payload)
    assert (settings.dir("agent_tasks/files") / payload["image"].rsplit("/", 1)[1]).exists()
    assert "PARSE-PDF-LOW-CONFIDENCE" in [r["check_id"] for r in p.db.query("SELECT check_id FROM issues")]


def test_header_only_csv_creates_no_agent_task(settings, tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("a,b,c\n")
    p = run_one(settings, f)
    assert p.db.query("SELECT count(*) n FROM agent_tasks")[0]["n"] == 0
    assert [r["check_id"] for r in p.db.query("SELECT check_id FROM issues")] == ["TABLE-EMPTY"]


# ---- B1-18 as-of survives a restart ----
def test_as_of_put_is_kept_after_restart(settings):
    _, c = make_client(settings)
    assert c.put("/api/settings", json={"as_of": "2027-01-02"}).status_code == 200
    settings.as_of = date(2020, 1, 1)
    assert create_app(settings).state.settings.as_of == date(2027, 1, 2)
