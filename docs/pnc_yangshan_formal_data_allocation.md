# PNC--Yangshan formal experiment data allocation

## Current confirmatory boundary

The current TRE confirmatory design uses the previously frozen PNC--Yangshan
data design with a newly registered, untouched seed block `2000--2009`.
The authoritative machine-readable specification is
`docs/specs/pnc_yangshan_v3_confirmatory_instance_spec.json`; the complete run
order is `docs/specs/tre_v3_formal_execution_plan.json`.

Seeds `1000--1009` and all bundles or results derived from them belong to the
historical objective version. They may be used only as exploratory or
historical evidence and must never be merged into the current confirmatory
sample. No seed-`2000--2009` bundle existed when this design was registered.

PNC calls and export loading quantities provide the demand skeleton. The
Yangshan observations provide the joint `(POD, size, height)` calibration and
the `OF`-area virtual-yard calibration. PORT-MIS is supplementary provenance,
not the source of the current demand sample.

## Frozen semi-synthetic panels

| Panel | Bundles | Methods/profile variants | Expected rows | Role |
|---|---:|---:|---:|---|
| Central main | 10 | 5 methods | 50 | Primary external-validity comparison |
| Temporal, volume and yard robustness | 70 | 2 methods | 140 | Prespecified robustness cells |
| Operation-weight sensitivity | 10 reused | 2 methods × 3 alternatives | 60 | Robustness of the empirical business weights |
| DRA-RPM parameter sensitivity | 10 reused | 1 method × 6 alternatives | 60 | Baseline-parameter robustness |
| Total | 80 unique | — | 310 | Semi-synthetic evidence |

The central setting uses `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`,
and `dra_rpm`. Robustness and operation-weight panels compare
`core_start` with `full_bottleneck`. The DRA sensitivity changes only the
prespecified DRA-RPM parameters. Business-weight and frozen-DRA reference rows
are reused from the central main result rather than rerun.

The primary operation profile is fixed at distance `0.40`, balance `0.30`,
concentration `0.20`, and inbound/outbound conflict `0.10`. The alternatives
`equal_weight_ablation`, `weak`, and `strong_distance` are sensitivity cases,
not candidate specifications selected after observing formal outcomes.

## Data and pairing rules

- Each method in one comparison receives the identical immutable bundle.
- Seeds, hidden realizations, source windows and time budgets are paired only
  within the prespecified scenario cell.
- A seed reused across several cells is not an additional independent
  replicate; inference is performed separately within each cell (`n=10`).
- Semi-synthetic and fully synthetic results are reported in separate panels
  and are never pooled for confidence intervals or tests.
- Algorithm deadline, no-incumbent and validation failures remain in failure
  accounting. Quality metrics exclude invalid rows, and failed cases are not
  selectively rerun.
- Environmental contamination invalidates the affected whole batch, which is
  quarantined and restarted from zero on an exclusive host.

## Frozen data interpretations

- The primary May panel uses consecutive positive-export PNC calls and the
  operator-published loading quantity; discharge quantity is excluded.
- Temporal robustness uses representative March, April and June panels in
  addition to the May reference.
- Export-volume sensitivity uses factors `0.8`, `1.0`, and `1.2` on the same
  representative May call panel.
- Yard sensitivity uses `observed` and `high_pressure` alternatives around
  the same central calibration. It evaluates transfer sensitivity and does
  not claim that the virtual yard reproduces PNC's physical layout.
- Supported model values remain size `{20, 40}` and height `{STD, HIGH}`.
- Performance bundles require an independent zero-shortage integer-packing
  certificate. Oracle information is offline and invisible to the optimizer.

## Generation boundary

Instance generation is centralized in
`scripts/prepare_tre_v3_formal_instances.py`. The entry point first verifies
the clean exact tag, registered seeds, source files, controlled 120-row
preflight hashes, specifications, absent output root and authorization flag.
It refuses overwrite and partial resume. The default action is non-generating;
actual generation additionally requires both `--generate` and
`--confirm-open-formal-seeds`.

Formal execution is sequential, single-process and one solver thread per
method on an otherwise idle host. Sharded formal execution is disabled for
this design because solver-thread limits do not isolate Python/model-building
memory.
