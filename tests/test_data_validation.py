from data import get_data_tiny_benders,prepare_instance,TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR
def test_handling_rate_units_and_metadata():
 d=prepare_instance(get_data_tiny_benders());assert set(d['Bay_Handling_Rate'].values())=={TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR} and d['handling_rate_source']=='model_calibration'
