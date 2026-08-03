# Dependency-aware impact-region design

## Rolling information boundary

The optimizer receives current realized inventory, the unexecuted previous
reservation, external arrival/outbound forecasts, and external planned release
times. Hidden future arrivals, truth-based forecast-error diagnostics, and
realized release delays are available only to the execution simulator. Planned
vessel completion uses public ship class and booking volume. Synthetic data
draw one hidden truth and then generate a correlated noisy information
trajectory that approaches truth as lead time shrinks; only the current
forecast enters the optimization snapshot.

Active receiving vessels and outbound-relevant vessels are deliberately
different sets. The latter also includes vessels already between ETA and
planned release. Their visible workload is constructed from actual inventory
and remaining arrival forecasts over the complete planned loading interval,
then truncated to the current horizon. Thus block-level outbound overlap does
not disappear merely because a vessel has entered its loading phase.

## Plan baseline and existing support

The cancellable baseline is `previous_reservation` only. Actual inventory is
immutable and cannot contribute to cancellation, mandatory reduction, block
cancellation, or the inherited plan start.

Existing spatial support combines live `actual_inventory` and
`previous_reservation`. It is represented by `(ship, POD, bay)` support and
ship-group historical blocks. This combined baseline is used for new-bay
counting, stability loss in block ranking, local candidate regions, dependency
history. Continuing in a bay already occupied by the
same ship/POD is therefore not a new support activation.

## Pair-level stability

For each historical or positive-demand pair `p`, cancellation is aggregated
from bay-level reductions. Its mandatory reduction is

```text
max(0, old_total[p] - current_demand[p]).
```

Pair discretionary cancellation is

```text
max(0, pair_cancellation[p]
       - pair_mandatory_reduction[p]
       - pair_shortage[p]).
```

The stability allowance limits the sum of these pair values. Thus shortage in
one pair cannot offset cancellation in another. Block reallocation uses the
same pair-local subtraction after aggregating historical block withdrawals.
By default, the MIP uses epigraph lower bounds for positive-part stability
variables. Their positive objective weights and the discretionary budget drive
them to the minimum relevant values. `USE_EXACT_STABILITY_BIG_M=True` retains
four exact binary families for diagnostics. In both modes, validation
recomputes canonical stability values directly from reservation and shortage.

## Fixed objective scales and occupancy balance

One unrestricted scale dictionary is calculated before stage-specific
candidate domains are built. Only ship/group pairs with positive optimizer-
visible arrivals contribute to its reachable support and quantity bounds. The
concentration scale counts their distinct compatible `(ship, POD, bay)`
supports. Distance uses their total positive forecast quantity times the
maximum reachable ship--block distance, and conflict uses the same quantity.
For \(K\) blocks, the tight universal per-period bound on the sum of absolute
utilization deviations from their mean is
\(2\lfloor K^2/4\rfloor/K\); the occupancy-balance scale multiplies this by the
number of periods. Every restricted and global stage receives this same
dictionary.

Block balance is inventory occupancy utilization, not equipment workload. For
each block and period, occupancy is divided by that block's own total bay
capacity. The objective minimizes deviations from average block utilization,
which remains meaningful when block capacities differ.

## Time-dependent capacity and block scores

Physical residual capacity is calculated for every bay and period after locked
old inventory, actual inventory, and their release times. The optional
dependency graph uses this physical capacity. In the first impact solve, only
direct pairs are adjustable and positive-demand unaffected pairs are frozen.
Baseline residual capacity deducts their inherited, time-dependent reservation
commitments. Final candidate ranking and allowed-region construction use this
baseline capacity.

For each ship-group and block, compatible capacity is calculated only from bays
with the correct size and a compatible live height type.

The outbound component of block scoring includes all outbound-relevant vessels,
including loading-phase vessels. Their block distribution uses current actual
inventory and unexecuted previous reservation only. This overlap enters both
the block score and the dependency-aware candidate ranking; no future MIP
allocation or hidden realized outbound data is used to construct it.

For arrival weights `w[p,n]`, the effective block capacity is

```text
sum_n w[p,n] * compatible_residual_capacity[p,k,n].
```

The capacity feature combines 70% arrival-weighted capacity ratio and 30%
minimum positive-arrival-period capacity ratio. Height conflict is also weighted
by the arrival profile. A block that is empty only at the end of the horizon is
therefore not treated as available for early arrivals.

## Safeguarded adaptive routing

`full_bottleneck` now replaces the empirical two-threshold route with a
lead-aware aggregate-LP screen. After pair-block scores are available, it
constructs the nested domains `N0`, `N1`, and `N2`. For each domain, a
continuous relaxation maximizes one common multiplier on all visible forecast
arrivals subject to shared block-size-height-period capacity. Existing occupied
bays contribute residual capacity only to their fixed height; empty bays form a
shared flexible-height pool.

The required multiplier is one plus the declared forecast-error magnitude
times the maximum visible lead-time sigma. The first restricted domain reaching
that multiplier identifies a locally recoverable snapshot. The exact integer
solver still starts from `N0`, and only an integer shortage incumbent can
activate the minimum pair-block repair. If none of `N0`--`N2` passes, the
controller enters the unrestricted Global MIP. Thus the LP decides local versus
global routing but does not claim integer packing feasibility.

The screen uses no instance-size or utilization label and no hidden
realization. The former peak-load and demand/free-capacity measures remain
diagnostics for development comparisons only. Every extracted exact-stage
solution receives the same key

```text
(predicted shortage, stability cost, normalized operations score).
```

It replaces the incumbent only if this key improves strictly and
lexicographically. This guard prevents later repair stages from replacing an
equally feasible plan by one with worse stability or operating quality. It
does not claim dominance over a separately time-limited Global run.

## Dependency graph and propagation

Nodes are the union of positive-demand and historical-reservation pairs.
Directions are `new`, `increase`, `decrease`, `disappear`, or `unchanged`.
Zero-demand historical nodes keep their historical blocks and a visible
historical remaining-plan profile; if no such profile exists, a deterministic
post-execution uniform profile is used.

Pairs of the same size are linked when their candidate blocks overlap. Edge
features are candidate Jaccard overlap, arrival-profile cosine similarity,
time-weighted common-capacity pressure, and historical-block overlap. Different
heights have fragmentation factor 1.0; equal heights use 0.8. Common capacity is
aggregated once per block-period and uses the minimum temporal weight and
compatible capacity of both endpoints, avoiding duplicate bay capacity.

Finite propagation multiplies the current path score by edge score and decay,
subject to edge/path thresholds, neighbor limits, and maximum depth. It is
reactive rather than proactive: the first impact solve never releases graph
neighbors. If its incumbent has shortage, deficient pairs become pressure
nodes; optional `full` then propagates one layer of dependency neighbors before
candidate expansion. Zero-demand nodes can influence the graph but never create
reservation or arrival variables. Progressive Repair expands the local domain
and finally restores all compatible bays through global recovery.

## Realized recourse

Planned and fallback placements call the same `feasible_take` function. It
checks remaining reservation, requested quantity, size, live capacity, old and
planning-ship release, and height compatibility. Failed planned quantities are
reported separately and remain eligible for fallback; they are not double
counted in placement conservation.

Fallback candidates are ordered deterministically by same planned block,
existing ship/POD support, realized outbound conflict, distance, free capacity,
remaining reservation, and bay name. Execution state is validated after every
period in test mode and at every cycle boundary.

## Realized evaluation

Each non-overlapping 24-hour window reports planned, infeasible, fallback, and
unplaced quantities; rates; distance; realized inbound/outbound overlap;
ship/POD bay support; support activation; and block utilization statistics.
These space states are sampled after every executed 6-hour period. Peak
utilization and maximum spread are within-cycle maxima, deviation is averaged
over periods, and bay concentration is weighted by its number of ship/POD
period observations. Forecast diagnostics and plan revision metrics remain
separate and are never interpreted as realized totals.

The former quality-polish stage is disabled by the experiment protocol after it
showed no accepted-incumbent improvement in the Pilot matrix.

## Wall-clock and ablation contract

Every configuration uses the same per-cycle wall-clock deadline. Preprocessing,
model construction, solving, extraction, and validation are timed explicitly.
`core` configurations do not pay for impact scoring they do not use. The sole
difference between `full_direct` and `full` is dependency propagation, including
the graph construction and propagation time that mechanism requires.

Stage diagnostics include binary/total variables, constraints, nodes, solution
count, stage first-incumbent time, and reliable Gurobi bound/gap attributes.
Cycle first-incumbent time starts before preprocessing. Because multiobjective
attributes are version-dependent, unavailable bound, gap, and root-relaxation
values are reported as `None` rather than inferred.
