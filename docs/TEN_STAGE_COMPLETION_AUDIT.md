# Ten-stage completion audit

Audit date: 2026-07-11. Branch: `paper-exp-v1-development`.

| Stage | Status | Persistent evidence |
|---|---|---|
| 01 baseline/cleanup/smoke | PASS | archived history at `archive/paper-exp-v1-development`, registry and smoke tests |
| 02 fixed problem/provisional algorithm | PASS | protocol, data/configuration schemas, machine-readable defaults and hash tests |
| 03 common evaluator/KPIs | PASS | canonical evaluator, pure/Gurobi consistency tests, incomplete-solution guard |
| 04 deterministic generator | PASS | frozen spec, local RNG, construction prechecks and regression tests |
| 05 benchmark IO/digest/registry | PASS | canonical JSON records, SHA-256 verification, file-aware CLIs and round-trip tests |
| 06 pilot build/audit | PASS | nine fixed files, manifest and 9/9 PASS audit |
| 07 exact regression gate | PASS | tiny, tiny_concentration and S01–S03 all PASS |
| 08 configurable runner | PASS | stable run IDs, atomic JSONL, resume/failure tests and Gurobi smoke |
| 09 Classical Benders baseline | PASS | sequential no-callback solver, Direct consistency tests and S01 smoke |
| 10 pilot calibration | PASS (pilot scope) | 47 unique runs, difficulty/component reports and recommendations |

## Rechecked invariants

- All nine benchmark files match their manifest digests and audit status is PASS.
- All five exact-gate instances are PASS; oracle cuts are tight and independently valid.
- All named algorithm configurations have distinct configuration hashes.
- Experiment JSONL files contain unique run IDs.
- Every recorded incumbent in the calibration has a passing common-evaluator feasibility report.
- Classical Benders contains no callback and keeps every strengthening switch disabled.
- `final_algorithm_frozen` remains false; Task 10 is not a final paper experiment.

## Scope limitations retained intentionally

- Pilot calibration uses S01/M01/L01 only. S01 stochastic configurations use seeds 0/1/2;
  Medium/Large are preliminary seed-0 screens.
- Calibration budgets are 15/30/45 seconds, not suggested formal budgets.
- Stabilized and node-cut candidates were not run because the instructions make them conditional
  on prior supporting evidence.
- Some root final bounds are unavailable when the final added cut was not followed by another
  completed root solve; stale bounds are not substituted.
- Pilot benchmarks and calibration results are synthetic development evidence, not final paper data.

## Cleanup policy

Historical Pilot1 calibration and smoke evidence is preserved by `archive/paper-exp-v1-development`.
The active tree retains Pilot2.1 benchmarks, validation gates, and compact P1-P3 selection evidence.
