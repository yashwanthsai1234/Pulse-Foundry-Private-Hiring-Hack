"""Survivorship: pick the golden claim per (entity, attribute) by source priority, then newest (IMPLEMENTATION §12).

Ties are broken by file name, then source row, then record id: nothing in the order depends on content hashes,
so re-delimiting or re-saving a file cannot flip a golden value.

A conflict is a claim whose normalized value differs from the golden one. Conflicts on attributes marked
`conflict_check: true` in survivorship.yaml become SRC-CONFLICT drafts.

Sources:
- https://en.wikipedia.org/wiki/Master_data_management  (survivorship rules: source priority, recency)
- https://www.informatica.com/resources/articles/what-is-master-data-management.html  (trust/priority-based survivorship)
- https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts  (a total, deterministic sort key)
"""
from __future__ import annotations

from collections import defaultdict

from sot.core.models import Claim, GoldenValue, IssueDraft
from sot.core.pack import Pack


def _norm(value):
    return value.strip().casefold() if isinstance(value, str) else value


def _priority(pack: Pack, entity_type: str, attribute: str) -> tuple[list[str], bool]:
    spec = pack.survivorship.get(entity_type, {}).get(attribute) or []
    if isinstance(spec, dict):
        return spec.get("priority", []), bool(spec.get("conflict_check"))
    return spec, False


def _conflict_draft(entity_id: str, attribute: str, golden: Claim, others: list[Claim], holders: list[str]) -> IssueDraft:
    said = "; ".join(f"{c.template_id} says {c.value}" for c in [golden, *others])
    return IssueDraft(
        check_id="SRC-CONFLICT", severity="MEDIUM", title=f"Sources disagree on {attribute}",
        message=f"{entity_id} {attribute}: {said}. Golden value: {golden.value} (from {golden.template_id}).",
        entity_ids=[entity_id, *holders], key=attribute,
        evidence_refs={"claims": [golden.claim_id, *(c.claim_id for c in others)]},
        action="Confirm the correct value with the primary source and correct the other system.")


def survive(claims: list[Claim], pack: Pack) -> tuple[list[GoldenValue], list[IssueDraft]]:
    person_of = {c.record_id: c.entity_id for c in claims if c.entity_type == "person"}  # issues join to people by id
    groups: dict[tuple[str, str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        groups[(c.entity_type, c.entity_id, c.attribute)].append(c)
    golden: list[GoldenValue] = []
    drafts: list[IssueDraft] = []
    for (etype, eid, attr), group in sorted(groups.items()):
        priority, check = _priority(pack, etype, attr)
        rank = {t: i for i, t in enumerate(priority)}
        ordered = sorted(group, key=lambda c: (rank.get(c.template_id, len(rank)), -c.observed_at.timestamp(),
                                               c.loc.file_name, c.loc.row or 0, c.record_id))
        top, others = ordered[0], [c for c in ordered[1:] if _norm(c.value) != _norm(ordered[0].value)]
        rule = "priority:" + ">".join(priority) if priority else "latest_observed"
        golden.append(GoldenValue(entity_type=etype, entity_id=eid, attribute=attr, value=top.value,
                                  claim_id=top.claim_id, rule=rule, conflict=bool(others),
                                  conflicting_claim_ids=[c.claim_id for c in others]))
        if others and check:
            holders = sorted({person_of[c.record_id] for c in group if etype == "credential" and c.record_id in person_of})
            drafts.append(_conflict_draft(eid, attr, top, others, holders))
    return golden, drafts
