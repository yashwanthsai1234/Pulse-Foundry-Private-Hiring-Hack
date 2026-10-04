"""Union-find clustering with cannot-link rules.

Sources:
- https://en.wikipedia.org/wiki/Disjoint-set_data_structure (path compression, union by size)
- https://moj-analytical-services.github.io/splink/topic_guides/evaluation/clusters/overview.html (clustering pairwise links into entities)
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha1
from typing import Any

from sot.core.models import Link, Person, SourceRecord

Facts = dict[tuple[int, Any], set[str]]  # (rule index, bucket) -> values seen in the group


def _facts(r: SourceRecord, rules: list[dict[str, Any]]) -> Facts:
    out: Facts = {}
    for i, rule in enumerate(rules):
        if "distinct_name_part" in rule:
            val, bucket = r.person_key and getattr(r.person_key, rule["distinct_name_part"]), None
        elif "distinct" in rule:
            val, bucket = r.fields.get(rule["distinct"]), None
        else:
            num_field, type_field = rule["distinct_per_type"]
            val, bucket = r.fields.get(num_field), r.fields.get(type_field)
            if bucket is None:
                continue
        if val:
            out[(i, bucket)] = {str(val)}
    return out


def _violation(a: Facts, b: Facts, rules: list[dict[str, Any]]) -> str | None:
    for (i, bucket), vals in a.items():
        if (i, bucket) in b and len(vals | b[(i, bucket)]) > 1:
            rule = rules[i]
            return f"distinct {rule.get('distinct') or rule.get('distinct_name_part') or rule['distinct_per_type'][0]}" + (f" for type {bucket}" if bucket else "")
    return None


def cluster(
    records: list[SourceRecord], links: list[Link], rules: list[dict[str, Any]], anchor_template: str
) -> tuple[list[Person], list[Link], list[tuple[str, str, str]]]:
    """Merge records along `links` (highest prob first) unless a cannot-link rule fires.
    Returns (persons, links applied, refused (record_a, record_b, rule) triples)."""
    parent = {r.record_id: r.record_id for r in records}
    size = dict.fromkeys(parent, 1)
    facts = {r.record_id: _facts(r, rules) for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    applied, refused = [], []
    for link in sorted(links, key=lambda x: (-x.prob, x.a, x.b)):
        ra, rb = find(link.a), find(link.b)
        if ra == rb:
            applied.append(link)
            continue
        broken = _violation(facts[ra], facts[rb], rules)
        if broken:
            refused.append((link.a, link.b, broken))
            continue
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]
        for k, v in facts.pop(rb).items():
            facts[ra].setdefault(k, set()).update(v)
        applied.append(link)

    groups: dict[str, list[SourceRecord]] = defaultdict(list)
    for r in records:
        groups[find(r.record_id)].append(r)
    persons = []
    for members in groups.values():
        ids = sorted(r.record_id for r in members)
        emp = next((r.fields["person.employee_id"] for r in members if r.template_id == anchor_template and r.fields.get("person.employee_id")), None)
        pid = f"P-{emp}" if emp else "P-X" + sha1("|".join(ids).encode()).hexdigest()[:8]
        persons.append(Person(person_id=pid, record_ids=ids, employee_id=emp, has_hr=any(r.template_id == anchor_template for r in members)))
    return sorted(persons, key=lambda p: p.person_id), applied, refused
