"""Reproducible Route-A benchmark and ablation runner (CSV + JSON)."""
from __future__ import annotations
import argparse,csv,json,os,time
from config import AttributeRefinementWeights,Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES,solve_direct_gurobi
from solver_mip_alns import solve_strengthened_mip_alns

FIELDS="instance algorithm seed status runtime nodes root_bound ub lb gap phase1_ub alns_start_ub alns_best_ub alns_improvement phase3_lb alloc_domain handling_rate_scale valid_inequalities epsilon pod_spread weight_spread height_mix attribute_score core_degradation".split()
def configurations(full):
    base=[{"algorithm":"plain_gurobi","plain":True},{"algorithm":"strengthened_core","alns":False,"proof":False,"refine":False},{"algorithm":"core_alns","proof":False,"refine":False},{"algorithm":"core_alns_proof","refine":False},{"algorithm":"full","refine":True},{"algorithm":"without_valid_inequalities","valid":False},{"algorithm":"without_alns","alns":False}]
    if full:
        base += [{"algorithm":f"alloc_{x}","domain":x} for x in ("integer","continuous")]
        base += [{"algorithm":f"handling_{x}","rate":x} for x in (.5,1.0,1.5)]
        base += [{"algorithm":f"epsilon_{x}","epsilon":x} for x in (0,.005,.01,.02,.05)]
        base += [{"algorithm":f"attribute_{x}","attributes":x} for x in ("pod","weight","height","all")]
    return base
def run_one(instance,seed,cfg,t):
    domain=cfg.get("domain","integer"); rate=cfg.get("rate",1.0); valid=cfg.get("valid",True); epsilon=cfg.get("epsilon",.01); attrs=cfg.get("attributes","all"); aw=AttributeRefinementWeights(4 if attrs in ("all","pod") else 0,3 if attrs in ("all","weight") else 0,10 if attrs in ("all","height") else 0); weights=Weights(attribute=aw); data=prepare_instance(INSTANCES[instance](),rate)
    if cfg.get("plain"):
        r=solve_direct_gurobi(data,weights,time_limit_s=t,mip_gap=.03,verbose=False,alloc_domain=domain,add_valid_inequalities=valid); p1=r; alns={}; p3={}; core={"ub":r.get("ub"),"lb":r.get("lb"),"gap":r.get("gap")}; ref={}; components=r.get("components") or {}
    else:
        r=solve_strengthened_mip_alns(data,weights,phase1_time=t,lns_time=t,phase3_time=t,attribute_time=t,attribute_epsilon=epsilon,alloc_domain=domain,add_valid_inequalities=valid,seed=seed,enable_alns=cfg.get("alns",True),enable_proof=cfg.get("proof",True),enable_refinement=cfg.get("refine",True)); p1=r.get("phase1_core_mip",{}); alns=r.get("phase2_alns",{}); p3=r.get("phase3_proof_mip",{}); core=r.get("core_best",{}); ref=r.get("attribute_refinement",{}); components=p1.get("components") or {}
    raw=components.get("raw",{}); runtime=sum(float(x.get("runtime",0) or 0) for x in (p1,alns,p3))+float(ref.get("runtime",0) or 0)
    return {"instance":instance,"algorithm":cfg["algorithm"],"seed":seed,"status":p1.get("status_name","OK" if r.get("ok") else "FAILED"),"runtime":runtime,"nodes":p3.get("nodes",p1.get("nodes")),"root_bound":p3.get("root_bound",p1.get("root_bound")),"ub":core.get("ub"),"lb":core.get("lb"),"gap":core.get("gap"),"phase1_ub":p1.get("ub"),"alns_start_ub":p1.get("ub"),"alns_best_ub":alns.get("best_ub"),"alns_improvement":alns.get("improvement"),"phase3_lb":p3.get("lb"),"alloc_domain":domain,"handling_rate_scale":rate,"valid_inequalities":valid,"epsilon":epsilon,"pod_spread":raw.get("pod_spread"),"weight_spread":raw.get("weight_spread"),"height_mix":raw.get("height_mix"),"attribute_score":ref.get("candidate_attribute_score"),"core_degradation":ref.get("core_degradation")}
def main():
    p=argparse.ArgumentParser();p.add_argument("--instances",nargs="+",choices=INSTANCES,default=["tiny"]);p.add_argument("--seeds",nargs="+",type=int,default=[0]);p.add_argument("--time",type=float,default=5);p.add_argument("--suite",choices=("quick","full"),default="quick");p.add_argument("--output",default="experiments");a=p.parse_args();os.makedirs(a.output,exist_ok=True);rows=[]
    for instance in a.instances:
        for seed in a.seeds:
            for cfg in configurations(a.suite=="full"): rows.append(run_one(instance,seed,cfg,a.time))
    json.dump(rows,open(os.path.join(a.output,"results.json"),"w",encoding="utf8"),indent=2);f=open(os.path.join(a.output,"results.csv"),"w",newline="",encoding="utf8");w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows);f.close();print(f"wrote {len(rows)} rows to {a.output}")
if __name__=="__main__":main()
