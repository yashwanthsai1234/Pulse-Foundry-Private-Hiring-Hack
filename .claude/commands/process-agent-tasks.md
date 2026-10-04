---
description: Process pending Source-of-Truth agent tasks with parallel Sonnet subagents
---
Paths are relative to the repository root (the folder that holds `runtime/`). If the backend runs with another
SOT_RUNTIME, use that folder instead of `runtime/`.

1. List the files in `runtime/agent_tasks/pending/`. If there are none, say so and stop.
2. For EACH task file, start one subagent (Agent tool, model "sonnet") in ONE message so that all run in parallel.
   Give each subagent this prompt:
   "Read the task file <TASK_FILE> (a path under runtime/agent_tasks/pending/). Follow its `instructions` exactly,
    using its `payload` (and Read its `input_files` if any). Produce ONE JSON object that validates against its
    `output_schema`. Write it to the task's `output_path` (runtime/agent_tasks/done/<task_id>.json) with the Write
    tool. Write no other file. Do not modify the task file. Reply with 'done <task_id>' or 'failed <task_id>: <reason>'."
3. When all subagents finish, report: completed count, failed count, and the task ids.
   The running backend validates and applies the results automatically and removes the task file from `pending/`.
