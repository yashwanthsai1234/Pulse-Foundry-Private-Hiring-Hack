"""Executors complete agent tasks (IMPLEMENTATION §15.2). All of them leave the task file in pending/;
the result goes to done/<task_id>.json, which AgentGateway.poll() validates.

Sources:
- https://code.claude.com/docs/en/headless (claude -p, --output-format json, --json-schema -> structured_output)
- https://code.claude.com/docs/en/cli-reference (--tools, --no-session-persistence, --max-budget-usd)
- https://docs.python.org/3/library/asyncio-subprocess.html
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sot.config import Settings
from sot.core.models import AgentTask


class Executor(Protocol):
    background: bool  # True: run on the API event loop without blocking the pipeline thread

    async def submit(self, task: AgentTask) -> None: ...


def task_file(settings: Settings, task_id: str) -> Path:
    return settings.dir("agent_tasks/pending") / f"{task_id}.json"


def write_task(settings: Settings, task: AgentTask) -> None:
    task_file(settings, task.task_id).write_text(task.model_dump_json(indent=2))


class QueueExecutor:
    """Default: only writes the task file. A Claude Code session runs /process-agent-tasks."""

    background = False

    def __init__(self, settings: Settings):
        self.settings = settings

    async def submit(self, task: AgentTask) -> None:
        write_task(self.settings, task)


class OffExecutor:
    """No executor: the task is rejected at once (AGENT-UNAVAILABLE issue, a human decides)."""

    background = False

    def __init__(self, settings: Settings, reject: Callable[[AgentTask, str], None]):
        self.settings = settings
        self.reject = reject

    async def submit(self, task: AgentTask) -> None:
        write_task(self.settings, task)
        self.reject(task, "agent unavailable: no executor configured (SOT_AGENTS=off)")


class ClaudeCliExecutor:
    """Runs `claude -p` per task; at most agent.cli.concurrency at once. Not --bare (needs ANTHROPIC_API_KEY)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.sem = asyncio.Semaphore(int(settings["agent.cli.concurrency"]))

    @staticmethod
    def command(task: AgentTask) -> list[str]:
        prompt = f"{task.instructions}\n\nPayload:\n{json.dumps(task.payload, indent=1)}"
        return ["claude", "-p", prompt, "--model", "sonnet", "--output-format", "json",
                "--json-schema", json.dumps(task.output_schema),
                "--tools", "Read" if task.kind == "page_reader" else "",
                "--no-session-persistence", "--max-budget-usd", "0.50"]

    async def submit(self, task: AgentTask) -> None:
        write_task(self.settings, task)
        async with self.sem:
            proc = await asyncio.create_subprocess_exec(
                *self.command(task), cwd=self.settings.dir("agent_tasks/files"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), self.settings["agent.cli.timeout_s"])
            except TimeoutError:
                proc.kill()
                return
        output = json.loads(out).get("structured_output") if proc.returncode == 0 else None
        if output is not None:
            Path(task.output_path).write_text(json.dumps(output))


def make_executor(settings: Settings, reject: Callable[[AgentTask, str], None]) -> Executor:
    if settings.agents == "cli":
        return ClaudeCliExecutor(settings)
    if settings.agents == "off":
        return OffExecutor(settings, reject)
    return QueueExecutor(settings)
