import copy
from pathlib import Path
import pytest
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest,save_instance
from experiment_runner import atomic_append_jsonl,execute_run,identity_payload,read_jsonl,run_jobs
from experiment_schema import stable_run_id,validate_result
from config import Weights
from instance_registry import build_builtin_instance

def fixture_job(tmp_path,method="direct",config=None):
    raw=build_builtin_instance("tiny_concentration");path=tmp_path/"tiny.json";save_instance(raw,path,instance_id="tiny")
    return {"instance_id":"tiny","instance_path":path,"expected_digest":instance_digest(raw),"method":method,"configuration":config or {"algorithm_family":method,"configuration_name":"mock","configuration_version":"1","status":"baseline","configuration_hash":"a"*64},"seed":0,"budget":1.0,"threads":1,"mip_gap":.03,"alloc_domain":"integer","handling_rate_scale":1.0,"outbound_policy":"proportional"}

def mock_success(method,data,weights,configuration,**kwargs):return {"status_name":"MOCK","runtime":0,"ub":1,"lb":0,"gap":1,"nodes":0},{"x":{}},{"feasibility":{"feasible":True},"core_cost":1}
def mock_failure(*args,**kwargs):raise RuntimeError("planned failure")

def test_run_id_stable_and_configuration_change_changes_identity():
    base=dict(protocol="paper-exp-v1",instance_digest_value="d",method="direct",configuration_hash_value="a",seed=0,budget=1,threads=1,mip_gap=.03,alloc_domain="integer",weights=Weights(),handling_rate_scale=1,outbound_policy="proportional")
    first=stable_run_id(identity_payload(**base));assert first==stable_run_id(identity_payload(**base));base["configuration_hash_value"]="b";assert first!=stable_run_id(identity_payload(**base))

def test_resume_and_failed_rerun_are_explicit(tmp_path):
    job=fixture_job(tmp_path);out=tmp_path/"out";rows=run_jobs([job],out,method_runner=mock_success);assert len(rows)==1
    rows=run_jobs([job],out,resume=True,method_runner=lambda *a,**k:(_ for _ in ()).throw(AssertionError("should skip")));assert len(rows)==1
    failed_job=fixture_job(tmp_path/"failed");failed=run_jobs([failed_job],tmp_path/"failed_out",method_runner=mock_failure);assert failed[0]["status"]["status"]=="EXCEPTION"
    unchanged=run_jobs([failed_job],tmp_path/"failed_out",resume=True,method_runner=mock_success);assert not unchanged[0]["status"]["ok"]
    retried=run_jobs([failed_job],tmp_path/"failed_out",resume=True,rerun_failed=True,method_runner=mock_success);assert retried[0]["status"]["ok"] and len(retried)==1

def test_atomic_jsonl_and_schema_validation(tmp_path):
    path=tmp_path/"rows.jsonl";atomic_append_jsonl(path,{"a":1});atomic_append_jsonl(path,{"a":2});assert read_jsonl(path)==[{"a":1},{"a":2}] and not path.with_suffix(".jsonl.tmp").exists()
    with pytest.raises(ValueError,match="missing fields"):validate_result({"schema_version":"experiment-result-v1"})

@pytest.mark.gurobi
@pytest.mark.parametrize("method,config",[("direct",None),("bbc_candidate","bbc_full_current"),("direct_alns",None)])
def test_gurobi_method_smoke(tmp_path,method,config):
    job=fixture_job(tmp_path/method,method,get_algorithm_configuration(config) if config else None);job["budget"]=4
    result=execute_run(**job,output=tmp_path,save_solutions=True)
    assert result["status"]["ok"] and result["evaluation"]["feasibility"]["feasible"]
    assert Path(tmp_path/result["solution_file"]["relative_path"]).exists()
