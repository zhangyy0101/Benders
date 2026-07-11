"""Recoverable, configuration-aware experiment orchestration."""
from __future__ import annotations
import csv,hashlib,json,os,platform,socket,subprocess,sys,time,traceback
from pathlib import Path
from gurobipy import gurobi
from algorithm_configuration import configuration_hash
from benchmark_io import instance_digest,load_instance
from config import Weights
from data import prepare_instance
from experiment_methods import run_method
from experiment_schema import SCHEMA_VERSION,stable_run_id,validate_result

def _git(args):
    try:return subprocess.check_output(["git",*args],text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:return None
def environment_metadata(command=None):return {"git_commit":_git(["rev-parse","HEAD"]),"git_dirty":bool(_git(["status","--porcelain"])),"python":platform.python_version(),"gurobi":".".join(map(str,gurobi.version())),"os":platform.platform(),"cpu_logical_count":os.cpu_count(),"machine_id":hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12],"command":command or " ".join(sys.argv)}
def _atomic_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+".tmp");temporary.write_text(text,encoding="utf-8");os.replace(temporary,path)
def read_jsonl(path):
    source=Path(path)
    if not source.exists():return []
    rows=[]
    for number,line in enumerate(source.read_text(encoding="utf-8").splitlines(),1):
        if line.strip():
            try:rows.append(json.loads(line))
            except json.JSONDecodeError as exc:raise ValueError(f"corrupt JSONL line {number}: {exc}") from exc
    return rows
def atomic_append_jsonl(path,row):
    rows=read_jsonl(path);rows.append(row);_atomic_write(path,"".join(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n" for item in rows))
def _solution_payload(solution):
    records={}
    for name,values in solution.items():records[name]=[{"key":list(key) if isinstance(key,tuple) else key,"value":value} for key,value in sorted(values.items(),key=lambda item:repr(item[0]))]
    return records
def _json_safe(value):
    if isinstance(value,dict):
        if all(isinstance(key,str) for key in value):return {key:_json_safe(item) for key,item in value.items()}
        return {"__mapping__":[{"key":_json_safe(list(key) if isinstance(key,tuple) else key),"value":_json_safe(item)} for key,item in sorted(value.items(),key=lambda pair:repr(pair[0]))]}
    if isinstance(value,(list,tuple)):return [_json_safe(item) for item in value]
    return value
def solution_digest(solution):return hashlib.sha256(json.dumps(_solution_payload(solution),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def identity_payload(*,protocol,instance_digest_value,method,configuration_hash_value,seed,budget,threads,mip_gap,alloc_domain,weights,handling_rate_scale,outbound_policy):return {"problem_protocol":protocol,"instance_digest":instance_digest_value,"method_family":method,"configuration_hash":configuration_hash_value,"seed":seed,"budget":budget,"threads":threads,"mip_gap":mip_gap,"allocation_domain":alloc_domain,"weights":{"open":weights.master.x,"concentration":weights.master.concentration,"distance":weights.sub.dist,"balance":weights.sub.balance,"conflict":weights.sub.conflict,"objective_scale":weights.objective_scale},"prepare":{"handling_rate_scale":handling_rate_scale,"old_outbound_release_policy":outbound_policy}}
def _timing(raw,wall):
    main=raw.get("phase3_bbc",raw.get("main_solve",{}));root=raw.get("phase0_root_prepass",{});warm=raw.get("phase1_initialization",raw.get("warm_start",{}));alns=raw.get("phase2_alns",raw.get("alns",{}));return {"wall_clock":wall,"solver_reported":raw.get("runtime"),"model_build":raw.get("model_build_runtime",main.get("model_build_runtime")),"solve":raw.get("optimization_runtime",main.get("optimization_runtime")),"root":root.get("root_cut_runtime"),"warm":warm.get("runtime"),"alns":alns.get("runtime"),"main":main.get("runtime"),"callback":main.get("cut_statistics",{}).get("callback_time"),"sp_total":main.get("sp_statistics",{}).get("sp_total_time")}
def _optimization(raw):
    best=raw.get("core_best",raw);main=raw.get("phase3_bbc",raw.get("main_solve",raw));stats=main.get("cut_statistics",{});return {"ub":best.get("ub"),"lb":best.get("lb"),"gap":best.get("gap"),"nodes":main.get("nodes"),"cuts":raw.get("total_unique_cuts",main.get("new_unique_cuts")),"sp_solves":main.get("sp_statistics",{}).get("sp_solve_count"),"cache_hits":stats.get("cache_hits"),"cache_misses":stats.get("cache_misses"),"cache_hit_rate":stats.get("cache_hit_rate"),"time_to_first_feasible":raw.get("time_to_first_feasible"),"time_to_best":raw.get("time_to_best"),"solution_source":best.get("solution_source")}
def execute_run(*,instance_id,instance_path,expected_digest,method,configuration,seed,budget,threads,mip_gap,alloc_domain,handling_rate_scale,outbound_policy,output,save_solutions=False,method_runner=run_method,command=None):
    raw_instance=load_instance(instance_path);digest=instance_digest(raw_instance)
    if digest!=expected_digest:raise ValueError(f"fatal benchmark digest mismatch for {instance_id}")
    weights=Weights();config_hash=configuration.get("configuration_hash") or configuration_hash({k:v for k,v in configuration.items() if k!="configuration_hash"});identity=identity_payload(protocol="paper-exp-v1",instance_digest_value=digest,method=method,configuration_hash_value=config_hash,seed=seed,budget=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,weights=weights,handling_rate_scale=handling_rate_scale,outbound_policy=outbound_policy);run_id=stable_run_id(identity);started=time.perf_counter();solution=None;evaluation=None
    try:
        data=prepare_instance(raw_instance,handling_rate_scale=handling_rate_scale,old_outbound_release_policy=outbound_policy);solver,solution,evaluation=method_runner(method,data,weights,configuration,budget=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,seed=seed);wall=time.perf_counter()-started;status={"ok":bool(solution),"status":solver.get("status_name",solver.get("phase3_bbc",{}).get("status_name")),"termination_reason":solver.get("reason"),"exception_type":None,"exception_message":None,"feasible_incumbent_found":bool(solution),"solution_source":solver.get("core_best",{}).get("solution_source")};timing=_timing(solver,wall);optimization=_optimization(solver)
    except Exception as exc:
        wall=time.perf_counter()-started;status={"ok":False,"status":"EXCEPTION","termination_reason":"exception","exception_type":type(exc).__name__,"exception_message":str(exc),"feasible_incumbent_found":False,"solution_source":None};timing={"wall_clock":wall,**{key:None for key in ("solver_reported","model_build","solve","root","warm","alns","main","callback","sp_total")}};optimization={key:None for key in ("ub","lb","gap","nodes","cuts","sp_solves","cache_hits","cache_misses","cache_hit_rate","time_to_first_feasible","time_to_best","solution_source")};traceback_text=traceback.format_exc()
    evaluation_safe=_json_safe(evaluation) if evaluation else None;result={"schema_version":SCHEMA_VERSION,"run_id":run_id,"identity":{"instance_id":instance_id,**identity,"configuration_name":configuration["configuration_name"],"configuration_version":configuration["configuration_version"],"configuration_status":configuration["status"]},"configuration":configuration,"status":status,"timing":timing,"optimization":optimization,"evaluation":evaluation_safe,"environment":environment_metadata(command)}
    if status["status"]=="EXCEPTION":result["exception_traceback"]=traceback_text
    if solution and save_solutions:
        digest_solution=solution_digest(solution);relative=f"solutions/{run_id}.json";payload={"run_id":run_id,"solution_digest":digest_solution,"feasibility_pass":evaluation["feasibility"]["feasible"],"evaluation":evaluation_safe,"solution":_solution_payload(solution)};_atomic_write(Path(output)/relative,json.dumps(payload,indent=2,ensure_ascii=False)+"\n");result["solution_file"]={"relative_path":relative,"solution_digest":digest_solution,"feasibility_pass":True}
    validate_result(result);return result
def export_results(output,rows):
    root=Path(output);_atomic_write(root/"results.json",json.dumps(rows,indent=2,ensure_ascii=False)+"\n");flat=[]
    for row in rows:flat.append({"run_id":row["run_id"],"instance_id":row["identity"]["instance_id"],"method":row["identity"]["method_family"],"configuration":row["identity"]["configuration_name"],"seed":row["identity"]["seed"],"ok":row["status"]["ok"],"status":row["status"]["status"],"wall_clock":row["timing"]["wall_clock"],"ub":row["optimization"]["ub"],"lb":row["optimization"]["lb"],"gap":row["optimization"]["gap"],"evaluation_json":json.dumps(row["evaluation"],separators=(",",":")) if row["evaluation"] else None})
    if flat:
        import io;stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat);_atomic_write(root/"results.csv",stream.getvalue())
def run_jobs(jobs,output,*,resume=False,rerun_failed=False,save_solutions=False,method_runner=run_method,command=None):
    root=Path(output);source=root/"results.jsonl";existing=read_jsonl(source);by_id={row["run_id"]:row for row in existing}
    for job in jobs:
        probe_identity=identity_payload(protocol="paper-exp-v1",instance_digest_value=job["expected_digest"],method=job["method"],configuration_hash_value=job["configuration"]["configuration_hash"],seed=job["seed"],budget=job["budget"],threads=job["threads"],mip_gap=job["mip_gap"],alloc_domain=job["alloc_domain"],weights=Weights(),handling_rate_scale=job["handling_rate_scale"],outbound_policy=job["outbound_policy"]);rid=stable_run_id(probe_identity);old=by_id.get(rid)
        if resume and old and (old["status"]["ok"] or not rerun_failed):continue
        result=execute_run(**job,output=output,save_solutions=save_solutions,method_runner=method_runner,command=command)
        if old:existing=[row for row in existing if row["run_id"]!=rid];_atomic_write(source,"".join(json.dumps(row,separators=(",",":"),ensure_ascii=False)+"\n" for row in existing))
        atomic_append_jsonl(source,result);existing.append(result);by_id[rid]=result;export_results(output,existing)
    export_results(output,existing);return existing
