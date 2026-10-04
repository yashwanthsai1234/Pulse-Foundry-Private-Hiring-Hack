"""Agent gateway: queue round trip, schema and validator rejection, cache, executors."""
import json
from datetime import datetime

import polars as pl
import pytest

from sot.agents.executors import ClaudeCliExecutor, OffExecutor, QueueExecutor, make_executor
from sot.agents.gateway import AgentGateway
from sot.core.events import EventBus
from sot.core.models import ColumnProfile, ExtractionInfo, FileRef, Mapping, RawTable

COLS = {"LicNo": "credential.number", "Holder": "person.full_name", "Kind": "credential.type",
        "Expires": "credential.expires_on"}


class FakeCtx:
    """Stands in for ValidationContext: profiles and classification come from the test."""

    def __init__(self, pack, settings, hits=1.0, classified=0.9, fields=None):
        self.pack, self.settings, self.hits, self.classified, self.fields = pack, settings, hits, classified, fields or {}

    def table(self, table_id):
        f = FileRef(file_id="f" * 64, file_name="x.csv", path="x", size=1, received_at=datetime.now())
        return RawTable(table_id=table_id, file=f, parser="csv", header=list(COLS),
                        df=pl.DataFrame({c: ["a"] for c in COLS}), extraction=ExtractionInfo(method="csv", score=1))

    def profiles(self, table_id):
        return [ColumnProfile(column=c, index=i, n=1, null_ratio=0, distinct=1, inferred_type="string", sample=["a"],
                              validator_hits={f: self.hits}) for i, (c, f) in enumerate(COLS.items())]

    def classify(self, table_id, forced):
        return Mapping(table_id=table_id, template_id="license", confidence=self.classified, matches=[],
                       unmapped_columns=[], missing_required=[], source="agent")

    def record_fields(self, record_id):
        return self.fields[record_id]


GOOD = {"template_id": "license", "column_map": COLS, "confidence": 0.9, "reasons": {c: "ok" for c in COLS}}


@pytest.fixture
def gw(db, settings, pack):
    g = AgentGateway(db, settings, EventBus())
    g.ctx = FakeCtx(pack, settings)
    g.accepted = []
    g.on_accept = lambda task, out: g.accepted.append(task.task_id)
    return g


def submit(gw, payload=None):
    task = gw.make_task("schema_mapper", "r1", "tbl:0:0", payload or {"file_name": "x.csv"})
    assert gw.submit(task) is None
    return task


def answer(task, output):
    open(task.output_path, "w").write(json.dumps(output))


def status(db, task):
    return db.query("SELECT status, validator_notes FROM agent_tasks WHERE task_id = ?", [task.task_id])[0]


def test_task_has_prompt_version_schema_and_stable_id(gw):
    a = gw.make_task("schema_mapper", "r1", "t", {"x": 1})
    b = gw.make_task("schema_mapper", "r2", "other", {"x": 1})
    assert a.prompt_version == "1" and a.task_id == b.task_id and a.task_id.startswith("t-")
    assert "column_map" in a.output_schema["properties"] and a.output_path.endswith(f"done/{a.task_id}.json")


def test_queue_round_trip(gw, db, settings):
    task = submit(gw)
    pending = settings.dir("agent_tasks/pending") / f"{task.task_id}.json"
    assert json.loads(pending.read_text())["kind"] == "schema_mapper"
    assert status(db, task)["status"] == "pending" and gw.poll() == []
    answer(task, GOOD)
    [res] = gw.poll()
    assert res.accepted and status(db, task)["status"] == "accepted" and gw.accepted == [task.task_id]
    assert db.query("SELECT count(*) n FROM agent_cache")[0]["n"] == 1
    assert gw.poll() == []  # already handled
    assert [e.type for e in gw.bus.history] == ["agent.task_created", "agent.task_done", "agent.task_accepted"]


def test_schema_rejection(gw, db):
    task = submit(gw)
    answer(task, {"template_id": "license"})
    [res] = gw.poll()
    assert not res.accepted and res.validator_notes[0].startswith("schema:")
    assert status(db, task)["status"] == "rejected" and gw.accepted == []


def test_validator_rejection(gw, db, pack, settings):
    gw.ctx = FakeCtx(pack, settings, hits=0.3)
    task = submit(gw)
    answer(task, GOOD)
    [res] = gw.poll()
    assert not res.accepted and "validator" in res.validator_notes[0]
    assert status(db, task)["status"] == "rejected" and db.query("SELECT count(*) n FROM agent_cache")[0]["n"] == 0


def test_missing_required_field_rejected(gw):
    task = submit(gw)
    answer(task, {**GOOD, "column_map": {**COLS, "Expires": None}})
    [res] = gw.poll()
    assert not res.accepted and "credential.expires_on" in res.validator_notes[0]


def test_reclassification_below_agent_min_rejected(gw, pack, settings):
    gw.ctx = FakeCtx(pack, settings, classified=0.2)
    task = submit(gw)
    answer(task, GOOD)
    assert not gw.poll()[0].accepted


def test_cache_hit_applies_without_new_file(gw, settings):
    task = submit(gw)
    answer(task, GOOD)
    gw.poll()
    pending = settings.dir("agent_tasks/pending") / f"{task.task_id}.json"
    assert not pending.exists()  # judged tasks leave pending/
    assert gw.submit(gw.make_task("schema_mapper", "r2", "tbl:0:0", {"file_name": "x.csv"})) == GOOD
    assert not pending.exists() and gw.accepted == [task.task_id, task.task_id]


def test_resubmitting_pending_task_does_not_duplicate(gw, db):
    submit(gw)
    submit(gw)
    assert db.query("SELECT count(*) n FROM agent_tasks")[0]["n"] == 1


def test_submit_completes_a_bare_task(gw):
    bare = gw.make_task("page_reader", "r1", "f:1", {"image": "/x/p1.png", "page": 1}).model_copy(
        update={"instructions": "", "output_schema": {}, "prompt_version": "?"})
    gw.submit(bare)
    queued = json.loads(open(gw.executor.settings.dir("agent_tasks/pending") / f"{bare.task_id}.json").read())
    assert queued["input_files"] == ["/x/p1.png"] and queued["instructions"].startswith("prompt_version")


def test_identity_same_rejected_on_cannot_link(gw, db, pack, settings):
    gw.ctx = FakeCtx(pack, settings, fields={"a": {"person.employee_id": "E1"}, "b": {"person.employee_id": "E2"}})
    task = gw.make_task("identity_adjudicator", "r1", "a|b", {"x": 1})
    gw.submit(task)
    answer(task, {"decision": "same", "confidence": 0.9, "reason": "looks alike"})
    [res] = gw.poll()
    assert not res.accepted and "cannot-link" in res.validator_notes[0]


def test_off_executor_rejects_immediately(db, settings):
    settings.agents = "off"
    g = AgentGateway(db, settings, EventBus())
    assert isinstance(g.executor, OffExecutor)
    task = g.make_task("schema_mapper", "r1", "t", {"a": 1})
    g.submit(task)
    row = status(db, task)
    assert row["status"] == "rejected" and "agent unavailable" in row["validator_notes"][0]
    assert g.bus.history[-1].type == "agent.task_rejected"


def test_executor_selection(settings):
    for name, cls in (("queue", QueueExecutor), ("cli", ClaudeCliExecutor), ("off", OffExecutor)):
        settings.agents = name
        assert isinstance(make_executor(settings, lambda *a: None), cls)


def test_cli_command(gw):
    page = ClaudeCliExecutor.command(gw.make_task("page_reader", "r", "f:1", {"image": "/a.png"}))
    other = ClaudeCliExecutor.command(gw.make_task("schema_mapper", "r", "t", {}))
    assert page[:2] == ["claude", "-p"] and "--bare" not in page
    assert page[page.index("--tools") + 1] == "Read" and other[other.index("--tools") + 1] == ""
    for flag in ("--model", "--output-format", "--json-schema", "--no-session-persistence", "--max-budget-usd"):
        assert flag in page
    assert json.loads(page[page.index("--json-schema") + 1])["required"] == ["title", "header", "rows", "footnote"]
