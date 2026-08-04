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
- candidate algorithm: `lead-aware-aggregate-lp-residual-global-repair-v1.7.1`;
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
stage.

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

Before version 1.7.1 is authorized for a confirmatory formal run, register an
untouched seed set or an independent operational time window in the V3
manifest. Do not select the primary weight profile from any V3 result. All
profile definitions, normalization equations, evaluation panels, and stopping
rules must be frozen in a clean tagged commit before the new confirmatory set
is opened.

Formal statistical summaries use two-sided Student-t 95% confidence intervals.
Wilcoxon signed-rank tests are reported only with at least five nonzero paired
differences, and their p-values receive a Holm correction within each metric
family. The default formal audit rejects mixed protocols or commits, duplicate
identities, failed/invalid/late rows, missing bundle hashes, unexpected seeds,
provisional public sources, score-accounting gaps, and incomplete manifests.

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

## Gates before a new formal tag

1. Implement and unit-test the reachable scale equations, weight-profile
   plumbing, residual-shortage and restricted-build-timeout global recovery,
   objective-only stability policy, and exact support indicators without
   changing the three objective priorities.
2. Run development and preflight cases only; record raw, normalized, scale,
   weight, and weighted-contribution fields for every operations component.
3. Confirm that every stage receives the same unrestricted scale dictionary.
4. Confirm that the business and sensitivity profiles do not mix output roots
   or resume identities.
5. Select and register a new untouched confirmatory set.
6. Commit a clean worktree, pass the complete test suite, freeze the V3
   manifest, and create a new annotated formal tag.
