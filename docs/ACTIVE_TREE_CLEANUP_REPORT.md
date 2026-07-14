# Active Tree Cleanup Report

Cleanup date: 2026-07-14
Branch: `cleanup/stable-candidate-v1`

## Removed historical content

The following directories were removed from the active tree after reference auditing:

- `baseline/pre_paper_exp_v1/`
- `benchmarks/paper_exp_v1_pilot/`
- `benchmarks/paper_exp_v1_pilot2/`
- `validation/small_exact/`
- `experiments/pilot_calibration/`
- `experiments/pilot2_smoke/`
- `experiments/paired_ablation/`
- `experiments/smoke/`
- `experiments/classical_benders_smoke/`

Their history remains accessible through the archive tags. Six analysis/run scripts dedicated only to those removed outputs were also removed. Reusable runners and tests now default to or reference Pilot2.1.

Across retained experiment and validation directories, duplicate `results.json` arrays and generated solution payloads were removed. Baseline run/log payloads were removed. Candidate-v1 smoke retains JSONL, CSV, and its smoke reports.

## Retained active evidence

- `benchmarks/paper_exp_v1_pilot21/`
- `benchmarks/paper_exp_v1_pilot21_exact/`
- `validation/pilot21_exact_fixtures/`
- `validation/pilot21_small_finite_time/`
- `validation/candidate_v1_smoke/`
- `experiments/pilot21_feasibility_screen/`
- `experiments/pilot21_feasibility_screen_l01_120s/`
- `experiments/internal_screen_fast/`
- `experiments/confirmatory_adaptive/`

Exact BBC, Direct Gurobi, Classical Benders, ALNS baseline code, common valid inequalities, checkers/evaluators, benchmark tooling, runners, and tests remain active.

## Configuration visibility

Normal CLI choices expose only `algorithm-candidate-v1`. C0-C8 and other development configurations remain available for evidence replay with `--include-historical-configs`. Visibility metadata is kept outside configuration payloads.

Candidate-v1 remains unchanged:

```text
fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce
```

## Large-file audit

No tracked `results.json`, experiment solution, or baseline run/log payload remains. The largest retained files are standard compact evidence and active Pilot2.1 inputs.

Four experiment files exceed 5 MiB and are intentionally retained because the cleanup specification defines JSONL plus CSV plus report as the standard evidence package:

| File | Bytes | Reason retained |
|---|---:|---|
| `experiments/confirmatory_adaptive/results.csv` | 11,074,288 | Compact tabular P3 confirmation evidence |
| `experiments/confirmatory_adaptive/raw_results.jsonl` | 10,056,520 | Authoritative replayable P3 raw evidence |
| `experiments/internal_screen_fast/results.csv` | 7,666,373 | Compact tabular P2 screening evidence |
| `experiments/internal_screen_fast/raw_results.jsonl` | 6,957,284 | Authoritative replayable P2 raw evidence |

These are neither generated solution files nor duplicate JSON arrays. The largest active benchmark is approximately 2.17 MiB.

## Validation

- Python compilation: PASS
- Full test suite: PASS (`154 passed`)
- Pilot2.1 benchmark audit: PASS (`9 instances`)
- Candidate-v1 smoke: PASS (`3 runs`)
- Candidate-v1 smoke hash: `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`

Stage 03 does not update `main`, push the cleanup branch, or delete any remote branch.
