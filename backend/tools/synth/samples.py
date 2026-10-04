"""Build the three ready-to-use sample datasets in ../sample_data (judge file format + an answer key).

    python -m tools.synth.samples            # from backend/

Each set folder holds the files to upload (hr_roster, payroll, licenses, schedule PDF) and `answer_key/`
(expected_issues.json = planted problems, truth.json = person <-> record ground truth, schedule*.json = PDF content).

Sources:
- Synthetic test data with planted, known defects (answer key) as a benchmark: https://en.wikipedia.org/wiki/Test_data
"""
from __future__ import annotations

import random
import shutil
from pathlib import Path

from tools.synth.generator import CATALOG, generate_world, plant_defects, write_world
from tools.synth.mutators import MUTATORS

OUT = Path(__file__).resolve().parents[3] / "sample_data"

SETS = [  # name, seed, staff, weeks, defects, PDF variant, mutators per file
    ("set1_weekly_light", 101, 20, 1,
     ["nickname_on_schedule", "last_first_in_payroll", "worked_after_expiry", "paid_vs_scheduled_delta",
      "expiring_in_20_days", "hr_vs_license_expiry_conflict"], "grid", {}),
    ("set2_two_weeks_messy", 202, 40, 2,
     ["nickname_on_schedule", "last_first_in_payroll", "typo_family_name", "maiden_name_on_license",
      "worked_after_expiry", "paid_vs_scheduled_delta", "payroll_person_not_in_hr", "schedule_person_not_in_hr",
      "cna_on_rn_shift", "float_to_other_facility", "missing_rn_day", "phone_format_mix", "hr_duplicate_row",
      "two_people_same_family_name"], "nogrid", {}),
    ("set3_chaos_formats", 303, 60, 1, list(CATALOG), "wrapped_names", {
        "hr_roster.csv": ["rename_headers_synonyms", "delimiter_semicolon", "encoding_latin1_bom"],
        "payroll.csv": ["reorder_columns", "rename_headers_synonyms", "to_xlsx"],
        "licenses.csv": ["title_rows_above_header", "date_format_us_slash"]}),
]


def build(name: str, seed: int, staff: int, weeks: int, defects: list[str], variant: str,
          mutate: dict[str, list[str]]) -> Path:
    world, _ = plant_defects(generate_world(seed, n_staff=staff, weeks=weeks), defects, seed)
    raw = OUT / f".{name}_raw"
    shutil.rmtree(raw, ignore_errors=True)
    write_world(world, raw, variant)
    target, key = OUT / name, OUT / name / "answer_key"
    shutil.rmtree(target, ignore_errors=True)
    key.mkdir(parents=True)
    rng = random.Random(seed)
    for f in sorted(raw.iterdir()):
        if f.suffix == ".json":
            shutil.copy(f, key / f.name)
            continue
        out = f
        for m in mutate.get(f.name, []):
            out = MUTATORS[m](out, rng)
        shutil.copy(out, target / (out.name.split(".")[0] + out.suffix))  # payroll.to_xlsx.xlsx -> payroll.xlsx
    shutil.rmtree(raw)
    return target


if __name__ == "__main__":
    for spec in SETS:
        print(build(*spec))
