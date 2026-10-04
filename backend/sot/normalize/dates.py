"""Date parsing with column-level format inference (IMPLEMENTATION §10.2).

A column is parsed with ONE format, chosen by how many values it parses; a value that does not fit it falls back to
the other formats. A time part ("T00:00:00", " 00:00") is dropped first. If the day-first twin of the
winning month-first format also parses every value and changes at least one date, the column is
ambiguous: US month-first is used and the caller raises PARSE-DATE-AMBIGUOUS. A weekday-only header
("Mon 09/14") gets the weekday-consistent date within half a year of an anchor, else None (the caller flags it).

Sources:
- https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior (strptime formats, %y pivot)
- https://learn.microsoft.com/en-us/office/troubleshoot/excel/1900-and-1904-date-system (Excel serial epoch)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sot.core.models import SourceRecord

EXCEL = "excel"
FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%d-%b-%Y", "%d-%b-%y",
           "%b %d, %Y", "%m-%d-%Y", "%d-%m-%Y", "%d.%m.%Y", "%B %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y",
           "%d %B, %Y", "%d %b, %Y", "%Y%m%d", EXCEL]
DAY_FIRST = {"%m/%d/%Y": "%d/%m/%Y", "%m/%d/%y": "%d/%m/%y", "%m-%d-%Y": "%d-%m-%Y"}
_TIME_PART = re.compile(r"[T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")
MAX_ANCHOR_GAP_DAYS = 183
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse(value: str, fmt: str) -> date | None:
    value = _TIME_PART.sub("", value.strip())
    try:
        if fmt == EXCEL:
            serial = float(value)
            return date(1899, 12, 30) + timedelta(days=int(serial)) if 30000 <= serial <= 60000 else None
        return datetime.strptime(value, fmt).date()
    except ValueError:
        return None


def parse_date(value: str, fmt: str | None = None) -> date | None:
    """Parse with `fmt` (the column's format), else with the first format that fits."""
    return next((d for f in dict.fromkeys([fmt, *FORMATS] if fmt else FORMATS) if (d := _parse(value, f))), None)


def infer_column_date_format(values: list[str]) -> tuple[str | None, bool]:
    """(best format, ambiguous). Ties go to the earlier (US-first) format."""
    values = [v for v in values if v and v.strip()]
    counts = {f: sum(_parse(v, f) is not None for v in values) for f in FORMATS}
    best = max(FORMATS, key=lambda f: counts[f])
    if counts[best] == 0:
        return None, False
    twin = DAY_FIRST.get(best)
    ambiguous = bool(twin) and counts[twin] == counts[best] and any(
        _parse(v, best) != _parse(v, twin) for v in values)
    return best, ambiguous


def resolve_weekday_date(dow: str, month: int, day: int, anchors: list[date]) -> date | None:
    """Year for a header like 'Mon 09/14': the weekday-consistent date nearest to the latest anchor, within half a year."""
    if not anchors:
        return None
    wanted = _WEEKDAYS.index(dow[:3].lower())
    candidates = []
    for year in range(min(anchors).year - 1, max(anchors).year + 2):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d.weekday() == wanted:
            candidates.append(d)
    ref = max(anchors)  # the schedule belongs to the most recent operational period, not to an old outlier
    best = min(candidates, key=lambda d: abs((d - ref).days), default=None)
    return best if best and abs((best - ref).days) <= MAX_ANCHOR_GAP_DAYS else None


ANCHOR_FIELDS = ("pay.period_start", "pay.period_end")


def date_anchors(records: list[SourceRecord]) -> list[date]:
    """Operational dates (pay periods) that give a schedule's 'Mon 09/14' columns their year. Hire dates and
    license expirations are deliberately excluded: they lie years away and would pull the schedule there (R1-02)."""
    out = {date.fromisoformat(r.fields[f]) for r in records for f in ANCHOR_FIELDS
           if isinstance(r.fields.get(f), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.fields[f])}
    return sorted(out)
