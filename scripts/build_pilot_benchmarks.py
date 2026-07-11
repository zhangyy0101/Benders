from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from benchmark_io import instance_digest,load_instance,save_instance
from pilot_benchmark_suite import PILOT_VERSION,SEEDS,audit_suite,instance_summary,pilot_specs,write_manifests
from synthetic_instance_generator import generate_synthetic_instance
def main():
    p=argparse.ArgumentParser();p.add_argument("--output",default="benchmarks/paper_exp_v1_pilot");p.add_argument("--overwrite",action="store_true");a=p.parse_args();root=Path(a.output);root.mkdir(parents=True,exist_ok=True);rows=[]
    for instance_id,(size_class,spec) in pilot_specs().items():
        instance=generate_synthetic_instance(spec,SEEDS[instance_id]);relative=f"{size_class}/{instance_id}.json";path=root/relative
        if path.exists():
            existing=load_instance(path)
            if instance_digest(existing)==instance_digest(instance):status="already_exists"
            elif not a.overwrite:raise RuntimeError(f"{instance_id} exists with a different digest; use a new pilot version or --overwrite")
            else:save_instance(instance,path,instance_id=instance_id);status="overwritten"
        else:save_instance(instance,path,instance_id=instance_id);status="created"
        row=instance_summary(instance,instance_id,size_class,relative,SEEDS[instance_id]);row["creation_status"]=status;rows.append(row);print(f"{instance_id}: {status} {row['digest'][:12]}")
    write_manifests(root,rows);readme=f"""# {PILOT_VERSION}\n\nAll nine files are deterministic **synthetic** pilot benchmarks for development, validation, and difficulty calibration. They are not real-port data and must not be used as final paper results.\n\nSeeds are permanent: S01–S03 = 1101–1103, M01–M03 = 2101–2103, L01–L03 = 3101–3103. Instances use generator `synthetic-yard-v1`, schema `yard-bay-instance-v1`, and problem protocol `paper-exp-v1`.\n\nRegenerate with `python scripts/build_pilot_benchmarks.py`. Existing equal digests are retained; a conflicting file fails unless explicit `--overwrite` is supplied. Verify with `python scripts/audit_benchmarks.py benchmarks/paper_exp_v1_pilot`. No solver performance was used to select or tune these instances.\n""";(root/"README.md").write_text(readme,encoding="utf-8");audit=audit_suite(root);print(f"audit: {audit['status']}");return 0 if audit["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
