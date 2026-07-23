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
| normalized operations score | 0.598095 | 0.598104 |
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

## Bottleneck-guided repair development (2026-07-23)

`full_bottleneck` keeps the mathematical model, MIP start, direct Impact Region,
validation, and global recovery unchanged.  It replaces the fixed 20% repair
expansion with a small minimum pair-block cover driven by cumulative shortage,
time-dependent compatible residual capacity, and a one-compatible-bay packing
granularity guard.  `full_direct` remains the formal candidate while this
controller is evaluated as a development ablation.

On the three medium tuning seeds at 30 seconds per cycle, both configurations
completed all runs.  Relative to `full_direct`, `full_bottleneck` reduced mean
wall time from 71.16 to 65.48 seconds and mean repair count from 3.0 to 2.0.
Mean realized unplaced arrivals changed from 2.33 to 1.67.  The trade-off was a
higher mean stability cost (1374.3 versus 1302.3) and normalized operations
score (0.9635 versus 0.9397).  The small normal cases did not trigger either
repair controller and produced identical accepted solutions.

The representative large case did not complete under either 30- or 60-second
cycle limits.  At 60 seconds both controllers reached repair, but exceeded the
cycle wall limit.  The bottleneck repair model was smaller (68,351 versus
78,876 variables; 80,277 versus 92,003 constraints) and its partial run was
shorter (100.3 versus 115.8 seconds), but this is diagnostic evidence rather
than a valid completed comparison.  The development conclusion is therefore
promising mechanism-level reduction without enough evidence to replace
`full_direct` in the formal protocol.

## Freeze-candidate promotion (2026-07-23)

After sparse model construction and indexed independent validation removed the
large-instance Python bottlenecks, `full_bottleneck` passed the candidate-only
held-out preflight on seeds 700--702: 9/9 small, medium, and large rows
completed with no wall-clock, validation, or no-incumbent failure.  The large
profile used 80% initial utilization and triggered bottleneck repair on every
seed.  It is therefore promoted to the freeze candidate under protocol
`rolling-v4.1-bottleneck-repair-freeze-candidate`.  `full_direct` is retained
only as the fixed-ratio repair-controller ablation.

The complete preflight exposed one `core_start` large-cycle overrun: Gurobi
ran 54.03 seconds against an allocated 50.10 seconds even though it returned a
valid incumbent.  The common runtime contract now retains the full 15% tail
(capped at 10 seconds) and terminates from the callback at the absolute stage
deadline.  This safeguard applies identically to every configuration.

## Final freeze-candidate preflight

The final preflight used the complete 36-row matrix under one runtime profile:
four methods, three reserved seeds, and the small/medium/large profiles defined
in `docs/formal_experiment_protocol.md`. All three manifests are complete.
Artifact audit reports 36/36 successful rows, zero wall-clock failures, zero
validation failures, zero no-incumbent failures, and zero normalized-score
identity failures; the largest identity residual is \(7.99\times10^{-15}\).

| Mean metric | profile | `core` | `core_start` | `core_start_impact` | `full_bottleneck` |
|---|---|---:|---:|---:|---:|
| total wall time (s) | small | 3.17 | 2.96 | 1.58 | 1.67 |
| realized unplaced | small | 0.00 | 0.00 | 0.00 | 0.00 |
| total wall time (s) | medium | 61.01 | 61.42 | 52.41 | 40.51 |
| realized unplaced | medium | 2.67 | 3.00 | 55.00 | 3.00 |
| total wall time (s) | large, 80% utilization | 239.80 | 253.09 | 256.01 | 272.69 |
| realized unplaced | large, 80% utilization | 779.33 | 783.33 | 1720.33 | 784.00 |
| stability cost | large, 80% utilization | 16527.67 | 15194.00 | 5087.67 | 27943.33 |

The candidate is materially faster than Global Core on the medium profile and
recovers the severe reliability loss of an unrepaired Impact Region. At 80%
large-instance utilization it reaches Global-Core-level unplaced quantity but
invokes global recovery in most stressed cycles; consequently it is about
13.7% slower than `core` and has a higher time-limited stability cost. The
formal claim is therefore adaptive efficiency in ordinary regimes and
interpretable reliability recovery under stress, not universal dominance over
the unrestricted Global MIP.

The technical preflight gate is passed. Before formal execution, commit and
tag the freeze candidate, require a clean worktree, and do not inspect or tune
on formal seeds 1000--1004.
