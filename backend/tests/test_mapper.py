from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from sot.core.models import ExtractionInfo, FileRef, RawTable
from sot.semantic.classify import classify
from sot.semantic.mapper import assign
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators

FIX = Path(__file__).parent / "fixtures" / "readme_sample"


def make_table(header, rows, name="t"):
    data = {h: [r[i] for r in rows] for i, h in enumerate(header)}
    df = pl.DataFrame(data, schema={h: pl.Utf8 for h in header}).with_columns(
        pl.Series("_src_row", list(range(2, 2 + len(rows))), dtype=pl.Int64))
    f = FileRef(file_id=name * 12, file_name=f"{name}.csv", path=f"/x/{name}.csv", size=1, received_at=datetime(2026, 10, 4))
    return RawTable(table_id=f"{name}:0:0", file=f, parser="csv", header=header, df=df,
                    extraction=ExtractionInfo(method="csv", score=1.0))


def csv_table(name):
    df = pl.read_csv(FIX / name, infer_schema_length=0)
    return make_table(df.columns, df.rows(), name)


def run(t, pack, settings, forced=None):
    profiles = profile_table(t, build_validators(pack))
    return classify(t, profiles, pack, settings, forced)


def colmap(m):
    return {x.column: x.field_id for x in m.matches}


README = {
    "hr_roster.csv": ("hr_roster", {
        "employee_id": "person.employee_id", "first_name": "person.given_name", "last_name": "person.family_name",
        "job_title": "person.role", "facility": "person.facility", "phone": "person.phone",
        "license_number": "credential.number", "license_expiration": "credential.expires_on",
        "hire_date": "person.hire_date"}),
    "payroll.csv": ("payroll", {
        "payroll_id": "pay.payroll_id", "employee_name": "person.full_name", "job_code": "person.role",
        "facility_code": "person.facility", "period_start": "pay.period_start", "period_end": "pay.period_end",
        "hours_paid": "pay.hours_paid"}),
    "licenses.csv": ("license", {
        "license_number": "credential.number", "name_on_license": "person.full_name",
        "license_type": "credential.type", "expiration_date": "credential.expires_on",
        "last_verified": "credential.last_verified"}),
}


@pytest.mark.parametrize("name", README)
def test_readme_csvs(name, pack, settings):
    template, expected = README[name]
    m = run(csv_table(name), pack, settings)
    assert m.template_id == template
    assert m.confidence >= 0.8
    assert colmap(m) == expected
    assert m.missing_required == [] and m.unmapped_columns == [] and m.source == "auto"


def test_validators(pack):
    v = build_validators(pack)
    assert v["person.full_name"]("REYES, SOFIA") and v["person.full_name"]("Sofia Reyes")
    assert not v["person.full_name"]("Registered Nurse")
    assert v["credential.number"]("rn-551203") and not v["credential.number"]("hello")
    assert v["person.role"]("Registered Nurse") and not v["person.role"]("Harborview")
    assert v["person.phone"]("718-555-0201") and not v["person.phone"]("55")
    assert v["pay.hours_paid"]("36") and v["pay.hours_paid"]("500")  # form, not range: PAY-HOURS-INVALID flags it
    assert not v["pay.hours_paid"]("50000")
    assert v["schedule.day"]("7a-3p") and v["schedule.day"]("OFF") and not v["schedule.day"]("Sofia")
    assert v["contact.email"]("a@b.com") and not v["contact.email"]("a@b")
    assert v["pay.period_start"]("09/14/2026") and not v["pay.period_start"]("RN")


def test_profile(pack):
    t = csv_table("payroll.csv")
    p = {x.column: x for x in profile_table(t, build_validators(pack))}
    assert p["period_start"].inferred_type == "date"
    assert p["hours_paid"].inferred_type == "integer"
    assert p["employee_name"].validator_hits["person.full_name"] == 1.0
    assert p["employee_name"].n == 2 and p["employee_name"].distinct == 2


def test_schedule_with_day_columns(pack, settings):
    header = ["Staff", "Role", "Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
    rows = [["Sofia Reyes", "RN", "7a-3p", "7a-3p", "OFF", "7a-7p", "OFF", "7a-3p", "OFF"],
            ["Marc Bell", "CNA", "3p-11p", "OFF", "3p-11p", "3p-11p", "3p-11p", "3p-11p", "OFF"]]
    m = run(make_table(header, rows), pack, settings)
    assert m.template_id == "schedule" and m.confidence >= 0.8
    cm = colmap(m)
    assert cm["Staff"] == "person.full_name" and cm["Role"] == "person.role"
    assert [c for c, f in cm.items() if f == "schedule.day"] == header[2:]


def test_mangled_payroll_headers_no_agent(pack, settings):
    header = ["Emp", "Cls", "Site", "Wk Beg", "Wk End", "Hrs", "Ref"]
    rows = [["REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36", "P-3001"],
            ["BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40", "P-3002"]]
    m = run(make_table(header, rows), pack, settings)
    assert m.template_id == "payroll" and m.confidence >= 0.8
    assert colmap(m) == {"Emp": "person.full_name", "Cls": "person.role", "Site": "person.facility",
                         "Wk Beg": "pay.period_start", "Wk End": "pay.period_end", "Hrs": "pay.hours_paid",
                         "Ref": "pay.payroll_id"}


def test_relation_swaps_reversed_date_columns(pack, settings):
    header = ["Name", "Role", "Facility", "Date A", "Date B", "Hours", "Ref"]
    rows = [["REYES, SOFIA", "RN", "BYS", "2026-09-20", "2026-09-14", "36", "P-3001"],
            ["BELL, MARCUS", "CNA", "RVD", "2026-09-20", "2026-09-14", "40", "P-3002"]]
    cm = colmap(run(make_table(header, rows), pack, settings))
    assert cm["Date A"] == "pay.period_end" and cm["Date B"] == "pay.period_start"


def test_value_gate_header_alone_cannot_win(pack, settings):
    t = make_table(["Hours", "Name"], [["lots", "REYES, SOFIA"], ["many", "BELL, MARCUS"]])
    profiles = profile_table(t, build_validators(pack))
    ms = {m.column: m for m in assign(profiles, [pack.fields["pay.hours_paid"]], 0.35)}
    assert ms["Hours"].header_score == 1.0 and ms["Hours"].score == 0.4
    m = classify(t, profiles, pack, settings)
    assert "pay.hours_paid" not in colmap(m) and "Hours" in m.unmapped_columns


def test_vendor_file_not_license(pack, settings):
    header = ["Vendor", "Doc Type", "Policy #", "Eff", "Exp", "Contact"]
    rows = [["Acme Staffing", "Liability Insurance", "GL-99281", "01/01/2026", "12/31/2026", "ops@acme.com"],
            ["Nurse Temps LLC", "Workers Comp", "WC-55012", "02/01/2026", "01/31/2027", "hr@nt.com"]]
    m = run(make_table(header, rows), pack, settings)
    assert m.template_id != "license"
    assert m.template_id == "vendor_credential" or m.confidence < 0.8
    assert colmap(m)["Vendor"] == "org.name" and colmap(m)["Exp"] == "credential.expires_on"


def test_unknown_table_has_no_template(pack, settings):
    m = run(make_table(["Foo", "Bar"], [["zzz", "qqq"], ["yyy", "ppp"]]), pack, settings)
    assert m.template_id is None and m.confidence < settings["map.agent_min"]


def test_forced_mapping_from_agent(pack, settings):
    header = ["a", "b", "c", "d", "e", "f", "g"]
    rows = [["REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36", "P-3001"],
            ["BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40", "P-3002"]]
    forced = dict(zip(header, ["person.full_name", "person.role", "person.facility", "pay.period_start",
                               "pay.period_end", "pay.hours_paid", "pay.payroll_id"]))
    m = run(make_table(header, rows), pack, settings, forced)
    assert m.template_id == "payroll" and m.source == "agent" and m.confidence >= 0.8
    assert colmap(m) == forced
