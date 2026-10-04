"""W3-B3: schedule PDFs made by engines other than reportlab (Chrome, PyMuPDF, LibreOffice, scans) and real web PDFs.

Each PDF is ingested through the real Pipeline together with the e1 CSVs (they give the Mon-Sun 2026-09-14 date anchors);
the e1 schedule itself is not ingested. Ground truth: fixtures/realworld/pdf/truth.json (see rw_make_pdfs.py)."""
import functools
import json
import re
import tempfile

import pytest

from sot.store import repo
from tests.breakers.rw_harness import RW, ingest, ingest_with_anchors, shift_set, truth_rows, truth_shifts

PDF = RW / "pdf"
TRUTH = json.loads((PDF / "truth.json").read_text())
GEN_TEXT = ["chrome_bordered_twoline.pdf", "chrome_bordered_oneline.pdf", "chrome_borderless_zebra.pdf",
            "pymupdf_story.pdf", "pymupdf_draw_plain.pdf", "pymupdf_draw_rotated_header.pdf",
            "libreoffice_xlsx.pdf", "libreoffice_docx_pandoc.pdf"]
SCANS = ["scan_130dpi_rot1.5.pdf", "scan_100dpi_rot2.pdf"]


@functools.lru_cache(maxsize=None)
def run(name):
    p, err = ingest_with_anchors(PDF / name, tempfile.mkdtemp())
    assert err is None, f"pipeline crashed: {err!r}"
    return p


def sched_tables(p, name):
    out = []
    for r in p.db.query("SELECT t.table_id FROM raw_tables t JOIN files f USING (file_id) WHERE f.file_name = ? "
                        "ORDER BY t.page, t.table_id", [name]):
        out.append(repo.load_raw_table(p.db, r["table_id"]))
    return out


def norm(s):
    return re.sub(r"\s+", "", s or "")


@pytest.mark.parametrize("name", GEN_TEXT)
def test_extracted_rows_match_truth_or_score_is_low(name):
    """False confidence = score >= pdf.method_min_score (0.8) but cells differ from the document."""
    p = run(name)
    ts = sched_tables(p, name)
    got = [[norm(c) for c in row] for t in ts for row in t.df.drop("_src_row").rows()]
    want = [[norm(c) for c in r] for r in truth_rows(TRUTH)]
    score = min((t.extraction.score for t in ts), default=0.0)
    if got != want:
        assert score < 0.8, f"score {score:.2f} with {len(got)} of {len(want)} rows, method {ts[0].extraction.method if ts else None}"


@pytest.mark.parametrize("name", GEN_TEXT)
def test_downstream_shifts_equal_truth(name):
    p = run(name)
    got = {(norm(n), d, norm(t)) for n, d, t in shift_set(p)}  # norm on names too, as in the rows test:
    want = {(norm(n), d, norm(t)) for n, d, t in truth_shifts(TRUTH)}  # the pandoc PDF hard-wraps inside words
    assert got == want, f"{len(got & want)}/{len(want)} correct, {len(got - want)} wrong, missing {len(want - got)}"


@pytest.mark.parametrize("name", GEN_TEXT + SCANS)
def test_file_without_schedule_table_is_flagged_or_tasked(name):
    """A schedule PDF that yields no schedule table must leave a visible trace: an agent task or an issue."""
    p = run(name)
    if any(m["template_id"] == "schedule" for m in p.db.query(
            "SELECT m.template_id FROM mappings m JOIN raw_tables t USING (table_id) JOIN files f USING (file_id) "
            "WHERE f.file_name = ?", [name])):
        return
    tasks = p.db.query("SELECT kind FROM agent_tasks")
    issues = p.db.query("SELECT check_id FROM issues WHERE check_id IN ('FILE-QUARANTINED','TABLE-UNMAPPED',"
                        "'PARSE-PDF-LOW-CONFIDENCE','AGENT-UNAVAILABLE','AGENT-REJECTED')")
    assert tasks or issues, "PDF produced no schedule table, no agent task and no issue: the schedule silently vanished"


@pytest.mark.parametrize("name", SCANS)
def test_scans_route_to_page_reader_one_task_per_page(name):
    p = run(name)
    assert [r["kind"] for r in p.db.query("SELECT kind FROM agent_tasks")] == ["page_reader"] * 2


def test_schedule_only_ingest_without_date_anchor_is_flagged():
    """No HR/payroll CSV in the run: Mon 09/14 has no year anchor. 14 staff rows, 0 shifts and NO issue = silent loss."""
    p, err, = ingest(PDF / "chrome_bordered_twoline.pdf", tempfile.mkdtemp())[::2]
    assert err is None
    n = p.db.query("SELECT count(*) n FROM shifts_silver")[0]["n"]
    if n == 0:
        assert p.db.query("SELECT count(*) n FROM issues")[0]["n"] > 0, "0 shifts and no issue"


# ---- real PDFs from the web (see SOURCES.md) ----

def test_web_calendarlabs_weekly_schedule_not_mapped_to_vendor_credential():
    """Excel-made 'weekly work schedule' (hours per day, no shift tokens). Must not become 21 credential records."""
    p = run("web_calendarlabs_weekly_work_schedule.pdf")
    m = p.db.query("SELECT m.* FROM mappings m JOIN raw_tables t USING (table_id) JOIN files f USING (file_id) "
                   "WHERE f.file_name = 'web_calendarlabs_weekly_work_schedule.pdf'")
    assert not m or m[0]["template_id"] in (None, "schedule") or m[0]["status"] != "mapped", \
        f"auto-mapped to {m[0]['template_id']} at {m[0]['confidence']:.2f}: {m[0]['matches'][:200]}"


def test_web_calendarlabs_low_extraction_score_is_surfaced():
    p = run("web_calendarlabs_weekly_work_schedule.pdf")
    (t,) = sched_tables(p, "web_calendarlabs_weekly_work_schedule.pdf")
    assert t.extraction.score < 0.8
    assert (p.db.query("SELECT count(*) n FROM issues WHERE check_id = 'PARSE-PDF-LOW-CONFIDENCE'")[0]["n"]
            or p.db.query("SELECT count(*) n FROM agent_tasks WHERE kind = 'page_reader'")[0]["n"]), \
        "extraction score 0.60 (< 0.8) but neither PARSE-PDF-LOW-CONFIDENCE nor a page_reader task (B-012)"


def test_web_blank_duty_roster_not_auto_mapped_and_no_records():
    p = run("web_platoforms_hospital_duty_roster.pdf")
    q = p.db.query("SELECT m.template_id, m.status FROM mappings m JOIN raw_tables t USING (table_id) "
                   "JOIN files f USING (file_id) WHERE f.file_name = 'web_platoforms_hospital_duty_roster.pdf'")
    assert all(r["status"] != "mapped" for r in q), q
    assert p.db.query("SELECT count(*) n FROM shifts_silver")[0]["n"] == 0
