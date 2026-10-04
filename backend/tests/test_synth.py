"""Tests for the synthetic generator, mutators and chaos comparison math (IMPLEMENTATION section 19)."""
from __future__ import annotations

import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

import openpyxl
import pymupdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tools.synth import chaos
from tests.synth_support import rn_gaps
from tools.synth.generator import CATALOG, HR_HEADER, LIC_HEADER, PAY_HEADER, generate_world, plant_defects, write_world
from tools.synth.mutators import MUTATORS, decode

SAMPLE = Path(__file__).parent / "fixtures" / "readme_sample"
FILES = ["hr_roster.csv", "payroll.csv", "licenses.csv", "schedule.json"]


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def dump(world, tmp_path: Path, name: str) -> Path:
    out = tmp_path / name
    write_world(world, out, "grid")
    return out


def test_determinism(tmp_path):
    a, b = (dump(generate_world(5, 20, 2), tmp_path, n) for n in "ab")
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f
    c = dump(generate_world(6, 20, 2), tmp_path, "c")
    assert (a / "hr_roster.csv").read_bytes() != (c / "hr_roster.csv").read_bytes()


def test_defaults_cover_rn_and_roles():
    w = generate_world(1, 40, 2)
    assert rn_gaps(w) == []
    roles = [s.role for s in w.staff]
    assert roles.count("RN") == 12 and roles.count("LPN") == 6 and roles.count("CNA") == 22
    assert len({s.employee_id for s in w.staff}) == 40 and len({s.license_number for s in w.staff}) == 40
    assert len({s.family for s in w.staff}) == 40


@given(seed=st.integers(0, 10_000), n=st.integers(12, 60), weeks=st.integers(1, 2))
@settings(max_examples=15, deadline=None)
def test_property_defaults_are_clean(seed, n, weeks):
    w = generate_world(seed, n, weeks)
    assert rn_gaps(w) == []
    assert all(s.license_exp > w.start + timedelta(days=100) for s in w.staff)


def test_headers_exact_and_payroll_matches_schedule(tmp_path):
    out = dump(generate_world(2, 30, 2), tmp_path, "w")
    assert list(read_csv(out / "hr_roster.csv")[0]) == HR_HEADER == (
        "employee_id,first_name,last_name,job_title,facility,phone,license_number,license_expiration,hire_date".split(","))
    assert PAY_HEADER == "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid".split(",")
    assert LIC_HEADER == "license_number,name_on_license,license_type,expiration_date,last_verified".split(",")
    assert list(read_csv(out / "payroll.csv")[0]) == PAY_HEADER
    assert list(read_csv(out / "licenses.csv")[0]) == LIC_HEADER
    hours = {"7a-3p": 8, "3p-11p": 8, "11p-7a": 8, "7a-7p": 12}
    sched: dict[str, float] = {}
    for f in ("schedule.json", "schedule_w2.json"):
        spec = json.loads((out / f).read_text())
        for page in spec["pages"]:
            for row in page["rows"]:
                sched[row[0]] = sched.get(row[0], 0) + sum(hours.get(c, 0) for c in row[2:])
    paid: dict[str, float] = {}
    for r in read_csv(out / "payroll.csv"):
        last, first = r["employee_name"].split(", ")
        paid[f"{first.title()} {last.title()}"] = paid.get(f"{first.title()} {last.title()}", 0) + float(r["hours_paid"])
    assert {k.lower(): v for k, v in paid.items()} == {k.lower(): v for k, v in sched.items() if v}


def test_pdf_renders_every_name(tmp_path):
    w = generate_world(3, 20, 1)
    out = dump(w, tmp_path, "w")
    doc = pymupdf.open(out / "schedule.pdf")
    assert doc.page_count == 2
    text = "\n".join(p.get_text() for p in doc)
    spec = json.loads((out / "schedule.json").read_text())
    names = [row[0] for page in spec["pages"] for row in page["rows"]]
    assert names and all(n in text for n in names)
    assert "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours." in text


def planted(name, seed=11):
    base = generate_world(seed, 40, 2)
    w, exp = plant_defects(base, [name], seed)
    return base, w, exp


EXPECT_ID = {
    "worked_after_expiry": "LIC-WORKED-EXPIRED", "expiring_in_20_days": "LIC-EXPIRING",
    "hr_vs_license_expiry_conflict": "SRC-CONFLICT", "paid_vs_scheduled_delta": "HRS-PAID-VS-SCHED",
    "payroll_person_not_in_hr": "PAY-NO-HR", "schedule_person_not_in_hr": "SCHED-NO-HR",
    "duplicate_license_number": "ID-DUP-LICENSE", "cna_on_rn_shift": "LIC-SCOPE",
    "float_to_other_facility": "FAC-MISMATCH", "overlapping_shifts_two_facilities": "SHIFT-OVERLAP",
    "missing_rn_day": "COV-RN-DAILY", "legend_mismatch_token": "LEGEND-MISMATCH", "bad_date_value": "PARSE-DATE",
    "ambiguous_date_column": "PARSE-DATE-AMBIGUOUS", "hr_duplicate_row": "HR-DUP-ROW",
    "maiden_name_on_license": "ID-NAME-DIFFERS-ON-LICENSE", "nickname_on_schedule": "ID-FUZZY-LINK",
    "typo_family_name": "ID-FUZZY-LINK",
}
CHANGES = {
    "nickname_on_schedule": {"schedule.json"}, "typo_family_name": {"schedule.json"},
    "maiden_name_on_license": {"licenses.csv"}, "worked_after_expiry": {"hr_roster.csv", "licenses.csv"},
    "expiring_in_20_days": {"hr_roster.csv", "licenses.csv"}, "hr_vs_license_expiry_conflict": {"hr_roster.csv"},
    "paid_vs_scheduled_delta": {"payroll.csv"}, "payroll_person_not_in_hr": {"payroll.csv"},
    "schedule_person_not_in_hr": {"schedule.json", "licenses.csv"},
    "duplicate_license_number": {"hr_roster.csv", "licenses.csv"}, "cna_on_rn_shift": {"schedule.json"},
    "float_to_other_facility": {"schedule.json"},
    "overlapping_shifts_two_facilities": {"schedule.json", "payroll.csv"},
    "missing_rn_day": {"schedule.json", "payroll.csv"}, "legend_mismatch_token": {"schedule.json"},
    "bad_date_value": {"hr_roster.csv"}, "ambiguous_date_column": {"hr_roster.csv"},
    "phone_format_mix": {"hr_roster.csv"}, "hr_duplicate_row": {"hr_roster.csv"},
    "whitespace_case_noise": {"hr_roster.csv"}, "last_first_in_payroll": set(),
    "two_people_same_family_name": set(FILES),
}


def test_catalog_is_complete():
    assert set(CATALOG) == set(CHANGES)


@pytest.mark.parametrize("name", CATALOG)
def test_each_defect_changes_only_what_it_claims(name, tmp_path):
    base, w, exp = planted(name)
    a, b = dump(base, tmp_path, "a"), dump(w, tmp_path, "b")
    changed = {f for f in FILES if (a / f).read_bytes() != (b / f).read_bytes()}
    assert changed == CHANGES[name]
    if name in EXPECT_ID:
        assert [e.check_id for e in exp][:1] == [EXPECT_ID[name]] and exp[0].severity
    json.loads((b / "expected_issues.json").read_text())
    json.loads((b / "truth.json").read_text())


def staff_by_id(w):
    return {s.employee_id: s for s in w.staff}


def test_worked_after_expiry_and_expiring():
    _, w, exp = planted("worked_after_expiry")
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    assert s.license_exp < max(x.work_date for x in w.shifts if x.employee_id == s.employee_id)
    assert s.hr_exp == s.license_exp
    _, w, exp = planted("expiring_in_20_days")
    assert staff_by_id(w)[exp[0].employee_ids[0]].license_exp == w.as_of + timedelta(days=20)


def test_conflict_scope_float_overlap_missing():
    _, w, exp = planted("hr_vs_license_expiry_conflict")
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    assert s.hr_exp != s.license_exp
    _, w, exp = planted("cna_on_rn_shift")
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    assert s.license_type == "CNA" and any(x.role == "RN" for x in w.shifts if x.employee_id == s.employee_id)
    _, w, exp = planted("float_to_other_facility")
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    assert any(x.facility != s.facility for x in w.shifts if x.employee_id == s.employee_id)
    _, w, exp = planted("overlapping_shifts_two_facilities")
    mine = [x for x in w.shifts if x.employee_id == exp[0].employee_ids[0]]
    assert any(x.work_date == y.work_date and x.facility != y.facility for x in mine for y in mine)
    _, w, exp = planted("missing_rn_day")
    assert [e.facility_id for e in exp] == ["FAC-RVD"]
    assert rn_gaps(w) == [("FAC-RVD", w.start + timedelta(days=3))]


def test_file_level_defects(tmp_path):
    _, w, exp = planted("paid_vs_scheduled_delta")
    assert exp[0].employee_ids
    _, w, exp = planted("payroll_person_not_in_hr")
    out = dump(w, tmp_path, "p")
    hr_ids = {r["employee_id"] for r in read_csv(out / "hr_roster.csv")}
    assert len(staff_by_id(w)) == 41 and sum(1 for s in w.staff if s.employee_id not in hr_ids) == 1
    _, w, _ = planted("schedule_person_not_in_hr")
    assert sum(1 for s in w.staff if not s.in_hr) == 1
    _, w, exp = planted("duplicate_license_number")
    out = dump(w, tmp_path, "d")
    nums = [r["license_number"] for r in read_csv(out / "licenses.csv")]
    assert len(nums) - len(set(nums)) == 1 and len(exp[0].employee_ids) == 2
    _, w, exp = planted("legend_mismatch_token")
    spec = w and json.loads((dump(w, tmp_path, "l") / "schedule.json").read_text())
    assert "7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours." not in spec["footnote"]
    _, w, exp = planted("bad_date_value")
    out = dump(w, tmp_path, "b")
    assert [r["hire_date"] for r in read_csv(out / "hr_roster.csv")].count("2020-02-30") == 1
    _, w, exp = planted("ambiguous_date_column")
    out = dump(w, tmp_path, "m")
    assert all(int(r["hire_date"][:2]) <= 12 and "/" in r["hire_date"] for r in read_csv(out / "hr_roster.csv"))
    _, w, exp = planted("phone_format_mix")
    out = dump(w, tmp_path, "ph")
    assert len({"".join(c if c in "()." else "x" if c.isdigit() else c for c in r["phone"])
                for r in read_csv(out / "hr_roster.csv")}) >= 3
    _, w, exp = planted("hr_duplicate_row")
    out = dump(w, tmp_path, "h")
    ids = [r["employee_id"] for r in read_csv(out / "hr_roster.csv")]
    assert ids.count(exp[0].employee_ids[0]) == 2


def test_same_family_and_nickname_expectations():
    _, w, exp = planted("two_people_same_family_name")
    a, b = (staff_by_id(w)[e] for e in exp[0].employee_ids)
    assert exp[0].kind == "no_merge" and a.family == b.family and a.given != b.given
    _, w, exp = planted("nickname_on_schedule")
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    assert exp[0].kind == "link" and s.sched_name and s.sched_name.split()[0] != s.given


def test_full_catalogue_together(tmp_path):
    w, exp = plant_defects(generate_world(4, 40, 2), CATALOG, 4)
    out = dump(w, tmp_path, "all")
    assert len(json.loads((out / "expected_issues.json").read_text())) == len(exp) > 15
    assert len(json.loads((out / "truth.json").read_text())["persons"]) == len(w.staff)


@pytest.mark.parametrize("name", MUTATORS)
@pytest.mark.parametrize("fname", ["hr_roster.csv", "payroll.csv", "licenses.csv"])
def test_mutators_keep_rows_and_never_touch_input(name, fname):
    src = SAMPLE / fname
    before = src.read_bytes()
    out = MUTATORS[name](src, random.Random(3))
    assert src.read_bytes() == before and out != src
    try:
        original = list(csv.reader(io.StringIO(before.decode())))[1:]
        if out.suffix == ".xlsx":
            rows = [[str(c) for c in r if c is not None] for r in openpyxl.load_workbook(out).active.iter_rows(values_only=True)]
        else:
            data = out.read_bytes()
            text = decode(data)
            delim = max(",;\t", key=lambda d: text.splitlines()[-1 if name == "title_rows_above_header" else 0].count(d))
            rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        rows = [r for r in rows if any(c.strip() for c in r)]
        for rec in original:
            assert sum(1 for r in rows if rec[0] in [c.strip().strip('"') for c in r]) == 1
        if name == "to_xlsx":
            assert out.suffix == ".xlsx"
        if name == "encoding_latin1_bom":
            assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    finally:
        out.unlink()


def test_synonym_headers_and_chain(tmp_path):
    out = MUTATORS["rename_headers_synonyms"](SAMPLE / "payroll.csv", random.Random(1))
    header = out.read_text().splitlines()[0].split(",")
    assert "employee_name" not in header and "hours_paid" not in header
    out.unlink()
    for name in ["hr_roster.csv", "payroll.csv", "licenses.csv"]:
        src = tmp_path / name
        src.write_bytes((SAMPLE / name).read_bytes())
        res = chaos.apply_chain(src, list(MUTATORS)[:-1], random.Random(2), tmp_path / "out")
        assert res.exists() and res.name.startswith(src.stem)


def test_chaos_gold_snapshot_and_diff():
    class FakeDB:
        def query(self, sql):
            return {"persons": [{"person_id": "P-E1", "employee_id": "E1", "display_name": "A B", "role": "RN",
                                 "phone": "7185550101"}],
                    "credentials": [{"credential_id": "C1", "number": "RN-1", "expires_on": date(2027, 1, 1)}]}[
                sql.split("FROM ")[1].split()[0]]

    snap = chaos.gold_snapshot(FakeDB())
    assert snap["persons"] == [(("display_name", "a b"), ("employee_id", "E1"), ("phone", "7185550101"), ("role", "RN"))]
    assert chaos.gold_diff(snap, snap, set()) == []
    other = {"persons": [], "credentials": snap["credentials"]}
    assert len(chaos.gold_diff(snap, other, set())) == 1
    ph = {"persons": [(("employee_id", "E1"), ("phone", "x"))], "credentials": []}
    pb = {"persons": [(("employee_id", "E1"), ("phone", "y"))], "credentials": []}
    assert chaos.gold_diff(ph, pb, {"phone"}) == []


def test_chaos_issue_matching_math():
    expected = [
        {"check_id": "LIC-WORKED-EXPIRED", "employee_ids": ["E1"], "facility_id": None},
        {"check_id": "COV-RN-DAILY", "employee_ids": [], "facility_id": "FAC-RVD"},
        {"check_id": "PAY-NO-HR", "employee_ids": [], "facility_id": None},
        {"check_id": "SRC-CONFLICT", "employee_ids": ["E2"], "facility_id": None},
    ]
    actual = [
        {"check_id": "LIC-WORKED-EXPIRED", "entity_ids": ["P-E1"], "facility_id": None},
        {"check_id": "COV-RN-DAILY", "entity_ids": [], "facility_id": "FAC-BAY"},
        {"check_id": "COV-RN-DAILY", "entity_ids": [], "facility_id": "FAC-RVD"},
        {"check_id": "SRC-CONFLICT", "entity_ids": ["RN-22"], "facility_id": None},
        {"check_id": "SHIFT-OVERLAP", "entity_ids": ["P-E9"], "facility_id": None},
        {"check_id": "SOMETHING-ELSE", "entity_ids": [], "facility_id": None},
    ]
    aliases = {"E1": {"P-E1"}, "E2": {"P-E2", "RN-22"}}
    m = chaos.match_issues(expected, actual, aliases)
    assert (m["matched"], m["expected"], m["actual_checked"]) == (3, 4, 5)
    assert [e["check_id"] for e in m["missed"]] == ["PAY-NO-HR"]
    assert m["recall"] == 0.75 and m["precision"] == 0.6


def test_chaos_summary_and_report():
    ok = {"variant": "v0", "golden_equal": True, "matched": 3, "expected": 3, "actual_checked": 4, "mutators": {}}
    bad = {"variant": "v1", "golden_equal": False, "matched": 1, "expected": 3, "actual_checked": 1,
           "mutators": {"hr_roster.csv": ["to_xlsx"]}, "diff": ["x"]}
    err = {"variant": "v2", "error": "boom", "mutators": {"payroll.csv": ["quote_all"]}}
    s = chaos.summarize([ok, bad, err])
    assert s["variants"] == 3 and s["errors"] == 1
    assert s["golden_equality_rate"] == 0.5 and s["recall"] == 4 / 6 and s["precision"] == 4 / 5
    assert [f["variant"] for f in s["failures"]] == ["v1", "v2"]
    md = chaos.render_md(s, [ok, bad, err])
    assert "to_xlsx" in md and "boom" in md and "recall" in md.lower()


def test_run_variant_glue_with_fake_pipeline(tmp_path, monkeypatch):
    class FakeDB:
        def query(self, sql):
            if "FROM issues" in sql:
                return []
            return {"persons": [{"person_id": "P-E201", "display_name": "x"}], "credentials": []}.get(
                sql.split("FROM ")[1].split()[0], [])

    seen = []
    monkeypatch.setattr(chaos, "_ingest",
                        lambda files, as_of, runtime, scans=None: seen.append(sorted(f.suffix for f in files)) or FakeDB())
    r = chaos.run_variant(0, 7, tmp_path, clean_too=True)
    assert "error" not in r, r.get("error")
    assert len(seen) == 2 and r["golden_equal"] is False and r["recall"] == 0.0
    assert r["clean"]["recall"] == 0.0 and r["clean"]["expected"] == r["expected"]
    assert set(r["mutators"]) == {"hr_roster.csv", "payroll.csv", "licenses.csv"}
    assert all(1 <= len(v) <= 3 for v in r["mutators"].values())


def test_wildcard_expectation_does_not_steal_a_specific_issue():  # RC13
    expected = [{"check_id": "HRS-PAID-VS-SCHED", "employee_ids": [], "facility_id": None},
                {"check_id": "HRS-PAID-VS-SCHED", "employee_ids": ["E233"], "facility_id": None}]
    actual = [{"check_id": "HRS-PAID-VS-SCHED", "entity_ids": ["P-E233"], "facility_id": None}]
    m = chaos.match_issues(expected, actual, {"E233": {"P-E233"}})
    assert m["matched"] == 1 and [e["employee_ids"] for e in m["missed"]] == [[]]


def test_golden_comparison_ignores_name_case():  # RC14
    class FakeDB:
        def __init__(self, name):
            self.name = name

        def query(self, sql):
            if "persons" in sql:
                return [{"person_id": "P-E1", "display_name": self.name, "role": "RN"}]
            return [{"credential_id": "C1", "holder_name": self.name, "number": "RN-1"}]

    assert chaos.gold_snapshot(FakeDB("Ann Lee")) == chaos.gold_snapshot(FakeDB("ANN LEE"))
    assert chaos.gold_snapshot(FakeDB("Ann Lee")) != chaos.gold_snapshot(FakeDB("Ann Lea"))


def test_duplicate_license_expects_a_name_difference_per_holder():  # RC16
    _, _, exp = planted("duplicate_license_number")
    dup = next(e for e in exp if e.check_id == "ID-DUP-LICENSE")
    named = [e for e in exp if e.check_id == "ID-NAME-DIFFERS-ON-LICENSE"]
    assert sorted(x for e in named for x in e.employee_ids) == sorted(dup.employee_ids)


def test_legend_mismatch_is_expected_once_per_table_and_token():
    _, w, exp = planted("legend_mismatch_token")
    tables = {(x.facility, (x.work_date - w.start).days // 7) for x in w.shifts if x.token == "11p-7a"}
    assert len([e for e in exp if e.check_id == "LEGEND-MISMATCH"]) == len(tables) > 1
    assert not any(e.check_id == "LEGEND-MISMATCH" for e in planted("cna_on_rn_shift")[2])


def test_cna_on_rn_and_missing_rn_day_coexist():  # RC18
    w, exp = plant_defects(generate_world(11, 40, 2), ["cna_on_rn_shift", "missing_rn_day"], 11)
    assert rn_gaps(w) == [("FAC-RVD", w.start + timedelta(days=3))]
    s = staff_by_id(w)[exp[0].employee_ids[0]]
    fac = next(x.facility for x in w.shifts if x.employee_id == s.employee_id and x.role == "RN")
    assert all(x.role == "RN" for x in w.shifts if x.employee_id == s.employee_id and x.facility == fac)


def test_combinations_that_hide_a_defect_are_not_generated():  # RC18
    assert "drop_optional_column" not in chaos.allowed_mutators("hr_roster.csv", ["hr_duplicate_row"])
    assert "drop_optional_column" in chaos.allowed_mutators("payroll.csv", ["hr_duplicate_row"])
    assert "drop_optional_column" in chaos.allowed_mutators("hr_roster.csv", ["missing_rn_day"])
    assert "no_footnote" not in chaos.pdf_variants(["legend_mismatch_token"])
    assert "no_footnote" in chaos.pdf_variants(["missing_rn_day"])


def test_spec_page_reader_answers_from_the_spec(tmp_path):  # RC17
    import asyncio
    from types import SimpleNamespace

    spec = {"header": ["Staff", "Role"], "footnote": "Shifts: x", "pages": [
        {"title": "A", "subtitle": "Week", "rows": [["a", "RN"]]}, {"title": "B", "rows": [["b", "CNA"]]}]}
    out = tmp_path / "done.json"
    settings = SimpleNamespace(dir=lambda name: tmp_path)
    task = SimpleNamespace(payload={"file_id": "abc", "page": 2}, output_path=str(out), task_id="t-1",
                           model_dump_json=lambda indent=None: "{}")
    asyncio.run(chaos.SpecPageReader(settings, {"abc": spec}).submit(task))
    assert json.loads(out.read_text()) == {"title": "B", "header": ["Staff", "Role"], "rows": [["b", "CNA"]],
                                           "footnote": "Shifts: x"}


def test_report_shows_clean_next_to_mutated():
    ok = {"variant": "v0", "golden_equal": True, "matched": 3, "expected": 4, "actual_checked": 4, "mutators": {},
          "clean": {"matched": 4, "expected": 4, "actual_checked": 4, "missed": [], "unexpected": []}}
    s = chaos.summarize([ok])
    assert s["clean"]["recall"] == 1.0 and s["recall"] == 0.75
    md = chaos.render_md(s, [ok])
    assert "clean (unmutated)" in md and "| mutated |" in md
