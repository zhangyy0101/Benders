# TRE v1.7.2 preflight candidate v3 readiness

Candidate v2 is permanently failed at the online-runtime gate. Version 1.7.2
passes the complete test suite and a clean two-method frozen large-instance
regression documented in `tre_v172_runtime_fix_gate.md`. This authorizes a new
preflight attempt only; it does not authorize formal execution.

The candidate v3 matrix remains the prespecified 120 rows:

- seeds 700, 701, and 702;
- 24 zero-shortage-oracle-certified bundles;
- methods `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`;
- business operation weights and frozen DRA parameters;
- one thread, 1% MIP gap, and the immutable 60-second per-cycle bundle budget.

Run from the clean annotated candidate v3 tag and write only to the new root:

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
  --output "local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v3/main_gate/results/business_main.csv"
```

Require exactly 120 rows, `complete=true`, `all_ok=true`, and zero deadline,
missing-incumbent, validation, identity, formulation, and normalized-score
accounting failures before interpretation. Do not resume or merge any v2
artifact. `FORMAL_RESULT_AUTHORIZED` and manifest `freeze_authorization` remain
false after preflight unless a new untouched confirmatory set is separately
registered and authorized.
