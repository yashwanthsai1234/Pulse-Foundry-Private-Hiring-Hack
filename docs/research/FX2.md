# FX2 semantic (wave 4)

## Decisions and evidence

- **Confidence = coverage x quality x share of columns explained** (B3-03/B3-07). Before, the share only picked the winner. Real files: PBJ 3 of ~33 columns, CO licences 3 of 8, NYC payroll 3 of ~15, Excel calendar 3 of 10 now score below `map.agent_min` (0.5) -> template None -> `new_source_modeler`. E1 CSVs stay 0.99-1.0. Valentine (below) motivates penalising unmatched columns.
- **Min sample**: a hit rate over fewer than 2 non-null values is divided by 2 (one lucky cell scores 0.5), unless the whole table has fewer rows (the e1 schedule PDF pages are one-row tables; without that exception they fell to 0.775 and TABLE-UNMAPPED).
- **Header similarity**: `token_sort_ratio` instead of `token_set_ratio` (the latter is 100 for any token subset: "EMPLOYEE NAME" -> org.name "name"). JaroWinkler kept as the typo/prefix signal.
- **Vocab fuzzy**: `fuzz.ratio` >= 90 instead of token_set_ratio ("Nurse" -> RN, "Riverdale/Bayside" -> Bayside); "Registerd Nurse" still maps (fuzzy).
- **Dates**: time part stripped by one regex; added `%d.%m.%Y %B %d, %Y %b %d %Y %d %B %Y %d %b %Y` (+ comma variants) and `%Y%m%d`; `parse_date(v, fmt)` falls back to the other formats per value; ambiguity compares counts of parsed values (RC3) instead of `len(values)`.
- **B-002**: weekday-consistent date nearest an anchor, accepted only within 183 days; else None (caller flags `schedule_dates`). "Tue 09/14" with a 2026-09-20 anchor was 2027-09-14 (a year away), now None; New Year crossing still works.
- **B-001 rule**: a contract of the same template under another fingerprint is *drift* only when the normalised headers overlap (Jaccard >= 0.5: same source, columns renamed/added/dropped). An unrelated header (Jaccard 0) is a second source: new contract, no drift. Payroll header with 2 of 7 columns renamed: 5/9 = 0.56 (drift); the "Emp/Cls/Site..." export: 0.0 (new source). `tests/test_contracts.py::test_drift_on_renamed_headers` asserted the old rule for a zero-overlap header; it is now `test_drift_on_partly_renamed_headers`.
- **B1-06**: replay checks value_score only for fields with a real validator (not none / `non_empty`).
- **B1-07**: new `credential.policy_number` (loose, needs a digit) in `vendor_credential`; `credential.number` stays strict and the synonym "policy number" moved to the loose field. `credential.number` remains in `vendor_credential.optional` so existing agent maps that use it still validate. The breaker `test_realistic_policy_numbers_pass_the_credential_number_validator` asserts the strict field accepts policy numbers, which contradicts the contract "keep credential.number strict"; it should target `credential.policy_number`.
- **B2-05**: `TemplateSpec.one_of` (one extra requirement met by any one field list). hr_roster: `one_of: [[given, family], [full_name]]`. `missing_required` reports the fields of the best alternative.
- **S10**: `vocab.clean` (Unicode letters and digits, everything else one space) is the only normaliser; mapper `_norm` and contracts `_norm` build on it.

## Sources

- https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html : token_set_ratio is 100 for subsets; ratio is normalized Indel. Decided ratio for vocab, token_sort_ratio for headers.
- https://arxiv.org/pdf/2010.07386 : Valentine; combining matchers, penalising unmatched columns.
- https://arxiv.org/abs/1905.10688 : Sherlock; value features need enough values per column.
- https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior : %B vs %b, non-padded fields.
- https://pandas.pydata.org/docs/user_guide/timeseries.html : day-first ambiguity pitfall.
- https://docs.python.org/3/library/re.html#regular-expression-syntax : `[^\W\d_]` = any Unicode letter.
- https://www.w3.org/International/questions/qa-personal-names : names are not ASCII.
