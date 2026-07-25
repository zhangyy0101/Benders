# Formal experiment protocol

The version 1.1 preflight passed on 2026-07-23 with reserved seeds 700--702.
Those 36 rows are retained as historical development evidence. Version 1.2
then used the protocol-authorized final preflight adjustment to add a
state-based high-pressure route. Version 1.3 replaces that empirical route
with a lead-aware aggregate-LP screen. Its oracle-certified preflight passed
on 2026-07-24 from the clean tag
`rolling-v4.3-aggregate-v1.3-preflight-rc1`; formal seeds remain uninspected.
Independent packing certification proved that the former 80% large development
profile can be structurally overloaded (seed 100 has an integer-shortage lower
bound of 816 boxes). It is therefore historical stress evidence, not a valid
zero-shortage algorithm benchmark.

## Status and immutable identifiers

This document defines the publication-oriented interface before public-data
calibration and final benchmark execution.  It does not change the mathematical
model or the solution stages.

- Problem protocol: `rolling-v4.3-oracle-certified`
- Algorithm: `lead-aware-aggregate-lp-screened-repair-v1.3`
- Result schema: `rolling-results-v6`
- Packing oracle: `full-horizon-integer-packing-v1`
- Candidate core configuration: `full_bottleneck`
- External baseline protocol: `adapted-literature-baselines-v1`
- Preprocessing implementation: `lead-aware-aggregate-lp-sparse-indexed-v3`

The candidate core computes a lead-aware forecast buffer and evaluates nested
`N0`--`N2` domains with a continuous block-size-height-period capacity LP.
When no restricted domain covers the buffered common demand scale, it runs the
unrestricted Global MIP with the common MIP start. Otherwise it starts with the
exact integer `N0` Impact Region and lets an integer shortage incumbent trigger
the granularity-guarded minimum pair-block repair. The aggregate LP is a route
screen, not an integer-feasibility claim. Stage solutions are protected by one
strict lexicographic incumbent key: predicted shortage, stability cost, then
normalized operations score. Independent execution validation remains
mandatory. Fixed-ratio Progressive Repair (`full_direct`) is a controller
ablation; reactive dependency propagation (`full`) is historical development
evidence. Quality polish remains disabled.

Any change to constraints, objective priorities, stage triggers, domain
expansion, or validation semantics requires a new problem or algorithm version.
Any incompatible CSV-field change requires a new result-schema version.

The packing oracle is an offline data-certification tool, not an algorithm
component and not part of timed candidate execution. It uses realized integer
arrivals, realized whole-ship release periods, old-vessel release periods, bay
size, bay capacity, and the no-mixed-height rule. A zero-shortage incumbent
certifies structural feasibility. A positive shortage lower bound certifies
structural overload. A time-limited run with neither certificate is recorded as
`unknown` and must never be relabeled infeasible.

## Experiment phases and data separation

The seed sets are disjoint and stored in `config.py`.

- Development: seeds `100, 101, 102` and arbitrary smoke-test seeds.  These may
  guide implementation and tuning.
- Preflight: seeds `700, 701, 702`.  These exercise the formal interface on a
  small representative matrix and may still guide one final algorithm change.
- Formal: held-out seeds `1000`--`1009`. These must not guide algorithm
  selection or parameter tuning.

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
The required external literature families are:

- `kp_dos` and `kp_sg`, adapted from Kim and Park (2003);
- `dra_rpm`, adapted from Xuan et al. (2024).

Their model-to-model mapping, source inconsistencies, fidelity status, neutral
bay decoder, and frozen development parameters are specified in
`docs/external_baseline_adaptation_protocol.md`. They share the same
information boundary, rolling windows, end-to-end time limit, common hard
constraints, realized execution path, objective evaluator, and independent
validator. Candidate-only MIP starts and repair stages are not shared.

The external-baseline methods remain unchanged by later candidate-controller
development and still share the common information boundary and evaluator.

`full_bottleneck_no_aggregate` is a dedicated controller ablation. It retains
the exact integer model, MIP start, direct Impact Region, bottleneck selector,
Progressive Repair, and global recovery of `full_bottleneck`, but disables the
aggregate-LP ladder and uses the former state-based route. It is not a
candidate method and is not included in the main seven-method table.

Version 1.1 replaces repeated full-table scans in residual-capacity and
height indexing with sparse bay/pair indexes. When dependency propagation is
disabled, it also skips the physical-score pass that would be overwritten
immediately by frozen-plan-baseline scores. The score equations, candidate
ordering and mathematical model are unchanged. Pre/post deterministic hashes
for physical capacity, baseline residual capacity and all pair-block scores
match exactly on the development small and large instances.

Version 1.2 leaves the mathematical model, objective priorities, candidate
scores, and external baselines unchanged. Its pressure diagnostic uses only
forecast load, vessel presence, physical capacity, and visible remaining
demand. Severe-pressure snapshots skip score construction and enter the
unrestricted Global MIP immediately. The threshold was finalized on reserved
preflight seeds; formal seeds 1000--1009 remain uninspected.

Version 1.3 also leaves the bay-level mathematical model and objective
priorities unchanged. It removes the two empirical routing thresholds from the
candidate decision and uses a timed aggregate LP relaxation instead. Its
lead-aware buffer uses only the declared error level and visible forecast
timestamps. Passing the relaxation selects the local exact-and-repair path;
failure to pass through `N2` selects Global. Development trials used seeds
100--102 only. The clean tagged preflight used seeds 700--702 and passed the
gate below; the version is frozen for formal runs.

### Version 1.3 preflight result

The ordinary/tight gate contained 72 paired rows:

- three scale profiles, three reserved seeds, two oracle-certified feasible
  pressure classes, and four required internal methods;
- 72/72 successful rows, zero independent-validation failures, zero numerical
  feasibility failures, and zero unreported per-cycle wall-clock overruns;
- all 18 candidate rows were produced from clean, identifiable Git state;
- against unrestricted Global MIP, candidate shortage win/tie/loss was
  5/9/4 and the aggregate shortage difference was one box over all 18 paired
  cases;
- against Global MIP with the common start, shortage win/tie/loss was 5/8/5;
- candidate end-to-end time was lower in 16/18 comparisons with Global and
  15/18 comparisons with Global plus start;
- direct Impact Region accumulated much larger shortage on tight medium and
  large cases, confirming the need for route screening and exact recovery.

A separate six-row pressure-mechanism gate also passed validation. Bottleneck
repair was reached in every row and selected 2--9 pair-blocks. These mechanism
rows are not pooled with the ordinary/tight performance rows. Across the 18
ordinary/tight candidate rows, the aggregate screen evaluated 120 rolling
cycles and selected `N0`, `N1`, `N2`, and Global 57, 16, 2, and 45 times,
respectively. Its total measured overhead was 20.18 seconds, or 0.161 seconds
per rolling cycle on average.

## Preflight gate

Before the complete formal matrix, run the four required methods on
oracle-certified ordinary-feasible and tight-feasible members of three scale
profiles with all preflight seeds:

1. small, 10% booking-add/cancel error;
2. medium, 20% mixed error;
3. large, 20% mixed error.

Use identical time limits within each profile. The frozen limits are 20
seconds per cycle for small and medium, 60 seconds for large, and 120 seconds
for xlarge. Initial
utilization is a recorded scenario factor, not a surrogate feasibility label.
Certified-overloaded members are reported separately as mechanism/stress cases
and are not pooled into zero-shortage performance claims.

Every certified case separates admission cycles from three terminal execution
cycles. The terminal cycles admit no additional vessels and execute the
remaining 72-hour receiving tails, so `realized_arrivals` covers the same demand
that the full-horizon oracle certifies. Oracle construction time is recorded
separately and excluded from timed online solution performance.

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

### Immutable instance-bundle workflow

Formal generation and timed solution are separate commands. An instance is
first serialized as `rolling-instance-bundle-v1`. The serializer preserves
tuple-key dictionaries, tuples, and sets, and records both the case SHA-256 and
the exact bundle-file SHA-256. The bundle stores the instance family, profile,
seed, source window, source/calibration hashes, and frozen per-cycle time
budget. Result schema `rolling-results-v6` repeats these identities in every
row.

`scripts/prepare_formal_instances.py` creates or verifies bundles.
It also writes `rolling-instance-index-v1`, containing the expected bundle and
case hashes. `scripts/run_formal_matrix.py` requires that index in formal mode,
verifies every file against it, and atomically checkpoints a common CSV and
manifest. A formal run rejects:

- seeds outside `1000`--`1009`;
- a dirty or unidentifiable Git state;
- a command-line time override;
- a provisional public-data source;
- a main matrix other than the frozen seven methods;
- a changed bundle, case hash, metadata record, or resume matrix.

The frozen main methods are `core`, `core_start`, `core_start_impact`,
`full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`. All seven see the same
bundle and the same per-cycle wall-clock budget.

The fixed PORT-MIS entry-date windows are deliberately non-overlapping:

| Profile | Inclusive dates | Yard | Limit/cycle |
|---|---:|---:|---:|
| `public_small` | 2025-07-04--2025-07-06 | 8 blocks × 6 bays | 20 s |
| `public_medium` | 2025-07-12--2025-07-18 | 16 blocks × 8 bays | 60 s |
| `public_large` | 2025-07-20--2025-07-30 | 20 blocks × 10 bays | 120 s |

Each profile keeps all calls and calibrated groups whose entry date falls
inside the inclusive window; calls are never truncated to reach a target size.
The yard layout remains semi-synthetic and is fixed by profile rather than
retuned after seeing method performance.

## PORT-MIS public-data pilot gate

The bounded PORT-MIS acquisition pilot passed on 2026-07-23 without changing
the mathematical model or frozen algorithm.  It queried Busan vessel calls
from 2025-07-01 through 2025-07-30, retained final declarations for full
container ships (`vsslKndCd=41`), and used the Sinsundae berth group as the
first single-terminal proxy.

The primary sample contains 200 inbound calls by 91 unique vessels across five
berths.  Callsign, entry/departure time, gross tonnage, facility, previous port,
and next port are complete in the retained sample.  No source business-key
duplicates or reversed times remain.  The 27 complete daily rolling cycles
contain 3--9 newly admitted vessels in each 72--96 hour slice (median 6).

The Busan Port Authority identifies Sinsundae as a five-berth container
terminal operated by Busan Port Terminal Co., Ltd. (BPT).  Inbound and outbound
facility fields are retained separately: calls that move between different
terminal clusters are marked `MULTI_TERMINAL` and excluded from the primary
single-yard proxy.  Cargo tonnage is not interpreted as container moves, and
next port is not interpreted as a per-container POD.

`scripts/prepare_portmis_pilot.py` reproduces the bounded acquisition audit.
Its guest-accessible table endpoint is undocumented and remains a pilot route,
not the publication extraction contract.  Before formal instance generation,
archive a fixed official PORT-MIS table export, its query metadata and hashes;
then freeze the separate semi-synthetic rules for box quantities, attributes,
forecast trajectories, yard state, and bay layout.

The infrastructure enforces that distinction. A publication-ready source
manifest must declare `publication_ready: true` and
`pilot_only_undocumented_endpoint: false`, and list the SHA-256 of every raw
source file. The calibration manifest must list the SHA-256 of every derived
artifact and its audit must have status `PASS`. The current July pilot snapshot
verifies byte-for-byte but deliberately fails the formal publication-ready
gate; it remains usable for development and integration tests only.

A minimal publication source declaration has this shape; the actual query and
all raw files must be archived beside it:

```json
{
  "schema": "portmis-fixed-source-snapshot-v1",
  "publication_ready": true,
  "pilot_only_undocumented_endpoint": false,
  "official_data_page": "https://www.data.go.kr/data/15006353/openapi.do",
  "extraction_method": "fixed official export or documented OpenAPI",
  "query": {
    "port_code": "020",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD"
  },
  "raw_files": {
    "raw_inbound.json": {"sha256": "<64 hexadecimal characters>"},
    "raw_outbound.json": {"sha256": "<64 hexadecimal characters>"}
  }
}
```

## Capacity-anchored demand calibration

The first demand-layer protocol is frozen as `portmis-demand-v1` and is
implemented independently in `scripts/calibrate_portmis_demand.py`.  It does
not change the mathematical model or optimization algorithm.

An anonymously reproducible Sinsundae monthly actual-throughput series was not
found.  The detailed Chain Portal statistics API returns an authentication-token
requirement, and the public BPT pages do not provide a stable historical
per-vessel workload query.  The protocol therefore uses the following
transparent aggregate anchors instead of inventing a terminal-month actual:

- official Sinsundae design capacity: 2,236,000 TEU/year;
- official 2025 North Port total: 6,244,000 TEU;
- official 2025 North Port import/export: 4,056,000 TEU.

For a source window of \(D\) days, the baseline targets are

\[
C_D = 2{,}236{,}000D/365,
\qquad
E_D = \operatorname{round}\left[
C_D u \left(\frac{4{,}056}{6{,}244}\right)s
\right],
\qquad
B_D = \operatorname{round}\left[\frac{E_D}{1+p_{40}}\right].
\]

Here \(u=0.85\) is the assumed capacity utilization, \(s=0.50\) is a symmetric
split of the published combined import/export volume into export volume, and
\(p_{40}=0.65\) is the semi-synthetic 40-foot share.  These are generator
assumptions, not observed Sinsundae parameters.  The resulting integer box
target is allocated to calls proportionally to real gross tonnage, subject to
80--450 boxes per call.  Gross tonnage is only a relative vessel-capacity
proxy.  PORT-MIS inbound and outbound loaded-cargo tonnage is never used,
because neither field is the export-box flow represented by the model.

The POD count is
\(\min(12,\max(1,\lceil B_j/100\rceil))\) for call \(j\).  POD shares,
container size, and container height are semi-synthetic integer attributes.
The baseline enforces the exact aggregate 40-foot share, assigns 55% of
40-foot boxes to `HIGH`, and does not generate 20-foot high-cube boxes.
Every group table must reconcile exactly to the per-call box and TEU totals.

On the 2025-07-01--2025-07-30 pilot, the baseline produces 30,750 export boxes
and 50,738 TEU across 200 calls.  Per-call boxes have min/median/p90/max
109/139/188.1/260, and POD counts range from 2 to 3.  These figures describe
the calibrated semi-synthetic layer, not observed BPT throughput.

The paper and released metadata must preserve this information boundary:

- real: call identity, vessel identity, entry/departure time, berth, gross
  tonnage, previous port, and next port;
- semi-synthetic: export box total, per-container POD, size, height, forecast
  trajectory, initial yard state, and bay layout;
- prohibited interpretation: next port as container POD, or reported cargo
  tonnage as container moves.

Formal robustness uses one-factor-at-a-time sensitivity around the baseline:
\(u\in\{0.70,0.85,1.00\}\), \(s\in\{0.45,0.50,0.55\}\),
\(p_{40}\in\{0.55,0.65,0.75\}\), and high-cube share among 40-foot boxes in
\(\{0.40,0.55,0.70\}\).  These are not combined into an unnecessary full
Cartesian product.  Larger 1,000--2,000-box vessel calls, if needed for the
computational scale family, must be introduced as a separately labelled
synthetic large-vessel stratum rather than being forced into this observed
small/medium-vessel pilot.

## Calibrated rolling integration gate

`scripts/run_portmis_end_to_end.py` maps the calibrated demand layer to the
unchanged rolling-case contract.  The mapping is frozen as
`portmis-rolling-adapter-v1`:

- PORT-MIS entry time becomes vessel ETA;
- the receiving window begins exactly 72 hours before ETA;
- PORT-MIS departure time becomes the deterministic planned and realized
  release proxy for this integration test;
- the real berth affects only the ship-to-block distance preference;
- calibrated POD/size/height boxes form the booking baseline and are
  distributed over the twelve 6-hour receiving periods;
- the yard layout, initial inventory, forecast trajectory, and hidden
  realization remain semi-synthetic.

The adapter does not change the 6-hour time buckets, 24-hour rolling cycle,
96-hour lookahead, mathematical constraints, objective, or
`full_bottleneck` algorithm.

The bounded integration smoke test selects the first three calibrated calls.
It has five blocks, 30 bays, 1,500 box slots, 300 initially locked boxes,
415 calibrated booking boxes, six attribute groups, and a 10% multiplicative
forecast-error trajectory.  The hidden realization contains 414 boxes.

All five rolling cycles completed: four invoked the optimizer and the fifth
closed the remaining vessel lifecycles.  Every solver solution passed the
independent validator; three final stages were optimal and one returned a
validated feasible solution after controlled interruption.  All 414 realized
boxes were placed without fallback, no box remained unplaced, and both new-
ship and old-ship inventories were empty after their release times.  Total
wall time was approximately 2.38 seconds on the pilot machine.

This gate establishes data-contract and lifecycle correctness only.  It is not
a formal computational-performance result and does not demonstrate the value
of Progressive Repair, which was correctly not triggered in this non-pressure
case.

## Formal experiment table and data families

The final study keeps different evidential roles in separate tables:

1. **Data audit and calibration.** PORT-MIS only; schedule, vessel, berth,
   source completeness, calibration assumptions, and hashes.
2. **Main external-validity comparison.** The three public-data-driven windows;
   the frozen seven methods and ten formal seeds.
3. **Public calibration robustness.** PORT-MIS windows with one-factor-at-a-
   time calibration variants; at minimum the candidate and `core_start`, with
   external baselines included on the central setting.
4. **Synthetic computational scale.** Oracle-certified small, medium, large,
   and xlarge bundles; the frozen seven methods.
5. **Synthetic utilization/pressure.** Certified feasible, tight, and
   separately labelled overloaded sister cases. Overloaded cases are stress
   evidence and are not pooled into zero-shortage claims.
6. **Internal component ablation.** `core`, `core_start`,
   `core_start_impact`, and `full_bottleneck`; add
   `full_bottleneck_no_aggregate` only for the aggregate routing ablation.
7. **Repair-mechanism reachability.** Controlled `nearby` and `global`
   pressure cases; mechanism statistics only.
8. **Parameter sensitivity.** DRA-RPM one-factor-at-a-time profiles and the
   declared public calibration factors. These are not used to retune the
   candidate after formal outcomes are inspected.

Public data support external validity but do not expose true box attributes,
forecast histories, or yard layout. Those elements remain fully disclosed
semi-synthetic fields. Synthetic cases are therefore still required for exact
scale, utilization, oracle certification, and mechanism control.

## Frozen DRA-RPM sensitivity

The main comparison uses `frozen`: \(\mu=0.5\), \(\nu=0.5\), and history
discount \(0.8\). The separate one-factor-at-a-time profiles are
`mu_low=0.25`, `mu_high=0.75`, `nu_low=0.25`, `nu_high=0.75`,
`discount_low=0.60`, and `discount_high=0.95`; all unspecified values remain
at the frozen setting. Every CSV row records the profile and three scalar
values.

## Reproducible commands

After committing and tagging the infrastructure, prepare synthetic bundles
without running a method:

```bash
python scripts/prepare_formal_instances.py \
  --experiment-phase formal \
  --output-dir local_results/formal/instances/synthetic \
  synthetic --sizes small medium large xlarge \
  --seeds 1000 1001 1002 1003 1004 1005 1006 1007 1008 1009 \
  --forecast-error 0.1 --forecast-error-mode mixed \
  --initial-utilization 0.55 \
  --oracle-case-classes feasible tight
```

Prepare public bundles only after replacing the provisional source manifest
with the archived publication extraction:

```bash
python scripts/prepare_formal_instances.py \
  --experiment-phase formal \
  --output-dir local_results/formal/instances/portmis \
  portmis --windows public_small public_medium public_large \
  --seeds 1000 1001 1002 1003 1004 1005 1006 1007 1008 1009 \
  --calibration-dir <fixed-calibration-directory> \
  --source-manifest <fixed-official-source-manifest>
```

Run the paired seven-method matrix from archived files:

```bash
python scripts/run_formal_matrix.py \
  --experiment-phase formal --experiment-set main \
  --bundle-indexes \
    local_results/formal/instances/synthetic/synthetic_instance_index.json \
  --output local_results/formal/runs/synthetic_main.csv
```

The Aggregate-LP ablation and DRA-RPM sensitivity use the same bundles:

```bash
python scripts/run_formal_matrix.py \
  --experiment-phase formal --experiment-set aggregate_ablation \
  --bundle-indexes \
    local_results/formal/instances/synthetic/synthetic_instance_index.json \
  --output local_results/formal/runs/aggregate_ablation.csv

python scripts/run_formal_matrix.py \
  --experiment-phase formal --experiment-set dra_sensitivity \
  --bundle-indexes \
    local_results/formal/instances/portmis/portmis_instance_index.json \
  --output local_results/formal/runs/dra_sensitivity.csv
```

Summarize one completed matrix with artifact gates, descriptive statistics,
95% confidence intervals, paired differences, win/tie/loss counts, and a
two-sided Wilcoxon test when SciPy is available:

```bash
python analysis/summarize_experiments.py \
  local_results/formal/runs/synthetic_main.csv \
  --output local_results/formal/runs/synthetic_main.summary.json
```

The summary distinguishes every DRA-RPM sensitivity profile, includes the
three external-baseline pairings, and audits formal seed membership, instance
hash presence, duplicate experiment identities, dirty state, validation
failures, wall-clock failures, and provisional public sources.
