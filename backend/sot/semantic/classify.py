"""Pick the template a table belongs to and build its column -> field Mapping (§9.4).

For every template: assign its fields, then coverage = share of requirements met with S >= agent_min (a required
field, or the `one_of` alternatives, e.g. given+family name OR full name), quality = mean S over those,
confidence = coverage x quality x share of the table's columns explained. A template that explains 3 of 10 columns
therefore cannot claim the table, however well those 3 fit (real CMS/state/city files, an Excel calendar PDF).
A forced map (agent or contract) already states which columns matter, so the share is not applied to it.
Relations such as period_end >= period_start swap two columns when violated in more than half the rows.

Sources:
- https://arxiv.org/pdf/2010.07386 (Valentine: score aggregation across matchers)
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html
"""
from __future__ import annotations

from sot.config import Settings
from sot.core.models import ColumnProfile, FieldMatch, Mapping, RawTable
from sot.core.pack import Pack, TemplateSpec
from sot.normalize.dates import infer_column_date_format, parse_date
from sot.semantic.mapper import assign, field_match


def _requirements(tmpl: TemplateSpec) -> list[list[list[str]]]:
    """Each requirement is a list of alternatives; an alternative is the field list that must all be matched."""
    return [[[f]] for f in tmpl.required] + ([tmpl.one_of] if tmpl.one_of else [])


def _score(tmpl: TemplateSpec, matches: list[FieldMatch], min_s: float) -> tuple[float, float, list[str]]:
    """(coverage x quality, coverage, missing fields)."""
    best = {m.field_id: m.score for m in matches if m.score >= min_s}
    hit, missing = [], []
    for alts in _requirements(tmpl):
        mean = lambda alt: sum(best.get(f, 0.0) for f in alt) / len(alt)  # noqa: E731
        alt = max(alts, key=mean)
        if all(f in best for f in alt):
            hit.append(mean(alt))
        else:
            missing += [f for f in alt if f not in best]
    coverage = len(hit) / len(_requirements(tmpl))
    return coverage * (sum(hit) / len(hit) if hit else 0.0), coverage, missing


def _swap_violated_relations(t: RawTable, tmpl: TemplateSpec, matches: list[FieldMatch]) -> None:
    by_field = {m.field_id: m for m in matches}
    for rel in tmpl.relations:
        big, small = (by_field.get(f) for f in rel["gte"])
        if not (big and small):
            continue
        cols = []
        for m in (big, small):
            values = t.df[m.column].to_list()
            fmt, _ = infer_column_date_format([v for v in values if v])
            cols.append([parse_date(v, fmt) if v else None for v in values])
        pairs = [(a, b) for a, b in zip(*cols) if a and b]
        if pairs and sum(a < b for a, b in pairs) > len(pairs) / 2:
            big.field_id, small.field_id = small.field_id, big.field_id


def classify(t: RawTable, profiles: list[ColumnProfile], pack: Pack, settings: Settings,
             forced: dict[str, str] | None = None) -> Mapping:
    """Auto-classify, or (forced = column -> field from an agent/contract) score the given mapping."""
    agent_min, no_field = settings["map.agent_min"], settings["map.no_field_score"]
    by_col = {p.column: p for p in profiles}
    candidates = []
    for tmpl in pack.templates.values():
        if forced is None:
            matches = [m for m in assign(profiles, [pack.fields[f] for f in tmpl.fields], no_field)
                       if m.score >= agent_min]
        else:
            matches = [field_match(by_col[c], pack.fields[f]) for c, f in forced.items()
                       if f in tmpl.fields and c in by_col]
        quality, coverage, missing = _score(tmpl, matches, 0.0 if forced else agent_min)
        explained = 1.0 if forced else len({m.column for m in matches if m.score >= agent_min}) / len(t.header)
        candidates.append((quality * explained, coverage, tmpl, matches, missing))
    confidence, _, tmpl, matches, missing = max(candidates, key=lambda c: c[:2])
    if confidence < agent_min and forced is None:
        return Mapping(table_id=t.table_id, template_id=None, confidence=confidence, matches=[],
                       unmapped_columns=list(t.header), missing_required=[], source="auto")
    if forced is None:
        _swap_violated_relations(t, tmpl, matches)
    return Mapping(
        table_id=t.table_id, template_id=tmpl.id, confidence=confidence, matches=matches,
        unmapped_columns=[c for c in t.header if c not in {m.column for m in matches}],
        missing_required=missing,
        source="auto" if forced is None else "agent")
