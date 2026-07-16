"""Bay LP/MILP indexed by bay, ship, POD and height; bay data imply size."""
from __future__ import annotations
import math,time
import gurobipy as gp
from gurobipy import GRB
from model_common import demand_types,remaining_capacity

class BayPackingOracle:
 def __init__(self,data,*,integer_alloc=False,reservation_only=False):
  I,N,K=data["I_list"],data["N"],data["K"];types=demand_types(data);self.I,self.N,self.K,self.types=I,N,K,types;rem=remaining_capacity(data);m=gp.Model("pod_height_bay_packing");m.Params.OutputFlag=0;m.Params.Method=1;m.Params.DualReductions=0;m.Params.InfUnbdInfo=1;self.model=m
  idx=list(dict.fromkeys((i,j,p,h,n) for j,p,s,h in types for i in I if int(data["Fixed_Bay_Mode"][i])==s and data.get("OldBayHeight",{}).get(i,h)==h for n in N));self.alloc=m.addVars(idx,lb=0,vtype=GRB.INTEGER if integer_alloc else GRB.CONTINUOUS);self.din={} if reservation_only else m.addVars([(j,p,h,i,n) for i,j,p,h,n in idx],lb=0);self.dynamic=[];self.all=[]
  def add(lhs,sense,rhs,coeff=None):
   c=m.addConstr(lhs==rhs) if sense=="=" else (m.addConstr(lhs>=rhs) if sense==">=" else m.addConstr(lhs<=rhs));r=(c,{"constant":float(rhs),**(coeff or {})});self.all.append(r)
   if coeff:self.dynamic.append(r)
  keys={(j,p,h) for j,p,s,h in types}
  for i in I:
   for n in N:add(gp.quicksum(self.alloc[i,j,p,h,n] for j,p,h in keys if (i,j,p,h,n) in self.alloc),"<=",math.floor(rem[i,n]+1e-9))
  for j,p,s,h in types:
   for k in K:
    bays=[i for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==s and (i,j,p,h,min(N)) in self.alloc]
    for n in N:
     add(gp.quicksum(self.alloc[i,j,p,h,n] for i in bays),"=",0,{"A":{(k,j,p,s,h,n):1}})
     if not reservation_only:add(gp.quicksum(self.din[j,p,h,i,n] for i in bays),"=",0,{"z":{(j,k,p,s,h,n):1}})
     for i in bays:
      if n>min(N):add(self.alloc[i,j,p,h,n]-self.alloc[i,j,p,h,n-1],">=",0)
      add(self.alloc[i,j,p,h,n],"<=",0,{"support":{(j,p,h,i):math.floor(rem[i,n]+1e-9)}})
      if not reservation_only:add(gp.quicksum(self.din[j,p,h,i,t] for t in N if t<=n)-self.alloc[i,j,p,h,n],"<=",0)
  m.setObjective(0);m.update();self.point=None;self.solve_count=0;self.total_time=0
 def update_rhs(self,p):
  self.point=p
  for c,s in self.dynamic:c.RHS=sum(a*p[name].get(key,0) for name,terms in s.items() if name!="constant" for key,a in terms.items())
  self.model.update()
 def solve(self):t=time.perf_counter();self.model.optimize();self.total_time+=time.perf_counter()-t;self.solve_count+=1;return self.model.Status
 def farkas_cut(self,master):
  constant,coeff,val=self.farkas_certificate();e=gp.LinExpr(constant)
  for name,terms in coeff.items():
   for key,a in terms.items():e+=a*master[{"A":"block_alloc","z":"block_flow","support":"pod_support"}[name]][key]
  return e,val
 def farkas_certificate(self):
  """Return constant, RHS coefficients and value at the separated point."""
  constant=0.0;coeff={"A":{},"z":{},"support":{}};val=0.0
  for c,s in self.all:
   d=float(c.FarkasDual);constant+=d*s["constant"]
   for name,terms in s.items():
    if name=="constant":continue
    for key,a in terms.items():coeff[name][key]=coeff[name].get(key,0.0)+d*a
  val=constant+sum(a*self.point[name].get(key,0) for name,terms in coeff.items() for key,a in terms.items())
  if val>0:constant=-constant;coeff={name:{key:-a for key,a in terms.items()} for name,terms in coeff.items()};val=-val
  return constant,coeff,val
 @staticmethod
 def certificate_value(certificate,point):
  constant,coeff,_=certificate;return constant+sum(a*point[name].get(key,0) for name,terms in coeff.items() for key,a in terms.items())
 def solution(self):
  keys={(j,p,h) for j,p,s,h in self.types};a={(i,j,p,h,n):(float(self.alloc[i,j,p,h,n].X) if (i,j,p,h,n) in self.alloc else 0) for j,p,h in keys for i in self.I for n in self.N};d={(j,p,h,i,n):(float(self.din[j,p,h,i,n].X) if (j,p,h,i,n) in self.din else 0) for j,p,h in keys for i in self.I for n in self.N};return a,d
