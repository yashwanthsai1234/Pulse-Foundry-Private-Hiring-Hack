"""Helpers for the R1 review tests: real pipeline over small CSV strings (agents off)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sot.config import load_settings
from sot.pipeline.orchestrator import Pipeline
from sot.store import repo

HR = ("employee_id,first_name,last_name,job_title,facility,phone,license_number,license_expiration,hire_date\n"
      "E201,Sofia,Reyes,Registered Nurse,Harborview Bayside,718-555-0201,RN-551203,2027-05-31,2020-03-02\n"
      "E202,Marcus,Bell,Certified Nursing Assistant,Harborview Riverdale,347-555-0202,CNA-771045,2026-12-31,2022-09-12\n")
PAY = ("payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid\n"
       "P-3001,\"REYES, SOFIA\",RN,BYS,2026-09-14,2026-09-20,36\n"
       "P-3002,\"BELL, MARCUS\",CNA,RVD,2026-09-14,2026-09-20,48\n")
LIC = ("license_number,name_on_license,license_type,expiration_date,last_verified\n"
       "RN-551203,\"REYES, SOFIA\",RN,2027-05-31,2026-09-01\n"
       "CNA-771045,\"BELL, MARCUS\",CNA,2026-12-31,2026-09-01\n")


def run_pipeline(tmp_path: Path, files: dict[str, str | bytes], as_of: date = date(2026, 9, 21)) -> Pipeline:
    settings = load_settings(runtime=tmp_path / "runtime")
    settings.agents = "off"
    settings.as_of = as_of
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    paths = []
    for name, body in files.items():
        p = src / name
        p.write_bytes(body if isinstance(body, bytes) else body.encode())
        paths.append(p)
    pipe = Pipeline(settings)
    pipe.ingest(paths, run_id="r1")
    return pipe


def issues(pipe: Pipeline, check_id: str | None = None):
    return [i for i in repo.load_issues(pipe.db) if check_id is None or i.check_id == check_id]


def gold_issues(tmp_path: Path, *, persons=(), shifts=(), pay=(), credentials=(), as_of: date = date(2026, 9, 21)):
    """Insert gold rows directly (no parsing) and run the real check engine. Returns the active issues."""
    from sot.checks.engine import run_checks
    from sot.core.pack import load_pack
    from sot.store.db import DB

    settings = load_settings(runtime=tmp_path / "runtime")
    settings.as_of = as_of
    db = DB(":memory:")
    base_p = {"person_id": None, "employee_id": None, "has_hr": True, "display_name": "Pat Doe", "role": "RN",
              "home_facility_id": "FAC-BAY", "phone": None, "hire_date": None}
    db.insert("persons", [{**base_p, **p} for p in persons])
    base_s = {"shift_id": None, "person_id": "P-E1", "facility_id": "FAC-BAY", "role": "RN", "work_date": date(2026, 9, 14),
              "start_ts": None, "end_ts": None, "hours": 8.0, "record_id": "rec", "loc": {"file_id": "f", "file_name": "f"}}
    db.insert("shifts", [{**base_s, **s} for s in shifts])
    base_pay = {"pay_id": None, "person_id": "P-E1", "facility_id": "FAC-BAY", "role": "RN", "period_start": date(2026, 9, 14),
                "period_end": date(2026, 9, 20), "hours_paid": 40.0, "record_id": "rec"}
    db.insert("pay_periods", [{**base_pay, **p} for p in pay])
    base_c = {"credential_id": None, "holder_type": "person", "holder_id": "P-E1", "holder_name": "Pat Doe",
              "credential_type": "RN", "number": "RN-100001", "issued_on": None, "expires_on": date(2027, 1, 1),
              "last_verified": None}
    db.insert("credentials", [{**base_c, **c} for c in credentials])
    pack = load_pack(settings.pack_dir)
    run_checks(db, pack, settings, "r1", [])
    return repo.load_issues(db)
