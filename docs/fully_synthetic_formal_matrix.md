# Fully synthetic formal experiment matrix

The current authoritative design is
`docs/specs/fully_synthetic_formal_matrix_v2.json`. It preserves the frozen
factor levels of V1 but creates every confirmatory bundle with the untouched
seeds `2000--2009`. V1 bundles and outcomes from seeds `1000--1009` are
historical/exploratory only.

## Frozen panels

| Panel | Unique bundles | Methods | Expected rows | Evidence role |
|---|---:|---:|---:|---|
| Scale × pressure | 80 | 5 | 400 | Computational scale and controlled pressure |
| Initial utilization | 30 | 2 | 60 | Yard-load sensitivity |
| Forecast error | 80 | 2 | 160 | Magnitude and mechanism sensitivity |
| Internal ablation | 10 reused | 4 | 40 | Candidate component contribution |
| Aggregate-LP ablation | 10 reused | 2 | 20 | Routing-screen contribution |
| Repair reachability | 20 | 3 | 60 | Mechanism diagnostics only |

There are 180 unique performance bundles and 20 mechanism bundles. The
performance panels contain 680 rows; the mechanism panel contains 60 rows, for
740 fully synthetic rows in total. Reused medium-ordinary bundles are not
counted as new data.

Scale × pressure uses small, medium, large and xlarge cases under `ordinary`
and `high_pressure` profiles and runs all five comparison methods. Frozen
per-cycle budgets are 20, 20, 60 and 120 seconds respectively. Initial
utilization uses medium cases at 25%, 55% and 65% and compares
`core_start` with `full_bottleneck`.

Forecast magnitude is evaluated at 0%, 10%, 20% and 30% with the `mixed`
mechanism. At 10%, `multiplicative`, `timing_shift`,
`booking_add_cancel`, `ship_correlated` and `mixed` are compared. The
10%-mixed instances are the same immutable 55%-utilization bundles, so the
panel has eight unique profiles rather than nine.

Internal ablation uses `core`, `core_start`, `core_start_impact` and
`full_bottleneck`. Aggregate routing compares `full_bottleneck` with
`full_bottleneck_no_aggregate`. The controlled `nearby` and `global` repair
cases use `full_direct`, `full_bottleneck` and `full`; they demonstrate path
reachability only and are never pooled with certified performance results.

## Inference and execution rules

- Comparisons are paired by seed within one prespecified scenario cell.
- Multiple cells produced from the same seed are not independent replicates
  and are never pooled into one Wilcoxon or confidence interval.
- Semi-synthetic and fully synthetic observations remain in separate paper
  tables.
- Failed, late or invalid algorithm rows remain in failure accounting; quality
  metrics use only valid paired outcomes, without selective reruns.
- Formal methods run sequentially with one solver thread on an exclusive host.
- No separate time-budget sensitivity panel is added: the scale panel already
  contains the prespecified 20/60/120-second budgets, and adding a second
  post-hoc time grid would expand the hypothesis family without addressing a
  missing primary claim.

No seed-`2000--2009` bundle was generated when this matrix was frozen.
