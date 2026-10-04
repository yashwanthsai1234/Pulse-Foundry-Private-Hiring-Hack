"""R1-08/09: payroll per facility vs scheduled hours; PBJ midnight split."""
from datetime import date, datetime

from sot.core.pack import load_pack
from sot.config import load_settings
from sot.exports.pbj import build_pbj
from sot.store.db import DB
from tests.review.r1_support import gold_issues


def test_split_payroll_across_facilities_is_compared_per_facility(tmp_path):
    shifts = [{"shift_id": f"s{i}", "work_date": date(2026, 9, 14 + i), "hours": 12} for i in range(3)]
    shifts.append({"shift_id": "r1", "facility_id": "FAC-RVD", "work_date": date(2026, 9, 18), "hours": 8})
    pay = [{"pay_id": "a", "hours_paid": 36}, {"pay_id": "b", "facility_id": "FAC-RVD", "hours_paid": 8}]
    found = gold_issues(tmp_path, persons=[{"person_id": "P-E1"}], shifts=shifts, pay=pay)
    assert [i.message for i in found if i.check_id == "HRS-PAID-VS-SCHED"] == []  # 36 h at BAY and 8 h at RVD both match


def test_pbj_splits_an_overnight_shift_at_midnight(tmp_path):
    """CMS PBJ is calendar-day based: 11p-7a on 09/14 is 1 h on 09/14 and 7 h on 09/15."""
    settings = load_settings(runtime=tmp_path / "rt")
    pack = load_pack(settings.pack_dir)
    db = DB(":memory:")
    db.insert("persons", [{"person_id": "P-E1", "employee_id": "E1", "has_hr": True, "display_name": "Pat Doe", "role": "RN",
                           "home_facility_id": "FAC-BAY", "phone": None, "hire_date": None}])
    db.insert("shifts", [{"shift_id": "s", "person_id": "P-E1", "facility_id": "FAC-BAY", "role": "RN",
                          "work_date": date(2026, 9, 14), "start_ts": datetime(2026, 9, 14, 23), "end_ts": datetime(2026, 9, 15, 7),
                          "hours": 8.0, "record_id": "r", "loc": {"file_id": "f", "file_name": "f"}}])
    rows = {str(r["work_date"]): r["hours"] for r in build_pbj(db, pack, settings).iter_rows(named=True)}
    assert rows == {"2026-09-14": 1.0, "2026-09-15": 7.0}
