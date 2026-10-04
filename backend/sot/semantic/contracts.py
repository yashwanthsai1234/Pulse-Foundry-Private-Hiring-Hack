"""Mapping contracts: remember an approved/auto column map per header fingerprint and detect drift (§9.5).

Lookup: same fingerprint -> re-score the stored map on the new values (a column whose field has a real validator and
value_score < 0.5 is drift) -> else classify. A contract for the same template under another fingerprint is drift
(version+1) only when the headers mostly overlap (Jaccard >= DRIFT_OVERLAP: the same source with columns renamed,
added or dropped); a header sharing almost nothing is a second, legitimate source of that template.
Contracts live in the DuckDB `contracts` table and are mirrored as YAML for review.

Sources:
- https://docs.python.org/3/library/hashlib.html (sha1 fingerprint)
- https://pyyaml.org/wiki/PyYAMLDocumentation (safe_dump)
- https://datacontract.com/ (data-contract idea: a versioned, reviewable agreement per source)
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

import yaml

from sot.config import Settings
from sot.core.models import Contract, Mapping, RawTable
from sot.core.pack import Pack
from sot.normalize.vocab import clean
from sot.semantic.classify import classify
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators
from sot.store.db import DB


DRIFT_OVERLAP = 0.5


def _norm(col: str) -> str:
    """Cleaned words with digits collapsed, so 'Mon 09/14' and 'Mon 09/21' are the same column."""
    return re.sub(r"\d+", "0", clean(col))


def header_fingerprint(header: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(_norm(h) for h in header)).encode()).hexdigest()


def save_contract(db: DB, m: Mapping, t: RawTable, source: str, export_dir: Path | None = None) -> Contract:
    """Store `m` as the next version for its template; optionally mirror it as YAML into export_dir."""
    fp = header_fingerprint(t.header)
    version = db.query("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM contracts WHERE template_id = ?", [m.template_id])[0]["v"]
    c = Contract(contract_id=f"{m.template_id}:v{version}:{fp[:8]}", template_id=m.template_id, header_fingerprint=fp,
                 version=version, column_map={x.column: x.field_id for x in m.matches}, source=source,
                 approved=False, created_at=datetime.now())
    db.insert("contracts", [c.model_dump()], replace=True)
    if export_dir:
        data = c.model_dump(mode="json", exclude={"approved"})
        (export_dir / f"{c.contract_id}.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return c


def approve_contract(db: DB, contract_id: str) -> None:
    db.execute("UPDATE contracts SET approved = TRUE WHERE contract_id = ?", [contract_id])


def _is_changed_source(db: DB, template_id: str, header: list[str]) -> bool:
    new = {_norm(h) for h in header}
    for row in db.query("SELECT * FROM contracts WHERE template_id = ?", [template_id]):
        old = {_norm(c) for c in Contract(**row).column_map}
        if len(old & new) / len(old | new) >= DRIFT_OVERLAP:
            return True
    return False


def map_table(t: RawTable, db: DB, pack: Pack, settings: Settings) -> Mapping:
    profiles = profile_table(t, build_validators(pack))
    fp = header_fingerprint(t.header)
    known = db.query("SELECT * FROM contracts WHERE header_fingerprint = ? ORDER BY version DESC LIMIT 1", [fp])
    drift = False
    if known:
        c = Contract(**known[0])
        by_norm = {_norm(col): f for col, f in c.column_map.items()}
        m = classify(t, profiles, pack, settings, forced={col: by_norm[_norm(col)] for col in t.header if _norm(col) in by_norm})
        checked = [x for x in m.matches if pack.fields[x.field_id].validator not in (None, {"non_empty": True})]
        if m.template_id == c.template_id and all(x.value_score >= 0.5 for x in checked):
            return m.model_copy(update={"source": "contract", "contract_id": c.contract_id})
        drift = True
    m = classify(t, profiles, pack, settings)
    if m.template_id is None:
        return m.model_copy(update={"drift": drift})
    drift = drift or _is_changed_source(db, m.template_id, t.header)
    if m.confidence >= settings["map.auto_min"]:
        c = save_contract(db, m, t, "auto", settings.dir("contracts"))
        return m.model_copy(update={"drift": drift, "contract_id": c.contract_id})
    return m.model_copy(update={"drift": drift})
