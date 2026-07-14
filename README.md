# Yard allocation / Benders research code

This repository contains exact Branch-and-Benders-Cut, monolithic, classical Benders, and development experiment tooling for the yard-allocation model.

## Supported candidate entry point

The unique recommended command for candidate evidence is:

```bash
python scripts/run_candidate_experiments.py \
  --instances S01 \
  --budget 30 \
  --algorithm-config algorithm-candidate-v1 \
  --resume
```

Defaults are the fixed Pilot2.1 suite, `algorithm-candidate-v1`, seed 0, one thread, and a 3% MIP gap. Use `--require-clean-git` for formal runs. A dirty worktree always produces a warning.

`main.py` is the supported single-instance configuration-driven CLI:

```bash
python main.py --algorithm-config algorithm-candidate-v1
```

Any field override changes the result to a newly hashed `development_override`; it is never reported as frozen candidate-v1. The historical full pipeline remains explicitly callable with `--algorithm-config bbc_full_current`.

`run_experiments.py` is a generic/legacy multi-method runner. Do not use it to create candidate evidence.

## Reproducibility and evidence

- `benchmarks/paper_exp_v1_pilot21/`: fixed Pilot2.1 synthetic suite.
- `validation/pilot21_exact_fixtures/`: P1 exact correctness evidence.
- `validation/pilot21_small_finite_time/`: P1 finite-time correctness evidence.
- `experiments/internal_screen_fast/`: P2 development screening evidence.
- `experiments/confirmatory_adaptive/`: P3 development confirmation evidence.
- `algorithm_candidate_decision.json`: authoritative P4 freeze decision.
- `docs/EVIDENCE_HIERARCHY.md`: precedence rules for historical evidence.

Candidate-v1 is frozen and approved for public-data development/calibration testing. The final algorithm is not frozen, and final holdout execution is not authorized.

## Verification

```bash
python -m py_compile *.py scripts/*.py
pytest -q
python scripts/run_candidate_v1_smoke.py
```
