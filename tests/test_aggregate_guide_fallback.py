import time

from config import Weights
from data import get_data_tiny_benders, prepare_instance
import solver_aggregate_guide as guide


def test_lp_fallback_is_used_when_mip_has_no_incumbent(monkeypatch):
    real_build = guide.build_master_model

    def build(*args, **kwargs):
        if not kwargs.get("relax", False):
            raise RuntimeError("simulated MIP without extractable point")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(guide, "build_master_model", build)
    data = prepare_instance(get_data_tiny_benders())
    result = guide.solve_aggregate_guide(data, Weights(), time_limit=2)
    assert result["ok"] and result["source"] == "lp_fallback"
    assert result["x"] and result["aggregate_z"]


def test_static_fallback_is_harmless(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("expected guide failure")

    monkeypatch.setattr(guide, "build_master_model", fail)
    data = prepare_instance(get_data_tiny_benders())
    result = guide.solve_aggregate_guide(data, Weights(), time_limit=1)
    assert result["ok"] and result["source"] == "static_fallback"
    assert result["x"] == result["alloc_boxes"] == result["aggregate_z"] == {}
    assert "fallback_errors" in result["diagnostics"]


def test_zero_budget_respects_deadline_and_never_builds(monkeypatch):
    monkeypatch.setattr(
        guide, "build_master_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called"))
    )
    data = prepare_instance(get_data_tiny_benders())
    started = time.perf_counter()
    result = guide.solve_aggregate_guide(data, Weights(), time_limit=0)
    assert result["source"] == "static_fallback"
    assert time.perf_counter() - started < 0.1


def test_module_does_not_call_recourse_oracle(monkeypatch):
    import model_recourse

    monkeypatch.setattr(
        model_recourse,
        "GlobalRecourseOracle",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("recourse called")),
    )
    data = prepare_instance(get_data_tiny_benders())
    assert guide.solve_aggregate_guide(data, Weights(), time_limit=2)["ok"]
