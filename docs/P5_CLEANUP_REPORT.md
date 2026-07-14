# P5 repository and entry-point cleanup report

## Scope and branch protection

- Immutable tag: `algorithm-candidate-v1-baseline` at `a4b8b2a`.
- Development branch: `algorithm-candidate-v2-development`.
- Candidate-v1 hash remains `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`.
- No candidate-v2 strengthening has been implemented or run.

## Entry points

| Entry point | Role | Default |
|---|---|---|
| `scripts/run_candidate_experiments.py` | Unique recommended resumable candidate experiment runner | Pilot2.1, candidate-v1, seed 0, one thread, 3% gap |
| `main.py` | Configuration-driven single-instance runner | candidate-v1 |
| `run_experiments.py` | Generic/legacy multi-method runner | Explicitly not candidate evidence |
| `solve_direct_gurobi.py` | Direct/Direct+ALNS baselines | Unchanged |
| `scripts/run_candidate_v1_smoke.py` | Candidate-v1 P5 regression gate | XS01 and S01 short smoke |

Recommended formal command:

```bash
python scripts/run_candidate_experiments.py --algorithm-config algorithm-candidate-v1 --require-clean-git
```

The candidate runner supports instances, budget, seeds, threads, MIP gap, output, resume, failed-run rerun, optional solution saving, registered configuration selection, and clean-git enforcement.

## Candidate-v1 immutable proof

- A frozen manifest validator checks every mathematical switch, phase share, status, and hash.
- Backward-compatible defaults for future `aggregate_relaxation_level` and `valid_inequality_profile` fields are read with `get`; they are not written into the candidate-v1 payload.
- Regression tests verify the exact frozen hash and absence of the future fields.
- CLI overrides are renamed and rehashed as `development_override`; they cannot retain the frozen status or name.

## Naming and result identity

New results contain `resolved_algorithm_label`. Candidate-v1 resolves to `aggregate_strengthened_bbc`, while the historical full pipeline resolves to `true_bbc_alns_legacy`. Result identity retains configuration name/version/hash/status, digest, seed, budget, threads, MIP gap, allocation domain, and protocol; environment metadata retains commit and dirty-worktree state.

Candidate/formal runs warn on a dirty worktree and optionally reject it through `--require-clean-git`.

## Status consistency

`docs/pilot21_status.json`, `algorithm_candidate_decision.json`, the candidate decision documents, and README agree:

```json
{
  "candidate_algorithm_frozen": true,
  "candidate_configuration": "algorithm-candidate-v1",
  "final_algorithm_frozen": false,
  "approved_for_public_data_pilot": true
}
```

P4 authorizes development/calibration-set adaptation and testing; final holdout execution remains unauthorized.

P2/P3 directories are explicitly marked as development evidence. `docs/EVIDENCE_HIERARCHY.md` records that the P4 freeze decision supersedes P3's provisional valid-inequalities recommendation without rewriting historical results.

## Verification

- Python compilation: PASS.
- Full tests: 153 passed.
- Candidate-v1 smoke: PASS, 3 runs, 31.84 seconds total wall clock.
- XS01 candidate-v1: OPTIMAL, UB/LB `32466.090558738055 / 32466.09055873805`.
- XS01 C2 equivalence: mathematical switches match and exact objective matches.
- S01 candidate-v1: checker PASS, `LB <= UB`, valid final anytime point; finite-time status `TIME_LIMIT` at 30 seconds.
- Root, warm, and ALNS are disabled; analytic LB and valid inequalities are false; size-level aggregate LB is true.

## P5 boundary

Repository cleanup is complete. Candidate-v2 algorithm improvement has not started; P6A remains the next stage.
