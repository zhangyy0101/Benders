# Rolling yard bay-slot allocation

This repository implements a stability-aware rolling optimization framework.
Every 24 hours it solves a 96-hour look-ahead model divided into sixteen 6-hour
periods. Each ship has its own twelve-period (72-hour) receiving window and a
ship-specific time-varying forecast. The model jointly reallocates the remaining
demand of receiving ships and newly admitted ships (ETA in 72--96 hours).
Already received containers are immutable.  Old outbound inventory is released
only after its whole ship has left the yard.

All ships follow one non-overlapping lifecycle: twelve inbound periods before
ETA, then uniform outbound periods beginning at ETA. The default aggregate rate
is 150 boxes per ship per 6-hour period and is configurable. Outbound forecasts
create a conflict cost whenever they overlap another ship's inbound flow in the
same block and period, while capacity remains locked until whole-ship completion.

The core integer MIP preserves bay capacity, fixed container size, no mixed
height, same-ship/same-POD concentration, block balance, berth distance, and
same-block simultaneous inbound/outbound conflict.
Its lexicographic objectives minimize shortage, plan disruption, and operational
cost in that order.

The outer framework contains four focused mechanisms:

1. inherited MIP starts from the unexecuted part of the previous plan;
2. ship-group direct-impact detection and optional dependency propagation;
3. capacity/conflict-guided adaptive repair and final global recovery;
4. selective quality polishing.

The Full configuration derives a cancellation budget from the rolling forecast
change. Candidate blocks are ranked by normalized demand coverage and marginal
distance, time-specific inbound/outbound overlap, balance, bay-use, height, and
stability effects. If shortage remains, only deficient ship-attribute pairs are
expanded and successive repairs relax the cancellation budget before global
recovery. Once a shortage-free plan is found, one selective quality-polishing
solve expands two alternatives for the highest-cost half of ship-attribute
pairs. The incumbent is retained unless the lexicographic objective improves.

Five ablation configurations are available:

- `core`: global Core MIP without a start;
- `core_start`: global Core MIP with the inherited start;
- `core_start_impact`: inherited start plus the restricted impact region;
- `full_direct`: direct ship-group impact, repair, recovery, and polishing;
- `full`: the same mechanisms plus dependency propagation.

Forecast-window diagnostics, plan-revision metrics, and realized 24-hour
execution metrics are reported separately. Only realized execution metrics are
summed across rolling cycles as operational outcomes. See
`docs/dependency_impact_design.md` for the dependency and accounting definitions.

Forecasts are exogenous.  Synthetic tests keep a hidden realized demand and
generate correlated forecasts that improve as ETA approaches; the optimizer
never sees the hidden demand.

Run a rolling case:

```bash
python main.py --size small --time 20 --forecast-error 0.1
```

Run one ablation or a diagnostic repair case:

```bash
python main.py --configuration core_start_impact
python main.py --configuration full --pressure nearby
python main.py --configuration full --pressure global
```

Run controlled scale/error experiments:

```bash
python run_experiments.py --sizes small medium large --errors 0 0.1 0.2
```

Run the component comparison and both repair diagnostics:

```bash
python run_experiments.py --sizes small --errors 0.1 --configurations core core_start core_start_impact full_direct full --pressure-levels nearby global
```
