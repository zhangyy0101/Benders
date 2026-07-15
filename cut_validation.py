"""Independent cut and aggregate-relaxation validation helpers."""
from gurobipy import GRB
from model_recourse import GlobalRecourseOracle
def validate_optimality_cut(data,weights,cut,points,tolerance=1e-5):
    oracle=GlobalRecourseOracle(data,weights);worst=0
    for p in points:
        oracle.update_rhs(p["alloc_boxes"]);status=oracle.solve()
        if status==GRB.OPTIMAL:worst=max(worst,-cut.value_at({**p,"eta":oracle.objective_value()}))
    return {"valid":worst<=tolerance,"max_violation":worst}
def validate_feasibility_cut(cut,feasible_points,tolerance=1e-5):
    worst=max([-cut.value_at(p) for p in feasible_points]+[0]);return {"valid":worst<=tolerance,"max_violation":worst}
