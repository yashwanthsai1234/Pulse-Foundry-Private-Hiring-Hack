"""Built-in drafts that need no SQL: PARSE-*, LEGEND-MISMATCH, ROW-INCOMPLETE and ID-FUZZY-LINK (IMPLEMENTATION §13.2).

`SourceRecord.parse_issues` entries look like "kind:detail" (e.g. "date_ambiguous:person.hire_date"); KINDS is the
contract with silver (docs/TASKGRAPH.md §6). A bad expiry date is HIGH: an expiry nobody can read is never tracked.
LEGEND-MISMATCH is one issue per file and token (a wrong footnote affects every cell that uses the token).
ID-FUZZY-LINK is one issue per source record linked to the person's HR record by a nickname, fuzzy or initial match
(for a person without an HR record, a link between two records flags both).

Sources:
- https://www.cms.gov/files/document/pbj-policy-manual-v2-8-august-2026.pdf  (why bad dates and tokens matter)
- https://en.wikipedia.org/wiki/Record_linkage  (fuzzy / nickname links are probabilistic: show the reasons)
- https://docs.python.org/3/library/re.html  (stripping the score weights from link reasons)
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from sot.core.models import EvidenceItem, IssueDraft, Link, Person, SourceRecord

KINDS = {  # silver kind -> (check id, severity)
    "bad_date": ("PARSE-DATE", "MEDIUM"), "date_ambiguous": ("PARSE-DATE-AMBIGUOUS", "MEDIUM"),
    "bad_number": ("PARSE-NUMBER", "MEDIUM"), "unknown_vocab": ("PARSE-UNKNOWN-VALUE", "MEDIUM"),
    "vocab_fuzzy": ("PARSE-FUZZY-VALUE", "INFO"), "bad_phone": ("PARSE-PHONE", "LOW"),
    "shift_token": ("PARSE-SHIFT-TOKEN", "MEDIUM"), "row_incomplete": ("ROW-INCOMPLETE", "MEDIUM"),
    "schedule_dates": ("PARSE-SCHEDULE-DATES", "HIGH"), "day_mismatch": ("PARSE-DATE-WEEKDAY", "MEDIUM")}
FIELD_DETAIL = {"bad_date", "date_ambiguous", "bad_number", "unknown_vocab", "vocab_fuzzy", "bad_phone"}
FUZZY_WORDS = ("nickname", "fuzzy", "initial")
WEIGHT = re.compile(r"\s*\([+-]?[\d.]+\)")


def _where(r: SourceRecord) -> str:
    return f"{r.loc.file_name} p.{r.loc.page}" if r.loc.page else f"{r.loc.file_name} row {r.loc.row}"


def _parse_draft(r: SourceRecord, issue: str) -> IssueDraft:
    kind, _, detail = issue.partition(":")
    check_id, severity = KINDS.get(kind, ("PARSE-" + kind.upper().replace("_", "-"), "LOW"))
    if detail == "credential.expires_on":
        severity = "HIGH"
    refs = {"records": [r.record_id], **({"field": detail} if kind in FIELD_DETAIL else {})}
    return IssueDraft(
        check_id=check_id, severity=severity, title=f"Parse problem: {kind.replace('_', ' ')}",
        message=f"{kind.replace('_', ' ')} ({detail}) in {_where(r)}.", entity_ids=[r.record_id], key=issue,
        evidence_refs=refs, action="Open the source cell and confirm how it should be read.")


def _legend_drafts(records: list[SourceRecord]) -> list[IssueDraft]:
    cells: dict[tuple[str, str], list[SourceRecord]] = defaultdict(list)
    for r in records:
        for issue in r.parse_issues:
            kind, _, token = issue.partition(":")
            if kind == "legend_mismatch":
                cells[(r.loc.file_name, token)].append(r)
    return [IssueDraft(
        check_id="LEGEND-MISMATCH", severity="MEDIUM", title="Legend hours differ from the shift duration",
        message=f"Shift token '{token}' has legend hours different from its computed duration "
                f"in {len(rs)} schedule row(s) of {file_name}.",
        entity_ids=[file_name], key=token, evidence_refs={"records": [r.record_id for r in rs]},
        action="Check the legend on the schedule page and the shift times.") for (file_name, token), rs in cells.items()]


def _suspect(by_id: dict[str, SourceRecord], anchor_of: dict[str, SourceRecord], person_of: dict[str, str],
             rid: str, other: str) -> bool:
    """HR is the anchor of a person: a record is suspect through its link to the HR record. Only for a person
    without HR is a link between two other records worth a flag."""
    if by_id[rid].template_id == "hr_roster":
        return False
    linked_to_hr = other in by_id and by_id[other].template_id == "hr_roster"
    return linked_to_hr or person_of.get(rid) not in anchor_of


def _fuzzy_drafts(records: list[SourceRecord], links: list[Link], persons: Sequence[Person]) -> list[IssueDraft]:
    by_id = {r.record_id: r for r in records}
    person_of = {rid: p.person_id for p in persons for rid in p.record_ids}
    anchor_of = {person_of[r.record_id]: r for r in records if r.template_id == "hr_roster" and r.record_id in person_of}
    found: dict[str, tuple[Link, list[str], str]] = {}
    for link in links:
        reasons = [WEIGHT.sub("", x) for x in link.reasons if any(w in x.lower() for w in FUZZY_WORDS)]
        for rid, other in ((link.a, link.b), (link.b, link.a)):
            if reasons and rid in by_id and rid not in found and _suspect(by_id, anchor_of, person_of, rid, other):
                found[rid] = (link, reasons, other)
    drafts = []
    for rid, (link, reasons, other) in sorted(found.items()):
        r = by_id[rid]
        anchor = anchor_of.get(person_of.get(rid)) or by_id.get(other)
        pid = person_of.get(rid, rid)
        drafts.append(IssueDraft(
            check_id="ID-FUZZY-LINK", severity="INFO", title="Record linked to a person by a fuzzy, nickname or initial match",
            message=f"“{r.person_key.display if r.person_key else rid}” ({_where(r)}) → "
                    f"{anchor.person_key.display if anchor and anchor.person_key else other} ({pid}): {'; '.join(reasons)}.",
            entity_ids=[pid], key=rid, evidence=[EvidenceItem(kind="link", label="link", text="; ".join(link.reasons), link=link)],
            evidence_refs={"records": [rid, other]}, action="Confirm the two records are one person."))
    return drafts


def builtin_drafts(records: list[SourceRecord], links: list[Link], persons: Sequence[Person] = ()) -> list[IssueDraft]:
    """`persons` maps records to people for ID-FUZZY-LINK; without it the issue names the record instead."""
    drafts = [_parse_draft(r, issue) for r in records for issue in r.parse_issues if not issue.startswith("legend_mismatch:")]
    return drafts + _legend_drafts(records) + _fuzzy_drafts(records, links, persons)
