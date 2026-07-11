# Pre-paper-exp-v1 regression baseline

This directory records the solver behavior before Task 01 changes. It is a
development regression artifact, not a paper result. The recoverable source
point is Git tag `pre-paper-exp-v1` at commit
`2120e50e81b2b20a6fd05c31fd560a23c7beaa86`.

Environment:

- Python 3.12.0
- Gurobi 13.0.0, licensed on the baseline machine
- Windows / PowerShell
- branch created after capture: `paper-exp-v1-development`

Commands (stdout/stderr are under `logs/`; complete solver summaries are under
`runs/`):

```text
python solve_direct_gurobi.py --instance tiny --time 5 --mip-gap 0 --threads 1 --output-root baseline/pre_paper_exp_v1/runs --quiet
python main.py --instance tiny --total-core-time 5 --mip-gap 0 --threads 1 --output-root baseline/pre_paper_exp_v1/runs
python solve_direct_gurobi.py --instance tiny_concentration --time 5 --mip-gap 0 --threads 1 --output-root baseline/pre_paper_exp_v1/runs --quiet
python main.py --instance tiny_concentration --total-core-time 5 --mip-gap 0 --threads 1 --output-root baseline/pre_paper_exp_v1/runs
python solve_direct_gurobi.py --instance 3new6old --time 8 --mip-gap .03 --threads 1 --output-root baseline/pre_paper_exp_v1/runs --quiet
python main.py --instance 3new6old --total-core-time 8 --mip-gap .03 --threads 1 --output-root baseline/pre_paper_exp_v1/runs
```

Observed headline results:

| method | instance | status | UB | LB | gap |
|---|---|---|---:|---:|---:|
| Direct | tiny | OPTIMAL | 21000.0 | 21000.0 | 0 |
| BBC | tiny | OPTIMAL | 21000.0 | 21000.0 | 0 |
| Direct | tiny_concentration | OPTIMAL | 19333.333333 | 19333.333333 | ~0 |
| BBC | tiny_concentration | OPTIMAL | 19333.333333 | 19333.333333 | 0 |
| Direct | 3new6old | TIME_LIMIT, no incumbent | — | 16439.296740 | — |
| BBC | 3new6old | no exact recourse-feasible incumbent in 8 s | — | — | — |

The tiny summary files contain the objective components and runtimes. The two
short `3new6old` runs are intentionally retained as unsuccessful-incumbent
baseline outcomes rather than being tuned or relabeled.
