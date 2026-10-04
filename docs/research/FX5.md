# FX5 research notes (pipeline, API, agents)

Sources and what each decided:
- https://www.starlette.io/staticfiles/ : `StaticFiles.get_response` raises HTTP 404 for an unknown path; a subclass catches it and serves `index.html` (SPA deep links). API paths and paths with a file extension keep their 404.
- https://fastapi.tiangolo.com/tutorial/handling-errors/ : a 404 raised under the mount renders as the JSON `{"detail": "Not Found"}`.
- https://github.com/sysid/sse-starlette : `EventSourceResponse` pings every 15 s and stops the generator on disconnect, so the never-ending `/api/events` generator needs no extra keep-alive code.
- https://html.spec.whatwg.org/multipage/server-sent-events.html : the client reconnects with its own cursor, so the stream takes `?since=<seq>`; `seq` must therefore grow across server restarts (EventBus `first_seq` = max persisted + 1).
- https://fastapi.tiangolo.com/advanced/events/ : lifespan owns the agent-result poller; orphaned runs are closed in `Pipeline.__init__`, which runs before the first request.
- https://fastapi.tiangolo.com/tutorial/request-files/ : upload parts can share a file name; each part is saved in its own folder.
- https://pymupdf.readthedocs.io/en/latest/rect.html : `Rect.normalize()` and `intersect()` keep the crop highlight inside 0..1 for inverted or partly off-page boxes.
- https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap : page -> PNG for page_reader tasks created from text PDFs.

Decisions
- Zero-table PDF pages: the orchestrator adds an empty placeholder RawTable (method "none", score 0) per page, so the page is visible in `raw_tables` and the PARSE-PDF-LOW-CONFIDENCE draft can be recomputed on every rebuild (checks close issues that are absent from the drafts). The parser (FX1) was not changed.
- A table scoring below 0.5 is not mapped; its page goes to a page_reader. When the agent's table arrives it replaces the placeholder (same table id `<file12>:<page>:0`).
- "Schedule-looking" page = at least 3 distinct day names or 3 shift tokens in the page text.
- B-016 (checks only) is not done: `run_checks` closes every issue missing from the drafts, and the drafts of resolve and truth are not stored, so PUT /api/settings still rebuilds stages 5-7.
- Schedules are re-silvered whenever a non-schedule table is new (anchors may have changed); with no anchors at all the as-of date is the anchor, and silver's `schedule_dates` parse issue becomes PARSE-SCHEDULE-DATES.
- Task expiry: `agent.expire_min` in settings (default 30 minutes, `EXPIRE_MINUTES` in gateway.py). `config.py` could carry the default.
