"""Canonical anytime traces and finite-horizon integral metrics."""
from __future__ import annotations
def relative_gap(ub,lb):return None if ub is None or lb is None else max(0.0,(ub-lb)/max(abs(ub),1e-9))
def canonicalize(points,final_time,final_ub=None,final_lb=None):
 out=[];best_ub=best_lb=None
 for p in sorted(points,key=lambda x:float(x.get("time",0))):
  if p.get("ub") is not None:best_ub=float(p["ub"]) if best_ub is None else min(best_ub,float(p["ub"]))
  if p.get("lb") is not None:best_lb=float(p["lb"]) if best_lb is None else max(best_lb,float(p["lb"]))
  q={"time":max(0.0,float(p.get("time",0))),"phase":str(p.get("phase","main")),"source":str(p.get("source","solver")),"ub":best_ub,"lb":best_lb,"gap":relative_gap(best_ub,best_lb)}
  if not out or any(q[k]!=out[-1][k] for k in ("ub","lb","phase","source")):out.append(q)
 if final_ub is not None:best_ub=float(final_ub) if best_ub is None else min(best_ub,float(final_ub))
 if final_lb is not None:best_lb=float(final_lb) if best_lb is None else max(best_lb,float(final_lb))
 q={"time":max(float(final_time),out[-1]["time"] if out else 0),"phase":"final","source":"final_result","ub":best_ub,"lb":best_lb,"gap":relative_gap(best_ub,best_lb)}
 if out and out[-1]["time"]==q["time"]:out[-1]=q
 else:out.append(q)
 return out
def trace_metrics(trace,horizon,bks=None):
 feasible=[p for p in trace if p["ub"] is not None];first=feasible[0]["time"] if feasible else None;best=min((p["ub"] for p in feasible),default=None);best_time=next((p["time"] for p in feasible if p["ub"]==best),None);pi=gi=0.0
 for a,b in zip(trace,trace[1:]):
  dt=max(0,min(float(horizon),b["time"])-min(float(horizon),a["time"]))
  if bks is not None and a["ub"] is not None:pi+=dt*max(0,(a["ub"]-bks)/max(abs(bks),1e-9))
  if a["gap"] is not None:gi+=dt*a["gap"]
 return {"time_to_first_feasible":first,"time_to_best":best_time,"primal_integral":pi if bks is not None else None,"gap_integral":gi}
