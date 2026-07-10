"""Equal-budget operational/concentration experiments for Route B."""
from __future__ import annotations
import argparse,csv,json,os,time
from config import MasterWeights,Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES,solve_direct_alns_pipeline,solve_direct_gurobi
from solver_true_benders import solve_true_benders_pipeline

FIELDS="instance seed algorithm budget runtime status ub lb gap open_cost concentration_cost distance_cost balance_cost conflict_cost concentration_available concentration_enabled concentration_weight concentration_raw_used_bays concentration_normalized concentration_scale used_bays_total root_open_bound root_concentration_bound root_eta_bound aggregate_recourse_bound cuts sp_solves callback_time alns_improvement nodes alloc_domain".split()
def configs(suite):
    if suite=="concentration":return [{"algorithm":f"concentration_weight_{w}","weight":w,"enabled":w>0} for w in (0,2,5,10,20)]
    return [{"algorithm":"model_o_without_concentration","weight":0,"enabled":False},{"algorithm":"model_c_joint_concentration","weight":10,"enabled":True},{"algorithm":"direct_joint_concentration","weight":10,"enabled":True,"direct":True},{"algorithm":"direct_warm_alns_joint_concentration","weight":10,"enabled":True,"direct_alns":True}]
def run_one(instance,seed,cfg,budget,threads,domain):
    data=prepare_instance(INSTANCES[instance]());weights=Weights(master=MasterWeights(concentration=cfg["weight"]));started=time.perf_counter()
    if cfg.get("direct_alns"):
        r=solve_direct_alns_pipeline(data,weights,total_time=budget,mip_gap=.03,threads=threads,seed=seed,alloc_domain=domain,concentration_enabled=cfg["enabled"]);components=r.get("components") or {};con=components.get("concentration",{});root={};cuts=sp=callback=None;alns=r.get("alns",{}).get("improvement");nodes=r.get("nodes")
    elif cfg.get("direct"):
        r=solve_direct_gurobi(data,weights,time_limit=budget,threads=threads,seed=seed,alloc_domain=domain,concentration_enabled=cfg["enabled"]);components=r.get("components") or {};con=components.get("concentration",{});root={};cuts=sp=callback=alns=None;nodes=r.get("nodes")
    else:
        r=solve_true_benders_pipeline(data,weights,total_core_time=budget,threads=threads,seed=seed,alloc_domain=domain,concentration_enabled=cfg["enabled"]);components=r.get("core_best",{}).get("components",{});con=r.get("concentration",{});root=r.get("phase0_root_prepass",{});main=r.get("phase3_bbc",{});cuts=r.get("total_unique_cuts");sp=main.get("sp_statistics",{}).get("sp_solve_count");callback=main.get("cut_statistics",{}).get("callback_time");alns=r.get("phase2_alns",{}).get("improvement");nodes=main.get("nodes");r={**r,**r.get("core_best",{}),"status_name":main.get("status_name")}
    return {"instance":instance,"seed":seed,"algorithm":cfg["algorithm"],"budget":budget,"runtime":time.perf_counter()-started,"status":r.get("status_name"),"ub":r.get("ub"),"lb":r.get("lb"),"gap":r.get("gap"),"open_cost":components.get("open_cost"),"concentration_cost":components.get("concentration_cost"),"distance_cost":components.get("distance_cost"),"balance_cost":components.get("balance_cost"),"conflict_cost":components.get("conflict_cost"),"concentration_available":con.get("available"),"concentration_enabled":con.get("enabled"),"concentration_weight":cfg["weight"],"concentration_raw_used_bays":con.get("raw_used_bays"),"concentration_normalized":con.get("normalized"),"concentration_scale":con.get("scale"),"used_bays_total":con.get("used_bays_total"),"root_open_bound":root.get("master_open_bound"),"root_concentration_bound":root.get("master_concentration_bound"),"root_eta_bound":root.get("master_eta_bound"),"aggregate_recourse_bound":root.get("aggregate_recourse_bound"),"cuts":cuts,"sp_solves":sp,"callback_time":callback,"alns_improvement":alns,"nodes":nodes,"alloc_domain":domain}
def main():
    p=argparse.ArgumentParser();p.add_argument("--instances",nargs="+",choices=INSTANCES,default=["tiny_concentration"]);p.add_argument("--seeds",nargs="+",type=int,default=[0]);p.add_argument("--total-core-time",type=float,default=20);p.add_argument("--threads",type=int,default=1);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--suite",choices=("quick","concentration"),default="quick");p.add_argument("--output",default="experiments");a=p.parse_args();os.makedirs(a.output,exist_ok=True);rows=[run_one(i,s,c,a.total_core_time,a.threads,a.alloc_domain) for i in a.instances for s in a.seeds for c in configs(a.suite)]
    with open(os.path.join(a.output,"results.csv"),"w",newline="",encoding="utf8") as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    with open(os.path.join(a.output,"results.json"),"w",encoding="utf8") as f:json.dump(rows,f,indent=2)
    print(f"wrote {len(rows)} equal-budget rows")
if __name__=="__main__":main()
