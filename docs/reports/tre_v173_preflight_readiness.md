# TRE v1.7.3 preflight candidate v5 readiness

Candidate v3 is permanently failed at the online-runtime gate. Version 1.7.3
passes the complete test suite and both failure-instance regressions documented
in `tre_v173_runtime_fix_gate.md`. This authorizes a new preflight attempt only;
it does not authorize formal execution.

Candidate v4 was superseded before any solver row was started because a legacy
candidate-v3 resume process was discovered after its tag. Candidate v5 changes
only the run-control audit and retains the prespecified 120-row matrix. The
runner now rejects a dirty Git tree, a non-preflight index, any command-line
time override, non-frozen solver parameters or methods, and accidental output
overwrite before the first solver call:

- seeds 700, 701, and 702;
- 24 zero-shortage-oracle-certified bundles;
- methods `core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`;
- business operation weights and frozen DRA parameters;
- one thread, 1% MIP gap, and the unchanged 60-second per-cycle bundle budget.

Two delayed background launches after the v5 tag produced overlapping,
incomplete 3-row and 4-row checkpoints outside the declared exclusive
foreground protocol. Both are retained in the preflight quarantine and record
the same two core-method deadline misses. They are diagnostic evidence, not a
passed preflight, and must not be resumed or merged. The controlled retry uses
a fresh detached checkout and a new output root.

Run sequentially from the clean annotated candidate-v5 tag and write only to
the new candidate-v5 root:

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
  --output "local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v5_controlled_retry1/main_gate/results/business_main.csv"
```

Require exactly 120 rows, `complete=true`, `all_ok=true`, and zero deadline,
missing-incumbent, validation, identity, formulation, and normalized-score
accounting failures before interpretation. Do not use `--resume`, and do not
merge any v2, v3, or quarantined v5 artifact. Run through one managed foreground
process only; do not use Task Scheduler or a launcher script.
`FORMAL_RESULT_AUTHORIZED` and manifest `freeze_authorization` remain false
after preflight unless a new untouched confirmatory set is separately
registered and authorized.

The complete pre-run audit is recorded in
`tre_v173_preflight_candidate_v5_audit.md`. Preparation does not itself start
the matrix; launch requires a separate user confirmation.
