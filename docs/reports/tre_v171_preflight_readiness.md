# TRE v1.7.1 preflight readiness

> Status update (2026-08-06): candidate v2 failed the online-runtime gate in
> its first five-method block. The run was stopped early and is documented in
> `docs/reports/tre_v171_preflight_attempt_v2.md`. This readiness plan is kept
> as the frozen pre-run specification, not as evidence that the gate passed.

- Preparation date: 2026-08-05
- Behavior-bearing algorithm commit: `ba3a7266c27c3ab7ff2fde35cf6397d9d8b89c9b`
- Reporting/preflight code commit: `56e44bea5ab7bdcb413681bfa8765d3c33e7bd4f`
- Planned freeze tag: `rolling-v4.6-objective-only-stability-preflight-candidate-v2`
- Problem protocol: `rolling-v4.6-objective-only-stability`
- Algorithm version: `lead-aware-aggregate-lp-residual-global-repair-v1.7.1`
- Result schema: `rolling-results-v16`

## Scope of the post-development revision

The v16 revision changes reporting and publication auditing only. External
literature-baseline rows now report `common_ex_post_accounting`, while core
MIP rows report the configured epigraph/exact stability formulation. Default
analysis includes planned infeasibility, fallback, pre-recovery shortfall,
physical recovery, displaced reservations, and final unplaced quantity. No
optimization, rolling execution, or recovery decision changed, so the sealed
72-row development matrix was not rerun.

The complete test suite passed with 168 tests and 9 subtests. A rolling
`kp_dos` result-row smoke confirmed the method-specific stability field. The
sealed development CSV was re-summarized in memory with all six recovery-funnel
fields and no consistency error.

## Frozen preflight inputs

Three existing preflight indexes were revalidated against every bundle hash.
They contain 24 bundles on seeds 700--702, all with an integer zero-shortage
packing certificate and a frozen 60-second per-cycle budget.

| Seed | Index SHA-256 |
|---:|---|
| 700 | `9d7078193b812c38de13a5f4fcc7c1166957c8e5ae3cfd49b3228b7f63793332` |
| 701 | `dd0bc8e1a94e1fb9bf337cde4bdd5cc0731d8fa871b3aee9cadace54e1c2164a` |
| 702 | `23f4dc3cd4305e3fdec73bb121419ca48a39f747a95d102690a4932426c48713` |

The main preflight matrix is frozen at five methods (`core_start`,
`full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`), the `business`
operation-weight profile, frozen DRA parameters, one thread, and a 1% MIP gap.
The expected matrix has 120 rows. No command-level time override is permitted.

## Run command

Run from the repository root after checking out the annotated candidate tag:

```powershell
python scripts/run_formal_matrix.py `
  --bundle-indexes `
  "local_results/protocol_v2_pnc_yangshan/assembled_instances/preflight/pnc_yangshan_v2_semisynthetic_preflight_index.json" `
  "local_results/protocol_v2_pnc_yangshan/assembled_instances/preflight_seed701/pnc_yangshan_v2_semisynthetic_preflight_index.json" `
  "local_results/protocol_v2_pnc_yangshan/assembled_instances/preflight_seed702/pnc_yangshan_v2_semisynthetic_preflight_index.json" `
  --experiment-set main `
  --experiment-phase preflight `
  --threads 1 `
  --mip-gap 0.01 `
  --operation-weight-profile business `
  --output "local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v2/main_gate/results/business_main.csv"
```

If interrupted, repeat the identical command with `--resume`. Do not change
the output root, profile, method set, indexes, or runtime settings.

## Acceptance checks

Before any interpretation, require:

1. exactly 120 rows and a complete manifest with `all_ok=true`;
2. no failed row, independent-validation failure, online deadline miss, dirty
   identity, duplicate identity, or normalized-score accounting failure;
3. exactly the five frozen methods and seeds 700--702;
4. `business` weights on every row and frozen DRA parameters;
5. `epigraph_only` on core rows and `common_ex_post_accounting` on literature
   rows, with zero formulation-audit mismatches;
6. separate reporting of planned infeasibility, pre-recovery shortfall,
   physical recovery, displaced reservations, and final unplaced quantity;
7. paired candidate comparisons on identical instance/seed keys.

Preflight results may diagnose the frozen candidate but do not authorize a
formal run. `FORMAL_RESULT_AUTHORIZED` and manifest `freeze_authorization`
remain false until a new untouched confirmatory set is registered.
