# FX7 research: synthetic data and chaos harness fixes

| Source | What it decided |
|---|---|
| https://hypothesis.readthedocs.io/en/latest/data.html | Build valid combinations by construction instead of filtering after the fact: `allowed_mutators` and `pdf_variants` pick only from combinations that keep the planted defect visible; `cna_on_rn_shift` was fixed in the generator (it now turns every shift of that person at the facility into RN, which is what the PDF shows) instead of being skipped next to `missing_rn_day`. |
| https://dl.acm.org/doi/10.1145/3143561 (Chen et al., metamorphic testing) | The mutated files are metamorphic follow-ups of the clean files: same data, other format. The golden-equality check is the metamorphic relation, so it must ignore display-only changes (names are casefolded, RC14) and the columns a mutator removed. |
| https://aclanthology.org/2020.acl-main.442/ (CheckList) | Report the unperturbed run next to the perturbed one (`--clean`): the gap between them is what the format noise costs, the clean number is what the system gets wrong by itself (B4: clean recall was already about 80%). |
| https://docs.python.org/3/library/csv.html | `csv.writer` keyword arguments (`delimiter`, `quoting`) are the parameters of the mutator factory (S8): quote_all and the two delimiter mutators are one `_csv_mutator(..., **save_kw)` call each. |
| docs/breakdowns/B4.md RC13-RC18, S8, S9; docs/TASKGRAPH.md section 6 (parse-issue contract, RC12) | The fixes below; LEGEND-MISMATCH is expected once per schedule table (facility x week) and token whose footnote hours are wrong and used. |

Design notes
- Matcher: expectations with employee ids claim issues first, wildcards last (RC13). Matching stays greedy one-to-one.
- RC17: `SpecPageReader` (in chaos.py) replaces the gateway executor for the raster variant only and answers each page from the schedule spec, found by the sha256 of the PDF (the `file_id` in the task payload). The pipeline then runs the real path: scan parser, task, gateway validation, `_apply_page`, silver. Every other agent task stays rejected (agents off).
- RC16: duplicate license numbers expect one ID-NAME-DIFFERS-ON-LICENSE per holder.
- CHECKED now also lists the new check ids (PAY-DUPLICATE, PAY-PERIOD-OVERLAP, PAY-PERIOD-INVALID, PAY-HOURS-INVALID, LIC-EXPIRY-MISSING, LIC-TYPE-MISMATCH, HR-HIRE-DATE, ROW-INCOMPLETE, PARSE-NUMBER, PARSE-PHONE, PARSE-UNKNOWN-VALUE). None is planted, so any of them in a generated world is counted as a false positive (precision).
- S9: `rn_gaps` and its helper moved to `tests/synth_support.py`. `render.make_spec` is only used by `tests/test_pdf_cascade.py`; render.py belongs to FX1, so it is still there (move it to that test when FX1 is done).
