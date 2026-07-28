# PNC--Yangshan v1.4.7 three-seed preflight

Candidate version `lead-aware-aggregate-lp-screened-repair-v1.4.7` was tested
on all eight declared semi-synthetic preflight scenarios for seeds 700, 701,
and 702. The 24 runs were executed sequentially with one Gurobi thread and a
60-second online-decision budget per cycle. All input bundles had already
received a zero-shortage certificate from the full-horizon integer packing
oracle.

| Seed | Scenarios passed | Realized arrivals | Final unplaced | Physical recovery | Recovery rate | Maximum revision rate | Maximum peak block utilization | Maximum cycle time (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 700 | 8/8 | 35,623 | 0 | 3 | 0.0084% | 0.0437% | 94.55% | 46.40 |
| 701 | 8/8 | 35,367 | 0 | 5 | 0.0141% | 0.9104% | 88.72% | 46.46 |
| 702 | 8/8 | 35,509 | 0 | 23 | 0.0648% | 3.7053% | 94.26% | 46.31 |
| **Total / maximum** | **24/24** | **106,499** | **0** | **31** | **0.0291%** | **3.7053%** | **94.55%** | **46.46** |

Every run returned `TIME_LIMIT_FEASIBLE`; there were no no-incumbent events,
validation failures, deadline misses, or final unplaced boxes. Physical
recovery affected 31 of 106,499 realized arrivals. Of these, 17 occurred in
the seed-702 baseline-volume case and five in its observed-yard case; this is
a small, localized reservation mismatch rather than aggregate infeasibility.
Twenty-seven recovery placements displaced future reservations, which is why
physical recovery is reported separately from final unplaced quantity.

The maximum revision rate, 3.7053%, occurred in the seed-702 June temporal
case. That case required no physical recovery and placed every arrival, so the
rate records ordinary replanning under that realization rather than a
feasibility repair. The maximum observed block utilization remains localized:
the aggregate instance is oracle-feasible, but the Yangshan-calibrated yard
profile is deliberately spatially imbalanced.

## Freeze decision

Version v1.4.7 passes the declared three-seed candidate gate and may be frozen
for the formal comparison. No further algorithm or parameter tuning should be
performed after formal seeds are opened. The common physical-recovery layer,
time accounting, one-thread setting, and sequential shared-workstation
orchestration must remain identical for the candidate and all applicable
baselines.

Machine-readable aggregate:
`local_results/protocol_v2_pnc_yangshan/preflight_runs/v147_three_seed_summary.csv`.
Per-seed raw results:
`v147_sequential_full/candidate_all8.csv`,
`v147_sequential_seed701/candidate_all8.csv`, and
`v147_sequential_seed702/candidate_all8.csv`.
