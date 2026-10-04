"""B2 attacks on facility and role spellings."""
from tests.breakers.edge_world import HR, NOISE, PAY, hr_row, run


def _set(rows, col, values):
    out = [list(r) for r in rows]
    for r, v in zip(out, values):
        r[col] = v
    return out


def test_facility_spellings_all_map_to_the_two_known_facilities(tmp_path, settings):
    hr = _set(HR, 4, ["Bayside", "HV-Bayside", "Harborview Bayside SNF", "BAYSIDE"])
    r = run(tmp_path, settings, hr=hr)
    homes = {p["person_id"]: p["home_facility_id"] for p in r.persons}
    assert homes == {"P-E201": "FAC-BAY", "P-E202": "FAC-BAY", "P-E203": "FAC-BAY", "P-E204": "FAC-BAY"}


def test_payroll_facility_code_spellings(tmp_path, settings):
    pay = _set(PAY, 3, ["bys", "Bayside", "BYS ", "HV-Bayside"])
    r = run(tmp_path, settings, pay=pay)
    assert {p["facility_id"] for p in r.p.db.query("SELECT facility_id FROM pay_periods")} == {"FAC-BAY"}
    assert not (r.attention() - NOISE - {"FAC-MISMATCH", "HRS-PAID-VS-SCHED"})


def test_unknown_facility_in_hr_is_a_needs_human_issue(tmp_path, settings):
    """'Harborview Lakeside' is not one of the two facilities: more than a LOW parse note, and not hidden by payroll's BYS."""
    r = run(tmp_path, settings, hr=[hr_row(0, facility="Harborview Lakeside"), *HR[1:]])
    rec = [x.record_id for x in r.records("hr_roster") if x.fields.get("person.employee_id") == "E201"]
    flagged = [i for i in r.issues if set(i.entity_ids) & set(rec + ["P-E201"]) and i.check_id != "COV-RN-DAILY"]
    assert any(i.severity in ("MEDIUM", "HIGH", "CRITICAL") for i in flagged), [(i.check_id, i.severity) for i in flagged]


def test_ambiguous_two_facility_string_is_not_auto_mapped_at_info(tmp_path, settings):
    """'Harborview Riverdale/Bayside' names both facilities; it was fuzzy-mapped to Bayside with an INFO note."""
    r = run(tmp_path, settings, hr=[hr_row(0, facility="Harborview Riverdale/Bayside"), *HR[1:]])
    rec = [x.record_id for x in r.records("hr_roster") if x.fields.get("person.employee_id") == "E201"]
    flagged = [i for i in r.issues if set(i.entity_ids) & set(rec)]
    assert any(i.severity in ("MEDIUM", "HIGH", "CRITICAL") for i in flagged), [(i.check_id, i.severity) for i in flagged]


def test_role_spellings_map_to_the_three_roles_without_mismatches(tmp_path, settings):
    hr = _set(HR, 3, ["R.N.", "CNA II", "LPN/LVN", "Registered Nurse (RN)"])
    r = run(tmp_path, settings, hr=hr)
    assert {p["person_id"]: p["role"] for p in r.persons} == {"P-E201": "RN", "P-E202": "CNA", "P-E203": "LPN", "P-E204": "RN"}
    assert not r.ids("ROLE-MISMATCH")


def test_unknown_role_med_tech_is_flagged(tmp_path, settings):
    r = run(tmp_path, settings, hr=[hr_row(0, job_title="Med Tech"), *HR[1:]])
    assert "PARSE-UNKNOWN-VALUE" in r.checks()


def test_generic_nurse_title_is_not_silently_an_rn(tmp_path, settings):
    """'Nurse' is an RN or an LPN; fuzzy-matching it to RN at INFO lets scope checks pass for the wrong licence."""
    r = run(tmp_path, settings, hr=[hr_row(0, job_title="Nurse"), *HR[1:]])
    rec = [x.record_id for x in r.records("hr_roster") if x.fields.get("person.employee_id") == "E201"]
    flagged = [i for i in r.issues if set(i.entity_ids) & set(rec)]
    assert any(i.severity in ("MEDIUM", "HIGH", "CRITICAL") for i in flagged), [(i.check_id, i.severity) for i in flagged]
