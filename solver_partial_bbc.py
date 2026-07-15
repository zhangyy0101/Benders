"""Group-aggregated partial branch-and-Benders-cut solver."""
from __future__ import annotations
import time,traceback
from gurobipy import GRB
from anytime import canonicalize
from model_bay_packing import BayPackingOracle
from model_common import derive_activation,reconstruct_inventory,ship_group_pairs
from model_partial_master import build_partial_master,extract_partial_point
from solution_evaluation import evaluate_common_solution
from solution_validation import validate_solution

def solve_partial_bbc(data,weights,*,time_limit=60,mip_gap=.03,threads=1,seed=0,alloc_domain="integer",concentration_enabled=True):
    started=time.perf_counter();deadline=started+float(time_limit);model,vars,ctx=build_partial_master(data,weights,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);build=time.perf_counter()-started;oracle=BayPackingOracle(data);integer_oracle=BayPackingOracle(data,integer_alloc=True,reservation_only=True);model.Params.OutputFlag=0;model.Params.LazyConstraints=1;model.Params.PreCrush=1;model.Params.Threads=int(threads or 1);model.Params.Seed=int(seed);model.Params.MIPGap=float(mip_gap);stats={"feasibility_checks":0,"feasibility_cuts":0,"integer_checks":0,"integer_feasibility_cuts":0,"integer_cache_hits":0,"callback_time":0.0};errors=[];events=[];integer_cache={}
    from deterministic_initializer import build_deterministic_initial_solution
    initial=build_deterministic_initial_solution(data,weights,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)
    if initial:
        sol=initial["solution"];final=max(data["N"])
        start_A={key:int(round(sum(sol["alloc_boxes"].get((i,key[1],key[2],key[3]),0) for i in data["Bays_in_Block"][key[0]]))) for key in vars["block_alloc"]}
        for key,var in vars["block_alloc"].items():var.Start=start_A[key]
        for (key,b),var in vars["allocation_bits"].items():var.Start=float((start_A[key]>>b)&1)
        for key,var in vars["block_flow"].items():var.Start=sol["in_share"].get(key,0)
        for (i,h),var in vars["bay_height"].items():var.Start=float(data.get("OldBayHeight",{}).get(i)==h or any(sol["alloc_boxes"].get((i,j,g,final),0)>1e-6 and data["GroupHeight"][g]==h for j,g in ship_group_pairs(data)))
        for (j,p,h,i),var in vars["pod_support"].items():var.Start=float(any(data["GroupPOD"][g]==p and data["GroupHeight"][g]==h and sol["alloc_boxes"].get((i,j,g,final),0)>1e-6 for g in data["ActiveGroupsByShip"].get(j,data["G"])))
        for (j,p,i),var in vars["concentration_use"].items():var.Start=float(any(data["GroupPOD"][g]==p and sol["alloc_boxes"].get((i,j,g,final),0)>1e-6 for g in data["ActiveGroupsByShip"].get(j,data["G"])))
        for key,var in vars["in_total"].items():var.Start=sol["in_total"].get(key,0)
        for key,var in vars["avg"].items():var.Start=sol["avg"].get(key,0)
        for key,var in vars["g_bal"].items():var.Start=sol["g_bal"].get(key,0)
        model.Params.Cutoff=initial["ub"]+1e-6;events.append({"time":time.perf_counter()-started,"phase":"initialization","source":"deterministic_vector_packing","ub":initial["ub"],"lb":None})
    model.Params.TimeLimit=max(0,deadline-time.perf_counter())
    def oracle_point(point):return {"A":point["block_alloc"],"z":point["block_flow"],"support":point["pod_support"]}
    def discrete_key(point):return (tuple(sorted(k for k,v in point["allocation_bits"].items() if v>.5)),tuple(sorted(k for k,v in point["pod_support"].items() if v>.5)))
    def integer_nogood(point):
        terms=[]
        for k,var in vars["allocation_bits"].items():terms.append(1-var if point["allocation_bits"][k]>.5 else var)
        for k,var in vars["pod_support"].items():terms.append(1-var if point["pod_support"][k]>.5 else var)
        return sum(terms)>=1
    def callback(m,where):
        tick=time.perf_counter()
        try:
            if where==GRB.Callback.MIPSOL:
                point=extract_partial_point(vars,lambda v:m.cbGetSolution(v));oracle.update_rhs(oracle_point(point));status=oracle.solve();stats["feasibility_checks"]+=1
                if status==GRB.INFEASIBLE:
                    cut,value=oracle.farkas_cut(vars);m.cbLazy(cut>=0);stats["feasibility_cuts"]+=1
                elif status==GRB.OPTIMAL:
                    key=discrete_key(point);integer_status=integer_cache.get(key)
                    if integer_status is None:
                        integer_oracle.update_rhs(oracle_point(point));integer_status=integer_oracle.solve();integer_cache[key]=integer_status;stats["integer_checks"]+=1
                    else:stats["integer_cache_hits"]+=1
                    if integer_status==GRB.INFEASIBLE:m.cbLazy(integer_nogood(point));stats["integer_feasibility_cuts"]+=1
                    elif integer_status==GRB.OPTIMAL:events.append({"time":time.perf_counter()-started,"phase":"main","source":"integer_bay_feasible_incumbent","ub":float(m.cbGet(GRB.Callback.MIPSOL_OBJ)),"lb":None})
                    else:raise RuntimeError(f"integer bay packing status {integer_status}")
                else:raise RuntimeError(f"bay packing status {status}")
        except Exception as exc:errors.append((exc,traceback.format_exc()));m.terminate()
        finally:stats["callback_time"]+=time.perf_counter()-tick
    model.optimize(callback);runtime=time.perf_counter()-started
    if errors:raise RuntimeError(errors[0][1]) from errors[0][0]
    solution=evaluation=None;ub=None
    if model.SolCount:
        point=extract_partial_point(vars);final_oracle=BayPackingOracle(data,integer_alloc=True);final_oracle.update_rhs(oracle_point(point));final_oracle.model.Params.TimeLimit=max(1.0,deadline-time.perf_counter())
        if final_oracle.solve()!=GRB.OPTIMAL:raise RuntimeError("final master incumbent is not integer bay-packable")
        from collections import defaultdict
        point["block_flow"]=defaultdict(float,point["block_flow"])
        integer_oracle=final_oracle
        alloc,din=integer_oracle.solution();pairs=ship_group_pairs(data);share={(j,k,g,n):point["block_flow"][j,k,g,n] for j,g in pairs for k in data["K"] for n in data["N"]};solution={"alloc_boxes":alloc,"din":din,"inv":reconstruct_inventory(data,din),"x":derive_activation(data,alloc),"in_share":share,"in_total":point["in_total"],"avg":point["avg"],"g_bal":point["g_bal"],"concentration_use":point["concentration_use"],"bay_height":point["bay_height"],"block_alloc":point["block_alloc"]};report=validate_solution(data,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)
        if not report["feasible"]:raise RuntimeError(f"partial BBC final validation failed: {report}")
        evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);ub=evaluation["core_cost"]
        if abs(ub-float(model.ObjVal))>1e-4:raise AssertionError(f"objective mismatch {ub} != {model.ObjVal}")
    lb=float(model.ObjBound) if model.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None;stats["sp_solve_count"]=oracle.solve_count;stats["sp_total_time"]=oracle.total_time
    return {"anytime_trace":canonicalize(events,runtime,ub,lb),"ok":solution is not None,"algorithm":"group_aggregated_partial_bbc","workflow":"aggregate_master_bay_feasibility_sp","status":int(model.Status),"status_name":{GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE"}.get(model.Status,str(model.Status)),"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"runtime":runtime,"model_build_runtime":build,"nodes":float(model.NodeCount),"solution":solution,"components":evaluation,"cut_statistics":stats,"sp_statistics":{"sp_solve_count":oracle.solve_count,"sp_total_time":oracle.total_time}}
