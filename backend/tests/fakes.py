"""Fake pipeline stages (TASKGRAPH §4 signatures): patch_stages swaps them into sot.pipeline.orchestrator."""
from datetime import datetime
from types import SimpleNamespace

import polars as pl

from sot.core.models import (
    AuctionResult, ExtractionInfo, Issue, Link, Locator, Mapping, Person, RawTable, SniffResult, SourceRecord,
)

CONF = {"high": 0.95, "mid": 0.6, "low": 0.2}


class FakeParser:
    name = "csv"

    def extract(self, f, ctx):
        df = pl.DataFrame({"a": ["1", "2"], "b": ["x", "y"], "_src_row": [2, 3]})
        return [RawTable(table_id=f"{f.file_id[:12]}:0:0", file=f, parser="csv", header=["a", "b"], df=df,
                         extraction=ExtractionInfo(method="csv", score=0.97))]


def patch_stages(monkeypatch, calls: list | None = None, gray=()) -> list:
    calls = calls if calls is not None else []

    def run_auction(f, parsers, min_score):
        ok = not f.file_name.endswith(".bin")
        win = SniffResult(parser="csv", score=0.97, reason="',' gives 2 fields in 100% of rows") if ok else None
        return AuctionResult(file=f, bids=[SniffResult(parser="csv", score=0.1, reason="no")], winner=win)

    def map_table(t, db, pack, settings):
        conf = CONF[t.file.file_name.split(".")[0].split("_")[0]]
        return Mapping(table_id=t.table_id, template_id="hr_roster", confidence=conf, matches=[],
                       unmapped_columns=[], missing_required=[], source="auto")

    def build_silver(t, m, pack, anchors):
        return [SourceRecord(record_id=f"{t.table_id}:{r}", template_id=m.template_id, entity="person", fields={},
                             raw={}, loc=Locator(file_id=t.file.file_id, file_name=t.file.file_name))
                for r in t.df["_src_row"]], []

    def resolve_all(records, pack, settings, extra_links=()):
        calls.append(("resolve", len(records), list(extra_links)))
        persons = [Person(person_id=f"P-{i}", record_ids=[r.record_id], employee_id=None, has_hr=True)
                   for i, r in enumerate(records)]
        grays = [Link(a=records[0].record_id, b=records[1].record_id, prob=0.8, weight=1, method="score",
                      reasons=["x"])] if gray and len(records) > 1 else []
        return SimpleNamespace(persons=persons, links=[], drafts=[], gray_pairs=grays)

    def run_checks(db, pack, settings, run_id, extra_drafts):
        calls.append(("checks", [d.check_id for d in extra_drafts]))
        return [Issue(**d.model_dump(exclude={"evidence_refs"}), fingerprint=f"fp-{i}", first_seen_run=run_id,
                      last_seen_run=run_id) for i, d in enumerate(extra_drafts)]

    stages = dict(
        all_parsers=lambda: [FakeParser()], run_auction=run_auction, map_table=map_table, build_silver=build_silver,
        date_anchors=lambda records: [], resolve_all=resolve_all, build_claims=lambda records, persons, file_times={}: [],
        survive=lambda claims, pack: ([], []), write_gold=lambda *a: None, builtin_drafts=lambda records, links, persons=(): [],
        run_checks=run_checks, build_validators=lambda pack: {}, profile_table=lambda t, v: [],
        classify=lambda t, profiles, pack, settings, forced=None: Mapping(
            table_id=t.table_id, template_id="hr_roster", confidence=0.9, matches=[], unmapped_columns=[],
            missing_required=[], source="agent"),
        save_contract=lambda db, m, t, source: SimpleNamespace(contract_id="hr_roster:v1:abcd1234"),
        parse_legend=lambda text: {})
    for name, fn in stages.items():
        monkeypatch.setattr(f"sot.pipeline.orchestrator.{name}", fn)
    return calls
