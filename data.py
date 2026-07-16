from __future__ import annotations

import copy
import math
import random


TIME_BUCKET_HOURS = 6.0
_FIXED_3N6O_CACHE = None

# Capacity is modeled directly in boxes.
TOS_NUM_YARD_BLOCKS = 10
TOS_YARD_BAYS = 10
TOS_BAY_CAPACITY_BOXES = 50.0
TOS_NUM_BERTHS = 3

def list_builtin_instances():return ("tiny","tiny_concentration","3new6old")
def build_builtin_instance(name):
    factories={"tiny":get_data_tiny_benders,"tiny_concentration":get_data_tiny_concentration,"3new6old":get_data_3new6old_fixed}
    if name not in factories:raise KeyError(f"unknown built-in instance {name!r}")
    return factories[name]()
def resolve_instance(*,builtin_name=None,instance_file=None):
    if (builtin_name is None)==(instance_file is None):raise ValueError("provide exactly one instance source")
    if instance_file is not None:
        from benchmark_io import load_instance
        return load_instance(instance_file)
    return build_builtin_instance(builtin_name)

def prepare_instance(data: dict, old_outbound_release_policy: str = "ship_complete") -> dict:
    result=copy.deepcopy(data);_migrate_pod_size_height_groups(result);_ensure_old_bay_heights(result)
    if old_outbound_release_policy not in {"legacy_sorted","proportional","conservative","ship_complete"}:raise ValueError("invalid old outbound release policy")
    result["old_outbound_release_policy"]=old_outbound_release_policy;validate_instance_units(result);return result

def _migrate_pod_size_height_groups(data):
    """Remove weight class from the planning taxonomy while accepting legacy files."""
    if not data.get("G") or not data.get("GroupAttrs") or any("pod" not in data["GroupAttrs"].get(g,{}) or "height" not in data["GroupAttrs"].get(g,{}) for g in data["G"]):return
    mapping={};attrs={}
    for g in data["G"]:
        a=data["GroupAttrs"][g];size=int(a["size"]);pod=str(a.get("pod","ALL"));height=str(a.get("height","STD"));key=f"Group_{size}_{pod}_{height}";mapping[g]=key;attrs[key]={"size":size,"pod":pod,"height":height}
    arrivals={}
    active={j:set() for j in data["J_new"]}
    legacy_active=data.get("ActiveGroupsByShip")
    for j in data["J_new"]:
        source=data["G"] if legacy_active is None else legacy_active.get(j,())
        for old in source:
            new=mapping[old];active[j].add(new)
            for n in data["N"]:arrivals[j,new,n]=arrivals.get((j,new,n),0.0)+float(data.get("Arrivals_group_interval",{}).get((j,old,n),0.0))
    data["G"]=sorted(attrs);data["GroupAttrs"]=attrs;data["GroupSize"]={g:a["size"] for g,a in attrs.items()};data["GroupPOD"]={g:a["pod"] for g,a in attrs.items()};data["GroupHeight"]={g:a["height"] for g,a in attrs.items()};data.pop("GroupWeightClass",None);data["Arrivals_group_interval"]=arrivals;data["ActiveGroupsByShip"]={j:sorted(v) for j,v in active.items()};data["LegacyGroupMap"]=mapping;data["group_taxonomy"]="pod_size_height"

def _ensure_old_bay_heights(data):
    heights=dict(data.get("OldBayHeight",{}));allowed=("STD","HIGH")
    for pos,i in enumerate(data["I_list"]):
        occupied=any(bay==i and float(v)>1e-9 for (bay,_j,_s),v in data.get("initial_inventory_data",{}).items()) or any(bay==i and float(v)>1e-9 for (_j,_s,bay,_n),v in data.get("Fixed_In_Flow",{}).items())
        if occupied and i not in heights:heights[i]=allowed[pos%len(allowed)]
    data["OldBayHeight"]=heights;data["HeightTypes"]=sorted(set(allowed)|set(heights.values()))
def simulate_old_inventory(data,policy=None):
    policy=policy or data.get("old_outbound_release_policy","ship_complete");I,J,S,N=data["I_list"],data["J_old"],data["S"],data["N"];logical={(i,j,s):float(data["initial_inventory_data"].get((i,j,s),0)) for i in I for j in J for s in S};capacity=dict(logical);occ={};unserved={};max_violation=0
    for n in N:
      for i in I:
       for j in J:
        for s in S:q=float(data["Fixed_In_Flow"].get((j,s,i,n),0));logical[i,j,s]+=q;capacity[i,j,s]+=q
      for k,bays in data["Bays_in_Block"].items():
       for j in J:
        req=float(data["Block_Outbound_Req"].get((k,j,n),0));available=sum(logical[i,j,s] for i in bays for s in S);unserved[k,j,n]=max(0,req-available);take_total=min(req,available)
        if policy in {"proportional","ship_complete"} and available>1e-9:
         snapshot={(i,s):logical[i,j,s] for i in bays for s in S}
         for (i,s),q in snapshot.items():take=take_total*q/available;logical[i,j,s]-=take;capacity[i,j,s]-=take if policy=="proportional" else 0
        else:
         left=take_total
         for i in sorted(bays):
          for s in S:take=min(left,logical[i,j,s]);logical[i,j,s]-=take;capacity[i,j,s]-=take if policy=="legacy_sorted" else 0;left-=take
      if policy=="ship_complete":
       for j in J:
        if sum(logical[i,j,s] for i in I for s in S)<=1e-9:
         for i in I:
          for s in S:capacity[i,j,s]=0.0
      for i in I:occ[i,n]=sum(capacity[i,j,s] for j in J for s in S);max_violation=max(max_violation,occ[i,n]-float(data["I"][i]["cap"]))
    return {"occupancy":occ,"unserved_outbound":unserved,"max_capacity_violation":max(0,max_violation)}

def validate_instance_units(data: dict) -> None:
    required=("K","I","I_list","Bays_in_Block","J_new","J_old","S","N","Intervals","Dist","Arrivals_interval","initial_inventory_data","Fixed_In_Flow","Block_Outbound_Vol","Block_Outbound_Req","Fixed_Bay_Mode","Fixed_Mode_Force")
    missing=[k for k in required if k not in data]
    if missing:raise ValueError(f"missing model keys: {missing}")
    def finite(v,label):
        x=float(v)
        if not math.isfinite(x):raise ValueError(f"non-finite {label}")
        return x
    if sorted(data["N"])!=list(range(len(data["N"]))):raise ValueError("period ids must be contiguous")
    for n in data["N"]:
        if int(data["Intervals"][n]["id"])!=n or finite(data["Intervals"][n]["dur"],"duration")<=0:raise ValueError("invalid interval")
    modes={int(s) for s in data["S"]}
    for i in data["I_list"]:
        cap=finite(data["I"][i]["cap"],"capacity")
        if cap<0 or int(data["Fixed_Bay_Mode"][i]) not in modes:raise ValueError(f"invalid bay {i}")
        initial=sum(float(v) for (bay,_j,_s),v in data["initial_inventory_data"].items() if bay==i)
        if initial>cap+1e-6:raise ValueError(f"initial occupancy exceeds {i}")
    for j in data["J_new"]:
        for k in data["K"]:finite(data["Dist"][j,k],"distance")
        for s in data["S"]:
            for n in data["N"]:
                if finite(data["Arrivals_interval"][j,s,n],"arrival")<0:raise ValueError("negative arrival")
    if data.get("G"):
      for j in data["J_new"]:
       for s in data["S"]:
        active=data.get("ActiveGroupsByShip",{}).get(j,data["G"]);gs=[g for g in active if int(data["GroupSize"][g])==int(s)]
        for n in data["N"]:
         if any((j,g,n) not in data["Arrivals_group_interval"] for g in gs):raise ValueError("missing grouped arrival")
         if abs(sum(float(data["Arrivals_group_interval"][j,g,n]) for g in gs)-float(data["Arrivals_interval"][j,s,n]))>1e-6:raise ValueError("grouped arrival mismatch")
    simulation=simulate_old_inventory(data)
    if simulation["max_capacity_violation"]>1e-6:raise ValueError("old occupancy exceeds capacity")
    if max(simulation["unserved_outbound"].values(),default=0)>1e-6:raise ValueError("old outbound residual")


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

def get_data_tiny_benders() -> dict:
    """Two-block fixture with positive recourse and deliberately infeasible master points."""
    K=["A","B"];I_list=["A20","A40","B20","B40"];I={i:{"block":i[0],"cap":10.0,"fixed_size_ft":20 if i.endswith("20") else 40} for i in I_list};B={k:[i for i in I_list if i[0]==k] for k in K};J=["J1"];S=[20,40];G=["G20","G40"];N=[0,1];attrs={"G20":{"size":20,"pod":"P1","height":"STD","weight_class":"LIGHT"},"G40":{"size":40,"pod":"P2","height":"HIGH","weight_class":"HEAVY"}}
    return {"K":K,"I":I,"I_list":I_list,"Bays_in_Block":B,"J_new":J,"J_old":[],"J_all":J,"S":S,"G":G,"GroupAttrs":attrs,"GroupSize":{g:attrs[g]["size"] for g in G},"GroupPOD":{g:attrs[g]["pod"] for g in G},"GroupHeight":{g:attrs[g]["height"] for g in G},"GroupWeightClass":{g:attrs[g]["weight_class"] for g in G},"Alpha":1.0,"N":N,"Intervals":[{"id":0,"start":0,"end":1,"dur":1.0},{"id":1,"start":1,"end":2,"dur":1.0}],"Dist":{("J1","A"):100.0,("J1","B"):200.0},"Fixed_Bay_Mode":{i:I[i]["fixed_size_ft"] for i in I_list},"Fixed_Mode_Force":{(i,n):None for i in I_list for n in N},"initial_inventory_data":{},"Old_Box_Occupancy_Map":{},"Old_Ship_Size_Map":{},"Arrivals_interval":{("J1",s,n):2.0 for s in S for n in N},"Arrivals_group_interval":{("J1",g,n):2.0 for g in G for n in N},"Fixed_In_Flow":{},"Block_Outbound_Vol":{(k,n):0.0 for k in K for n in N},"Block_Outbound_Req":{},"ScenarioName":"tiny_true_benders","New_Outbound_Req":{}}

def get_data_tiny_concentration() -> dict:
    d=get_data_tiny_benders();d["ScenarioName"]="tiny_joint_concentration";d["K"].append("C");d["Bays_in_Block"]["C"]=[]
    for size in d["S"]:
        i=f"C{size}";d["I"][i]={"block":"C","cap":10.0,"fixed_size_ft":size};d["I_list"].append(i);d["Bays_in_Block"]["C"].append(i);d["Fixed_Bay_Mode"][i]=size
        for n in d["N"]:d["Fixed_Mode_Force"][i,n]=None
    d["Dist"]["J1","C"]=300.0
    for n in d["N"]:d["Block_Outbound_Vol"]["C",n]=0.0
    return d
