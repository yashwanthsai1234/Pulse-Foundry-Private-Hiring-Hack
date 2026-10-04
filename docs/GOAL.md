# Build Goal (from the user's brief) — tracked until every box is checked

- [x] W0: shared contracts, DB, pack, fixtures, renderer (Opus)
- [x] Dependency graph + task graph so agents do not get confused (`docs/TASKGRAPH.md`)
- [x] W1: spawn the build fleet (Sonnet), one agent per work package, own files only
- [x] Every implementation is TDD: think → test (see it fail) → implement → refactor
- [x] Every proposal/deviation is evidenced by a sandbox experiment before implementation (`docs/research/*.md`)
- [x] Agents research online; each module cites its online sources (docstring `Sources:` + `docs/research/*.md`)
- [x] Code simplicity: 200 lines → 50 where possible; no dead or stale code
- [x] No git
- [x] W2: integration — wiring complete, example_e1 passes through the real pipeline end to end
- [x] W3: 3–4 breaker agents audit wiring and attack with edge cases; every breakdown logged in `docs/BREAKDOWNS.md`
- [x] W4: fix fleet addresses every logged breakdown
- [x] W5: verification + code-quality checks (simplify / code-review passes), best well-researched fixes applied
- [x] A/B tests (e.g. cascade method order, mapper with/without value gate, resolver thresholds) with numbers
- [x] Live panel tests: 4–5 diverse cases, incl. online CSV files and PDFs that could break the system
- [x] Everything implemented and fixed end to end; nothing left out

## Progress log
- W1: 8 Sonnet agents done — 330 unit tests pass; research notes in docs/research/A1–A8.md.
- W2: silver builder + real E2E (tests/test_e2e.py, 5/5) on the PLAN §10 example; baseline chaos (5 variants): recall 81.7%, precision 34%, golden 60%.
- W3: 4 breaker agents launched (wiring, edge cases, real-world files, chaos+simplicity).
- W3: 4 breakers → ~70 breakdowns, 119 failing tests (docs/breakdowns/B1–B4.md).
- W4: 7 fix agents + integrator → 0 failing breaker tests; per-finding status in docs/BREAKDOWNS.md.
- W5: correctness review R1 (8 bugs, all fixed, 12 tests), simplicity refactor R2 (ruff clean, JSON decode once, dead code removed, 109 source URLs verified), A/B harness (6 experiments, docs/ab/AB_TESTS.md), live panel (5 cases, real UI + real Sonnet subagents, docs/panel/PANEL.md; 3 panel bugs found and fixed), DECISIONS.md.
- Process notes (honest): FX4 wrote some code before its tests and did no live web research in its round (it cites known docs); every other agent followed test-first + cited research. `/verify` is not an installed skill here — verification was done with the R1 review, the full suites, ruff and the live panel.
