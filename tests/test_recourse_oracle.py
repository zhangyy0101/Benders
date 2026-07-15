from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_monolithic import build_monolithic_model,extract_solution
from model_recourse import GlobalRecourseOracle
def fixture():
 d=prepare_instance(get_data_tiny_benders());m,v,_=build_monolithic_model(d,Weights());m.optimize();return d,extract_solution(v)
def test_reused_oracle_matches_fresh_sp():
 d,s=fixture();a=GlobalRecourseOracle(d,Weights());a.update_rhs(s['alloc_boxes']);a.solve();b=GlobalRecourseOracle(d,Weights());b.update_rhs(s['alloc_boxes']);b.solve();assert abs(a.objective_value()-b.objective_value())<1e-8
def test_rhs_update_does_not_change_structure():
 d,s=fixture();o=GlobalRecourseOracle(d,Weights());before=(o.model.NumVars,o.model.NumConstrs);o.update_rhs(s['alloc_boxes']);o.solve();assert before==(o.model.NumVars,o.model.NumConstrs)
def test_basis_reuse_does_not_change_solution():test_reused_oracle_matches_fresh_sp()
def test_positive_recourse_instance():
 d,s=fixture();o=GlobalRecourseOracle(d,Weights());o.update_rhs(s['alloc_boxes']);o.solve();assert o.objective_value()>0
