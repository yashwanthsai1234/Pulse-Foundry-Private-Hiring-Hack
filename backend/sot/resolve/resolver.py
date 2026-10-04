"""Stage 5: who is who. Hard key links, blocking, scoring, zones, one-to-one guard, union-find (IMPLEMENTATION §11).

Sources:
- https://moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html (Fellegi-Sunter model, thresholds)
- https://en.wikipedia.org/wiki/Record_linkage (deterministic keys + probabilistic linkage)
- https://rapidfuzz.github.io/RapidFuzz/Usage/distance/JaroWinkler.html (name similarity)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from collections.abc import Callable, Iterable

from sot.config import Settings
from sot.core.models import IssueDraft, Link, Person, SourceRecord
from sot.core.pack import Pack
from sot.resolve.blocking import block, canonical_number, table_of
from sot.resolve.cluster import cluster
from sot.resolve.scoring import jaro_winkler, score_pair

KEY_WEIGHT = 20.0  # stands in for log2(m/u) of a deterministic key
MAIDEN_NAME_JW = 0.85


@dataclass
class ResolveResult:
    persons: list[Person]
    links: list[Link]
    drafts: list[IssueDraft]
    gray_pairs: list[Link] = field(default_factory=list)


def _key_links(records: list[SourceRecord], hard_keys: list[dict]) -> list[Link]:
    links = []
    for hk in hard_keys:
        buckets: dict[str, list[SourceRecord]] = defaultdict(list)
        for r in records:
            value = r.fields.get(hk["field"])
            if value and r.template_id in hk["templates"]:
                buckets[value].append(r)
        for value, group in buckets.items():
            for a, b in combinations(sorted(group, key=lambda r: r.record_id), 2):
                if a.template_id != b.template_id or table_of(a.record_id) != table_of(b.record_id):
                    links.append(Link(a=a.record_id, b=b.record_id, prob=1.0, weight=KEY_WEIGHT, method="key", reasons=[f"{hk['field']} equal ({value})"]))
    return links


def _prepare(r: SourceRecord) -> SourceRecord | None:
    """None for a record that names nobody and carries no id (a totals row); else the record with its licence number canonical."""
    key = r.person_key
    number = r.fields.get("credential.number")
    if not (key and (key.given or key.family or key.given_initial)) and not number and not r.fields.get("person.employee_id"):
        return None
    return r.model_copy(update={"fields": {**r.fields, "credential.number": canonical_number(number)}}) if number else r


def _compete(
    links: list[Link], is_subject: Callable[[str], bool], owner: Callable[[str], str | None], margin: float
) -> tuple[list[Link], dict[str, list[str]]]:
    """One-to-one guard. A subject record joins at most one owner (an HR person, or a group of full-name records).
    Keep the owner that leads by >= margin bits of weight, else drop all its links to owners and report it ambiguous."""
    cands: dict[str, dict[str, list[Link]]] = defaultdict(lambda: defaultdict(list))
    for x in links:
        for s, o in ((x.a, x.b), (x.b, x.a)):
            if is_subject(s) and owner(o) is not None:
                cands[s][owner(o)].append(x)
    dropped: set[int] = set()
    ambiguous: dict[str, list[str]] = {}
    for rid, per_owner in cands.items():
        if len(per_owner) < 2:
            continue
        ranked = sorted(per_owner.values(), key=lambda ls: -max(x.weight for x in ls))
        lead = max(x.weight for x in ranked[0]) - max(x.weight for x in ranked[1])
        dropped.update(id(x) for ls in (ranked if lead < margin else ranked[1:]) for x in ls)
        if lead < margin:
            ambiguous[rid] = sorted(x.b if x.a == rid else x.a for ls in ranked for x in ls)
    return [x for x in links if id(x) not in dropped], ambiguous


def _draft(check_id: str, severity: str, title: str, message: str, pids: Iterable[str], record_ids: list[str]) -> IssueDraft:
    return IssueDraft(check_id=check_id, severity=severity, title=title, message=message, entity_ids=sorted(set(pids)),
                      key="|".join(record_ids), evidence_refs={"record_ids": record_ids})


def resolve_all(records: list[SourceRecord], pack: Pack, settings: Settings, extra_links: Iterable[Link] = ()) -> ResolveResult:
    cfg = pack.resolution
    people = [r for r in map(_prepare, records) if r and not (r.template_id in pack.templates and pack.templates[r.template_id].holder == "organization")]
    by_id = {r.record_id: r for r in people}
    anchor = cfg["anchor_template"]

    keyed = _key_links(people, cfg["hard_keys"])
    seen = {(x.a, x.b) for x in keyed}
    scored = [score_pair(by_id[a], by_id[b], cfg["weights"], cfg.get("prior", settings["link.prior"]))
              for a, b in sorted(block(people, cfg["blocking"]) - seen)]
    auto = [x for x in scored if x.prob >= settings["link.auto"]]
    gray = [x for x in scored if settings["link.gray"] <= x.prob < settings["link.auto"]]
    margin = cfg.get("one_to_one_margin_bits", 2.0)

    def hr_person(rid: str) -> str | None:
        return (by_id[rid].fields.get("person.employee_id") or rid) if by_id[rid].template_id == anchor else None

    machine, ambiguous = _compete(keyed + auto, lambda r: by_id[r].template_id != anchor, hr_person, margin)

    def initial_only(rid: str) -> bool:  # "M. Bell": too little evidence to link to other initial-only records
        return bool(by_id[rid].person_key) and not by_id[rid].person_key.given

    machine = [x for x in machine if not (initial_only(x.a) and initial_only(x.b))]
    solid = [x for x in machine if not (initial_only(x.a) or initial_only(x.b))]
    groups = cluster([r for r in people if not initial_only(r.record_id)], solid, cfg["cannot_link"], anchor)[0]
    group_of = {rid: p.person_id for p in groups for rid in p.record_ids}
    machine, ambiguous_initial = _compete(machine, initial_only, group_of.get, margin)
    ambiguous |= ambiguous_initial
    extra = [x for x in extra_links if x.a in by_id and x.b in by_id]

    persons, links, refused = cluster(people, machine + extra, cfg["cannot_link"], anchor)
    pid = {rid: p.person_id for p in persons for rid in p.record_ids}

    drafts = []
    for x in keyed:
        fa, fb = by_id[x.a].person_key and by_id[x.a].person_key.family, by_id[x.b].person_key and by_id[x.b].person_key.family
        if fa and fb and jaro_winkler(fa, fb) < MAIDEN_NAME_JW:
            drafts.append(_draft("ID-NAME-DIFFERS-ON-LICENSE", "INFO", "Name differs from licence holder",
                                 f"Linked by credential number but the family names differ ('{fa}' vs '{fb}'): maiden or married name?",
                                 [pid[x.a], pid[x.b]], [x.a, x.b]))
    conflicts = {(frozenset((pid[a], pid[b])), rule): (a, b) for a, b, rule in refused}  # one issue per person pair and rule
    for (_, rule), (a, b) in conflicts.items():
        drafts.append(_draft("ID-CONFLICT", "HIGH", "Records refused a merge", f"Linking {a} and {b} would break the rule '{rule}'.", [pid[a], pid[b]], [a, b]))
    for rid, candidates in ambiguous.items():
        drafts.append(_draft("ID-AMBIGUOUS", "MEDIUM", "Record matches several HR people equally",
                             f"{rid} fits {len(candidates)} HR records about equally; it was not linked.", [pid[c] for c in candidates] + [pid[rid]], [rid, *candidates]))
    gray = [x for x in gray if pid[x.a] != pid[x.b]]
    for x in gray:
        drafts.append(_draft("ID-GRAY-PAIR", "INFO", "Possible match needs review", f"{x.a} and {x.b} look alike (p={x.prob:.2f}): " + "; ".join(x.reasons), [pid[x.a], pid[x.b]], [x.a, x.b]))
    return ResolveResult(persons=persons, links=links, drafts=drafts, gray_pairs=gray)
