"""Field-by-field checker: JSON from the API vs frontend/src/api/types.ts (hand-encoded spec).
Spec notation: "s" string, "n" number, "b" bool, "any", suffix "?" optional (absent/null OK), "|null" nullable.
"""
from __future__ import annotations

SEV = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def _t(spec, v, path, errs):
    if isinstance(spec, str):
        opt = spec.endswith("?")
        nul = opt or spec.endswith("|null")
        base = spec.rstrip("?").replace("|null", "")
        if v is None:
            if not nul:
                errs.append(f"{path}: null, expected {spec}")
            return
        ok = {"s": isinstance(v, str), "n": isinstance(v, (int, float)) and not isinstance(v, bool),
              "b": isinstance(v, bool), "any": True, "o": isinstance(v, dict), "a": isinstance(v, list)}[base]
        if not ok:
            errs.append(f"{path}: {type(v).__name__} {str(v)[:40]!r}, expected {spec}")
    elif isinstance(spec, list):
        if not isinstance(v, list):
            errs.append(f"{path}: not a list ({type(v).__name__})")
            return
        for i, x in enumerate(v[:50]):
            _t(spec[0], x, f"{path}[{i}]", errs)
    elif isinstance(spec, dict):
        if "__map__" in spec:
            if not isinstance(v, dict):
                errs.append(f"{path}: not an object")
                return
            for k, x in v.items():
                _t(spec["__map__"], x, f"{path}.{k}", errs)
            return
        if not isinstance(v, dict):
            errs.append(f"{path}: not an object ({type(v).__name__})")
            return
        for k, s in spec.items():
            if k not in v:
                if not (isinstance(s, str) and s.endswith("?")):
                    errs.append(f"{path}.{k}: MISSING (expected {s if isinstance(s, str) else type(s).__name__})")
                continue
            _t(s, v[k], f"{path}.{k}", errs)


def check(spec, value, name="$"):
    errs: list[str] = []
    _t(spec, value, name, errs)
    return errs


LOC = {"file_id": "s", "file_name": "s", "page": "n?", "sheet": "s?", "row": "n?", "col": "s?", "bbox": "a?"}
LINK = {"a": "s", "b": "s", "prob": "n", "weight": "n", "method": "s", "reasons": ["s"]}
EVID = {"kind": "s", "label": "s", "text": "s", "loc": {**LOC} , "claim_id": "s?", "link": "o?", "is_golden": "b?", "raw": "o?"}
ISSUE = {"check_id": "s", "severity": "s", "title": "s", "message": "s", "entity_ids": ["s"], "facility_id": "s?",
         "period_start": "s?", "period_end": "s?", "key": "s", "action": "s?", "fingerprint": "s", "status": "s",
         "owner": "s?", "note": "s?", "first_seen_run": "s", "last_seen_run": "s", "active": "b"}
ISSUE_LIST = {**ISSUE, "evidence_count": "n", "person_name": "s|null"}
ISSUE_DETAIL = {**ISSUE, "evidence": [{**EVID, "loc": {**LOC}}], "person_name": "s|null"}
PERSON_ROW = {"person_id": "s", "employee_id": "s|null", "has_hr": "b", "display_name": "s", "role": "s|null",
              "home_facility_id": "s|null", "phone": "s|null", "hire_date": "s|null", "issue_count": "n"}
CLAIM = {"claim_id": "s", "entity_type": "s", "entity_id": "s", "attribute": "s", "value": "any", "value_type": "s",
         "template_id": "s", "record_id": "s", "loc": LOC, "observed_at": "s"}
GOLDEN = {"attribute": "s", "value": "any", "claim_id": "s", "rule": "s", "conflict": "b",
          "conflicting_claim_ids": ["s"], "claims": [CLAIM]}
CRED = {"credential_id": "s", "holder_type": "s", "holder_id": "s", "holder_name": "s", "credential_type": "s",
        "number": "s|null", "issued_on": "s|null", "expires_on": "s|null", "last_verified": "s|null",
        "days_left": "n|null"}
SHIFT = {"shift_id": "s", "facility_id": "s|null", "role": "s|null", "work_date": "s", "token": "s", "hours": "n|null",
         "loc": LOC}
SPECS = {
    "runs": [{"run_id": "s", "started_at": "s", "finished_at": "s|null", "status": "s", "file_count": "n"}],
    "summary": {"files": "n", "skipped": "n", "quarantined": "n", "tables": "n", "records": "n", "persons": "n",
                "issues_by_severity": {"__map__": "n"}, "agent_tasks": {"__map__": "n"}},
    "issues": [ISSUE_LIST],
    "issue": ISSUE_DETAIL,
    "people": [PERSON_ROW],
    "person": {"person": PERSON_ROW, "golden": [GOLDEN], "links": [LINK], "credentials": [CRED], "shifts": [SHIFT],
               "issues": [ISSUE_LIST]},
    "shifts": {"days": ["s"], "facilities": [{"facility_id": "s", "name": "s", "rn_coverage": {"__map__": "n"},
               "rows": [{"person_id": "s", "display_name": "s", "role": "s|null",
                         "cells": {"__map__": {"token": "s", "hours": "n|null", "license_valid": "b"}}}]}]},
    "credentials": [CRED],
    "contracts": [{"contract_id": "s", "template_id": "s", "header_fingerprint": "s", "version": "n",
                   "column_map": {"__map__": "s"}, "source": "s", "approved": "b", "created_at": "s"}],
    "agent-tasks": [{"task_id": "s", "kind": "s", "run_id": "s", "ref": "s", "prompt_version": "s",
                     "instructions": "s", "payload": "o", "status": "s", "created_at": "s"}],
    "settings": {"as_of": "s"},
}
