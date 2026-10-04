"""Check engine: loads pack checks, runs them, enriches evidence, merges into `issues` (IMPLEMENTATION §13).

A check is `checks/<ID>.sql` (YAML header in leading `--` comments: id, severity, title, action; then one SELECT
returning entity_ids, facility_id, period_start, period_end, message, evidence, key and optionally severity) or
`checks/<ID>.py` with `run(db, ctx) -> list[IssueDraft]`. `evidence` is a JSON object: the keys `records`,
`shifts` and `claims` hold ids that become cell / claim evidence with locators, the key `field` names the source
field the issue is about (CSV/XLSX evidence cells then carry that column), any other key becomes a note.
SQL checks may read the temp table `role_scope(role, license_type)` and the variables as_of, hours_tol_abs,
hours_tol_rel, expiry_high_days, expiry_medium_days.

Sources:
- https://duckdb.org/docs/stable/sql/statements/set_variable.html  (SET VARIABLE / getvariable)
- https://duckdb.org/docs/stable/sql/statements/create_table.html  (CREATE TEMP TABLE)
- https://duckdb.org/docs/stable/sql/functions/char.html#printfformat-parameters  (printf returns NULL when an argument is NULL)
- https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly  (loading .py checks)
- https://duckdb.org/docs/stable/sql/statements/insert.html#on-conflict-clause  (INSERT ... ON CONFLICT DO UPDATE, excluded.*)
"""
from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from sot.config import Settings
from sot.core.ids import issue_fingerprint
from sot.core.models import SEVERITY_ORDER, EvidenceItem, Issue, IssueDraft, Locator
from sot.core.pack import Pack
from sot.store import repo
from sot.store.db import DB
from sot.truth.claims import CLAIM_FIELDS


HEADER_LINE = re.compile(r"^-- (id|severity|title|action|Sources):")


@dataclass
class CheckContext:
    pack: Pack
    settings: Settings


def _set_variables(db: DB, pack: Pack, settings: Settings) -> None:
    variables = {"as_of": settings.as_of, "hours_tol_abs": settings["hours.tolerance_abs"],
                 "hours_tol_rel": settings["hours.tolerance_rel"], "expiry_high_days": settings["expiry.high_days"],
                 "expiry_medium_days": settings["expiry.medium_days"]}
    for name, value in variables.items():
        db.execute(f"SET VARIABLE {name} = ?", [value])
    db.execute("CREATE OR REPLACE TEMP TABLE role_scope (role VARCHAR, license_type VARCHAR)")
    db.insert("role_scope", [{"role": role, "license_type": t}
                             for role, types in pack.vocabs["roles"].scope.items() for t in types])


def _sql_check(db: DB, path: Path) -> list[IssueDraft]:
    """One draft per row: a row that cannot become a valid draft is skipped and reported once, the others survive."""
    text = path.read_text()
    meta = yaml.safe_load("\n".join(line[2:] for line in text.splitlines() if HEADER_LINE.match(line)))
    drafts, bad = [], []
    for row in db.query(text):
        entity_ids = [e for e in row["entity_ids"] or [] if e is not None]
        try:
            drafts.append(IssueDraft(
                check_id=meta["id"], severity=row.get("severity") or meta["severity"], title=meta["title"],
                message=row["message"] or f"{meta['title']}: {', '.join(entity_ids) or 'unknown entity'}",
                entity_ids=entity_ids, facility_id=row["facility_id"], period_start=row["period_start"],
                period_end=row["period_end"], key=str(row.get("key") or ""), evidence_refs=row["evidence"] or {},
                action=meta.get("action")))
        except ValueError as exc:
            bad.append(f"{entity_ids}: {exc}")
    if bad:
        drafts.append(IssueDraft(
            check_id="CHECK-ERROR", severity="HIGH", title="A check failed to run", key=path.stem,
            message=f"Check {path.stem} skipped {len(bad)} row(s) it could not report, e.g. {bad[0]}",
            entity_ids=[path.stem]))
    return drafts


def _py_check(db: DB, path: Path, ctx: CheckContext) -> list[IssueDraft]:
    spec = importlib.util.spec_from_file_location(f"pack_check_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run(db, ctx)


def _run_pack_checks(db: DB, ctx: CheckContext) -> list[IssueDraft]:
    drafts: list[IssueDraft] = []
    for path in sorted(ctx.pack.checks_dir.iterdir()):
        if path.suffix not in (".sql", ".py"):
            continue
        try:
            drafts += _sql_check(db, path) if path.suffix == ".sql" else _py_check(db, path, ctx)
        except Exception as exc:  # a broken check must not stop the run
            drafts.append(IssueDraft(
                check_id="CHECK-ERROR", severity="HIGH", title="A check failed to run", key=path.stem,
                message=f"Check {path.stem} raised {type(exc).__name__}: {exc}", entity_ids=[path.stem]))
    return drafts


# ---------- evidence enrichment ----------
def _columns(db: DB, record_ids: list[str]) -> dict[str, dict[str, str]]:
    """record id -> {field id: source column}, from the mapping of the record's table."""
    rows = db.query("SELECT r.record_id, m.matches FROM source_records r JOIN mappings m USING (table_id) "
                    "WHERE r.record_id IN (SELECT unnest(?::VARCHAR[]))", [record_ids])
    return {r["record_id"]: {m["field_id"]: m["column"] for m in r["matches"]} for r in rows}


def _cell(loc: Locator, raw: dict | None, column: str | None) -> tuple[Locator, dict | None]:
    """CSV/XLSX cells carry the source row and the column the issue is about; PDF cells carry page + bbox."""
    if loc.page is not None:
        return loc, None
    return loc.model_copy(update={"col": column}), raw


def _record_evidence(db: DB, ids: list[str], field: str | None) -> list[EvidenceItem]:
    columns = _columns(db, ids)
    items = []
    for r in db.query("SELECT record_id, loc, raw FROM source_records WHERE record_id IN (SELECT unnest(?::VARCHAR[]))", [ids]):
        raw = r["raw"]
        loc, shown = _cell(Locator(**r["loc"]), raw, columns.get(r["record_id"], {}).get(field))
        text = ", ".join(f"{k}={v}" for k, v in raw.items() if v)
        items.append(EvidenceItem(kind="cell", label=f"record {loc.file_name} row {loc.row}", text=text, loc=loc,
                                  raw=shown))
    return items


def _shift_evidence(db: DB, ids: list[str]) -> list[EvidenceItem]:
    items = []
    for r in db.query("SELECT s.loc, s.work_date, coalesce(v.token, '') AS token FROM shifts s LEFT JOIN shifts_silver v USING (shift_id) "
                      "WHERE s.shift_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY s.work_date", [ids]):
        loc = Locator(**r["loc"])
        items.append(EvidenceItem(kind="cell", label=f"shift {loc.file_name} page {loc.page} row {loc.row}",
                                  text=f"{r['work_date']} {r['token']}", loc=loc))
    return items


def _claim_evidence(db: DB, ids: list[str]) -> list[EvidenceItem]:
    golden_ids = {r["claim_id"] for r in db.query("SELECT claim_id FROM golden_values")}
    claims = db.query("SELECT c.*, r.raw FROM claims c LEFT JOIN source_records r USING (record_id) "
                      "WHERE c.claim_id IN (SELECT unnest(?::VARCHAR[]))", [ids])
    columns = _columns(db, [c["record_id"] for c in claims])
    items = []
    for c in claims:
        mapped = columns.get(c["record_id"], {})
        column = next((mapped[f] for f in CLAIM_FIELDS[c["attribute"]] if f in mapped), None)
        loc, raw = _cell(Locator(**c["loc"]), c["raw"], column)
        items.append(EvidenceItem(
            kind="claim", label=f"{c['template_id']} {loc.file_name} row {loc.row}", claim_id=c["claim_id"], loc=loc,
            text=f"{c['attribute']} = {c['value']}", is_golden=c["claim_id"] in golden_ids, raw=raw))
    return items


def _enrich(db: DB, draft: IssueDraft) -> list[EvidenceItem]:
    refs = draft.evidence_refs
    items = list(draft.evidence)
    items += _record_evidence(db, refs.get("records", []), refs.get("field"))
    items += _shift_evidence(db, refs.get("shifts", []))
    items += _claim_evidence(db, refs.get("claims", []))
    items += [EvidenceItem(kind="note", label=k, text=str(v)) for k, v in refs.items()
              if k not in ("records", "shifts", "claims", "field")]
    return items


# ---------- merge into the persistent issues table ----------
UPSERT = """
INSERT INTO issues (fingerprint, check_id, severity, title, message, entity_ids, facility_id, period_start, period_end,
                    evidence, action, first_seen_run, last_seen_run)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (fingerprint) DO UPDATE SET
  severity = excluded.severity, title = excluded.title, message = excluded.message, entity_ids = excluded.entity_ids,
  facility_id = excluded.facility_id, period_start = excluded.period_start, period_end = excluded.period_end,
  evidence = excluded.evidence, action = excluded.action, last_seen_run = excluded.last_seen_run, active = TRUE
"""


def _merge(db: DB, run_id: str, drafts: list[IssueDraft]) -> None:
    """Status, owner, note and first_seen_run survive: they are not in the DO UPDATE list."""
    seen: set[str] = set()
    for d in drafts:
        fp = issue_fingerprint(d.check_id, d.entity_ids, d.period_start, d.period_end, d.key)
        evidence = json.dumps([e.model_dump(mode="json") for e in _enrich(db, d)])
        db.execute(UPSERT, [fp, d.check_id, d.severity, d.title, d.message, json.dumps(d.entity_ids), d.facility_id,
                            d.period_start, d.period_end, evidence, d.action, run_id, run_id])
        seen.add(fp)
    db.execute("UPDATE issues SET active = FALSE WHERE fingerprint NOT IN (SELECT unnest(?::VARCHAR[]))",
               [sorted(seen)])


def run_checks(db: DB, pack: Pack, settings: Settings, run_id: str, extra_drafts: list[IssueDraft]) -> list[Issue]:
    _set_variables(db, pack, settings)
    drafts = [*extra_drafts, *_run_pack_checks(db, CheckContext(pack, settings))]
    _merge(db, run_id, drafts)
    return sorted(repo.load_issues(db), key=lambda i: (SEVERITY_ORDER[i.severity], i.check_id, i.fingerprint))
