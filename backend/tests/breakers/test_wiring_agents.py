"""W3-B1: agent queue + SSE wiring with a simulated Sonnet subagent (writes done/<task_id>.json)."""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from sot.config import REPO_DIR
from tests.breakers.wiring_support import (E1, E1_FILES, VENDOR_HDR, VENDOR_MAP, make_client, pending_tasks, sse_events,
                                           upload, write_done)

ASOF = date(2026, 10, 4)


def vendor_csv(tmp_path, name, rows, header=VENDOR_HDR):
    p = tmp_path / name
    p.write_text(header + "\n" + "\n".join(rows) + "\n")
    return p


@pytest.fixture
def vendor_world(settings, tmp_path):
    app, c = make_client(settings, ASOF)
    upload(c, [E1 / f for f in E1_FILES])
    p = vendor_csv(tmp_path, "vendors2.csv", [
        "Zenith Rehab Partners,General Liability,ZR-9001,2025-10-20,2026-10-16,rep@zenith.example,1200",
        "Orchid Nursing Pool,Workers Comp,ON-7742,2025-11-02,2027-02-01,rep@orchid.example,900",
        "Lakeview Dialysis Svc,Professional Liability,LD-3310,2025-07-09,2027-07-08,rep@lakeview.example,1500"])
    run = upload(c, [p])
    return app, c, run, p


def test_vendor_file_valid_agent_output_is_accepted_without_restart(vendor_world):
    app, c, run, _ = vendor_world
    (t,) = pending_tasks(c)
    assert t["kind"] == "schema_mapper"
    write_done(app, t["task_id"], VENDOR_MAP)
    app.state.pipeline.poll_agents()  # what the lifespan poller does every second
    assert [x["status"] for x in c.get("/api/agent-tasks").json()] == ["accepted"]
    exp = c.get("/api/issues?check_id=LIC-EXPIRING").json()
    assert any("Zenith" in i["message"] for i in exp), exp


def test_agent_events_after_run_completed_reach_the_sse_stream(vendor_world):
    """The UI closes the EventSource on run.completed and the backend ends the replay there, so
    agent.task_accepted (emitted later with the same run_id) can never reach the UI."""
    app, c, run, _ = vendor_world
    (t,) = pending_tasks(c)
    write_done(app, t["task_id"], VENDOR_MAP)
    app.state.pipeline.poll_agents()
    types = [e["type"] for e in sse_events(c, run)]
    assert "agent.task_accepted" in types, types


def test_agent_events_carry_file_name_so_the_feed_can_group_them(vendor_world):
    _, c, run, _ = vendor_world
    ev = [e for e in sse_events(c, run) if e["type"].startswith("agent.")]
    assert ev and all(e["file_name"] for e in ev), [(e["type"], e["file_name"]) for e in ev]


def test_mapper_candidates_offer_vendor_credential(vendor_world):
    _, c, _, _ = vendor_world
    (t,) = pending_tasks(c)
    ids = [x["id"] for x in t["payload"]["template_candidates"]]
    assert "vendor_credential" in ids, ids


def test_agent_accepted_contract_is_reused_for_the_same_header(vendor_world, tmp_path):
    app, c, _, _ = vendor_world
    (t,) = pending_tasks(c)
    write_done(app, t["task_id"], VENDOR_MAP)
    app.state.pipeline.poll_agents()
    p = vendor_csv(tmp_path, "vendors7.csv", [
        "Birch Hospice Care,General Liability,BH-90017,2025-10-20,2026-11-20,rep@birch.example,1200",
        "Cedar Imaging,Workers Comp,CI-70211,2025-11-02,2027-02-01,rep@cedar.example,900"])
    upload(c, [p])
    assert pending_tasks(c) == [], "same header as an accepted agent contract still created a new task (drift)"


def test_pending_file_is_removed_once_the_task_is_accepted(vendor_world):
    """/process-agent-tasks lists pending/ and would re-dispatch accepted tasks."""
    app, c, _, _ = vendor_world
    (t,) = pending_tasks(c)
    write_done(app, t["task_id"], VENDOR_MAP)
    app.state.pipeline.poll_agents()
    assert not (app.state.settings.dir("agent_tasks/pending") / f"{t['task_id']}.json").exists()


def test_invalid_done_files_become_agent_rejected_issues(settings, tmp_path):
    app, c = make_client(settings, ASOF)
    for i, bad in enumerate([{"template_id": "vendor_credential", "column_map": {}, "confidence": 5, "reasons": {}, "x": 1},
                             {**VENDOR_MAP, "column_map": {**VENDOR_MAP["column_map"], "Cert No": "credential.expires_on"}}]):
        hdr = VENDOR_HDR.replace("Carrier", f"Carrier{i}")
        upload(c, [vendor_csv(tmp_path, f"v{i}.csv", ["Acme,General Liability,AC-1001,2025-10-20,2026-10-16,a@b.example,1"], hdr)])
        (t,) = pending_tasks(c)
        write_done(app, t["task_id"], bad)
        app.state.pipeline.poll_agents()
        assert pending_tasks(c) == []
    rejected = c.get("/api/issues?check_id=AGENT-REJECTED").json()
    assert len(rejected) == 2 and all(i["severity"] == "HIGH" for i in rejected)
    assert any("schema:" in i["message"] for i in rejected) and any("validator" in i["message"] for i in rejected)


@pytest.mark.parametrize("number", ["NTL-2025-0042", "GL-2025-0042", "POL/778812", "778812"])
def test_realistic_policy_numbers_pass_the_policy_number_validator(settings, number):
    from sot.core.pack import load_pack
    from sot.semantic.validators import build_validators
    pack = load_pack(settings.pack_dir)
    v = build_validators(pack)["credential.policy_number"]  # credential.number stays strict (licence numbers)
    assert v(number), f"{number!r} rejected by credential.policy_number validator -> every agent mapping of such a file is AGENT-REJECTED"


def test_page_reader_payload_has_the_keys_its_prompt_promises(settings, tmp_path):
    import pymupdf
    app, c = make_client(settings, ASOF)
    src, out = pymupdf.open(E1 / "schedule.pdf"), pymupdf.open()
    for pg in src:
        pm = pg.get_pixmap(dpi=60)
        out.new_page(width=pg.rect.width, height=pg.rect.height).insert_image(pg.rect, pixmap=pm)
    out.save(tmp_path / "scan.pdf")
    upload(c, [tmp_path / "scan.pdf"])
    import json
    tasks = [json.loads(f.read_text()) for f in app.state.settings.dir("agent_tasks/pending").glob("*.json")]
    tasks = [t for t in tasks if t["kind"] == "page_reader"]
    assert tasks
    promised = set(re.findall(r"`(\w+)`", tasks[0]["instructions"].split("The payload has")[1].split("Rules")[0]))
    assert promised <= set(tasks[0]["payload"]) | {"image"}, promised - set(tasks[0]["payload"])


def test_orphaned_running_run_is_closed_on_startup(settings):
    """A crash/kill during a run leaves runs.status='running'; the UI replays the newest run and its SSE never ends."""
    from sot.api.app import create_app
    app = create_app(settings)
    app.state.db.insert("runs", [{"run_id": "run-orphan", "started_at": datetime.now(), "status": "running"}])
    app2 = create_app(settings)  # a restart on the same database
    status = app2.state.db.query("SELECT status FROM runs WHERE run_id = 'run-orphan'")[0]["status"]
    assert status != "running"


def test_slash_command_does_not_hardcode_a_machine_path():
    text = (REPO_DIR / ".claude" / "commands" / "process-agent-tasks.md").read_text()
    assert "/Users/" not in text, "absolute path of the author's machine is baked into the command"
