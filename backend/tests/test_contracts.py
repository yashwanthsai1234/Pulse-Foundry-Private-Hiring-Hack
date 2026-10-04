from sot.semantic.contracts import approve_contract, header_fingerprint, map_table
from test_mapper import csv_table, make_table


def test_fingerprint_ignores_order_case_and_dates():
    assert header_fingerprint(["A_b", "C"]) == header_fingerprint(["c", "a b"])
    assert header_fingerprint(["Mon 09/14"]) == header_fingerprint(["Mon 09/21"])
    assert header_fingerprint(["a"]) != header_fingerprint(["b"])


def test_contract_saved_then_reused(db, pack, settings):
    m1 = map_table(csv_table("payroll.csv"), db, pack, settings)
    assert m1.source == "auto" and not m1.drift
    rows = db.query("SELECT * FROM contracts")
    assert len(rows) == 1 and rows[0]["approved"] is False and rows[0]["version"] == 1
    assert list(settings.dir("contracts").glob("*.yaml"))
    m2 = map_table(csv_table("payroll.csv"), db, pack, settings)
    assert m2.source == "contract" and m2.contract_id == rows[0]["contract_id"] and not m2.drift
    assert {x.column: x.field_id for x in m2.matches} == {x.column: x.field_id for x in m1.matches}
    approve_contract(db, rows[0]["contract_id"])
    assert db.query("SELECT approved FROM contracts")[0]["approved"] is True


def test_drift_on_partly_renamed_headers(db, pack, settings):
    """B-001: drift = the same source with some columns renamed (headers mostly overlap); an unrelated header is a new source."""
    map_table(csv_table("payroll.csv"), db, pack, settings)
    header = ["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "Wk End", "Hrs"]
    rows = [["P-3001", "REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36"],
            ["P-3002", "BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40"]]
    m = map_table(make_table(header, rows), db, pack, settings)
    assert m.drift and m.source == "auto" and m.template_id == "payroll"
    assert sorted(r["version"] for r in db.query("SELECT version FROM contracts")) == [1, 2]


def test_drift_when_values_change_under_same_header(db, pack, settings):
    t = csv_table("payroll.csv")
    map_table(t, db, pack, settings)
    bad = make_table(t.header, [["x", "y", "z", "no", "no", "no", "no"], ["x", "y", "z", "no", "no", "no", "no"]])
    m = map_table(bad, db, pack, settings)
    assert m.drift and m.source != "contract"


def test_low_confidence_not_saved(db, pack, settings):
    m = map_table(make_table(["Foo", "Bar"], [["zzz", "qqq"]]), db, pack, settings)
    assert m.template_id is None
    assert db.query("SELECT * FROM contracts") == []
