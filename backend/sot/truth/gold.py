"""Gold tables: rebuilt from scratch on every run (IMPLEMENTATION §12, schema.sql).

Gold never raises on a data problem. Persons that share an id are merged; a shift or pay period that arrives
twice (same person and time, e.g. a re-saved export) is stored once, from the newest file (files.received_at);
a payroll row without a person or period dates supports no gold fact and is skipped (silver reports it as
ROW-INCOMPLETE, the PAY-* checks read the duplicates from source_records).

Sources:
- https://duckdb.org/docs/stable/sql/statements/insert.html  (INSERT semantics)
- https://en.wikipedia.org/wiki/Master_data_management  (golden record)
- https://en.wikipedia.org/wiki/Data_deduplication  (keep one copy of identical data)
- https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts  (stable two-pass sort: newest first, then id)
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from sot.core.models import Claim, GoldenValue, Link, Person, ShiftRecord, SourceRecord
from sot.store.db import DB

def _newest_per_key[T](items: Iterable[T], key: Callable[[T], object], file_id: Callable[[T], str],
                      record_id: Callable[[T], str], received: dict[str, datetime]) -> list[T]:
    """One item per key: the one from the newest file, then the lowest record id (deterministic)."""
    ordered = sorted(items, key=record_id)
    ordered.sort(key=lambda x: received.get(file_id(x), datetime.min), reverse=True)
    winners: dict[object, T] = {}
    for x in ordered:
        winners.setdefault(key(x), x)
    return list(winners.values())


def _shift_times(s: ShiftRecord) -> tuple[datetime | None, datetime | None]:
    if s.start is None or s.end is None:
        return None, None
    start, end = datetime.combine(s.work_date, s.start), datetime.combine(s.work_date, s.end)
    return start, end + timedelta(days=1) if end <= start else end


def _credential_rows(golden: dict, claims: list[Claim], person_of: dict[str, str]) -> list[dict]:
    holders: dict[str, set[str]] = {}
    for c in claims:
        if c.entity_type == "credential" and c.record_id in person_of:
            holders.setdefault(c.entity_id, set()).add(person_of[c.record_id])
    rows = []
    by_credential: dict[str, dict] = {}
    for (entity_type, entity_id, attr), value in golden.items():
        if entity_type == "credential":
            by_credential.setdefault(entity_id, {})[attr] = value
    for cid, attrs in sorted(by_credential.items()):
        g = attrs.get
        org = cid.startswith("ORG:")
        number = cid if not org else g("number")
        holder = cid if org else min(holders.get(cid, {None}), key=str)
        rows.append({"credential_id": cid, "holder_type": "organization" if org else "person", "holder_id": holder,
                     "holder_name": g("holder_name"), "credential_type": g("credential_type"), "number": number,
                     "issued_on": g("issued_on"), "expires_on": g("expires_on"), "last_verified": g("last_verified")})
    return rows


def _merge_persons(persons: list[Person]) -> list[Person]:
    """Two persons with one id (e.g. two rows of one employee in a single HR file) become one."""
    merged: dict[str, Person] = {}
    for p in persons:
        have = merged.setdefault(p.person_id, p.model_copy(update={"record_ids": []}))
        have.record_ids = list(dict.fromkeys([*have.record_ids, *p.record_ids]))
        have.has_hr = have.has_hr or p.has_hr
    return list(merged.values())


def _pay_rows(records: list[SourceRecord], person_of: dict[str, str], received: dict[str, datetime]) -> list[dict]:
    complete = [r for r in records if r.template_id == "payroll" and r.record_id in person_of
                and r.fields.get("pay.period_start") and r.fields.get("pay.period_end")]

    def f(r: SourceRecord, name: str):
        return r.fields.get(name)

    rows, used = [], set()
    for r in _newest_per_key(
            complete, lambda r: (person_of[r.record_id], f(r, "person.facility"), f(r, "pay.period_start"),
                                 f(r, "pay.period_end")), lambda r: r.loc.file_id, lambda r: r.record_id, received):
        pay_id = f(r, "pay.payroll_id")
        pay_id = r.record_id if not pay_id or pay_id in used else pay_id
        used.add(pay_id)
        rows.append({"pay_id": pay_id, "person_id": person_of[r.record_id], "facility_id": f(r, "person.facility"),
                     "role": f(r, "person.role"), "period_start": f(r, "pay.period_start"),
                     "period_end": f(r, "pay.period_end"), "hours_paid": f(r, "pay.hours_paid"),
                     "record_id": r.record_id})
    return rows


def write_gold(db: DB, records: list[SourceRecord], shifts: list[ShiftRecord], persons: list[Person],
               links: list[Link], claims: list[Claim], golden: list[GoldenValue]) -> None:
    db.clear_gold()
    persons = _merge_persons(persons)
    received = {r["file_id"]: r["received_at"] for r in db.query("SELECT file_id, received_at FROM files")}
    gv = {(g.entity_type, g.entity_id, g.attribute): g.value for g in golden}
    person_of = {rid: p.person_id for p in persons for rid in p.record_ids}
    template_of = {r.record_id: r.template_id for r in records}
    best_prob: dict[str, float] = {}
    for link in links:
        for rid in (link.a, link.b):
            best_prob[rid] = max(best_prob.get(rid, 0.0), link.prob)

    db.insert("links", [link.model_dump() for link in links])
    db.insert("persons", [{
        "person_id": p.person_id, "employee_id": p.employee_id, "has_hr": p.has_hr,
        "display_name": gv.get(("person", p.person_id, "display_name")), "role": gv.get(("person", p.person_id, "role")),
        "home_facility_id": gv.get(("person", p.person_id, "home_facility")),
        "phone": gv.get(("person", p.person_id, "phone")), "hire_date": gv.get(("person", p.person_id, "hire_date")),
    } for p in persons])
    db.insert("person_records", [{
        "person_id": p.person_id, "record_id": rid, "template_id": template_of.get(rid),
        "link_prob": best_prob.get(rid, 1.0)} for p in persons for rid in p.record_ids])
    db.insert("credentials", _credential_rows(gv, claims, person_of))
    def same_shift(s: ShiftRecord):  # a shift with no times or no person cannot be matched to another one
        if s.start is None or s.record_id not in person_of:
            return s.shift_id
        return person_of[s.record_id], s.facility_id, s.work_date, s.start, s.end  # two facilities = double booking

    shift_rows = []
    for s in _newest_per_key(shifts, same_shift, lambda s: s.loc.file_id, lambda s: s.shift_id, received):
        start_ts, end_ts = _shift_times(s)
        shift_rows.append({"shift_id": s.shift_id, "person_id": person_of.get(s.record_id),
                           "facility_id": s.facility_id, "role": s.role, "work_date": s.work_date,
                           "start_ts": start_ts, "end_ts": end_ts, "hours": s.hours, "record_id": s.record_id,
                           "loc": s.loc})
    db.insert("shifts", shift_rows)
    db.insert("pay_periods", _pay_rows(records, person_of, received))
    db.insert("claims", [{**c.model_dump(exclude={"value"}), "value": json.dumps(c.value)}
                         for c in claims])
    db.insert("golden_values", [{**g.model_dump(exclude={"value"}), "value": json.dumps(g.value)}
                                for g in golden])
