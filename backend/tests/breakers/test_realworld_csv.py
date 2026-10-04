"""W3-B3: real-world CSVs (CMS PBJ, CO/TX nurse licences, NYC/Chicago payroll, cp1252+CRLF) through the real Pipeline."""
import functools
import tempfile

import pytest

from tests.breakers.rw_harness import RW, ingest

UNRELATED = ["pbj_daily_nurse_sample.csv", "co_nurse_licenses.csv", "tx_rn_active.csv", "nyc_payroll.csv",
             "chicago_employees.csv", "tx_rn_cp1252_crlf.csv"]


@functools.lru_cache(maxsize=None)
def run(name):
    p, _, err = ingest(RW / name, tempfile.mkdtemp())
    return p, err


def mapping(name):
    p, err = run(name)
    assert err is None, f"pipeline crashed: {err!r}"
    return p.db.query("SELECT * FROM mappings")[0]


@pytest.mark.parametrize("name", UNRELATED)
def test_no_crash_and_not_auto_mapped(name):
    m = mapping(name)
    assert m["status"] != "mapped", f"{name} silently auto-mapped to {m['template_id']} ({m['confidence']:.2f})"
    p, _ = run(name)
    assert p.db.query("SELECT count(*) n FROM source_records")[0]["n"] == 0


@pytest.mark.parametrize("name", ["pbj_daily_nurse_sample.csv", "co_nurse_licenses.csv", "nyc_payroll.csv", "chicago_employees.csv"])
def test_unrelated_file_gets_modeler_not_hr_roster_mapper(name):
    """Facility-day hours / licence lists / city payroll are not an HR roster: the clear path is the new-source modeler,
    not a schema_mapper task that proposes hr_roster with nonsense column matches."""
    p, _ = run(name)
    kinds = [r["kind"] for r in p.db.query("SELECT kind FROM agent_tasks")]
    assert kinds == ["new_source_modeler"], kinds


def test_pbj_state_and_county_not_mapped_to_person_names():
    m = mapping("pbj_daily_nurse_sample.csv")
    bad = [(x["column"], x["field_id"]) for x in m["matches"]
           if x["column"] in ("STATE", "COUNTY_NAME", "PROVNAME", "CITY") and x["field_id"].startswith("person.")]
    assert not bad, bad


def test_cp1252_crlf_decodes_and_maps_when_names_have_accents():
    """Real HR export: Windows-1252, CRLF, a few accented names (José Peña, Zoë Müller, Renée O’Brien)."""
    m = mapping("hr_roster_cp1252_crlf.csv")
    assert m["status"] == "mapped" and m["template_id"] == "hr_roster", (
        f"{m['status']} {m['template_id']} {m['confidence']:.2f}; unmapped={m['unmapped']} missing={m['missing_required']}")


def test_cp1252_crlf_values_not_mojibake():
    p, _ = run("hr_roster_cp1252_crlf_10rows.csv")
    names = {r["display_name"] for r in p.db.query("SELECT display_name FROM persons")}
    assert {"José Peña", "Zoë Müller", "María Gonzalez"} <= names


def test_cp1252_10_rows_accented_names_map_both_name_columns():
    m = mapping("hr_roster_cp1252_crlf_10rows.csv")
    cols = {x["column"]: x["score"] for x in m["matches"]}
    assert m["status"] == "mapped"
    assert cols["first_name"] >= 0.95 and cols["last_name"] >= 0.95, cols  # accents must not lower the validator share
