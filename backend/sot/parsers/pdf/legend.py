"""Shift legend from a schedule footnote: "7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."

Sources:
- Python re (sentence split + token search): https://docs.python.org/3/library/re.html
"""
from __future__ import annotations

import re

from sot.normalize.shifts import TOKEN_RE, canonical, parse_shift_token

_SENTENCE = re.compile(r"(?<=[a-z])\.\s+|[;\n]", re.IGNORECASE)
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", re.IGNORECASE)


def parse_legend(text: str) -> dict[str, float]:
    """{canonical token: hours}. Each sentence assigns its one hours number to every token in it."""
    legend: dict[str, float] = {}
    for sentence in _SENTENCE.split(text):
        hours = _HOURS.search(sentence)
        if not hours:
            continue
        for m in TOKEN_RE.finditer(sentence):
            tok = parse_shift_token(m.group())
            if tok and tok.start and tok.end:
                legend[canonical(tok.start, tok.end)] = float(hours.group(1))
    return legend


_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{1,3})(?![A-Za-z])\s*[=:]|\(([A-Z]{1,3})\)")


def parse_legend_codes(text: str) -> dict[str, str]:
    """{letter code: canonical token} for "D = 7a-3p, E: Evening 3p-11p" or "Day (D) 7a-3p"; {} when none."""
    codes: dict[str, str] = {}
    for part in re.split(r"[,;\n]", text):
        code, m = _CODE.search(part), TOKEN_RE.search(part)
        tok = parse_shift_token(m.group()) if m else None
        if code and tok and tok.start and tok.end:
            codes[code.group(1) or code.group(2)] = canonical(tok.start, tok.end)
    return codes
