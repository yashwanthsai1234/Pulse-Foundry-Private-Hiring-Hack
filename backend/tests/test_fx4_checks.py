"""FX4: parse-issue contract, LEGEND-MISMATCH and ID-FUZZY-LINK drafts, evidence with raw row and column."""
import pytest

from a5_e1 import example_e1, run_e1
from sot.checks.builtin import builtin_drafts
from sot.core.models import FieldMatch, Locator, Mapping, SourceRecord
from sot.store import repo

LOC = Locator(file_id="f", file_name="f.csv", row=1)

CONTRACT = [  # docs/TASKGRAPH.md §6, one row per kind
    ("bad_date:person.hire_date", "PARSE-DATE", "MEDIUM"),
    ("bad_date:credential.expires_on", "PARSE-DATE", "HIGH"),
    ("date_ambiguous:person.hire_date", "PARSE-DATE-AMBIGUOUS", "MEDIUM"),
    ("bad_number:pay.hours_paid", "PARSE-NUMBER", "MEDIUM"),
    ("unknown_vocab:person.facility", "PARSE-UNKNOWN-VALUE", "MEDIUM"),
    ("vocab_fuzzy:person.role", "PARSE-FUZZY-VALUE", "INFO"),
    ("bad_phone:person.phone", "PARSE-PHONE", "LOW"),
    ("shift_token:7a-?", "PARSE-SHIFT-TOKEN", "MEDIUM"),
    ("row_incomplete:pay.period_start", "ROW-INCOMPLETE", "MEDIUM"),
    ("schedule_dates:Mon", "PARSE-SCHEDULE-DATES", "HIGH"),
    ("day_mismatch:Mon 09/15", "PARSE-DATE-WEEKDAY", "MEDIUM"),
    ("legend_mismatch:7a-3p", "LEGEND-MISMATCH", "MEDIUM"),
]


def rec(rid, issues, template="schedule", page=None):
    return SourceRecord(record_id=rid, template_id=template, entity="x", fields={}, raw={},
                        loc=LOC.model_copy(update={"page": page}), parse_issues=issues)


@pytest.mark.parametrize(("issue", "check_id", "severity"), CONTRACT)
def test_parse_issue_contract(issue, check_id, severity):
    (d,) = builtin_drafts([rec("t:1:0:2", [issue])], [])
    assert (d.check_id, d.severity) == (check_id, severity)


def test_field_issues_name_the_field_for_the_evidence_column():
    (d,) = builtin_drafts([rec("t:1:0:2", ["bad_date:person.hire_date"])], [])
    assert d.evidence_refs == {"records": ["t:1:0:2"], "field": "person.hire_date"}


# ---- RC11 (per file and token: tests/breakers/test_chaos_rootcauses.py::test_legend_mismatch_is_one_issue_per_file_and_token)
def test_legend_mismatch_is_one_issue_per_file_and_token():
    other = LOC.model_copy(update={"file_name": "g.pdf"})
    rows = [rec(f"ab:1:0:{n}", ["legend_mismatch:11p-7a"]) for n in range(5)]
    rows += [rec("ab:2:0:1", ["legend_mismatch:11p-7a"], page=2), rec("ab:1:0:9", ["legend_mismatch:7a-3p"])]
    rows += [rec("cd:2:0:3", ["legend_mismatch:11p-7a"]).model_copy(update={"loc": other})]
    drafts = builtin_drafts(rows, [])
    assert sorted((d.entity_ids[0], d.key) for d in drafts) == [("f.csv", "11p-7a"), ("f.csv", "7a-3p"), ("g.pdf", "11p-7a")]
    six = next(d for d in drafts if d.key == "11p-7a" and d.entity_ids == ["f.csv"])
    assert len(six.evidence_refs["records"]) == 6 and "6 schedule row" in six.message


# ---- RC1 / B-009 / B-019 -------------------------------------------------------------------------------------------
def test_fuzzy_link_is_one_issue_per_source_record_with_person_id_and_names():
    records, _, persons, links = example_e1()
    (d,) = builtin_drafts(records, links, persons)
    assert (d.check_id, d.severity, d.entity_ids, d.key) == ("ID-FUZZY-LINK", "INFO", ["P-E202"], "sch:2")
    assert d.message == "“Marc Bell” (schedule.csv p.2) → Marcus Bell (P-E202): given nickname."
    assert d.evidence_refs == {"records": ["sch:2", "hr:3"]} and d.evidence[0].link == links[0]


def test_two_links_to_one_record_make_one_issue():
    records, _, persons, links = example_e1()
    twin = links[0].model_copy(update={"a": "hr:3", "reasons": ["given initial (+1.0)"]})
    assert len(builtin_drafts(records, [*links, twin], persons)) == 1


def test_fuzzy_link_between_two_non_hr_records_does_not_flag_records_linked_exactly_to_hr():
    records, _, persons, links = example_e1()
    via_payroll = links[0].model_copy(update={"a": "pay:3", "b": "sch:2"})  # pay:3 is exact to HR; only sch:2 is suspect
    drafts = builtin_drafts(records, [links[0], via_payroll], persons)
    assert [d.key for d in drafts] == ["sch:2"]


def test_exact_links_make_no_fuzzy_issue():
    records, _, persons, links = example_e1()
    exact = links[0].model_copy(update={"method": "key", "reasons": ["credential.number equal (CNA-771045)"]})
    assert builtin_drafts(records, [exact], persons) == []


def test_fuzzy_link_without_persons_names_the_record():
    records, _, _, links = example_e1()
    (d,) = builtin_drafts(records, links)
    assert d.entity_ids == ["sch:2"]


# ---- B1-11: evidence names the column and carries the source row ---------------------------------------------------
def test_csv_claim_and_record_evidence_carry_raw_row_and_column(db, pack, settings):
    for table, column in (("hr", "license_expiration"), ("lic", "Expiration")):
        repo.save_mapping(db, Mapping(table_id=table, template_id="x", confidence=1, source="auto", unmapped_columns=[],
                                      missing_required=[], matches=[FieldMatch(column=column, field_id="credential.expires_on",
                                                                               score=1, header_score=1, value_score=1, type_score=1)]), "mapped")
    issues, _ = run_e1(db, pack, settings)
    lic = next(i for i in issues if i.check_id == "LIC-WORKED-EXPIRED")
    claims = [e for e in lic.evidence if e.kind == "claim"]
    assert claims and all(e.raw for e in claims)
    assert {e.loc.col for e in claims} == {"license_expiration", "Expiration"}
