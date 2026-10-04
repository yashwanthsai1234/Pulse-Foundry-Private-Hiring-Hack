"""Read endpoints over the gold tables, issues, contracts, exports and settings (IMPLEMENTATION §17).

Sources:
- https://fastapi.tiangolo.com/tutorial/query-params/
- https://duckdb.org/docs/stable/clients/python/dbapi (parameterised queries)
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from sot.core.models import SEVERITY_ORDER, IssueStatus
from sot.exports.issues_csv import issues_csv
from sot.exports.pbj import build_pbj
from sot.semantic.contracts import approve_contract
from sot.store import repo

router = APIRouter()
AS_OF_FILE = "as_of.txt"  # the chosen as-of date survives a restart (it is the only setting the UI changes)


def rows(request: Request, sql: str, params: list | None = None) -> list[dict]:
    """JSON columns come back decoded (DB.query)."""
    return request.app.state.db.query(sql, params)


@router.get("/summary")
def summary(request: Request) -> dict:
    def n(sql: str) -> int:
        return rows(request, sql)[0]["n"]

    def by(sql: str) -> dict:
        return {r["k"]: r["n"] for r in rows(request, sql)}

    latest = rows(request, "SELECT summary FROM runs WHERE summary IS NOT NULL ORDER BY started_at DESC LIMIT 1")
    return {
        "files": n("SELECT count(*) n FROM files"), "skipped": latest[0]["summary"]["skipped"] if latest else 0,
        "quarantined": n("SELECT count(*) n FROM files WHERE status = 'quarantined'"),
        "tables": n("SELECT count(*) n FROM raw_tables"), "records": n("SELECT count(*) n FROM source_records"),
        "persons": n("SELECT count(*) n FROM persons"),
        "issues_by_severity": by("SELECT severity k, count(*) n FROM issues WHERE active AND status = 'open' GROUP BY 1"),
        "agent_tasks": by("SELECT status k, count(*) n FROM agent_tasks GROUP BY 1"),
    }


@router.get("/files")
def files(request: Request) -> list[dict]:
    out = rows(request, "SELECT * FROM files ORDER BY received_at")
    tables = rows(request, "SELECT t.table_id, t.file_id, t.page, t.sheet, t.n_rows, t.extraction, m.template_id, "
                  "m.confidence, m.status, m.source, m.drift FROM raw_tables t LEFT JOIN mappings m USING (table_id) "
                  "ORDER BY t.table_id")
    for f in out:
        f["tables"] = [t for t in tables if t["file_id"] == f["file_id"]]
    return out


def _person_names(request: Request) -> dict[str, str]:
    return {r["person_id"]: r["display_name"] for r in rows(request, "SELECT person_id, display_name FROM persons")}


def _person_name(names: dict[str, str], issue) -> str | None:
    return next((names[e] for e in issue.entity_ids if e in names), None)


def _issue_summary(names: dict[str, str], issue) -> dict:
    """An issue without its evidence, plus the evidence count and the first person it names."""
    return {**issue.model_dump(exclude={"evidence"}), "evidence_count": len(issue.evidence),
            "person_name": _person_name(names, issue)}


def _where(*conditions: tuple[str, Any]) -> tuple[str, list]:
    """AND of every (sql condition with one ?, value) whose value is not None, with the values in order."""
    used = [(cond, val) for cond, val in conditions if val is not None]
    return " AND ".join(["TRUE", *(cond for cond, _ in used)]), [val for _, val in used]


def _issue_or_404(request: Request, fingerprint: str) -> dict:
    for i in repo.load_issues(request.app.state.db, active_only=False):
        if i.fingerprint == fingerprint:
            return {**i.model_dump(), "person_name": _person_name(_person_names(request), i)}
    raise HTTPException(404, "unknown issue")


@router.get("/issues")
def issues(request: Request, severity: str | None = None, status: str | None = None, check_id: str | None = None,
           person_id: str | None = None, active: bool = True) -> list[dict]:
    names = _person_names(request)
    found = [i for i in repo.load_issues(request.app.state.db, active_only=False)
             if i.active == active and (not severity or i.severity == severity) and (not status or i.status == status)
             and (not check_id or i.check_id == check_id) and (not person_id or person_id in i.entity_ids)]
    found.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.check_id, i.fingerprint))
    return [_issue_summary(names, i) for i in found]


@router.get("/issues/{fingerprint}")
def issue(request: Request, fingerprint: str) -> dict:
    return _issue_or_404(request, fingerprint)


class IssuePatch(BaseModel):
    status: IssueStatus
    owner: str | None = None
    note: str | None = None


@router.patch("/issues/{fingerprint}")
def patch_issue(request: Request, fingerprint: str, body: IssuePatch) -> dict:
    _issue_or_404(request, fingerprint)
    sets = {"status": body.status, **body.model_dump(exclude_unset=True, exclude={"status"})}
    request.app.state.db.execute(f"UPDATE issues SET {', '.join(f'{c} = ?' for c in sets)} WHERE fingerprint = ?",
                                 [*sets.values(), fingerprint])
    return _issue_or_404(request, fingerprint)


ISSUE_COUNTS = "(SELECT count(*) FROM issues i WHERE i.active AND i.status = 'open' AND i.entity_ids LIKE '%\"' || p.person_id || '\"%')"


@router.get("/people")
def people(request: Request, q: str | None = None, facility: str | None = None, has_hr: bool | None = None) -> list[dict]:
    where, params = _where(("p.display_name ILIKE ?", f"%{q}%" if q else None), ("p.home_facility_id = ?", facility),
                           ("p.has_hr = ?", has_hr))
    return rows(request, f"SELECT p.*, {ISSUE_COUNTS} AS issue_count FROM persons p WHERE {where} "
                "ORDER BY p.display_name, p.person_id", params)


@router.get("/people/{person_id}")
def person(request: Request, person_id: str) -> dict:
    p = rows(request, f"SELECT p.*, {ISSUE_COUNTS} AS issue_count FROM persons p WHERE person_id = ?", [person_id])
    if not p:
        raise HTTPException(404, "unknown person")
    rec_ids = [r["record_id"] for r in rows(request, "SELECT record_id FROM person_records WHERE person_id = ?", [person_id])]
    rmarks = ",".join("?" * len(rec_ids)) or "NULL"
    creds = rows(request, "SELECT * FROM credentials WHERE holder_id = ?", [person_id])
    ids = [person_id] + [c["credential_id"] for c in creds]
    marks = ",".join("?" * len(ids))
    claims = rows(request, f"SELECT * FROM claims WHERE entity_id IN ({marks}) ORDER BY attribute, observed_at", ids)
    golden = rows(request, f"SELECT * FROM golden_values WHERE entity_id IN ({marks})", ids)
    for g in golden:
        g["claims"] = [c for c in claims if (c["entity_id"], c["attribute"]) == (g["entity_id"], g["attribute"])]
    as_of = request.app.state.settings.as_of
    for c in creds:
        c["days_left"] = (c["expires_on"] - as_of).days if c["expires_on"] else None
    names = _person_names(request)
    return {
        "person": p[0], "golden": golden,
        "links": rows(request, f"SELECT * FROM links WHERE a IN ({rmarks}) OR b IN ({rmarks})", rec_ids * 2),
        "credentials": creds,
        "shifts": rows(request, "SELECT s.shift_id, s.facility_id, s.role, s.work_date, v.token, s.hours, s.loc FROM shifts s "
                       "LEFT JOIN shifts_silver v USING (shift_id) WHERE s.person_id = ? ORDER BY s.work_date",
                       [person_id]),
        "issues": [_issue_summary(names, i) for i in repo.load_issues(request.app.state.db) if person_id in i.entity_ids],
    }


@router.get("/shifts")
def shifts(request: Request, start: date | None = None, end: date | None = None, facility: str | None = None) -> dict:
    where, params = _where(("s.work_date >= ?", start), ("s.work_date <= ?", end), ("s.facility_id = ?", facility))
    found = rows(request, "SELECT s.person_id, p.display_name, COALESCE(p.role, s.role) AS role, s.facility_id, "
                 "s.work_date, s.hours, v.token, EXISTS (SELECT 1 FROM credentials c WHERE c.holder_id = s.person_id "
                 "AND c.expires_on >= s.work_date) AS license_valid FROM shifts s "
                 "LEFT JOIN persons p USING (person_id) LEFT JOIN shifts_silver v USING (shift_id) "
                 f"WHERE {where} ORDER BY p.display_name, s.work_date", params)
    names = request.app.state.pipeline.pack.vocabs["facilities"].names
    facilities: dict[str, dict] = {}
    for s in found:
        fac = facilities.setdefault(s["facility_id"], {"facility_id": s["facility_id"],
                                                       "name": names.get(s["facility_id"], s["facility_id"]),
                                                       "rows": {}, "rn_coverage": {}})
        day = s["work_date"].isoformat()
        row = fac["rows"].setdefault(s["person_id"], {"person_id": s["person_id"], "display_name": s["display_name"],
                                                      "role": s["role"], "cells": {}})
        row["cells"][day] = {"token": s["token"], "hours": s["hours"], "license_valid": s["license_valid"]}
        if s["role"] == "RN":
            fac["rn_coverage"][day] = fac["rn_coverage"].get(day, 0) + (s["hours"] or 0)
    for fac in facilities.values():
        fac["rows"] = list(fac["rows"].values())
    return {"days": sorted({s["work_date"].isoformat() for s in found}), "facilities": list(facilities.values())}


@router.get("/credentials")
def credentials(request: Request, horizon_days: int = 90) -> list[dict]:
    as_of = request.app.state.settings.as_of
    found = rows(request, "SELECT * FROM credentials WHERE expires_on IS NOT NULL ORDER BY expires_on")
    for c in found:
        c["days_left"] = (c["expires_on"] - as_of).days
    return [c for c in found if c["days_left"] <= horizon_days]


@router.get("/contracts")
def contracts(request: Request) -> list[dict]:
    return rows(request, "SELECT * FROM contracts ORDER BY created_at")


@router.post("/contracts/{contract_id}/approve")
def approve(request: Request, contract_id: str) -> dict:
    if not rows(request, "SELECT 1 FROM contracts WHERE contract_id = ?", [contract_id]):
        raise HTTPException(404, "unknown contract")
    approve_contract(request.app.state.db, contract_id)
    return rows(request, "SELECT * FROM contracts WHERE contract_id = ?", [contract_id])[0]


@router.get("/exports/pbj.csv")
def pbj_csv(request: Request) -> Response:
    s = request.app.state
    return Response(build_pbj(s.db, s.pipeline.pack, s.settings).write_csv(), media_type="text/csv")


@router.get("/exports/issues.csv")
def issues_export(request: Request) -> Response:
    return Response(issues_csv(request.app.state.db), media_type="text/csv")


class SettingsPut(BaseModel):
    as_of: date


@router.get("/settings")
def get_settings(request: Request) -> dict:
    s = request.app.state.settings
    return {"as_of": s.as_of.isoformat(), "agents": s.agents, "pack": s.pack_name, "values": s.values}


@router.put("/settings")
async def put_settings(request: Request, body: SettingsPut) -> dict:
    settings = request.app.state.settings
    settings.as_of = body.as_of
    (settings.runtime / AS_OF_FILE).write_text(body.as_of.isoformat())
    latest = rows(request, "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1")
    if latest:  # checks need the drafts of the earlier stages (an issue absent from them is closed), so rebuild 5-7
        await asyncio.to_thread(request.app.state.pipeline.rebuild, latest[0]["run_id"])
    return get_settings(request)
