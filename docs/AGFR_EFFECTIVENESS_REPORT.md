# BBC-Incumbent-Guided Fix-and-Repair Effectiveness Report

## Final design

The effective workflow is:

```text
main exact BBC -> incumbent-support candidate domain -> restricted monolithic repair
```

The earlier guide-first workflow was rejected because a poor repair start could
consume BBC time and degrade the final result.  The final repair domain always
contains every active bay/allocation in the BBC incumbent, then adds
aggregate-ranked neighboring bays.  The original incumbent is therefore
representable in the restricted model.

The repair receives 10% of the common wall-clock budget, bounded to 3–12
seconds.  Its UB is accepted only after the complete monolithic solution passes
the common checker and its solver objective agrees with the common evaluator.
The final LB always remains the exact BBC bound.

## Same-budget seed-0 results

All runs use one thread and the same total wall-clock budget for the frozen
Candidate-v1 baseline and the development AGFR method.

| Instance | Budget | Baseline UB | AGFR UB | UB reduction | Baseline gap | AGFR gap |
|---|---:|---:|---:|---:|---:|---:|
| S01 | 30 s | 20437.6339 | 20079.5037 | 358.1301 (1.75%) | 8.44% | 6.90% |
| M01 | 60 s | 15353.6923 | 14895.1404 | 458.5519 (2.99%) | 11.30% | 8.68% |
| L01 | 120 s | 16493.3312 | 16486.0976 | 7.2336 (0.044%) | 15.34% | 15.30% |

Primal integral also decreased on all three instances.  L01's first feasible
solution arrived about 8.8 seconds earlier.  Selected candidate-pair ratios were
0.50, 0.173, and 0.134 for S01, M01, and L01 respectively.

## Correctness and limitations

- Full regression: `191 passed`.
- Every reported final solution passes the common feasibility checker.
- Restricted solver objective and common evaluator agree within tolerance.
- The repair UB source is explicitly recorded as
  `checked_monolithic_feasible_solution`.
- No claim of global recourse optimality is made for post-BBC repair solutions;
  this is not required for a legal UB.  The BBC lower bound remains valid.
- These are seed-0 development results on S01/M01/L01, not a multi-seed or
  public-dataset confirmation.

Reproduce with:

```text
python scripts/run_agfr_effectiveness_screen.py
```

Artifacts are stored under `validation/agfr_effectiveness/`.
