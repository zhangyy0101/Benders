# Dynamic bay-allocation Pilot report

> Status: **preliminary Pilot evidence; expansion stopped by the prescribed
> failure rule.** This report is not a formal statistical result and does not
> establish superiority of any method.

## A. Environment and version

- Git commit: `01912f380fa43e303de71197f50b78de4ea009e9`
- Branch: `dynamic-allocation-development`
- Saved-batch dirty state: `false`
- Problem protocol: `rolling-v3.2-dynamic-allocation-pilot`
- Python: `3.12.0` (`CPython`)
- Gurobi: `13.0.0`
- Threads: `1`
- MIP gap: `0.01`
- Main stability formulation: `epigraph_only`
- Release delay periods: `0`
- Weight/runtime profile SHA-256:
  `5af684bc3230161472ae247d484a30a37bf3f0bf97fa129ad3a43af7c4fc1e9e`

Two experiment-pipeline defects were found before freezing this Pilot commit:

1. a 0.2-second postprocessing reserve was smaller than observed extraction and
   validation time on `pilot_medium`; protocol v3.2 uses a common bounded 15%
   reserve (0.5--3 seconds) for every configuration;
2. long batches did not explicitly dispose completed Gurobi models and could
   terminate natively with `exit=-1`; v3.2 releases each model after its stage.

Neither correction changes the mathematical model, dependency parameters,
stability definition, or the `full_direct`/`full` ablation contract.

## B. Experiment matrices actually run

### Gate smoke

- Size: `pilot_small`
- Utilization: `0.25, 0.70`
- Modes: `multiplicative, booking_add_cancel`
- Error: `0.10`
- Configurations: `core_start, full_direct, full`
- Seeds: `0, 1`
- Time: 5 seconds per cycle
- Retained rows: 24

### Stage 1

- Same small scenarios, with seeds `0, 1, 2`
- Retained rows: 36

### Stage 2 partial diagnostic

- Size: `pilot_medium`
- Utilization: `0.55, 0.80`
- Configurations: `core_start, full_direct, full`
- Seeds: `0, 1, 2`
- Time: 10 seconds per cycle
- Completed submatrices:
  - error `0.10`, `booking_add_cancel`;
  - error `0.10`, `mixed`;
  - error `0.20`, `booking_add_cancel`.
- Omitted after the stop condition: error `0.20`, `mixed`.
- Retained rows: 54; this is explicitly a partial diagnostic matrix.

The 30-second matrix and seeds 3--4 were not run because the 10-second partial
matrix contained a wall-clock failure.

### Exact-formulation check

- Size: `pilot_small`, utilization `0.70`
- Mode/error: `booking_add_cancel / 0.10`
- Configurations: `core_start, full`
- Seeds: `0, 1`
- Time: 10 seconds per cycle
- Four epigraph rows and four exact big-M rows, stored separately from the main
  Pilot results.

## C. Process integrity

| Batch | Runs | Successful | Failed | Wall exceed | Validation failure |
|---|---:|---:|---:|---:|---:|
| Smoke | 24 | 24 | 0 | 0 | 0 |
| Stage 1 | 36 | 36 | 0 | 0 | 0 |
| Stage 2 partial | 54 | 53 | 1 | 1 | 0 |
| Exact check | 8 | 8 | 0 | 0 | 0 |
| **Retained total** | **122** | **121** | **1** | **1** | **0** |

- All retained source manifests record a clean working tree and the intended
  formulation, threads, MIP gap, and zero release delay.
- Every checked row satisfies
  `planned + fallback + unplaced = realized arrivals`.
- Requested and realized initial utilization differ by no more than one box
  divided by total capacity.
- The Stage 2 failure was a strict `wall_clock_time_limit_exceeded` for
  `utilization=0.55`, `booking_add_cancel`, `error=0.20`, `core_start`, seed 0.
  It had an incumbent and no validation failure.

Discarded debug batches from earlier protocol commits are not used in the
comparisons. They exposed the reserve and model-lifecycle defects described in
Section A.

## D. `full` versus `full_direct`

### Stage 1: 12 complete pairs

The two methods had identical realized unplaced quantity, fallback rate,
normalized operations score, stability cost, distance, conflict, and global-repair count.
`full` was 0.0009 seconds slower to first incumbent and 0.019 seconds slower in
total wall time on average. Thus propagation was active but produced no
operational gain on `pilot_small`.

### Stage 2 partial: 18 complete pairs

Mean paired difference (`full - full_direct`):

| Metric | Difference | Preliminary interpretation |
|---|---:|---|
| Realized unplaced | +0.0556 | slightly worse |
| Fallback rate | +0.000154 | slightly worse |
| First-incumbent time | -0.0542 s | faster |
| Normalized operations score | -0.000407 | slightly better |
| Total wall time | +0.340 s | slower |
| Stability cost | -1.167 | slightly better |
| Realized distance | -952.2 | better |
| Realized conflict | +0.104 | slightly worse |

The signs are mixed and the sample is incomplete. Current Pilot evidence does
not show a consistent marginal advantage for dependency propagation.

## E. `full` versus `core_start`

### Stage 1: 12 complete pairs

Both methods had zero unplaced and fallback. `full` reached its first incumbent
0.031 seconds earlier and slightly improved the normalized operations score and distance, but
used 12.15 seconds more total wall time because quality polish consumed nearly
the full remaining budget.

### Stage 2 partial: 17 complete pairs

Mean paired difference (`full - core_start`):

| Metric | Difference | Preliminary interpretation |
|---|---:|---|
| Realized unplaced | +1.294 | worse |
| Fallback rate | +0.00113 | worse |
| First-incumbent time | -0.900 s | faster |
| Normalized operations score | -0.0547 | better |
| Total wall time | +17.29 s | slower |
| Stability cost | +3.0 | worse |
| Realized distance | -6185.9 | better |
| Realized conflict | +2.013 | worse |

This indicates a quality/runtime trade-off, not dominance. In particular, the
global `core_start` MIP had no realized unplaced boxes among its successful
rows, while the local framework sometimes did.

## F. Dependency diagnostics

### Stage 1

- Propagation triggered in 12/12 `full` runs.
- Mean cycle trigger rate: `0.3333`.
- Total pressure-propagated pairs: `67`.
- Release-opportunity pairs: `0`.
- Mean dependency edges per cycle: `11.11`.
- Mean graph time per cycle: `0.00037` seconds.

### Stage 2 partial

- Propagation triggered in 18/18 `full` runs.
- Mean cycle trigger rate: `0.75`.
- Total pressure-propagated pairs: `438`.
- Total release-opportunity pairs: `328`.
- Mean propagated pairs per cycle: `10.64`.
- Mean dependency edges per cycle: `105.94`.
- Mean graph time per cycle: `0.00261` seconds.

The graph overhead is negligible and propagation is demonstrably active. Its
effect on decisions is nevertheless small and inconsistent relative to
`full_direct`, so activation alone is not evidence of value.

## G. Repair, polish, and exact-formulation evidence

- Adaptive repair and global repair were never triggered in retained Stage 1
  or Stage 2 rows. These instances therefore do not validate the repair chain.
- Quality polish trigger rate was `1.0` in Stage 1 and approximately `0.90` in
  Stage 2 enhanced configurations.
- Quality polish improvement rate was `0.0` in every retained batch.

This is direct Pilot evidence that the current polish trigger spends time
without improving the lexicographic incumbent.

For the exact check, all four epigraph/exact pairs had identical canonical
shortage, cancellation, discretionary cancellation, block reallocation,
stability cost, and normalized operations score. Epigraph used 65--110 fewer binary
variables (mean reduction 86.5). It was not faster in the `full` runs because
quality polish consumed the budget. Maximum raw auxiliary epigraph slack was
50, while accepted solutions were corrected and validated using canonical
values. The rolling CSV does not store full reservation-plan hashes, so this
check does not claim complete bay-plan equality; the unit formulation test
separately confirms reservation equality on its controlled snapshot.

## H. Scenario discrimination

- `pilot_small` has almost no outcome discrimination; it is suitable for smoke
  and mechanism checks only.
- `pilot_medium` creates meaningful differences in first-incumbent time,
  normalized operations score, distance, fallback, and unplaced quantity.
- Utilization `0.80` with `mixed / error=0.10` was the strongest observed
  `full` versus `core_start` separator: `full` was faster to an incumbent and
  better on predicted normalized operations/distance, but averaged 7.33 more realized
  unplaced boxes in the three pairs.
- Error `0.20 / booking_add_cancel` produced the sole retained strict
  wall-clock failure and mixed `full`/`full_direct` effects.
- `mixed / error=0.20` and the 30-second limit remain untested.

## I. Recommendations before formal experiments

1. **Do not yet freeze `full` as the paper's dominant method.** Keep it as a
   candidate because propagation is active and cheap, but first test its edge
   and path thresholds on separate tuning seeds. Current marginal evidence is
   mixed.
2. **Disable quality polish in the next tuning Pilot, or require a stronger
   trigger.** Its trigger rate is near 100% and its improvement rate is zero.
   Retain the current configuration as an ablation reference.
3. Use 5 seconds only for smoke. Treat 10 seconds as a short-budget stress
   setting, not yet as the sole formal limit. Do not claim anything about 30
   seconds until a fresh Pilot completes it.
4. Retain utilization levels `0.55` and `0.80`; include a low-utilization
   baseline only for calibration, not as the main discriminator.
5. Retain both booking-add/cancel and mixed uncertainty. Run the missing
   `mixed / error=0.20` cell first on independent tuning seeds.
6. Use five independent tuning seeds, disjoint from formal test seeds. After
   freezing settings, use at least ten formal seeds per scenario.
7. Run sensitivity analysis for dependency edge/path thresholds and a polish
   on/off ablation. Do not tune them on the retained Pilot seeds again.
8. Add checkpoint/resume or per-run atomic CSV append before long formal
   batches so one native/process failure cannot discard a whole matrix.

After those changes, rerun a bounded Stage 2 Pilot before launching formal
large-scale experiments.

## J. Limitations and non-claims

- Release delay was fixed at zero and was not tested.
- Synthetic forecasts and demand still require calibration with real terminal
  data.
- This Pilot is incomplete and does not constitute formal statistical evidence.
- Gurobi multiobjective bound and gap may remain unavailable (`None`).
- Outbound conflict remains a block-level proxy rather than a detailed
  equipment-scheduling model.
- Capacity still follows whole-vessel release.
- The missing Stage 2 cell, absent 30-second batch, and three-seed sample prevent
  formal significance claims.
