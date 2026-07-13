# Candidate algorithm freeze decision

## Decision

`algorithm-candidate-v1` is frozen for public-data development work. The final algorithm is not frozen.

In one sentence: the candidate is exact branch-and-Benders-cut with a global recourse oracle, feasibility and optimality cuts, and an aggregate recourse lower bound.

No optimization run was started for this review. The decision uses only the persisted P1–P3 evidence.

## Gate review

| Requirement | Existing evidence | Decision |
|---|---|---|
| Exact fixtures | `validation/pilot21_exact_fixtures/report.json`: PASS | PASS |
| Formal Small finite-time | `validation/pilot21_small_finite_time/report.json`: PASS | PASS |
| Sparse/dense consistency | Existing test-suite verification through P3: 137 passed | PASS |
| Candidate feasibility | 12 persisted C2 runs, 12 feasible, 0 exceptions | PASS |
| Bound consistency | 12 persisted C2 runs, 0 cases with LB > UB | PASS |
| Paired component evidence | Aggregate: 6 wins, 0 ties, 0 losses in P3 | PASS |
| Scale coverage | Aggregate improved on S01, M01, and L01 | PASS |
| Feasible rate | C2 and C0 both 6/6 feasible in P3 | PASS |
| Cost | Mean runtime improvement versus C0 was non-negative; no extra phase is allocated | PASS |

## Structure decision

Retained:

- exact BBC core;
- global recourse oracle;
- feasibility and optimality cuts;
- aggregate recourse lower bound.

Removed from candidate-v1:

- analytic LB: no incremental benefit over aggregate in P2;
- root prepass: overlaps with bound strengthening and was not needed for the simplest supported structure;
- warm start: P3 warm bundle median improvement was zero;
- ALNS: P3 win rate was 44.4% and median improvement was zero;
- valid inequalities: P3 measured them only in a root+valid bundle, so isolated freeze evidence was insufficient under the P4 structure rule.

Cache, duplicate filtering, checker, logging, resume, and digest remain engineering mechanisms rather than paper components.

## Approval

The candidate may enter the public-data development/calibration pilot. Holdout use remains prohibited until the final algorithm is frozen.

```json
{
  "candidate_algorithm_frozen": true,
  "final_algorithm_frozen": false,
  "approved_for_public_data_pilot": true
}
```
