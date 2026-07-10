from __future__ import annotations

import copy
import json
import math
import os
import random
import re


TIME_BUCKET_HOURS = 6.0
_FIXED_3N6O_CACHE = None

# Capacity is modeled directly in boxes.
TOS_NUM_YARD_BLOCKS = 10
TOS_YARD_BAYS = 10
TOS_BAY_CAPACITY_BOXES = 50.0
TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR = 50.0
TOS_NUM_BERTHS = 3


def prepare_instance(data: dict, handling_rate_scale: float = 1.0) -> dict:
    """Attach calibrated boxes/hour rates and validate a fresh instance."""
    scale = float(handling_rate_scale)
    if not math.isfinite(scale) or scale < 0:
        raise ValueError("handling_rate_scale must be finite and nonnegative")
    result = copy.deepcopy(data)
    result["Bay_Handling_Rate"] = {
        (i, n): TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR * scale
        for i in result["I_list"] for n in result["N"]
    }
    result["handling_rate_base"] = TOS_BAY_HANDLING_RATE_BOXES_PER_HOUR
    result["handling_rate_scale"] = scale
    result["handling_rate_source"] = "model calibration"
    validate_instance_units(result)
    return result


def validate_instance_units(data: dict) -> None:
    """Reject incomplete, dimensionally invalid, or non-finite model data."""
    required = ("K", "I", "I_list", "Bays_in_Block", "J_new", "J_old", "S", "N",
                "Intervals", "Dist", "Arrivals_interval", "Fixed_Bay_Mode",
                "Old_Box_Occupancy_Map", "Bay_Handling_Rate")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"missing instance keys: {missing}")
    def number(value, label):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{label} contains NaN/inf")
        return value
    valid_modes = {int(s) for s in data["S"]}
    groups = list(data.get("G") or data["S"])
    for g in groups:
        size = int(data.get("GroupSize", {}).get(g, data.get("GroupAttrs", {}).get(g, {}).get("size", g)))
        if size not in valid_modes:
            raise ValueError(f"group {g} has invalid size {size}")
    for i in data["I_list"]:
        cap = number(data["I"][i]["cap"], f"capacity[{i}]")
        if cap < 0: raise ValueError(f"negative capacity for {i}")
        if int(data["Fixed_Bay_Mode"][i]) not in valid_modes:
            raise ValueError(f"invalid Fixed_Bay_Mode for {i}")
        initial = sum(number(v, "initial occupancy") for (bay, _j, _s), v in data.get("initial_inventory_data", {}).items() if bay == i)
        if initial > cap + 1e-9: raise ValueError(f"old occupancy exceeds capacity for {i}")
        for n in data["N"]:
            if (i, n) not in data["Bay_Handling_Rate"]:
                raise ValueError(f"missing handling rate for {(i, n)}")
            if number(data["Bay_Handling_Rate"][(i, n)], "handling rate") < 0:
                raise ValueError(f"negative handling rate for {(i, n)}")
    for n in data["N"]:
        if number(data["Intervals"][n]["dur"], "duration") <= 0: raise ValueError("interval duration must be positive")
    for key, value in data["Arrivals_interval"].items():
        if number(value, f"arrival[{key}]") < 0: raise ValueError(f"negative arrival at {key}")
    for j in data["J_new"]:
        for k in data["K"]:
            if (j, k) not in data["Dist"]:
                raise ValueError(f"missing Dist key {(j, k)}")
            number(data["Dist"][(j, k)], f"Dist[{j},{k}]")
        for n in data["N"]:
            for s in data["S"]:
                if (j, s, n) not in data["Arrivals_interval"]:
                    raise ValueError(f"missing arrival key {(j, s, n)}")
    numeric_maps = ("Fixed_In_Flow", "Block_Outbound_Vol", "Block_Outbound_Req",
                    "Old_Box_Occupancy_Map", "Arrivals_group_interval")
    for map_name in numeric_maps:
        for key, value in data.get(map_name, {}).items():
            if number(value, f"{map_name}[{key}]") < 0:
                raise ValueError(f"negative value in {map_name} at {key}")


def _build_yard(num_blocks: int = TOS_NUM_YARD_BLOCKS, bays_per_block: int = TOS_YARD_BAYS):
    K = [f"Block_{chr(ord('A') + idx)}" for idx in range(num_blocks)]
    I = {}
    for blk in K:
        letter = blk.split("_")[1]
        for bay_no in range(1, bays_per_block + 1):
            bay = f"Bay_{letter}{bay_no:02d}"
            I[bay] = {"block": blk, "cap": float(TOS_BAY_CAPACITY_BOXES)}

    I_list = list(I.keys())
    Bays_in_Block = {k: [] for k in K}
    for bay, info in I.items():
        Bays_in_Block[info["block"]].append(bay)
    return K, I, I_list, Bays_in_Block


def _build_intervals(t_max: float):
    Intervals = []
    t = 0.0
    idx = 0
    while t < t_max - 1e-9:
        t_next = min(t_max, t + TIME_BUCKET_HOURS)
        Intervals.append({"id": idx, "start": t, "end": t_next, "dur": t_next - t})
        t = t_next
        idx += 1
    return Intervals, list(range(len(Intervals)))


def _uniform_volume(total: float, src_start: float, src_end: float, tgt_start: float, tgt_end: float) -> float:
    if total <= 0.0 or src_end <= src_start:
        return 0.0
    overlap = max(0.0, min(src_end, tgt_end) - max(src_start, tgt_start))
    if overlap <= 1e-9:
        return 0.0
    return float(total) * overlap / (src_end - src_start)


def _triangle_volume(conf: dict, size: int, t_start: float, t_end: float) -> float:
    total = float(conf["total_40"] if int(size) == 40 else conf["total_20"])
    if total <= 0.0:
        return 0.0

    s0 = float(conf["start"])
    e0 = s0 + float(conf["dur"])
    p0 = s0 + float(conf["dur"]) * float(conf["peak"])

    a = max(t_start, s0)
    b = min(t_end, e0)
    if b <= a + 1e-12:
        return 0.0

    if p0 <= s0 + 1e-12 or p0 >= e0 - 1e-12:
        return total * (b - a) / max(e0 - s0, 1e-12)

    h_peak = 2.0 * total / (e0 - s0)
    vol = 0.0

    left_a = a
    left_b = min(b, p0)
    if left_b > left_a + 1e-12:
        vol += h_peak * (((left_b - s0) ** 2) - ((left_a - s0) ** 2)) / (2.0 * (p0 - s0))

    right_a = max(a, p0)
    right_b = b
    if right_b > right_a + 1e-12:
        vol += h_peak * (((e0 - right_a) ** 2) - ((e0 - right_b) ** 2)) / (2.0 * (e0 - p0))

    return vol


def _empty_time_maps(K, I_list, J_old, S, N):
    Arrivals_interval = {}
    Block_Outbound_Vol = {}
    Block_Outbound_Req = {}
    Fixed_In_Flow = {}
    Fixed_Mode_Force = {}

    for n in N:
        for k in K:
            Block_Outbound_Vol[(k, n)] = 0.0
            for j in J_old:
                Block_Outbound_Req[(k, j, n)] = 0.0
        for i in I_list:
            Fixed_Mode_Force[(i, n)] = None
            for j in J_old:
                for s in S:
                    Fixed_In_Flow[(j, s, i, n)] = 0.0
    return Arrivals_interval, Block_Outbound_Vol, Block_Outbound_Req, Fixed_In_Flow, Fixed_Mode_Force


def _berth_distance(K, J_new, ship_berth: dict | None = None):
    berths = [f"Berth_{b}" for b in range(1, TOS_NUM_BERTHS + 1)]
    block_berth_dist = {}
    for blk_idx, k in enumerate(K):
        for berth_idx, berth in enumerate(berths):
            block_berth_dist[(k, berth)] = 200 + 200 * abs(blk_idx - berth_idx)

    if ship_berth is None:
        ship_berth = {j: random.choice(berths) for j in J_new}
    Dist = {(j, k): block_berth_dist[(k, ship_berth[j])] for j in J_new for k in K}
    return berths, Dist


def _build_old_box_map(I_list, J_old, initial_inventory_data, fixed_inbound_schedule):
    old_box_map = {(i, j): 0.0 for i in I_list for j in J_old}
    old_size_map = {}

    for (bay, ship, size), qty in initial_inventory_data.items():
        if ship in J_old and float(qty) > 1e-9:
            old_box_map[(bay, ship)] += float(qty)
            old_size_map[(bay, ship)] = int(size)

    for fix in fixed_inbound_schedule:
        ship = fix["ship"]
        bay = fix["bay"]
        if ship in J_old:
            old_box_map[(bay, ship)] += float(fix["flow"])
            old_size_map[(bay, ship)] = int(fix["size"])
    return old_box_map, old_size_map


def _finalize_fixed_modes(I, I_list, initial_inventory_data, fixed_inbound_schedule, default_size: int = 40):
    fixed_bay_mode = {i: int(default_size) for i in I_list}
    for (bay, _ship, size), qty in initial_inventory_data.items():
        if float(qty) > 1e-9:
            fixed_bay_mode[bay] = int(size)
    for fix in fixed_inbound_schedule:
        fixed_bay_mode[fix["bay"]] = int(fix["size"])
    for bay, size in fixed_bay_mode.items():
        I[bay]["fixed_size_ft"] = int(size)
    return fixed_bay_mode


def _yard_structure(num_blocks: int, bays_per_block: int):
    return {
        "num_blocks": int(num_blocks),
        "bays_per_block": int(bays_per_block),
        "bay_capacity_boxes": float(TOS_BAY_CAPACITY_BOXES),
    }


def _default_3new_box_groups() -> tuple[list[str], dict[str, dict], dict[int, list[tuple[str, float]]]]:
    """
    Business-style export box groups used by the 3new6old synthetic case.

    The model still treats all new boxes as export boxes in one flow.  These
    groups only add attributes that affect soft objective terms: POD
    concentration, weight concentration, and height mixing.
    """
    group_attrs = {
        "G20_N_STD_L": {"size": 20, "pod": "POD_N", "height": "STD", "weight_class": "LIGHT"},
        "G20_S_STD_M": {"size": 20, "pod": "POD_S", "height": "STD", "weight_class": "MEDIUM"},
        "G20_E_HIGH_H": {"size": 20, "pod": "POD_E", "height": "HIGH", "weight_class": "HEAVY"},
        "G40_N_STD_M": {"size": 40, "pod": "POD_N", "height": "STD", "weight_class": "MEDIUM"},
        "G40_S_HIGH_H": {"size": 40, "pod": "POD_S", "height": "HIGH", "weight_class": "HEAVY"},
        "G40_E_STD_L": {"size": 40, "pod": "POD_E", "height": "STD", "weight_class": "LIGHT"},
    }
    split_by_size = {
        20: [("G20_N_STD_L", 0.45), ("G20_S_STD_M", 0.35), ("G20_E_HIGH_H", 0.20)],
        40: [("G40_N_STD_M", 0.45), ("G40_S_HIGH_H", 0.35), ("G40_E_STD_L", 0.20)],
    }
    return list(group_attrs), group_attrs, split_by_size


def get_data_3new6old() -> dict:
    """
    Deterministic 3-new/6-old instance.

    The yard and every flow quantity are measured directly in boxes. Old
    inventory and fixed inbound occupy bay capacity exactly as box counts.
    """
    K, I, I_list, Bays_in_Block = _build_yard()
    J_new = ["Ship_New_1", "Ship_New_2", "Ship_New_3"]
    J_old = [f"Ship_Old_{i:02d}" for i in range(1, 7)]
    J_all = J_old + J_new
    S = [20, 40]
    Alpha = 1.1
    T_max = 72.0
    ship_berth = {
        "Ship_New_1": "Berth_1",
        "Ship_New_2": "Berth_2",
        "Ship_New_3": "Berth_3",
    }
    berths, Dist = _berth_distance(K, J_new, ship_berth)
    G, GroupAttrs, group_split_by_size = _default_3new_box_groups()

    inbound_old = ["Ship_Old_01", "Ship_Old_02", "Ship_Old_03"]
    outbound_old = ["Ship_Old_04", "Ship_Old_05", "Ship_Old_06"]
    old_size = 20
    qty_per_bay = 50.0

    old_initial_bays = {
        "Ship_Old_01": ["Bay_A01", "Bay_A02", "Bay_B01", "Bay_B02"],
        "Ship_Old_02": ["Bay_C01", "Bay_C02", "Bay_D01", "Bay_D02"],
        "Ship_Old_03": ["Bay_E01", "Bay_E02", "Bay_F01", "Bay_F02"],
        "Ship_Old_04": ["Bay_G01", "Bay_G02", "Bay_H01", "Bay_H02"],
        "Ship_Old_05": ["Bay_I01", "Bay_I02", "Bay_J01", "Bay_J02"],
        "Ship_Old_06": ["Bay_G03", "Bay_G04", "Bay_H03", "Bay_H04"],
    }
    inbound_reserve_bays = {
        "Ship_Old_01": ["Bay_A03", "Bay_A04", "Bay_B03", "Bay_B04"],
        "Ship_Old_02": ["Bay_C03", "Bay_C04", "Bay_D03", "Bay_D04"],
        "Ship_Old_03": ["Bay_E03", "Bay_E04", "Bay_F03", "Bay_F04"],
    }

    all_old_bays = []
    for bays in old_initial_bays.values():
        all_old_bays.extend(bays)
    for bays in inbound_reserve_bays.values():
        all_old_bays.extend(bays)
    if len(all_old_bays) != len(set(all_old_bays)):
        raise RuntimeError("Old-ship bay layout has collisions.")

    initial_inventory_data = {}
    for ship, bays in old_initial_bays.items():
        for bay in bays:
            initial_inventory_data[(bay, ship, old_size)] = qty_per_bay

    ships_config = {
        "Ship_New_1": {"start": 0.0, "dur": 72.0, "total_40": 500.0, "total_20": 300.0, "peak": 0.50},
        "Ship_New_2": {"start": 0.0, "dur": 66.0, "total_40": 460.0, "total_20": 340.0, "peak": 0.50},
        "Ship_New_3": {"start": 0.0, "dur": 60.0, "total_40": 420.0, "total_20": 380.0, "peak": 0.50},
    }

    fixed_inbound_schedule = []
    for ship in inbound_old:
        for bay in inbound_reserve_bays[ship]:
            fixed_inbound_schedule.append(
                {"ship": ship, "size": old_size, "bay": bay, "start": 0.0, "end": 72.0, "flow": qty_per_bay}
            )

    outbound_requests = [
        {"block": "Block_G", "ship": "Ship_Old_04", "start": 0.0, "end": 72.0, "total": 80.0},
        {"block": "Block_H", "ship": "Ship_Old_04", "start": 0.0, "end": 72.0, "total": 80.0},
        {"block": "Block_I", "ship": "Ship_Old_05", "start": 0.0, "end": 72.0, "total": 80.0},
        {"block": "Block_J", "ship": "Ship_Old_05", "start": 0.0, "end": 72.0, "total": 80.0},
        {"block": "Block_G", "ship": "Ship_Old_06", "start": 0.0, "end": 72.0, "total": 80.0},
        {"block": "Block_H", "ship": "Ship_Old_06", "start": 0.0, "end": 72.0, "total": 80.0},
    ]

    Fixed_Bay_Mode = _finalize_fixed_modes(I, I_list, initial_inventory_data, fixed_inbound_schedule)
    extra_20ft_per_block = 3
    converted_by_block = {k: 0 for k in K}
    touched_old_bays = set(all_old_bays)
    for bay in I_list:
        block = I[bay]["block"]
        if converted_by_block[block] >= extra_20ft_per_block:
            continue
        if bay in touched_old_bays:
            continue
        if int(Fixed_Bay_Mode.get(bay, 40)) != 40:
            continue
        Fixed_Bay_Mode[bay] = old_size
        I[bay]["fixed_size_ft"] = old_size
        converted_by_block[block] += 1

    Old_Box_Occupancy_Map, Old_Ship_Size_Map = _build_old_box_map(
        I_list, J_old, initial_inventory_data, fixed_inbound_schedule
    )

    Intervals, N = _build_intervals(T_max)
    (
        Arrivals_interval,
        Block_Outbound_Vol,
        Block_Outbound_Req,
        Fixed_In_Flow,
        Fixed_Mode_Force,
    ) = _empty_time_maps(K, I_list, J_old, S, N)
    Arrivals_group_interval = {(j, g, n): 0.0 for j in J_new for g in G for n in N}

    for n in N:
        iv = Intervals[n]
        for ship in J_new:
            for size in S:
                vol = _triangle_volume(ships_config[ship], size, iv["start"], iv["end"])
                Arrivals_interval[(ship, size, n)] = vol
                for group, share in group_split_by_size[int(size)]:
                    Arrivals_group_interval[(ship, group, n)] += vol * float(share)

        for fix in fixed_inbound_schedule:
            vol = _uniform_volume(fix["flow"], fix["start"], fix["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Fixed_In_Flow[(fix["ship"], fix["size"], fix["bay"], n)] += vol
                Fixed_Mode_Force[(fix["bay"], n)] = fix["size"]

        for req in outbound_requests:
            vol = _uniform_volume(req["total"], req["start"], req["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Block_Outbound_Req[(req["block"], req["ship"], n)] += vol
                Block_Outbound_Vol[(req["block"], n)] += vol

    return {
        "K": K,
        "I": I,
        "I_list": I_list,
        "Bays_in_Block": Bays_in_Block,
        "J_new": J_new,
        "J_old": J_old,
        "J_all": J_all,
        "S": S,
        "G": G,
        "GroupAttrs": copy.deepcopy(GroupAttrs),
        "GroupSize": {g: int(attrs["size"]) for g, attrs in GroupAttrs.items()},
        "GroupPOD": {g: attrs["pod"] for g, attrs in GroupAttrs.items()},
        "GroupHeight": {g: attrs["height"] for g, attrs in GroupAttrs.items()},
        "GroupWeightClass": {g: attrs["weight_class"] for g, attrs in GroupAttrs.items()},
        "Alpha": Alpha,
        "Intervals": Intervals,
        "N": N,
        "TimeBucketHours": TIME_BUCKET_HOURS,
        "NumBerths": TOS_NUM_BERTHS,
        "Berths": berths,
        "YardStructure": _yard_structure(TOS_NUM_YARD_BLOCKS, TOS_YARD_BAYS),
        "Dist": Dist,
        "Old_Ship_Size_Map": Old_Ship_Size_Map,
        "Old_Box_Occupancy_Map": Old_Box_Occupancy_Map,
        "initial_inventory_data": initial_inventory_data,
        "Arrivals_interval": Arrivals_interval,
        "Arrivals_group_interval": Arrivals_group_interval,
        "Block_Outbound_Vol": Block_Outbound_Vol,
        "Block_Outbound_Req": Block_Outbound_Req,
        "Fixed_In_Flow": Fixed_In_Flow,
        "Fixed_Mode_Force": Fixed_Mode_Force,
        "Fixed_Bay_Mode": copy.deepcopy(Fixed_Bay_Mode),
        "OldShipType": {"in_only": inbound_old, "out_only": outbound_old, "fixed_only": []},
        "ScenarioName": "3new_6old_boxes",
        "ships_config": copy.deepcopy(ships_config),
        "fixed_inbound_schedule": copy.deepcopy(fixed_inbound_schedule),
        "outbound_requests": copy.deepcopy(outbound_requests),
        "old_initial_bays": copy.deepcopy(old_initial_bays),
        "inbound_reserve_bays": copy.deepcopy(inbound_reserve_bays),
    }


def get_data_3new6old_fixed() -> dict:
    global _FIXED_3N6O_CACHE
    if _FIXED_3N6O_CACHE is None:
        _FIXED_3N6O_CACHE = get_data_3new6old()
    return copy.deepcopy(_FIXED_3N6O_CACHE)


def get_data_tiny_route_a() -> dict:
    """Small deterministic fixture designed to solve to proven optimality quickly."""
    K = ["Block_A", "Block_B"]
    I_list = ["Bay_A01", "Bay_A02", "Bay_B01", "Bay_B02"]
    I = {i: {"block": "Block_A" if "_A" in i else "Block_B", "cap": 10.0,
             "fixed_size_ft": 20 if i.endswith("01") else 40} for i in I_list}
    bays = {k: [i for i in I_list if I[i]["block"] == k] for k in K}
    J_new, J_old, S, N = ["Ship_New_1"], [], [20, 40], [0, 1]
    G = ["G20", "G40"]
    attrs = {"G20": {"size": 20, "pod": "P1", "height": "STD", "weight_class": "LIGHT"},
             "G40": {"size": 40, "pod": "P2", "height": "HIGH", "weight_class": "HEAVY"}}
    intervals = [{"id": 0, "start": 0.0, "end": 1.0, "dur": 1.0},
                 {"id": 1, "start": 1.0, "end": 2.0, "dur": 1.0}]
    arrivals_group = {(j, g, n): 2.0 for j in J_new for g in G for n in N}
    arrivals = {(j, s, n): 2.0 for j in J_new for s in S for n in N}
    return {
        "K": K, "I": I, "I_list": I_list, "Bays_in_Block": bays,
        "J_new": J_new, "J_old": J_old, "J_all": J_new, "S": S, "G": G,
        "GroupAttrs": attrs, "GroupSize": {g: attrs[g]["size"] for g in G},
        "GroupPOD": {g: attrs[g]["pod"] for g in G},
        "GroupHeight": {g: attrs[g]["height"] for g in G},
        "GroupWeightClass": {g: attrs[g]["weight_class"] for g in G},
        "Alpha": 1.0, "Intervals": intervals, "N": N,
        "Dist": {(j, k): 100.0 + 100.0 * idx for j in J_new for idx, k in enumerate(K)},
        "Fixed_Bay_Mode": {i: I[i]["fixed_size_ft"] for i in I_list},
        "Fixed_Mode_Force": {(i, n): None for i in I_list for n in N},
        "Old_Ship_Size_Map": {}, "Old_Box_Occupancy_Map": {},
        "initial_inventory_data": {}, "Arrivals_interval": arrivals,
        "Arrivals_group_interval": arrivals_group,
        "Block_Outbound_Vol": {(k, n): 0.0 for k in K for n in N},
        "Block_Outbound_Req": {}, "Fixed_In_Flow": {},
        "OldShipType": {"in_only": [], "out_only": [], "fixed_only": []},
        "ScenarioName": "tiny_route_a", "New_Outbound_Req": {},
    }


# ---------------------------------------------------------------------------
# BAPTBI original-file adapters
# ---------------------------------------------------------------------------

_BAPTBI_ORIGINAL_CACHE = {}
_BAPTBI_TIDE_HOURS = 3.0
_BAPTBI_BOX_SCALE = 0.25


_BAPTBI_INSTANCE_FILES = {
    "baptbi_5n_4b_4p": {
        "path": os.path.join("SelectedInstances", "InstancesFO1", "Soft", "instancia.10N.4B.4P.100D.dat"),
        "max_ships": 5,
    },
    "baptbi_8n_4b_4p": {
        "path": os.path.join("SelectedInstances", "InstancesFO1", "Soft", "instancia.10N.4B.4P.100D.dat"),
        "max_ships": 8,
    },
    "baptbi_10n_4b_4p": {
        "path": os.path.join("SelectedInstances", "InstancesFO1", "Soft", "instancia.10N.4B.4P.100D.dat"),
        "max_ships": None,
    },
    "baptbi_15n_4b_5p": {
        "path": os.path.join("SelectedInstances", "InstancesFO1", "Hard", "instancia.15N.4B.5P.100D.dat"),
        "max_ships": None,
    },
    "baptbi_25n_6b_5p": {
        "path": os.path.join("SelectedInstances", "InstancesFO2", "Hard", "instancia.25N.6B.5P.100D.dat"),
        "max_ships": None,
    },
}


def _baptbi_original_root() -> str:
    return os.path.join(os.path.dirname(__file__), "datasets", "baptbi_original", "selected_instances")


def _baptbi_original_path(instance_name: str) -> str:
    rel_path = _BAPTBI_INSTANCE_FILES[instance_name]["path"]
    path = os.path.join(_baptbi_original_root(), rel_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"BAPTBI original file not found: {path}. "
            "Download Mendeley dataset 58ph43s6h4 and extract "
            "Mendeley_BAPTBI_SelectedInstances.zip under "
            "Benders-changed/datasets/baptbi_original/selected_instances."
        )
    return path


def _baptbi_parse_set(text: str, name: str) -> list[str]:
    match = re.search(rf"set\s+{re.escape(name)}\s*:=\s*(.*?);", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"BAPTBI set {name} not found")
    return match.group(1).split()


def _baptbi_parse_scalar(text: str, name: str) -> float:
    match = re.search(rf"param\s+{re.escape(name)}\s*:=\s*([-+]?\d+(?:\.\d+)?)\s*;", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"BAPTBI scalar param {name} not found")
    return float(match.group(1))


def _baptbi_parse_vector(text: str, name: str) -> dict[str, float]:
    match = re.search(rf"param\s+{re.escape(name)}\s*:=\s*(.*?);", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"BAPTBI vector param {name} not found")
    values = {}
    for raw_line in match.group(1).splitlines():
        parts = raw_line.split()
        if len(parts) >= 2:
            values[parts[0]] = float(parts[1])
    return values


def _baptbi_parse_q(text: str) -> tuple[list[str], dict[str, dict[str, float]]]:
    match = re.search(r"param\s+q\s*:\s*(.*?)\s*:=\s*(.*?);", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("BAPTBI matrix param q not found")
    materials = match.group(1).split()
    q = {}
    for raw_line in match.group(2).splitlines():
        parts = raw_line.split()
        if len(parts) >= len(materials) + 1:
            ship = parts[0]
            q[ship] = {mat: float(parts[idx + 1]) for idx, mat in enumerate(materials)}
    return materials, q


def _read_baptbi_dat(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    ships = _baptbi_parse_set(text, "N")
    materials = _baptbi_parse_set(text, "K")
    berths = _baptbi_parse_set(text, "L")
    q_materials, q = _baptbi_parse_q(text)
    if q_materials != materials:
        materials = q_materials
    return {
        "ships": ships,
        "materials": materials,
        "berths": berths,
        "mares": _baptbi_parse_scalar(text, "Mares"),
        "throughput": _baptbi_parse_vector(text, "v"),
        "demurrage": _baptbi_parse_vector(text, "d"),
        "eta": _baptbi_parse_vector(text, "a"),
        "initial_inventory": _baptbi_parse_vector(text, "e"),
        "inventory_rate": _baptbi_parse_vector(text, "ck"),
        "spin": _baptbi_parse_vector(text, "spin"),
        "q": q,
    }


def _baptbi_material_size(material_idx: int) -> int:
    return 20 if material_idx % 2 == 0 else 40


def _build_baptbi_original_adapted(instance_name: str) -> dict:
    path = _baptbi_original_path(instance_name)
    raw = _read_baptbi_dat(path)

    max_ships = _BAPTBI_INSTANCE_FILES[instance_name].get("max_ships")
    original_ships = raw["ships"][:max_ships] if max_ships else raw["ships"]
    materials = raw["materials"]
    original_berths = raw["berths"]
    n_ships = len(original_ships)
    n_materials = len(materials)
    n_berths = len(original_berths)

    num_blocks = max(4, min(12, n_berths + n_materials))
    bays_per_block = max(8, min(12, 6 + (n_ships + 7) // 8))
    K, I, I_list, Bays_in_Block = _build_yard(num_blocks=num_blocks, bays_per_block=bays_per_block)
    S = [20, 40]
    Alpha = 1.0
    T_max = max(float(raw["mares"]) * _BAPTBI_TIDE_HOURS, max(raw["eta"].values()) * _BAPTBI_TIDE_HOURS + 48.0)
    Intervals, N = _build_intervals(T_max)

    J_new = [f"BAPTBI_{instance_name}_{ship}" for ship in original_ships]
    material_to_old_ship = {mat: f"BAPTBI_{instance_name}_STOCK_{mat}" for mat in materials}
    J_old = [material_to_old_ship[mat] for mat in materials]
    J_all = J_old + J_new

    ship_berth = {
        ship_name: f"Berth_{1 + (idx % TOS_NUM_BERTHS)}"
        for idx, ship_name in enumerate(J_new)
    }
    model_berths, Dist = _berth_distance(K, J_new, ship_berth)

    material_block = {mat: K[idx % len(K)] for idx, mat in enumerate(materials)}
    initial_inventory_data = {}
    fixed_inbound_schedule = []
    outbound_requests = []

    for midx, mat in enumerate(materials):
        old_ship = material_to_old_ship[mat]
        size = _baptbi_material_size(midx)
        block = material_block[mat]
        bays = Bays_in_Block[block]
        init_bay = bays[0]
        reserve_bay = bays[min(1, len(bays) - 1)]
        initial_inventory_data[(init_bay, old_ship, size)] = float(raw["initial_inventory"].get(mat, 0.0)) * _BAPTBI_BOX_SCALE

        rate = abs(float(raw["inventory_rate"].get(mat, 0.0))) * _BAPTBI_BOX_SCALE
        flow = rate * max(1.0, float(raw["mares"])) * 0.35
        if flow > 1e-9:
            fixed_inbound_schedule.append({
                "ship": old_ship,
                "size": size,
                "bay": reserve_bay,
                "start": 0.0,
                "end": T_max,
                "flow": flow,
            })

    Arrivals_interval = {(j, s, n): 0.0 for j in J_new for s in S for n in N}
    ships_config = {}
    for sidx, original_ship in enumerate(original_ships):
        ship = J_new[sidx]
        eta_time = float(raw["eta"].get(original_ship, 0.0)) * _BAPTBI_TIDE_HOURS
        berth_key = original_berths[sidx % max(1, len(original_berths))]
        throughput = max(1.0, float(raw["throughput"].get(berth_key, 1.0)))
        total_qty = sum(float(raw["q"].get(original_ship, {}).get(mat, 0.0)) for mat in materials)
        load_hours = max(12.0, min(48.0, total_qty / throughput * _BAPTBI_TIDE_HOURS * _BAPTBI_BOX_SCALE))
        start = max(0.0, eta_time - 18.0)
        end = min(T_max, eta_time + load_hours)
        if end <= start + 1e-9:
            end = min(T_max, start + 6.0)

        ships_config[ship] = {
            "source_ship": original_ship,
            "source_eta_tide": float(raw["eta"].get(original_ship, 0.0)),
            "source_berth": berth_key,
            "source_demurrage": float(raw["demurrage"].get(original_ship, 0.0)),
            "start": start,
            "end": end,
            "total_quantity": total_qty,
        }

        for midx, mat in enumerate(materials):
            size = _baptbi_material_size(midx)
            qty = float(raw["q"].get(original_ship, {}).get(mat, 0.0)) * _BAPTBI_BOX_SCALE
            for n in N:
                iv = Intervals[n]
                Arrivals_interval[(ship, size, n)] += _uniform_volume(qty, start, end, iv["start"], iv["end"])

            block = material_block[mat]
            old_ship = material_to_old_ship[mat]
            out_start = max(0.0, eta_time - 6.0)
            out_end = min(T_max, eta_time + load_hours)
            outbound_requests.append({
                "block": block,
                "ship": old_ship,
                "start": out_start,
                "end": out_end,
                "total": qty * 0.35,
            })

    Fixed_Bay_Mode = _finalize_fixed_modes(I, I_list, initial_inventory_data, fixed_inbound_schedule, default_size=40)
    touched_bays = {
        bay for (bay, _ship, _size), qty in initial_inventory_data.items()
        if float(qty) > 1e-9
    }
    touched_bays.update(fix["bay"] for fix in fixed_inbound_schedule)
    for idx, bay in enumerate(I_list):
        if bay in touched_bays:
            continue
        size = 20 if idx % 2 == 0 else 40
        Fixed_Bay_Mode[bay] = size
        I[bay]["fixed_size_ft"] = size
    Old_Box_Occupancy_Map, Old_Ship_Size_Map = _build_old_box_map(
        I_list, J_old, initial_inventory_data, fixed_inbound_schedule
    )

    (
        _unused_arrivals,
        Block_Outbound_Vol,
        Block_Outbound_Req,
        Fixed_In_Flow,
        Fixed_Mode_Force,
    ) = _empty_time_maps(K, I_list, J_old, S, N)

    for n in N:
        iv = Intervals[n]
        for fix in fixed_inbound_schedule:
            vol = _uniform_volume(fix["flow"], fix["start"], fix["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Fixed_In_Flow[(fix["ship"], fix["size"], fix["bay"], n)] += vol
                Fixed_Mode_Force[(fix["bay"], n)] = fix["size"]
        for req in outbound_requests:
            vol = _uniform_volume(req["total"], req["start"], req["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Block_Outbound_Req[(req["block"], req["ship"], n)] += vol
                Block_Outbound_Vol[(req["block"], n)] += vol

    return {
        "K": K,
        "I": I,
        "I_list": I_list,
        "Bays_in_Block": Bays_in_Block,
        "J_new": J_new,
        "J_old": J_old,
        "J_all": J_all,
        "S": S,
        "Alpha": Alpha,
        "T_max": T_max,
        "Intervals": Intervals,
        "N": N,
        "TimeBucketHours": TIME_BUCKET_HOURS,
        "NumBerths": TOS_NUM_BERTHS,
        "Berths": model_berths,
        "YardStructure": _yard_structure(num_blocks, bays_per_block),
        "Dist": Dist,
        "Old_Ship_Size_Map": Old_Ship_Size_Map,
        "Old_Box_Occupancy_Map": Old_Box_Occupancy_Map,
        "initial_inventory_data": initial_inventory_data,
        "Arrivals_interval": Arrivals_interval,
        "Block_Outbound_Vol": Block_Outbound_Vol,
        "Block_Outbound_Req": Block_Outbound_Req,
        "Fixed_In_Flow": Fixed_In_Flow,
        "Fixed_Mode_Force": Fixed_Mode_Force,
        "Fixed_Bay_Mode": copy.deepcopy(Fixed_Bay_Mode),
        "OldShipType": {"in_only": J_old, "out_only": J_old, "fixed_only": []},
        "ScenarioName": f"{instance_name}_original_file_adapted",
        "ships_config": copy.deepcopy(ships_config),
        "fixed_inbound_schedule": copy.deepcopy(fixed_inbound_schedule),
        "outbound_requests": copy.deepcopy(outbound_requests),
        "benchmark_metadata": {
            "name": instance_name,
            "source": "BAPTBI Mendeley Data original file",
            "source_url": "https://data.mendeley.com/datasets/58ph43s6h4",
            "source_file": path,
            "is_original_file": True,
            "adapted_to_current_model": True,
            "box_scale": _BAPTBI_BOX_SCALE,
            "tide_hours": _BAPTBI_TIDE_HOURS,
            "original_sets": {
                "N": copy.deepcopy(original_ships),
                "K": copy.deepcopy(materials),
                "L": copy.deepcopy(original_berths),
            },
            "original_params": {
                "Mares": raw["mares"],
                "v": copy.deepcopy(raw["throughput"]),
                "d": copy.deepcopy(raw["demurrage"]),
                "a": copy.deepcopy(raw["eta"]),
                "e": copy.deepcopy(raw["initial_inventory"]),
                "ck": copy.deepcopy(raw["inventory_rate"]),
                "spin": copy.deepcopy(raw["spin"]),
                "q": copy.deepcopy(raw["q"]),
            },
            "translation_note": (
                "Original BAPTBI N/K/L/Mares/v/d/a/e/ck/spin/q fields are read "
                "from the .dat file. Ships become J_new, raw materials become "
                "old stock ships and 20/40ft demand classes, ETA/throughput/q "
                "generate Arrivals_interval, and inventory fields generate old "
                "occupancy/fixed inbound/outbound pressure for the current model."
            ),
        },
    }


def get_data_baptbi_10n_4b_4p() -> dict:
    if "baptbi_10n_4b_4p" not in _BAPTBI_ORIGINAL_CACHE:
        _BAPTBI_ORIGINAL_CACHE["baptbi_10n_4b_4p"] = _build_baptbi_original_adapted("baptbi_10n_4b_4p")
    return copy.deepcopy(_BAPTBI_ORIGINAL_CACHE["baptbi_10n_4b_4p"])


def get_data_baptbi_5n_4b_4p() -> dict:
    if "baptbi_5n_4b_4p" not in _BAPTBI_ORIGINAL_CACHE:
        _BAPTBI_ORIGINAL_CACHE["baptbi_5n_4b_4p"] = _build_baptbi_original_adapted("baptbi_5n_4b_4p")
    return copy.deepcopy(_BAPTBI_ORIGINAL_CACHE["baptbi_5n_4b_4p"])


def get_data_baptbi_8n_4b_4p() -> dict:
    if "baptbi_8n_4b_4p" not in _BAPTBI_ORIGINAL_CACHE:
        _BAPTBI_ORIGINAL_CACHE["baptbi_8n_4b_4p"] = _build_baptbi_original_adapted("baptbi_8n_4b_4p")
    return copy.deepcopy(_BAPTBI_ORIGINAL_CACHE["baptbi_8n_4b_4p"])


def get_data_baptbi_15n_4b_5p() -> dict:
    if "baptbi_15n_4b_5p" not in _BAPTBI_ORIGINAL_CACHE:
        _BAPTBI_ORIGINAL_CACHE["baptbi_15n_4b_5p"] = _build_baptbi_original_adapted("baptbi_15n_4b_5p")
    return copy.deepcopy(_BAPTBI_ORIGINAL_CACHE["baptbi_15n_4b_5p"])


def get_data_baptbi_25n_6b_5p() -> dict:
    if "baptbi_25n_6b_5p" not in _BAPTBI_ORIGINAL_CACHE:
        _BAPTBI_ORIGINAL_CACHE["baptbi_25n_6b_5p"] = _build_baptbi_original_adapted("baptbi_25n_6b_5p")
    return copy.deepcopy(_BAPTBI_ORIGINAL_CACHE["baptbi_25n_6b_5p"])


# ---------------------------------------------------------------------------
# Barcelona BAP real-schedule-driven synthetic yard instances
# ---------------------------------------------------------------------------

_BARCELONA_BAP_CACHE = {}
_BARCELONA_SOURCE_PERIOD_HOURS = 0.5
_BARCELONA_BOXES_PER_LENGTH_PERIOD = 2.0


_BARCELONA_BAP_INSTANCE_SPECS = {
    "barcelona_bcn36a_5n": {
        "source_file": "bcn_36A_6.json",
        "max_ships": 5,
        "num_blocks": 6,
        "bays_per_block": 8,
        "old_ship_count": 3,
    },
    "barcelona_bcn36a_8n": {
        "source_file": "bcn_36A_6.json",
        "max_ships": 8,
        "num_blocks": 7,
        "bays_per_block": 8,
        "old_ship_count": 4,
    },
    "barcelona_bcn36a_10n": {
        "source_file": "bcn_36A_6.json",
        "max_ships": 10,
        "num_blocks": 8,
        "bays_per_block": 8,
        "old_ship_count": 4,
    },
    "barcelona_bcn36a_20n": {
        "source_file": "bcn_36A_6.json",
        "max_ships": 20,
        "num_blocks": 10,
        "bays_per_block": 8,
        "old_ship_count": 5,
    },
}


def _barcelona_bap_root() -> str:
    return os.path.join(
        os.path.dirname(__file__),
        "datasets",
        "barcelona_bap",
        "instances",
        "hyb_dyn_fix_max-comp",
    )


def _barcelona_bks_root() -> str:
    return os.path.join(
        os.path.dirname(__file__),
        "datasets",
        "barcelona_bap",
        "bks",
        "hyb_dyn_fix_max-comp",
    )


def _barcelona_bap_path(source_file: str) -> str:
    path = os.path.join(_barcelona_bap_root(), source_file)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Barcelona BAP source file not found: {path}. "
            "Download Santini's berth-allocation-problems repository files "
            "under Benders-changed/datasets/barcelona_bap/instances/hyb_dyn_fix_max-comp."
        )
    return path


def _barcelona_bks_path(source_file: str) -> str:
    return os.path.join(_barcelona_bks_root(), f"bks-{source_file}")


def _read_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return json.load(fh)


def _build_barcelona_bap_adapted(instance_name: str) -> dict:
    spec = _BARCELONA_BAP_INSTANCE_SPECS[instance_name]
    source_file = spec["source_file"]
    source_path = _barcelona_bap_path(source_file)
    raw = _read_json_file(source_path)

    bks_path = _barcelona_bks_path(source_file)
    bks = _read_json_file(bks_path) if os.path.exists(bks_path) else {}
    bks_by_ship = {
        int(ship["data_ship_id"]): ship
        for ship in bks.get("ships", [])
        if "data_ship_id" in ship
    }

    n_source_ships = int(raw["n_ships"])
    ship_rows = []
    for source_id in range(n_source_ships):
        ship_rows.append({
            "source_id": source_id,
            "arrival_period": int(raw["arrival_time"][source_id]),
            "handling_periods": int(raw["handling_time"][source_id]),
            "ship_len": float(raw["ship_len"][source_id]),
        })
    ship_rows.sort(key=lambda row: (row["arrival_period"], row["source_id"]))
    selected = ship_rows[:int(spec["max_ships"])]

    K, I, I_list, Bays_in_Block = _build_yard(
        num_blocks=int(spec["num_blocks"]),
        bays_per_block=int(spec["bays_per_block"]),
    )
    S = [20, 40]
    Alpha = 1.0
    source_period_hours = float(_BARCELONA_SOURCE_PERIOD_HOURS)
    T_max = max(
        float(raw.get("n_periods", 0)) * source_period_hours,
        max((row["arrival_period"] + row["handling_periods"] for row in selected), default=0)
        * source_period_hours
        + 48.0,
    )
    Intervals, N = _build_intervals(T_max)

    J_new = [f"BCN_{source_file[:-5]}_S{row['source_id']:03d}" for row in selected]
    J_old = [f"BCN_{source_file[:-5]}_OLD_{idx:02d}" for idx in range(1, int(spec["old_ship_count"]) + 1)]
    J_all = J_old + J_new

    source_berths = [f"SourceBerth_{idx:02d}" for idx in range(int(raw["n_berths"]))]
    block_positions = {
        k: round(idx * max(1, int(raw["n_berths"]) - 1) / max(1, len(K) - 1))
        for idx, k in enumerate(K)
    }

    Dist = {}
    ships_config = {}
    Arrivals_interval = {(j, s, n): 0.0 for j in J_new for s in S for n in N}

    for local_idx, row in enumerate(selected):
        ship = J_new[local_idx]
        source_id = int(row["source_id"])
        bks_ship = bks_by_ship.get(source_id, {})
        mooring_period = int(bks_ship.get("mooring_time", row["arrival_period"]))
        completion_period = int(
            bks_ship.get("completion_time", row["arrival_period"] + row["handling_periods"])
        )
        mooring_berth = int(bks_ship.get("mooring_berth", source_id % max(1, int(raw["n_berths"]))))

        arrival_h = float(row["arrival_period"]) * source_period_hours
        mooring_h = float(mooring_period) * source_period_hours
        completion_h = float(completion_period) * source_period_hours
        handling_h = max(source_period_hours, float(row["handling_periods"]) * source_period_hours)
        gate_start = max(0.0, mooring_h - 24.0)
        gate_end = min(T_max, max(completion_h, mooring_h + handling_h))
        if gate_end <= gate_start + 1e-9:
            gate_end = min(T_max, gate_start + max(6.0, handling_h))

        total_boxes = (
            float(row["ship_len"])
            * float(row["handling_periods"])
            * float(_BARCELONA_BOXES_PER_LENGTH_PERIOD)
        )
        share_20 = min(0.40, max(0.20, 0.30 + 0.025 * ((source_id % 5) - 2)))
        total_20 = total_boxes * share_20
        total_40 = total_boxes - total_20

        ships_config[ship] = {
            "source_file": source_file,
            "source_ship_id": source_id,
            "source_arrival_period": int(row["arrival_period"]),
            "source_handling_periods": int(row["handling_periods"]),
            "source_ship_len": float(row["ship_len"]),
            "source_mooring_time": mooring_period,
            "source_completion_time": completion_period,
            "source_mooring_berth": mooring_berth,
            "arrival_h": arrival_h,
            "gate_start": gate_start,
            "gate_end": gate_end,
            "total_20": total_20,
            "total_40": total_40,
        }

        for k in K:
            Dist[(ship, k)] = (
                150.0
                + 35.0 * abs(float(block_positions[k]) - float(mooring_berth))
                + 8.0 * float(row["ship_len"])
            )

        for n in N:
            iv = Intervals[n]
            Arrivals_interval[(ship, 20, n)] += _uniform_volume(
                total_20, gate_start, gate_end, iv["start"], iv["end"]
            )
            Arrivals_interval[(ship, 40, n)] += _uniform_volume(
                total_40, gate_start, gate_end, iv["start"], iv["end"]
            )

    initial_inventory_data = {}
    fixed_inbound_schedule = []
    touched_bays = set()

    for block_idx, k in enumerate(K):
        old_ship = J_old[block_idx % len(J_old)]
        old_size = 20 if block_idx % 3 == 0 else 40
        bays = Bays_in_Block[k]
        init_bay = bays[0]
        reserve_bay = bays[min(1, len(bays) - 1)]
        init_qty = min(float(TOS_BAY_CAPACITY_BOXES) * 0.42, 18.0 + 2.0 * (block_idx % 4))
        fixed_qty = min(float(TOS_BAY_CAPACITY_BOXES) * 0.24, 8.0 + 1.5 * (block_idx % 3))
        initial_inventory_data[(init_bay, old_ship, old_size)] = init_qty
        touched_bays.add(init_bay)
        fixed_inbound_schedule.append({
            "ship": old_ship,
            "size": old_size,
            "bay": reserve_bay,
            "start": 0.0,
            "end": min(T_max, 72.0 + 6.0 * (block_idx % 4)),
            "flow": fixed_qty,
        })
        touched_bays.add(reserve_bay)

    outbound_requests = []
    for local_idx, ship in enumerate(J_new):
        cfg = ships_config[ship]
        mooring_berth = int(cfg["source_mooring_berth"])
        block = min(K, key=lambda k: abs(float(block_positions[k]) - float(mooring_berth)))
        old_ship = J_old[local_idx % len(J_old)]
        total_boxes = float(cfg["total_20"]) + float(cfg["total_40"])
        outbound_requests.append({
            "block": block,
            "ship": old_ship,
            "start": max(0.0, float(cfg["arrival_h"]) - 6.0),
            "end": min(T_max, float(cfg["gate_end"]) + 12.0),
            "total": max(2.0, 0.10 * total_boxes),
        })

    Fixed_Bay_Mode = _finalize_fixed_modes(
        I, I_list, initial_inventory_data, fixed_inbound_schedule, default_size=40
    )
    for idx, bay in enumerate(I_list):
        if bay in touched_bays:
            continue
        size = 20 if idx % 3 == 0 else 40
        Fixed_Bay_Mode[bay] = size
        I[bay]["fixed_size_ft"] = size

    Old_Box_Occupancy_Map, Old_Ship_Size_Map = _build_old_box_map(
        I_list, J_old, initial_inventory_data, fixed_inbound_schedule
    )

    (
        _unused_arrivals,
        Block_Outbound_Vol,
        Block_Outbound_Req,
        Fixed_In_Flow,
        Fixed_Mode_Force,
    ) = _empty_time_maps(K, I_list, J_old, S, N)

    for n in N:
        iv = Intervals[n]
        for fix in fixed_inbound_schedule:
            vol = _uniform_volume(fix["flow"], fix["start"], fix["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Fixed_In_Flow[(fix["ship"], fix["size"], fix["bay"], n)] += vol
                Fixed_Mode_Force[(fix["bay"], n)] = fix["size"]
        for req in outbound_requests:
            vol = _uniform_volume(req["total"], req["start"], req["end"], iv["start"], iv["end"])
            if vol > 1e-6:
                Block_Outbound_Req[(req["block"], req["ship"], n)] += vol
                Block_Outbound_Vol[(req["block"], n)] += vol

    return {
        "K": K,
        "I": I,
        "I_list": I_list,
        "Bays_in_Block": Bays_in_Block,
        "J_new": J_new,
        "J_old": J_old,
        "J_all": J_all,
        "S": S,
        "Alpha": Alpha,
        "T_max": T_max,
        "Intervals": Intervals,
        "N": N,
        "TimeBucketHours": TIME_BUCKET_HOURS,
        "NumBerths": int(raw["n_berths"]),
        "Berths": source_berths,
        "YardStructure": _yard_structure(int(spec["num_blocks"]), int(spec["bays_per_block"])),
        "Dist": Dist,
        "Old_Ship_Size_Map": Old_Ship_Size_Map,
        "Old_Box_Occupancy_Map": Old_Box_Occupancy_Map,
        "initial_inventory_data": initial_inventory_data,
        "Arrivals_interval": Arrivals_interval,
        "Block_Outbound_Vol": Block_Outbound_Vol,
        "Block_Outbound_Req": Block_Outbound_Req,
        "Fixed_In_Flow": Fixed_In_Flow,
        "Fixed_Mode_Force": Fixed_Mode_Force,
        "Fixed_Bay_Mode": copy.deepcopy(Fixed_Bay_Mode),
        "OldShipType": {"in_only": J_old, "out_only": J_old, "fixed_only": []},
        "ScenarioName": f"{instance_name}_real_schedule_synthetic_yard",
        "ships_config": copy.deepcopy(ships_config),
        "fixed_inbound_schedule": copy.deepcopy(fixed_inbound_schedule),
        "outbound_requests": copy.deepcopy(outbound_requests),
        "benchmark_metadata": {
            "name": instance_name,
            "source": "Port of Barcelona BAP instances from Santini berth-allocation-problems",
            "source_url": "https://github.com/alberto-santini/berth-allocation-problems",
            "source_file": source_path,
            "bks_file": bks_path if os.path.exists(bks_path) else None,
            "is_original_file": True,
            "adapted_to_current_model": True,
            "source_period_hours": source_period_hours,
            "boxes_per_length_period": _BARCELONA_BOXES_PER_LENGTH_PERIOD,
            "original_fields_used": [
                "n_ships",
                "n_berths",
                "n_periods",
                "arrival_time",
                "handling_time",
                "ship_len",
                "bks.mooring_time",
                "bks.completion_time",
                "bks.mooring_berth",
            ],
            "translation_note": (
                "Barcelona BAP provides real container-ship schedule structure "
                "(arrival_time, handling_time, ship_len, berth count). Yard blocks, "
                "bay capacities, export gate-in volumes, legacy inventory, fixed "
                "old inbound, and old outbound pressure are generated by transparent "
                "rules so the data satisfies the current yard pre-allocation model."
            ),
        },
}


def get_data_barcelona_bcn36a_5n() -> dict:
    if "barcelona_bcn36a_5n" not in _BARCELONA_BAP_CACHE:
        _BARCELONA_BAP_CACHE["barcelona_bcn36a_5n"] = _build_barcelona_bap_adapted("barcelona_bcn36a_5n")
    return copy.deepcopy(_BARCELONA_BAP_CACHE["barcelona_bcn36a_5n"])


def get_data_barcelona_bcn36a_8n() -> dict:
    if "barcelona_bcn36a_8n" not in _BARCELONA_BAP_CACHE:
        _BARCELONA_BAP_CACHE["barcelona_bcn36a_8n"] = _build_barcelona_bap_adapted("barcelona_bcn36a_8n")
    return copy.deepcopy(_BARCELONA_BAP_CACHE["barcelona_bcn36a_8n"])


def get_data_barcelona_bcn36a_10n() -> dict:
    if "barcelona_bcn36a_10n" not in _BARCELONA_BAP_CACHE:
        _BARCELONA_BAP_CACHE["barcelona_bcn36a_10n"] = _build_barcelona_bap_adapted("barcelona_bcn36a_10n")
    return copy.deepcopy(_BARCELONA_BAP_CACHE["barcelona_bcn36a_10n"])


def get_data_barcelona_bcn36a_20n() -> dict:
    if "barcelona_bcn36a_20n" not in _BARCELONA_BAP_CACHE:
        _BARCELONA_BAP_CACHE["barcelona_bcn36a_20n"] = _build_barcelona_bap_adapted("barcelona_bcn36a_20n")
    return copy.deepcopy(_BARCELONA_BAP_CACHE["barcelona_bcn36a_20n"])
