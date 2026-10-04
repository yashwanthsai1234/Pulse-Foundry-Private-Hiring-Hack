# FX3 resolve: names, nicknames, blocking, cannot-link

## Changes
| finding | fix | test |
|---|---|---|
| B2-08 | `PersonKey.suffix` keeps jr/sr/ii/iii/iv (rn/cna/lpn/titles are dropped). Scoring component `suffix_disagree -8`; cannot-link rule `{distinct_name_part: suffix}` | test_fx3_resolve (suffix parametrised, never_merges, cannot_link...), breaker test_bell_jr_and_sr |
| B2-14 / RC8 | 20 nickname rows (kate, kathy, katie, peggy, meg, rick, jack, ted, sue, susie, deb, debbie, larry, jerry, terry, cindy, steve, jeff, phil, stacy); all but `terry>terrence` (dataset has terence) are edges of the cited dataset | test_nickname_pairs_from_dataset, breakers |
| B2-15 / RC9 | blocking rule `[family3, given_initial]` replaces `[family, given_initial]` (superset); `family_part` outcome (+2.0) when a compound surname shares a component of 3+ letters; `ph`->`f` given spelling fold = fuzzy (sophia/sofia) | test_compound_or_typo_family..., test_typo_family_shares_a_blocking_key |
| B2-16 | `(...)` and `[...]` notes removed from names | test_parenthetical_notes_are_stripped |
| B3-09 | curly apostrophes to `'`; Ł ø đ ð ß æ œ folded; "Washington- Greene" (cell wrap) rejoined | test_curly_apostrophes..., test_hyphen_then_space... |
| B2-21 | ID-CONFLICT: one draft per person pair and rule | test_one_conflict_per_person_pair |
| licences | resolver canonicalises `credential.number` to PREFIX-DIGITS before blocking, hard keys and cannot-link | test_license_number_forms_are_one_credential_in_the_resolver |
| totals rows | records with no name, no employee id and no licence number are ignored (old test `..._become_singleton_persons` replaced by `..._are_ignored`) | test_records_with_no_name_and_no_ids_are_ignored |

Not changed: `phones.py` (0000000000 / area code rule is not in my brief's list; B2-21 phone part left).

## A/B (synthetic truth, 600 people x 5 records, 3 seeds, pairwise; nick 20%, typo 10%, wrong role 5%, wrong facility 10%, 30% initial-only schedule; names drawn with replacement from 45 given x 25 surnames, so collisions are heavy)
| | P | R | F1 | gray pairs |
|---|---|---|---|---|
| before | .9439 | .8606 | .9003 | 1530 |
| after | .9442 | .9098 | .9267 | 1579 |
| before, 10 surnames | .8551 | .8141 | .8341 | 3589 |
| after, 10 surnames | .8527 | .8614 | .8570 | 3717 |

Recall +4.9 points (nickname rows and the 3-letter blocking key), precision flat. 5k-record scale test (`test_scale_5000_records_under_5_seconds`) passes, no wrong merges.

## Sources
- https://github.com/carltonnorthern/nickname-and-diminutive-names-lookup : nickname edges (names.csv checked for each added pair)
- https://moj-analytical-services.github.io/splink/topic_guides/blocking/blocking_rules.html : union of blocking rules; a coarser key (3-letter prefix) catches typos
- https://en.wikipedia.org/wiki/Suffix_(name) : Jr/Sr/II/III/IV identify different people, RN/CNA are credentials
- https://www.unicode.org/reports/tr15/ : NFKD does not decompose Ł, ø, đ
- https://en.wikipedia.org/wiki/Record_linkage#Blocking : standard blocking
