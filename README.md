# Rolling-horizon export-container bay allocation

This repository implements stability-aware rolling allocation and capacity
reservation at bay level. It does not assign exact row/tier/stack slots, model
stacking order, or optimize relocation.

Every 24 hours the framework solves a 96-hour look-ahead model with 6-hour
periods. Each vessel has a 72-hour receiving window. Realized inventory is
immutable, while unexecuted historical reservations can be revised together
with newly admitted vessels.

## Information, forecasts, and release

The optimizer receives current realized inventory, the current arrival and
outbound forecasts, previous reservations, and external planned release times.
It never receives hidden future arrivals, truth-based forecast diagnostics, or
realized schedule delays.

Synthetic cases first create a public booking baseline and draw one hidden
final truth. Forecasts form a correlated noisy information trajectory around
that truth: quantity variance, timing errors, and unrevealed booking changes
shrink with lead time. MAE, MAPE, total error, and timing error remain case-level
simulation diagnostics and are excluded from optimization snapshots.

Planned vessel release uses public ship class and booking volume. Planned
operation duration is the maximum of the external class duration and
`ceil(public_booking_total / nominal_outbound_rate_per_ship_period)`. It never
uses hidden volume. Outbound-relevant vessels satisfy `ETA < look-ahead end`
and `planned release > now`. This set is distinct from active receiving vessels:
it includes both vessels whose ETA falls in the look-ahead window and vessels
already loading after ETA but before planned release.

Each relevant vessel's visible outbound total is current actual inventory plus
remaining current-cycle forecast arrivals. Its planned workload profile is
first distributed over the complete `[planned ETA, planned release)` interval;
periods before now and at or beyond the look-ahead end are then truncated, not
redistributed. Block weights use current actual inventory plus unexecuted
previous reservations, with a deterministic closest-block fallback when both
are empty. Loading-phase vessels therefore remain represented in predicted
inbound/outbound conflict.

Capacity is released only when the entire vessel operation is complete.
Progressive box-by-box release is not modeled. Outbound flows are an
inbound/outbound interference proxy and do not themselves release capacity.

## Synthetic initialization

The generator records both requested and realized initial utilization. A
deterministic seeded allocator places the exact rounded target quantity, caps
each bay at 95%, preserves one height type per bay, distributes inventory over
multiple old vessels, and raises an exception if the requested level is
physically unreachable. This certifies only the initial inventory placement;
an 80% initial state can still make later vessel demand structurally
unplaceable.

For publication experiments, an independent full-information integer packing
oracle classifies sister instances as ordinary feasible, tight feasible, or
overloaded. It uses true arrivals only offline and is never visible to the
rolling optimizer. Zero shortage certifies feasibility, while a strictly
positive objective lower bound certifies overload. Oracle protocol v2 first
checks a conservative period-by-size aggregate capacity lower bound, then uses
the integer MIP whenever that bound does not already prove overload.
Unresolved time-limited cases remain `unknown`. Oracle-certified cases add
three terminal execution cycles with no new admissions so all admitted
vessels' 72-hour receiving tails are executed and realized-arrival coverage
equals the certified demand.

## Model and stability

The integer MIP enforces:

- bay capacity in every period and at the horizon boundary;
- fixed 20/40-foot compatibility;
- no mixed height type in a bay during one period;
- immutable realized inventory and whole-vessel release;
- ship/POD bay-support concentration;
- block occupancy-utilization balance;
- transport distance and inbound/outbound overlap costs.

Its lexicographic objectives minimize predicted shortage, plan-stability cost,
and a normalized operational score. One unrestricted set of normalization scales
is reused by every stage.

Stability is computed per `(ship, group)`, preventing one group's shortage from
offsetting another group's cancellation. Actual inventory contributes to
existing spatial support but not to the cancellable plan baseline. The default
formulation is epigraph-only for the three positive-part quantities that enter
the stability objective. Pair discretionary cancellation is derived only in
canonical accounting, not represented by a free model variable.
`USE_EXACT_STABILITY_BIG_M=True` retains three exact binary families for
diagnostic comparison. Independent canonical accounting validates accepted
solutions. There is no hard plan-revision budget: stability is controlled only
by the second lexicographic objective, so an artificial allowance can never
force additional shortage in a restricted or global domain.

Forecast arrivals at or after planned release are rejected by snapshot
validation. Model construction also omits their inbound-flow variables, so an
invalid bypassed snapshot can only record that quantity as shortage.

## Impact-region and bottleneck-guided repair algorithm

The recommended `full_bottleneck` configuration:

1. identifies directly changed ship-group pairs;
2. computes time-dependent residual capacity, height conflicts, and the frozen
   inherited-plan baseline used to rank candidate blocks;
3. builds the lead-aware forecast buffer from the declared error magnitude and
   the maximum visible forecast lead-time coefficient;
4. solves a continuous block-size-height-period aggregate LP on domains
   `N0`, `N1`, and `N2`, stopping at the smallest domain whose uniform capacity
   scale covers the buffered forecast;
5. sends the snapshot directly to the unrestricted Global MIP if no restricted
   domain passes the aggregate screen;
6. otherwise solves the exact integer `N0` Impact Region with a MIP start;
7. solves a granularity-guarded minimum pair-block cover only after the integer
   incumbent exposes shortage;
8. reserves a bounded part of the same online window and restores the
   unrestricted compatible domain if the bottleneck incumbent still has
   shortage.

The aggregate LP is explicitly a screening relaxation, not a bay-level
feasibility certificate. Integer bay packing, no-mixed-height constraints, and
independent validation remain in the downstream MIP path. The controller never
reads an instance-size label or hidden realized demand. Across all exact stages,
an incumbent is replaced only by a strict lexicographic improvement in
predicted shortage, stability cost, and normalized operations score.

The optional `full` ablation additionally builds a physical-resource dependency
graph. It does not proactively release graph neighbors: only a shortage-bearing
incumbent can add dependency neighbors to Progressive Repair. This keeps normal
cycles aligned with `full_direct` while exposing the mechanism in controlled
pressure tests. The retired quality-polish implementation is protocol-disabled.

The minimum-cover repair uses the incumbent's time-dependent shortage and
compatible residual capacity to release the smallest useful set of additional
pair-block domains. A one-compatible-bay guard reflects integer packing
granularity without reserving extra physical capacity.

Configurations are:

- `core`: unrestricted MIP without a start;
- `core_start`: unrestricted MIP with inherited MIP start;
- `core_start_impact`: direct impact region without propagation or repair;
- `full_direct`: fixed-ratio Progressive Repair ablation;
- `full_bottleneck`: lead-aware aggregate-LP screening, minimum bottleneck
  repair, and global recovery;
- `full`: optional reactive dependency propagation on top of `full_direct`.

`full_direct` is retained only to isolate the repair-controller contribution;
it is not a primary external baseline.

## Execution and realized metrics

Planned and fallback placement use the same feasibility function for capacity,
size, height, release, requested quantity, and remaining reservation. Execution
state is validated after every 6-hour period and at each cycle boundary.

Space metrics are recorded after every executed period. Cycle peak utilization
is the true maximum over periods; mean utilization deviation is averaged over
periods; maximum spread is the period maximum. Support activation counts each
new period-to-period `(ship, POD, bay)` support even if it disappears before the
cycle ends. Overall bays-per-ship-POD uses the sum of bay counts divided by the
sum of period observations rather than an unweighted average of cycle means.

## Timing and solver diagnostics

The per-cycle online limit is wall-clock time from method-specific
preprocessing through the availability of a complete executable allocation. It
includes impact detection, scoring, graph construction, model construction,
Gurobi, callbacks, repair control, and complete solution extraction. Independent
validation and final model disposal are audit work outside that online decision
boundary; an invalid audited solution still fails the run. Every stage reports
total and binary variables, constraints, nodes, solution count, stage
first-incumbent time, and reliable bound/gap attributes. Cycle first-incumbent
time starts before preprocessing.

To enforce that contract, every configuration reserves the same bounded tail
for solver-limit overrun and complete incumbent extraction:
16% of the cycle limit, with a 0.5-second minimum and 20-second maximum, while
very short diagnostic limits retain at least half their budget for
optimization. The callback also enforces the absolute stage deadline. The
reserve is included in the recorded weight/runtime profile.
Because Gurobi documents that it may return after its nominal `TimeLimit`
while finalizing solver attributes, optimization also receives a common
in-budget return guard (10% of the cycle limit, capped at 12 seconds) and an
independent wall-clock termination request. The unused part of that guard
remains inside the method's original budget; it is not extra runtime.
`online_decision_time` is the primary computational metric.
`audit_wall_time`, solution-extraction time, model-disposal time, and validation
time are recorded separately. A time-limited but valid allocation available by
the deadline is `TIME_LIMIT_FEASIBLE`; only a missing/late allocation or an
invalid audited allocation fails the rolling trajectory.
Each completed stage disposes its Gurobi model explicitly so long Pilot batches
do not accumulate native solver resources across rolling cycles.
The Pilot quality-polish stage is disabled in protocol `rolling-v3.9` because
it consumed most of the residual budget without improving any accepted Pilot
incumbent. The switch is applied equally to `full_direct` and `full` and is
recorded in every experiment weight profile.
Integer and binary solver values are normalized to exact integers before
independent validation. This follows the solver's integer-feasibility contract
without weakening the tighter physical-balance and capacity checks.
Dependency propagation exposes exactly three reproducible sensitivity profiles:
`conservative`, `current`, and `expansive`. They change only the edge/path
thresholds and are selected with `--dependency-profile`; the selected values
are stored in both scalar metadata and the weight profile.
Propagation is reactive: the first impact-region solve changes direct pairs
only, and dependency neighbors are released only when that incumbent has
predicted shortage and Progressive Repair is invoked. This prevents routine
cycles from trading execution robustness for marginal operational polishing.
The `nearby` and `global` pressure cases are two-cycle, multi-ship mechanism
tests with a controlled second-cycle forecast shock. They are intended only to
verify reactive propagation and repair-stage reachability, not to estimate
normal operational performance.

Gurobi may not expose `ObjBound` or `MIPGap` reliably for this lexicographic
multiobjective model. `final_stage_objective_bound` and
`final_stage_mip_gap` therefore describe the last optimization stage and are
explicitly `None` when the attributes are unavailable; root relaxation is also
`None` unless it can be obtained reliably.

## Running

The reproducible reference environment is Python 3.12 with the exact package
versions in `requirements.txt`. Create an isolated environment and install it
before running tests or scripts:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

Gurobi also requires a valid local licence. Package installation alone does
not supply that licence. The repository currently has no declared software
licence; redistribution terms must therefore be chosen by the repository
owner before a public archival release.

Run one case:

```bash
python main.py --size small --configuration full_bottleneck --time 20 \
  --mip-gap 0.01 --seed 0
```

Run controlled combinations:

```bash
python run_experiments.py --sizes small medium --errors 0.1 0.2 \
  --forecast-error-modes multiplicative timing_shift booking_add_cancel \
  --initial-utilizations 0.25 0.55 0.70 \
  --configurations core_start full_direct full_bottleneck --seeds 0 1 2 \
  --mip-gap 0.01 --output local_results/runs/pilot_results.csv \
  --manifest-output local_results/runs/pilot_results.manifest.json
```

Generate ordinary-feasible, tight-feasible, and overloaded sister cases with
offline integer certificates:

```bash
python run_experiments.py --sizes small \
  --oracle-case-classes feasible tight overloaded \
  --configurations core core_start core_start_impact full_bottleneck \
  --seeds 100 --time 20 \
  --output local_results/runs/oracle_certified_development.csv
```

Oracle calibration time is recorded separately and excluded from each online
method's time limit.

The unified experiment interface also exposes three adapted literature
baselines:

- `kp_dos`: Kim--Park least-duration-of-stay allocation;
- `kp_sg`: Kim--Park Lagrangian/subgradient allocation;
- `dra_rpm`: Xuan et al. dynamic reward-penalty reservation.

For a paired development comparison:

```bash
python run_experiments.py --sizes small medium large --errors 0.1 \
  --forecast-error-modes mixed --initial-utilizations 0.55 \
  --configurations full_bottleneck full_direct kp_dos kp_sg dra_rpm \
  --seeds 0 --time 20 \
  --output local_results/runs/external_baseline_development.csv
```

These are adapted rather than code-identical reproductions. They share the
same visible rolling snapshot, integer bay decoder, hard constraints,
realized execution path and evaluator. Source mappings, missing source
parameters and fidelity labels are frozen in
`docs/external_baseline_adaptation_protocol.md`.

Each completed row atomically checkpoints both files. An interrupted batch can
be continued with the identical command plus `--resume`; incompatible Git,
protocol, runtime, weight-profile, or matrix metadata is rejected instead of
silently mixing results. The manifest distinguishes a successful partial
checkpoint from a complete requested matrix through `row_count`,
`expected_row_count`, and `complete`.

## Current TRE submission workflow

The current implementation identifiers are
`rolling-v4.6-objective-only-stability`,
`lead-aware-aggregate-lp-residual-global-repair-v1.7.1`, and
`rolling-results-v15`. Its primary operation profile is `business`
(`distance=0.40`, `balance=0.30`, `concentration=0.20`,
`in_out_conflict=0.10`); the other frozen profiles are sensitivity cases.
The authoritative change and experiment boundary is
`docs/tre_objective_revision_protocol.md`, and the current machine-readable
state is `docs/specs/formal_run_manifest_v3.json`.
The v1.7.1 development gate has passed; its 72-row main matrix, separate
mechanism evidence, profile-isolation checks, and observed trade-offs are
reported in `docs/reports/tre_v171_development_gate.md`. Preflight and formal
execution remain separate gates.

Formal execution is intentionally closed while
`FORMAL_RESULT_AUTHORIZED=False`. Opening formal seeds, running a formal
matrix, or labeling results as confirmatory requires first registering a new
untouched confirmatory set and then explicitly changing that flag in a clean,
frozen commit. Both the generator and matrix runner enforce this gate, and a
formal index must itself contain `formal_results_authorized=true`.

Once that prerequisite has been documented and authorized, the sole PNC--
Yangshan formal bundle generator is:

```powershell
python scripts/prepare_pnc_yangshan_v2_formal_instances.py `
  --output-root local_results/protocol_v3_tre_objective/formal_instances
```

The resulting central index is consumed without a time-budget override:

```powershell
python scripts/run_formal_sharded_matrix.py `
  --bundle-index local_results/protocol_v3_tre_objective/formal_instances/pnc_yangshan_v2_central_main_index.json `
  --workers 2 --threads 1 `
  --output local_results/protocol_v3_tre_objective/runs/public_main.csv
```

`analysis/summarize_experiments.py` defaults to a strict publication audit for
formal CSVs: it rejects mixed protocols or commits, duplicate identities,
failed/late/invalid rows, non-held-out seeds, missing bundle hashes,
provisional sources, and incomplete manifests. `--exploratory` is an explicit
escape hatch and labels the resulting report as non-publication analysis.

## Historical PORT-MIS formal workflow

The earlier PORT-MIS protocol used a two-step interface so case generation could not change
between methods:

1. `scripts/prepare_formal_instances.py` serializes each exact case to a
   hash-verified instance bundle and immutable index;
2. `scripts/run_formal_sharded_matrix.py` verifies the index, balances whole
   instances over independent workers, and merges their atomic checkpoints
   into `rolling-results-v9` rows after exact identity auditing.

The formal runner fixes ten held-out seeds (`1000`--`1009`), rejects dirty Git
state and time overrides, and uses per-cycle budgets stored in each bundle:
20 seconds for small/medium, 60 for large, and 120 for xlarge. The frozen main
matrix is `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`.
The unrestricted `core` and direct `core_start_impact` variants are reserved
for the separate internal-ablation panel.

The formal main matrix uses two parallel instance workers by default. Each
worker still uses one Gurobi thread and runs all five paired methods for its
assigned instances. Workers never share a CSV: each writes an independent
checkpoint and manifest, and the controller rejects missing, duplicate, or
unexpected experiment identities before producing the common result. Per-cycle
online times remain method runtimes, not total batch makespan.

```bash
python scripts/run_formal_sharded_matrix.py \
  --bundle-index \
    local_results/formal/instances/portmis_primary/portmis_instance_index.json \
  --workers 2 --threads 1 \
  --output local_results/formal/runs/public_main.csv
```

Example development smoke:

```bash
python scripts/prepare_formal_instances.py \
  --output-dir local_results/formal_smoke/instances \
  synthetic --sizes pilot_small --seeds 100

python scripts/run_formal_matrix.py \
  --bundles local_results/formal_smoke/instances \
  --experiment-set main --time 2 \
  --output local_results/formal_smoke/results.csv
```

The fixed July PORT-MIS snapshot now uses
`portmis-fixed-source-snapshot-v2`. The documented data.go.kr OpenAPI requires
a service key, so the archived source instead uses the Ministry's official
`fileData` record, whose provider URL is the PORT-MIS vessel-call query page.
The publication contract archives both data.go.kr catalogue records, the
official pages, the PORT-MIS UI definition, exact POST-request identities, raw
responses, standardized tables, licence evidence, and all SHA-256 values. The
formal gate independently checks this chain and the calibration/source link;
changing only `publication_ready` cannot bypass it.

March, July, and November 2025 source snapshots provide a separate temporal
robustness panel. The July small/medium/large profiles remain the primary scale
panel; equal-duration, equal-layout temporal profiles are never pooled with
them. PORT-MIS supplies the vessel-call and schedule skeleton only. Box
quantities and attributes, forecast histories, yard state, and bay layout are
explicitly recorded as semi-synthetic rather than treated as observed data.
The committed checksum ledger is
`docs/portmis_publication_source_registry.json`; matching raw source archives
remain publication-package artifacts rather than Git-tracked generated data.
`scripts/package_portmis_source.py` verifies a complete source/calibration
chain and creates the deterministic ZIP named in that ledger.
Full experiment composition and commands are specified in
`docs/formal_experiment_protocol.md`.

After a matrix completes, `analysis/summarize_experiments.py` produces the
paired win/tie/loss and confidence-interval report while auditing formal seeds,
bundle hashes, duplicate rows, source readiness, validation, and time-limit
failures.

If `--manifest-output` is omitted, the manifest defaults to the CSV stem, for
example `local_results/runs/pilot_results.manifest.json`. Every CSV row records
the Git commit, branch and dirty state; problem protocol; Python and Gurobi
versions; threads; MIP gap; stability formulation; and a compact sorted JSON
weight profile. The batch manifest additionally records UTC creation time, the
command, platform and Python implementation, requested experiment matrix, row
count, and batch success status. Unavailable Git or Gurobi metadata is recorded
as null rather than aborting the experiment.

Run the bounded pilot workflow, which uses only `pilot_small`:

```bash
python scripts/run_pilot_smoke.py
```

This produces both `local_results/runs/pilot_smoke_results.csv` and
`local_results/runs/pilot_smoke_results.manifest.json`. New ad-hoc experiment
artifacts belong under `local_results/runs/`; frozen preflight artifacts and
older development outputs are kept under `local_results/preflight/` and
`local_results/archive/`. Archived pilot and tuning narratives are under
`docs/reports/`.

`large` and `xlarge` are interfaces for later formal experiments and are never
part of the default smoke workflow. Statistical summaries are generated with:

```bash
python analysis/summarize_experiments.py \
  local_results/runs/rolling_results.csv
```

Detailed definitions are in `docs/model_assumptions.md` and
`docs/dependency_impact_design.md`. The candidate-freeze rules, metric schema,
held-out seeds, preflight gate, and required baselines are specified in
`docs/formal_experiment_protocol.md`. The synthetic formal design separates
four computational sizes, three initial-utilization levels, and two calibrated
capacity-pressure levels. Aggregate pressure targets are descriptive only;
every formal comparison bundle must still pass the independent integer
full-horizon packing oracle.
