"""Agent gateway: tasks out as JSON files, results in, schema + validator check, cache (IMPLEMENTATION §15).

The pipeline never calls a model. It submits a task; an executor (queue, claude -p, or off) writes
done/<task_id>.json; poll() accepts or rejects it. Accepted output is cached and applied via on_accept.

Sources:
- https://python-jsonschema.readthedocs.io/en/stable/validate/ (Draft202012Validator.iter_errors)
- https://docs.python.org/3/library/asyncio-task.html#asyncio.run_coroutine_threadsafe
- docs/PLAN.md §A.9, docs/IMPLEMENTATION.md §15.1
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

from sot.agents.executors import make_executor, task_file
from sot.agents.validators import ValidationContext, validate
from sot.config import Settings
from sot.core.events import EventBus
from sot.core.ids import canonical_json, sha256_bytes
from sot.core.models import AgentKind, AgentResult, AgentTask, EventType
from sot.core.pack import load_pack
from sot.store.db import DB

AGENTS_DIR = Path(__file__).parent
PARTIAL_WRITE_GRACE_S = 3
EXPIRE_MINUTES = 30  # a pending task older than this is given up on; override with setting agent.expire_min


class AgentGateway:
    def __init__(self, db: DB, settings: Settings, bus: EventBus):
        self.db, self.settings, self.bus = db, settings, bus
        self.ctx = ValidationContext(db, load_pack(settings.pack_dir), settings)
        self.executor = make_executor(settings, self._reject)
        self.on_accept: Callable[[AgentTask, dict], None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None  # the API loop, for background executors

    def make_task(self, kind: AgentKind, run_id: str, ref: str, payload: dict,
                  input_files: Sequence[str] = ()) -> AgentTask:
        prompt = (AGENTS_DIR / "prompts" / f"{kind}.md").read_text()
        version = re.search(r"^prompt_version:\s*(\S+)", prompt, re.M).group(1)
        key = _cache_key(kind, version, payload)
        task_id = "t-" + key[:10]
        files = list(input_files) or ([payload["image"]] if "image" in payload else [])
        return AgentTask(
            task_id=task_id, kind=kind, run_id=run_id, ref=ref, prompt_version=version, instructions=prompt,
            payload=payload, output_schema=json.loads((AGENTS_DIR / "schemas" / f"{kind}.json").read_text()),
            output_path=str(self.settings.dir("agent_tasks/done") / f"{task_id}.json"),
            input_files=files, created_at=datetime.now())

    def submit(self, task: AgentTask) -> dict | None:
        """Cache hit -> apply and return the output. Otherwise queue the task (once) and return None.

        The task is rebuilt with make_task, so callers may pass a bare AgentTask (kind, run_id, ref, payload).
        """
        task = self.make_task(task.kind, task.run_id, task.ref, task.payload, task.input_files)
        key = _cache_key(task.kind, task.prompt_version, task.payload)
        cached = self.db.query("SELECT output FROM agent_cache WHERE cache_key = ?", [key])
        if cached:
            output = cached[0]["output"]
            self._save(task, "pending")
            self._accept(task, output, "cache hit")
            return output
        if self.db.query("SELECT 1 FROM agent_tasks WHERE task_id = ?", [task.task_id]):
            return None
        self._save(task, "pending")
        self._emit(task, "agent.task_created", f"{task.kind} task for {task.ref}: waiting for agent")
        coro = self.executor.submit(task)
        if self.executor.background and self.loop:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            asyncio.run(coro)
        return None

    def poll(self) -> list[AgentResult]:
        """Check done/ for the results of pending tasks; give up on tasks nobody answered in time."""
        results = []
        limit = float(self.settings.values.get("agent.expire_min", EXPIRE_MINUTES))
        for row in self.db.query("SELECT task_id, created_at FROM agent_tasks WHERE status = 'pending'"):
            out_path = self.settings.dir("agent_tasks/done") / f"{row['task_id']}.json"
            pending = task_file(self.settings, row["task_id"])
            if not (out_path.exists() and pending.exists()):
                if pending.exists() and datetime.now() - row["created_at"] > timedelta(minutes=limit):
                    results.append(self._expire(row["task_id"], limit))
                continue
            task = AgentTask.model_validate_json(pending.read_text())
            try:
                output = json.loads(out_path.read_text())
            except json.JSONDecodeError:
                if time.time() - out_path.stat().st_mtime > PARTIAL_WRITE_GRACE_S:
                    results.append(self._reject(task, "output is not valid JSON"))
                continue
            self._emit(task, "agent.task_done", f"{task.kind} result received for {task.ref}")
            results.append(self._judge(task, output))
        return results

    def _judge(self, task: AgentTask, output: dict) -> AgentResult:
        errors = [f"schema: {e.message}" for e in Draft202012Validator(task.output_schema).iter_errors(output)]
        ok, notes = (False, errors) if errors else validate(task, output, self.ctx)
        return self._accept(task, output, "validator OK") if ok else self._reject(task, *notes, output=output)

    def _accept(self, task: AgentTask, output: dict, note: str) -> AgentResult:
        self._save(task, "accepted", output, [note])
        self.db.insert("agent_cache", [{"cache_key": _cache_key(task.kind, task.prompt_version, task.payload),
                                        "kind": task.kind, "output": output, "created_at": datetime.now()}],
                       replace=True)
        self._emit(task, "agent.task_accepted", f"{task.kind} for {task.ref} accepted ({note})", notes=[note])
        self._drop_pending_file(task)
        if self.on_accept:
            try:
                self.on_accept(task, output)
            except Exception as e:  # applying failed: the output is not usable
                return self._reject(task, f"apply failed: {e}", output=output)
        return AgentResult(task_id=task.task_id, output=output, accepted=True, validator_notes=[note])

    def _reject(self, task: AgentTask, *notes: str, output: dict | None = None) -> AgentResult:
        self._save(task, "rejected", output or {}, list(notes))
        self._emit(task, "agent.task_rejected", f"{task.kind} for {task.ref} rejected: {'; '.join(notes)}",
                   notes=list(notes))
        self._drop_pending_file(task)
        return AgentResult(task_id=task.task_id, output=output or {}, accepted=False, validator_notes=list(notes))

    def _expire(self, task_id: str, minutes: float) -> AgentResult:
        task = AgentTask.model_validate_json(task_file(self.settings, task_id).read_text())
        note = f"agent unavailable: no result after {minutes:g} minutes"
        self._save(task, "expired", None, [note])
        self._emit(task, "agent.task_rejected", f"{task.kind} for {task.ref} expired: {note}", notes=[note])
        self._drop_pending_file(task)
        return AgentResult(task_id=task_id, output={}, accepted=False, validator_notes=[note])

    def _emit(self, task: AgentTask, type_: EventType, message: str, **data) -> None:
        """Agent events carry the file name so the UI can show them under their file."""
        file_name = None
        if "|" not in task.ref:  # a table id or file_id:page starts with the file id (a table id with its first 12 chars)
            row = self.db.query("SELECT file_name FROM files WHERE file_id LIKE ? LIMIT 1", [task.ref.split(":")[0] + "%"])
            file_name = row[0]["file_name"] if row else None
        self.bus.emit(task.run_id, type_, message, file_name, task_id=task.task_id, kind=task.kind, ref=task.ref, **data)

    def _drop_pending_file(self, task: AgentTask) -> None:
        """A judged task must not stay in pending/: /process-agent-tasks would hand it to a subagent again."""
        task_file(self.settings, task.task_id).unlink(missing_ok=True)

    def _save(self, task: AgentTask, status: str, output: dict | None = None, notes: list[str] | None = None) -> None:
        self.db.insert("agent_tasks", [{
            "task_id": task.task_id, "kind": task.kind, "run_id": task.run_id, "ref": task.ref, "status": status,
            "payload": task.payload, "output": output, "validator_notes": notes or [],
            "created_at": task.created_at, "finished_at": datetime.now() if status != "pending" else None,
        }], replace=True)


def _cache_key(kind: str, version: str, payload: dict) -> str:
    return sha256_bytes(f"{kind}|{version}|{canonical_json(payload)}".encode())
