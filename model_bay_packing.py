"""Bay-level LP feasibility oracle for a group-aggregated master point."""
from __future__ import annotations
import math,time
import gurobipy as gp
from gurobipy import GRB
from model_common import group_attr,group_size,remaining_capacity,required_reserve,ship_group_pairs

class BayPackingOracle:
    def __init__(self,data,*,integer_alloc=False,reservation_only=False):
        self.data=data;I,N,K=data["I_list"],data["N"],data["K"];pairs=[(j,g) for j,g in ship_group_pairs(data) if required_reserve(data,j,g,max(N),"integer")>0];self.I,self.N,self.K,self.pairs=I,N,K,pairs;rem=remaining_capacity(data);m=gp.Model("bay_packing_sp");m.Params.OutputFlag=0;m.Params.Method=1;m.Params.DualReductions=0;m.Params.InfUnbdInfo=1;self.model=m
        self.reservation_only=reservation_only;indices=[(i,j,g,n) for j,g in pairs for i in I if int(data["Fixed_Bay_Mode"][i])==group_size(data,g) for n in N];self.alloc=m.addVars(indices,lb=0,vtype=GRB.INTEGER if integer_alloc else GRB.CONTINUOUS,name="alloc_boxes");self.din={} if reservation_only else m.addVars([(j,g,i,n) for j,g in pairs for i in I if int(data["Fixed_Bay_Mode"][i])==group_size(data,g) for n in N],lb=0,name="din");self.dynamic=[];self.all=[]
        def add(lhs,sense,rhs,name,coeff=None):
            c=m.addConstr(lhs<=rhs,name=name) if sense=="<=" else (m.addConstr(lhs>=rhs,name=name) if sense==">=" else m.addConstr(lhs==rhs,name=name));record=(c,{"constant":float(rhs),**(coeff or {})});self.all.append(record)
            if coeff:self.dynamic.append(record)
        for i in I:
          for n in N:add(gp.quicksum(self.alloc[i,j,g,n] for j,g in pairs if (i,j,g,n) in self.alloc),"<=",math.floor(rem[i,n]+1e-9),f"cap_{i}_{n}")
        for j,g in pairs:
          p,h=group_attr(data,g,"pod"),group_attr(data,g,"height")
          for k in K:
            bays=[i for i in data["Bays_in_Block"][k] if (i,j,g,min(N)) in self.alloc]
            for n in N:
              add(gp.quicksum(self.alloc[i,j,g,n] for i in bays),"=",0,f"reserve_{k}_{j}_{g}_{n}",{"A":{(k,j,g,n):1}})
              if not reservation_only:add(gp.quicksum(self.din[j,g,i,n] for i in bays),"=",0,f"flow_{k}_{j}_{g}_{n}",{"z":{(j,k,g,n):1}})
              for i in bays:
                if n>min(N):add(self.alloc[i,j,g,n]-self.alloc[i,j,g,n-1],">=",0,f"mono_{i}_{j}_{g}_{n}")
                add(self.alloc[i,j,g,n],"<=",0,f"support_{i}_{j}_{g}_{n}",{"support":{(j,p,h,i):math.floor(rem[i,n]+1e-9)}})
                if not reservation_only:add(gp.quicksum(self.din[j,g,i,t] for t in N if t<=n)-self.alloc[i,j,g,n],"<=",0,f"storage_{i}_{j}_{g}_{n}")
        m.setObjective(0);m.update();self.point=None;self.solve_count=0;self.total_time=0
    def update_rhs(self,point):
        self.point=point
        for c,spec in self.dynamic:c.RHS=spec["constant"]+sum(v*point[name].get(k,0) for name,terms in spec.items() if name!="constant" for k,v in terms.items())
        self.model.update()
    def solve(self):
        t=time.perf_counter();self.model.optimize();self.total_time+=time.perf_counter()-t;self.solve_count+=1;return self.model.Status
    def farkas_cut(self,master_vars):
        expr=gp.LinExpr();value=0.0
        constant=0.0
        for c,spec in self.all:
            d=float(c.FarkasDual);constant+=d*spec["constant"]
            for name,terms in spec.items():
                if name=="constant":continue
                for k,v in terms.items():expr+=d*v*master_vars[{"A":"block_alloc","z":"block_flow","support":"pod_support"}[name]][k];value+=d*v*self.point[name].get(k,0)
        expr+=constant;value+=constant
        if value>0:expr=-expr;value=-value
        return expr,value
    def solution(self):
        alloc={(i,j,g,n):(float(self.alloc[i,j,g,n].X) if (i,j,g,n) in self.alloc else 0.0) for j,g in self.pairs for i in self.I for n in self.N};din={(j,g,i,n):(float(self.din[j,g,i,n].X) if (j,g,i,n) in self.din else 0.0) for j,g in self.pairs for i in self.I for n in self.N};return alloc,din
