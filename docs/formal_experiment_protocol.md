# Formal experiment protocol

Preflight status: passed on 2026-07-23 with reserved seeds 700--702. All 36
requested rows completed under the freeze-candidate code with no wall-clock,
validation, or no-incumbent failure. These dirty-worktree preflight artifacts
are development gates, not publication results; formal runs still require a
clean tagged commit.

## Status and immutable identifiers

This document defines the publication-oriented interface before public-data
calibration and final benchmark execution.  It does not change the mathematical
model or the solution stages.

- Problem protocol: `rolling-v4.1-bottleneck-repair-freeze-candidate`
- Algorithm: `bottleneck-guided-progressive-repair-v1.0`
- Result schema: `rolling-results-v1`
- Candidate core configuration: `full_bottleneck`

The candidate core is MIP start, direct Impact Region, granularity-guarded
minimum pair-block repair, unrestricted global recovery, and independent
execution validation. Fixed-ratio Progressive Repair (`full_direct`) is a
repair-controller ablation. Reactive dependency propagation (`full`) is
historical development evidence and is not part of the candidate core.
Quality polish remains disabled.

Any change to constraints, objective priorities, stage triggers, domain
expansion, or validation semantics requires a new problem or algorithm version.
Any incompatible CSV-field change requires a new result-schema version.

## Experiment phases and data separation

The seed sets are disjoint and stored in `config.py`.

- Development: seeds `100, 101, 102` and arbitrary smoke-test seeds.  These may
  guide implementation and tuning.
- Preflight: seeds `700, 701, 702`.  These exercise the formal interface on a
  small representative matrix and may still guide one final algorithm change.
- Formal: held-out seeds `1000, 1001, 1002, 1003, 1004`.  These must not guide
  algorithm selection or parameter tuning.

`run_experiments.py --experiment-phase preflight` and `formal` reject seeds
outside their phase set.  A formal batch also rejects a dirty or unidentifiable
Git worktree.  Use a tagged clean commit for every reported batch.  If a method
is modified after inspecting formal outcomes, those outcomes become exploratory;
increment the version and evaluate on a new held-out set.

## Metrics and terminology

The third lexicographic objective is a dimensionless score, not a monetary
cost.  New artifacts use `normalized_operations_score`.  The score is the
weighted sum of four normalized terms:

1. ship/POD/bay support concentration;
2. block-utilization deviation over time;
3. forecast inbound transport distance;
4. forecast inbound/outbound overlap.

Every cycle exposes the raw value, normalized value, and normalization scale
for all four terms.  Batch CSV files report their cycle means together with
`mean_cycle_normalized_operations_score`.  Raw components are not added into a
second aggregate because their units differ.  The weight profile is stored in
every row and manifest.  Legacy rolling-v3.x CSV files can still be summarized;
their `mean_cycle_predicted_operations_cost` field is interpreted only as an
alias for the normalized score.

Predicted objective diagnostics and realized execution KPIs must be reported
separately.  The principal realized KPIs are:

- unplaced quantity and rate;
- fallback quantity and rate;
- transport distance;
- inbound/outbound conflict;
- bays per ship/POD;
- peak block utilization and utilization deviation;
- discretionary revision rate and stability cost.

Runtime reporting uses end-to-end wall time per rolling cycle.  Solver time,
preprocessing time, first-incumbent time, node count, repair stages, and final
stage gap are secondary diagnostics.  A missing multiobjective Gurobi gap is
reported as null and must not be converted to zero.

## Required comparison methods

The minimum internally comparable matrix is:

- `core`: unrestricted Global MIP;
- `core_start`: unrestricted Global MIP with the common MIP start;
- `core_start_impact`: MIP start and direct Impact Region only;
- `full_bottleneck`: candidate complete algorithm.

`full_direct` appears only in the repair-controller ablation and `full` only in
the historical dependency ablation. Pressure instances verify stage
reachability and must not be pooled with normal-instance performance.
One adapted published yard-allocation or rolling-repair method should be added
after its model-to-model mapping is fixed.  It must share the same information
boundary, rolling windows, time limit, threads, objective weights, and
independent validator.

## Preflight gate

Before the complete formal matrix, run the four required methods on three
representative profiles with all preflight seeds:

1. small, 10% booking-add/cancel error, 55% initial utilization;
2. medium, 20% mixed error, 55% initial utilization;
3. large, 20% mixed error, 80% initial utilization.

Use identical time limits within each profile.  Recommended initial limits are
20 seconds per cycle for small and medium and 60 seconds for large.  This is a
36-row gate rather than a full Cartesian sweep.

The gate passes only if:

- every requested row and manifest is complete;
- every accepted core solution passes independent validation;
- there are no unreported wall-clock overruns or numerical feasibility errors;
- the candidate core has no systematic reliability regression against Global
  MIP or Impact Region;
- Progressive Repair is reachable on pressure cases, while routine performance
  claims use only normal cases;
- the component means reproduce the stored normalized score under the recorded
  weights within numerical tolerance.

No requirement is imposed that one method win every KPI.  Comparisons are
paired by instance profile and seed.  Report mean, standard deviation, median,
95% confidence interval, paired difference, and win/tie/loss counts; use a
paired significance test only when the sample size and nonzero differences make
it meaningful.

## Formal instance families

The final study should keep three families distinct:

1. public-data-calibrated semi-synthetic cases for external validity;
2. reproducible synthetic scale and utilization cases for computational limits;
3. controlled pressure cases for repair-mechanism verification.

Generator code, source-to-field mapping, distributions, seeds, and generated
instance files must be archived.  The existing Pilot cases remain development
evidence and are not reused as the sole formal evidence.
