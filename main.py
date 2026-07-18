"""CLI for the stability-aware rolling allocation framework."""
from __future__ import annotations
import argparse,json
from rolling_data import build_repair_pressure_case,build_synthetic_rolling_case
from rolling_experiment import run_rolling_case
from rolling_solver import CONFIGURATIONS


PRESETS={
 "small":dict(num_blocks=4,bays_per_block=6,num_ships=5,cycles=5),
 "medium":dict(num_blocks=8,bays_per_block=8,num_ships=8,cycles=6),
 "large":dict(num_blocks=12,bays_per_block=10,num_ships=12,cycles=7),
}
def parser():
 p=argparse.ArgumentParser(description="Stability-aware rolling bay-slot allocation");p.add_argument("--size",choices=PRESETS,default="small");p.add_argument("--configuration",choices=CONFIGURATIONS,default="full");p.add_argument("--pressure",choices=("nearby","global"));p.add_argument("--time",type=float,default=20,help="seconds per rolling cycle");p.add_argument("--forecast-error",type=float,default=.10);p.add_argument("--initial-utilization",type=float,default=.25);p.add_argument("--outbound-rate",type=int,default=150,help="boxes per ship per 6-hour period");p.add_argument("--seed",type=int,default=0);p.add_argument("--threads",type=int,default=1);p.add_argument("--output");return p
def serial(v):
 if isinstance(v,set):return sorted(v)
 if isinstance(v,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):serial(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [serial(x) for x in v]
 return v
def main():
 a=parser().parse_args();case=build_repair_pressure_case(level=a.pressure,seed=a.seed) if a.pressure else build_synthetic_rolling_case(seed=a.seed,forecast_error=a.forecast_error,initial_utilization=a.initial_utilization,outbound_boxes_per_period=a.outbound_rate,**PRESETS[a.size]);result=run_rolling_case(case,time_per_cycle=a.time,threads=a.threads,seed=a.seed,configuration=a.configuration)
 summary={k:v for k,v in result.items() if k!="final_state"};print(json.dumps(serial(summary),indent=2,ensure_ascii=False))
 if a.output:
  with open(a.output,"w",encoding="utf-8") as f:json.dump(serial(result),f,indent=2,ensure_ascii=False)
 return 0 if result["ok"] else 2
if __name__=="__main__":raise SystemExit(main())
