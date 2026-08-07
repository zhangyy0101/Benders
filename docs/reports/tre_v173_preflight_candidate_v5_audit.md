# TRE v1.7.3 preflight candidate v5 controlled audit

The initial audit completed preparation before any candidate-v5 solver row was
started. Candidate v4 was superseded with zero result rows because a legacy
candidate-v3 resume process was discovered after the v4 tag. That process was
terminated, and candidate v3 remains a permanently failed diagnostic attempt.
The stable candidate-v3 checkpoint contains 60 rows and three same-mechanism
deadline failures. All three pass v1.7.3 directional regression; the closest
case also passes an immediate repeat at 59.388 and 56.495 seconds respectively,
with zero deadline misses, validation failures, and final unplaced quantity.

After the candidate-v5 tag was published, delayed background commands from a
concurrent interactive session started two uncontrolled local checkpoints.
They were not launched from the declared exclusive foreground protocol. The
first contains 3 of 120 rows and the second contains 4 of 120 rows; both have
`complete=false` and `all_ok=false`. Their overlapping first instance records
the same `core_start` and `full_bottleneck` deadline misses, while the completed
literature-baseline rows are feasible. The directories are retained under
`local_results/protocol_v3_tre_objective/preflight/quarantine/` as
`preflight_candidate_v5_aborted_20260806_135001` and
`preflight_candidate_v5_aborted_20260806_135133`. These failures remain part of
the diagnostic audit, but the checkpoints must not be resumed, merged, or
reported as a controlled preflight because process ownership and exclusive-host
conditions were violated before the first row.

## Frozen implementation and execution policy

- Algorithm implementation commit:
  `bdd4f5331c3aea7d33bdcca57e3dd727908acfbb`.
- Immutable preflight orchestration commit:
  `74b27f634a38f3282c99d2328a75e2e69b5d9fe6`.
- Algorithm version:
  `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`.
- Orchestration protocol: `immutable-indexed-publication-v2`.
- Frozen tag:
  `rolling-v4.6-objective-only-stability-preflight-candidate-v5`.
- Formal authorization remains false.

The runner now stops before solving unless the Git tree is clean, all inputs
come from preflight-phase immutable indexes, bundle time budgets are used
without override, threads equal 1, MIP gap equals 1%, the main five-method and
frozen profile identities match, and a fresh output path is selected. Existing
artifacts can only be continued through explicit `--resume`, whose metadata and
requested-matrix equality checks remain mandatory.

## Frozen input and matrix audit

All three index hashes match the manifest. They contain 24 unique bundles over
seeds 700, 701, and 702. Every bundle SHA-256 and embedded case SHA-256 matches
its index. All 24 integer packing certificates prove optimum zero minimum
shortage. Every bundle carries the same 60-second per-cycle budget and the
`preflight` phase. Five methods yield exactly 120 requested rows:
`core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`.

The two uncontrolled candidate-v5 roots have been moved intact to quarantine.
The controlled retry output root
`preflight_candidate_v5_controlled_retry1` does not exist at audit time. It
must be created only by a new run without `--resume`. The empty candidate-v4
log directory contains no CSV, manifest, or solver row and will not be reused.

## Environment and verification

- Python 3.12.0;
- gurobipy 13.0.0 with the licensed host environment verified by the complete
  Gurobi-dependent test suite;
- approximately 236.1 GB free on the workspace drive at the controlled-retry
  readiness audit;
- no Python experiment or solver process active;
- 175 tests and 16 subtests pass;
- formal input generation and execution remain closed.

The controlled preflight was required to run sequentially from a fresh
detached checkout of the clean candidate-v5 tag into the new
`preflight_candidate_v5_controlled_retry1` result root. It used a single
managed foreground process, no Task Scheduler entry, no launcher script, and
no `--resume`. The local and `origin` annotated tag objects both resolve to
`e7651b3801836ad15c2d05b2eecb92d4304c2c6a`.

## Controlled retry outcome

The controlled retry completed on 2026-08-07 (Asia/Shanghai). Its manifest
records `complete=true`, `all_ok=true`, and exactly 120 of 120 requested rows:
24 rows each for `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and
`dra_rpm`. There were no deadline misses, missing incumbents, validation
failures, formulation or identity failures, or final unplaced boxes. All 48
core-method rows contain complete normalized-objective accounting in the
declared range. The maximum observed single-cycle online decision time was
56.075 seconds under the common 60-second limit.

The result artifacts are:

- `local_results/protocol_v3_tre_objective/preflight/`
  `preflight_candidate_v5_controlled_retry1/main_gate/results/business_main.csv`;
- the adjacent `business_main.manifest.json`;
- CSV SHA-256
  `79722d3d7dc14f3e1f065c96ca146858999764a87a1edff3eb7627199771fd2e`.

## Comparison and reporting boundary

All listed metrics are lower-is-better. Values are means over the same 24
instances, except physical recovery, which is the total number of boxes.

| Metric | `full_bottleneck` | `core_start` | Candidate difference |
|---|---:|---:|---:|
| Total online decision time per instance (s) | 137.96 | 175.53 | -21.4% |
| Realized distance (million) | 8.732 | 10.019 | -12.9% |
| Realized conflict | 199.54 | 270.59 | -26.3% |
| Mean-cycle normalized operations score | 0.1885 | 0.2143 | -12.0% |
| Stability cost | 3,252.00 | 2,982.04 | +9.1% |
| Bays per ship-POD | 11.48 | 10.56 | +8.7% |
| Peak block utilization | 77.34% | 68.85% | +8.48 percentage points |
| Utilization deviation | 3.257% | 2.081% | +1.176 percentage points |
| Revision rate | 0.1651% | 0.0160% | +0.149 percentage points |
| Physical-recovery placement (boxes) | 41 | 4 | +37 boxes |

Relative to `core_start`, the candidate therefore shows a preflight advantage
in online decision time, distance, conflict, and the normalized operations
score, while `core_start` is better on accumulated stability, revision,
fragmentation, yard-balance indicators, and physical recovery. This is a
multidimensional trade-off, not universal candidate dominance.

The external baselines are much faster: their mean total decision times are
1.89 seconds for `kp_dos`, 22.78 seconds for `kp_sg`, and 15.15 seconds for
`dra_rpm`, versus 137.96 seconds for the candidate. The two KP methods also
have much lower distance, and DRA-RPM is slightly lower on distance. The
candidate instead has substantially lower conflict, stability cost, revision
rate, bay fragmentation, peak utilization, and utilization deviation than the
three external baselines. Its mean normalized operations score is worse than
the two KP methods but better than DRA-RPM, and all three external baselines
use less physical recovery (9, 9, and 5 boxes, respectively, versus 41).
These methods consequently represent different
speed--distance--solution-structure trade-offs.

The model's lexicographic order remains predicted shortage, stability, and
normalized operations score, but its guarantee is local to alternative stages
evaluated from the same rolling snapshot within one method execution.
`core_start` and `full_bottleneck` are independent rolling simulations:
different early decisions change later states and objectives, while the common
finite time limit and 1% MIP gap can return different feasible incumbents. The
candidate's higher accumulated stability cost therefore does not by itself
show that a lower-priority objective displaced stability inside a common
snapshot.

The candidate used physical recovery for 41 of 106,499 realized boxes
(0.0385%) across 10 of 24 instances and ended with zero unplaced boxes. Here
41 is a box quantity, not 41 recovery events or 41 TEU. Physical recovery is a
post-optimization execution fallback and must be reported separately from
predicted shortage and final unplaced quantity.

This controlled preflight passes the feasibility, interface, accounting, and
runtime gate. It is preliminary evidence only: it does not authorize formal
execution, establish confirmatory statistical significance, or support a
claim that the candidate dominates every comparator on every metric. Formal
authorization remains false pending registration and freezing of an untouched
confirmatory set.
