from data import prepare_instance,simulate_old_inventory,TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR,validate_instance_units
from instance_registry import build_builtin_instance,list_builtin_instances
from model_common import groups,group_size,remaining_capacity

def test_handling_rate_units_and_metadata():
 d=prepare_instance(build_builtin_instance("tiny"));assert set(d['Bay_Handling_Rate'].values())=={TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR} and d['handling_rate_source']=='instance_scaled'

def test_all_builtins_pass_pure_data_checks():
 for name in list_builtin_instances():
  d=prepare_instance(build_builtin_instance(name));validate_instance_units(d)
  assert min(remaining_capacity(d).values())>=-1e-9
  assert max(simulate_old_inventory(d)["unserved_outbound"].values(),default=0)<=1e-9
  for j in d["J_new"]:
   for size in d["S"]:
    matching=[g for g in groups(d) if group_size(d,g)==int(size)]
    for n in d["N"]:assert abs(sum(d["Arrivals_group_interval"][j,g,n] for g in matching)-d["Arrivals_interval"][j,size,n])<=1e-6

def test_3new6old_is_deterministic():
 assert build_builtin_instance("3new6old")==build_builtin_instance("3new6old")
