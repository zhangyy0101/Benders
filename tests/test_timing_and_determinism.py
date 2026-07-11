import json,subprocess,sys
from config import Weights
from data import get_data_tiny_benders,prepare_instance
from solve_direct_gurobi import solve_direct_gurobi
def test_direct_runtime_includes_model_build():
 r=solve_direct_gurobi(prepare_instance(get_data_tiny_benders()),Weights(),time_limit=1,mip_gap=0);assert r["runtime"]>=r["model_build_runtime"] and r["runtime"]>=r["optimization_runtime"]
def test_pair_helper_is_cross_process_deterministic():
 code="from solver_alns import active_pair_keys;import json;d={'I_list':['b','a'],'J_new':['j'],'N':[0,1]};s={'x':{('b','j',0):1,('a','j',1):1}};print(json.dumps(active_pair_keys(d,s)))"
 a=subprocess.check_output([sys.executable,"-c",code],text=True).strip();b=subprocess.check_output([sys.executable,"-c",code],text=True).strip();assert a==b
