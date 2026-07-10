"""Route A: strengthened MIP, adaptive LNS, proof restart and refinement."""
from __future__ import annotations
import math, random, time
from collections import defaultdict
import gurobipy as gp
from gurobipy import GRB
from model_core import build_core_monolithic_model, evaluate_core_solution, extract_solution
from model_common import attribute_score, handling_diagnostics, has_attribute_data, raw_components
from solution_validation import validate_core_solution


def _status(status):
    return {GRB.OPTIMAL:"OPTIMAL", GRB.TIME_LIMIT:"TIME_LIMIT", GRB.INFEASIBLE:"INFEASIBLE", GRB.INTERRUPTED:"INTERRUPTED", GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(status, str(status))


def _start(variables, solution, alloc_domain):
    for name in ("x", "block_use", "alloc_boxes", "in_share", "din", "inv"):
        for key, value in solution.get(name, {}).items():
            if key in variables.get(name, {}):
                variables[name][key].Start = round(value) if alloc_domain == "integer" and name == "alloc_boxes" else value


def solve_core_mip(data, weights, *, time_limit_s, mip_gap, alloc_domain="integer", add_valid_inequalities=True, symmetry_breaking=False,start_solution=None, proof=False, seed=0,threads=None, verbose=False):
    model, variables, expressions = build_core_monolithic_model(data, weights, alloc_domain=alloc_domain, add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking)
    model.Params.OutputFlag = int(verbose); model.Params.TimeLimit = max(0.01, float(time_limit_s)); model.Params.MIPGap = float(mip_gap); model.Params.Seed = int(seed)
    model.Params.Presolve = 2; model.Params.Cuts = 2 if proof else 1; model.Params.MIPFocus = 3 if proof else 1; model.Params.Heuristics = 0.02 if proof else 0.20
    if threads is not None:model.Params.Threads=int(threads)
    if proof: model.Params.Symmetry = 2
    if start_solution: _start(variables, start_solution, alloc_domain)
    root={"bound":None}
    def capture_root(m,where):
        if where==GRB.Callback.MIPNODE and root["bound"] is None and m.cbGet(GRB.Callback.MIPNODE_NODCNT)<.5:
            root["bound"]=float(m.cbGet(GRB.Callback.MIPNODE_OBJBND))
    t0=time.perf_counter(); model.optimize(capture_root); runtime=time.perf_counter()-t0
    has=model.SolCount > 0; solution=extract_solution(expressions["data"], variables) if has else None
    recomputed=evaluate_core_solution(expressions["data"], weights, solution) if has else None
    feasibility=validate_core_solution(expressions["data"],solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities) if has else None
    if has and not feasibility["feasible"]: has=False; solution=None; recomputed=None
    ub=recomputed["total_core_cost"] if recomputed else None
    objective_error=abs(float(model.ObjVal)-ub) if has else None
    if has and objective_error > 1e-5: raise AssertionError("model objective and recomputed core cost differ")
    lb=float(model.ObjBound) if model.Status not in (GRB.INFEASIBLE, GRB.INF_OR_UNBD) else None
    diagnostics=handling_diagnostics(data,solution) if has else None
    return {"ok":has,"status":int(model.Status),"status_name":_status(model.Status),"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0.0,(ub-lb)/max(abs(ub),1e-9)),"runtime":runtime,"nodes":float(model.NodeCount),"root_relaxation_bound":root["bound"],"final_global_bound":lb,"objective_consistency_error":objective_error,"solution_count":int(model.SolCount),"solution":solution,"components":recomputed,"feasibility_report":feasibility,"diagnostics":diagnostics}


OPERATORS=("random","active-biased","block-focused","interval-focused","ship-focused","conflict-focused","distance-focused")
def adaptive_lns(data, weights, incumbent, *, time_limit_s=45, repair_time_s=5, repair_gap=.03,
        min_destroy=.10,max_destroy=.35,stall_iters=10,min_iters=1,restarts=1,
        temperature=.02,cooling_rate=.98,alloc_domain="integer", add_valid_inequalities=True,
        symmetry_breaking=False,seed=0,threads=None):
    rng=random.Random(seed); started=time.perf_counter(); current=incumbent; best=incumbent; weights_op={op:1.0 for op in OPERATORS}; stats={op:{"used":0,"accepted":0,"improved":0,"rejected":0,"improvement":0.0,"runtime":0.0} for op in OPERATORS}; log=[]; iteration=0;streak=0;restart_count=0;fraction=min_destroy
    keys=list(current["solution"]["x"])
    while keys and (time.perf_counter()-started < time_limit_s or iteration < min_iters):
        iteration+=1; op=rng.choices(OPERATORS, weights=[weights_op[x] for x in OPERATORS])[0]; fraction=min(max_destroy,max(min_destroy,fraction)); used_fraction=fraction; count=max(1,int(len(keys)*fraction))
        if op=="active-biased": pool=[k for k in keys if current["solution"]["x"].get(k,0)>.5] or keys
        elif op=="block-focused":
            block=rng.choice(data["K"]); pool=[k for k in keys if k[0] in data["Bays_in_Block"][block]] or keys
        elif op=="interval-focused": n=rng.choice(data["N"]); pool=[k for k in keys if k[2]==n] or keys
        elif op=="ship-focused": j=rng.choice(data["J_new"]); pool=[k for k in keys if k[1]==j] or keys
        elif op=="conflict-focused":
            pressure=data.get("Block_Outbound_Vol",{}); bay_block={i:data["I"][i]["block"] for i in data["I_list"]}; pool=sorted(keys,key=lambda q:pressure.get((bay_block[q[0]],q[2]),0),reverse=True)[:max(count,len(keys)//4)] or keys
        elif op=="distance-focused":
            bay_block={i:data["I"][i]["block"] for i in data["I_list"]}; pool=sorted(keys,key=lambda q:data["Dist"][(q[1],bay_block[q[0]])],reverse=True)[:max(count,len(keys)//4)] or keys
        else: pool=keys
        released=set(rng.sample(pool,min(count,len(pool)))); model,variables,expr=build_core_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking)
        _start(variables,current["solution"],alloc_domain)
        released_pairs={(i,j) for i,j,_n in released}; released_alloc=0
        for key,var in variables["x"].items():
            if key not in released: var.LB=var.UB=round(current["solution"]["x"][key])
        released_blocks={(data["I"][i]["block"],j,n) for i,j,n in released}
        for key,var in variables["block_use"].items():
            if key not in released_blocks: var.LB=var.UB=round(current["solution"]["block_use"][key])
        for key,var in variables["alloc_boxes"].items():
            if (key[0],key[1]) not in released_pairs:
                value=current["solution"]["alloc_boxes"][key]; value=round(value) if alloc_domain=="integer" else value; var.LB=var.UB=value
            else: released_alloc+=1
        model.Params.OutputFlag=0; model.Params.TimeLimit=min(repair_time_s,max(.01,time_limit_s-(time.perf_counter()-started))); model.Params.MIPGap=repair_gap; model.Params.Seed=seed+iteration
        if threads is not None:model.Params.Threads=int(threads)
        t0=time.perf_counter(); model.optimize(); rt=time.perf_counter()-t0; accepted=False; sa=False; candidate_cost=None
        if model.SolCount:
            sol=extract_solution(expr["data"],variables); ev=evaluate_core_solution(expr["data"],weights,sol); candidate_cost=ev["total_core_cost"]; feasibility=validate_core_solution(data,sol,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities)
            if abs(float(model.ObjVal)-candidate_cost)>1e-5:raise AssertionError("repair objective mismatch")
            delta=candidate_cost-current["ub"]; temp=max(1e-9,abs(best["ub"])*temperature*(cooling_rate**iteration)); accepted=feasibility["feasible"] and (delta < -1e-6 or rng.random()<math.exp(-max(0,delta)/temp)); sa=accepted and delta>=-1e-6
            candidate={"ok":True,"ub":candidate_cost,"solution":sol,"components":ev,"feasibility_report":feasibility}
            if accepted: current=candidate
            if candidate_cost < best["ub"]-1e-6:
                improvement=best["ub"]-candidate_cost; best=candidate; stats[op]["improved"]+=1; stats[op]["improvement"]+=improvement; weights_op[op]=.8*weights_op[op]+.2*5;streak=0;fraction=max(min_destroy,fraction*.8)
            else:streak+=1;fraction=min(max_destroy,fraction+(max_destroy-min_destroy)/max(1,stall_iters))
        stats[op]["used"]+=1; stats[op]["runtime"]+=rt; stats[op]["accepted" if accepted else "rejected"]+=1; weights_op[op]=.95*weights_op[op]+.05*(2 if accepted else .5)
        log.append({"iteration":iteration,"operator":op,"destroy_fraction":used_fraction,"released_x_count":len(released),"released_alloc_count":released_alloc,"candidate_core_cost":candidate_cost,"current_core_cost":current["ub"],"best_core_cost":best["ub"],"accepted":accepted,"sa_accepted":sa,"repair_status":_status(model.Status),"repair_runtime":rt,"repair_gap":float(model.MIPGap) if model.SolCount else None,"repair_nodes":float(model.NodeCount)})
        if streak>=stall_iters and restart_count<restarts:current=best;streak=0;restart_count+=1;fraction=max_destroy
    op_summary={op:{**s,"average_improvement":s["improvement"]/max(1,s["improved"]),"average_runtime":s["runtime"]/max(1,s["used"]),"final_adaptive_weight":weights_op[op]} for op,s in stats.items()}
    return {"best_ub":best["ub"],"best_solution":best["solution"],"best_components":best["components"],"best_feasibility_report":best.get("feasibility_report",incumbent.get("feasibility_report")),"improvement":incumbent["ub"]-best["ub"],"iterations":log,"operators":op_summary,"runtime":time.perf_counter()-started,"restarts":restart_count}


def solve_attribute_refinement(data, weights, core_best_solution, core_best_ub, *, epsilon=.01, attribute_scope="final",attribute_basis="inventory", time_limit_s=20, mip_gap=.03, alloc_domain="integer", add_valid_inequalities=True,symmetry_breaking=False, seed=0,threads=None):
    if not has_attribute_data(data):return {"status":"NOT_APPLICABLE","status_name":"NOT_APPLICABLE","accepted":False,"epsilon":epsilon,"attribute_basis":attribute_basis,"attribute_scope":attribute_scope,"start_core_cost":core_best_ub,"candidate_core_cost":None,"core_degradation_absolute":None,"core_degradation_relative":None,"start_attribute_score":None,"candidate_attribute_score":None,"solution":core_best_solution,"runtime":0.0}
    model,variables,expr=build_core_monolithic_model(data,weights,alloc_domain=alloc_domain,include_attribute_helpers=True,attribute_scope=attribute_scope,attribute_basis=attribute_basis,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking)
    cap=float(core_best_ub)*(1+float(epsilon)); model.addConstr(expr["core_objective"]<=cap+1e-6,name="epsilon_core_cap"); model.setObjective(expr["attribute_objective"],GRB.MINIMIZE); _start(variables,core_best_solution,alloc_domain)
    model.Params.OutputFlag=0; model.Params.TimeLimit=float(time_limit_s); model.Params.MIPGap=float(mip_gap); model.Params.Seed=int(seed)
    if threads is not None:model.Params.Threads=int(threads)
    started=time.perf_counter(); model.optimize(); runtime=time.perf_counter()-started
    start_raw=raw_components(data,core_best_solution,attribute_scope=attribute_scope,attribute_basis=attribute_basis); start_attr=attribute_score(data,weights,start_raw,attribute_scope); accepted=False; solution=core_best_solution; candidate_core=None; candidate_attr=None;candidate_components=None;feasibility=None
    attribute_error=None
    if model.SolCount:
        candidate=extract_solution(expr["data"],variables); ev=evaluate_core_solution(expr["data"],weights,candidate,attribute_scope=attribute_scope,attribute_basis=attribute_basis); candidate_components=ev;candidate_core=ev["total_core_cost"]; candidate_attr=ev["attribute_score"];feasibility=validate_core_solution(data,candidate,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities)
        attribute_error=abs(float(model.ObjVal)-candidate_attr)
        if attribute_error>1e-5:raise AssertionError("attribute objective mismatch")
        accepted=feasibility["feasible"] and candidate_core<=cap+1e-5 and candidate_attr<start_attr-1e-6
        if accepted: solution=candidate
    absolute=None if candidate_core is None else candidate_core-core_best_ub;relative=None if absolute is None else absolute/max(abs(core_best_ub),1e-5)
    return {"status":"ACCEPTED" if accepted else "REJECTED","accepted":accepted,"epsilon":epsilon,"attribute_basis":attribute_basis,"attribute_scope":attribute_scope,"core_cap":cap,"start_core_cost":core_best_ub,"candidate_core_cost":candidate_core,"core_degradation_absolute":absolute,"core_degradation_relative":relative,"start_attribute_score":start_attr,"candidate_attribute_score":candidate_attr,"attribute_objective_consistency_error":attribute_error,"candidate_components":candidate_components,"candidate_feasibility_report":feasibility,"solution":solution,"status_name":_status(model.Status),"runtime":runtime}


def solve_strengthened_mip_alns(data,weights,*,phase1_time=20,lns_time=45,phase3_time=20,attribute_time=20,attribute_epsilon=.01,attribute_scope="final",attribute_basis="inventory",alloc_domain="integer",add_valid_inequalities=True,symmetry_breaking=False,seed=0,threads=None,mip_gap=.03,verbose=False,enable_alns=True,enable_proof=True,enable_refinement=True,lns_options=None):
    p1=solve_core_mip(data,weights,time_limit_s=phase1_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking,seed=seed,threads=threads,verbose=verbose)
    if not p1["ok"]: return {"algorithm":"strengthened_mip_alns","phase1_core_mip":p1,"attribute_data_available":has_attribute_data(data),"ok":False}
    options=dict(lns_options or {});alns=adaptive_lns(data,weights,p1,time_limit_s=lns_time,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking,seed=seed,threads=threads,**options) if enable_alns else {"best_ub":p1["ub"],"best_solution":p1["solution"],"best_components":p1["components"],"best_feasibility_report":p1["feasibility_report"],"improvement":0.0,"iterations":[],"operators":{op:{"used":0,"accepted":0,"improved":0,"rejected":0,"average_improvement":0,"average_runtime":0,"final_adaptive_weight":1.0} for op in OPERATORS},"runtime":0.0,"disabled":True}
    p3=solve_core_mip(data,weights,time_limit_s=phase3_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking,start_solution=alns["best_solution"],proof=True,seed=seed,threads=threads,verbose=verbose) if enable_proof else {"ok":False,"disabled":True,"lb":None,"runtime":0.0,"nodes":0}
    candidates=[{"source":"phase1","ub":p1["ub"],"solution":p1["solution"],"components":p1["components"],"feasibility_report":p1["feasibility_report"]},{"source":"alns","ub":alns["best_ub"],"solution":alns["best_solution"],"components":alns["best_components"],"feasibility_report":alns["best_feasibility_report"]}]+([{"source":"phase3","ub":p3["ub"],"solution":p3["solution"],"components":p3["components"],"feasibility_report":p3["feasibility_report"]}] if p3["ok"] else []);best=min(candidates,key=lambda x:x["ub"]);ub,solution=best["ub"],best["solution"]; lbs=[x for x in (p1["lb"],p3.get("lb")) if x is not None]; lb=max(lbs) if lbs else None
    if lb is not None and lb>ub+1e-5: raise AssertionError("best valid LB exceeds core UB")
    refinement=solve_attribute_refinement(data,weights,solution,ub,epsilon=attribute_epsilon,attribute_scope=attribute_scope,attribute_basis=attribute_basis,time_limit_s=attribute_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,symmetry_breaking=symmetry_breaking,seed=seed,threads=threads) if enable_refinement else {"status":"DISABLED","accepted":False,"disabled":True,"epsilon":attribute_epsilon,"attribute_basis":attribute_basis,"attribute_scope":attribute_scope,"start_core_cost":ub,"candidate_core_cost":None,"core_degradation_absolute":None,"core_degradation_relative":None,"start_attribute_score":evaluate_core_solution(data,weights,solution,attribute_scope,attribute_basis)["attribute_score"] if has_attribute_data(data) else None,"candidate_attribute_score":None,"solution":solution,"runtime":0.0}
    final_solution=refinement["solution"];final_components=evaluate_core_solution(data,weights,final_solution,attribute_scope,attribute_basis)
    return {"ok":True,"algorithm":"strengthened_mip_alns","phase1_core_mip":p1,"phase2_alns":alns,"phase3_proof_mip":p3,"core_best":{"ub":ub,"lb":lb,"gap":None if lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"solution":solution,"components":best["components"],"feasibility_report":best["feasibility_report"],"diagnostics":handling_diagnostics(data,solution),"solution_source":best["source"]},"attribute_refinement":refinement,"final_solution":{"solution":final_solution,"components":final_components,"solution_source":"attribute_refinement" if refinement["accepted"] else "core_best"},"attribute_data_available":has_attribute_data(data)}
