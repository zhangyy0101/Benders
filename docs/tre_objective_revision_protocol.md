# TRE objective revision protocol

## Baseline preservation

The equal-weight objective is frozen at commit
`fd506b08c3b0c85d2c576ccf578bb3742d2f6ecc` under the annotated tag
`rolling-v4.4-objective-equal-weight-freeze-v1`. The tag is published to the
`origin` remote. Before the tag was created, the complete test suite passed
with 135 tests and 9 subtests.

The ignored local result roots `local_results/protocol_v2_pnc_yangshan`,
`local_results/formal`, and `local_results/preflight` are preserved in place.
Their non-destructive inventory is
`local_results/archive/objective_equal_weight_freeze_v1/inventory.json`. It
contains 1,139 files totaling 508,076,290 bytes, with aggregate SHA-256
`857d5680c3cc3fe1d9641435b82567add52ca1e2ad3d85fac7eaf830fa5aa2a9`.
No revision run may resume from, overwrite, or merge with those artifacts.

## Objective revision implementation

Development occurs on `research/tre-objective-normalization-v2`. The implemented
version identities are:

- problem protocol: `rolling-v4.6-objective-only-stability`;
- candidate algorithm: `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`;
- result schema: `rolling-results-v16`;
- normalization: `reachable_snapshot_upper_bounds_v2`;
- new local root: `local_results/protocol_v3_tre_objective`.

The shortage--stability--operations lexicographic priorities remain unchanged.
The third-priority operations score uses the revised normalization below. The
controller imposes no hard stability allowance in any domain because no such
business constraint exists; stability remains the second objective. Positive
residual shortage after bottleneck repair enters global safety repair when its
bounded in-budget reserve remains. A restricted model that cannot start within
its stage allocation also transfers to the unrestricted safety stage while the
common online window remains. The scale dictionary must still be calculated
once from the unrestricted snapshot and reused by every restricted and global
stage. At a 60-second cycle budget, the controller reserves 15 seconds for the
safety stage and requires at least 10 seconds to remain before admitting or
constructing its unrestricted model. These are allocations inside the
unchanged common budget, not extra runtime.

### Interpretation boundary for the priority order

The three priorities apply to one optimization snapshot. The controller's
strict incumbent guard also compares only the restricted and repair-stage
candidates generated inside that same execution. It does not use the result of
a separately run `core_start` configuration as a stability bound or reference
solution.

Consequently, the priority order does not imply cross-method dominance of
full-horizon totals. `core_start` and `full_bottleneck` make different early
decisions, which produce different inventories, inherited plans, forecasts,
and feasible regions in later cycles. Both are also solved under a finite
per-cycle time limit and a 1% MIP gap. Their accumulated stability cost can
therefore rank differently even though each accepted within-run stage obeys
the declared shortage--stability--operations ordering.

Reports must distinguish modeled per-snapshot objectives from realized
rolling KPIs. In particular, physical recovery is a deterministic
post-optimization execution fallback and is not a fourth lexicographic
objective. `physical_recovery_placement` is a quantity of boxes placed through
that fallback, not a count of recovery events and not a TEU measure unless an
explicit size conversion is performed. Preflight comparisons must be framed
as feasibility, interface, runtime, and trade-off evidence; claims of
statistical superiority are reserved for the frozen confirmatory experiment.

For positive optimizer-visible arrival quantity \(Q^+\), reachable support set
\(\mathcal S^+\), maximum reachable distance \(d_{max}^+\), \(K\) blocks, and
\(N\) periods, the implemented scales are:

- concentration: \(\max(1, |\mathcal S^+|)\);
- occupancy balance:
  \(\max(1, N\,2\lfloor K^2/4\rfloor/K)\);
- distance: \(\max(1, Q^+d_{max}^+)\);
- inbound/outbound conflict: \(\max(1, Q^+)\).

Zero-arrival, out-of-domain, and post-release pairs do not enlarge the first,
third, or fourth scales. The selected profile is passed explicitly to the MIP
and literature-baseline evaluator, recorded in experiment identity and
metadata, and separated by the summarizer.

Accepted candidate and external-baseline solutions are audited from extracted
physical `reservation` and `din` flows. The audit independently recomputes all
four raw components, their scales, normalized and weighted values, the total
operations score, and the exact support/new-support indicators; it does not
trust the MIP expressions or heuristic-side accounting.

Development version 1.7.0 exposed that a time-limited third-priority solve can
leave the absolute utilization-deviation epigraph above its physical value.
Version 1.7.1 therefore replaces every extracted operations component with the
canonical flow-based evaluation before incumbent comparison and validation;
the modeled-versus-canonical balance slack is retained as a diagnostic only.

Preflight candidate v2 then exposed an implementation-scale defect rather than
a mathematical one: core MIP solutions retained hundreds of thousands of
zero-valued entries, and the canonical occupancy evaluator rescanned the full
arrival-flow map inside every period--block cell. Version 1.7.2 extracts known
physical groups sparsely and accumulates locked, actual, and planned block
loads in one pass. Dense and sparse representations must produce exactly the
same canonical components and independent validation report.

Version 1.7.2 also completes a positive shifted rolling MIP start by clipping
old period flow to the revised forecast, deriving reservation totals and
shortage, and setting the associated integer indicators. It does not inject an
artificial all-shortage start when no positive prior flow exists. The common
60-second budget is unchanged; measured solver-return and sparse
postprocessing tails set the in-budget guards to 2.0 and 4.2 seconds,
respectively. These are algorithm-runtime changes, so no v1.7.1 preflight row
may be retained.

The primary business profile is fixed before implementation as distance 0.40,
balance 0.30, concentration 0.20, and inbound/outbound conflict 0.10. The
prespecified sensitivity profiles are stored in
`docs/specs/formal_run_manifest_v3.json`; the old equal-weight profile is an
ablation, not a competing primary specification.

## Evaluation boundary

Formal outputs already exist for seeds 1000--1009 under objective version
1.4.7, including the 50-row central five-method matrix, the 140-row robustness
matrix, and synthetic formal panels. Under the existing repository rule that a
method revised after formal outcomes have been inspected requires a new
held-out set, those seeds may be reused only for historical or exploratory
paired re-evaluation of the objective change.

The untouched confirmatory set is registered as seeds `2000--2009` before any
corresponding bundle is generated. The V3 manifest, PNC--Yangshan specification,
fully synthetic matrix and sequential execution plan freeze the normalization,
primary and sensitivity weights, panel membership, stopping rules and failure
policy. Do not select or revise the primary weight profile from any V3 outcome.

Formal statistical summaries use two-sided Student-t 95% confidence intervals.
Wilcoxon signed-rank tests are reported only with at least five nonzero paired
differences. Inference is paired by seed inside one prespecified scenario cell;
cells sharing a seed are not pooled as independent observations. P-values
receive a Holm correction within each cell and metric family. The audit rejects
mixed protocols or commits, duplicate identities, missing bundle hashes,
unexpected seeds, provisional public sources, score-accounting gaps, and
structurally incomplete manifests. Algorithm deadline, no-incumbent and
validation failures are retained as outcomes; invalid rows are excluded from
quality metrics and are never selectively rerun.

## Version 1.7.1 development gate

The 72-row oracle-certified main development matrix completed on seeds
100--102 with zero failed rows, validation failures, deadline misses, dirty
identities, or normalized-score accounting failures. A separate six-row
mechanism panel reached bottleneck repair, and the main panel reached residual
shortage global recovery. Four isolated one-row profile smokes verified weight
profile identity without using their outcomes to select the business weights.
The complete development-only evidence and observed KPI trade-offs are recorded
in `docs/reports/tre_v171_development_gate.md`.

Result schema v16 is a reporting-only correction made after the development
gate. The batch manifest retains the core MIP stability formulation, while
each result row records the formulation/accounting used by the executed
method. Formal auditing rejects a literature-baseline row unless it reports
`common_ex_post_accounting`; core rows must report `epigraph_only` or
`exact_big_m`. Default analysis includes planned infeasibility, fallback,
pre-recovery shortfall, physical recovery, displaced reservations, and final
unplaced quantity. These fields already exist in the sealed development CSV,
so this revision requires re-summarization but not re-optimization.

## Version 1.7.2 runtime-correction gate

Candidate v2 failed before preflight completion because both core MIP methods
exceeded the online window during dense extraction and repeated canonical
accounting. The retained 15-row diagnostic and its sequential confirmation are
historical failure evidence only.

At clean implementation commit
`6c7ed7dbe740199f9de8eb046676eaf75d8f7261`, all 171 tests and 9 subtests pass.
The frozen seed-700 March bundle then completed both `core_start` and
`full_bottleneck` under the original 60-second per-cycle budget. The two-row
manifest is complete and `all_ok=true`; neither row has a deadline miss,
missing incumbent, validation failure, predicted shortage, or final unplaced
quantity. Detailed timings and hashes are in
`docs/reports/tre_v172_runtime_fix_gate.md`.

This gate authorizes a new clean preflight candidate, not a formal run. The
entire 120-row preflight matrix must be regenerated under candidate v3.

## Version 1.7.3 controlled preflight gate

Candidate v3 exposed a global-repair admission defect and candidate v4 was
superseded before execution by a run-control contamination audit. The clean
candidate-v5 retry then regenerated the complete 120-row matrix from zero at
commit `e7651b3801836ad15c2d05b2eecb92d4304c2c6a`. Its manifest is complete and
`all_ok=true`; all five methods have 24 valid rows, with zero deadline,
missing-incumbent, validation, and final-unplaced failures. The result and its
non-dominance reporting boundary are recorded in
`docs/reports/tre_v173_preflight_candidate_v5_audit.md`.

This passes the V3 preflight gate. The untouched seeds `2000--2009`, exact
1,050-row matrix and execution policy were subsequently registered without
generating an instance. Formal instance generation remains separately guarded
by the clean exact formal-input tag and an explicit seed-opening confirmation.

## Formal-input freeze checklist

1. Implement and unit-test the reachable scale equations, weight-profile
   plumbing, residual-shortage and restricted-build-timeout global recovery,
   objective-only stability policy, and exact support indicators without
   changing the three objective priorities.
2. Run development and preflight cases only; record raw, normalized, scale,
   weight, and weighted-contribution fields for every operations component.
3. Confirm that every stage receives the same unrestricted scale dictionary.
4. Confirm that the business and sensitivity profiles do not mix output roots
   or resume identities.
5. Select and register a new untouched confirmatory set. Completed with seeds
   `2000--2009`; seeds `1000--1009` are historical only.
6. Freeze the cell-level inference, failure-accounting and sequential batch
   policies together with the exact 1,050-row execution plan.
7. Commit a clean worktree, pass the complete test suite, run the non-generating
   readiness gate, publish the annotated formal-input tag, and repeat the gate
   at that exact tag before any instance generation.
