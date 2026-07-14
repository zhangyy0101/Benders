import solver_true_benders as stb


def test_repair_budget_formula_and_main_uses_deadline_remainder(monkeypatch):
    source = __import__("inspect").getsource(stb.solve_true_benders_pipeline)
    assert "min(max(float(primal_repair_min_seconds),repair_planned),float(primal_repair_max_seconds),remaining_time(deadline))" in source
    assert "main_time=remaining_time(deadline)" in source
    assert "total-repair_planned" not in source
