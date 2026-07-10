import pytest
from solver_true_benders import master_point_cache_key
def point(alloc=2,eta=0):return {"x":{("i","j",0):1.0,("z","j",0):0.0},"alloc_boxes":{("i","j","g",0):alloc},"eta":eta}
def test_same_point_different_order_same_key():
 a=point();b={"x":dict(reversed(list(a["x"].items()))),"alloc_boxes":dict(reversed(list(a["alloc_boxes"].items()))),"eta":99};assert master_point_cache_key(a,"integer")==master_point_cache_key(b,"integer")
def test_allocation_change_changes_key():assert master_point_cache_key(point(2),"integer")!=master_point_cache_key(point(3),"integer")
def test_eta_not_in_key():assert master_point_cache_key(point(2,0),"integer")==master_point_cache_key(point(2,100),"integer")
def test_continuous_close_points_not_merged():assert master_point_cache_key(point(1.00000000001),"continuous")!=master_point_cache_key(point(1.00000000002),"continuous")
def test_integer_key_rejects_fractional_alloc():
 with pytest.raises(AssertionError):master_point_cache_key(point(1.2),"integer")
