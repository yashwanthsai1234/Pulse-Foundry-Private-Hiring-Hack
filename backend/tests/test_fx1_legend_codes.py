from sot.parsers.pdf.legend import parse_legend_codes


def test_codes_forms():
    assert parse_legend_codes("D = 7a-3p, E = 3p-11p, N = 11p-7a (8 hours each)") == {"D": "7a-3p", "E": "3p-11p", "N": "11p-7a"}
    assert parse_legend_codes("D: Day 7a-3p (8 hrs)") == {"D": "7a-3p"}
    assert parse_legend_codes("Day (D) 7a-3p; Night (N) 11p-7a") == {"D": "7a-3p", "N": "11p-7a"}
    assert parse_legend_codes("Shifts: 7a-3p are 8 hours.") == {}
