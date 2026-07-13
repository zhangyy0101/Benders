import pytest
from anytime import canonicalize,trace_metrics

def test_canonical_trace_and_integrals():
 trace=canonicalize([{"time":0,"phase":"main","source":"start","ub":None,"lb":0},{"time":1,"phase":"main","source":"inc","ub":12,"lb":None},{"time":2,"phase":"main","source":"bound","ub":None,"lb":4},{"time":3,"phase":"main","source":"inc","ub":10,"lb":None}],4,10,5)
 assert [x["time"] for x in trace]==sorted(x["time"] for x in trace);assert [x["ub"] for x in trace if x["ub"] is not None]==sorted((x["ub"] for x in trace if x["ub"] is not None),reverse=True);assert [x["lb"] for x in trace if x["lb"] is not None]==sorted(x["lb"] for x in trace if x["lb"] is not None)
 m=trace_metrics(trace,4,9);assert m["time_to_first_feasible"]==1;assert m["time_to_best"]==3;assert m["primal_integral"]>0;assert m["gap_integral"]>0

def test_gap_integral_excludes_missing_bound_interval():
 trace=canonicalize([{"time":0,"ub":10,"lb":None},{"time":2,"ub":None,"lb":5}],4,10,5);assert trace_metrics(trace,4,9)["gap_integral"]==pytest.approx(1.0)
