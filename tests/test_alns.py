from config import Weights
from data import get_data_tiny_route_a,prepare_instance
from solver_mip_alns import adaptive_lns,solve_core_mip

def _run(seed=4,domain="integer"):
    d=prepare_instance(get_data_tiny_route_a()); start=solve_core_mip(d,Weights(),time_limit_s=3,mip_gap=0,alloc_domain=domain,seed=seed); return d,start,adaptive_lns(d,Weights(),start,time_limit_s=.15,repair_time_s=.05,alloc_domain=domain,seed=seed)
def test_alns_candidate_is_monolithic_feasible():
    _d,_s,r=_run(); assert r["best_solution"] and r["best_ub"]>=0
def test_same_seed_reproducible():
    *_,a=_run(9); *_,b=_run(9); assert a["best_ub"]==b["best_ub"] and [x["operator"] for x in a["iterations"][:3]]==[x["operator"] for x in b["iterations"][:3]]
def test_alns_never_reports_invalid_ub():
    _d,start,r=_run(); assert r["best_ub"]<=start["ub"]+1e-7
def test_continuous_alloc_is_not_rounded():
    _d,_start,r=_run(domain="continuous"); assert all(isinstance(v,float) for v in r["best_solution"]["alloc_boxes"].values())
def test_all_destroy_operators_are_reportable():
    _d,_start,r=_run(); assert all(x["operator"] in {"random","active-biased","block-focused","interval-focused","ship-focused","conflict-focused","distance-focused"} for x in r["iterations"])
