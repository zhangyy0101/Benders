"""Deterministic, parameterized synthetic yard-instance generation."""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from data import simulate_old_inventory, validate_instance_units
from model_concentration import has_joint_attribute_groups

GENERATOR_VERSION = "synthetic-yard-v2"


@dataclass(frozen=True)
class SyntheticInstanceSpec:
    name: str
    num_blocks: int
    bays_per_block: int
    bay_capacity_boxes: float
    num_berths: int
    num_new_ships: int
    num_old_ships: int
    num_periods: int
    time_bucket_hours: float
    alpha: float
    handling_rate_boxes_per_hour: float
    initial_utilization_range: tuple[float, float]
    fixed_inbound_ratio_range: tuple[float, float]
    outbound_pressure_ratio_range: tuple[float, float]
    arrival_boxes_per_ship_range: tuple[float, float]
    arrival_overlap_level: float
    peak_position_range: tuple[float, float]
    mode_20ft_share: float
    group_profile: str = "standard"
    pod_count_range: tuple[int, int] = (2, 2)
    positive_group_count_range: tuple[int, int] = (4, 6)
    single_combination_pod_ratio_range: tuple[float, float] = (.2, .5)
    arrival_overlap_ratio_range: tuple[float, float] = (0, 1)
    pressure_positive_ratio_range: tuple[float, float] = (0, 1)
    minimum_active_group_boxes: int = 2

    def validate(self):
        positive_ints = {
            "num_blocks": self.num_blocks, "bays_per_block": self.bays_per_block,
            "num_berths": self.num_berths, "num_new_ships": self.num_new_ships,
            "num_periods": self.num_periods,
        }
        for name, value in positive_ints.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer; got {value!r}")
        if not isinstance(self.num_old_ships, int) or self.num_old_ships < 0:
            raise ValueError("num_old_ships must be a nonnegative integer")
        for name, value in {
            "bay_capacity_boxes": self.bay_capacity_boxes,
            "time_bucket_hours": self.time_bucket_hours,
            "alpha": self.alpha,
            "handling_rate_boxes_per_hour": self.handling_rate_boxes_per_hour,
        }.items():
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive; got {value!r}")
        for name, bounds in {
            "initial_utilization_range": self.initial_utilization_range,
            "fixed_inbound_ratio_range": self.fixed_inbound_ratio_range,
            "outbound_pressure_ratio_range": self.outbound_pressure_ratio_range,
        }.items():
            _validate_range(name, bounds, 0.0, 1.0)
        _validate_range("arrival_boxes_per_ship_range", self.arrival_boxes_per_ship_range, 0.0, math.inf)
        _validate_range("peak_position_range", self.peak_position_range, 0.0, 1.0)
        if not 0 <= self.arrival_overlap_level <= 1:
            raise ValueError("arrival_overlap_level must be in [0, 1]")
        if not 0 <= self.mode_20ft_share <= 1:
            raise ValueError("mode_20ft_share must be in [0, 1]")
        if self.group_profile not in {"standard", "standard6", "pilot2_small", "pilot2_medium", "pilot2_large"}:
            raise ValueError(f"unsupported group_profile {self.group_profile!r}")


def _validate_range(name, bounds, lower, upper):
    if not isinstance(bounds, tuple) or len(bounds) != 2:
        raise ValueError(f"{name} must be a two-value tuple")
    lo, hi = map(float, bounds)
    if not all(math.isfinite(value) for value in (lo, hi)) or lo < lower or hi > upper or lo > hi:
        raise ValueError(f"invalid {name}: {bounds!r}; expected {lower} <= low <= high <= {upper}")


def _groups(profile):
    attrs = {
        "Group_20_POD_A_STD_LIGHT": {"size": 20, "pod": "POD_A", "height": "STD", "weight_class": "LIGHT"},
        "Group_20_POD_B_HIGH_HEAVY": {"size": 20, "pod": "POD_B", "height": "HIGH", "weight_class": "HEAVY"},
        "Group_40_POD_A_STD_LIGHT": {"size": 40, "pod": "POD_A", "height": "STD", "weight_class": "LIGHT"},
        "Group_40_POD_B_HIGH_HEAVY": {"size": 40, "pod": "POD_B", "height": "HIGH", "weight_class": "HEAVY"},
    }
    if profile == "standard6":
        attrs.update({
            "Group_20_POD_C_STD_MEDIUM": {"size": 20, "pod": "POD_C", "height": "STD", "weight_class": "MEDIUM"},
            "Group_40_POD_C_HIGH_MEDIUM": {"size": 40, "pod": "POD_C", "height": "HIGH", "weight_class": "MEDIUM"},
        })
    return list(attrs), attrs


def _period_profile(rng, spec, ship_index):
    if spec.group_profile.startswith("pilot2_"):
        patterns={
            "pilot2_small":[(0,5),(3,5)],
            "pilot2_medium":[(0,7),(2,7),(4,7)],
            "pilot2_large":[(0,10),(0,11),(1,10),(1,11),(2,10)],
        }
        start,duration=patterns[spec.group_profile][ship_index]
        peak=start+duration//2;weights=[0.0]*spec.num_periods
        for n in range(start,min(spec.num_periods,start+duration)):weights[n]=float(1+min(n-start,start+duration-1-n))
        total=sum(weights)
        return [v/total for v in weights],{"start_period":start,"end_period":start+duration,"active_duration":duration,"peak_period":peak,"realized_active_periods":[n for n,v in enumerate(weights) if v>0]}
    horizon = float(spec.num_periods)
    window = max(1.0, horizon * (.40 + .55 * spec.arrival_overlap_level))
    available_start = max(0.0, horizon - window)
    spread = available_start * (1.0 - spec.arrival_overlap_level)
    start = 0.0 if spec.num_new_ships == 1 else spread * ship_index / (spec.num_new_ships - 1)
    peak = start + window * rng.uniform(*spec.peak_position_range)
    weights = []
    for n in range(spec.num_periods):
        midpoint = n + .5
        if midpoint < start or midpoint > start + window:
            weights.append(0.0)
        elif midpoint <= peak:
            weights.append(max(1e-9, (midpoint - start) / max(peak - start, 1e-9)))
        else:
            weights.append(max(1e-9, (start + window - midpoint) / max(start + window - peak, 1e-9)))
    if not any(weights):
        weights[min(spec.num_periods - 1, int(start))] = 1.0
    total = sum(weights)
    return [value / total for value in weights], {"start_period": start, "end_period": min(horizon, start + window), "peak_period": peak}

def _split_integer(total,count,rng,minimum=1):
    total=int(round(total));minimum=int(minimum)
    if total<count*minimum:raise ValueError(f"cannot split {total} boxes over {count} groups with minimum {minimum}")
    result=[minimum]*count
    for _ in range(total-count*minimum):result[rng.randrange(count)]+=1
    return result

def _pilot2_ship_groups(rng,spec,ship):
    pod_count=rng.randint(*spec.pod_count_range);pods=[f"POD_{i:02d}" for i in rng.sample(range(1,9),pod_count)]
    target=rng.randint(*spec.positive_group_count_range);single_target=max(1,round(pod_count*rng.uniform(*spec.single_combination_pod_ratio_range)))
    attrs={};by_pod={pod:[] for pod in pods}
    for pos,pod in enumerate(pods):
        sizes=[20,40] if (spec.group_profile!="pilot2_small" or rng.random()<.35) else [rng.choice((20,40))]
        if pos==0:sizes=[20,40]
        for size in sizes:
            combos=[("STD","LIGHT"),("STD","HEAVY"),("HIGH","LIGHT"),("HIGH","HEAVY")]
            rng.shuffle(combos);max_combo={"pilot2_small":2,"pilot2_medium":3,"pilot2_large":4}[spec.group_profile]
            count=1 if pos<single_target else rng.randint(1,max_combo)
            for height,weight in combos[:count]:
                g=f"Group_{size}_{pod}_{height}_{weight}";attrs[g]={"size":size,"pod":pod,"height":height,"weight_class":weight};by_pod[pod].append(g)
    candidates=[]
    for pod in pods:
      for size in (20,40):
       for h in ("STD","HIGH"):
        for w in ("LIGHT","HEAVY"):
         g=f"Group_{size}_{pod}_{h}_{w}"
         if g not in attrs:candidates.append((g,{"size":size,"pod":pod,"height":h,"weight_class":w}))
    while len(attrs)<target and candidates:
        idx=rng.randrange(len(candidates));g,a=candidates.pop(idx);attrs[g]=a;by_pod[a["pod"]].append(g)
    while len(attrs)>target:
        removable=[g for g,a in attrs.items() if len(by_pod[a["pod"]])>1]
        if not removable:break
        g=rng.choice(removable);by_pod[attrs[g]["pod"]].remove(g);del attrs[g]
    heights={a["height"] for a in attrs.values()};weights={a["weight_class"] for a in attrs.values()};sizes={a["size"] for a in attrs.values()}
    return attrs,pods,{"pod_count":pod_count,"positive_group_count":len(attrs),"single_combination_pod_count":sum(any(sum(a["size"]==s for a in (attrs[g] for g in by_pod[p]))==1 for s in (20,40)) for p in pods),"height_coverage":sorted(heights),"weight_coverage":sorted(weights),"size_coverage":sorted(sizes)}


def generate_synthetic_instance(spec: SyntheticInstanceSpec, seed: int) -> dict:
    spec.validate()
    if not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    rng = random.Random(seed)
    K = [f"Block_{index:03d}" for index in range(1, spec.num_blocks + 1)]
    I_list = [f"Bay_{block:03d}_{bay:03d}" for block in range(1, spec.num_blocks + 1) for bay in range(1, spec.bays_per_block + 1)]
    Bays_in_Block = {k: [f"Bay_{block:03d}_{bay:03d}" for bay in range(1, spec.bays_per_block + 1)] for block, k in enumerate(K, 1)}
    target_20 = round(len(I_list) * spec.mode_20ft_share)
    if len(I_list) >= 2:
        target_20 = min(len(I_list) - 1, max(1, target_20))
    modes = {}
    remaining_20 = target_20
    for block_index, k in enumerate(K):
        bays = Bays_in_Block[k]
        for bay_index, i in enumerate(bays):
            if len(bays) >= 2 and bay_index < 2:
                size = 20 if bay_index == block_index % 2 else 40
            else:
                slots_left = len(I_list) - len(modes)
                size = 20 if remaining_20 > 0 and (remaining_20 >= slots_left or rng.random() < spec.mode_20ft_share) else 40
            modes[i] = size
            remaining_20 -= int(size == 20)
    # Correct the global share without destroying two-mode blocks when possible.
    for i in reversed(I_list):
        current = sum(value == 20 for value in modes.values())
        if current == target_20:
            break
        block = f"Block_{int(i.split('_')[1]):03d}"
        peers = [modes[b] for b in Bays_in_Block[block] if b != i]
        desired = 20 if current < target_20 else 40
        if desired in peers and len(Bays_in_Block[block]) >= 2:
            continue
        modes[i] = desired
    I = {i: {"block": f"Block_{int(i.split('_')[1]):03d}", "cap": float(spec.bay_capacity_boxes), "fixed_size_ft": modes[i]} for i in I_list}
    J_new = [f"Ship_New_{index:03d}" for index in range(1, spec.num_new_ships + 1)]
    J_old = [f"Ship_Old_{index:03d}" for index in range(1, spec.num_old_ships + 1)]
    S, N = [20, 40], list(range(spec.num_periods))
    Intervals = [{"id": n, "start": n * spec.time_bucket_hours, "end": (n + 1) * spec.time_bucket_hours, "dur": spec.time_bucket_hours} for n in N]
    berths = [f"Berth_{index:03d}" for index in range(1, spec.num_berths + 1)]
    ShipBerth = {j: berths[index % len(berths)] for index, j in enumerate(J_new)}
    Dist = {(j, k): float(100 + 75 * abs(K.index(k) - (index % len(K))) + 7 * index) for index, j in enumerate(J_new) for k in K}
    pilot2=spec.group_profile.startswith("pilot2_")
    G, GroupAttrs = ([],{}) if pilot2 else _groups(spec.group_profile)

    initial = {}
    Fixed_In_Flow = {(j, s, i, n): 0.0 for j in J_old for s in S for i in I_list for n in N}
    Block_Outbound_Req = {(k, j, n): 0.0 for k in K for j in J_old for n in N}
    Block_Outbound_Vol = {(k, n): 0.0 for k in K for n in N}
    if J_old:
        for index, i in enumerate(I_list):
            ship = J_old[index % len(J_old)]
            qty = spec.bay_capacity_boxes * rng.uniform(*spec.initial_utilization_range)
            initial[i, ship, modes[i]] = qty
            free = spec.bay_capacity_boxes - qty
            inbound_total = free * rng.uniform(*spec.fixed_inbound_ratio_range)
            weights = [1.0 + .15 * ((n + index) % 3) for n in N]
            for n, weight in enumerate(weights):
                Fixed_In_Flow[ship, modes[i], i, n] = inbound_total * weight / sum(weights)
        for block_index, k in enumerate(K):
            for ship_index, ship in enumerate(J_old):
                available = sum(initial.get((i, ship, modes[i]), 0.0) for i in Bays_in_Block[k])
                if available <= 0:
                    continue
                if pilot2:
                    active_blocks={"pilot2_small":3,"pilot2_medium":5,"pilot2_large":9}[spec.group_profile]
                    if block_index>=active_blocks or ship_index!=block_index%len(J_old):continue
                ratio = rng.uniform(*spec.outbound_pressure_ratio_range)
                if block_index == 0 and ship_index == 0 and spec.outbound_pressure_ratio_range[1] > 0:
                    ratio = max(ratio, sum(spec.outbound_pressure_ratio_range) / 2)
                total = available * ratio
                if pilot2:
                    length={"pilot2_small":4,"pilot2_medium":8,"pilot2_large":9}[spec.group_profile];start=(2*block_index+ship_index)%max(1,len(N)-length+1)
                    weights=[0.0 if n<start or n>=start+length else 1.0+3.0*(n==start+length//2) for n in N]
                else:weights = [1.0 + ((n + 2 * block_index + ship_index) % 4) for n in N]
                for n, weight in enumerate(weights):
                    value = total * weight / sum(weights)
                    Block_Outbound_Req[k, ship, n] = value
                    Block_Outbound_Vol[k, n] += value

    Arrivals_interval = {}
    Arrivals_group_interval = {}
    ships_config = {}
    active_by_ship={};pods_by_ship={};ship_group_meta={}
    for ship_index, j in enumerate(J_new):
        total = round(rng.uniform(*spec.arrival_boxes_per_ship_range)) if pilot2 else rng.uniform(*spec.arrival_boxes_per_ship_range)
        share20 = min(.95, max(.05, spec.mode_20ft_share + rng.uniform(-.08, .08)))
        profile, window = _period_profile(rng, spec, ship_index)
        ships_config[j] = {"total_boxes": total, "share_20ft": share20, **window}
        if pilot2:
            attrs,pods,meta=_pilot2_ship_groups(rng,spec,j);GroupAttrs.update(attrs);active_by_ship[j]=sorted(attrs);pods_by_ship[j]=pods;ship_group_meta[j]=meta
            volumes=_split_integer(total,len(attrs),rng,spec.minimum_active_group_boxes)
            group_volume=dict(zip(sorted(attrs),volumes))
            for n,period_share in enumerate(profile):
                by_size={s:0.0 for s in S}
                for g in active_by_ship[j]:
                    value=group_volume[g]*period_share;Arrivals_group_interval[j,g,n]=value;by_size[attrs[g]["size"]]+=value
                for size in S:Arrivals_interval[j,size,n]=by_size[size]
            continue
        for size, size_share in ((20, share20), (40, 1 - share20)):
            size_groups = [g for g in G if GroupAttrs[g]["size"] == size]
            raw_group_shares = [rng.uniform(.5, 1.5) for _ in size_groups]
            group_shares = [value / sum(raw_group_shares) for value in raw_group_shares]
            for n, period_share in enumerate(profile):
                value = total * size_share * period_share
                Arrivals_interval[j, size, n] = value
                assigned = 0.0
                for position, group in enumerate(size_groups):
                    group_value = value - assigned if position == len(size_groups) - 1 else value * group_shares[position]
                    Arrivals_group_interval[j, group, n] = group_value
                    assigned += group_value

    if pilot2:G=sorted(GroupAttrs)

    Fixed_Mode_Force = {(i, n): None for i in I_list for n in N}
    Old_Box_Occupancy_Map = {(i, j): sum(initial.get((i, j, s), 0.0) for s in S) + sum(Fixed_In_Flow.get((j, s, i, n), 0.0) for s in S for n in N) for i in I_list for j in J_old}
    Old_Ship_Size_Map = {(i, j): modes[i] for i in I_list for j in J_old if Old_Box_Occupancy_Map[i, j] > 0}
    data = {
        "K": K, "I": I, "I_list": I_list, "Bays_in_Block": Bays_in_Block,
        "J_new": J_new, "J_old": J_old, "J_all": J_old + J_new, "S": S,
        "G": G, "GroupAttrs": GroupAttrs,
        "GroupSize": {g: value["size"] for g, value in GroupAttrs.items()},
        "GroupPOD": {g: value["pod"] for g, value in GroupAttrs.items()},
        "GroupHeight": {g: value["height"] for g, value in GroupAttrs.items()},
        "GroupWeightClass": {g: value["weight_class"] for g, value in GroupAttrs.items()},
        "Alpha": float(spec.alpha), "Intervals": Intervals, "N": N,
        "TimeBucketHours": float(spec.time_bucket_hours), "NumBerths": spec.num_berths,
        "Berths": berths, "ShipBerth": ShipBerth, "Dist": Dist,
        "initial_inventory_data": initial, "Arrivals_interval": Arrivals_interval,
        "Arrivals_group_interval": Arrivals_group_interval,
        "Block_Outbound_Vol": Block_Outbound_Vol, "Block_Outbound_Req": Block_Outbound_Req,
        "Fixed_In_Flow": Fixed_In_Flow, "Fixed_Mode_Force": Fixed_Mode_Force,
        "Fixed_Bay_Mode": dict(modes), "Old_Box_Occupancy_Map": Old_Box_Occupancy_Map,
        "Old_Ship_Size_Map": Old_Ship_Size_Map,
        "OldShipType": {"in_only": [], "out_only": [], "fixed_only": list(J_old)},
        "ScenarioName": spec.name, "ships_config": ships_config,
        "Bay_Handling_Rate": {(i, n): float(spec.handling_rate_boxes_per_hour) for i in I_list for n in N},
        "New_Outbound_Req": {},
        "benchmark_metadata": {"source_type": "synthetic", "generator_version": GENERATOR_VERSION, "spec_name": spec.name, "seed": seed, "spec": asdict(spec)},
    }
    if pilot2:data.update({"ActiveGroupsByShip":active_by_ship,"ActivePODsByShip":pods_by_ship,"ShipGroupGenerationMetadata":ship_group_meta})
    _precheck(data)
    return data


def _precheck(data):
    simulation = simulate_old_inventory(data)
    if simulation["max_capacity_violation"] > 1e-6 or max(simulation["unserved_outbound"].values(), default=0) > 1e-6:
        raise ValueError(f"old-operation feasibility failed: {simulation}")
    for size in data["S"]:
        bays = [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == size]
        for n in data["N"]:
            demand = data["Alpha"] * sum(data["Arrivals_interval"][j, size, t] for j in data["J_new"] for t in data["N"] if t <= n)
            capacity = sum(data["I"][i]["cap"] - simulation["occupancy"][i, n] for i in bays)
            if demand > capacity + 1e-6:
                raise ValueError(f"compatible reserve capacity insufficient for size={size}, period={n}: demand={demand:.6f}, capacity={capacity:.6f}")
        for j in data["J_new"]:
            for n in data["N"]:
                demand = data["Alpha"] * data["Arrivals_interval"][j, size, n]
                capacity = sum(data["Bay_Handling_Rate"][i, n] * data["Intervals"][n]["dur"] for i in bays)
                if demand > capacity + 1e-6:
                    raise ValueError(f"handling capacity insufficient for ship={j}, size={size}, period={n}: demand={demand:.6f}, capacity={capacity:.6f}")
    validate_instance_units(data)
    if not has_joint_attribute_groups(data):
        raise ValueError("joint-group attributes or grouped arrivals are incomplete")
