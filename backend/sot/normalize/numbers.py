"""Lenient number reading shared by column mapping and the silver builder.

Sources:
- Decimal comma vs thousands separator conventions: https://en.wikipedia.org/wiki/Decimal_separator
"""
from __future__ import annotations

import re

NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
UNIT_TAIL = re.compile(r"\s*(h|hr|hrs|hour|hours)?\.?\s*", re.I)


def parse_number(text: str) -> float | None:
    """'36,5' -> 36.5 (decimal comma), '1,036' -> 1036, '40 hrs' -> 40; anything else around the number -> None."""
    m = NUMBER.match(text.strip())
    if not m or not UNIT_TAIL.fullmatch(text.strip()[m.end():]):
        return None
    s = m.group()
    return float(s.replace(",", ".") if re.fullmatch(r"[-+]?\d+,\d{1,2}", s) else s.replace(",", ""))
