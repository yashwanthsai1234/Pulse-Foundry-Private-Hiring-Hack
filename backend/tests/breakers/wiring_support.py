"""Shared helpers for the W3-B1 wiring tests: real app + real pipeline through the HTTP API (TestClient)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sot.api.app import create_app
from tests.conftest import FIXTURES

E1 = FIXTURES / "example_e1"
E1_FILES = ["hr_roster.csv", "payroll.csv", "licenses.csv", "schedule.pdf"]


def make_client(settings, as_of: date = date(2026, 9, 21)):
    settings.as_of = as_of
    app = create_app(settings)
    return app, TestClient(app)


def upload(client, paths: list[Path], names: list[str] | None = None) -> str:
    files = [("files", ((names[i] if names else p.name), p.read_bytes())) for i, p in enumerate(paths)]
    r = client.post("/api/ingest", files=files)  # BackgroundTasks run before TestClient returns
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def sse_events(client, run_id: str) -> list[dict]:
    with client.stream("GET", f"/api/runs/{run_id}/events") as r:
        body = "".join(r.iter_text())
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def write_done(app, task_id: str, output: dict) -> None:
    s = app.state.settings
    (s.dir("agent_tasks/done") / f"{task_id}.json").write_text(json.dumps(output))


def pending_tasks(client, status="pending") -> list[dict]:
    return client.get(f"/api/agent-tasks?status={status}").json()


VENDOR_HDR = "Carrier,Coverage Kind,Cert No,Start,End,Rep Email,Premium Paid"
VENDOR_MAP = {"template_id": "vendor_credential",
              "column_map": {"Carrier": "org.name", "Coverage Kind": "credential.doc_type", "Cert No": "credential.number",
                             "Start": "credential.issued_on", "End": "credential.expires_on",
                             "Rep Email": "contact.email", "Premium Paid": None},
              "confidence": 0.9, "reasons": {"Carrier": "company names"}}
