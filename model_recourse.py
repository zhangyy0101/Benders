"""Reusable global LP recourse oracle and mathematically derived Benders cuts."""
from __future__ import annotations
import hashlib,time
from dataclasses import dataclass,field
import gurobipy as gp
from gurobipy import GRB
from model_common import arrival,fixed_in_block,groups,objective_scales,outbound_pressure,scale_factor

@dataclass
class BendersCutRecord:
    cut_type:str;constant:float;eta_coeff:float=0.0;x_coefficients:dict=field(default_factory=dict);alloc_coefficients:dict=field(default_factory=dict);origin:str="unknown";violation:float=0.0;signature:str=""
    def __post_init__(self):
        if not self.signature:
            payload=(self.cut_type,round(self.constant,12),round(self.eta_coeff,12),sorted((str(k),round(v,12)) for k,v in self.x_coefficients.items() if abs(v)>1e-12),sorted((str(k),round(v,12)) for k,v in self.alloc_coefficients.items() if abs(v)>1e-12));self.signature=hashlib.sha256(repr(payload).encode()).hexdigest()
    def value_at(self,point):return self.constant+self.eta_coeff*float(point.get("eta",0))+sum(v*point["x"].get(k,0) for k,v in self.x_coefficients.items())+sum(v*point["alloc_boxes"].get(k,0) for k,v in self.alloc_coefficients.items())
    def as_expression(self,master_vars):return self.constant+self.eta_coeff*master_vars["eta"]+gp.quicksum(v*master_vars["x"][k] for k,v in self.x_coefficients.items())+gp.quicksum(v*master_vars["alloc_boxes"][k] for k,v in self.alloc_coefficients.items())
    def coefficient_metrics(self):
        values=[abs(v) for v in [self.eta_coeff,*self.x_coefficients.values(),*self.alloc_coefficients.values()] if abs(v)>1e-12];return {"min_nonzero_coefficient":min(values,default=0),"max_nonzero_coefficient":max(values,default=0),"coefficient_ratio":max(values)/min(values) if values else 0,"cut_density":len(values)/(1+len(self.x_coefficients)+len(self.alloc_coefficients))}
@dataclass
class BendersCutPool:
    records:list=field(default_factory=list);signatures:set=field(default_factory=set);duplicate_skips:int=0
    def add(self,record):
        if record.signature in self.signatures:self.duplicate_skips+=1;return False
        self.records.append(record);self.signatures.add(record.signature);return True

class GlobalRecourseOracle:
    def __init__(self,data,weights):
        self.data,self.weights=data,weights;I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];self.I,self.J,self.G,self.N,self.K=I,J,G,N,K;self.model=gp.Model("global_recourse_lp");self.model.Params.OutputFlag=0;self.model.Params.Method=1;self.model.Params.DualReductions=0;self.model.Params.InfUnbdInfo=1
        m=self.model;self.din=m.addVars(J,G,I,N,lb=0,name="din");self.inv=m.addVars(J,G,I,N,lb=0,name="inv");self.share=m.addVars(J,K,G,N,lb=0,name="in_share");self.total=m.addVars(K,N,lb=0,name="in_total");self.avg=m.addVars(N,lb=0,name="avg");self.bal=m.addVars(K,N,lb=0,name="g_bal");self.rhs_records=[];self.storage={};self.handling={};alpha=float(data["Alpha"])
        def add(lhs,sense,rhs,name,affine=None):
            c=m.addConstr(lhs<=rhs,name=name) if sense=="<=" else (m.addConstr(lhs>=rhs,name=name) if sense==">=" else m.addConstr(lhs==rhs,name=name));self.rhs_records.append((c,affine or {"constant":float(rhs),"x":{},"alloc":{}}));return c
        for j in J:
         for g in G:
          for i in I:
           for n in N:
            initial=float(data["initial_inventory_data"].get((i,j,g),0));previous=self.inv[j,g,i,n-1] if n>0 else 0;add(self.inv[j,g,i,n]-self.din[j,g,i,n]-previous,"=",initial if n==0 else 0,f"inventory_{j}_{g}_{i}_{n}");key=(i,j,g,n);self.storage[key]=add(alpha*self.inv[j,g,i,n],"<=",0,f"storage_{i}_{j}_{g}_{n}",{"constant":0,"x":{},"alloc":{key:1.0}})
          for n in N:add(gp.quicksum(self.din[j,g,i,n] for i in I),"=",arrival(data,j,g,n),f"arrival_{j}_{g}_{n}")
         for i in I:
          for n in N:
           coeff=float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"]);key=(i,j,n);self.handling[key]=add(alpha*gp.quicksum(self.din[j,g,i,n] for g in G),"<=",0,f"handling_{i}_{j}_{n}",{"constant":0,"x":{key:coeff},"alloc":{}})
         for k in K:
          for g in G:
           for n in N:add(self.share[j,k,g,n]-gp.quicksum(self.din[j,g,i,n] for i in data["Bays_in_Block"][k]),"=",0,f"share_{j}_{k}_{g}_{n}")
        fixed=fixed_in_block(data)
        for k in K:
         for n in N:add(self.total[k,n]-gp.quicksum(self.share[j,k,g,n] for j in J for g in G),"=",fixed[k,n],f"total_{k}_{n}");add(self.total[k,n]-self.avg[n]-self.bal[k,n],"<=",0,f"bal_pos_{k}_{n}");add(self.avg[n]-self.total[k,n]-self.bal[k,n],"<=",0,f"bal_neg_{k}_{n}")
        for n in N:add(len(K)*self.avg[n]-gp.quicksum(self.total[k,n] for k in K),"=",0,f"avg_{n}")
        scales=objective_scales(data);pressure=outbound_pressure(data);self.distance_raw=gp.quicksum(float(data["Dist"][j,k])*self.share[j,k,g,n] for j in J for k in K for g in G for n in N);self.balance_raw=gp.quicksum(self.bal[k,n] for k in K for n in N);self.conflict_raw=gp.quicksum(float(pressure[k,n])*self.share[j,k,g,n] for j in J for k in K for g in G for n in N);self.objective=scale_factor(weights)*(weights.sub.dist*self.distance_raw/scales["distance"]+weights.sub.balance*self.balance_raw/scales["balance"]+weights.sub.conflict*self.conflict_raw/scales["conflict"]);m.setObjective(self.objective,GRB.MINIMIZE);m.update();self.point=None;self.solve_count=self.optimal_count=self.infeasible_count=0;self.total_time=self.max_time=0
    @staticmethod
    def _affine_value(a,point):return a["constant"]+sum(v*point["x"].get(k,0) for k,v in a["x"].items())+sum(v*point["alloc_boxes"].get(k,0) for k,v in a["alloc"].items())
    def update_rhs(self,x_values,alloc_values):
        self.point={"x":dict(x_values),"alloc_boxes":dict(alloc_values),"eta":0.0}
        for c,a in self.rhs_records:c.RHS=self._affine_value(a,self.point)
        self.model.update()
    def solve(self):
        t=time.perf_counter();self.model.optimize();dt=time.perf_counter()-t;self.solve_count+=1;self.total_time+=dt;self.max_time=max(self.max_time,dt)
        if self.model.Status==GRB.OPTIMAL:self.optimal_count+=1
        elif self.model.Status==GRB.INFEASIBLE:self.infeasible_count+=1
        return self.model.Status
    def objective_value(self):return float(self.model.ObjVal)
    def solution(self):return {"din":{k:v.X for k,v in self.din.items()},"inv":{k:v.X for k,v in self.inv.items()},"in_share":{k:v.X for k,v in self.share.items()},"in_total":{k:v.X for k,v in self.total.items()},"avg":{k:v.X for k,v in self.avg.items()},"g_bal":{k:v.X for k,v in self.bal.items()}}
    def build_optimality_cut(self,point,origin="unknown"):
        if self.model.Status!=GRB.OPTIMAL:raise RuntimeError("optimality cut requested from non-optimal SP")
        xcoef={};acoef={}
        for c,a in self.rhs_records:
            pi=float(c.Pi)
            for k,v in a["x"].items():xcoef[k]=xcoef.get(k,0)+pi*v
            for k,v in a["alloc"].items():acoef[k]=acoef.get(k,0)+pi*v
        q=self.objective_value();intercept=q-sum(v*point["x"].get(k,0) for k,v in xcoef.items())-sum(v*point["alloc_boxes"].get(k,0) for k,v in acoef.items());record=BendersCutRecord("optimality",-intercept,1.0,{k:-v for k,v in xcoef.items()},{k:-v for k,v in acoef.items()},origin);tight=record.value_at({**point,"eta":q})
        if abs(tight)>1e-5:raise AssertionError(f"optimality cut not tight: {tight}")
        return record
    def build_feasibility_cut(self,point,origin="unknown"):
        if self.model.Status!=GRB.INFEASIBLE:raise RuntimeError("feasibility cut requested from non-infeasible SP")
        constant=0;xcoef={};acoef={}
        for c,a in self.rhs_records:
            fd=float(c.FarkasDual);constant+=fd*a["constant"]
            for k,v in a["x"].items():xcoef[k]=xcoef.get(k,0)+fd*v
            for k,v in a["alloc"].items():acoef[k]=acoef.get(k,0)+fd*v
        raw=constant+sum(v*point["x"].get(k,0) for k,v in xcoef.items())+sum(v*point["alloc_boxes"].get(k,0) for k,v in acoef.items());record=BendersCutRecord("feasibility",constant,0,xcoef,acoef,origin,abs(raw))
        if record.value_at(point)>=-1e-7:raise RuntimeError(f"Farkas cut does not violate point: {record.value_at(point)}")
        return record
    def statistics(self):return {"sp_solve_count":self.solve_count,"sp_optimal_count":self.optimal_count,"sp_infeasible_count":self.infeasible_count,"sp_total_time":self.total_time,"sp_average_time":self.total_time/max(1,self.solve_count),"sp_max_time":self.max_time}
