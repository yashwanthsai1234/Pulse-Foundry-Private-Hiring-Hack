"""API via TestClient: ingest upload, SSE replay, issues, evidence crop, reads, reset."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sot.api.app import create_app
from sot.core.models import FileRef
from sot.store import repo
from tests.conftest import FIXTURES


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def seed_issue(app, fp="fp1"):
    app.state.db.insert("issues", [{
        "fingerprint": fp, "check_id": "LIC-EXPIRED", "severity": "HIGH", "title": "Expired", "message": "m",
        "entity_ids": ["P-E1"], "evidence": [{"kind": "note", "label": "l", "text": "t", "raw": {"a": "1"}}],
        "status": "open", "first_seen_run": "r1", "last_seen_run": "r1", "active": True}])


def test_ingest_uploads_files_and_runs_pipeline(app, client):
    seen = {}
    app.state.pipeline.ingest = lambda paths, run_id: seen.update(paths=paths, run_id=run_id)
    names = ["hr_roster.csv", "licenses.csv", "payroll.csv", "schedule.pdf"]
    files = [("files", (n, (FIXTURES / "readme_sample" / n).read_bytes())) for n in names]
    r = client.post("/api/ingest", files=files)
    assert r.status_code == 200 and r.json()["run_id"] == seen["run_id"]
    assert [p.name for p in seen["paths"]] == names
    assert seen["paths"][0].read_bytes() == (FIXTURES / "readme_sample" / "hr_roster.csv").read_bytes()
    assert client.post("/api/ingest").status_code == 400


def test_sse_replays_persisted_events_until_run_ends(app, client):
    bus = app.state.bus
    bus.emit("r1", "run.started", "run started")
    bus.emit("r1", "file.sniffed", "hr_roster.csv → CSV (0.97)", "hr_roster.csv", parser="csv")
    bus.emit("r2", "run.started", "other run")
    bus.emit("r1", "run.completed", "done")
    with client.stream("GET", "/api/runs/r1/events") as r:
        body = "".join(r.iter_text())
    assert body.count("event: ") == 3 and "event: file.sniffed" in body and "other run" not in body
    data = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
    assert data[1]["data"] == {"parser": "csv"} and data[1]["file_name"] == "hr_roster.csv"


def test_runs_and_summary(app, client):
    app.state.db.insert("runs", [{"run_id": "r1", "started_at": datetime.now(), "status": "completed",
                                  "summary": json.dumps({"skipped": 2})}])
    seed_issue(app)
    assert client.get("/api/runs").json()[0]["file_count"] == 0
    s = client.get("/api/summary").json()
    assert s["skipped"] == 2 and s["issues_by_severity"] == {"HIGH": 1} and s["agent_tasks"] == {}
    assert "run_id" not in s


def test_issue_list_detail_and_patch(app, client):
    seed_issue(app)
    app.state.db.insert("persons", [{"person_id": "P-E1", "employee_id": "E1", "has_hr": True,
                                     "display_name": "Ana Cruz"}])
    [item] = client.get("/api/issues", params={"severity": "HIGH"}).json()
    assert item["evidence_count"] == 1 and item["person_name"] == "Ana Cruz" and "evidence" not in item
    assert client.get("/api/issues", params={"status": "resolved"}).json() == []
    detail = client.get("/api/issues/fp1").json()
    assert detail["evidence"][0]["raw"] == {"a": "1"} and detail["person_name"] == "Ana Cruz"
    r = client.patch("/api/issues/fp1", json={"status": "acknowledged"})
    assert r.json()["status"] == "acknowledged" and r.json()["evidence"]
    assert client.patch("/api/issues/fp1", json={"status": "bogus"}).status_code == 422
    assert client.patch("/api/issues/nope", json={"status": "open"}).status_code == 404


def test_evidence_crop_returns_png_and_highlight(app, client, e1_dir):
    f = e1_dir / "schedule.pdf"
    ref = FileRef(file_id="abc", file_name="schedule.pdf", path=str(f), size=1,
                                                received_at=datetime.now())
    repo.save_file(app.state.db, ref, "r1", "extracted")
    q = {"file_id": "abc", "page": 1, "x0": 100, "top": 100, "x1": 160, "bottom": 120}
    r = client.get("/api/evidence/crop", params=q)
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    x, y, w, h = map(float, r.headers["X-Highlight"].split(","))
    assert 0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1
    assert client.get("/api/evidence/crop", params={**q, "page": 99}).status_code == 404
    assert client.get("/api/evidence/crop", params={**q, "file_id": "zzz"}).status_code == 404


def test_people_shifts_credentials(app, client):
    db = app.state.db
    db.insert("persons", [{"person_id": "P-E1", "employee_id": "E1", "has_hr": True, "display_name": "Ana Cruz",
                           "role": "RN", "home_facility_id": "FAC-BAY"}])
    db.insert("credentials", [{"credential_id": "c1", "holder_type": "person", "holder_id": "P-E1",
                               "holder_name": "Ana Cruz", "credential_type": "RN", "number": "RN-1",
                               "expires_on": date(2026, 10, 10)}])
    db.insert("shifts", [{"shift_id": "s1", "person_id": "P-E1", "facility_id": "FAC-BAY", "role": "RN",
                          "work_date": date(2026, 10, 5), "hours": 8.0, "record_id": "x:1", "loc": {}}])
    db.insert("shifts_silver", [{"shift_id": "s1", "record_id": "x:1", "token": "7a-3p", "work_date": date(2026, 10, 5)}])
    [p] = client.get("/api/people", params={"q": "ana"}).json()
    assert p["issue_count"] == 0
    d = client.get("/api/people/P-E1").json()
    assert d["person"]["display_name"] == "Ana Cruz" and d["credentials"][0]["days_left"] is not None
    assert d["shifts"][0]["token"] == "7a-3p"
    grid = client.get("/api/shifts").json()
    [fac] = grid["facilities"]
    assert grid["days"] == ["2026-10-05"] and fac["rn_coverage"] == {"2026-10-05": 8.0}
    assert fac["rows"][0]["cells"]["2026-10-05"] == {"token": "7a-3p", "hours": 8.0, "license_valid": True}
    assert [c["credential_id"] for c in client.get("/api/credentials", params={"horizon_days": 3650}).json()] == ["c1"]
    assert client.get("/api/people/nope").status_code == 404


def test_agent_tasks_and_settings(app, client):
    app.state.db.insert("agent_tasks", [{"task_id": "t-1", "kind": "schema_mapper", "run_id": "r1", "ref": "x",
                                         "status": "pending", "payload": {"a": 1}, "created_at": datetime.now()}])
    assert client.get("/api/agent-tasks", params={"status": "pending"}).json()[0]["payload"] == {"a": 1}
    assert client.get("/api/agent-tasks", params={"status": "done"}).json() == []
    assert "as_of" in client.get("/api/settings").json()
    assert client.put("/api/settings", json={"as_of": "2026-01-02"}).json()["as_of"] == "2026-01-02"


def test_reset_needs_env_flag(app, client, monkeypatch, settings):
    seed_issue(app)
    settings.dir("landing")
    monkeypatch.delenv("SOT_ALLOW_RESET", raising=False)
    assert client.post("/api/reset").status_code == 403
    monkeypatch.setenv("SOT_ALLOW_RESET", "1")
    assert client.post("/api/reset").status_code == 200
    assert client.get("/api/issues").json() == [] and not (settings.runtime / "landing").exists()


def test_lifespan_polls_agent_results(app):
    polled = []
    app.state.pipeline.poll_agents = lambda: polled.append(1)
    import time
    with TestClient(app):
        time.sleep(1.5)
    assert polled


def test_bus_delivers_from_worker_thread_to_loop_subscribers():
    import asyncio
    import threading

    from sot.core.events import EventBus

    async def main():
        bus = EventBus()
        q = bus.subscribe("r1")
        threading.Thread(target=bus.emit, args=("r1", "log", "from thread")).start()
        return (await asyncio.wait_for(q.get(), 2)).message

    assert asyncio.run(main()) == "from thread"
