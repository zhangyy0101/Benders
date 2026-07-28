# PNC--Yangshan formal experiment data allocation

## Status and scope

This document freezes which formal experiment families use the
PNC--Yangshan semi-synthetic data and which use fully synthetic data. It does
not yet freeze the individual seed-1000--1009 bundle hashes; those hashes can
only be recorded after the formal bundles are generated and certified.

This allocation supersedes the historical Sinsundae/PORT-MIS formal-matrix
design wherever that design treated PORT-MIS-derived demand as the primary
semi-synthetic dataset. PORT-MIS now supplements PNC vessel information and
provides independent source validation only.

The mathematical model, supported attributes, constraints, candidate
algorithm, external baselines, runtime boundary, and common physical-recovery
rule are unchanged.

## Frozen allocation

| Formal experiment family | Dataset | Formal role |
|---|---|---|
| Main external-validity comparison | PNC--Yangshan semi-synthetic | Test the five methods under real PNC calls and export loading quantities, Yangshan-calibrated joint box attributes, and an OF-calibrated virtual yard |
| Temporal robustness | PNC--Yangshan semi-synthetic | Compare representative consecutive-call panels from March, April, May, and June 2026 under the same yard interpretation |
| Export-volume sensitivity | PNC--Yangshan semi-synthetic | Apply 0.8, 1.0, and 1.2 factors to the observed PNC export loading quantity in one representative May panel |
| Yard-calibration sensitivity | PNC--Yangshan semi-synthetic | Compare `observed`, `capacity_relief`, and `high_pressure` Yangshan-calibrated yard interpretations on the same May calls and box demand |
| Computational scale and efficiency | Fully synthetic | Control vessel count, box count, yard size, and horizon to compare runtime, solution quality, and scalability |
| High-pressure and extreme scenarios | Fully synthetic | Construct controlled congestion and capacity-pressure conditions that need not occur in the observed panels |
| Forecast-error sensitivity | Fully synthetic | Vary the existing model forecast-bias, noise, timing-shift, and booking-add/cancel mechanisms without confounding changes in calls or yard calibration |
| Internal component ablation | Fully synthetic | Hold all data factors fixed and isolate the contribution of individual algorithm components |
| Repair-mechanism reachability | Fully synthetic | Use controlled `nearby` and `global` repair-pressure cases for mechanism diagnostics only |

Both data families are required. Semi-synthetic results support external
validity; fully synthetic results support controlled computational and
mechanism claims. Results from the two families must be reported in separate
tables or clearly separated panels and must not be pooled into one sample.

## Semi-synthetic formal panels

### Main external-validity panel

- Source calls: consecutive positive-export PNC calls from the May 2026
  primary panel.
- Call volume: the PNC operator-published loading quantity; discharge
  quantity is excluded.
- Box attributes: the Yangshan-observed joint distribution over
  `(POD, size, height)`, restricted to export-qualified records.
- Supported model values: size in `{20, 40}` and height in `{STD, HIGH}`.
- Yard: model-compatible virtual yard calibrated only from Yangshan areas
  whose function includes `OF`.
- Methods: `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`.
- Seeds: held-out formal seeds 1000--1009, paired across all five methods.

### Temporal robustness panel

- Months: March, April, May, and June 2026.
- Each month uses a representative consecutive-call PNC panel.
- The layout, yard interpretation, volume rule, attribute generator, forecast
  setting, and method parameters are held fixed.
- This is a temporal robustness panel, not a computational scale panel.
- Primary methods: `core_start` and `full_bottleneck`.

### Export-volume sensitivity panel

- Factors: `0.8`, `1.0`, and `1.2`.
- The factor is applied only to observed PNC export loading quantities.
- Calls, yard, attribute-generation rule, forecast setting, and random seed
  remain paired.
- It is run on one representative May panel and is supplementary rather than
  the principal external-validity result.
- Primary methods: `core_start` and `full_bottleneck`.

### Yard-calibration sensitivity panel

- Profiles: `observed`, `capacity_relief`, and `high_pressure`.
- The same representative May calls, PNC export quantities, generated box
  attributes, forecast realization, and seed are retained.
- Only the OF-calibrated yard interpretation changes.
- This panel evaluates transfer sensitivity to the virtual-yard assumption;
  it does not claim that the virtual yard is the physical PNC layout.
- Primary methods: `core_start` and `full_bottleneck`.

### Excluded semi-synthetic use

- The former 2/4/6-call development scale cases remain preflight evidence and
  do not form the formal computational-scale experiment.
- Yangshan prediction files remain excluded.
- Yangshan observed documents and yard snapshots do not replace PNC call
  totals.
- PORT-MIS does not select the PNC sample and does not generate box demand.
- No extra POD-shift formal panel is introduced by this allocation.

## Fully synthetic formal panels

### Computational scale and efficiency

Use the existing reproducible synthetic generator for small, medium, large,
and xlarge cases. Vessel count, box volume, yard size, horizon, and pressure
are controlled explicitly. These cases provide the primary evidence on
runtime growth, solution quality under scale, and computational extensibility.

### Capacity pressure and extreme conditions

Use the frozen `ordinary` and `high_pressure` targets and independently
oracle-certify every accepted instance. Boundary or structurally overloaded
instances must be labelled as stress evidence and must not be pooled with
zero-shortage feasible cases.

### Forecast-error sensitivity

Use the existing forecast-error mechanisms already present in the model.
Calls and physical capacity remain fixed while forecast magnitude or mode is
varied. Yangshan prediction files are not used to calibrate these errors.

### Internal ablation and repair reachability

Component ablation uses `core`, `core_start`, `core_start_impact`, and
`full_bottleneck`; `full_bottleneck_no_aggregate` is used only for the
aggregate-routing ablation. Controlled `nearby` and `global` pressure cases
are mechanism diagnostics and are reported separately from performance
claims.

## Pairing and reporting rules

1. Every method in a comparison consumes the identical immutable bundle.
2. Random seeds, hidden realizations, source windows, and time budgets are
   paired within a panel.
3. The main semi-synthetic panel uses all five frozen comparison methods.
4. Semi-synthetic robustness panels may use `core_start` and
   `full_bottleneck`; the three external baselines are required on the central
   main setting, not on every sensitivity point.
5. Fully synthetic scale comparisons use the method set declared in the
   formal run manifest; internal ablations and mechanism diagnostics remain
   separate.
6. Semi-synthetic and fully synthetic observations are never pooled for
   averages, confidence intervals, or significance tests.
7. Formal seeds 1000--1009 remain unopened until the clean tested commit and
   final `--check-only` generation gate are complete.

## Next gate

The data-family allocation, exact formal instance specification, and formal
run manifest are frozen. The unchanged `core_start` and three external
baselines have passed the seed-700--702 interface preflight. The remaining
mechanical gate is a clean tested commit followed by the non-generating
`--check-only` readiness command.
