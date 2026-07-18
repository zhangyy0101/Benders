# Dependency-aware impact-region design

## Rolling model semantics

The model rolls every 24 hours, uses 6-hour buckets, a 72-hour receiving window,
and a 96-hour look-ahead. Forecast arrivals are the only future arrivals visible
to the optimizer. Hidden realized arrivals are read only by execution simulation.

A ship occupies its realized inventory and reserved capacity until its known
planned operation-completion period. All of that ship's capacity is released at
once at completion; progressive box-by-box capacity release is not modeled.
Outbound forecasts measure workload conflict only and do not release capacity.

## Direct impact pairs

The basic impact unit is `(ship, group)`. A pair is directly affected when it
belongs to a newly admitted ship, changes by at least the configured relative
threshold, appears with no historical reservation, or disappears despite a
positive historical reservation. A changed group never promotes all other
groups of the same ship automatically.

## Dependency graph

Each positive-demand pair has demand, size, height, arrival profile, historical
blocks, eligible blocks, ranked candidate blocks, and compatible capacity by
block. Two pairs are linked only when they have the same size and share candidate
block resources. The edge score is

```text
fragmentation_factor * (
    0.35 * candidate-block Jaccard overlap
  + 0.25 * arrival-profile cosine similarity
  + 0.25 * common-capacity pressure
  + 0.15 * historical-block Jaccard overlap
)
```

Different heights receive fragmentation factor 1.0 because they compete for an
empty bay but cannot coexist. Equal heights receive 0.8. Different sizes do not
share bays and have no dependency edge.

## Finite-depth propagation and candidate regions

Direct pairs start with path score 1. An eligible edge multiplies the current
path score by its dependency score and the decay factor. Paths below the path
threshold are discarded, propagation has a fixed maximum depth, and each node
keeps only its strongest configured number of neighbors. Tuple ordering breaks
ties, making propagation deterministic.

Direct pairs receive historical blocks plus the leading ranked alternatives.
Propagated pairs receive historical blocks plus at least one new alternative.
Unaffected pairs with history remain in historical blocks. A positive-demand
pair with neither impact status nor history is treated as a logic error.

If shortage remains, deficient pairs become direct repair pairs. In `full`, one
additional dependency layer joins their repair region. Candidate batches expand
progressively, and final global repair restores every size-compatible bay.
Quality polishing expands alternatives only for high-cost affected pairs.

## Stability accounting

Plan revision is reported as cancellation quantity, mandatory demand reduction,
discretionary cancellation, new bay count, block reallocation quantity, and
their weighted stability cost. Mandatory demand reduction and forecast shortage
do not consume the discretionary cancellation allowance. They remain explicit
diagnostics rather than being hidden inside a single ambiguous measure.

## Prediction, revision, and realization

Forecast diagnostics describe one complete overlapping 96-hour optimization
window, including predicted shortage and predicted operational cost. Plan
revision metrics describe the change from the inherited plan at that replan.
Realized metrics count only the next executed 24 hours: arrivals, planned and
fallback placements, unplaced boxes, distance, and actual inbound/outbound
overlap. Only realized execution metrics may be summed as operational outcomes
across rolling cycles.

## Ablation contract

`full_direct` and `full` use identical MIP starts, stability allowances,
progressive repair, global recovery, and quality polishing. Their only difference
is dependency propagation: `full_direct` uses direct pairs only, while `full`
adds graph-propagated pairs and dependency-aware shortage repair.
