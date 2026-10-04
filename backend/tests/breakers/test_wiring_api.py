"""W3-B1 wiring auditor: HTTP API <-> pipeline <-> front end, REAL data (example_e1), no fakes.
Failing tests are the evidence; see docs/breakdowns/B1.md for the analysis."""
from __future__ import annotations

import io
import urllib.parse
from datetime import date

import pymupdf
import pytest

from sot.config import REPO_DIR
from tests.breakers.shapecheck import SPECS, check
from tests.breakers.wiring_support import E1, E1_FILES, make_client, sse_events, upload


@pytest.fixture
def world(settings):
    app, client = make_client(settings)
    run_id = upload(client, [E1 / f for f in E1_FILES])
    return app, client, run_id


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def test_every_endpoint_matches_frontend_types(world):
    """Field-by-field comparison with frontend/src/api/types.ts (hand-encoded in shapecheck.py)."""
    _, c, _ = world
    errs = []
    for name, path in [("runs", "/api/runs"), ("summary", "/api/summary"), ("issues", "/api/issues"),
                       ("people", "/api/people"), ("shifts", "/api/shifts"), ("credentials", "/api/credentials"),
                       ("contracts", "/api/contracts"), ("agent-tasks", "/api/agent-tasks"), ("settings", "/api/settings")]:
        errs += check(SPECS[name], _get(c, path), name)
    for i in _get(c, "/api/issues"):
        d = _get(c, f"/api/issues/{i['fingerprint']}")
        errs += [e for e in check(SPECS["issue"], d, f"issue:{i['check_id']}") if not e.endswith("loc: not an object (NoneType)")]
    for p in _get(c, "/api/people"):
        errs += check(SPECS["person"], _get(c, f"/api/people/{p['person_id']}"), "person")
    assert errs == []


def test_event_data_keys_the_ui_reads(world):
    _, c, run_id = world
    ev = sse_events(c, run_id)
    by = {}
    for e in ev:
        by.setdefault(e["type"], []).append(e)
    assert {"parser", "score", "bids"} <= set(by["file.sniffed"][0]["data"])
    assert all({"table_id", "method", "score", "rows"} <= set(e["data"]) for e in by["table.extracted"])
    assert all({"table_id", "template_id", "confidence", "matches", "unmapped_columns"} <= set(e["data"]) for e in by["table.mapped"])
    assert by["run.completed"][0]["data"]["agent_tasks"] == 0
    assert [e["seq"] for e in ev] == sorted(e["seq"] for e in ev)


def test_csv_evidence_has_source_row_and_column_for_the_ui_mini_table(world):
    """IMPLEMENTATION s18: 'a CSV cell shows the source row as a mini table with the column highlighted'."""
    _, c, _ = world
    fp = next(i["fingerprint"] for i in _get(c, "/api/issues?check_id=LIC-WORKED-EXPIRED"))
    csv_items = [e for e in _get(c, f"/api/issues/{fp}")["evidence"] if (e.get("loc") or {}).get("file_name", "").endswith(".csv")]
    assert csv_items
    assert all(e.get("raw") for e in csv_items), [(e["kind"], e["label"]) for e in csv_items if not e.get("raw")]
    assert all(e["loc"].get("col") for e in csv_items), "loc.col is null: the UI cannot highlight the cell"


def test_crop_highlight_contains_the_shift_text(world):
    _, c, _ = world
    fp = next(i["fingerprint"] for i in _get(c, "/api/issues?check_id=LIC-WORKED-EXPIRED"))
    cells = [e for e in _get(c, f"/api/issues/{fp}")["evidence"] if e["kind"] == "cell" and e["loc"].get("bbox")]
    assert len(cells) == 4
    for e in cells:
        loc = e["loc"]
        x0, t, x1, b = loc["bbox"]
        r = c.get("/api/evidence/crop?" + urllib.parse.urlencode(
            dict(file_id=loc["file_id"], page=loc["page"], x0=x0, top=t, x1=x1, bottom=b)))
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        hx, hy, hw, hh = (float(v) for v in r.headers["X-Highlight"].split(","))
        assert 0 <= hx and 0 <= hy and hx + hw <= 1.0001 and hy + hh <= 1.0001 and hw > 0 and hh > 0
        pix = pymupdf.Pixmap(r.content)
        assert pix.width > 0 and pix.height > 0
        path = c.app.state.db.query("SELECT path FROM files WHERE file_id = ?", [loc["file_id"]])[0]["path"]
        pg = pymupdf.open(path)[loc["page"] - 1]
        pad = 40
        clip = pymupdf.Rect(x0 - pad, t - pad, x1 + pad, b + pad).intersect(pg.rect)
        hr = pymupdf.Rect(clip.x0 + hx * clip.width, clip.y0 + hy * clip.height,
                          clip.x0 + (hx + hw) * clip.width, clip.y0 + (hy + hh) * clip.height)
        assert e["text"].split(" ", 1)[1] in pg.get_text("text", clip=hr)


def test_crop_with_bbox_partly_off_page_keeps_highlight_in_unit_range(world):
    _, c, _ = world
    fid = c.app.state.db.query("SELECT file_id FROM files WHERE file_name = 'schedule.pdf'")[0]["file_id"]
    r = c.get(f"/api/evidence/crop?file_id={fid}&page=1&x0=-20&top=-20&x1=30&bottom=30")
    hx, hy, hw, hh = (float(v) for v in r.headers["X-Highlight"].split(","))
    assert min(hx, hy) >= 0 and hx + hw <= 1.0001 and hy + hh <= 1.0001, r.headers["X-Highlight"]


@pytest.mark.parametrize("q", ["x0=1&top=1&x1=10&bottom=10", "x0=nan&top=1&x1=10&bottom=10"])
def test_crop_never_500s(world, q):
    _, c, _ = world
    fid = c.app.state.db.query("SELECT file_id FROM files WHERE file_name = 'hr_roster.csv'")[0]["file_id"]
    assert c.get(f"/api/evidence/crop?file_id={fid}&page=1&{q}").status_code < 500  # a CSV file id, then NaN on the PDF
    pdf = c.app.state.db.query("SELECT file_id FROM files WHERE file_name = 'schedule.pdf'")[0]["file_id"]
    assert c.get(f"/api/evidence/crop?file_id={pdf}&page=1&{q}").status_code < 500


def test_spa_deep_link_reload_serves_index_html(world):
    """BrowserRouter routes (/issues, /people ...) must survive a page reload (StaticFiles(html=True) has no fallback)."""
    if not (REPO_DIR / "frontend" / "dist").exists():
        pytest.skip("frontend/dist not built")
    _, c, _ = world
    assert c.get("/").status_code == 200
    for path in ("/issues", "/people", "/ingest"):
        r = c.get(path)
        assert r.status_code == 200 and "<div id=\"root\">" in r.text, (path, r.status_code, r.text[:60])


def test_issue_status_survives_reingest_and_as_of_put_creates_expiring(world):
    _, c, _ = world
    fp = next(i["fingerprint"] for i in _get(c, "/api/issues?check_id=LIC-WORKED-EXPIRED"))
    assert c.patch(f"/api/issues/{fp}", json={"status": "acknowledged", "owner": "don"}).json()["status"] == "acknowledged"
    upload(c, [E1 / f for f in E1_FILES])  # same bytes: all skipped, rebuild only
    d = _get(c, f"/api/issues/{fp}")
    assert d["status"] == "acknowledged" and d["owner"] == "don" and d["first_seen_run"] != d["last_seen_run"]
    assert c.put("/api/settings", json={"as_of": "2027-05-10"}).status_code == 200
    exp = _get(c, "/api/issues?check_id=LIC-EXPIRING")
    assert [i["person_name"] for i in exp] == ["Sofia Reyes"] and exp[0]["severity"] == "HIGH"


def test_same_filename_in_one_upload_is_not_lost(settings):
    app, c = make_client(settings)
    files = [("files", ("export.csv", b"k,v\n1,2\n")), ("files", ("export.csv", b"k,v\n9,9\n8,8\n"))]
    run = c.post("/api/ingest", files=files).json()["run_id"]
    msgs = [e["message"] for e in sse_events(c, run)]
    assert not any("skipped" in m for m in msgs), msgs
    assert len(c.get("/api/files").json()) == 2


def test_resaved_schedule_pdf_does_not_double_count_shifts(world):
    """Same schedule re-exported (different bytes, same cells) must not double hours / raise overlap issues."""
    _, c, _ = world
    before = {i["check_id"] for i in _get(c, "/api/issues")}
    doc = pymupdf.open(E1 / "schedule.pdf")
    doc.set_metadata({"title": "re-export"})
    buf = io.BytesIO()
    doc.save(buf)
    p = c.app.state.settings.runtime / "schedule_v2.pdf"
    p.write_bytes(buf.getvalue())
    upload(c, [p])
    after = _get(c, "/api/issues")
    assert {i["check_id"] for i in after} - before == set(), [(i["check_id"], i["message"][:70]) for i in after
                                                              if i["check_id"] not in before]
    fac = {f["facility_id"]: f for f in _get(c, "/api/shifts")["facilities"]}
    assert fac["FAC-BAY"]["rn_coverage"]["2026-09-14"] == 8.0


def test_schedule_uploaded_before_hr_still_yields_shifts(settings):
    """Any file order (IMPLEMENTATION s16): schedule alone, then the HR/payroll/license files."""
    app, c = make_client(settings)
    upload(c, [E1 / "schedule.pdf"])
    upload(c, [E1 / f for f in E1_FILES[:3]])
    assert c.get("/api/shifts").json()["facilities"], "schedule shifts were never built (weekday dates need anchors)"
    assert any(i["check_id"] == "LIC-WORKED-EXPIRED" for i in c.get("/api/issues").json())


def test_schedule_alone_uses_today_as_anchor(settings):
    app, c = make_client(settings)
    upload(c, [E1 / "schedule.pdf"])
    assert c.get("/api/shifts").json()["facilities"]


def test_db_bulk_insert_is_not_per_row_slow(db):
    import time
    from datetime import datetime
    rows = [{"run_id": "r", "seq": i, "ts": datetime.now(), "type": "log", "file_name": None, "message": "m", "data": {}}
            for i in range(3000)]
    t = time.time()
    db.insert("events", rows)
    assert time.time() - t < 2.0, f"3000-row insert took {time.time() - t:.1f}s (duckdb executemany)"
