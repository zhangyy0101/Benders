# Rolling-horizon export-container bay allocation

This repository implements a stability-aware rolling-horizon model for
**bay-level allocation and capacity reservation**. It does not assign exact
row/tier/stack slots, model stacking order, or optimize container relocation.

Every 24 hours the framework solves a 96-hour look-ahead model with 6-hour
periods. Each ship has a 72-hour receiving window. Already received containers
are immutable, while the unexecuted part of the previous reservation can be
revised together with newly admitted ships.

## Information and release assumptions

Forecast arrivals and planned vessel-completion times are external inputs to
the optimizer. Hidden realized arrivals are used only by the execution
simulator. In synthetic cases, forecasts and hidden realizations are separate
reproducible draws from a public booking baseline; the forecast generator does
not read the hidden realization. Planned release times are generated from public ship classes and
external operation durations; they are never inferred from hidden container
totals. Optional realized release delays are stored separately and remain
invisible to optimization.

A vessel's containers and reserved capacity remain in the yard until its
planned completion period, when the whole vessel allocation is released at
once. Progressive box-by-box loading release is not modeled. Outbound flows are
used only as an inbound/outbound operation-overlap proxy; they do not release
capacity.

## Model

The integer MIP enforces:

- bay capacity by period and at the horizon boundary;
- fixed 20/40-foot bay compatibility;
- no mixed height type in one bay during the same period;
- immutable realized inventory;
- ship/POD bay-support concentration;
- block occupancy-utilization balance;
- transport distance and inbound/outbound overlap costs.

The lexicographic objectives minimize predicted shortage, plan stability cost,
and normalized operation cost. All stages reuse one set of scales computed from
the unrestricted snapshot, so local and global incumbent objectives are
comparable.

Stability is calculated per ship-group. A group's cancellation can be explained
only by its own mandatory demand reduction and its own predicted shortage.
Cancellation from one group cannot be offset by another group's shortage.
Actual inventory contributes to existing bay support but never to the
cancellable plan baseline.

## Dependency-aware impact algorithm

The `full` configuration:

1. identifies directly changed ship-group pairs;
2. computes time-dependent compatible residual capacity and height conflicts;
3. builds a resource-competition graph;
4. propagates both capacity pressure and release opportunities;
5. solves the resulting impact region with an inherited MIP start;
6. expands shortage pairs and their strongest dependency neighbors;
7. falls back to the unrestricted compatible-bay model if required;
8. selectively polishes a shortage-free incumbent.

Historical pairs whose demand disappears remain dependency nodes, although no
decision variables are created for their zero demand. Their released historical
blocks can therefore be reconsidered by affected positive-demand pairs.

Available configurations are:

- `core`: unrestricted MIP without a start;
- `core_start`: unrestricted MIP with inherited MIP start;
- `core_start_impact`: direct impact region without propagation or repair;
- `full_direct`: direct impact, repair, global recovery, and polishing;
- `full`: identical to `full_direct`, plus dependency propagation.

The time limit is a per-cycle wall-clock deadline. Impact detection, score and
graph construction, model construction, Gurobi runtime, extraction, and
validation are all reported and included in elapsed time.

## Closed-loop evaluation

Execution first tries the period-specific planned bay and then uses a
deterministic fallback ranking based on planned block, existing ship/POD
support, realized conflict, distance, free capacity, and remaining reservation.
Both planned and fallback placement use the same capacity, size, height,
release, and reservation feasibility check.

Results distinguish:

- overlapping 96-hour predicted diagnostics;
- plan-revision metrics at each reoptimization;
- non-overlapping realized 24-hour execution metrics.

Realized outputs include fallback and unplaced rates, distance, operation
overlap, bay concentration, peak block utilization, and utilization deviation.
Occupancy balance refers to inventory utilization—not equipment workload.

## Running

Run one small case:

```bash
python main.py --size small --configuration full --time 20 --seed 0
```

Select an uncertainty mode or realized release delay:

```bash
python main.py --forecast-error-mode timing_shift --release-delay-periods 1
```

Run controlled experiment combinations:

```bash
python run_experiments.py --sizes small medium --errors 0.1 0.2 \
  --forecast-error-modes multiplicative timing_shift booking_add_cancel \
  --initial-utilizations 0.25 0.55 0.70 \
  --configurations core_start full_direct full --seeds 0 1 2
```

The `xlarge` preset is an interface for later formal experiments and is not part
of default smoke testing. Experiment summaries and paired differences can be
generated with:

```bash
python analysis/summarize_experiments.py rolling_results.csv
```

Detailed assumptions and algorithm definitions are in
`docs/model_assumptions.md` and `docs/dependency_impact_design.md`.
