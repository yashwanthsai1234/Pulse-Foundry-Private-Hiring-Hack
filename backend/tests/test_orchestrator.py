"""Orchestrator with faked stages: event order, skip, quarantine, agent paths."""
import json

import pytest

from sot.pipeline.orchestrator import Pipeline
from tests.fakes import patch_stages

MAPPED = {"answer": {"template_id": "hr_roster", "column_map": {"a": "person.employee_id"}, "confidence": 0.9,
                     "reasons": {}}}


@pytest.fixture
def pipe(settings, db, monkeypatch):
    p = Pipeline(settings, db)
    p.calls = patch_stages(monkeypatch)
    return p


def write(tmp_path, name, content="x"):
    f = tmp_path / name
    f.write_text(content + name)
    return f


def types(pipe):
    return [e.type for e in pipe.bus.history]


def test_event_order_and_summary(pipe, tmp_path):
    s = pipe.ingest([write(tmp_path, "high.csv")], "r1")
    assert types(pipe) == ["run.started", "file.landed", "file.sniffed", "table.extracted", "table.mapped",
                           "normalize.done", "resolve.done", "truth.done", "checks.done", "run.completed"]
    msgs = {e.type: e.message for e in pipe.bus.history}
    assert msgs["file.sniffed"] == "high.csv → CSV (0.97): ',' gives 2 fields in 100% of rows"
    assert msgs["resolve.done"].startswith("resolve: 2 records → 2 people")
    assert (s.files, s.tables, s.records, s.persons, s.skipped) == (1, 1, 2, 2, 0)
    assert pipe.db.query("SELECT status FROM runs")[0]["status"] == "completed"
    assert pipe.db.query("SELECT count(*) n FROM events")[0]["n"] == len(pipe.bus.history)
    assert pipe.db.query("SELECT status FROM mappings")[0]["status"] == "mapped"


def test_known_file_is_skipped(pipe, tmp_path):
    f = write(tmp_path, "high.csv")
    pipe.ingest([f], "r1")
    s = pipe.ingest([f], "r2")
    assert s.skipped == 1 and s.files == 1
    assert [e.type for e in pipe.bus.history if e.run_id == "r2"][1] == "file.skipped"
    assert pipe.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 2


def test_quarantine_path(pipe, tmp_path):
    s = pipe.ingest([write(tmp_path, "junk.bin")], "r1")
    assert s.quarantined == 1 and "file.quarantined" in types(pipe) and "table.extracted" not in types(pipe)
    assert ("checks", ["FILE-QUARANTINED"]) in pipe.calls


def test_pending_agent_paths(pipe, tmp_path, settings):
    pipe.ingest([write(tmp_path, "mid.csv"), write(tmp_path, "low.csv")], "r1")
    kinds = {r["kind"] for r in pipe.db.query("SELECT kind FROM agent_tasks WHERE status = 'pending'")}
    assert kinds == {"schema_mapper", "new_source_modeler"}
    assert {r["status"] for r in pipe.db.query("SELECT status FROM mappings")} == {"pending_agent"}
    assert pipe.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 0
    assert ("checks", ["TABLE-UNMAPPED", "TABLE-UNMAPPED"]) in pipe.calls
    assert len(list(settings.dir("agent_tasks/pending").glob("t-*.json"))) == 2
    assert "table.unmapped" in types(pipe)


def finish_agent(pipe, settings, accept: bool, monkeypatch):
    monkeypatch.setattr("sot.agents.gateway.validate", lambda *a: (accept, [] if accept else ["bad map"]))
    [row] = pipe.db.query("SELECT task_id FROM agent_tasks")
    out = {"template_id": "hr_roster", "column_map": {"a": "person.employee_id", "b": None}, "confidence": 0.9,
           "reasons": {"a": "ids"}}
    (settings.dir("agent_tasks/done") / f"{row['task_id']}.json").write_text(json.dumps(out))
    pipe.poll_agents()


def test_agent_acceptance_triggers_rebuild(pipe, tmp_path, settings, monkeypatch):
    pipe.ingest([write(tmp_path, "mid.csv")], "r1")
    before = len(pipe.calls)
    finish_agent(pipe, settings, True, monkeypatch)
    assert pipe.db.query("SELECT status, source FROM mappings")[0] == {"status": "mapped", "source": "agent"}
    assert pipe.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 2
    assert pipe.calls[before][:2] == ("resolve", 2)
    assert pipe.calls[-1][0] == "checks" and "MAPPING-REVIEW" in pipe.calls[-1][1]
    assert "agent.task_accepted" in types(pipe)


def test_agent_rejection_makes_issue(pipe, tmp_path, settings, monkeypatch):
    pipe.ingest([write(tmp_path, "mid.csv")], "r1")
    finish_agent(pipe, settings, False, monkeypatch)
    assert "AGENT-REJECTED" in pipe.calls[-1][1] and pipe.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 0


def test_gray_pair_creates_adjudication_task(settings, db, tmp_path, monkeypatch):
    p = Pipeline(settings, db)
    patch_stages(monkeypatch, gray=True)
    p.ingest([write(tmp_path, "high.csv")], "r1")
    [t] = db.query("SELECT kind, ref, status FROM agent_tasks")
    assert t["kind"] == "identity_adjudicator" and "|" in t["ref"] and t["status"] == "pending"


def test_accepted_same_decision_becomes_extra_link(settings, db, tmp_path, monkeypatch):
    p = Pipeline(settings, db)
    calls = patch_stages(monkeypatch, gray=True)
    p.ingest([write(tmp_path, "high.csv")], "r1")
    monkeypatch.setattr("sot.agents.gateway.validate", lambda *a: (True, []))
    [t] = db.query("SELECT task_id FROM agent_tasks")
    (settings.dir("agent_tasks/done") / f"{t['task_id']}.json").write_text(
        json.dumps({"decision": "same", "confidence": 0.9, "reason": "same nurse"}))
    p.poll_agents()
    resolve_calls = [c for c in calls if c[0] == "resolve"]
    [link] = resolve_calls[-1][2]
    assert link.method == "agent" and link.prob == 0.95
    assert "ID-AGENT-LINK" in calls[-1][1]


def test_failure_emits_run_failed(pipe, tmp_path, monkeypatch):
    monkeypatch.setattr("sot.pipeline.orchestrator.run_checks", lambda *a: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        pipe.ingest([write(tmp_path, "high.csv")], "r1")
    assert types(pipe)[-1] == "run.failed"
    assert pipe.db.query("SELECT status FROM runs")[0]["status"] == "failed"
