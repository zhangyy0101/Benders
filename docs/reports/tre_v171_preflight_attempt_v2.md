# TRE v1.7.1 preflight attempt v2

- Attempt date: 2026-08-06
- Frozen commit: `247623ae3a8293b0a769d95546717ac30b4e8728`
- Frozen tag: `rolling-v4.6-objective-only-stability-preflight-candidate-v2`
- Problem protocol: `rolling-v4.6-objective-only-stability`
- Algorithm version: `lead-aware-aggregate-lp-residual-global-repair-v1.7.1`
- Result schema: `rolling-results-v16`
- Status: **failed early at the online-runtime gate**

## Execution boundary

The declared main preflight matrix contained 24 zero-shortage-oracle-certified
bundles on seeds 700--702 and five methods, for 120 expected rows. Three seed
shards were started with one method thread, the frozen business weights, frozen
DRA parameters, a 1% MIP gap, and the immutable 60-second per-cycle budgets.

The first complete instance-method block was retained for every seed. It
contains all five methods on the March temporal profile, for 15 diagnostic
rows. The run was then stopped before completing the remaining 105 rows because
the same hard deadline failure had occurred for both MIP methods on all three
seeds. Continuing could not make the preflight matrix pass and would only
repeat a known infrastructure failure. Each seed checkpoint remains an
explicitly incomplete 5/40-row manifest; the merged diagnostic manifest is
15/120, `complete=false`, and `all_ok=false`.

## Observed outcome

| Method | Rows passed | Deadline misses | Mean decision (s) | Mean extraction (s) | Mean validation (s) |
|---|---:|---:|---:|---:|---:|
| `core_start` | 0/3 | 3 | 195.02 | 150.36 | 137.30 |
| `full_bottleneck` | 0/3 | 3 | 202.44 | 157.75 | 132.22 |
| `kp_dos` | 3/3 | 0 | 7.20 | 5.17 | 4.81 |
| `kp_sg` | 3/3 | 0 | 52.35 | 6.18 | 5.30 |
| `dra_rpm` | 3/3 | 0 | 36.97 | 5.80 | 5.49 |

All nine literature-baseline rows completed all five effective execution
cycles, placed 42,618 realized boxes with zero final unplaced quantity, and
reported `common_ex_post_accounting`. The six MIP rows stopped in the first
cycle before execution, so their zero arrivals/unplaced fields are incomplete
and must not be compared with the completed baselines. No row had an
independent feasibility-validation failure, score-identity error, dirty Git
identity, duplicate identity, or stability-accounting mismatch.

## Sequential confirmation

One additional seed-700 `temporal_mar/core_start` row was run alone with the
same frozen settings to exclude parallel resource contention. It also failed:

- preprocessing: 26.95 seconds;
- Gurobi solver: 15.92 seconds;
- solution extraction and canonical accounting: 121.83 seconds;
- online decision: 166.44 seconds;
- independent validation: 212.37 seconds;
- total audit wall time: 379.04 seconds.

The sequential row is complete as a one-row diagnostic manifest but has
`all_ok=false`. It confirms that the three-shard launch was not the cause.

## Root-cause diagnosis

The optimizer produced an incumbent within the intended solve window. The
deadline miss occurs after optimization while turning a 616,277-variable MIP
solution into canonical operation metrics. The current core solution contains
dense zero-valued variable dictionaries. Occupancy-balance evaluation scans
the full `din` dictionary inside every period-by-block combination in
`evaluate_operation_components`. The same evaluator is invoked once during
incumbent extraction/ranking and again by independent validation. This yields
the nearly symmetric 120--158-second extraction and 132--212-second validation
costs seen above.

This is a computational implementation defect, not evidence that the instance
is physically infeasible or that the mathematical model is invalid. On the
same March instances, archived v1.4.7 rows completed both MIP methods, with
roughly 4--6 seconds of total extraction and 2--4 seconds of validation per
full rolling run. The current model is not larger than that archived model;
the regression is in canonical dense-flow accounting introduced after the old
preflight.

## Gate decision and required resolution

Preflight candidate v2 fails and must not proceed to formal experiments.
`FORMAL_RESULT_AUTHORIZED` and manifest `freeze_authorization` remain false.
The partial diagnostic rows are not publication performance evidence.

Before rerunning preflight, optimize canonical operation evaluation and/or
sparsify extracted physical flows while preserving exact numerical equality.
Required verification includes dense-versus-sparse evaluator equivalence,
independent-validator equivalence, a large fixed-snapshot timing regression,
the complete test suite, and a new clean candidate tag. The frozen 24 preflight
bundles may then be rerun because no preflight outcome may be retained across
an implementation change.

## Artifact identities

- Merged 15-row diagnostic CSV SHA-256:
  `ce61927c0062d903f14c4f22ad6418e15f2e582636b5a9f55bb0d92830f25b48`
- Merged diagnostic manifest SHA-256:
  `d51c59217c5330ecbb5a979b4dd2a873d252c012cac83d2a52224dba8f87f504`
- Sequential confirmation CSV SHA-256:
  `204567ae04393f9a91712ed6f465673bb141761b849908f4748e737b28cb93bd`
- Sequential confirmation manifest SHA-256:
  `bf58bbd57b8392db4a6d2729048a0273792a654c21e51521b3030ea9c81793fa`

Local artifacts are under
`local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v2/`.
