# Fully synthetic formal experiment matrix

The exact fully synthetic matrix is frozen in
`docs/specs/fully_synthetic_formal_matrix_v1.json`. This document explains the
division of evidence; the JSON file is authoritative for profile membership,
methods, counts, time budgets, indexes, and output paths.

## Frozen panels

| Panel | Bundles | Methods | Expected rows | Data status |
|---|---:|---:|---:|---|
| Scale x pressure | 80 | 5 | 400 | generated and integer-certified |
| Initial utilization | 30 | 2 | 60 | generated and integer-certified |
| Forecast error | 80 | 2 | 160 | 10 existing, 70 pending |
| Internal ablation | 10 reused | 4 | 40 | reuse medium-ordinary bundles |
| Aggregate-LP ablation | 10 reused | 2 | 20 | reuse medium-ordinary bundles |
| Repair reachability | 20 | 3 | 60 | generated mechanism cases |

The performance panels contain 680 result rows. The mechanism panel contains
60 separately reported rows, giving 740 expected rows in total. Reused
bundles are not counted twice when reporting the number of unique datasets.

## Forecast-error design

Forecast magnitude is evaluated at 0%, 10%, 20%, and 30% using the existing
`mixed` mechanism. Forecast mechanism is evaluated at a fixed 10% magnitude
using `multiplicative`, `timing_shift`, `booking_add_cancel`,
`ship_correlated`, and `mixed`. The 10%-mixed profile belongs to both
subpanels but is one immutable bundle per seed. Thus there are eight unique
profiles and 80 bundles, not nine profiles and 90 bundles.

All forecast profiles use the medium preset, 55% requested initial
utilization, ship-volume factor 1.0, a 20-second cycle budget, and seeds
1000--1009. Only candidate `full_bottleneck` and comparator `core_start` are
run because this panel tests forecast robustness rather than external
baseline fidelity.

The 10%-mixed profile already exists in
`synthetic_utilization_u055`. Seven profiles, or 70 certified bundles, remain
to be generated. Parameter values are symmetric around the existing 10%
baseline and are frozen without reference to algorithm outcomes.

## Evidence boundaries

- Scale and pressure use all five comparison methods.
- Utilization and forecast robustness compare candidate with `core_start`.
- Internal and Aggregate-LP ablations reuse the medium-ordinary scale cases.
- Repair-pressure bundles demonstrate path reachability only. They do not
  require a zero-shortage oracle certificate and must not be pooled with
  performance results.
- Semi-synthetic and fully synthetic rows remain in separate paper tables.
- A shared workstation must execute formal methods sequentially; the prior
  two-worker semi-synthetic attempt demonstrated that one solver thread does
  not by itself isolate model-construction memory.

No new bundle was generated when this matrix was frozen.
