# Provisional algorithm configuration schema

`paper-exp-v1` freezes the optimization problem and evaluation ruler, not the final
algorithm. Every algorithm run must carry a configuration record conforming to this
schema. The current candidate is `algorithm-candidate-001`; it is not the paper's
final algorithm.

## Required identity fields

| Field | Type | Meaning |
|---|---|---|
| `algorithm_family` | string | e.g. `direct`, `direct_alns`, `true_bbc_alns` |
| `configuration_name` | string | development names use `algorithm-candidate-*` |
| `configuration_version` | string | revision within that named candidate |
| `problem_protocol_version` | string | fixed evaluation protocol, currently `paper-exp-v1` |
| `status` | enum | `provisional` during development; never silently promoted |

## Required solver and component fields

The record must explicitly contain Boolean `root_prepass`, `warm_start`, `alns`,
`aggregate_recourse_lb`, `analytic_recourse_lb`, `valid_inequalities`, and
`node_cuts`; string `cut_strategy`; numeric `threads`, `seed`, and `mip_gap`.
Non-applicable switches remain present with `false` or an explicit `not_applicable`
annotation rather than being omitted.

`phase_shares` records every active wall-clock phase. BBC candidates use
`root`, `warm`, `alns`, `main`; Direct+ALNS uses `warm`, `alns`, `main`. Shares
must be nonnegative and total one. An explicit absolute phase time, if supported,
must also be recorded because it changes the effective configuration.

`alns_parameters` includes at least `repair_time`, `repair_gap`, `min_destroy`,
`max_destroy`, `restarts`, `stall_iters`, and `destination_ratio`. Implementations
must additionally record any non-default operator, adaptive repair-time, acceptance,
or restart setting that can affect the trajectory.

## Current candidate algorithm configuration

Every item below has **Status: provisional** and must be evaluated by pilot
calibration and/or ablation before a final algorithm is declared.

| Item | Current candidate | Purpose | To be evaluated by |
|---|---|---|---|
| root prepass | enabled, 5% | seed globally valid cuts and strengthen the root | pilot + ablation |
| warm start | enabled, 15% | obtain an initial exact feasible solution | pilot + ablation |
| ALNS | enabled, 25% | improve the incumbent before main BBC | pilot + ablation |
| aggregate recourse LB | enabled | strengthen `eta` with a size-level relaxation | ablation |
| analytic recourse LB | enabled | provide a cheap global recourse floor | ablation |
| valid inequalities | enabled | strengthen handling/open trajectories | ablation |
| node cuts | disabled | optional fractional-node separation | pilot calibration |
| cut strategy | `standard` | generate canonical oracle cuts without stabilization | pilot calibration |
| main BBC | 55% | exact branch-and-Benders-cut phase | pilot calibration |
| Direct+ALNS shares | 15%/25%/60% | equal-budget comparison pipeline | pilot calibration |
| ALNS defaults | repair 2 s, gap .03, destroy .10–.35, 1 restart, stall 10 | candidate neighborhood search controls | pilot + ablation |

## Hashing and result immutability

A configuration hash must cover the canonical serialization of every field above,
including phase shares and all ALNS parameters. Changing any value creates a new
hash even if `configuration_name` is accidentally reused. Results are keyed by the
problem protocol, instance digest, method, seed, budget, and configuration hash;
new configurations must never overwrite old results.

The canonical implementation is `algorithm_configuration.configuration_hash`:
UTF-8 JSON, recursively sorted object keys, compact separators, then SHA-256. The
hash itself is derived metadata and is not included in its own input payload.

Development configurations use `algorithm-candidate-*`. After calibration and
ablation, a separately reviewed immutable record may be named `algorithm-final-v1`.
No current configuration has that status.
