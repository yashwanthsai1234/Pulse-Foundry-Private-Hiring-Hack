"""FastAPI app factory: wires settings, DB, event bus, pipeline, routers and the agent-result poller.

Sources:
- https://fastapi.tiangolo.com/advanced/events/ (lifespan)
- https://fastapi.tiangolo.com/tutorial/background-tasks/
- https://github.com/sysid/sse-starlette
- https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread
- https://www.starlette.dev/staticfiles/ (StaticFiles.get_response raises HTTPException 404: the hook for the SPA fallback)
- https://fastapi.tiangolo.com/tutorial/handling-errors/
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import date
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from sot.api.routes_data import AS_OF_FILE
from sot.api import evidence, routes_agents, routes_data, routes_ingest
from sot.config import REPO_DIR, Settings, load_settings
from sot.core.events import EventBus, db_persister, next_seq
from sot.pipeline.orchestrator import Pipeline
from sot.store.db import DB

POLL_SECONDS = 1.0
FRONTEND_DIST = REPO_DIR / "frontend" / "dist"


class SPAFiles(StaticFiles):
    """Static files; an unknown path that is not an API call or an asset gets index.html (BrowserRouter deep links)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api/") or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    as_of = settings.runtime / AS_OF_FILE
    if as_of.exists():
        settings.as_of = date.fromisoformat(as_of.read_text().strip())
    db = DB(settings.db_path)
    bus = EventBus(persist=db_persister(db), first_seq=next_seq(db))
    pipeline = Pipeline(settings, db, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipeline.gateway.loop = asyncio.get_running_loop()

        async def poller() -> None:
            while True:
                await asyncio.sleep(POLL_SECONDS)
                await asyncio.to_thread(pipeline.poll_agents)

        task = asyncio.create_task(poller())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="Harborview Source of Truth", lifespan=lifespan)
    app.state.settings, app.state.db, app.state.bus, app.state.pipeline = settings, db, bus, pipeline
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Highlight"])
    for module in (routes_ingest, routes_data, routes_agents, evidence):
        app.include_router(module.router, prefix="/api")
    if FRONTEND_DIST.exists():
        app.mount("/", SPAFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
