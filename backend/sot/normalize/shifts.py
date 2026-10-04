"""Shift token grammar (IMPLEMENTATION §8.5): "7a-3p", "11p-7a" (crosses midnight), "07:00-15:00", "7a to 3p", double "7a-3p/3p-11p", OFF tags.

Soft hyphen U+00AD is deleted and U+2010-2015/U+2212 read as "-" (Word/Chrome hyphenation).

Sources:
- https://www.unicode.org/charts/PDF/U2000.pdf (hyphen/dash code points), U+00AD soft hyphen: https://www.unicode.org/reports/tr14/
- pdfplumber / PyMuPDF table docs (cell text is free-form, so the grammar must be forgiving):
  https://github.com/jsvine/pdfplumber#table-extraction-settings
- Python re / datetime.time: https://docs.python.org/3/library/re.html
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap])?m?"
_SEP = r"\s*(?:[-\u2013\u2014]|to)\s*"
# Shared with legend.py: finds a token inside a sentence.
TOKEN_RE = re.compile(rf"(?<![\w:]){_TIME}{_SEP}{_TIME}(?![A-Za-z0-9:])", re.IGNORECASE)
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"} | {"\u00ad": None})
_DOUBLE = re.compile(r"^\s*[/+&]\s*(.+)$")
_OFF = {"off": "off", "o": "off", "x": "off", "-": "off", "": "off", "pto": "pto", "vac": "vac", "lv": "lv"}


@dataclass(frozen=True)
class ShiftToken:
    start: time | None
    end: time | None
    hours: float | None
    off: bool
    tag: str | None
    note: str | None


def _time(h: str, m: str | None, ap: str | None) -> time | None:
    hour, minute = int(h), int(m or 0)
    if minute > 59:
        return None
    if ap:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ap.lower() == "p" else 0)
    elif m is None or hour > 23:  # 24h clock needs HH:MM
        return None
    return time(hour, minute)


def canonical(start: time, end: time) -> str:
    """Canonical token text, e.g. time(7), time(15) -> "7a-3p"."""
    def one(t: time) -> str:
        h = t.hour % 12 or 12
        return f"{h}{f':{t.minute:02d}' if t.minute else ''}{'a' if t.hour < 12 else 'p'}"
    return f"{one(start)}-{one(end)}"


def hours_between(start: time, end: time) -> float:
    minutes = ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) % 1440
    return (minutes or 1440) / 60


def parse_shift_token(text: str) -> ShiftToken | None:
    """None = not recognized. Unrecognized suffixes after a valid time range are kept as `note`."""
    t = text.translate(_DASHES).strip()
    if t.lower() in _OFF:
        return ShiftToken(None, None, None, True, _OFF[t.lower()], None)
    m = TOKEN_RE.match(t)
    if not m:
        return None
    ap1, ap2 = m.group(3), m.group(6)
    if bool(ap1) != bool(ap2):
        return None
    start, end = _time(*m.group(1, 2, 3)), _time(*m.group(4, 5, 6))
    if not start or not end:
        return None
    hours, rest = hours_between(start, end), t[m.end():].strip()
    second = _DOUBLE.match(rest)
    nxt = parse_shift_token(second.group(1)) if second else None
    if nxt and nxt.start and nxt.end and not nxt.note:  # double shift: one token spanning both halves
        return ShiftToken(start, nxt.end, hours + (nxt.hours or 0), False, None, "double")
    return ShiftToken(start, end, hours, False, None, rest or None)
