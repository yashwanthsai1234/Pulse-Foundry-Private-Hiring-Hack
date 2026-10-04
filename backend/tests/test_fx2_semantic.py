"""FX2 (wave 4): semantic layer fixes. Each test names the finding it proves (docs/breakdowns, docs/BREAKDOWNS.md)."""
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from sot.normalize.dates import infer_column_date_format, parse_date, resolve_weekday_date
from sot.normalize.vocab import clean, normalize_vocab
from sot.semantic import contracts, mapper
from sot.semantic.classify import classify
from sot.semantic.contracts import map_table
from sot.semantic.mapper import header_similarity
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators
from test_mapper import csv_table, make_table, run

RW = Path(__file__).parent / "fixtures" / "realworld"
D = date(2027, 5, 31)


# ---- B2-06 / B2-13 / RC3: dates ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["31.05.2027", "2027-05-31T00:00:00", "2027-05-31 00:00", "2027-05-31 00:00:00",
                                  "2027-05-31T00:00:00Z", "May 31, 2027", "31 May 2027", "31 May, 2027", "May 31 2027",
                                  "20270531", "2027-5-31", "05/31/2027", "31-May-2027"])
def test_date_styles(text):
    assert parse_date(text) == D
    fmt, _ = infer_column_date_format([text, text])
    assert parse_date(text, fmt) == D


def test_full_month_names_and_garbage():
    assert parse_date("September 14, 2026") == date(2026, 9, 14)
    assert parse_date("12345678") is None and parse_date("2026-02-30") is None


def test_one_value_in_another_style_is_not_lost():
    """B2-13: the column format is ISO, one cell is 09/14/2026: per-value fallback keeps it."""
    assert parse_date("09/14/2026", "%Y-%m-%d") == date(2026, 9, 14)
    assert parse_date("junk", "%Y-%m-%d") is None


def test_one_bad_value_does_not_hide_column_ambiguity():
    """RC3."""
    assert infer_column_date_format(["03/04/2020", "05/06/2021", "2020-02-30"]) == ("%m/%d/%Y", True)


def test_weekday_year_must_match_and_be_near():
    """B-002: 'Tue 09/14' has no weekday-consistent date near a 2026-09 anchor (2026-09-14 is a Monday): None."""
    anchors = [date(2026, 9, 20)]
    assert resolve_weekday_date("Tue", 9, 14, anchors) is None
    assert resolve_weekday_date("Mon", 9, 14, anchors) == date(2026, 9, 14)
    assert resolve_weekday_date("Fri", 1, 1, [date(2026, 12, 28)]) == date(2027, 1, 1)  # across New Year


# ---- B3-06 / RC5: Unicode names, no token-subset 100s -------------------------------------------------------------
@pytest.mark.parametrize("name", ["José Peña", "MUÑOZ, MICHELLE", "Łukasz Nowak", "Renée O’Brien", "O'Neil, Mary-Jane"])
def test_unicode_names_pass_validators(pack, name):
    v = build_validators(pack)
    assert v["person.full_name"](name)


@pytest.mark.parametrize("name", ["Zoë", "Łukasz", "O’Brien"])
def test_unicode_single_name_tokens(pack, name):
    assert build_validators(pack)["person.given_name"](name)


@pytest.mark.parametrize("col,field", [("Type", "credential.doc_type"), ("Name on License", "org.name")])
def test_header_token_subset_is_not_a_perfect_match(pack, col, field):
    assert header_similarity(col, pack.fields[field]) < 0.9


def test_header_exact_synonym_still_scores_one(pack):
    assert header_similarity("Name on License", pack.fields["person.full_name"]) == 1.0
    assert header_similarity("EMPLOYEE\nNAME", pack.fields["person.full_name"]) == 1.0
    assert header_similarity("Exp. Date", pack.fields["credential.expires_on"]) == 1.0


# ---- B2-17: vocab fuzzy ----------------------------------------------------------------------------------------
def test_generic_nurse_is_not_rn(pack):
    assert normalize_vocab("Nurse", pack.vocabs["roles"]) == (None, False)
    assert normalize_vocab("Registerd Nurse", pack.vocabs["roles"]) == ("RN", True)
    assert normalize_vocab("Harborview Riverdale/Bayside", pack.vocabs["facilities"])[0] is None


# ---- S10: one text normaliser ------------------------------------------------------------------------------------
def test_one_shared_text_normaliser():
    assert mapper.clean is clean and contracts.clean is clean
    assert clean("  José_Peña-Ñ#2 ") == "josé peña ñ 2"
    assert contracts.header_fingerprint(["Mon\n09/14"]) == contracts.header_fingerprint(["mon 09/21"])


# ---- B2-03: schedule.day header pattern ---------------------------------------------------------------------------
@pytest.mark.parametrize("header", ["Mon 09/14", "09/14", "9/14/2026", "2026-09-14", "Mon\n09/14", "Monday 14 Sep",
                                    "Tue, 09/15", "Mon 09/14/26"])
def test_schedule_day_header_pattern_accepts(pack, header):
    import re
    assert re.fullmatch(pack.fields["schedule.day"].header_pattern, header.strip(), re.I), header


@pytest.mark.parametrize("header", ["Name", "Role", "Hours", "Mon", "Total", "Notes 2"])
def test_schedule_day_header_pattern_rejects(pack, header):
    import re
    assert not re.fullmatch(pack.fields["schedule.day"].header_pattern, header, re.I)


def test_schedule_with_two_line_and_dateonly_headers(pack, settings):
    for hdr in (["Mon\n09/14", "Tue\n09/15", "Wed\n09/16"], ["09/14", "09/15", "09/16"], ["2026-09-14", "2026-09-15", "2026-09-16"]):
        rows = [["Sofia Reyes", "RN", "7a-3p", "OFF", "7a-3p"], ["Marc Bell", "CNA", "3p-11p", "3p-11p", "OFF"]]
        m = run(make_table(["Staff", "Role", *hdr], rows), pack, settings)
        assert m.template_id == "schedule" and m.confidence >= 0.8, hdr
        assert [x.column for x in m.matches if x.field_id == "schedule.day"] == hdr


# ---- B2-05: one_of groups ------------------------------------------------------------------------------------------
HR_ONE_NAME = ["employee_id", "employee_name", "job_title", "facility", "phone", "license_number", "license_expiration"]


def _hr_one_name_rows():
    return [[f"E20{i}", f"{f}, {g}", "Registered Nurse", "Harborview Bayside", "718-555-020%d" % i, f"RN-55120{i}", "2027-05-31"]
            for i, (g, f) in enumerate([("Sofia", "Reyes"), ("Marcus", "Bell"), ("Ana", "Cruz")], 1)]


def test_hr_roster_with_one_full_name_column(pack, settings):
    m = run(make_table(HR_ONE_NAME, _hr_one_name_rows()), pack, settings)
    assert m.template_id == "hr_roster" and m.confidence >= 0.8, (m.template_id, m.confidence)
    assert {x.column: x.field_id for x in m.matches}["employee_name"] == "person.full_name"
    assert m.missing_required == []


def test_hr_roster_missing_both_name_forms_reports_the_group(pack, settings):
    header = [h for h in HR_ONE_NAME if h != "employee_name"]
    rows = [[v for h, v in zip(HR_ONE_NAME, r) if h != "employee_name"] for r in _hr_one_name_rows()]
    m = run(make_table(header, rows), pack, settings)
    assert m.template_id == "hr_roster"
    assert set(m.missing_required) == {"person.given_name", "person.family_name"}


def test_payroll_is_not_taken_by_hr_roster_one_name_group(pack, settings):
    assert run(csv_table("payroll.csv"), pack, settings).template_id == "payroll"


# ---- B3-03 / B3-07: confidence accounts for the share of columns explained ---------------------------------------------
def test_unexplained_columns_lower_the_reported_confidence(pack, settings):
    base = run(csv_table("hr_roster.csv"), pack, settings)
    t = csv_table("hr_roster.csv")
    wide = make_table([*t.header, "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9"],
                      [[*r, *(["zz qq"] * 9)] for r in t.df.drop("_src_row").rows()])
    m = run(wide, pack, settings)
    assert m.template_id == "hr_roster" or m.template_id is None
    assert m.confidence < base.confidence * 0.6


def test_calendar_hours_sheet_is_not_a_vendor_credential(pack, settings):
    """B3-03: Excel 'weekly work schedule' (hours per day, a date row) used to map to vendor_credential at 0.80."""
    header = ["EMPLOYEE\nNAME", "WORK ASSIGNED", "MON", "TUES", "WED", "THURS", "FRI", "SAT", "SUN", "HOURS"]
    rows = [["", "", "23-01-2023", "24-01-2023", "25-01-2023", "26-01-2023", "27-01-2023", "28-01-2023", "29-01-2023", ""],
            ["Ana", "Social Media statistical reporting", "3.00", "6.00", "4.50", "6.75", "12.00", "6.50", "4.00", "42.75"],
            ["", "", "", "", "", "", "", "", "", "0.00"]]
    m = run(make_table(header, rows), pack, settings)
    assert m.template_id != "vendor_credential" or m.confidence < settings["map.agent_min"]


def test_a_lone_value_in_a_longer_column_scores_half(pack):
    hit = lambda rows: profile_table(make_table(["Hours"], rows), build_validators(pack))[0].validator_hits["pay.hours_paid"]  # noqa: E731
    assert hit([["36"], [""], [""]]) == 0.5 and hit([["36"], ["40"], [""]]) == 1.0
    assert hit([["36"]]) == 1.0  # a one-row table (the e1 schedule pages) cannot have more evidence


@pytest.mark.parametrize("name", ["pbj_daily_nurse_sample.csv", "co_nurse_licenses.csv", "nyc_payroll.csv", "chicago_employees.csv"])
def test_unrelated_real_files_have_no_template(name, pack, settings):
    """B3-07: -> new_source_modeler (template None), not a schema_mapper task with nonsense columns."""
    df = pl.read_csv(RW / name, infer_schema_length=0, encoding="utf8-lossy")
    m = run(make_table(df.columns, df.rows()), pack, settings)
    assert m.template_id is None, (m.template_id, m.confidence, [(x.column, x.field_id) for x in m.matches])


def test_accented_name_columns_validate(pack):
    t = make_table(["first_name", "last_name"], [["José", "Peña"], ["Zoë", "Müller"], ["Renée", "O’Brien"]])
    hits = {p.column: p.validator_hits for p in profile_table(t, build_validators(pack))}
    assert hits["first_name"]["person.given_name"] == 1.0 and hits["last_name"]["person.family_name"] == 1.0


# ---- B-001 / B1-06 / B1-07: contracts ---------------------------------------------------------------------------------
def _payroll_variant(header):
    rows = [["REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36", "P-3001"],
            ["BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40", "P-3002"]]
    return make_table(header, rows)


def test_second_source_of_a_template_is_not_drift(db, pack, settings):
    """B-001: an unrelated header (Jaccard 0) mapping to a template already contracted is a new source, not drift."""
    map_table(csv_table("payroll.csv"), db, pack, settings)
    m = map_table(_payroll_variant(["Emp", "Cls", "Site", "Wk Beg", "Wk End", "Hrs", "Ref"]), db, pack, settings)
    assert m.template_id == "payroll" and not m.drift
    assert len(db.query("SELECT * FROM contracts")) == 2


def test_partly_renamed_header_is_drift(db, pack, settings):
    """B-001: the same source with 2 of 7 columns renamed (Jaccard 5/9) is drift; version bumps."""
    t = csv_table("payroll.csv")
    map_table(t, db, pack, settings)
    header = [*t.header[:5], "Hrs", "Ref"]
    m = map_table(_payroll_variant(header), db, pack, settings)
    assert m.template_id == "payroll" and m.drift


VENDOR_ROWS = [["Zenith Rehab,General Liability,ZR-9001,2025-10-20,2026-10-16,rep@z.example,1200".split(",")],
               ["Orchid Pool,Workers Comp,ON-7742,2025-11-02,2027-02-01,rep@o.example,900".split(",")]]
VENDOR_HDR = ["Carrier", "Coverage Kind", "Cert No", "Start", "End", "Rep Email", "Premium Paid"]
VENDOR_MAP = {"Carrier": "org.name", "Coverage Kind": "credential.doc_type", "Cert No": "credential.policy_number",
              "Start": "credential.issued_on", "End": "credential.expires_on", "Rep Email": "contact.email"}


def test_agent_contract_is_reused_for_the_same_header(db, pack, settings):
    """B1-06: validator-less / non_empty fields (org.name, doc_type) have value_score 0 and must not force drift."""
    t = make_table(VENDOR_HDR, [r[0] for r in VENDOR_ROWS])
    m = classify(t, profile_table(t, build_validators(pack)), pack, settings, forced=VENDOR_MAP)
    contracts.save_contract(db, m, t, "agent")
    again = map_table(make_table(VENDOR_HDR, [r[0] for r in VENDOR_ROWS]), db, pack, settings)
    assert again.source == "contract" and not again.drift


@pytest.mark.parametrize("number", ["NTL-2025-0042", "GL-2025-0042", "POL/778812", "778812", "ZR-9001"])
def test_policy_numbers_pass_the_loose_validator(pack, number):
    assert build_validators(pack)["credential.policy_number"](number)


@pytest.mark.parametrize("number", ["hello world", "", "--"])
def test_loose_policy_validator_still_needs_a_digit_shape(pack, number):
    assert not build_validators(pack)["credential.policy_number"](number)


def test_credential_number_stays_strict_and_license_does_not_use_policy_number(pack):
    assert not build_validators(pack)["credential.number"]("778812")
    assert "credential.policy_number" not in pack.templates["license"].fields
    assert "credential.policy_number" in pack.templates["vendor_credential"].fields


# ---- small tables are real inputs (e1 schedule pages have ONE staff row) ---------------------------------------------
@pytest.mark.parametrize("row", [["Sofia Reyes", "RN", "7a-3p", "7a-3p", "OFF", "7a-7p", "OFF", "7a-3p", "OFF"],
                                 ["Marc Bell", "CNA", "3p-11p", "OFF", "3p-11p", "3p-11p", "3p-11p", "3p-11p", "OFF"]])
def test_one_row_schedule_page_maps_at_auto_confidence(pack, settings, row):
    header = ["Staff", "Role", "Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
    m = run(make_table(header, [row]), pack, settings)
    assert m.template_id == "schedule" and m.confidence >= settings["map.auto_min"], m.confidence
