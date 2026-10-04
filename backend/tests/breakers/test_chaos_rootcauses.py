"""W3-B4 chaos root causes, each reduced to a minimal failing test (no chaos harness).

Every test names the chaos finding it reproduces (docs/breakdowns/B4.md). They fail today and must pass after the fix fleet.
"""
from __future__ import annotations

import csv
from datetime import date

import pytest

from sot.checks.builtin import builtin_drafts
from sot.core.models import Locator, SourceRecord
from sot.normalize.dates import infer_column_date_format
from sot.normalize.names import compare_given, person_key_from_parts
from sot.parsers.base import detect_header_row
from sot.parsers.csv_parser import detect_encoding
from sot.pipeline.orchestrator import Pipeline
from sot.resolve.blocking import block
from sot.store import repo

HR_HEADER = ["employee_id", "first_name", "last_name", "job_title", "facility", "phone", "license_number",
             "license_expiration", "hire_date"]
LIC_HEADER = ["license_number", "name_on_license", "license_type", "expiration_date", "last_verified"]
PAY_HEADER = ["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"]
PHONES = ["347-555-02{i:02d}", "(347) 555-02{i:02d}", "34755502{i:02d}"]  # the generator's phone_format_mix
NAMES = [("Amy", "Rivera"), ("Brian", "Watson"), ("Cara", "Nguyen"), ("Dale", "Lopez"), ("Erin", "Cruz"),
         ("Finn", "Reed"), ("Gina", "Ortiz"), ("Hugo", "Perez")]


def hr_rows(n=8):
    return [[f"E2{i:02d}", g, f, "Registered Nurse", "Harborview Bayside", PHONES[i % 3].format(i=i), f"RN-55{i:04d}",
             "2027-05-31", f"{(i % 12) + 1:02d}/{i + 10:02d}/2021"] for i, (g, f) in enumerate(NAMES, 1)][:n]


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows([header, *rows])
    return path


@pytest.fixture
def pipe(settings):
    settings.agents = "off"
    settings.as_of = date(2026, 9, 21)
    return Pipeline(settings)


def record(rid, template, fields, key=None, parse_issues=()):
    return SourceRecord(record_id=rid, template_id=template, entity="person", fields=fields, raw={}, person_key=key,
                        loc=Locator(file_id="f", file_name="f.csv", row=2), parse_issues=list(parse_issues))


# ---- CR-1 (system, parsers/csv_parser.detect_encoding): a latin-1 file that starts with a UTF-8 BOM ----------------
def test_latin1_file_with_utf8_bom_keeps_accents():
    data = b"\xef\xbb\xbf" + "name\nMuñoz\n".encode("latin-1")
    # the sniffer trusts the BOM (utf-8-sig) although the bytes after it are not UTF-8, so "Muñoz" decodes as "Mu\ufffdoz"
    assert "Muñoz" in data.decode(detect_encoding(data), errors="replace")


# ---- CR-2 (contract, checks/builtin vs normalize/silver): bad_date must surface as PARSE-DATE -------------------------
def test_unparseable_date_becomes_parse_date_issue():
    from sot.normalize.silver import _normalize  # the producer of the parse_issues strings

    _, issue = _normalize("person.hire_date", "date", "2020-02-30", None, None)  # type: ignore[arg-type]
    drafts = builtin_drafts([record("t:1", "hr_roster", {}, parse_issues=[issue])], [])
    assert [d.check_id for d in drafts] == ["PARSE-DATE"], issue


# ---- CR-3 (normalize/dates.infer_column_date_format): one bad value hides the ambiguity of the rest -------------------
def test_ambiguous_column_is_still_flagged_when_one_value_is_unparseable():
    fmt, ambiguous = infer_column_date_format(["03/04/2020", "05/06/2021", "2020-02-30"])
    assert fmt == "%m/%d/%Y"
    assert ambiguous, "03/04/2020 may be 3 April or March 4: the column is ambiguous whatever the bad value is"


# ---- CR-4 (parsers/base.detect_header_row): extra text columns push the real header out -----------------------------
def test_hr_header_is_found_when_an_unknown_text_column_is_added():
    grid = [HR_HEADER + ["Notes"]] + [r + ["n/a"] for r in hr_rows()]
    assert detect_header_row(grid) == 0  # returns 2: a data row with a digits-only phone looks more like a header


def test_extra_unknown_column_does_not_drop_hr_rows(pipe, tmp_path):
    path = write_csv(tmp_path / "hr_roster.csv", HR_HEADER + ["Notes"], [r + ["n/a"] for r in hr_rows()])
    pipe.ingest([path])
    assert pipe.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 8


# ---- CR-5 (semantic/validators._LAST_FIRST/_ALPHA_TOKEN are ASCII-only): accented names fail the person_name validator --
@pytest.mark.parametrize("name", ["MU\u00d1OZ, MICHELLE", "Michelle Mu\u00f1oz", "Jos\u00e9 Watson", "WILLIAMS, REN\u00c9E"])
def test_person_name_validator_accepts_accented_names(pack, name):
    from sot.semantic.validators import build_validators

    assert build_validators(pack)["person.full_name"](name)


def test_license_file_with_an_accented_name_still_maps_to_the_license_template(pipe, tmp_path):
    # chaos: 'Name on License' + 'Type' + one MU\u00d1OZ row turned the whole file into vendor_credential (org.name 1.0)
    header = ["Lic Number", "Name on License", "Type", "Expires", "Verified On"]
    people = [("Michelle", "Mu\u00f1oz"), *NAMES]
    rows = [[f"RN-55{i:04d}", f"{f.upper()}, {g.upper()}", "RN", "2027-05-31", "2026-07-01"] for i, (g, f) in enumerate(people, 1)]
    pipe.ingest([write_csv(tmp_path / "licenses.csv", header, rows)])
    assert pipe.db.query("SELECT template_id FROM mappings")[0]["template_id"] == "license"


# ---- CR-6 (pack nicknames.csv): common nicknames missing from the dataset ----------------------------------------------
@pytest.mark.parametrize("given,nick", [("Katherine", "Kate"), ("Richard", "Rick"), ("Susan", "Sue"), ("Deborah", "Debbie")])
def test_common_nicknames_are_recognised(pack, given, nick):
    a, b = person_key_from_parts(given, "Brown", pack.nicknames), person_key_from_parts(nick, "Brown", pack.nicknames)
    assert compare_given(a, b) == "nickname"


# ---- CR-7 (pack resolution.yaml blocking): a one-letter family typo shares no blocking key -----------------------------
@pytest.mark.parametrize("family,typo", [("Watson", "Waton"), ("Murphy", "Murhy"), ("Sanchez", "Sanhez"), ("Anderson", "Andeson")])
def test_family_typo_pair_is_a_blocking_candidate(pack, family, typo):
    fields = {"person.role": "CNA", "person.facility": "FAC-RVD"}
    hr = record("hr:1", "hr_roster", fields, person_key_from_parts("Brian", family, pack.nicknames))
    sched = record("sched:1", "schedule", fields, person_key_from_parts("Brian", typo, pack.nicknames))
    assert ("hr:1", "sched:1") in block([hr, sched], pack.resolution["blocking"])


# ---- CR-8 (pipeline/truth): an HR roster ingested alone crashes when it holds two rows for one employee --------------
def test_hr_roster_with_a_duplicate_employee_row_ingests(pipe, tmp_path):
    rows = hr_rows()
    rows.append(rows[0][:5] + ["347-555-9999"] + rows[0][6:])
    pipe.ingest([write_csv(tmp_path / "hr_roster.csv", HR_HEADER, rows)])  # DuckDB ConstraintException today
    assert pipe.db.query("SELECT count(*) n FROM persons WHERE person_id = 'P-E201'")[0]["n"] == 1


# ---- CR-9 (checks/builtin.ID-FUZZY-LINK, B-009/B-019): one issue per fuzzy record, entities are person ids -------------
def test_fuzzy_link_issue_is_one_per_record_with_person_ids(pipe, e1_dir):
    pipe.ingest([e1_dir / f for f in ("hr_roster.csv", "payroll.csv", "licenses.csv", "schedule.pdf")])
    fuzzy = [i for i in repo.load_issues(pipe.db) if i.check_id == "ID-FUZZY-LINK"]  # Marc Bell on the schedule
    assert len(fuzzy) == 1, [i.entity_ids for i in fuzzy]
    assert fuzzy[0].entity_ids == ["P-E202"]


# ---- CR-10 (checks/builtin.LEGEND-MISMATCH): one issue per shift cell floods the list --------------------------------
def test_legend_mismatch_is_one_issue_per_file_and_token(pipe, tmp_path):
    from tools.synth.generator import generate_world, plant_defects, write_world

    world, _ = plant_defects(generate_world(3, weeks=1), ["legend_mismatch_token"], 3)
    write_world(world, tmp_path, "grid")
    pipe.ingest([tmp_path / "hr_roster.csv", tmp_path / "payroll.csv", tmp_path / "licenses.csv", tmp_path / "schedule.pdf"])
    legend = [i for i in repo.load_issues(pipe.db) if i.check_id == "LEGEND-MISMATCH"]
    assert len(legend) == 1, f"{len(legend)} issues for one wrong footnote"


# ---- CR-11 (parsers/pdf/context): a table that continues on the next page has no title, so its rows lose the facility --
def test_table_continued_on_the_next_page_keeps_its_facility(pipe, tmp_path):
    from tools.synth.generator import generate_world, schedule_specs
    from tools.synth.render import render_schedule_pdf

    spec = schedule_specs(generate_world(3, weeks=1))[0]  # two facility tables of ~20 rows; the second one is split
    pdf = render_schedule_pdf(spec, tmp_path / "schedule.pdf", "two_tables_one_page")
    pipe.ingest([pdf])
    hints = [repo.load_raw_table(pipe.db, r["table_id"]).context["facility_hint"]
             for r in pipe.db.query("SELECT table_id FROM raw_tables")]
    assert hints and all(hints), hints
