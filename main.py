"""Configuration-driven single-instance Branch-and-Benders-Cut CLI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from datetime import datetime

from algorithm_configuration import configuration_hash, resolved_algorithm_label, validate_algorithm_configuration
from algorithm_configurations import get_algorithm_configuration, list_algorithm_configurations
from config import MasterWeights, Weights
from data import prepare_instance
from instance_registry import list_builtin_instances, resolve_instance
from solver_true_benders import solve_true_benders_pipeline


def serial(value):
    if isinstance(value, dict):
        return {("|".join(map(str, key)) if isinstance(key, tuple) else str(key)): serial(item)
                for key, item in value.items() if key != "cut_pool"}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    return value


def parser(*, include_historical=False):
    value = argparse.ArgumentParser(description="Configuration-driven exact BBC runner")
    source = value.add_mutually_exclusive_group()
    source.add_argument("--instance", choices=list_builtin_instances(), default="3new6old")
    source.add_argument("--instance-file")
    value.add_argument("--include-historical-configs", action="store_true",
                       help="show and allow archived development configurations")
    value.add_argument("--algorithm-config",
                       choices=list_algorithm_configurations(include_historical=include_historical),
                       default="algorithm-candidate-v1")
    value.add_argument("--total-core-time", type=float, default=60)
    for flag in ("root-cut-prepass", "aggregate-recourse-lb", "analytic-recourse-lb",
                 "valid-inequalities", "warm-start", "alns", "node-cuts"):
        value.add_argument(f"--{flag}", action=argparse.BooleanOptionalAction, default=None)
    for phase in ("root", "warm-start", "alns", "main-bbc"):
        value.add_argument(f"--{phase}-time-share", type=float)
    value.add_argument("--cut-strategy", choices=("standard", "stabilized"))
    value.add_argument("--concentration", action=argparse.BooleanOptionalAction, default=True)
    value.add_argument("--concentration-mode", choices=("joint-group-bay",), default="joint-group-bay")
    value.add_argument("--concentration-weight", type=float, default=10)
    value.add_argument("--old-outbound-release-policy", choices=("proportional", "legacy_sorted", "conservative"), default="proportional")
    value.add_argument("--handling-rate-scale", type=float, default=1)
    value.add_argument("--alloc-domain", choices=("integer", "continuous"), default="integer")
    value.add_argument("--mip-gap", type=float, default=.03)
    value.add_argument("--numeric-focus", type=int, choices=range(4), default=1)
    value.add_argument("--threads", type=int, default=1)
    value.add_argument("--seed", type=int, default=0)
    value.add_argument("--output-root", default="outputs")
    return value


def resolve_configuration(args):
    base = get_algorithm_configuration(args.algorithm_config)
    configuration = deepcopy(base)
    field_overrides = {
        "root_prepass": args.root_cut_prepass, "aggregate_recourse_lb": args.aggregate_recourse_lb,
        "analytic_recourse_lb": args.analytic_recourse_lb, "valid_inequalities": args.valid_inequalities,
        "warm_start": args.warm_start, "alns": args.alns, "node_cuts": args.node_cuts,
        "cut_strategy": args.cut_strategy,
    }
    changed = []
    for key, override in field_overrides.items():
        if override is not None and override != configuration[key]:
            configuration[key] = override; changed.append(key)
    shares = dict(configuration["phase_shares"])
    phase_overrides = {"root": args.root_time_share, "warm": args.warm_start_time_share,
                       "alns": args.alns_time_share, "main": args.main_bbc_time_share}
    for key, override in phase_overrides.items():
        if override is not None and override != shares[key]:
            shares[key] = override; changed.append(f"phase_shares.{key}")
    configuration["phase_shares"] = shares
    if changed:
        configuration.pop("configuration_hash", None)
        configuration["configuration_name"] = f"{base['configuration_name']}-development-override"
        configuration["configuration_version"] = f"{base['configuration_version']}-override"
        configuration["status"] = "development_override"
        configuration["configuration_hash"] = configuration_hash(configuration)
        print("WARNING: frozen/registered configuration overridden; result is development_override: " + ", ".join(changed), file=sys.stderr)
    validate_algorithm_configuration(configuration)
    return configuration


def main():
    include_historical = "--include-historical-configs" in sys.argv[1:]
    args = parser(include_historical=include_historical).parse_args(); configuration = resolve_configuration(args)
    raw = resolve_instance(builtin_name=None if args.instance_file else args.instance, instance_file=args.instance_file)
    data = prepare_instance(raw, handling_rate_scale=args.handling_rate_scale,
                            old_outbound_release_policy=args.old_outbound_release_policy)
    shares = configuration["phase_shares"]
    weights = Weights(master=MasterWeights(concentration=args.concentration_weight))
    result = solve_true_benders_pipeline(
        data, weights, total_core_time=args.total_core_time, root_time_share=shares["root"],
        warm_start_time_share=shares["warm"], alns_time_share=shares["alns"], main_bbc_time_share=shares["main"],
        mip_gap=args.mip_gap, alloc_domain=args.alloc_domain, concentration_enabled=args.concentration,
        add_valid_inequalities=configuration["valid_inequalities"],
        aggregate_recourse_lb=configuration["aggregate_recourse_lb"],
        analytic_recourse_lb=configuration["analytic_recourse_lb"], cut_strategy=configuration["cut_strategy"],
        root_prepass=configuration["root_prepass"], node_cuts=configuration["node_cuts"],
        enable_alns=configuration["alns"], warm_start=configuration["warm_start"],
        seed=args.seed, threads=args.threads, numeric_focus=args.numeric_focus,
        lns_options=configuration.get("alns_parameters"), primal_repair=configuration.get("primal_repair",False),
        primal_repair_time_share=configuration.get("primal_repair_time_share",.08),
        primal_repair_min_seconds=configuration.get("primal_repair_min_seconds",2),
        primal_repair_max_seconds=configuration.get("primal_repair_max_seconds",20),
        primal_repair_guide_share=configuration.get("primal_repair_guide_share",.25),
        primal_repair_mip_gap=configuration.get("primal_repair_mip_gap",.05),
        primal_repair_max_expansions=configuration.get("primal_repair_max_expansions",2))
    result["configuration_identity"] = {"configuration_name": configuration["configuration_name"],
                                          "configuration_version": configuration["configuration_version"],
                                          "configuration_hash": configuration["configuration_hash"],
                                          "configuration_status": configuration["status"],
                                          "resolved_algorithm_label": resolved_algorithm_label(configuration)}
    label = args.instance if not args.instance_file else os.path.splitext(os.path.basename(args.instance_file))[0]
    output = os.path.abspath(os.path.join(args.output_root, f"bbc_{datetime.now():%Y%m%d_%H%M%S}_{label}"))
    os.makedirs(output, exist_ok=True)
    if result.get("ok"):
        with open(os.path.join(output, "core_best_solution.json"), "w", encoding="utf8") as handle:
            json.dump(serial(result["core_best"]["solution"]), handle, indent=2)
        result["core_best"]["solution_file"] = "core_best_solution.json"
    with open(os.path.join(output, "summary.json"), "w", encoding="utf8") as handle:
        json.dump(serial(result), handle, indent=2, default=str)
    print(json.dumps(result["configuration_identity"], indent=2))
    print(f"Summary: {os.path.join(output, 'summary.json')}")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
