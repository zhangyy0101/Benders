# PNC--Yangshan formal-data generation protocol

The formal division between semi-synthetic and fully synthetic experiment
families is frozen in `docs/pnc_yangshan_formal_data_allocation.md`. In
particular, the PNC--Yangshan data are used for the main external-validity,
March--June temporal, May export-volume, and yard-calibration panels.
Computational scale, controlled pressure, forecast-error, component-ablation,
and repair-reachability panels use fully synthetic data.

## Frozen model boundary

This protocol changes data construction only. It does not change the
mathematical model, constraints, candidate algorithm, external baselines, or
evaluation metrics.

The supported container group remains:

```text
(POD, size ∈ {20, 40}, height ∈ {STD, HIGH})
```

Yangshan height codes are transformed at the data boundary:

```text
HQ -> HIGH
PQ -> STD
MQ -> STD
```

No HQ/PQ/MQ state is introduced into the optimization model.

## Source roles

| Layer | Source | Used fields | Not claimed |
|---|---|---|---|
| Vessel skeleton | PNC operator berth schedule | vessel identity, carrier voyage, berth/departure, berth, operator, route | vessel IMO/GT or previous/next port |
| Export call volume | PNC operator berth schedule | observed loading quantity per call | container POD, size, or height |
| Independent validation | PORT-MIS | matched entry/departure, vessel identity, gross tonnage | selection of the PNC primary sample |
| Box attributes | Yangshan yard observations and declared-not-in-yard records | joint POD/size/height distribution | PNC route identity or exact voyage total |
| Yard calibration | Yangshan yard snapshots | slot capacity, bay/area structure, tier count, utilization | physical replication of the PNC yard |
| Forecast uncertainty | existing parameterized model mechanism | controlled bias and random error scenarios | calibration from Yangshan prediction files |

Yangshan voyage-prediction JSON and workbooks are excluded from calibration,
generation, validation labels, and formal experiments.

## Temporal split

- Calibration: May 8 and May 19, 2026.
- Held-out temporal validation: May 25, 2026.

Container IDs are deduplicated within and across calibration snapshots. The
latest state is retained, and a physical yard observation has priority over a
document record within the same snapshot.

The held-out snapshot is never used to fit generation probabilities.

## Yangshan attribute layer

The calibration output is a joint empirical distribution rather than three
independent marginal distributions:

```text
P(POD, size, height)
```

This preserves observed dependence between discharge port, size, and height.
Only 20/40-foot records with a recognized height code and nonmissing POD enter
the distribution. Yard-observed records must additionally be in an area whose
function contains `OF` and have a nonmissing export voyage ID
`IYC_EVOY_ID`. Records carrying only `IYC_IVOY_ID` are excluded. A record with
both IDs remains export-eligible because it has a defined outbound voyage.
`CNSHA` is excluded as an invalid POD for an export departing Yangshan.

The current temporal validation shows:

- calibration sample: 37,896 unique containers;
- held-out sample: 23,287 unique containers;
- size total-variation distance: 0.0008;
- height total-variation distance: 0.0003;
- POD total-variation distance: 0.2963;
- joint total-variation distance: 0.3045;
- 99.19% of held-out containers use a POD seen in calibration.

Size and height are temporally stable enough for direct empirical calibration.
POD is less stable and must therefore be generated with the documented
complete-voyage-profile bootstrap rule; rare PODs must not be silently
replaced with invented ports. The frozen formal allocation does not add a
separate POD-shift panel.

## Volume layer

Yangshan document and yard records provide only an observed lower bound per
voyage. They must not be used as exact voyage totals. Yangshan predictions are
also excluded.

The PNC operator's public berth schedule is the primary source for both the
vessel-call skeleton and call-level export volume. March--June contain 440 PNC
calls when each call is assigned by its PNC berth timestamp. Of these, 421
have a positive loading quantity and form the export-demand panel. The 19
zero-loading calls remain in the source audit but do not create model demand.
No call volume is fitted or imputed.

PORT-MIS no longer defines which calls enter the dataset. It independently
validates 428 of 440 PNC calls, including 419 of 421 positive-export calls.
All 428 PORT-MIS records match one-to-one. PORT-MIS gross tonnage and vessel
identifiers are supplementary fields only.

The model covers export containers only. Its formal baseline is the published
PNC loading quantity. PNC discharge quantity is retained solely for aggregate
source auditing and never enters demand, attribute disaggregation, or an
optimization instance. Scale sensitivity
uses 0.8, 1.0, and 1.2 times that observed quantity, with integer rounding.
PNC's stated annual capacity of five million TEU or more is used only as an
approximate aggregate reasonableness check. It is not divided among calls.

Loaded cargo tonnage from PORT-MIS must not be relabeled as container count.

The PNC call and export-volume panels are now built: May 2026 contains 111 PNC
source calls and 104 positive-export calls and is the primary panel. March,
April, and June are temporal-robustness panels. The integer export-attribute
layer is also built. It uses size-matched,
aggregate-balance-guided bootstrap sampling from complete observed Yangshan
voyage profiles. This retains realistic voyage sparsity (one to 12 PODs per
call, median six) while keeping monthly joint TV distance to the pooled
calibration distribution between 0.014 and 0.017.

## Yard layer

The generated yard remains a model-compatible virtual yard. Only areas whose
yard-function list contains the `OF` token are treated as export-capable.
Yangshan provides calibration targets, not a literal PNC layout:

- 84 areas are marked with an `OF` function, of which 74 appear in the slot
  snapshots;
- approximately 75,841--76,501 export-capable slot rows;
- approximately 2,789--2,819 export-capable bays;
- five tiers in the export-capable areas;
- export-area slot-row utilization of approximately 48.01%--57.25%.

The full observed-scale virtual yard contains 74 areas, 2,819 bays, and 76,341
integer box slots. With receiving inflow and vessel/old-inventory outflow both
represented, its maximum dynamic load ratio is 0.748. Capacity-relief and
high-initial-utilization sensitivities reach 0.731 and 0.812 respectively.
The more conservative all-boxes-overlap figures are retained only as sizing
upper bounds. These are virtual experimental templates, not claimed PNC yard
layouts.

Formal instances may scale the yard down while preserving the existing
capacity, size, height-lock, release, and other model constraints. Every scale
factor and rounding rule must be stored in the instance manifest.

## Required generation manifest

Every formal instance must record:

- PNC source period, terminal/facility mapping, and source hashes;
- Yangshan calibration version and source hashes;
- calibration/validation split;
- random seed;
- generated boxes per call;
- joint POD/size/height allocation;
- yard scale and target utilization;
- forecast-bias and forecast-noise scenario parameters;
- excluded attributes and unsupported records;
- code commit and protocol version.

## Readiness gates

A V2 instance may enter formal comparison only if:

1. every vessel call originates directly from the PNC operator schedule;
2. arrival precedes departure and call IDs are unique;
3. all groups use only 20/40 and STD/HIGH;
4. group probabilities sum to one;
5. generated export group totals equal PNC loading quantities;
6. yard capacity and compatibility constraints pass the existing validator;
7. the held-out Yangshan distribution report is attached;
8. prediction files are absent from source dependencies;
9. all three external baselines consume exactly the same instance;
10. the manifest contains source and output hashes.

## Reproduction

Build the observation-only Yangshan layer with:

```powershell
python scripts/build_yangshan_observed_calibration.py
```

Outputs are written below:

```text
local_results/protocol_v2_pnc_yangshan/yangshan_observed_calibration/
```

Build the PNC operator schedule and observed call-volume layer with:

```powershell
python scripts/fetch_pnc_work_moves.py
python scripts/build_pnc_observed_call_volumes.py
python analysis/plot_pnc_observed_volumes.py
```

Build the export-attribute layer with:

```powershell
python scripts/disaggregate_pnc_export_attributes.py
python analysis/plot_pnc_export_attributes.py
```

The virtual-yard templates and a first rolling pilot instance are built.
Reproduce the audited pilot and its integer packing certificate with:

```powershell
python scripts/assemble_pnc_yangshan_v2_pilot.py
```

The pilot uses two chronologically first positive-export calls in the May 2026
primary panel. It selects complete areas from the `capacity_relief_080`
OF-calibrated template and records the selection and scaling rule in the
bundle. A free-slot factor of 1.25 was rejected by the integer oracle as
overloaded; the audited pilot uses 3.0 and is certified feasible. This is a
data-instance scaling choice and does not alter the mathematical model.

The rolling preflight design was first assembled with seed 700 and then
repeated with seeds 701 and 702. It contains:

- May scale profiles with 2, 4, and 6 consecutive calls from the three
  predeclared candidate windows;
- March, April, and June temporal profiles with four consecutive calls and the
  same fixed set of 40 OF-calibrated areas;
- low, observed, and high PNC volume profiles on the same May medium calls and
  the same fixed yard;
- observed-full, capacity-relief, and high-pressure yard interpretations on
  the same May medium calls.

All 11 accepted bundles have zero-shortage integer packing certificates. The
complete ten-call May 8--10 source window returned `unknown` within the
60-second certificate budget and is excluded rather than treated as feasible.
The individual preflight indexes explicitly set
`formal_results_authorized=false`, because preflight bundles cannot themselves
be reported as formal results.

The representative May run exposed an implementation defect in bottleneck
preprocessing rather than a physical infeasibility. Equivalent sparse
indexing reduced selector time from 113.73 to 1.78 seconds. On the unchanged
bundle and seed, the initial optimized implementation completed all five
effective cycles at 60 seconds per cycle and reduced realized unplaced demand
from 1,441 boxes to 18. Later candidate version 1.4.7 passed all 24 declared
seed-700--702 scenario runs with zero final unplaced boxes. Proportional
subterminal sampling is therefore not required.

The data-family allocation and exact formal instance specification are frozen.
`core_start`, `kp_dos`, `kp_sg`, and `dra_rpm` have passed the unchanged
three-seed interface gate together with the candidate: all 120 rows completed
with zero final unplaced boxes and no validation or deadline failures.

The only authorized formal semi-synthetic generation entry point is:

```powershell
python scripts/prepare_pnc_yangshan_v2_formal_instances.py `
  --output-root local_results/protocol_v2_pnc_yangshan/formal_instances_v2
```

It consumes `docs/specs/pnc_yangshan_v2_formal_instance_spec.json`, requires a
clean Git commit and the audited five-method gate, refuses an existing output
root, and writes separate central-main and robustness indexes. The frozen
method partitions and expected result counts are recorded in
`docs/specs/formal_run_manifest_v2.json`.
