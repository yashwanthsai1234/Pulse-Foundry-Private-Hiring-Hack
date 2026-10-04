"""GET /api/agent-tasks: the agent task queue with payloads, outputs and validator notes decoded.

Sources:
- https://fastapi.tiangolo.com/tutorial/query-params/ (optional ?status= filter)
- https://duckdb.org/docs/stable/data/json/overview (JSON columns, decoded once in DB.query)
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from sot.api.routes_data import rows

router = APIRouter()


@router.get("/agent-tasks")
def agent_tasks(request: Request, status: str | None = None) -> list[dict]:
    where, params = ("WHERE status = ?", [status]) if status else ("", [])
    return rows(request, f"SELECT * FROM agent_tasks {where} ORDER BY created_at", params)
