from datetime import time

import pytest

from sot.normalize.shifts import parse_shift_token
from sot.parsers.pdf.legend import parse_legend


@pytest.mark.parametrize("text,start,end,hours", [
    ("7a-3p", time(7), time(15), 8.0),
    ("3p-11p", time(15), time(23), 8.0),
    ("11p-7a", time(23), time(7), 8.0),
    ("7a-7p", time(7), time(19), 12.0),
    ("7:30a-4p", time(7, 30), time(16), 8.5),
    ("07:00-15:00", time(7), time(15), 8.0),
    ("7a–3p", time(7), time(15), 8.0),
    ("7a to 3p", time(7), time(15), 8.0),
    ("7am - 3pm", time(7), time(15), 8.0),
    ("12a-8a", time(0), time(8), 8.0),
    ("12p-8p", time(12), time(20), 8.0),
])
def test_worked_tokens(text, start, end, hours):
    t = parse_shift_token(text)
    assert (t.start, t.end, t.hours, t.off) == (start, end, hours, False)


@pytest.mark.parametrize("text,tag", [
    ("OFF", "off"), ("off", "off"), ("O", "off"), ("x", "off"), ("-", "off"), ("—", "off"), ("", "off"),
    ("  ", "off"), ("PTO", "pto"), ("Vac", "vac"), ("LV", "lv"),
])
def test_off_tokens(text, tag):
    t = parse_shift_token(text)
    assert t.off and t.tag == tag and t.hours is None and t.start is None


def test_suffix_notes():
    assert parse_shift_token("7a-3p*").note == "*"
    t = parse_shift_token("7a-3p (float BYS)")
    assert t.hours == 8.0 and t.note == "(float BYS)"
    assert parse_shift_token("7a-3p").note is None


@pytest.mark.parametrize("text", ["hello", "7-3", "25:00-3:00", "7a-", "Sofia Reyes", "09/14"])
def test_unknown(text):
    assert parse_shift_token(text) is None


def test_legend_basic():
    legend = parse_legend("Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours.")
    assert legend == {"7a-3p": 8.0, "3p-11p": 8.0, "11p-7a": 8.0, "7a-7p": 12.0}


def test_legend_variants():
    assert parse_legend("7a-3p = 8 hrs; 7a-7p = 12h") == {"7a-3p": 8.0, "7a-7p": 12.0}
    assert parse_legend("7a–3p is 7.5 hours") == {"7a-3p": 7.5}
    assert parse_legend("Floor plan: see charge nurse") == {}
    assert parse_legend("") == {}
