# TRE v1.7.3 preflight candidate v4 readiness

Candidate v3 is permanently failed at the online-runtime gate. Version 1.7.3
passes the complete test suite and both failure-instance regressions documented
in `tre_v173_runtime_fix_gate.md`. This authorizes a new preflight attempt only;
it does not authorize formal execution.

Candidate v4 retains the prespecified 120-row matrix:

- seeds 700, 701, and 702;
- 24 zero-shortage-oracle-certified bundles;
- methods `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`;
- business operation weights and frozen DRA parameters;
- one thread, 1% MIP gap, and the unchanged 60-second per-cycle bundle budget.

Run sequentially from the clean annotated candidate-v4 tag and write only to
the new candidate-v4 root:

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
  --output "local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v4/main_gate/results/business_main.csv"
```

Require exactly 120 rows, `complete=true`, `all_ok=true`, and zero deadline,
missing-incumbent, validation, identity, formulation, and normalized-score
accounting failures before interpretation. Do not resume or merge any v2 or v3
artifact. `FORMAL_RESULT_AUTHORIZED` and manifest `freeze_authorization` remain
false after preflight unless a new untouched confirmatory set is separately
registered and authorized.

