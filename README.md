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
uses hidden volume. A continuing vessel's outbound forecast is rebuilt from
visible actual inventory plus remaining visible forecast arrivals, distributed
over `[planned ETA, planned release)` and then across blocks using current
actual inventory and inherited reservations.

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
and normalized operational cost. One unrestricted set of normalization scales
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

## Dependency-aware impact algorithm

The `full` configuration:

1. identifies directly changed ship-group pairs;
2. computes time-dependent physical residual capacity and height conflicts;
3. builds a physical-resource dependency graph;
4. propagates capacity pressure and resource-release opportunities;
5. deducts frozen inherited reservations to form baseline residual capacity;
6. ranks candidate blocks and solves the impact region with a MIP start;
7. expands shortage pairs and dependency neighbors;
8. restores the unrestricted compatible domain if needed;
9. polishes a shortage-free incumbent using utilization-consistent scores.

The dependency graph uses physical residual capacity after locked and actual
inventory. Candidate ranking uses baseline residual capacity, which additionally
deducts historical reservations of unaffected frozen pairs. Quality polish
uses horizon-end occupancy divided by each block's own capacity, including
locked, actual, and planned inventory that remains present.

Configurations are:

- `core`: unrestricted MIP without a start;
- `core_start`: unrestricted MIP with inherited MIP start;
- `core_start_impact`: direct impact region without propagation or repair;
- `full_direct`: direct impact, repair, global recovery, and polishing;
- `full`: identical to `full_direct`, plus dependency propagation.

Thus `full_direct` and `full` differ only through dependency propagation and
its downstream affected region.

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

Gurobi may not expose `ObjBound` or `MIPGap` reliably for this lexicographic
multiobjective model. `final_stage_objective_bound` and
`final_stage_mip_gap` therefore describe the last optimization stage and are
explicitly `None` when the attributes are unavailable; root relaxation is also
`None` unless it can be obtained reliably.

## Running

Run one case:

```bash
python main.py --size small --configuration full --time 20 --seed 0
```

Run controlled combinations:

```bash
python run_experiments.py --sizes small medium --errors 0.1 0.2 \
  --forecast-error-modes multiplicative timing_shift booking_add_cancel \
  --initial-utilizations 0.25 0.55 0.70 \
  --configurations core_start full_direct full --seeds 0 1 2
```

Run the bounded pilot workflow, which uses only `pilot_small`:

```bash
python scripts/run_pilot_smoke.py
```

`large` and `xlarge` are interfaces for later formal experiments and are never
part of the default smoke workflow. Statistical summaries are generated with:

```bash
python analysis/summarize_experiments.py rolling_results.csv
```

Detailed definitions are in `docs/model_assumptions.md` and
`docs/dependency_impact_design.md`.
