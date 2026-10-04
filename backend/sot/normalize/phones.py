"""US phone normalizer (IMPLEMENTATION §10.3).

Sources:
- https://en.wikipedia.org/wiki/North_American_Numbering_Plan (10-digit NANP, optional leading country code 1)
- NANP number format NXX-NXX-XXXX (N = 2-9): https://en.wikipedia.org/wiki/North_American_Numbering_Plan#Numbering_system
- https://www.itu.int/rec/T-REC-E.164 (E.164 "+<country><number>" canonical form)
"""
from __future__ import annotations

import re

_EXTENSION = re.compile(r"\s*(?:x|ext\.?)\s*\d+\s*$", re.IGNORECASE)


def normalize_phone(text: str) -> str | None:
    """E.164 string for a 10-digit (or 1 + 10 digit) US number, else None (caller keeps raw + PARSE-PHONE)."""
    digits = re.sub(r"\D", "", _EXTENSION.sub("", text))
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    return f"+1{digits}" if re.fullmatch(r"[2-9]\d{2}[2-9]\d{6}", digits) else None
