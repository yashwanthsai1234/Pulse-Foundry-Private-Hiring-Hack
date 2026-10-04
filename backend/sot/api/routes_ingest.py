"""POST /api/ingest, GET /api/runs, SSE /api/runs/{id}/events and /api/events, POST /api/reset.

Sources:
- https://fastapi.tiangolo.com/tutorial/background-tasks/ (sync task functions run in a thread pool)
- https://fastapi.tiangolo.com/tutorial/request-files/
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.datastructures import UploadFile  # form parts are Starlette's class, not fastapi.UploadFile

from sot.api.routes_data import AS_OF_FILE
from sot.api.sse import event_stream
from sot.pipeline.orchestrator import new_run_id

router = APIRouter()


@router.post("/ingest")
async def ingest(request: Request, background: BackgroundTasks) -> dict:
    """Multipart upload; every file part is ingested whatever its field name (files, files[])."""
    uploads = [v for _, v in (await request.form()).multi_items() if isinstance(v, UploadFile)]
    if not uploads:
        raise HTTPException(400, "no files uploaded")
    run_id = new_run_id()
    folder = request.app.state.settings.dir(f"uploads/{run_id}")
    paths = []
    for i, u in enumerate(uploads):  # one folder per part: two parts may share a file name
        part = folder / str(i)
        part.mkdir()
        paths.append(part / (Path(u.filename or "").name or "upload"))
        paths[-1].write_bytes(await u.read())
    background.add_task(request.app.state.pipeline.ingest, paths, run_id)
    return {"run_id": run_id}


@router.get("/runs")
def runs(request: Request) -> list[dict]:
    return request.app.state.db.query(
        "SELECT r.run_id, r.started_at, r.finished_at, r.status, "
        "(SELECT count(*) FROM files f WHERE f.run_id = r.run_id) AS file_count FROM runs r ORDER BY r.started_at DESC")


@router.get("/runs/{run_id}/events")
async def run_events(request: Request, run_id: str):
    db = request.app.state.db
    if not (db.query("SELECT 1 FROM runs WHERE run_id = ?", [run_id])
            or db.query("SELECT 1 FROM events WHERE run_id = ? LIMIT 1", [run_id])):
        raise HTTPException(404, "unknown run")
    return event_stream(request, run_id)


@router.get("/events")
async def all_events(request: Request, since: int = 0):
    return event_stream(request, None, since)


@router.post("/reset")
def reset(request: Request) -> dict:
    """Demo only: empty every table and delete runtime folders (the database file stays open)."""
    if os.environ.get("SOT_ALLOW_RESET") != "1":
        raise HTTPException(403, "reset is disabled (set SOT_ALLOW_RESET=1)")
    db, settings, pipeline = request.app.state.db, request.app.state.settings, request.app.state.pipeline
    if not pipeline.lock.acquire(blocking=False):
        raise HTTPException(409, "a run is in progress; try again when it has finished")
    try:
        _wipe(db, settings)
    finally:
        pipeline.lock.release()
    return {"ok": True}


def _wipe(db, settings) -> None:
    for r in db.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"):
        db.execute(f"DELETE FROM {r['table_name']}")
    for d in settings.runtime.iterdir():
        if d.is_dir():
            shutil.rmtree(d)
    (settings.runtime / AS_OF_FILE).unlink(missing_ok=True)
