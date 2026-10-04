"""Claims: one (entity, attribute, value) assertion per source cell (IMPLEMENTATION §12).

Person claims go to the person that owns the record. Credential claims go to the
normalized credential number, or "ORG:<slug>:<number or doc type>" for vendor paperwork.

Sources:
- https://en.wikipedia.org/wiki/Master_data_management  (claims/survivorship vocabulary)
- https://docs.pydantic.dev/latest/concepts/models/  (Claim model)
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, UTC

from sot.core.ids import short_hash
from sot.core.models import Claim, Person, SourceRecord

PERSON_ATTRS = {"role": "person.role", "home_facility": "person.facility", "phone": "person.phone",
                "hire_date": "person.hire_date"}
CREDENTIAL_ATTRS = {"expires_on": "credential.expires_on", "last_verified": "credential.last_verified",
                    "issued_on": "credential.issued_on", "credential_type": "credential.type",
                    "number": "credential.number"}
DATE_ATTRS = {"hire_date", "expires_on", "last_verified", "issued_on"}
# Source fields that can feed a claim attribute, in order: the evidence view uses them to name the source column.
CLAIM_FIELDS = {**{a: (f,) for a, f in {**PERSON_ATTRS, **CREDENTIAL_ATTRS}.items()},
                "display_name": ("person.full_name", "person.family_name"),
                "credential_type": ("credential.type", "credential.doc_type", "person.role"),
                "holder_name": ("org.name", "person.full_name", "person.family_name")}
NOT_A_HOME = {"schedule"}  # a schedule shows where someone works today, not their home facility


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _display(r: SourceRecord) -> str | None:
    if r.person_key:
        return r.person_key.display
    f = r.fields
    parts = [f.get("person.given_name"), f.get("person.family_name")]
    return f.get("person.full_name") or " ".join(p for p in parts if p) or None


def _credential_id(r: SourceRecord) -> str | None:
    f = r.fields
    if f.get("org.name"):
        return f"ORG:{_slug(f['org.name'])}:{f.get('credential.number') or f.get('credential.doc_type') or ''}"
    return f.get("credential.number")


def build_claims(records: list[SourceRecord], persons: list[Person],
                 file_times: Mapping[str, datetime] = {}) -> list[Claim]:
    """`file_times` maps file_id to files.received_at: a claim was observed when its file arrived."""
    person_of = {rid: p.person_id for p in persons for rid in p.record_ids}
    now = datetime.now(UTC)
    claims: dict[str, Claim] = {}  # by claim_id: one record can offer the same attribute from two fields

    def add(r: SourceRecord, etype: str, eid: str, attr: str, value) -> None:
        if value is None or value == "":
            return
        vtype = "date" if attr in DATE_ATTRS else "number" if isinstance(value, (int, float)) else "string"
        cid = "C-" + short_hash(eid, attr, r.record_id)
        claims[cid] = Claim(claim_id=cid, entity_type=etype, entity_id=eid, attribute=attr, value=value,
                            value_type=vtype, template_id=r.template_id, record_id=r.record_id, loc=r.loc,
                            observed_at=file_times.get(r.loc.file_id, now))

    for r in records:
        pid = person_of.get(r.record_id)
        if pid:
            add(r, "person", pid, "display_name", _display(r))
            for attr, fid in PERSON_ATTRS.items():
                if not (attr == "home_facility" and r.template_id in NOT_A_HOME):
                    add(r, "person", pid, attr, r.fields.get(fid))
        cid = _credential_id(r)
        if cid:
            for attr, fid in CREDENTIAL_ATTRS.items():
                add(r, "credential", cid, attr, r.fields.get(fid))
            # HR rosters carry no license type: the role is the license type in this domain
            add(r, "credential", cid, "credential_type",
                r.fields.get("person.role") if r.template_id == "hr_roster" else r.fields.get("credential.doc_type"))
            add(r, "credential", cid, "holder_name", r.fields.get("org.name") or _display(r))
    return list(claims.values())
