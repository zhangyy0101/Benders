# TRE v1.7.3 formal-instance generation readiness

## Decision

The model, algorithm, data design and experiment matrix remain frozen for the
new confirmatory instances. The RC1 generation attempt instantiated 70 of 80
PNC--Yangshan bundles and then stopped before any index, synthetic bundle or
formal result because a Windows temporary path reached 264 characters. The
complete partial output is quarantined and prohibited from reuse.

RC2 changes run control only: the formal root is shortened to
`local_results/tre_v3_rc2`, and the preparation gate rejects an unsafe planned
temporary-path length before opening a seed. Regeneration requires a clean
checkout at the exact annotated tag
`rolling-v4.6-objective-only-stability-formal-input-rc2` and both explicit
flags `--generate --confirm-open-formal-seeds`.

The current confirmatory seeds remain the preregistered `2000--2009`. They were
untouched when registered; RC1 subsequently opened part of their deterministic
instance construction but produced no algorithm result. No seed, factor,
weight, method or stopping rule was changed in response. Retaining the same
preregistered set therefore avoids outcome-based reselection. Seeds
`1000--1009` remain historical/exploratory only.

## RC1 generation incident

- Frozen commit: `178802f2d22ebc40f37312cb6fb056f66ea096f9`.
- Frozen tag: `rolling-v4.6-objective-only-stability-formal-input-rc1`.
- Failure: classic Windows absolute temporary path length `264`.
- Completed before failure: 70 bundles and 70 assembly audits; 45,278,224
  bytes in total.
- Not produced: formal indexes, generation manifest, synthetic bundles and
  algorithm result rows.
- Quarantine: `local_results/quarantine_rc1_path_failure_20260808`.
- Standard-output SHA-256:
  `fbd87b7c356aeea5fd5db29dbf92585f3aa778c9e87494beb8fa29d8fd830ece`.
- Standard-error SHA-256:
  `3f02a53a898a32f8b6c5e880aa520062960a3490bb9abc2c9dda8bddee1ba379`.
- Disposition: preserve for audit, never resume, index or use in the formal
  matrix; regenerate all 280 bundles from zero under RC2.

## Frozen identities and evidence gate

- Problem protocol: `rolling-v4.6-objective-only-stability`.
- Candidate: `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`.
- Result schema: `rolling-results-v16`.
- Normalization: `reachable_snapshot_upper_bounds_v2`.
- Primary operation weights: distance 0.40, balance 0.30, concentration 0.20,
  inbound/outbound conflict 0.10.
- Controlled preflight: 120/120 valid rows, five methods × 24 rows, with zero
  deadline, no-incumbent, validation or final-unplaced failures.
- Execution: one process and one solver thread, sequential batches, exclusive
  host, frozen 1% MIP gap and bundle-level cycle budgets.

The controlled-preflight CSV and manifest hashes, source-design hashes,
untouched-seed registration and generation paths are embedded in the V3 JSON
specifications and are revalidated by the preparation entry point.

The complete repository suite passed before the RC2 formal-input freeze with 186
tests and 16 subtests. All JSON specifications parsed successfully, all changed
Python entry points compiled, and `git diff --check` found no patch errors.

## Frozen matrix

| Evidence family | Expected rows |
|---|---:|
| PNC--Yangshan central five-method comparison | 50 |
| PNC--Yangshan temporal/volume/yard robustness | 140 |
| Operation-weight sensitivity | 60 |
| DRA-RPM parameter sensitivity | 60 |
| Fully synthetic performance panels | 680 |
| Fully synthetic repair-mechanism diagnostics | 60 |
| Total | 1,050 |

The exact 12-batch order is in
`docs/specs/tre_v3_formal_execution_plan.json`. The business-weight reference
and frozen DRA-RPM reference are reused from the central main batch; they are
not rerun merely to inflate the sample. The matrix deliberately omits an
additional time-budget sensitivity grid because the scale panel already fixes
20/60/120-second budgets and the main claim does not require a second post-hoc
time family.

## Statistical and failure policy

The independent replication unit is one seed within one prespecified scenario
cell. Confidence intervals and Wilcoxon tests are computed within that cell;
cells that share a seed are never pooled as independent replicates. Holm
correction is applied within each cell and prespecified metric family.

All requested rows must remain auditable. Deadline/no-incumbent failures count
against the method; validation failures remain in failure accounting but are
excluded from quality summaries. A quality pair requires two valid rows.
Selective reruns are prohibited. Environmental contamination invalidates the
whole affected batch, which is quarantined and restarted from zero.

## Safe entry point

The non-generating final gate is:

```powershell
python scripts/prepare_tre_v3_formal_instances.py --check-only
```

It verifies the clean Git identity and exact tag, 22 frozen PNC/Yangshan source
files, current specifications, 120-row controlled-preflight hashes, absent
RC2 output root, safe Windows path budget, 13 guarded generation commands and
the expected 310 + 740 result-row design. The default command is also
non-generating.

Only after that gate passes may the user deliberately open the registered
seeds with:

```powershell
python scripts/prepare_tre_v3_formal_instances.py `
  --generate --confirm-open-formal-seeds
```

The RC2 readiness work does not open or generate another instance.
