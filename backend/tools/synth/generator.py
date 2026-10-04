"""Seeded synthetic Harborview world: staff, schedule, payroll, licenses, plus a catalogue of planted defects.

The world is plain data. `write_world` renders it to the four judge files (README column names) plus
`schedule.json` (render spec), `expected_issues.json` (what the pipeline must flag) and `truth.json`
(person <-> record ground truth). A world with more than one week writes `schedule_w2.pdf`, ... as well.
Defaults are clean: one RN on 7a-3p at each facility every day, payroll = scheduled hours, licenses valid.
Each defect changes only the files it claims and records `ExpectedIssue`s (kind "issue", "link" or "no_merge").
Normalisation-only defects (`last_first_in_payroll`, `phone_format_mix`, `whitespace_case_noise`) record none.

Names: the 2010 US Census surname list and SSA given-name list are the public frequency sources the
embedded lists were taken from (top entries only, no network at runtime).

Sources:
- https://census.gov/topics/population/genealogy/data/2010_surnames.html
- https://www.ssa.gov/oact/babynames/limits.html
- https://hypothesis.readthedocs.io/ (property-based tests of the generator)
- https://docs.reportlab.com/reportlab/userguide/ch7_tables/ (renderer; rl_config.invariant for reproducible PDFs)
"""
from __future__ import annotations

import copy
import csv
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from reportlab import rl_config

from tools.synth.render import render_schedule_pdf

rl_config.invariant = 1  # byte-identical PDFs for the same input

HR_HEADER = ["employee_id", "first_name", "last_name", "job_title", "facility", "phone", "license_number",
             "license_expiration", "hire_date"]
PAY_HEADER = ["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"]
LIC_HEADER = ["license_number", "name_on_license", "license_type", "expiration_date", "last_verified"]
FACILITIES = {"FAC-BAY": ("Harborview Bayside", "BYS"), "FAC-RVD": ("Harborview Riverdale", "RVD")}
JOB_TITLE = {"RN": "Registered Nurse", "LPN": "Licensed Practical Nurse", "CNA": "Certified Nursing Assistant"}
TOKENS = {"7a-3p": (7, 8), "3p-11p": (15, 8), "11p-7a": (23, 8), "7a-7p": (7, 12)}  # token -> (start hour, hours)
RN_TOKENS = ["7a-3p", "7a-3p", "3p-11p", "7a-7p"]
ANY_TOKENS = ["7a-3p"] * 7 + ["3p-11p"] * 6 + ["11p-7a"] * 3 + ["7a-7p"] * 4
SAFE_OFFSETS = (0, 1, 5, 6)  # days whose shifts never touch the missing-RN day (offset 3)
MISSING_OFFSET = 3
NICKS = {"Marcus": "Marc", "William": "Bill", "Robert": "Bob", "Elizabeth": "Liz", "Katherine": "Kate",
         "Michael": "Mike", "Jennifer": "Jen", "Christopher": "Chris", "Margaret": "Maggie", "Matthew": "Matt",
         "Anthony": "Tony", "Joseph": "Joe", "Daniel": "Dan", "Kenneth": "Ken", "Timothy": "Tim",
         "Jeffrey": "Jeff", "Patricia": "Pat", "Deborah": "Debbie", "Richard": "Rick", "Susan": "Sue"}
GIVEN = [*NICKS, "Mary", "Linda", "Barbara", "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle", "Carol", "Amanda", "Melissa", "Stephanie", "Rebecca", "Laura", "Sharon", "Cynthia", "Kathleen", "Amy", "Angela", "Shirley", "Anna", "Brenda", "Pamela", "Nicole", "Sofia", "Maria", "Renée", "James", "John", "David", "Charles", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kevin", "Brian", "George", "Ronald", "Edward", "Jason", "Ryan", "José", "André", "Marcia"]
SURNAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Bell", "Muñoz"]
PHONE_FORMATS = ["{a}-{b}-{c}", "({a}) {b}-{c}", "{a}.{b}.{c}", "{a}{b}{c}", "+1 {a} {b} {c}"]
CATALOG = ("nickname_on_schedule", "last_first_in_payroll", "typo_family_name", "maiden_name_on_license",
           "worked_after_expiry", "expiring_in_20_days", "hr_vs_license_expiry_conflict", "paid_vs_scheduled_delta",
           "payroll_person_not_in_hr", "schedule_person_not_in_hr", "duplicate_license_number", "cna_on_rn_shift",
           "float_to_other_facility", "overlapping_shifts_two_facilities", "missing_rn_day", "legend_mismatch_token",
           "bad_date_value", "ambiguous_date_column", "phone_format_mix", "hr_duplicate_row",
           "whitespace_case_noise", "two_people_same_family_name")


@dataclass
class Staff:
    employee_id: str
    given: str
    family: str
    role: str
    facility: str
    license_number: str
    license_exp: date
    last_verified: date
    hire_date: date
    phone: str
    hr_exp: date
    in_hr: bool = True
    in_lic: bool = True
    in_pay: bool = True
    sched_name: str | None = None
    lic_name: str | None = None
    hire_text: str | None = None

    @property
    def license_type(self) -> str:
        return self.license_number.split("-")[0]

    @property
    def payroll_name(self) -> str:
        return f"{self.family}, {self.given}".upper()


@dataclass
class Shift:
    employee_id: str
    facility: str
    work_date: date
    token: str
    role: str


@dataclass
class ExpectedIssue:
    check_id: str
    severity: str
    employee_ids: list[str] = field(default_factory=list)
    facility_id: str | None = None
    note: str = ""
    kind: str = "issue"  # issue | link | no_merge


@dataclass
class World:
    seed: int
    start: date
    weeks: int
    staff: list[Staff]
    shifts: list[Shift]
    legend: dict[str, int] = field(default_factory=lambda: {t: h for t, (_, h) in TOKENS.items()})
    pay_delta: dict[tuple[str, int], float] = field(default_factory=dict)
    hr_dups: list[str] = field(default_factory=list)
    ambiguous_dates: bool = False
    phone_mix: bool = False
    noise: bool = False
    used: set[str] = field(default_factory=set)
    expected: list[ExpectedIssue] = field(default_factory=list)

    @property
    def as_of(self) -> date:
        return self.start + timedelta(days=7 * self.weeks)

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(7 * self.weeks)]


def _new_staff(rng: random.Random, number: int, role: str, facility: str, family: str, start: date,
               taken: set[str], given: str | None = None) -> Staff:
    while (num := rng.randint(100000, 999999)) and f"{role}-{num}" in taken:
        pass
    taken.add(f"{role}-{num}")
    exp = start + timedelta(days=rng.randint(150, 700))
    return Staff(f"E{number}", given or rng.choice(GIVEN), family, role, facility, f"{role}-{num}", exp,
                 start - timedelta(days=rng.randint(5, 60)), start - timedelta(days=rng.randint(200, 4000)),
                 f"{rng.choice([718, 347, 929, 917])}-555-{number:04d}", exp)


def _give_shifts(world: World, rng: random.Random, s: Staff) -> None:
    token = rng.choice(RN_TOKENS if s.role == "RN" else ANY_TOKENS)
    taken = {(x.employee_id, x.work_date) for x in world.shifts}
    for day in world.days():
        if rng.random() < 0.6 and (s.employee_id, day) not in taken:
            world.shifts.append(Shift(s.employee_id, s.facility, day, token, s.role))


def generate_world(seed: int, n_staff: int = 40, weeks: int = 2, start: date = date(2026, 9, 14)) -> World:
    rng = random.Random(seed)
    n_rn, n_lpn = round(0.3 * n_staff), round(0.15 * n_staff)
    roles = ["RN"] * n_rn + ["LPN"] * n_lpn + ["CNA"] * (n_staff - n_rn - n_lpn)
    families = rng.sample(SURNAMES, n_staff)
    taken: set[str] = set()
    fac_count = {r: 0 for r in JOB_TITLE}
    staff = []
    for i, (role, family) in enumerate(zip(roles, families)):
        fac_count[role] += 1
        staff.append(_new_staff(rng, 201 + i, role, list(FACILITIES)[fac_count[role] % 2], family, start, taken))
    world = World(seed, start, weeks, staff, [])
    for fac in FACILITIES:
        rns = [s for s in staff if s.role == "RN" and s.facility == fac]
        for g, day in enumerate(world.days()):
            world.shifts.append(Shift(rns[g % len(rns)].employee_id, fac, day, "7a-3p", "RN"))
    for s in staff:
        _give_shifts(world, rng, s)
    return world


# ---- defects -------------------------------------------------------------------------------------------------

def _pick(w: World, rng: random.Random, role: str | None = None, shifted: bool = True, nonrn: bool = True,
          safe: bool = False) -> Staff:
    have = {x.employee_id for x in w.shifts if not safe or (x.work_date - w.start).days in SAFE_OFFSETS}
    pool = [s for s in w.staff if s.in_hr and s.employee_id not in w.used and (s.role != "RN" or not nonrn)
            and (role is None or s.role == role) and (not shifted or s.employee_id in have)]
    s = rng.choice(pool)
    w.used.add(s.employee_id)
    return s


def _safe_shift(w: World, rng: random.Random, s: Staff) -> Shift:
    return rng.choice([x for x in w.shifts if x.employee_id == s.employee_id
                       and (x.work_date - w.start).days in SAFE_OFFSETS])


def _extra_staff(w: World, rng: random.Random, role: str, facility: str, family: str | None = None,
                 given: str | None = None) -> Staff:
    taken = {s.license_number for s in w.staff}
    family = family or rng.choice([f for f in SURNAMES if f not in {s.family for s in w.staff}])
    s = _new_staff(rng, 201 + len(w.staff), role, facility, family, w.start, taken, given)
    w.staff.append(s)
    w.used.add(s.employee_id)
    return s


def _issue(check: str, sev: str, ids: list[str] | None = None, **kw) -> ExpectedIssue:
    return ExpectedIssue(check, sev, ids or [], **kw)


def _nickname(w, rng):
    s = _pick(w, rng, nonrn=False)
    while s.given not in NICKS:
        s = _pick(w, rng, nonrn=False)
    s.sched_name = f"{NICKS[s.given]} {s.family}"
    return [_issue("ID-FUZZY-LINK", "INFO", [s.employee_id], note="nickname on schedule", kind="link")]


def _typo(w, rng):
    s = _pick(w, rng, nonrn=False)
    k = len(s.family) // 2
    s.sched_name = f"{s.given} {s.family[:k] + s.family[k + 1:]}"
    return [_issue("ID-FUZZY-LINK", "INFO", [s.employee_id], note="typo in family name", kind="link")]


def _maiden(w, rng):
    s = _pick(w, rng, nonrn=False, shifted=False)
    maiden = rng.choice([f for f in SURNAMES if f not in {x.family for x in w.staff}])
    s.lic_name = f"{maiden}, {s.given}".upper()
    return [_issue("ID-NAME-DIFFERS-ON-LICENSE", "LOW", [s.employee_id], note="maiden name on license")]


def _worked_after_expiry(w, rng):
    s = _pick(w, rng)
    first = min(x.work_date for x in w.shifts if x.employee_id == s.employee_id)
    s.license_exp = s.hr_exp = first
    s.last_verified = first - timedelta(days=30)
    return [_issue("LIC-WORKED-EXPIRED", "CRITICAL", [s.employee_id], note="license expired on the first shift day")]


def _expiring(w, rng):
    s = _pick(w, rng, shifted=False)
    s.license_exp = s.hr_exp = w.as_of + timedelta(days=20)
    return [_issue("LIC-EXPIRING", "HIGH", [s.employee_id], note="expires in 20 days")]


def _hr_conflict(w, rng):
    s = _pick(w, rng, shifted=False)
    s.hr_exp = s.license_exp + timedelta(days=90)
    return [_issue("SRC-CONFLICT", "MEDIUM", [s.employee_id], note="HR expiry differs from license service")]


def _paid_delta(w, rng):
    s = _pick(w, rng)
    w.pay_delta[(s.employee_id, 0)] = 8
    return [_issue("HRS-PAID-VS-SCHED", "HIGH", [s.employee_id], note="paid 8 h more than scheduled in week 1")]


def _payroll_only(w, rng):
    s = _extra_staff(w, rng, "CNA", rng.choice(list(FACILITIES)))
    s.in_hr = s.in_lic = False
    w.pay_delta[(s.employee_id, 0)] = 40
    return [_issue("PAY-NO-HR", "HIGH", note="payroll-only person"),
            _issue("HRS-PAID-VS-SCHED", "HIGH", note="payroll-only person has no scheduled hours")]


def _schedule_only(w, rng):
    s = _extra_staff(w, rng, "CNA", rng.choice(list(FACILITIES)))
    s.in_hr = s.in_pay = False
    _give_shifts(w, rng, s)
    return [_issue("SCHED-NO-HR", "MEDIUM", note="schedule-only person")]


def _dup_license(w, rng):
    a = _pick(w, rng, shifted=False)
    b = _pick(w, rng, role=a.role, shifted=False)
    b.license_number, b.license_exp, b.hr_exp, b.last_verified = a.license_number, a.license_exp, a.hr_exp, a.last_verified
    return [_issue("ID-DUP-LICENSE", "CRITICAL", [a.employee_id, b.employee_id], note=a.license_number),
            *(_issue("ID-NAME-DIFFERS-ON-LICENSE", "LOW", [x.employee_id], note="licence row shares the number of another person")
              for x in (a, b))]


def _cna_on_rn(w, rng):
    s = _pick(w, rng, role="CNA", safe=True)
    fac = _safe_shift(w, rng, s).facility
    for x in w.shifts:  # the schedule shows one role per person and facility, so all of them turn RN
        if x.employee_id == s.employee_id and x.facility == fac:
            x.role = "RN"
    return [_issue("LIC-SCOPE", "CRITICAL", [s.employee_id], note="CNA scheduled as RN"),
            _issue("ROLE-MISMATCH", "MEDIUM", [s.employee_id], note="schedule role RN, HR role CNA")]


def _float(w, rng):
    s = _pick(w, rng, safe=True)
    _safe_shift(w, rng, s).facility = next(f for f in FACILITIES if f != s.facility)
    return [_issue("FAC-MISMATCH", "MEDIUM", [s.employee_id], note="one shift at the other facility")]


def _overlap(w, rng):
    s = _pick(w, rng, safe=True)
    x = _safe_shift(w, rng, s)
    x.token = "7a-3p"
    other = next(f for f in FACILITIES if f != x.facility)
    w.shifts.append(Shift(s.employee_id, other, x.work_date, "7a-3p", x.role))
    return [_issue("SHIFT-OVERLAP", "HIGH", [s.employee_id], note="same hours at two facilities"),
            _issue("FAC-MISMATCH", "MEDIUM", [s.employee_id], note="second shift at the other facility")]


def _missing_rn(w, rng):
    day = w.start + timedelta(days=MISSING_OFFSET)
    w.shifts = [x for x in w.shifts if not (x.role == "RN" and x.facility == "FAC-RVD" and x.work_date == day)]
    return [_issue("COV-RN-DAILY", "CRITICAL", facility_id="FAC-RVD", note=day.isoformat())]


def _legend(w, rng):
    w.legend["11p-7a"] = 9  # the issues are counted per schedule table in plant_defects
    return []


def _bad_date(w, rng):
    s = _pick(w, rng, nonrn=False, shifted=False)
    s.hire_text = "2020-02-30"
    return [_issue("PARSE-DATE", "MEDIUM", [s.employee_id], note="impossible hire date")]


def _ambiguous(w, rng):
    w.ambiguous_dates = True
    for s in w.staff:
        s.hire_date = s.hire_date.replace(day=rng.randint(1, 12))
    return [_issue("PARSE-DATE-AMBIGUOUS", "MEDIUM", note="hire_date written dd/mm/yyyy, all days <= 12")]


def _hr_dup(w, rng):
    s = _pick(w, rng, nonrn=False, shifted=False)
    w.hr_dups.append(s.employee_id)
    return [_issue("HR-DUP-ROW", "MEDIUM", [s.employee_id], note="second HR row with a different phone")]


def _same_family(w, rng):
    a = _pick(w, rng, nonrn=False)
    same_letter = [g for g in GIVEN if g[0] == a.given[0] and g != a.given] or [g for g in GIVEN if g != a.given]
    b = _extra_staff(w, rng, a.role, a.facility, a.family, rng.choice(same_letter))
    _give_shifts(w, rng, b)
    return [_issue("", "", [a.employee_id, b.employee_id], note="two people, one family name: must not merge",
                   kind="no_merge")]


def _flag(attr: str):
    def plant(w, rng):
        setattr(w, attr, True)
        return []
    return plant


DEFECTS = {
    "nickname_on_schedule": _nickname, "last_first_in_payroll": lambda w, rng: [], "typo_family_name": _typo,
    "maiden_name_on_license": _maiden, "worked_after_expiry": _worked_after_expiry,
    "expiring_in_20_days": _expiring, "hr_vs_license_expiry_conflict": _hr_conflict,
    "paid_vs_scheduled_delta": _paid_delta, "payroll_person_not_in_hr": _payroll_only,
    "schedule_person_not_in_hr": _schedule_only, "duplicate_license_number": _dup_license,
    "cna_on_rn_shift": _cna_on_rn, "float_to_other_facility": _float,
    "overlapping_shifts_two_facilities": _overlap, "missing_rn_day": _missing_rn,
    "legend_mismatch_token": _legend, "bad_date_value": _bad_date, "ambiguous_date_column": _ambiguous,
    "phone_format_mix": _flag("phone_mix"), "hr_duplicate_row": _hr_dup,
    "whitespace_case_noise": _flag("noise"), "two_people_same_family_name": _same_family,
}
CHECKED = frozenset(i for i in (
    "LIC-WORKED-EXPIRED", "LIC-EXPIRING", "SRC-CONFLICT", "HRS-PAID-VS-SCHED", "PAY-NO-HR", "SCHED-NO-HR",
    "ID-DUP-LICENSE", "LIC-SCOPE", "ROLE-MISMATCH", "FAC-MISMATCH", "SHIFT-OVERLAP", "COV-RN-DAILY",
    "LEGEND-MISMATCH", "PARSE-DATE", "PARSE-DATE-AMBIGUOUS", "HR-DUP-ROW", "ID-NAME-DIFFERS-ON-LICENSE",
    "ID-FUZZY-LINK", "PAY-DUPLICATE", "PAY-PERIOD-OVERLAP", "PAY-PERIOD-INVALID", "PAY-HOURS-INVALID",
    "LIC-EXPIRY-MISSING", "LIC-TYPE-MISMATCH", "HR-HIRE-DATE", "ROW-INCOMPLETE", "PARSE-NUMBER", "PARSE-PHONE",
    "PARSE-UNKNOWN-VALUE"))


def plant_defects(world: World, catalog: list[str] | tuple[str, ...], seed: int) -> tuple[World, list[ExpectedIssue]]:
    """Return a copy of `world` with the named defects planted and the issues they must produce."""
    w, rng = copy.deepcopy(world), random.Random(seed)
    for name in sorted(catalog, key=lambda n: n == "missing_rn_day"):  # missing_rn_day last: it strips RN shifts
        w.expected += DEFECTS[name](w, rng)
    w.expected += _legend_issues(w)
    return w, w.expected


def _legend_issues(w: World) -> list[ExpectedIssue]:
    """LEGEND-MISMATCH once per schedule table (facility x week) and token whose footnote hours are wrong and used."""
    wrong = {t for t, h in w.legend.items() if h != TOKENS[t][1]}
    out = []
    for wk in range(w.weeks):
        days = set(w.days()[7 * wk:7 * wk + 7])
        for fac in FACILITIES:
            used = {x.token for x in w.shifts if x.facility == fac and x.work_date in days}
            out += [_issue("LEGEND-MISMATCH", "MEDIUM", note=f"{t} is {w.legend[t]} h in the footnote ({fac}, week {wk + 1})")
                    for t in sorted(wrong & used)]
    return out


# ---- rows and files ------------------------------------------------------------------------------------------

def _num(x: float) -> str:
    return f"{x:g}"


def hr_rows(w: World) -> list[list[str]]:
    rows = []
    for i, s in enumerate(x for x in w.staff if x.in_hr):
        d = s.phone.split("-")
        phone = PHONE_FORMATS[i % 5].format(a=d[0], b=d[1], c=d[2]) if w.phone_mix else s.phone
        hire = s.hire_text or s.hire_date.strftime("%d/%m/%Y" if w.ambiguous_dates else "%Y-%m-%d")
        given, family = (f"  {s.given} ", s.family.upper()) if w.noise and i % 7 == 3 else (s.given, s.family)
        rows.append([s.employee_id, given, family, JOB_TITLE[s.role], FACILITIES[s.facility][0], phone,
                     s.license_number, s.hr_exp.isoformat(), hire])
        if s.employee_id in w.hr_dups:
            rows.append([*rows[-1][:5], phone[:-1] + str((int(phone[-1]) + 1) % 10), *rows[-1][6:]])
    return rows


def payroll_rows(w: World) -> list[list[str]]:
    rows, n = [], 3000
    for wk in range(w.weeks):
        lo = w.start + timedelta(days=7 * wk)
        for s in (x for x in w.staff if x.in_pay):
            hours = sum(TOKENS[x.token][1] for x in w.shifts
                        if x.employee_id == s.employee_id and lo <= x.work_date < lo + timedelta(days=7))
            hours += w.pay_delta.get((s.employee_id, wk), 0)
            if hours:
                n += 1
                rows.append([f"P-{n}", s.payroll_name, s.role, FACILITIES[s.facility][1], lo.isoformat(),
                             (lo + timedelta(days=6)).isoformat(), _num(hours)])
    return rows


def license_rows(w: World) -> list[list[str]]:
    return [[s.license_number, s.lic_name or s.payroll_name, s.license_type, s.license_exp.isoformat(),
             s.last_verified.isoformat()] for s in w.staff if s.in_lic]


def _footnote(legend: dict[str, int]) -> str:
    groups: dict[int, list[str]] = {}
    for token, hours in legend.items():
        groups.setdefault(hours, []).append(token)
    return "Shifts: " + " ".join(f"{', '.join(t)} {'are' if len(t) > 1 else 'is'} {h} hours." for h, t in groups.items())


def schedule_specs(w: World) -> list[dict]:
    """One render spec per week (same format as tests/fixtures/*/schedule.json)."""
    specs = []
    for wk in range(w.weeks):
        days = w.days()[7 * wk:7 * wk + 7]
        pages = []
        for fac, (title, _) in FACILITIES.items():
            rows = []
            for s in sorted((x for x in w.staff), key=lambda x: x.sched_name or f"{x.given} {x.family}"):
                mine = {x.work_date: x for x in w.shifts if x.employee_id == s.employee_id and x.facility == fac}
                if any(d in mine for d in days):
                    role = min((x.role for x in mine.values() if x.work_date in days), key=list(JOB_TITLE).index)
                    rows.append([s.sched_name or f"{s.given} {s.family}", role,
                                 *(mine[d].token if d in mine else "OFF" for d in days)])
            pages.append({"title": title, "subtitle": f"Weekly Staff Schedule - Week of {days[0]:%m/%d}", "rows": rows})
        specs.append({"header": ["Staff", "Role", *(f"{d:%a %m/%d}" for d in days)], "footnote": _footnote(w.legend),
                      "pages": pages})
    return specs


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows([header, *rows])


def write_world(world: World, out_dir: Path, variant: str = "grid") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "hr_roster.csv", HR_HEADER, hr_rows(world))
    _write_csv(out_dir / "payroll.csv", PAY_HEADER, payroll_rows(world))
    _write_csv(out_dir / "licenses.csv", LIC_HEADER, license_rows(world))
    for i, spec in enumerate(schedule_specs(world)):
        suffix = "" if i == 0 else f"_w{i + 1}"
        (out_dir / f"schedule{suffix}.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        render_schedule_pdf(spec, out_dir / f"schedule{suffix}.pdf", variant)
    (out_dir / "expected_issues.json").write_text(json.dumps([asdict(e) for e in world.expected], indent=1))
    persons = [{"employee_id": s.employee_id, "person_id": f"P-{s.employee_id}", "given": s.given, "family": s.family,
                "role": s.role, "facility": s.facility, "license_number": s.license_number, "in_hr": s.in_hr,
                "names": {"hr": f"{s.given} {s.family}", "payroll": s.payroll_name,
                          "license": s.lic_name or s.payroll_name, "schedule": s.sched_name or f"{s.given} {s.family}"}}
               for s in world.staff]
    (out_dir / "truth.json").write_text(json.dumps({"persons": persons}, indent=1, ensure_ascii=False), encoding="utf-8")
