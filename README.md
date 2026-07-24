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
physically unreachable. Standard scenarios through 80% utilization are
supported.

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
formulation is epigraph-only and removes four families of stability binaries.
`USE_EXACT_STABILITY_BIG_M=True` retains the exact binary formulation for
diagnostic comparison. Independent canonical accounting validates accepted
solutions.

Forecast arrivals at or after planned release are rejected by snapshot
validation. Model construction also omits their inbound-flow variables, so an
invalid bypassed snapshot can only record that quantity as shortage.

## Impact-region and bottleneck-guided repair algorithm

The recommended `full_bottleneck` configuration:

1. identifies directly changed ship-group pairs;
2. computes time-dependent physical residual capacity and height conflicts;
3. deducts frozen inherited reservations to form baseline residual capacity;
4. ranks candidate blocks and solves the impact region with a MIP start;
5. solves a granularity-guarded minimum pair-block cover for shortage pairs;
6. restores the unrestricted compatible domain if shortage remains.

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
- `full_bottleneck`: recommended bottleneck-guided repair and global recovery;
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

The per-cycle limit is wall-clock time and includes impact detection, scoring,
graph construction, model construction, Gurobi, extraction, and validation.
Every stage reports total and binary variables, constraints, nodes, solution
count, stage first-incumbent time, and reliable bound/gap attributes. Cycle
first-incumbent time starts before preprocessing.

To enforce that contract, every configuration reserves the same bounded tail
for solver-limit overrun, incumbent extraction, and independent validation:
15% of the cycle limit, with a 0.5-second minimum and 10-second maximum, while
very short diagnostic limits retain at least half their budget for
optimization. The callback also enforces the absolute stage deadline. The
reserve is included in the recorded weight/runtime profile.
Each completed stage also disposes its Gurobi model explicitly so long Pilot
batches do not accumulate native solver resources across rolling cycles.
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
  --mip-gap 0.01 --output pilot_results.csv \
  --manifest-output pilot_results.manifest.json
```

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
  --seeds 0 --time 20 --output external_baseline_development.csv
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

If `--manifest-output` is omitted, the manifest defaults to the CSV stem, for
example `pilot_results.manifest.json`. Every CSV row records the Git commit,
branch and dirty state; problem protocol; Python and Gurobi versions; threads;
MIP gap; stability formulation; and a compact sorted JSON weight profile. The
batch manifest additionally records UTC creation time, the command, platform
and Python implementation, requested experiment matrix, row count, and batch
success status. Unavailable Git or Gurobi metadata is recorded as null rather
than aborting the experiment.

Run the bounded pilot workflow, which uses only `pilot_small`:

```bash
python scripts/run_pilot_smoke.py --output pilot_smoke_results.csv
```

This produces both `pilot_smoke_results.csv` and
`pilot_smoke_results.manifest.json`.

`large` and `xlarge` are interfaces for later formal experiments and are never
part of the default smoke workflow. Statistical summaries are generated with:

```bash
python analysis/summarize_experiments.py rolling_results.csv
```

Detailed definitions are in `docs/model_assumptions.md` and
`docs/dependency_impact_design.md`. The candidate-freeze rules, metric schema,
held-out seeds, preflight gate, and required baselines are specified in
`docs/formal_experiment_protocol.md`.
