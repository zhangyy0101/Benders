# PNC--Yangshan v1.4.7 candidate preflight

The eight indexed semi-synthetic preflight bundles were rerun sequentially in
one process with seed 700, one Gurobi thread, and a 60-second online-decision
budget per cycle. This removes the CPU and memory contention present in the
superseded paired-process v1.4.4 diagnostic.

Version 1.4.7 also applies the dynamic stability budget to ordinary
aggregate-routed global-core decisions. Only explicit post-shortage global
recovery may lift that budget. Global models use MIPFocus 1, a 0.20 heuristic
fraction, and a 2,000-node MIP-start repair limit to improve incumbent
reliability. Objectives, feasibility constraints, physical recovery, and the
60-second end-to-end cycle boundary are unchanged.

| Scenario | Completed | Arrivals | Pre-recovery shortfall | Final unplaced | Stability cost | Revision rate | Peak utilization | Total online time (s) | Max cycle (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| temporal March | yes | 4,718 | 1 | 0 | 3,210 | 0.000% | 68.77% | 148.91 | 46.40 |
| temporal April | yes | 4,365 | 0 | 0 | 3,041 | 0.043% | 67.48% | 82.48 | 46.26 |
| temporal June | yes | 4,733 | 0 | 0 | 3,202 | 0.000% | 67.35% | 152.28 | 46.38 |
| volume baseline | yes | 4,347 | 0 | 0 | 2,955 | 0.014% | 66.93% | 150.83 | 46.26 |
| volume low | yes | 3,497 | 0 | 0 | 2,703 | 0.017% | 87.94% | 129.93 | 45.98 |
| volume high | yes | 5,269 | 0 | 0 | 3,544 | 0.011% | 69.48% | 121.35 | 46.12 |
| yard observed | yes | 4,347 | 2 | 0 | 3,302 | 0.044% | 94.55% | 113.50 | 46.32 |
| yard high pressure | yes | 4,347 | 0 | 0 | 3,065 | 0.014% | 75.34% | 133.31 | 46.21 |

All eight bundles completed, every realized export box was placed, and only
three of 35,623 arrivals required reservation-domain physical recovery
(0.0084%). No cycle exceeded its 60-second wall budget. The observed-yard
peak remains high despite moderate terminal-wide initial utilization because
the observed calibration is spatially imbalanced; it is a yard-distribution
result rather than aggregate capacity infeasibility.

The seed-700 candidate gate passes. The subsequently completed seed-701 and
seed-702 gate and the final freeze decision are reported in
`pnc_yangshan_v147_three_seed_preflight.md`. Formal and preflight runs on a
shared workstation must be sequential; parallel shards are permissible only
with isolated CPU and memory resources that preserve the declared per-cycle
wall budget.

Raw results:
`local_results/protocol_v2_pnc_yangshan/preflight_runs/v147_sequential_full/candidate_all8.csv`.
