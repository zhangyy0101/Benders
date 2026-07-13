from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from benchmark_io import instance_digest,save_instance
from synthetic_instance_generator import GENERATOR_VERSION,SyntheticInstanceSpec,generate_synthetic_instance

def specs():
 result={}
 for number in range(1,4):
  iid=f"XS{number:02d}";result[iid]=SyntheticInstanceSpec(name=iid,num_blocks=2,bays_per_block=3,bay_capacity_boxes=40,num_berths=2,num_new_ships=1,num_old_ships=1,num_periods=12,time_bucket_hours=6,alpha=1.1,handling_rate_boxes_per_hour=50,initial_utilization_range=(.08+.04*number,.14+.04*number),fixed_inbound_ratio_range=(.01,.03),outbound_pressure_ratio_range=(.04+.01*number,.08+.02*number),arrival_boxes_per_ship_range=(18+number,21+number),arrival_overlap_level=.2+.2*number,peak_position_range=(.30+.03*number,.55+.03*number),mode_20ft_share=.5,group_profile="pilot2_small",pod_count_range=(3,3),positive_group_count_range=(5,6),single_combination_pod_ratio_range=(.25,.50),arrival_overlap_ratio_range=(0,1),pressure_positive_ratio_range=(0,1),minimum_active_group_boxes=2)
 return result

def main():
 root=Path("benchmarks/paper_exp_v1_pilot21_exact");root.mkdir(parents=True,exist_ok=True);rows=[]
 for number,(iid,spec) in enumerate(specs().items(),1):
  data=generate_synthetic_instance(spec,4100+number);path=root/f"{iid}.json";save_instance(data,path,instance_id=iid);rows.append({"instance_id":iid,"relative_path":path.name,"digest":instance_digest(data),"seed":4100+number,"generator_version":GENERATOR_VERSION,"periods":len(data["N"]),"new_ships":len(data["J_new"]),"old_ships":len(data["J_old"]),"blocks":len(data["K"]),"bays":len(data["I_list"]),"groups":len(data["G"])});print(iid,rows[-1]["digest"][:12])
 (root/"manifest.json").write_text(json.dumps({"suite":"paper-exp-v1-pilot2.1-exact-fixtures","candidate_algorithm_frozen":False,"final_algorithm_frozen":False,"instances":rows},indent=2)+"\n",encoding="utf-8");(root/"README.md").write_text("# Pilot2.1 exact fixtures\n\nXS01-XS03 are small sparse-schema mathematical fixtures, not development benchmarks or paper results. They use the same 12-period group, concentration, evaluator, checker, normalization, pressure, and digest contracts as Pilot2.1.\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
