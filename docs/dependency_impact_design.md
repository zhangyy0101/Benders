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
history, and quality polishing. Continuing in a bay already occupied by the
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
candidate domains are built. Its concentration bound uses every compatible
`(ship, POD, bay)` combination; distance and conflict use total forecast
quantity; occupancy balance uses the number of block-period deviations. Every
stage receives this same dictionary.

Block balance is inventory occupancy utilization, not equipment workload. For
each block and period, occupancy is divided by that block's own total bay
capacity. The objective minimizes deviations from average block utilization,
which remains meaningful when block capacities differ.

## Time-dependent capacity and block scores

Physical residual capacity is calculated for every bay and period after locked
old inventory, actual inventory, and their release times. The initial dependency
graph uses this physical capacity. After direct and propagated pairs are known,
positive-demand unaffected pairs are frozen. Baseline residual capacity deducts
their inherited, time-dependent reservation commitments. Final candidate
ranking and allowed-region construction use this baseline capacity. Affected
pairs remain adjustable and are not deducted as frozen commitments.

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
subject to edge/path thresholds, neighbor limits, and maximum depth. Propagation
from an increase/new pair is labelled `pressure`; propagation from a
decrease/disappeared pair is labelled `release_opportunity`.

Direct pairs receive historical support and leading ranked blocks. A release-
opportunity pair additionally receives the released ancestor's historical
blocks. Zero-demand nodes influence propagation but never create reservation or
arrival variables. Shortage repair adds deficient pairs as pressure nodes,
propagates one extra layer in `full`, expands candidates, and finally restores
all compatible bays through global recovery.

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

Quality polish uses the same utilization concept as the MIP. Horizon-end
occupancy includes locked, actual, and planned inventory that remains present,
then divides by block capacity. Its normalized contribution combines support,
distance, overlap, and positive utilization overload using weights from
`config.py`.

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
