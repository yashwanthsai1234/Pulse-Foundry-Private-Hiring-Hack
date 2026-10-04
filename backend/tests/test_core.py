from sot.core.ids import issue_fingerprint
from sot.store import repo


def test_pack_loads(pack):
    assert {"hr_roster", "payroll", "license", "schedule", "vendor_credential"} <= set(pack.templates)
    assert "rn" in pack.vocabs["roles"].codes["RN"]
    assert pack.vocabs["roles"].scope["CNA"] == ["CNA", "LPN", "RN"]


def test_fingerprint_order_independent():
    assert issue_fingerprint("X", ["b", "a"], None, None, "") == issue_fingerprint("X", ["a", "b"], None, None, "")


def test_db_schema_and_known_file(db):
    assert db.query("SELECT count(*) AS n FROM issues")[0]["n"] == 0
    assert not repo.known_file(db, "nope")


def test_bulk_insert_is_fast_and_handles_json_dates_nulls(db):
    import time
    from datetime import date
    rows = [{"pay_id": f"p{i}", "person_id": None if i % 2 else "P-1", "facility_id": "F", "role": "RN",
             "period_start": date(2026, 9, 14), "period_end": date(2026, 9, 20), "hours_paid": 36.0 + i,
             "record_id": f"r{i}"} for i in range(20000)]
    t = time.perf_counter()
    db.insert("pay_periods", rows)
    assert time.perf_counter() - t < 2.0
    assert db.query("SELECT count(*) n, count(person_id) p FROM pay_periods")[0] == {"n": 20000, "p": 10000}
    db.insert("runs", [{"run_id": "r", "status": "x", "summary": {"a": [1, 2]}}])
    db.insert("runs", [{"run_id": "r", "status": "y", "summary": None}], replace=True)
    assert db.query("SELECT status, summary FROM runs") == [{"status": "y", "summary": None}]


def test_person_key_has_suffix():
    from sot.core.models import PersonKey
    assert PersonKey(display="Bell Jr., Marcus", suffix="jr").suffix == "jr"
