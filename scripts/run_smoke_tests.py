"""Small, explicit smoke checks for repository and solver health."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Weights
from data import prepare_instance, validate_instance_units
from instance_registry import build_builtin_instance, list_builtin_instances
from model_concentration import concentration_metadata
from solution_validation import validate_solution


def check(label, action):
    try:
        action()
    except Exception:
        print(f"FAIL {label}")
        traceback.print_exc()
        return False
    print(f"PASS {label}")
    return True


def prepared(name):
    return prepare_instance(
        build_builtin_instance(name),
        handling_rate_scale=1.0,
        old_outbound_release_policy="proportional",
    )


def pure_checks():
    def inspect(name):
        data = prepared(name)
        validate_instance_units(data)
        meta = concentration_metadata(data)
        assert meta["available"] == (name in {"tiny", "tiny_concentration", "3new6old"})

    return [(f"import/build/validate/concentration {name}", lambda n=name: inspect(n)) for name in list_builtin_instances()]


def gurobi_checks():
    from model_monolithic import build_monolithic_model
    from solve_direct_gurobi import solve_direct_gurobi
    from solver_true_benders import solve_bbc_phase

    def direct(name):
        data = prepared(name)
        result = solve_direct_gurobi(data, Weights(), time_limit=8, mip_gap=0, threads=1)
        assert result["ok"], result
        report = validate_solution(data, result["solution"])
        assert report["feasible"], report
        assert abs(result["ub"] - result["components"]["core_cost"]) <= 1e-5

    def bbc(name):
        data = prepared(name)
        result = solve_bbc_phase(data, Weights(), time_limit=8, mip_gap=0, threads=1)
        assert result["ok"], result
        report = validate_solution(data, result["solution"])
        assert report["feasible"], report

    def build_large():
        model, _, _ = build_monolithic_model(prepared("3new6old"), Weights())
        model.update()
        assert model.NumVars > 0 and model.NumConstrs > 0

    def short_large(solver, label):
        data = prepared("3new6old")
        result = solver(data, Weights(), time_limit=3, mip_gap=.03, threads=1)
        status = result.get("status_name")
        assert isinstance(status, str) and status, f"{label} returned no status: {result}"
        if result.get("ok"):
            report = validate_solution(data, result["solution"])
            assert report["feasible"], report
            if label == "Direct":
                assert abs(result["ub"] - result["components"]["core_cost"]) <= 1e-5
        print(f"INFO {label} 3new6old status={status} incumbent={result.get('ok', False)}")

    return [
        ("Direct tiny", lambda: direct("tiny")),
        ("BBC tiny", lambda: bbc("tiny")),
        ("Direct tiny_concentration", lambda: direct("tiny_concentration")),
        ("BBC tiny_concentration", lambda: bbc("tiny_concentration")),
        ("3new6old model build", build_large),
        ("Direct 3new6old short solve", lambda: short_large(solve_direct_gurobi, "Direct")),
        ("BBC 3new6old short solve", lambda: short_large(solve_bbc_phase, "BBC")),
    ]


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pure", action="store_true")
    mode.add_argument("--gurobi", action="store_true")
    args = parser.parse_args()
    checks = pure_checks() if args.pure else pure_checks() + gurobi_checks()
    return 0 if all(check(label, action) for label, action in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
