"""Independent feasibility checker for Route-B exact UB solutions."""
from model_common import arrival,fixed_in_block,group_size,groups,remaining_capacity,required_reserve
from model_concentration import evaluate_joint_group_concentration
def validate_solution(data,solution,*,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,tolerance=1e-5):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];alpha=float(data["Alpha"]);rem=remaining_capacity(data);viol={}
    def rec(name,x):viol[name]=max(viol.get(name,0),max(0,float(x)))
    def val(name,k):return float(solution.get(name,{}).get(k,0))
    for j in J:
     for g in G:
      for n in N:
       rec("arrival",abs(sum(val("din",(j,g,i,n)) for i in I)-arrival(data,j,g,n)));rec("exact_reserve",abs(sum(val("alloc_boxes",(i,j,g,n)) for i in I)-required_reserve(data,j,g,n,alloc_domain)))
       for i in I:
        prev=val("inv",(j,g,i,n-1)) if n>0 else float(data["initial_inventory_data"].get((i,j,g),0));rec("inventory",abs(val("inv",(j,g,i,n))-prev-val("din",(j,g,i,n))));rec("storage_link",alpha*val("inv",(j,g,i,n))-val("alloc_boxes",(i,j,g,n)));rec("fixed_mode",abs(val("alloc_boxes",(i,j,g,n))) if group_size(data,g)!=int(data["Fixed_Bay_Mode"][i]) else 0)
     for i in I:
      for n in N:rec("handling",alpha*sum(val("din",(j,g,i,n)) for g in G)-float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"])*val("x",(i,j,n)));rec("alloc_x",sum(val("alloc_boxes",(i,j,g,n)) for g in G)-rem[i,n]*val("x",(i,j,n)));rec("x_alloc",val("x",(i,j,n))-sum(val("alloc_boxes",(i,j,g,n)) for g in G))
     for k in K:
      for g in G:
       for n in N:rec("block_flow",abs(val("in_share",(j,k,g,n))-sum(val("din",(j,g,i,n)) for i in data["Bays_in_Block"][k])))
    fixed=fixed_in_block(data)
    for i in I:
     for n in N:rec("bay_capacity",sum(val("alloc_boxes",(i,j,g,n)) for j in J for g in G)-rem[i,n])
    for k in K:
     for n in N:rec("in_total",abs(val("in_total",(k,n))-fixed[k,n]-sum(val("in_share",(j,k,g,n)) for j in J for g in G)));rec("l1_pos",val("in_total",(k,n))-val("avg",n)-val("g_bal",(k,n)));rec("l1_neg",val("avg",n)-val("in_total",(k,n))-val("g_bal",(k,n)))
    for n in N:rec("average",abs(len(K)*val("avg",n)-sum(val("in_total",(k,n)) for k in K)))
    if alloc_domain=="integer":
     for value in solution["alloc_boxes"].values():rec("integrality",abs(value-round(value)))
    concentration=evaluate_joint_group_concentration(data,solution,alloc_domain=alloc_domain,enabled=concentration_enabled,tolerance=tolerance)
    if concentration["enabled"]:
     final=concentration["final_period"]
     for j,g in concentration["positive_ship_groups"]:
      used=concentration["used_blocks"][j,g];rec("concentration_minimum_blocks",concentration["minimum_blocks"][j,g]-len(used));rec("concentration_cover",required_reserve(data,j,g,final,alloc_domain)-sum(concentration["big_m"][j,g,k] for k in used))
      for k in used:
       if "concentration_use" in solution:rec("concentration_support",1-float(solution["concentration_use"].get((j,g,k),0)))
     if "concentration_use" in solution:
      for (j,g,k),value in solution["concentration_use"].items():rec("concentration_support",abs(float(value)-float(k in concentration["used_blocks"].get((j,g),[]))))
      modeled=sum(float(v) for v in solution["concentration_use"].values())-sum(concentration["minimum_blocks"].values());rec("concentration_raw",abs(modeled-concentration["raw_excess_blocks"]))
    maximum=max(viol.values(),default=0);return {"feasible":maximum<=tolerance,"max_violation":maximum,"violations_by_family":viol}
