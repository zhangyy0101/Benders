import pytest
from pilot_benchmark_suite import PILOT_VERSION,RANGES,SEEDS,pilot_specs,suite_metrics
from synthetic_instance_generator import generate_synthetic_instance

@pytest.fixture(scope="module")
def generated():return {iid:(size,generate_synthetic_instance(spec,SEEDS[iid])) for iid,(size,spec) in pilot_specs().items()}

def test_pilot21_is_generated_in_memory_not_a_new_fixed_suite(generated):
 assert PILOT_VERSION=="paper-exp-v1-pilot2"

def test_five_level_conservation_and_metadata(generated):
 for _iid,(_size,d) in generated.items():
  for j in d["J_new"]:
   total=d["ships_config"][j]["total_boxes"];assert isinstance(total,int) and total>0
   assert sum(d["PODVolumeByShip"][j].values())==total
   assert sum(d["GroupVolumeByShip"][j].values())==total
   assert len(set(d["PODVolumeByShip"][j].values()))>1
   for pod,pod_total in d["PODVolumeByShip"][j].items():
    assert sum(d["PODSizeVolumeByShip"][j][pod].values())==pod_total
    for size,size_total in d["PODSizeVolumeByShip"][j][pod].items():
     groups=[g for g in d["ActiveGroupsByShip"][j] if d["GroupPOD"][g]==pod and d["GroupSize"][g]==int(size)]
     assert sum(d["GroupVolumeByShip"][j][g] for g in groups)==size_total
   for g,volume in d["GroupVolumeByShip"][j].items():
    assert isinstance(volume,int) and volume>=2
    assert sum(d["Arrivals_group_interval"][j,g,n] for n in d["N"])==pytest.approx(volume)
   actual={str(s):sum(v for g,v in d["GroupVolumeByShip"][j].items() if d["GroupSize"][g]==s)/total for s in d["S"]}
   assert d["ActualSizeShareByShip"][j]==pytest.approx(actual);assert d["ships_config"][j]["actual_size_share"]==pytest.approx(actual);assert "share_20ft" not in d["ships_config"][j]
   for s in d["S"]:
    for n in d["N"]:assert sum(d["Arrivals_group_interval"].get((j,g,n),0) for g in d["ActiveGroupsByShip"][j] if d["GroupSize"][g]==s)==pytest.approx(d["Arrivals_interval"][j,s,n])

def test_singleton_ratios_and_same_size_scenario_diversity(generated):
 single={"small":(.30,.50),"medium":(.20,.40),"large":(.10,.30)}
 for size in single:
  metrics=[suite_metrics(d) for _iid,(s,d) in generated.items() if s==size]
  assert all(single[size][0]<=m["single_combination_pod_ratio"]<=single[size][1] for m in metrics)
  assert len({m["arrival_overlap_ratio"] for m in metrics})>1
  assert len({m["positive_pressure_block_period_ratio"] for m in metrics})>1
  assert all(RANGES[size]["overlap"][0]<=m["arrival_overlap_ratio"]<=RANGES[size]["overlap"][1] for m in metrics)
  assert all(RANGES[size]["pressure"][0]<=m["positive_pressure_block_period_ratio"]<=RANGES[size]["pressure"][1] for m in metrics)
