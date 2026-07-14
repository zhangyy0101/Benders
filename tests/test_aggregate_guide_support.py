from solver_aggregate_guide import _diagnostics


def test_support_aggregation_formulas():
    data = {"N": [0, 1], "Intervals": {0: {"dur": 2}, 1: {"dur": 3}}}
    x = {("B1", "J1", 0): 0.5, ("B1", "J1", 1): 1.0, ("B2", "J1", 0): 0.0}
    alloc = {
        ("B1", "J1", "G1", 0): 2.0,
        ("B1", "J1", "G1", 1): 5.0,
        ("B2", "J1", "G1", 0): 0.0,
    }
    z = {("J1", "K1", 20, 0): 1.25, ("J1", "K1", 20, 1): 2.75}
    diagnostics = _diagnostics(data, x, alloc, z)
    assert diagnostics["aggregate_flow_by_ship_size_block"][("J1", 20, "K1")] == 4.0
    assert diagnostics["alloc_support_by_ship_group_bay"][("J1", "G1", "B1")] == {
        "max": 5.0,
        "sum": 7.0,
    }
    assert diagnostics["x_support_by_ship_bay"][("J1", "B1")] == 4.0
    assert diagnostics["fractional_x_count"] == 1
    assert diagnostics["fractional_alloc_count"] == 0
