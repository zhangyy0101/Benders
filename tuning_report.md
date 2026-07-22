# Post-Pilot tuning report

Date: 2026-07-22  
Tuning seeds: 100, 101, 102 (reserved for tuning; not formal evaluation)  
Common setting: one thread, 1% MIP gap, 15 seconds per rolling cycle

## Implemented safeguards

- Quality polish is uniformly disabled because the Pilot triggered it in about
  90% of medium runs without improving an incumbent.
- Experiment CSV and manifest files are atomically checkpointed after every
  completed row. `--resume` rejects a different code/protocol/runtime/matrix.
- Integer and binary Gurobi values are normalized to exact integers before the
  independent strict feasibility check. This fixed a false rejection at an
  `8.71e-6` integer residual without relaxing physical constraints.
- Progressive Repair stage dispatch was fixed. A loop variable had overwritten
  the outer stage name, preventing repair stages from entering the queue.

## Standard tuning matrix

The final matrix used `pilot_medium`, utilization 0.55/0.80, forecast error
0.10/0.20, `booking_add_cancel`/`mixed`, and all three tuning seeds. The
reported artifact is `local_results/final_tuning_v38_t15_results.csv`, generated
from clean commit `0d286318eb63e366565eab7167fdd0b5ab8568a0` under protocol v3.8.
All 48 rows completed successfully with zero wall-clock, validation, and
no-incumbent failures.

| Mean metric (24 rows/configuration) | `full_direct` | reactive `full` |
|---|---:|---:|
| total wall time (s) | 4.0379 | 4.0588 |
| first incumbent per cycle (s) | 0.4087 | 0.4109 |
| realized unplaced | 0 | 0 |
| fallback rate | 0.005531 | 0.005531 |
| stability cost | 422.75 | 422.75 |
| predicted operations cost | 0.598095 | 0.598104 |
| realized distance | 99,988.33 | 99,988.33 |
| realized in/out conflict | 123.5669 | 123.6107 |
| repair-trigger rate | 0.020833 | 0.020833 |

Reactive dependency propagation activated in only two standard runs and did
not improve their accepted solution. It no longer worsened unplaced quantity,
unlike proactive propagation.

## Dependency threshold sensitivity

Before adopting reactive triggering, conservative/current/expansive profiles
were tested on the same 24 scenario-seed combinations. Proactive propagation
produced respectively 13/7/7 total unplaced boxes, versus zero for
`full_direct`. Threshold changes alone therefore did not solve the robustness
problem. The proactive design was discarded rather than tuned further.

## Repair mechanism pressure test

The retained pressure suite is deliberately synthetic and is used only for
stage reachability. It has four ships, two cycles, and a controlled second-cycle
forecast shock. The artifact is
`local_results/repair_pressure_v38_t15_results.csv`, from the same clean commit.
All 12 rows completed successfully with zero realized unplaced boxes.

| Pressure/configuration | mean wall (s) | repair triggers | global repairs | propagated pairs | mean final shortage |
|---|---:|---:|---:|---:|---:|
| nearby / `full_direct` | 6.4621 | 4 | 0 | 0 | 0 |
| nearby / reactive `full` | 7.6377 | 4 | 0 | 18 | 0 |
| global / `full_direct` | 18.2933 | 4 | 3 | 0 | 9.1667 |
| global / reactive `full` | 18.2448 | 4 | 3 | 29 | 9.1667 |

The suite proves that Progressive Repair, global recovery, and reactive graph
expansion are reachable and active. It does not show a quality advantage from
dependency propagation: outcomes match direct repair, and nearby pressure is
slower with propagation.

## Final decision

`full_direct` is the recommended core algorithm: MIP start, direct Impact
Region, Progressive Repair, independent validation, and global recovery.
Reactive dependency propagation remains available as the `full` ablation but
is not claimed as a core performance contribution. Protocol v3.9 changes the
default configuration accordingly; it does not change the explicitly selected
v3.8 configurations used in the final matrices above.

Formal experiments must use new seeds and must not reuse seeds 100--102.
