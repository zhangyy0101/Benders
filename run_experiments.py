"""Batch experiment runner for Route-A ablations; writes JSON and flat CSV."""
import argparse, csv, itertools, json, os, subprocess, sys, tempfile

def main():
    p=argparse.ArgumentParser(); p.add_argument("--instances",nargs="+",default=["3new6old"]); p.add_argument("--seeds",nargs="+",type=int,default=[0]); p.add_argument("--output",default="experiments"); p.add_argument("--phase-time",type=float,default=20); a=p.parse_args(); os.makedirs(a.output,exist_ok=True); rows=[]
    configs=itertools.product(("integer","continuous"),(.5,1.0,1.5),(0,.005,.01,.02,.05),(True,False))
    for instance,seed,(domain,rate,epsilon,valid) in itertools.product(a.instances,a.seeds,configs):
        with tempfile.TemporaryDirectory(dir=a.output) as tmp:
            cmd=[sys.executable,"main.py","--instance",instance,"--seed",str(seed),"--alloc-domain",domain,"--handling-rate-scale",str(rate),"--attribute-epsilon",str(epsilon),"--phase1-time",str(a.phase_time),"--lns-time",str(a.phase_time),"--phase3-time",str(a.phase_time),"--attribute-time",str(a.phase_time),"--output-root",tmp]
            if not valid: cmd.append("--no-valid-inequalities")
            completed=subprocess.run(cmd,check=False); summaries=[]
            for root,_dirs,files in os.walk(tmp):
                if "summary.json" in files: summaries.append(os.path.join(root,"summary.json"))
            summary=json.load(open(summaries[0],encoding="utf8")) if summaries else {}; core=summary.get("core_best",{}); ref=summary.get("attribute_refinement",{}); p1=summary.get("phase1_core_mip",{}); p2=summary.get("phase2_alns",{}); p3=summary.get("phase3_proof_mip",{})
            rows.append({"instance":instance,"algorithm":"strengthened_mip_alns","seed":seed,"status":summary.get("status","OK" if completed.returncode==0 else "FAILED"),"runtime":sum(float(x.get("runtime",0) or 0) for x in (p1,p2,p3)),"nodes":p3.get("nodes"),"root_bound":p3.get("root_bound"),"ub":core.get("ub"),"lb":core.get("lb"),"gap":core.get("gap"),"phase1_ub":p1.get("ub"),"alns_start_ub":p1.get("ub"),"alns_best_ub":p2.get("best_ub"),"alns_improvement":p2.get("improvement"),"phase3_lb":p3.get("lb"),"alloc_domain":domain,"handling_rate_scale":rate,"valid_inequalities":valid,"epsilon":epsilon,"pod_spread":None,"weight_spread":None,"height_mix":None,"attribute_score":ref.get("candidate_attribute_score"),"core_degradation":ref.get("core_degradation")})
    fields=list(rows[0]); json.dump(rows,open(os.path.join(a.output,"results.json"),"w",encoding="utf8"),indent=2); f=open(os.path.join(a.output,"results.csv"),"w",newline="",encoding="utf8"); w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows); f.close()
if __name__=="__main__": main()
