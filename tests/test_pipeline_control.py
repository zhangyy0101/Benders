from config import Weights
from data import get_data_tiny_benders,prepare_instance
import solver_true_benders as stb
def test_no_warm_start_never_calls_initializer(monkeypatch):
 d=prepare_instance(get_data_tiny_benders());monkeypatch.setattr(stb,"_warm_start",lambda *a,**k:(_ for _ in ()).throw(AssertionError("called")));r=stb.solve_true_benders_pipeline(d,Weights(),total_core_time=.2,root_prepass=False,warm_start=False,enable_alns=False,enable_phase3=False);assert not r["ok"] and r["phase1_initialization"]["mode"]=="disabled"
def test_warm_failure_called_once_and_disables_alns(monkeypatch):
 d=prepare_instance(get_data_tiny_benders());calls=[]
 def fail(*a,**k):calls.append(1);return None
 monkeypatch.setattr(stb,"_warm_start",fail);r=stb.solve_true_benders_pipeline(d,Weights(),total_core_time=.2,root_prepass=False,enable_phase3=False);assert len(calls)==1 and r["phase2_alns"]["disabled"] and r["phase2_alns"]["reason"]=="no feasible initialization"
