from datetime import time

from sot.normalize.shifts import parse_shift_token


def test_double_shift_is_one_token():
    for t in ("7a-3p/3p-11p", "7a-3p + 3p-11p"):
        tok = parse_shift_token(t)
        assert (tok.start, tok.end, tok.hours, tok.note) == (time(7), time(23), 16.0, "double")


def test_unicode_hyphens():
    for t in ("7a­-3p", "7a‑3p", "7a−3p"):
        assert parse_shift_token(t).hours == 8.0
