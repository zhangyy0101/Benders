import inspect
from solver_true_benders import solve_bbc_phase,solve_true_benders_pipeline
def test_pipeline_default_shares_and_node_cuts():
 p=inspect.signature(solve_true_benders_pipeline).parameters;assert [p[x].default for x in ("root_time_share","warm_start_time_share","alns_time_share","main_bbc_time_share")]==[.05,.15,.25,.55];assert p["node_cuts"].default is False;assert inspect.signature(solve_bbc_phase).parameters["node_cuts"].default is False
