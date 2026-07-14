from pathlib import Path

import pytest


GUROBI_TEST_MODULES = {
    "test_alns.py", "test_alns_neighborhood.py", "test_bbc_cache.py",
    "test_benders_bounds.py", "test_benders_cuts.py", "test_gap95_followup.py",
    "test_joint_concentration.py", "test_pipeline_control.py",
    "test_pipeline_defaults.py", "test_recourse_oracle.py",
    "test_timing_and_determinism.py", "test_agfr_start_solution.py",
    "test_agfr_trace.py", "test_agfr_fallback.py",
}


def pytest_collection_modifyitems(items):
    """Keep solver-backed regression tests selectable on unlicensed machines."""
    marker = pytest.mark.gurobi
    for item in items:
        if Path(str(item.fspath)).name in GUROBI_TEST_MODULES:
            item.add_marker(marker)
