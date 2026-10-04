"""Deterministic validators for agent output (IMPLEMENTATION §15.4). An agent proposes, these decide.

Sources:
- docs/IMPLEMENTATION.md §15.4 (validator rules per task kind)
- https://python-jsonschema.readthedocs.io/en/stable/validate/ (schema check happens in the gateway)
"""
from __future__ import annotations

from dataclasses import dataclass

from sot.config import Settings
from sot.core.models import AgentTask, ColumnProfile, Mapping, PersonKey, RawTable
from sot.core.pack import Pack
from sot.normalize.dates import parse_date
from sot.normalize.names import compare_given, parse_person_name
from sot.normalize.shifts import parse_shift_token
from sot.semantic.classify import classify
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators
from sot.store import repo
from sot.store.db import DB

MIN_HITS = 0.8


@dataclass
class ValidationContext:
    """What validators may look at: the database, the pack, settings and the table profiles."""

    db: DB
    pack: Pack
    settings: Settings

    def table(self, table_id: str) -> RawTable:
        return repo.load_raw_table(self.db, table_id)

    def profiles(self, table_id: str) -> list[ColumnProfile]:
        return profile_table(self.table(table_id), build_validators(self.pack))

    def classify(self, table_id: str, forced: dict[str, str]) -> Mapping:
        return classify(self.table(table_id), self.profiles(table_id), self.pack, self.settings, forced)

    def person_keys(self) -> list[PersonKey]:
        return [r.person_key for r in repo.load_records(self.db) if r.template_id == "hr_roster" and r.person_key]

    def record_fields(self, record_id: str) -> dict:
        rows = self.db.query("SELECT fields FROM source_records WHERE record_id = ?", [record_id])
        return rows[0]["fields"] if rows else {}


def _order_ok(lo, hi) -> bool | None:
    """True/False if both values are comparable dates or numbers, else None."""
    for conv in (parse_date, float):
        try:
            a, b = conv(lo), conv(hi)
        except (TypeError, ValueError):
            continue
        if a is not None and b is not None:
            return b >= a
    return None


def _validate_mapping(task: AgentTask, out: dict, ctx: ValidationContext) -> list[str]:
    notes: list[str] = []
    tpl = ctx.pack.templates.get(out["template_id"] or "")
    if tpl is None:
        return [f"unknown template_id {out['template_id']!r}"]
    t = ctx.table(task.ref)
    profiles = {p.column: p for p in ctx.profiles(task.ref)}
    mapped = {c: f for c, f in out["column_map"].items() if f}
    for col, field in mapped.items():
        if col not in profiles:
            notes.append(f"column {col!r} is not in the table")
        elif field not in tpl.fields:
            notes.append(f"field {field!r} is not in template {tpl.id}")
        elif profiles[col].validator_hits.get(field, 1.0) < MIN_HITS:
            notes.append(f"column {col!r} passes the {field} validator for only "
                         f"{profiles[col].validator_hits[field]:.0%} of values (need {MIN_HITS:.0%})")
    used = list(mapped.values())
    notes += [f"field {f!r} used more than once" for f in set(used)
              if used.count(f) > 1 and not ctx.pack.fields[f].repeatable]
    notes += [f"required field {f!r} is not mapped" for f in tpl.required if f not in used]
    col_of = {f: c for c, f in mapped.items()}
    for rel in tpl.relations:
        lo, hi = rel["gte"][1], rel["gte"][0]
        if lo in col_of and hi in col_of:
            oks = [_order_ok(a, b) for a, b in zip(t.df[col_of[lo]], t.df[col_of[hi]])]
            known = [o for o in oks if o is not None]
            if known and sum(known) / len(known) < 0.95:
                notes.append(f"relation {hi} >= {lo} holds in only {sum(known) / len(known):.0%} of rows")
    if notes:
        return notes
    m = ctx.classify(task.ref, mapped)
    if m.template_id != tpl.id or m.confidence < ctx.settings["map.agent_min"]:
        notes.append(f"re-classification with this map gives {m.template_id} at {m.confidence:.2f}, "
                     f"need {tpl.id} >= {ctx.settings['map.agent_min']}")
    return notes


def _validate_page(task: AgentTask, out: dict, ctx: ValidationContext) -> list[str]:
    notes: list[str] = []
    width = len(out["header"])
    if any(len(r) != width for r in out["rows"]):
        notes.append(f"rows do not all have the header width {width}")
    cells = [c for r in out["rows"] for c in r[2:] if c]
    if cells:
        share = sum(parse_shift_token(c) is not None for c in cells) / len(cells)
        if share < 0.9:
            notes.append(f"only {share:.0%} of day cells are shift tokens (need 90%)")
    known = ctx.person_keys()
    names = [r[0] for r in out["rows"] if r and r[0]]
    if known and names:
        def hit(name: str) -> bool:
            k = parse_person_name(name, ctx.pack.nicknames)
            return any(k.family and k.family == p.family
                       and compare_given(k, p) in ("exact", "nickname", "fuzzy", "initial") for p in known)

        share = sum(hit(n) for n in names) / len(names)
        if share < 0.5:
            notes.append(f"only {share:.0%} of names match a known person (need 50%)")
    return notes


def _validate_adjudication(task: AgentTask, out: dict, ctx: ValidationContext) -> list[str]:
    if out["decision"] != "same":
        return []
    a, b = (ctx.record_fields(r) for r in task.ref.split("|"))
    ids = {x.get("person.employee_id") for x in (a, b)}
    notes = ["cannot-link: different employee ids"] if None not in ids and len(ids) == 2 else []
    if all(x.get("credential.number") for x in (a, b)) and a.get("credential.type") == b.get("credential.type") \
            and a["credential.number"] != b["credential.number"]:
        notes.append("cannot-link: different license numbers of the same type")
    return notes


def validate(task: AgentTask, output: dict, ctx: ValidationContext) -> tuple[bool, list[str]]:
    check = {"schema_mapper": _validate_mapping, "new_source_modeler": _validate_mapping,
             "page_reader": _validate_page, "identity_adjudicator": _validate_adjudication}[task.kind]
    notes = check(task, output, ctx)
    return not notes, notes
