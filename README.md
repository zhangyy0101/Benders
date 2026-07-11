# Yard allocation / Benders research code

The repository is organized by responsibility rather than by experiment stage.

## Entry points

- `main.py` — current provisional BBC pipeline CLI.
- `solve_direct_gurobi.py` — monolithic Direct Gurobi CLI and Direct+ALNS baseline.
- `run_experiments.py` — configuration-aware, resumable experiment runner.
- `scripts/` — smoke tests, benchmark build/audit, and exact regression gates.

## Model and algorithms

- `model_*.py` — canonical master, monolithic, recourse, concentration, and lower-bound formulations.
- `solver_true_benders.py` — strengthened true Branch-and-Benders-Cut pipeline.
- `solver_classical_benders.py` — sequential single-cut Classical Benders baseline.
- `solver_alns.py` — adaptive large-neighborhood search.
- `solution_validation.py` / `solution_evaluation.py` — independent feasibility and common KPI evaluation.
- `cut_validation.py` — independent cut checks.

## Data and reproducibility

- `data.py` — legacy built-in instances and preparation/validation.
- `synthetic_instance_generator.py` — deterministic parameterized generator.
- `benchmark_schema.py` / `benchmark_io.py` — canonical raw-instance JSON and SHA-256 digest.
- `instance_registry.py` — built-in and benchmark-file resolution.
- `benchmarks/paper_exp_v1_pilot/` — fixed synthetic pilot suite.
- `baseline/`, `validation/`, `experiments/smoke/` — required regression evidence; do not treat as final paper results.

## Experiment configuration

- `config.py` — objective weights.
- `algorithm_configuration.py` / `algorithm_configurations.py` — configuration identity and provisional candidates.
- `experiment_schema.py`, `experiment_methods.py`, `experiment_runner.py` — method adapters and recoverable result writing.
- `docs/` — fixed problem protocol, data schema, and provisional algorithm configuration schema.

## Verification

```bash
pytest -q
python scripts/run_smoke_tests.py --pure
python scripts/run_smoke_tests.py --gurobi
python scripts/audit_benchmarks.py benchmarks/paper_exp_v1_pilot
```

The current algorithm remains provisional. Mathematical correctness is gated by
`scripts/validate_small_benchmarks.py`; algorithm selection/calibration occurs in later stages.
