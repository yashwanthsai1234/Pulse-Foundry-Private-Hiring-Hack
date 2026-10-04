"""Silver builder: one mapped RawTable -> typed SourceRecords (+ ShiftRecords for schedule grids).

Every value keeps its raw text (`raw`) next to its normalized form (`fields`); problems never stop the
row, they are recorded in `parse_issues` as "kind:detail" (contract: docs/TASKGRAPH.md §6).
Shift hours come from the shift times; the footnote legend is a cross-check and the source for letter
codes such as "D" (decision RC12).

Sources:
- Medallion bronze/silver/gold layering: https://www.databricks.com/glossary/medallion-architecture
- Polars row iteration (iter_rows named=True): https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.iter_rows.html
- Python datetime.weekday (Monday == 0): https://docs.python.org/3/library/datetime.html#datetime.date.weekday
"""
from __future__ import annotations

import json
import re
from contextlib import suppress
from datetime import date, datetime

from sot.core.models import Locator, Mapping, PersonKey, RawTable, ShiftRecord, SourceRecord
from sot.core.pack import Pack, Vocab
from sot.normalize.dates import infer_column_date_format, parse_date, resolve_weekday_date
from sot.normalize.numbers import parse_number
from sot.normalize.names import parse_person_name, person_key_from_parts
from sot.normalize.phones import normalize_phone
from sot.normalize.shifts import ShiftToken, parse_shift_token
from sot.normalize.vocab import normalize_vocab
from sot.parsers.pdf.legend import parse_legend, parse_legend_codes

LICENSE = re.compile(r"^([A-Z]{1,5})[\W_]*(\d{3,10})$")  # any separator: space, -, –, U+2011, _, ., /
WEEKDAY = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?", re.I)
AMBIGUOUS_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}$")  # 03/04/2021: 3 Mar or 4 Apr (R1-07)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_DAY = re.compile(r"^(\d{1,2})/(\d{1,2})$|^(\d{1,2})\s+([a-z]{3})[a-z]*\.?$|^([a-z]{3})[a-z]*\.?\s+(\d{1,2})$", re.I)


def canonical_license(text: str) -> str:
    """'rn 551203', 'RN_551203', 'RN–551203' -> 'RN-551203'; other values: upper case, no whitespace."""
    s = text.strip().upper()
    m = LICENSE.match(s)
    return f"{m[1]}-{m[2]}" if m else re.sub(r"\s+", "", s)


def _nearest_year(month: int, day: int, anchors: list[date]) -> date | None:
    if not anchors:
        return None
    mid = max(anchors)  # most recent operational date (R1-02)
    candidates = []
    for y in (mid.year - 1, mid.year, mid.year + 1):
        with suppress(ValueError):  # 29 Feb in a non-leap year
            candidates.append(date(y, month, day))
    return min(candidates, key=lambda d: abs((d - mid).days), default=None)


def day_date(header: str, anchors: list[date]) -> tuple[date | None, str | None]:
    """Date of a schedule day column ('Mon 09/14', '09/14', '2026-09-16', 'Friday 18 Sep') + optional issue."""
    text = " ".join(header.split())
    m = WEEKDAY.search(text)
    dow = m.group(1).lower() if m else None
    rest = WEEKDAY.sub("", text).strip(" ,")
    full = parse_date(rest) if re.search(r"\d{4}", rest) else None
    if full is None:
        md = MONTH_DAY.match(rest)
        if not md:
            return None, f"schedule_dates:{header}"
        month, day = ((int(md[1]), int(md[2])) if md[1] else
                      (MONTHS.get(md[4][:3].lower()), int(md[3])) if md[3] else (MONTHS.get(md[5][:3].lower()), int(md[6])))
        if month is None:
            return None, f"schedule_dates:{header}"
        full = (resolve_weekday_date(dow, month, day, anchors) if dow and anchors else None) \
            or _nearest_year(month, day, anchors)
        if full is None:
            return None, f"schedule_dates:{header}"
    if dow and full.strftime("%a").lower() != dow:
        return full, f"day_mismatch:{header}"
    return full, None


_CLEANERS = {"credential.number": canonical_license, "person.employee_id": lambda v: re.sub(r"\s+", "", v).upper()}


def _follows(value: str, fmt: str | None) -> bool:
    try:
        return bool(fmt) and bool(datetime.strptime(value.strip(), fmt))
    except ValueError:
        return False


def _normalize(field_id: str, ftype: str, value: str, pack: Pack, date_fmt: str | None) -> tuple[object, str | None]:
    """Return (normalized value or None, parse issue or None)."""
    if ftype == "date":
        d = parse_date(value, date_fmt) or parse_date(value)
        if d is None:
            return None, f"bad_date:{field_id}"
        m = AMBIGUOUS_DATE.match(value.strip())  # a value off the column's format read day/month-ambiguously
        ambiguous = m and m[1] != m[2] and max(int(m[1]), int(m[2])) <= 12 and not _follows(value, date_fmt)
        return d.isoformat(), f"date_ambiguous:{field_id}" if ambiguous else None
    if ftype == "number":
        n = parse_number(value)
        return (n, None) if n is not None else (None, f"bad_number:{field_id}")
    if ftype == "vocab":
        code, fuzzy = normalize_vocab(value, pack.vocabs[pack.fields[field_id].vocab])
        return code, (f"unknown_vocab:{field_id}" if code is None else f"vocab_fuzzy:{field_id}" if fuzzy else None)
    if ftype == "phone":
        phone = normalize_phone(value)
        return phone, None if phone else f"bad_phone:{field_id}"
    return _CLEANERS.get(field_id, str)(value), None


def _row_fields(raw: dict, value_cols: list[str], col_field: dict[str, str], pack: Pack,
                date_fmts: dict[str, str | None]) -> tuple[dict, list[str]]:
    """Normalised field values of one row plus the parse issues met on the way."""
    fields, issues = {}, []
    for c in value_cols:
        if value := (raw[c] or "").strip():
            norm, issue = _normalize(col_field[c], pack.fields[col_field[c]].type, value, pack, date_fmts.get(c))
            if norm is not None:
                fields[col_field[c]] = norm
            if issue:
                issues.append(issue)
    return fields, issues


def facility_in(text: str, vocab: Vocab) -> str | None:
    """Facility code named in a page title, also when the title carries more text
    ('Harborview Riverdale - Weekly Staff Schedule'): exact vocab match first, else the longest alias found."""
    code, _ = normalize_vocab(text, vocab)
    if code:
        return code
    cleaned = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    hits = [(len(a), c) for c, aliases in vocab.codes.items() for a in aliases
            if f" {re.sub(r'[^a-z0-9]+', ' ', a).strip()} " in cleaned]
    return max(hits)[1] if hits else None


def _missing(required: list[str], alternatives: list[list[str]], fields: dict) -> list[str]:
    """Required fields absent from a row; the one_of requirement is met when any alternative is complete."""
    missing = [f for f in required if f not in fields]
    if alternatives and not any(all(f in fields for f in alt) for alt in alternatives):
        missing += [f for f in alternatives[0] if f not in fields]
    return missing


def _person_key(fields: dict, nick: dict[str, str]) -> PersonKey | None:
    if "person.full_name" in fields:
        return parse_person_name(fields["person.full_name"], nick)
    if "person.given_name" in fields or "person.family_name" in fields:
        return person_key_from_parts(fields.get("person.given_name"), fields.get("person.family_name"), nick)
    return None


def _shift_hours(tok: ShiftToken, legend_h: float | None) -> tuple[float | None, str]:
    if tok.hours is None:
        return legend_h, "legend" if legend_h is not None else "unknown"
    return tok.hours, "both" if legend_h is not None and abs(legend_h - tok.hours) <= 0.01 else "computed"


class _Grid:
    """Per-table schedule context: day columns -> dates, legend hours, letter codes."""

    def __init__(self, t: RawTable, day_cols: list[str], anchors: list[date]):
        footnote = t.context.get("footnote", "")
        legend = json.loads(t.context["legend_json"]) if t.context.get("legend_json") else parse_legend(footnote)
        self.codes = {k.upper(): v for k, v in parse_legend_codes(footnote).items()}
        self.legend = {}
        for token, hours in legend.items():
            tok = parse_shift_token(token)
            if tok and tok.start is not None:
                self.legend[(tok.start, tok.end)] = hours
        self.dates, self.issues = {}, []
        for c in day_cols:
            self.dates[c], issue = day_date(c, anchors)
            if issue:
                self.issues.append(issue)

    def token(self, text: str) -> ShiftToken | None:
        tok = parse_shift_token(text)
        if tok is None and text.upper() in self.codes:
            tok = parse_shift_token(self.codes[text.upper()])
        return tok


def build_silver(t: RawTable, m: Mapping, pack: Pack, anchors: list[date]) -> tuple[list[SourceRecord], list[ShiftRecord]]:
    template = pack.templates[m.template_id]
    col_field = {x.column: x.field_id for x in m.matches}
    day_cols = [c for c, f in col_field.items() if f == "schedule.day"]
    value_cols = [c for c, f in col_field.items() if f != "schedule.day"]
    mapped = set(col_field.values())
    required = [f for f in template.required if f in mapped and f != "schedule.day"]
    one_of = [alt for alt in template.one_of if set(alt) <= mapped]
    date_fmts, ambiguous = {}, []
    for c in value_cols:
        if pack.fields[col_field[c]].type == "date":
            date_fmts[c], amb = infer_column_date_format([v for v in t.df[c].to_list() if v])
            if amb:
                ambiguous.append(col_field[c])
    hint = t.context.get("facility_hint") or t.context.get("title") or ""
    facility = facility_in(hint, pack.vocabs["facilities"]) if hint else None
    grid = _Grid(t, day_cols, anchors) if day_cols else None

    records, shifts = [], []
    for i, row in enumerate(t.df.iter_rows(named=True)):
        raw = {h: row.get(h) for h in t.header}
        if not any((v or "").strip() for v in raw.values()):
            continue
        rid = f"{t.table_id}:{row['_src_row']}"
        loc = Locator(file_id=t.file.file_id, file_name=t.file.file_name, page=t.page, sheet=t.sheet, row=row["_src_row"])
        fields, issues = _row_fields(raw, value_cols, col_field, pack, date_fmts)
        if not records:
            issues += [f"date_ambiguous:{f}" for f in sorted(ambiguous)] + (grid.issues if grid else [])
        if missing := _missing(required, one_of, fields):
            issues.append(f"row_incomplete:{','.join(missing)}")
        if grid and facility and "person.facility" not in fields:
            fields["person.facility"] = facility
        for c in day_cols:
            text = (raw[c] or "").strip()
            tok = grid.token(text)
            if tok is None:
                issues.append(f"shift_token:{text}")
                continue
            if tok.off or grid.dates[c] is None:
                continue
            legend_h = grid.legend.get((tok.start, tok.end))
            if legend_h is not None and tok.hours is not None and abs(legend_h - tok.hours) > 0.01:
                issues.append(f"legend_mismatch:{text}")
            hours, source = _shift_hours(tok, legend_h)
            shifts.append(ShiftRecord(
                shift_id=f"{rid}:{grid.dates[c].isoformat()}", record_id=rid, facility_id=fields.get("person.facility"),
                role=fields.get("person.role"), work_date=grid.dates[c], token=text, start=tok.start, end=tok.end,
                hours=hours, hours_source=source,
                loc=loc.model_copy(update={"col": c, "bbox": (t.cell_bboxes or {}).get(f"{i}:{t.header.index(c)}")})))
        records.append(SourceRecord(record_id=rid, template_id=template.id, entity=template.entity, fields=fields,
                                    raw=raw, person_key=_person_key(fields, pack.nicknames), loc=loc,
                                    parse_issues=issues))
    return records, shifts
