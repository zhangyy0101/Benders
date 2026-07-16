# Yard allocation partial Benders code

Minimal active project for the current POD/size/height yard-allocation model.

- `solver_partial_bbc.py`: current partial branch-and-Benders-cut algorithm;
- `solve_direct_gurobi.py`: monolithic Direct Gurobi baseline;
- `solver_classical_benders.py`: sequential classical Benders baseline;
- `benchmarks/paper_exp_v1_pilot21/`: nine current synthetic instances.

The model uses integer bay-slot reservations, continuous operational flows, ship-POD concentration, and a no-mixed-height bay constraint. Under the default `ship_complete` policy, old-container capacity is released only after the corresponding old ship has completely left the yard.

Run one built-in instance:

```bash
python main.py --instance tiny --time 30 --mip-gap 0
```

Compare methods on the retained benchmark suite:

```bash
python run_experiments.py --instances S01 M01 L01 --methods direct bbc_candidate classical_benders --budget 60
```

Compile-check the active source:

```bash
python -m py_compile *.py
```
