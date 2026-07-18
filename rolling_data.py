"""Synthetic ship-specific 6-hour flows for rolling-horizon experiments.

Hidden realized flows are used only when the simulator advances.  Every model
snapshot contains only realized inventory, the current external forecast, and
the unexecuted reservation inherited from the previous run.
"""
from __future__ import annotations
import math,random
from config import DEFAULT_OUTBOUND_BOXES_PER_6H,LOOKAHEAD_HOURS,ROLLING_CYCLE_HOURS,RECEIVING_WINDOW_HOURS,TIME_BUCKET_HOURS

PERIOD_HOURS=TIME_BUCKET_HOURS
EXECUTION_PERIODS=ROLLING_CYCLE_HOURS//PERIOD_HOURS       # 4
RECEIVING_PERIODS=RECEIVING_WINDOW_HOURS//PERIOD_HOURS   # 12
LOOKAHEAD_PERIODS=LOOKAHEAD_HOURS//PERIOD_HOURS               # 16

def _integer_profile(total,weights):
    raw=[total*w/sum(weights) for w in weights];base=[int(x) for x in raw]
    for p in sorted(range(len(raw)),key=lambda x:raw[x]-base[x],reverse=True)[:total-sum(base)]:base[p]+=1
    return base

def build_synthetic_rolling_case(*,seed=0,num_blocks=8,bays_per_block=8,num_ships=8,cycles=6,bay_capacity=50,initial_utilization=.25,forecast_error=.10,outbound_boxes_per_period=DEFAULT_OUTBOUND_BOXES_PER_6H):
    if outbound_boxes_per_period<=0:raise ValueError("outbound_boxes_per_period must be positive")
    rng=random.Random(seed);blocks=[f"B{k+1:02d}" for k in range(num_blocks)];bays=[f"{k}_Y{i+1:02d}" for k in blocks for i in range(bays_per_block)];bay_block={i:i.split("_Y")[0] for i in bays};bay_size={i:(20 if p%2==0 else 40) for p,i in enumerate(bays)};capacity={i:int(bay_capacity) for i in bays};heights=("STD","HIGH");pods=("P1","P2","P3")
    ships=[];attrs={};eta_period={};release_period={};distance={};true_total={};true_flow={}
    triangle=[1,2,3,4,5,6,6,5,4,3,2,1]
    for q in range(num_ships):
        j=f"V{q+1:02d}";ships.append(j);admit=q%max(1,cycles-1)
        # Admission start is one of the four periods following the daily run.
        start=admit*EXECUTION_PERIODS+1+(q%EXECUTION_PERIODS);eta_period[j]=start+RECEIVING_PERIODS;berth=q%max(1,min(4,num_blocks))
        for kpos,k in enumerate(blocks):distance[j,k]=100+120*abs(kpos-berth)
        for pod in pods:
            for size in (20,40):
                h=heights[(q+pods.index(pod)+size//20)%2];g=f"{pod}_{size}_{h}";attrs[g]={"pod":pod,"size":size,"height":h};total=rng.randint(8,20) if rng.random()<.72 else 0
                if not total:continue
                true_total[j,g]=total
                for offset,value in enumerate(_integer_profile(total,triangle)):
                    if value:true_flow[j,g,start+offset]=value
        ship_total=sum(v for (jj,_g),v in true_total.items() if jj==j);release_period[j]=eta_period[j]+max(1,math.ceil(ship_total/outbound_boxes_per_period))
    # Forecast every future ship-period separately. Errors are correlated over
    # daily updates and shrink as the corresponding arrival period approaches.
    forecasts={};previous_error={}
    for r in range(cycles):
        now=r*EXECUTION_PERIODS
        for (j,g,t),truth in true_flow.items():
            if t<now:continue
            lead=max(1,t-now);sigma=forecast_error*min(1.0,lead/RECEIVING_PERIODS);old=previous_error.get((j,g,t),rng.gauss(0,sigma));e=.65*old+math.sqrt(1-.65**2)*rng.gauss(0,sigma);previous_error[j,g,t]=e;forecasts[r,j,g,t]=max(0,int(round(truth*(1+e))))
    locked={};locked_height={};old_release_period={};target=int(sum(capacity.values())*initial_utilization);placed=0;old_count=max(2,num_blocks//3)
    for o in range(old_count):
        old=f"OLD{o+1:02d}"
        quota=math.ceil(target/old_count);ship_placed=0
        for i in bays[o::old_count]:
            if placed>=target or ship_placed>=quota:break
            qty=min(capacity[i]//2,target-placed,quota-ship_placed);locked[i,old]=qty;locked_height[i,old]=heights[(bays.index(i)//2)%2];placed+=qty;ship_placed+=qty
    # Every ship uses a uniform post-ETA outbound profile. Initial old ships
    # start at staggered times; planning ships start exactly at ETA.
    old_outbound={}
    for o,old in enumerate(sorted({j for (_i,j) in locked})):
        total=sum(q for (_i,j),q in locked.items() if j==old);duration=max(1,math.ceil(total/outbound_boxes_per_period));start=o*EXECUTION_PERIODS;release=start+duration;old_release_period[old]=release
        block_remaining={k:sum(q for (i,j),q in locked.items() if j==old and bay_block[i]==k) for k in blocks};block_remaining={k:q for k,q in block_remaining.items() if q}
        for offset,period_total in enumerate(_integer_profile(int(total),[1]*duration)):
            left=period_total
            while left>0 and block_remaining:
                k=max(block_remaining,key=block_remaining.get);take=min(left,block_remaining[k]);old_outbound[old,k,start+offset]=take;block_remaining[k]-=take;left-=take
                if block_remaining[k]<=0:del block_remaining[k]
    ship_outbound={}
    for j in ships:
        total=sum(v for (jj,_g),v in true_total.items() if jj==j);duration=release_period[j]-eta_period[j]
        for offset,q in enumerate(_integer_profile(total,[1]*duration)):
            if q:ship_outbound[j,eta_period[j]+offset]=q
    outbound_forecasts={};ship_outbound_forecasts={};out_error={}
    for r in range(cycles):
        now=r*EXECUTION_PERIODS
        for (old,k,t),truth in old_outbound.items():
            if t<now:continue
            lead=max(1,t-now);sigma=.5*forecast_error*min(1.0,lead/RECEIVING_PERIODS);prior=out_error.get((old,k,t),rng.gauss(0,sigma));e=.65*prior+math.sqrt(1-.65**2)*rng.gauss(0,sigma);out_error[old,k,t]=e;outbound_forecasts[r,old,k,t]=max(0,int(round(truth*(1+e))))
        for (j,t),truth in ship_outbound.items():
            if t<now:continue
            lead=max(1,t-now);sigma=.5*forecast_error*min(1.0,lead/RECEIVING_PERIODS);key=(j,"SHIP",t);prior=out_error.get(key,rng.gauss(0,sigma));e=.65*prior+math.sqrt(1-.65**2)*rng.gauss(0,sigma);out_error[key]=e;ship_outbound_forecasts[r,j,t]=max(0,int(round(truth*(1+e))))
    return {"blocks":blocks,"bays":bays,"bay_block":bay_block,"bays_in_block":{k:[i for i in bays if bay_block[i]==k] for k in blocks},"bay_size":bay_size,"capacity":capacity,"heights":heights,"ships":ships,"eta_period":eta_period,"ship_release_period":release_period,"group_attrs":attrs,"true_total":true_total,"true_flow":true_flow,"forecasts":forecasts,"distance":distance,"locked_initial":locked,"locked_height_initial":locked_height,"old_release_period":old_release_period,"old_outbound_flow":old_outbound,"ship_outbound_flow":ship_outbound,"outbound_forecasts":outbound_forecasts,"ship_outbound_forecasts":ship_outbound_forecasts,"outbound_boxes_per_period":outbound_boxes_per_period,"cycles":cycles,"period_hours":PERIOD_HOURS,"execution_periods":EXECUTION_PERIODS,"receiving_periods":RECEIVING_PERIODS,"lookahead_periods":LOOKAHEAD_PERIODS,"seed":seed}

def build_repair_pressure_case(*,level="nearby",seed=0):
    """Create a diagnostic case that provably needs a repair expansion.

    ``nearby`` scales demand so the second adaptive expansion is required;
    ``global`` scales it further so only the full compatible yard is sufficient.
    """
    if level not in ("nearby","global"):raise ValueError("level must be nearby or global")
    case=build_synthetic_rolling_case(seed=seed,num_blocks=8,bays_per_block=4,num_ships=1,cycles=1,initial_utilization=0,forecast_error=0);factor=13 if level=="nearby" else 18
    case["forecasts"]={key:value*factor for key,value in case["forecasts"].items()};case["pressure_level"]=level;case["pressure_demand_factor"]=factor
    return case

def initial_simulation_state(case):return {"cycle":0,"actual_inventory":{},"previous_reservation":{},"previous_din":{},"locked_inventory":dict(case["locked_initial"]),"locked_height":dict(case["locked_height_initial"]),"completed":set(),"unplaced_actual":0}

def _participating_ships(case,now,completed):
    """Return the ships whose unexecuted plans may be revised at ``now``."""
    return {
        j for j in case["ships"]
        if case["eta_period"][j]-case["receiving_periods"]<=now<case["eta_period"][j]
        and j not in completed
    }

def optimization_snapshot(case: dict, state: dict) -> dict:
    r=state["cycle"];now=r*case["execution_periods"];end=now+case["lookahead_periods"];active=[];new=[];continuing=[]
    for j in case["ships"]:
        start=case["eta_period"][j]-case["receiving_periods"]
        if now<start<=now+case["execution_periods"]:new.append(j);active.append(j)
        elif start<=now<case["eta_period"][j] and j not in state["completed"]:continuing.append(j);active.append(j)
    # A historical plan is meaningful only for a ship that is still inside its
    # receiving window.  Filtering once here keeps expired plans out of the
    # stability budget, MIP start, impact region, and outbound block mapping.
    active_set=set(active)
    previous_reservation={key:q for key,q in state["previous_reservation"].items() if key[1] in active_set and q>0}
    previous_din={key:q for key,q in state.get("previous_din",{}).items() if key[1] in active_set and key[3]>=0 and q>0}
    forecast={}
    for j in active:
        for g in case["group_attrs"]:
            for absolute in range(now,end):
                q=case["forecasts"].get((r,j,g,absolute),0)
                if q:forecast[j,g,absolute-now]=q
    outbound={}
    for k in case["blocks"]:
        for absolute in range(now,end):
            q=sum(value for (rr,_old,kk,t),value in case["outbound_forecasts"].items() if rr==r and kk==k and t==absolute)
            if q:outbound[k,absolute-now]=q
    # Map post-ETA ship-level forecasts to blocks using already realized boxes
    # plus the inherited unexecuted plan. A first-cycle ship without a baseline
    # uses its closest block, keeping the forecast exogenous to this MIP.
    for j in case["ships"]:
        block_basis={k:sum(q for (i,jj,_g),q in state["actual_inventory"].items() if jj==j and case["bay_block"][i]==k)+sum(q for (i,jj,_g),q in previous_reservation.items() if jj==j and case["bay_block"][i]==k) for k in case["blocks"]}
        if not sum(block_basis.values()):
            closest=min(case["blocks"],key=lambda k:case["distance"][j,k]);block_basis[closest]=1
        weights=[block_basis[k] for k in case["blocks"]]
        for absolute in range(now,end):
            q=case["ship_outbound_forecasts"].get((r,j,absolute),0)
            if not q:continue
            for k,value in zip(case["blocks"],_integer_profile(q,weights)):
                if value:outbound[k,absolute-now]=outbound.get((k,absolute-now),0)+value
    remaining={(j,g):sum(q for (jj,gg,_n),q in forecast.items() if jj==j and gg==g) for j in active for g in case["group_attrs"]};remaining={k:q for k,q in remaining.items() if q}
    base={k:case[k] for k in ("blocks","bays","bay_block","bays_in_block","bay_size","capacity","heights","group_attrs","distance","period_hours","execution_periods","lookahead_periods")}
    releases={(i,j):case["old_release_period"].get(j,10**9)-now for i,j in state["locked_inventory"]}
    # Planned and realized inventory remains capacity-occupying until the known
    # whole-ship operation completion; forecast outbound is workload only.
    planned_ships=set(case["ships"])|{j for (_i,j,_g) in state["actual_inventory"]}|{j for (_i,j,_g) in previous_reservation}|set(active)
    ship_release_local={j:case["ship_release_period"].get(j,10**9)-now for j in sorted(planned_ships)}
    return base|{"cycle":r,"absolute_start_period":now,"periods":list(range(case["lookahead_periods"])),"active_ships":active,"new_ships":new,"continuing_ships":continuing,"actual_inventory":dict(state["actual_inventory"]),"previous_reservation":previous_reservation,"previous_din":previous_din,"locked_inventory":dict(state["locked_inventory"]),"locked_height":dict(state["locked_height"]),"locked_release_local":releases,"ship_release_local":ship_release_local,"forecast_arrivals":forecast,"forecast_outbound":outbound,"remaining_demand":remaining}

def advance_state(case: dict, state: dict, solution: dict) -> tuple[dict, dict]:
    """Execute only the next 24 hours and return realized incremental metrics."""
    cycle = state["cycle"]
    now = cycle * case["execution_periods"]
    actual = dict(state["actual_inventory"])
    reserve = {
        key: int(round(quantity))
        for key, quantity in solution.get("reservation", {}).items()
    }
    din = solution.get("din", {})
    cumulative_unplaced = state.get("unplaced_actual", 0)
    metrics = {
        "realized_arrivals": 0,
        "planned_placement_quantity": 0,
        "fallback_placement_quantity": 0,
        "realized_unplaced": 0,
        "realized_distance": 0.0,
        "realized_in_out_conflict": 0.0,
    }

    # Hidden outbound truth is read only in this execution simulator. Planning
    # ships are split over blocks deterministically using realized inventory.
    realized_outbound: dict[tuple[str, int], int] = {}
    for local in range(case["execution_periods"]):
        absolute = now + local
        for (_old, block, period), quantity in case["old_outbound_flow"].items():
            if period == absolute and quantity > 0:
                key = (block, local)
                realized_outbound[key] = realized_outbound.get(key, 0) + quantity
        for j in case["ships"]:
            quantity = case["ship_outbound_flow"].get((j, absolute), 0)
            if not quantity:
                continue
            basis = {
                block: sum(
                    value
                    for (bay, ship, _group), value in actual.items()
                    if ship == j and case["bay_block"][bay] == block
                )
                for block in case["blocks"]
            }
            if not sum(basis.values()):
                closest = min(case["blocks"], key=lambda block: case["distance"][j, block])
                basis[closest] = 1
            distributed = _integer_profile(
                quantity,
                [basis[block] for block in case["blocks"]],
            )
            for block, value in zip(case["blocks"], distributed):
                if value:
                    key = (block, local)
                    realized_outbound[key] = realized_outbound.get(key, 0) + value

    outbound_peak = max(realized_outbound.values(), default=1)
    for local in range(case["execution_periods"]):
        absolute = now + local
        for (j, g, period), realized in case["true_flow"].items():
            if period != absolute or realized <= 0:
                continue
            metrics["realized_arrivals"] += realized
            # Follow the period plan first, then use any remaining compatible
            # reservation for forecast error realized during execution.
            planned = sorted(
                ((din.get((bay, j, g, local), 0), bay) for bay in case["bays"]),
                reverse=True,
            )
            left = realized
            for planned_quantity, bay in planned:
                key = (bay, j, g)
                take = min(left, int(round(planned_quantity)), reserve.get(key, 0))
                actual[key] = actual.get(key, 0) + take
                reserve[key] = reserve.get(key, 0) - take
                left -= take
                block = case["bay_block"][bay]
                metrics["planned_placement_quantity"] += take
                metrics["realized_distance"] += take * case["distance"][j, block]
                metrics["realized_in_out_conflict"] += (
                    take * realized_outbound.get((block, local), 0) / max(1, outbound_peak)
                )
                if left <= 0:
                    break

            if left > 0:
                extras = sorted(
                    (
                        (quantity, bay)
                        for (bay, ship, group), quantity in reserve.items()
                        if ship == j and group == g and quantity > 0
                    ),
                    reverse=True,
                )
                for quantity, bay in extras:
                    locked = sum(
                        value
                        for (other_bay, old_ship), value in state["locked_inventory"].items()
                        if other_bay == bay
                        and case["old_release_period"].get(old_ship, 10**9) > absolute
                    )
                    occupied = sum(
                        value
                        for (other_bay, ship, _group), value in actual.items()
                        if other_bay == bay
                        and case["ship_release_period"].get(ship, 10**9) > absolute
                    )
                    existing_heights = {
                        case["group_attrs"][group]["height"]
                        for (other_bay, ship, group), value in actual.items()
                        if other_bay == bay
                        and value > 0
                        and case["ship_release_period"].get(ship, 10**9) > absolute
                    } | {
                        height
                        for (other_bay, old_ship), height in state["locked_height"].items()
                        if other_bay == bay
                        and case["old_release_period"].get(old_ship, 10**9) > absolute
                    }
                    if (
                        existing_heights
                        and case["group_attrs"][g]["height"] not in existing_heights
                    ):
                        continue
                    free = max(0, case["capacity"][bay] - locked - occupied)
                    take = min(left, quantity, free)
                    key = (bay, j, g)
                    actual[key] = actual.get(key, 0) + take
                    reserve[key] -= take
                    left -= take
                    block = case["bay_block"][bay]
                    metrics["fallback_placement_quantity"] += take
                    metrics["realized_distance"] += take * case["distance"][j, block]
                    metrics["realized_in_out_conflict"] += (
                        take * realized_outbound.get((block, local), 0) / max(1, outbound_peak)
                    )
                    if left <= 0:
                        break

            cumulative_unplaced += left
            metrics["realized_unplaced"] += left

    next_cycle = cycle + 1
    boundary = next_cycle * case["execution_periods"]
    next_active = _participating_ships(case, boundary, state["completed"])
    next_previous = {
        key: quantity
        for key, quantity in reserve.items()
        if key[1] in next_active and quantity > 0
    }
    next_din = {
        (bay, j, g, period - case["execution_periods"]): int(round(quantity))
        for (bay, j, g, period), quantity in din.items()
        if j in next_active
        and period >= case["execution_periods"]
        and quantity > 0
    }
    actual = {
        key: quantity
        for key, quantity in actual.items()
        if case["ship_release_period"].get(key[1], 10**9) > boundary
    }
    locked = {
        (bay, old_ship): quantity
        for (bay, old_ship), quantity in state["locked_inventory"].items()
        if case["old_release_period"].get(old_ship, 10**9) > boundary
    }
    locked_height = {
        key: height
        for key, height in state["locked_height"].items()
        if key in locked
    }
    completed = set(state["completed"])
    for j in case["ships"]:
        if boundary >= case["eta_period"][j]:
            completed.add(j)
    next_state = {
        "cycle": next_cycle,
        "actual_inventory": actual,
        "previous_reservation": next_previous,
        "previous_din": next_din,
        "locked_inventory": locked,
        "locked_height": locked_height,
        "completed": completed,
        "unplaced_actual": cumulative_unplaced,
    }
    return next_state, metrics
