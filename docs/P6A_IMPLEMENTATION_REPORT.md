# P6A candidate-v2 strengthening implementation report

## Implemented configurations

| Configuration | Hash | Aggregate | Common valid inequalities |
|---|---|---|---:|
| `V2A_valid` | `1bffc1e3229f5aee0273725f31d946c395c741c77fcbe6840170501a0741583b` | size | enabled |
| `V2B_pod_size_aggregate` | `e99b68eb08ee908f506f5c40c908ed9383315a6a8ff436b2bd6da5af8dce46cb` | POD-size | disabled |
| `V2C_pod_size_aggregate_valid` | `4a8c3824e70a0162e31d7b979f6981c9a6c72af92bdcbea6b30e4488dd0e9db6` | POD-size | enabled |

All are version `2-dev`, status `development_candidate_v2`, and keep analytic LB, root prepass, warm start, ALNS, node cuts, and stabilization disabled.

Candidate-v1 remains unchanged at hash `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`.

## POD–size relaxation and validity mapping

POD–size variables exist only for active `(ship, POD, size)` combinations. Height and weight subclasses are deliberately summed rather than separately constrained.

For any feasible full-recourse solution, define each POD–size aggregate flow by summing its bay/group inbound flows over groups sharing `(ship, block, POD, size, period)`. This construction:

1. preserves arrival conservation by partitioning active groups;
2. satisfies cumulative storage after summing the original group/bay storage inequalities;
3. satisfies size and total handling after summing the original bay handling inequalities;
4. preserves distance and conflict contributions under aggregation;
5. allows the aggregate balance model to minimize over a relaxation of the full flows.

Therefore the POD–size objective cannot exceed the corresponding exact recourse objective. It is at least as strong as the size aggregate at the same fixed master point because it retains the POD-specific cumulative storage partition.

## Common valid-inequality profile

The `common` profile contains only:

- ship-size-period handling capacity lower bounds;
- minimum compatible open-bay counts;
- open-state monotonicity when new-container outbound demand is absent.

Diagnostics record profile, total/family constraint counts, and build time. No reserve-cover cut was added.

## Diagnostics

New result field `master_strengthening` records aggregate enabled state, level, variable/constraint counts, build time, valid-inequality state/profile, family counts, total count, and build time.

## Exact gate

- Instances: tiny, tiny_concentration, XS01, XS02, XS03.
- Methods: Direct, candidate-v1, V2A, V2B, V2C.
- Runs: 25/25.
- Planned solver budget: 1650 seconds.
- Actual runtime: 26.04 seconds.
- Result: PASS; every run OPTIMAL, all objectives agree, all solutions pass the independent checker, every returned LB is at most the optimum, and cut/oracle validation passes.
- Direct objectives match the persisted P1 exact evidence.
- Common inequalities preserve every fixed Direct optimum.
- POD–size bound is no weaker than size on all five fixed points; XS03 improves by about 154.61 objective units and the other four are equal within tolerance.

No XS fixture was resized and no time limit was extended. S01/M01/L01 screening was not run.

## Stage decision

P6A exact gate is complete and permits entry into P6B. Candidate-v2 is not frozen, and the final algorithm is not frozen.
