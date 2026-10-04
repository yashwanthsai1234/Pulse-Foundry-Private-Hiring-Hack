"""Shared harness for the B2 edge-case attacks: write judge-style files to tmp_path and run the REAL pipeline."""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sot.pipeline.orchestrator import Pipeline  # noqa: E402
from sot.store import repo  # noqa: E402
from tools.synth.render import render_schedule_pdf  # noqa: E402

HR_H = ["employee_id", "first_name", "last_name", "job_title", "facility", "phone", "license_number",
        "license_expiration", "hire_date"]
PAY_H = ["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"]
LIC_H = ["license_number", "name_on_license", "license_type", "expiration_date", "last_verified"]
SCHED_H = ["Staff", "Role", "Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
FOOT = "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."

HR = [
    ["E201", "Sofia", "Reyes", "Registered Nurse", "Harborview Bayside", "718-555-0201", "RN-551203", "2027-05-31", "2020-03-02"],
    ["E202", "Marcus", "Bell", "Certified Nursing Assistant", "Harborview Riverdale", "347-555-0202", "CNA-771045", "2026-12-31", "2022-09-12"],
    ["E203", "Priya", "Natarajan", "Licensed Practical Nurse", "Harborview Bayside", "718-555-0203", "LPN-300111", "2027-08-31", "2019-01-07"],
    ["E204", "Dmitri", "Kowalczyk", "Registered Nurse", "Harborview Riverdale", "347-555-0204", "RN-662210", "2027-02-28", "2018-06-04"],
]
PAY = [
    ["P-3001", "REYES, SOFIA", "RN", "BYS", "2026-09-14", "2026-09-20", "36"],
    ["P-3002", "BELL, MARCUS", "CNA", "RVD", "2026-09-14", "2026-09-20", "40"],
    ["P-3003", "NATARAJAN, PRIYA", "LPN", "BYS", "2026-09-14", "2026-09-20", "16"],
    ["P-3004", "KOWALCZYK, DMITRI", "RN", "RVD", "2026-09-14", "2026-09-20", "24"],
]
LIC = [
    ["RN-551203", "REYES, SOFIA", "RN", "2027-05-31", "2026-09-01"],
    ["CNA-771045", "BELL, MARCUS", "CNA", "2026-12-31", "2026-09-01"],
    ["LPN-300111", "NATARAJAN, PRIYA", "LPN", "2027-08-31", "2026-09-01"],
    ["RN-662210", "KOWALCZYK, DMITRI", "RN", "2027-02-28", "2026-09-01"],
]
OFF = ["OFF"] * 7
SCHED_PAGES = [
    {"title": "Harborview Bayside", "subtitle": "Weekly Staff Schedule - Week of 09/14",
     "rows": [["Sofia Reyes", "RN", "7a-3p", "7a-3p", "OFF", "7a-7p", "OFF", "7a-3p", "OFF"],
              ["Priya Natarajan", "LPN", "3p-11p", "3p-11p", "OFF", "OFF", "OFF", "OFF", "OFF"]]},
    {"title": "Harborview Riverdale", "subtitle": "Weekly Staff Schedule - Week of 09/14",
     "rows": [["Marcus Bell", "CNA", "3p-11p", "OFF", "3p-11p", "3p-11p", "3p-11p", "3p-11p", "OFF"],
              ["Dmitri Kowalczyk", "RN", "7a-3p", "7a-3p", "7a-3p", "OFF", "OFF", "OFF", "OFF"]]},
]


def spec(pages=None, header=None, footnote=FOOT) -> dict:
    return {"header": header or SCHED_H, "footnote": footnote, "pages": pages if pages is not None else SCHED_PAGES}


def write_csv(path: Path, header, rows) -> Path:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([header, *rows] if header else rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def hr_row(i=0, **kw) -> list:
    r = list(HR[i])
    for k, v in kw.items():
        r[HR_H.index(k)] = v
    return r


class Result:
    def __init__(self, p: Pipeline, summary, error=None):
        self.p, self.summary, self.error = p, summary, error

    @property
    def issues(self):
        return repo.load_issues(self.p.db)

    def ids(self, check=None):
        return [i for i in self.issues if check is None or i.check_id == check]

    def checks(self) -> set[str]:
        return {i.check_id for i in self.issues}

    @property
    def persons(self):
        return self.p.db.query("SELECT * FROM persons ORDER BY person_id")

    def records(self, template=None):
        return [r for r in repo.load_records(self.p.db) if template is None or r.template_id == template]

    def person_of(self, record_id):
        r = self.p.db.query("SELECT person_id FROM person_records WHERE record_id = ?", [record_id])
        return r[0]["person_id"] if r else None

    def parse_kinds(self) -> list[str]:
        out = []
        for r in self.records():
            for pi in r.parse_issues:
                out.append(pi.split(":")[0])
        return out

    def pay_periods(self, pid):
        return self.p.db.query("SELECT * FROM pay_periods WHERE person_id = ? ORDER BY period_start", [pid])

    def shifts(self, pid=None):
        sql = "SELECT * FROM shifts" + (" WHERE person_id = ?" if pid else "") + " ORDER BY person_id, work_date"
        return self.p.db.query(sql, [pid] if pid else None)

    def creds(self, pid):
        return self.p.db.query("SELECT * FROM credentials WHERE holder_id = ? ORDER BY number", [pid])

    def person(self, pid):
        rows = self.p.db.query("SELECT * FROM persons WHERE person_id = ?", [pid])
        return rows[0] if rows else None

    def about(self, pid, *exclude):
        """Issues that mention person `pid` (or one of its records) minus the check ids in `exclude`."""
        recs = {rid for rid, _ in self.members().get(pid, [])}
        return [i for i in self.issues if i.check_id not in exclude and (pid in i.entity_ids or recs & set(i.entity_ids))]

    def members(self):
        out = {}
        for r in self.p.db.query("SELECT person_id, record_id, template_id FROM person_records"):
            out.setdefault(r["person_id"], []).append((r["record_id"], r["template_id"]))
        return out

    def nm(self, rid):
        for r in self.records():
            if r.record_id == rid:
                f = r.fields
                return f.get("person.full_name") or f.get("person.last_name") or f.get("credential.holder_name") or rid
        return rid

    def dump(self, label=""):
        print("=====", label)
        from collections import Counter
        print("RECORDS", dict(Counter(r.template_id for r in self.records())), "PARSE", dict(Counter(self.parse_kinds())))
        print("PERSONS", [(r["person_id"], r["display_name"], r["role"], r["home_facility_id"]) for r in self.persons])
        print("MEMBERS", {pid: sorted(f"{t[:3]}:{(self.nm(rid))}" for rid, t in rs) for pid, rs in self.members().items()})
        print("CREDS", [(c["number"], c["holder_id"], str(c["expires_on"])) for c in self.p.db.query("SELECT * FROM credentials ORDER BY number")])
        for i in self.issues:
            print(" ISSUE", i.check_id, i.severity, i.entity_ids, i.title)

    def attention(self) -> set[str]:
        """Check ids that tell a human something is off (anything but INFO)."""
        return {i.check_id for i in self.issues if i.severity != "INFO"}


def csv_text(header, rows) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(([header] if header else []) + rows)
    return buf.getvalue()


def run(tmp_path, settings, hr=HR, pay=PAY, lic=LIC, sched=None, hr_header=HR_H, pay_header=PAY_H,
        lic_header=LIC_H, extra=(), as_of=date(2026, 9, 21), hr_text=None, pay_text=None, lic_text=None,
        variant="grid", no_sched=False, raise_errors=True) -> Result:
    settings.agents = "off"
    settings.as_of = as_of
    d = tmp_path / "in"
    d.mkdir(exist_ok=True)
    paths = []
    for name, header, rows, text in (("hr_roster.csv", hr_header, hr, hr_text), ("payroll.csv", pay_header, pay, pay_text),
                                     ("licenses.csv", lic_header, lic, lic_text)):
        if text is not None:
            (d / name).write_text(text, encoding="utf-8")
            paths.append(d / name)
        elif rows is not None:
            paths.append(write_csv(d / name, header, rows))
    if not no_sched:
        paths.append(render_schedule_pdf(sched or spec(), d / "schedule.pdf", variant))
    paths += list(extra)
    p = Pipeline(settings)
    try:
        s = p.ingest(paths, run_id="b2")
    except Exception as e:  # a crash is a finding; tests assert on it explicitly
        if raise_errors:
            raise
        return Result(p, None, e)
    return Result(p, s)


def probe(label, tmp, **kw):
    """Exploration helper (scripts only)."""
    from sot.config import load_settings
    import tempfile
    st = load_settings(runtime=Path(tempfile.mkdtemp()))
    try:
        r = run(Path(tempfile.mkdtemp()), st, **kw)
    except Exception as e:
        import traceback
        print("=====", label, "CRASH", repr(e)); traceback.print_exc(limit=-4); return None
    r.dump(label)
    return r


NOISE = {"COV-RN-DAILY"}  # the baseline week has no RN cover on some days; every run reports it
R0 = SCHED_PAGES[0]["rows"]
R1 = SCHED_PAGES[1]["rows"]


def pages(rows0=None, rows1=None, header=None, footnote=FOOT) -> dict:
    """The baseline two-page schedule spec with the rows of either page replaced."""
    p0, p1 = dict(SCHED_PAGES[0]), dict(SCHED_PAGES[1])
    p0["rows"] = rows0 if rows0 is not None else p0["rows"]
    p1["rows"] = rows1 if rows1 is not None else p1["rows"]
    return spec([p0, p1], header=header, footnote=footnote)
