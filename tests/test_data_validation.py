import math
from data import get_data_3new6old_fixed, prepare_instance, validate_instance_units, TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR

def test_handling_rate_is_boxes_per_hour():
    d=prepare_instance(get_data_3new6old_fixed()); assert d["handling_rate_source"]=="model_calibration"; assert set(d["Bay_Handling_Rate"].values())=={TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR}
def test_nonnegative_instance_data():
    validate_instance_units(prepare_instance(get_data_3new6old_fixed()))
def test_interval_duration_positive():
    assert all(x["dur"]>0 for x in get_data_3new6old_fixed()["Intervals"])
def test_old_occupancy_within_capacity():
    d=prepare_instance(get_data_3new6old_fixed()); assert all(sum(v for (b,_j,_s),v in d["initial_inventory_data"].items() if b==i)<=d["I"][i]["cap"] for i in d["I_list"])
def test_required_keys_exist():
    d=prepare_instance(get_data_3new6old_fixed()); validate_instance_units(d); assert all((i,n) in d["Bay_Handling_Rate"] for i in d["I_list"] for n in d["N"])
def test_nan_rejected():
    d=prepare_instance(get_data_3new6old_fixed()); d["Bay_Handling_Rate"][next(iter(d["Bay_Handling_Rate"]))]=math.nan
    try: validate_instance_units(d)
    except ValueError: return
    raise AssertionError("NaN was not rejected")
