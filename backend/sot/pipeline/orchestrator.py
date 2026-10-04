"""Pipeline orchestrator: land -> sniff -> extract -> map -> silver -> resolve -> truth -> checks.

Synchronous (the API runs it in a worker thread). The stage functions are plain module imports, so tests replace
them with monkeypatch on this module. Agent results re-enter through AgentGateway.on_accept.

PDF pages: a text PDF page with no table, or a table scoring below 0.5, goes to a page_reader agent when the page
looks like a schedule; every page scoring below 0.8 raises PARSE-PDF-LOW-CONFIDENCE.

Sources:
- docs/IMPLEMENTATION.md §16, docs/TASKGRAPH.md §4 (stage signatures)
- https://fastapi.tiangolo.com/tutorial/background-tasks/ (how the API runs ingest off the event loop)
- https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap (page -> PNG for the page_reader)
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path

import pymupdf

from sot.agents.gateway import AgentGateway
from sot.checks.builtin import FUZZY_WORDS, builtin_drafts
from sot.checks.engine import run_checks
from sot.config import Settings
from sot.core.events import EventBus, db_persister, next_seq
from sot.core.ids import sha256_bytes
from sot.core.models import (
    AgentTask, FileRef, IssueDraft, Link, Mapping, RawTable, RunSummary, SEVERITY_ORDER,
)
from sot.core.pack import load_pack
from sot.core.registry import ExtractContext, all_parsers
from sot.normalize.dates import date_anchors
from sot.normalize.silver import build_silver
from sot.parsers.base import build_raw_table
from sot.parsers.pdf.legend import parse_legend
from sot.pipeline.pdf_pages import blank_pages, looks_like_schedule
from sot.resolve.resolver import resolve_all
from sot.semantic.classify import classify
from sot.semantic.contracts import map_table, save_contract
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators
from sot.sniff.auction import run_auction
from sot.store import repo
from sot.store.db import DB
from sot.truth.claims import build_claims
from sot.truth.gold import write_gold
from sot.truth.survivorship import survive

PDF_LOW_CONFIDENCE = 0.8  # below: PARSE-PDF-LOW-CONFIDENCE
PAGE_READER_BELOW = 0.5  # below: the page goes to a page_reader agent instead of the mapper
PAGE_DPI = 150
EXPECTED_HEADER = "Staff, Role, 7 day columns"
LEGEND_HINT = "A footnote may explain the shift codes, for example '7a-3p = 8 h' or 'D = 7a-3p'."


def new_run_id() -> str:
    return "run-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:21]


def _where(t: RawTable) -> str:
    return f" page {t.page}" if t.page else f" sheet {t.sheet}" if t.sheet else ""


class Pipeline:
    def __init__(self, settings: Settings, db: DB | None = None, bus: EventBus | None = None):
        self.settings = settings
        self.pack = load_pack(settings.pack_dir)
        self.db = db or DB(settings.db_path)
        self.bus = bus or EventBus(persist=db_persister(self.db), first_seq=next_seq(self.db))
        self.gateway = AgentGateway(self.db, settings, self.bus)
        self.gateway.on_accept = self._apply
        self.lock = threading.RLock()
        self._batch = False  # inside ingest/rebuild: agent results must not trigger a nested rebuild
        self._close_interrupted_runs()

    def _close_interrupted_runs(self) -> None:
        """A run still 'running' at startup died with the previous process."""
        for r in self.db.query("SELECT run_id FROM runs WHERE status = 'running'"):
            self.db.execute("UPDATE runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
                            [datetime.now(), r["run_id"]])
            self.bus.emit(r["run_id"], "run.failed", "run interrupted: the server stopped before it finished")

    # ---------- public ----------
    def ingest(self, paths: list[Path], run_id: str | None = None) -> RunSummary:
        run_id = run_id or new_run_id()
        with self.lock:
            self.db.insert("runs", [{"run_id": run_id, "started_at": datetime.now(), "status": "running"}], replace=True)
            self.bus.emit(run_id, "run.started", f"run started: {len(paths)} file(s)")
            self._batch = True
            try:
                skipped = 0
                for path in paths:
                    skipped += not self._safe_file(Path(path), run_id)
                self._silver_all()
                summary = self._rebuild(run_id, skipped)
            except Exception as e:
                self.bus.emit(run_id, "run.failed", f"run failed: {e}")
                self.db.execute("UPDATE runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
                                [datetime.now(), run_id])
                raise
            finally:
                self._batch = False
            self.db.execute("UPDATE runs SET status = 'completed', finished_at = ?, summary = ? WHERE run_id = ?",
                            [datetime.now(), summary.model_dump_json(), run_id])
            self.bus.emit(run_id, "run.completed", f"run completed: {summary.records} records, "
                          f"{summary.persons} people, {sum(summary.issues_by_severity.values())} issues",
                          **summary.model_dump(exclude={"run_id"}))
            return summary

    def rebuild(self, run_id: str) -> RunSummary:
        """Stages 5-7 over everything in silver."""
        with self.lock:
            self._batch = True
            try:
                return self._rebuild(run_id)
            finally:
                self._batch = False

    def poll_agents(self) -> None:
        """Collect agent results; a rejection changes the issues, so rebuild for it."""
        with self.lock:
            results = self.gateway.poll()
            if any(not r.accepted for r in results):
                self.rebuild(self._latest_run())

    # ---------- stages 1-4 ----------
    def _safe_file(self, path: Path, run_id: str) -> bool:
        """One bad file must not stop the batch, and must stay retryable once the fault is fixed (R1-06)."""
        try:
            return self._file(path, run_id)
        except Exception as e:
            self.db.execute("UPDATE files SET status = 'failed' WHERE file_id = ?", [sha256_bytes(path.read_bytes())])
            self.bus.emit(run_id, "file.quarantined", f"{path.name}: processing failed ({e})", path.name)
            return True

    def _file(self, path: Path, run_id: str) -> bool:
        """Land, sniff, extract and map one file. False if it was skipped as already known."""
        bus = self.bus
        data = path.read_bytes()
        sha = sha256_bytes(data)
        if repo.known_file(self.db, sha):
            bus.emit(run_id, "file.skipped", f"{path.name}: already ingested (sha256 {sha[:8]}), skipped", path.name)
            return False
        landed = self.settings.dir("landing") / f"{sha}{path.suffix.lower()}"
        landed.write_bytes(data)
        f = FileRef(file_id=sha, file_name=path.name, path=str(landed), size=len(data), received_at=datetime.now())
        bus.emit(run_id, "file.landed", f"{path.name}: landed ({len(data)} bytes)", path.name)
        parsers = all_parsers()
        auction = run_auction(f, parsers, self.settings["sniff.min_score"])
        bids = [b.model_dump() for b in auction.bids]
        win = auction.winner
        if win is None:
            best = auction.bids[0] if auction.bids else None
            repo.save_file(self.db, f, run_id, "quarantined", bids=bids)
            bus.emit(run_id, "file.quarantined", f"{path.name}: no parser recognised it"
                     + (f" (best: {best.parser} {best.score:.2f}, {best.reason})" if best else ""), path.name)
            return True
        repo.save_file(self.db, f, run_id, "sniffed", win.parser, win.score, bids)
        bus.emit(run_id, "file.sniffed", f"{path.name} → {win.parser.upper().replace('_', ' ')} ({win.score:.2f}): "
                 f"{win.reason}", path.name, parser=win.parser, score=win.score, bids=bids)
        parser = next(p for p in parsers if p.name == win.parser)
        ctx = ExtractContext(self.settings, self.pack, run_id, win.details, submit_task=self._submit_page)
        try:
            tables = parser.extract(f, ctx)
        except Exception as e:
            repo.save_file(self.db, f, run_id, "quarantined", win.parser, win.score, bids)
            bus.emit(run_id, "file.quarantined", f"{path.name}: extraction failed ({e})", path.name)
            return True
        repo.save_file(self.db, f, run_id, "extracted", win.parser, win.score, bids)
        if win.parser == "pdf_text":
            tables += blank_pages(f, tables)
        for t in tables:
            repo.save_raw_table(self.db, t, self.settings.dir("bronze"))
            self._table_extracted(t, run_id)
            self._route(t, run_id)
        return True

    def _route(self, t: RawTable, run_id: str) -> None:
        """Mapper for a usable table; page_reader for a PDF page the text extraction could not read; nothing for an empty table."""
        if t.parser == "pdf_text" and (looks_like_schedule(t.context["page_text"]) if not t.header
                                       else t.extraction.score < PAGE_READER_BELOW):
            self._request_page_reader(t, run_id)
        elif t.df.height:
            self._map(t, run_id)

    def _request_page_reader(self, t: RawTable, run_id: str) -> None:
        image = self.settings.dir("agent_tasks/files") / f"{t.file.file_id[:12]}_p{t.page}.png"
        with pymupdf.open(t.file.path) as doc:
            doc[t.page - 1].get_pixmap(dpi=PAGE_DPI).save(image)
        payload = {"image": str(image), "page": t.page, "file_id": t.file.file_id}
        self._submit_page(self.gateway.make_task("page_reader", run_id, f"{t.file.file_id}:{t.page}", payload))

    def _submit_page(self, task: AgentTask) -> None:
        """Every page_reader task gets the hints its prompt promises (the scan parser only knows image and page)."""
        names = self.pack.vocabs["facilities"].names or {c: c for c in self.pack.vocabs["facilities"].codes}
        hints = {"expected_header": EXPECTED_HEADER, "facility_vocab": sorted(names.values()),
                 "legend_hint": LEGEND_HINT}
        self.gateway.submit(task.model_copy(update={"payload": {**task.payload, **hints}}))

    def _table_extracted(self, t, run_id: str) -> None:
        self.bus.emit(run_id, "table.extracted", f"{t.file.file_name}{_where(t)}: {t.df.height} rows × "
                      f"{len(t.header)} columns via {t.extraction.method} ({t.extraction.score:.2f})",
                      t.file.file_name, table_id=t.table_id, page=t.page, sheet=t.sheet,
                      method=t.extraction.method, score=t.extraction.score, rows=t.df.height)

    def _map(self, t, run_id: str) -> None:
        m = map_table(t, self.db, self.pack, self.settings)
        name = t.file.file_name
        if m.drift:
            self.bus.emit(run_id, "table.drift", f"{name}: header changed from the stored contract (drift)", name,
                          table_id=t.table_id)
        if m.confidence >= self.settings["map.auto_min"]:
            repo.save_mapping(self.db, m, "mapped")
            self.bus.emit(run_id, "table.mapped", f"{name}{_where(t)} → {m.template_id} ({m.confidence:.2f}), "
                          f"{len(m.matches)} of {len(t.header)} columns mapped", name, **_mapped_data(m, t))
            return
        repo.save_mapping(self.db, m, "pending_agent")
        profiles = profile_table(t, build_validators(self.pack))
        if m.confidence >= self.settings["map.agent_min"]:
            kind, payload = "schema_mapper", self._mapper_payload(t, profiles)
            self.bus.emit(run_id, "table.mapped", f"{name}{_where(t)} → {m.template_id}? ({m.confidence:.2f}) too low to "
                          "trust, asking the schema mapper agent", name, **_mapped_data(m, t))
        else:
            kind, payload = "new_source_modeler", self._modeler_payload(t, profiles)
            self.bus.emit(run_id, "table.unmapped", f"{name}{_where(t)}: no known template fits ({m.confidence:.2f}), "
                          "asking the new-source modeler agent", name, **_mapped_data(m, t))
        self.gateway.submit(self.gateway.make_task(kind, run_id, t.table_id, payload))

    def _template_info(self, tid: str) -> dict:
        tpl = self.pack.templates[tid]
        fields = {f: self.pack.fields[f] for f in tpl.fields}
        return {"id": tid, "entity": tpl.entity, "holder": tpl.holder, "required": tpl.required,
                "fields": [{"id": f, "type": s.type, "synonyms": s.synonyms, "repeatable": s.repeatable}
                           for f, s in fields.items()]}

    def _mapper_payload(self, t, profiles) -> dict:
        """Candidates = the three templates that fit the table best, each scored on its own."""
        fit = {i: classify(t, profiles, self.pack.model_copy(update={"templates": {i: tpl}}), self.settings).confidence
               for i, tpl in self.pack.templates.items()}
        return {"template_candidates": [self._template_info(i) for i in sorted(fit, key=fit.get, reverse=True)[:3]],
                "profiles": [p.model_dump() for p in profiles], "file_name": t.file.file_name,
                "context": {k: v for k, v in t.context.items() if k in ("title", "footnote", "facility_hint")}}

    def _modeler_payload(self, t, profiles) -> dict:
        return {"profiles": [p.model_dump() for p in profiles], "file_name": t.file.file_name,
                "templates": [self._template_info(i) for i in self.pack.templates],
                "fields": {f: {"type": s.type, "synonyms": s.synonyms} for f, s in self.pack.fields.items()}}

    def _load_mapping(self, table_id: str) -> Mapping:
        return Mapping(**self.db.query("SELECT *, unmapped AS unmapped_columns FROM mappings WHERE table_id = ?",
                                       [table_id])[0])

    def _anchors(self) -> list[date]:
        """Dates that give a schedule's weekday columns their year; with none, the as-of date does."""
        return date_anchors([r for r in repo.load_records(self.db) if r.template_id != "schedule"]) or [self.settings.as_of]

    def _silver(self, table_id: str, run_id: str, anchors: list[date] | None = None) -> None:
        t, m = repo.load_raw_table(self.db, table_id), self._load_mapping(table_id)
        anchors = anchors or self._anchors()
        records, shifts = build_silver(t, m, self.pack, anchors)
        repo.delete_table_records(self.db, table_id)
        repo.save_records(self.db, records, shifts)
        self.bus.emit(run_id, "normalize.done", f"{t.file.file_name} → {len(records)} records"
                      + (f", {len(shifts)} shifts" if shifts else ""), t.file.file_name, table_id=table_id)

    def _silver_all(self) -> None:
        """Silver for every mapped table that has none yet. Schedules go last and are redone whenever another kind
        of table is new: its dates may have been guessed from the as-of date before the real anchors arrived."""
        rows = self.db.query(
            "SELECT m.table_id, m.template_id, f.run_id, NOT EXISTS (SELECT 1 FROM source_records s "
            "WHERE s.table_id = m.table_id) AS new FROM mappings m JOIN raw_tables t USING (table_id) "
            "JOIN files f ON f.file_id = t.file_id WHERE m.status = 'mapped'")
        anchors_new = any(r["new"] and r["template_id"] != "schedule" for r in rows)
        todo = [r for r in rows if r["new"] or (anchors_new and r["template_id"] == "schedule")]
        for row in sorted(todo, key=lambda r: r["template_id"] == "schedule"):
            self._silver(row["table_id"], row["run_id"])

    # ---------- stages 5-7 ----------
    def _rebuild(self, run_id: str, skipped: int = 0) -> RunSummary:
        bus = self.bus
        records, shifts = repo.load_records(self.db), repo.load_shifts(self.db)
        for _ in range(2):  # a cached adjudication changes the links, so resolve once more
            res = resolve_all(records, self.pack, self.settings, extra_links=self._agent_links())
            if not self._adjudicate(res.gray_pairs, records, run_id):
                break
        fuzzy = sum(any(w in r.lower() for r in lk.reasons for w in FUZZY_WORDS) for lk in res.links)
        bus.emit(run_id, "resolve.done", f"resolve: {len(records)} records → {len(res.persons)} people; "
                 f"{fuzzy} fuzzy links; {len(res.gray_pairs)} gray pairs")
        file_times = {r["file_id"]: r["received_at"] for r in self.db.query("SELECT file_id, received_at FROM files")}
        claims = build_claims(records, res.persons, file_times)
        golden, survivor_drafts = survive(claims, self.pack)
        write_gold(self.db, records, shifts, res.persons, res.links, claims, golden)
        bus.emit(run_id, "truth.done", f"truth: {len(claims)} claims → {len(golden)} golden values, "
                 f"{sum(g.conflict for g in golden)} conflicts")
        drafts = (builtin_drafts(records, res.links, res.persons) + res.drafts + survivor_drafts + self._pipeline_drafts())
        issues = run_checks(self.db, self.pack, self.settings, run_id, drafts)
        by_sev = {s: n for s in SEVERITY_ORDER if (n := sum(i.severity == s for i in issues if i.active and i.status == "open"))}
        bus.emit(run_id, "checks.done", f"checks: {sum(by_sev.values())} issues: "
                 + (", ".join(f"{n} {s}" for s, n in by_sev.items()) or "none"), counts=by_sev)
        return self._summary(run_id, skipped, len(res.persons), by_sev)

    def _summary(self, run_id: str, skipped: int, persons: int, by_sev: dict[str, int]) -> RunSummary:
        def count(sql: str) -> int:
            return self.db.query(sql, [run_id])[0]["n"]

        return RunSummary(
            run_id=run_id, files=count("SELECT count(*) n FROM files WHERE run_id = ?") + skipped, skipped=skipped,
            quarantined=count("SELECT count(*) n FROM files WHERE run_id = ? AND status = 'quarantined'"),
            tables=count("SELECT count(*) n FROM raw_tables r JOIN files f USING (file_id) WHERE f.run_id = ?"),
            records=self.db.query("SELECT count(*) n FROM source_records")[0]["n"], persons=persons,
            issues_by_severity=by_sev, agent_tasks=count("SELECT count(*) n FROM agent_tasks WHERE run_id = ?"))

    def _adjudicate(self, gray: list[Link], records, run_id: str) -> bool:
        """One identity_adjudicator task per new gray pair. True if a cached answer was applied."""
        by_id = {r.record_id: r for r in records}
        cached = False
        for lk in gray:
            ref = "|".join(sorted((lk.a, lk.b)))
            if self.db.query("SELECT 1 FROM agent_tasks WHERE kind = 'identity_adjudicator' AND ref = ?", [ref]):
                continue
            payload = {"a": _record_view(by_id[lk.a]), "b": _record_view(by_id[lk.b]), "prob": lk.prob,
                       "weight": lk.weight, "reasons": lk.reasons, "candidates": []}
            task = self.gateway.make_task("identity_adjudicator", run_id, ref, payload)
            cached |= self.gateway.submit(task) is not None
        return cached

    def _accepted_same(self) -> list[tuple[str, dict, dict]]:
        """(ref, payload, output) of every identity_adjudicator task an agent answered 'same' and the validator accepted."""
        rows = self.db.query("SELECT ref, payload, output FROM agent_tasks "
                             "WHERE kind = 'identity_adjudicator' AND status = 'accepted'")
        return [(r["ref"], r["payload"], r["output"]) for r in rows
                if r["output"]["decision"] == "same"]

    def _agent_links(self) -> list[Link]:
        return [Link(a=ref.split("|")[0], b=ref.split("|")[1], prob=max(payload["prob"], 0.95),
                     weight=payload["weight"], method="agent", reasons=[f"agent: {output['reason']}"])
                for ref, payload, output in self._accepted_same()]

    def _pipeline_drafts(self) -> list[IssueDraft]:
        q = self.db.query
        drafts = [IssueDraft(check_id="FILE-QUARANTINED", severity="HIGH", title=f"File not ingested: {r['file_name']}",
                             message=f"No parser recognised {r['file_name']}; it was quarantined.", key=r["file_id"],
                             action="Upload a supported format or add a parser.")
                  for r in q("SELECT file_id, file_name FROM files WHERE status = 'quarantined'")]
        drafts += [IssueDraft(check_id="FILE-FAILED", severity="HIGH", title=f"File could not be processed: {r['file_name']}",
                              message=f"{r['file_name']} failed during processing (see the run events); its data is not in "
                                      "the source of truth.", key=r["file_id"], action="Re-upload to retry after the fix.")
                   for r in q("SELECT file_id, file_name FROM files WHERE status = 'failed'")]
        drafts += [IssueDraft(check_id="TABLE-UNMAPPED", severity="HIGH", key=r["table_id"],
                              title=f"Table not mapped: {r['file_name']}",
                              message=f"{r['file_name']} has no confident mapping (confidence {r['confidence']:.2f}); "
                                      "its rows are not in the golden tables yet.",
                              action="Approve an agent mapping or map the columns by hand.")
                   for r in q("SELECT m.table_id, m.confidence, f.file_name FROM mappings m JOIN raw_tables t USING (table_id) "
                              "JOIN files f ON f.file_id = t.file_id WHERE m.status = 'pending_agent'")]
        for r in q("SELECT task_id, kind, ref, output, validator_notes FROM agent_tasks WHERE status IN ('rejected', 'expired')"):
            notes = r["validator_notes"]
            off = notes and notes[0].startswith("agent unavailable")
            drafts.append(IssueDraft(
                check_id="AGENT-UNAVAILABLE" if off else "AGENT-REJECTED", severity="MEDIUM" if off else "HIGH",
                title=f"{r['kind']} needs a human: {r['ref']}", key=r["task_id"], message="; ".join(notes),
                action="Review the suggestion and map or decide by hand.",
                evidence_refs={"agent_output": r["output"]}))
        drafts += [IssueDraft(check_id="MAPPING-REVIEW", severity="INFO", key=r["table_id"],
                              title=f"Review auto-applied mapping: {r['table_id']}",
                              message=f"Mapping to {r['template_id']} came from {'drift' if r['drift'] else r['source']} "
                                      "and is applied but not yet approved.", action="Approve the contract.")
                   for r in q("SELECT table_id, template_id, source, drift FROM mappings "
                              "WHERE status = 'mapped' AND (source = 'agent' OR drift)")]
        drafts += [IssueDraft(check_id="ID-AGENT-LINK", severity="INFO", key=ref, entity_ids=ref.split("|"),
                              title="Identity link made by an agent", message=output["reason"],
                              action="Confirm the link.")
                   for ref, _, output in self._accepted_same()]
        drafts += [IssueDraft(check_id="TABLE-EMPTY", severity="LOW", key=r["table_id"],
                              title=f"Table without data rows: {r['file_name']}",
                              message=f"{r['file_name']}{' page ' + str(r['page']) if r['page'] else ''} has a header "
                                      "but no data rows, so nothing was ingested from it.",
                              action="Check that the export is complete.")
                   for r in q("SELECT t.table_id, t.page, f.file_name FROM raw_tables t JOIN files f USING (file_id) "
                              "WHERE t.n_rows = 0 AND t.header::VARCHAR != '[]'")]
        drafts += self._low_confidence_drafts()
        return drafts

    def _low_confidence_drafts(self) -> list[IssueDraft]:
        """A PDF page that was read with a score below 0.8 (or not at all) and that no page_reader has replaced."""
        drafts = []
        for r in self.db.query(
                "SELECT t.table_id, t.page, t.extraction, f.file_name FROM raw_tables t JOIN files f USING (file_id) "
                "WHERE t.parser = 'pdf_text' AND NOT EXISTS (SELECT 1 FROM agent_tasks a WHERE a.kind = 'page_reader' "
                "AND a.status = 'accepted' AND a.ref = f.file_id || ':' || t.page)"):
            info = r["extraction"]
            if info["score"] < PDF_LOW_CONFIDENCE:
                drafts.append(IssueDraft(
                    check_id="PARSE-PDF-LOW-CONFIDENCE", severity="MEDIUM", key=r["table_id"],
                    title=f"PDF page read with low confidence: {r['file_name']} page {r['page']}",
                    message=f"{r['file_name']} page {r['page']}: {info['method']} scored {info['score']:.2f} "
                            f"(below {PDF_LOW_CONFIDENCE}). " + "; ".join(info["notes"]),
                    action="Compare the page with the extracted rows before relying on them."))
        return drafts

    # ---------- agent results ----------
    def _latest_run(self) -> str:
        return self.db.query("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1")[0]["run_id"]

    def _apply(self, task: AgentTask, output: dict) -> None:
        with self.lock:
            if task.kind == "page_reader":
                self._apply_page(task, output)
            elif task.kind != "identity_adjudicator":
                self._apply_mapping(task, output)
            if not self._batch:
                self.rebuild(task.run_id)

    def _apply_mapping(self, task: AgentTask, output: dict) -> None:
        t = repo.load_raw_table(self.db, task.ref)
        profiles = profile_table(t, build_validators(self.pack))
        forced = {c: f for c, f in output["column_map"].items() if f}
        m = classify(t, profiles, self.pack, self.settings, forced)
        contract = save_contract(self.db, m, t, "agent")
        m = m.model_copy(update={"source": "agent", "contract_id": contract.contract_id})
        repo.save_mapping(self.db, m, "mapped")
        self.bus.emit(task.run_id, "table.mapped", f"{t.file.file_name} → {m.template_id} via agent "
                      f"({m.confidence:.2f}), validator OK", t.file.file_name, **_mapped_data(m, t))
        self._silver(t.table_id, task.run_id)

    def _apply_page(self, task: AgentTask, output: dict) -> None:
        file_id, page = task.ref.rsplit(":", 1)
        rows = output["rows"]
        t = build_raw_table(
            repo.load_file(self.db, file_id), "pdf_scan", output["header"], rows, list(range(1, len(rows) + 1)),
            method="agent.page_reader", score=1.0, page=int(page),
            context={"title": output["title"], "footnote": output["footnote"], "facility_hint": output["title"],
                     "legend_json": json.dumps(parse_legend(output["footnote"]))})
        repo.save_raw_table(self.db, t, self.settings.dir("bronze"))
        self._table_extracted(t, task.run_id)
        self._map(t, task.run_id)
        if self.db.query("SELECT 1 FROM mappings WHERE table_id = ? AND status = 'mapped'", [t.table_id]):
            self._silver(t.table_id, task.run_id)


def _record_view(r) -> dict:
    return {"record_id": r.record_id, "template_id": r.template_id, "raw": r.raw, "fields": r.fields,
            "person_key": r.person_key.model_dump() if r.person_key else None}


def _mapped_data(m: Mapping, t: RawTable) -> dict:
    return {"table_id": m.table_id, "page": t.page, "template_id": m.template_id, "confidence": m.confidence,
            "matches": [x.model_dump() for x in m.matches], "unmapped_columns": m.unmapped_columns}
