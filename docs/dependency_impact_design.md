# Dependency-aware impact-region design

## Rolling information boundary

The optimizer receives current realized inventory, the unexecuted previous
reservation, external arrival/outbound forecasts, and external planned release
times. Hidden future arrivals and realized release delays are available only to
the execution simulator. Planned vessel completion is generated independently
of hidden realized container totals. Synthetic forecasts and hidden arrivals
are generated as independent draws from a public booking baseline; only the
forecast draw enters the optimization snapshot.

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
The MIP uses exact linear max formulations, and validation recomputes all values
from the plans.

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

Base residual capacity is calculated for every bay and period after accounting
for locked old inventory, actual inventory, and their release times. For each
ship-group and block, compatible capacity is calculated only from bays with the
correct size and a compatible live height type.

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
ship/POD bay support; new support; and block utilization statistics. Forecast
diagnostics and plan revision metrics remain separate and are never interpreted
as realized totals.

## Wall-clock and ablation contract

Every configuration uses the same per-cycle wall-clock deadline. Preprocessing,
model construction, solving, extraction, and validation are timed explicitly.
`core` configurations do not pay for impact scoring they do not use. The sole
difference between `full_direct` and `full` is dependency propagation, including
the graph construction and propagation time that mechanism requires.
