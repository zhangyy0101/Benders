"""Named provisional BBC configurations for development and ablation."""
from __future__ import annotations
from copy import deepcopy
from algorithm_configuration import configuration_hash,validate_algorithm_configuration

BASE={"algorithm_family":"true_bbc_alns","configuration_version":"1","status":"candidate","root_prepass":False,"warm_start":False,"alns":False,"aggregate_recourse_lb":False,"analytic_recourse_lb":False,"valid_inequalities":False,"node_cuts":False,"cut_strategy":"standard","phase_shares":{"root":0.0,"warm":0.0,"alns":0.0,"main":1.0},"alns_parameters":{"repair_time":2.0,"repair_gap":.03,"min_destroy":.1,"max_destroy":.35,"restarts":1,"stall_iters":10,"destination_ratio":1.0}}
def _cfg(name,**changes):
    value=deepcopy(BASE);value["configuration_name"]=name
    for key,item in changes.items():value[key]=item
    return value
def _shares(root=0,warm=0,alns=0):return {"root":root,"warm":warm,"alns":alns,"main":1-root-warm-alns}
CONFIGURATIONS={
 "C0_bbc_core":_cfg("C0_bbc_core"),
 "C1_core_analytic":_cfg("C1_core_analytic",analytic_recourse_lb=True),
 "C2_core_aggregate":_cfg("C2_core_aggregate",aggregate_recourse_lb=True),
 "C3_core_both_lb":_cfg("C3_core_both_lb",analytic_recourse_lb=True,aggregate_recourse_lb=True),
 "C4_both_lb_root":_cfg("C4_both_lb_root",analytic_recourse_lb=True,aggregate_recourse_lb=True,root_prepass=True,phase_shares=_shares(root=.05)),
 "C5_both_lb_warm":_cfg("C5_both_lb_warm",analytic_recourse_lb=True,aggregate_recourse_lb=True,warm_start=True,phase_shares=_shares(warm=.15)),
 "C6_both_lb_warm_alns":_cfg("C6_both_lb_warm_alns",analytic_recourse_lb=True,aggregate_recourse_lb=True,warm_start=True,alns=True,phase_shares=_shares(warm=.15,alns=.25)),
 "C7_both_lb_root_warm_alns":_cfg("C7_both_lb_root_warm_alns",analytic_recourse_lb=True,aggregate_recourse_lb=True,root_prepass=True,warm_start=True,alns=True,phase_shares=_shares(.05,.15,.25)),
 "C8_both_lb_root_warm_alns_valid":_cfg("C8_both_lb_root_warm_alns_valid",analytic_recourse_lb=True,aggregate_recourse_lb=True,root_prepass=True,warm_start=True,alns=True,valid_inequalities=True,phase_shares=_shares(.05,.15,.25)),
 "algorithm-candidate-v1":_cfg("algorithm-candidate-v1",aggregate_recourse_lb=True,status="frozen_candidate"),
 "bbc_core":_cfg("bbc_core"),
 "bbc_valid":_cfg("bbc_valid",valid_inequalities=True),
 "bbc_analytic_lb":_cfg("bbc_analytic_lb",analytic_recourse_lb=True),
 "bbc_aggregate_lb":_cfg("bbc_aggregate_lb",aggregate_recourse_lb=True),
 "bbc_root":_cfg("bbc_root",root_prepass=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,phase_shares=_shares(root=.05)),
 "bbc_warm":_cfg("bbc_warm",warm_start=True,phase_shares=_shares(warm=.15)),
 "bbc_alns":_cfg("bbc_alns",warm_start=True,alns=True,phase_shares=_shares(warm=.15,alns=.25)),
 "bbc_root_warm":_cfg("bbc_root_warm",root_prepass=True,warm_start=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,phase_shares=_shares(.05,.15)),
 "bbc_root_alns":_cfg("bbc_root_alns",root_prepass=True,warm_start=True,alns=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,phase_shares=_shares(.05,.15,.25)),
 "bbc_full_current":_cfg("bbc_full_current",root_prepass=True,warm_start=True,alns=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,valid_inequalities=True,phase_shares=_shares(.05,.15,.25)),
 "bbc_stabilized":_cfg("bbc_stabilized",root_prepass=True,warm_start=True,alns=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,valid_inequalities=True,cut_strategy="stabilized",phase_shares=_shares(.05,.15,.25)),
 "bbc_node_cuts":_cfg("bbc_node_cuts",root_prepass=True,warm_start=True,alns=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,valid_inequalities=True,node_cuts=True,phase_shares=_shares(.05,.15,.25)),
}
ACTIVE_CONFIGURATIONS = ("algorithm-candidate-v1",)
CONFIGURATION_VISIBILITY = {
    name: ("active" if name in ACTIVE_CONFIGURATIONS else "historical_development")
    for name in CONFIGURATIONS
}


def list_algorithm_configurations(*, include_historical=False):
    """List normal CLI choices without changing any hashed payload."""
    return tuple(CONFIGURATIONS) if include_historical else ACTIVE_CONFIGURATIONS


def configuration_registry_status(name):
    """Return visibility metadata deliberately stored outside the payload."""
    if name not in CONFIGURATIONS:
        raise KeyError(name)
    return CONFIGURATION_VISIBILITY[name]


def get_algorithm_configuration(name):
    if name not in CONFIGURATIONS:raise KeyError(f"unknown algorithm configuration {name!r}; available: {', '.join(CONFIGURATIONS)}")
    value=deepcopy(CONFIGURATIONS[name]);value["configuration_hash"]=configuration_hash(value);validate_algorithm_configuration(value);return value
