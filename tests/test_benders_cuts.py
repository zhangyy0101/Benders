import copy
from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_monolithic import build_monolithic_model,extract_solution
from model_recourse import BendersCutPool,GlobalRecourseOracle
def setup():
 d=prepare_instance(get_data_tiny_benders());m,v,_=build_monolithic_model(d,Weights());m.optimize();s=extract_solution(v,d);o=GlobalRecourseOracle(d,Weights());return d,s,o
def test_optimality_cut_tight_at_generation_point():
 d,s,o=setup();p={'alloc_boxes':s['alloc_boxes'],'eta':0};o.update_rhs(p['alloc_boxes']);o.solve();q=o.objective_value();c=o.build_optimality_cut(p);assert abs(c.value_at({**p,'eta':q}))<1e-6
def test_optimality_cut_is_global_lower_bound():
 d,s,o=setup();p={'alloc_boxes':s['alloc_boxes'],'eta':0};o.update_rhs(p['alloc_boxes']);o.solve();c=o.build_optimality_cut(p);other=copy.deepcopy(p)
 for k in other['alloc_boxes']:other['alloc_boxes'][k]=min(10,other['alloc_boxes'][k]+1)
 o.update_rhs(other['alloc_boxes']);o.solve();assert c.value_at({**other,'eta':o.objective_value()})>=-1e-5
def test_positive_recourse_generates_cut():test_optimality_cut_tight_at_generation_point()
def test_cut_dual_signs_for_le_constraints():
 d,s,o=setup();o.update_rhs(s['alloc_boxes']);o.solve();assert all(c.Pi<=1e-8 for c in o.storage.values())
def test_farkas_cut_violates_generation_point():
 d,s,o=setup();z={'alloc_boxes':{k:0 for k in s['alloc_boxes']},'eta':0};o.update_rhs(z['alloc_boxes']);o.solve();c=o.build_feasibility_cut(z);assert c.value_at(z)<-1e-6
def test_farkas_cut_keeps_known_feasible_points():
 d,s,o=setup();z={'alloc_boxes':{k:0 for k in s['alloc_boxes']},'eta':0};o.update_rhs(z['alloc_boxes']);o.solve();c=o.build_feasibility_cut(z);assert c.value_at({'alloc_boxes':s['alloc_boxes'],'eta':0})>=-1e-6
def test_no_x_only_nogood_fallback():
 d,s,o=setup();z={'alloc_boxes':{k:0 for k in s['alloc_boxes']},'eta':0};o.update_rhs(z['alloc_boxes']);o.solve();c=o.build_feasibility_cut(z);assert c.alloc_coefficients
def test_farkas_constant_terms_complete():
 d,s,o=setup();z={'alloc_boxes':{k:0 for k in s['alloc_boxes']},'eta':0};o.update_rhs(z['alloc_boxes']);o.solve();assert abs(o.build_feasibility_cut(z).constant)>0
def test_no_distance_double_counting():
 from model_master import build_master_model
 d,s,o=setup();m,v,_=build_master_model(d,Weights());assert not any(name in v for name in ('din','in_share','g_bal'))
def test_duplicate_cut_signature():
 d,s,o=setup();o.update_rhs(s['alloc_boxes']);o.solve();c=o.build_optimality_cut({'alloc_boxes':s['alloc_boxes'],'eta':0});p=BendersCutPool();assert p.add(c) and not p.add(c)
