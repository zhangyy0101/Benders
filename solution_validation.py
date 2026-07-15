"""Independent feasibility checker for Route-B exact UB solutions."""
from model_common import arrival,fixed_in_block,group_attr,group_size,groups,remaining_capacity,required_reserve,ship_group_pairs,ship_groups
from model_concentration import evaluate_joint_group_concentration
def validate_solution(data,solution,*,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,tolerance=1e-5):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];pairs=ship_group_pairs(data);rem=remaining_capacity(data);viol={}
    def rec(name,x):viol[name]=max(viol.get(name,0),max(0,float(x)))
    def val(name,k):return float(solution.get(name,{}).get(k,0))
    for j in J:
     for g in ship_groups(data,j):
      for n in N:
       rec("arrival",abs(sum(val("din",(j,g,i,n)) for i in I)-arrival(data,j,g,n)));rec("exact_reserve",abs(sum(val("alloc_boxes",(i,j,g,n)) for i in I)-required_reserve(data,j,g,n,alloc_domain)))
       for i in I:
        cumulative=float(data["initial_inventory_data"].get((i,j,g),0))+sum(val("din",(j,g,i,t)) for t in N if t<=n);rec("inventory_derived",abs(val("inv",(j,g,i,n))-cumulative));rec("storage_link",cumulative-val("alloc_boxes",(i,j,g,n)));rec("fixed_mode",abs(val("alloc_boxes",(i,j,g,n))) if group_size(data,g)!=int(data["Fixed_Bay_Mode"][i]) else 0)
     for k in K:
      for g in ship_groups(data,j):
       for n in N:rec("block_flow",abs(val("in_share",(j,k,g,n))-sum(val("din",(j,g,i,n)) for i in data["Bays_in_Block"][k])))
    fixed=fixed_in_block(data)
    for i in I:
     used_heights={group_attr(data,g,"height") for j,g in pairs if any(val("alloc_boxes",(i,j,g,n))>tolerance for n in N)};old=data.get("OldBayHeight",{}).get(i)
     rec("height_mixing",len(used_heights|({old} if old is not None else set()))-1)
     for n in N:rec("bay_capacity",sum(val("alloc_boxes",(i,j,g,n)) for j,g in pairs)-rem[i,n])
    for k in K:
     for n in N:rec("in_total",abs(val("in_total",(k,n))-fixed[k,n]-sum(val("in_share",(j,k,g,n)) for j,g in pairs)));rec("l1_pos",val("in_total",(k,n))-val("avg",n)-val("g_bal",(k,n)));rec("l1_neg",val("avg",n)-val("in_total",(k,n))-val("g_bal",(k,n)))
    for n in N:rec("average",abs(len(K)*val("avg",n)-sum(val("in_total",(k,n)) for k in K)))
    if alloc_domain=="integer":
     for value in solution["alloc_boxes"].values():rec("integrality",abs(value-round(value)))
    concentration=evaluate_joint_group_concentration(data,solution,alloc_domain=alloc_domain,enabled=concentration_enabled,tolerance=tolerance)
    if concentration["enabled"]:
     if "concentration_use" in solution:
      for (j,g,i),value in solution["concentration_use"].items():rec("concentration_support",abs(float(value)-float(i in concentration["used_bays"].get((j,g),[]))))
      modeled=sum(float(v) for v in solution["concentration_use"].values());rec("concentration_raw",abs(modeled-concentration["raw_used_bays"]))
    maximum=max(viol.values(),default=0);return {"feasible":maximum<=tolerance,"max_violation":maximum,"violations_by_family":viol}
