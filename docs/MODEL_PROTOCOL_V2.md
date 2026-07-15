# Model protocol v2

Identity: `paper-exp-v2-integer-allocation-no-alpha-no-open`.

The primary output `alloc_boxes[i,j,g,n]` is an integer number of box slots
reserved at bay `i` for ship `j` and joint attribute group `g` through period
`n`. Total reserved slots equal cumulative arrivals. `Alpha` is not part of the
V2 mathematical model.

`din` and `in_share` are continuous aggregate flows. This is appropriate for
tactical planning and preserves the LP recourse required by Benders cuts. They
support the integer slot plan but are not the primary operational output.
`inv` is reconstructed as initial inventory plus cumulative `din`; it is not a
separate optimization variable.

`x[i,j,n]` is a derived compatibility/KPI field: it equals one exactly when ship
`j` has a positive allocation at bay `i` in period `n`. It is neither a decision
variable nor part of the objective. Multiple ships may reserve slots in the same
bay. The original problem has no bay-unit-time handling-capacity constraint, so
no such constraint is imposed.

The objective contains concentration, distance, workload balance, and conflict.
The concentration numerator remains total used joint-group bays and is divided
by the number of positive ship-groups, i.e. average used bays per positive
ship-group. Handling-rate fields and `handling_rate_scale` are retained only for
legacy data/CLI compatibility and do not affect V2 optimization. V1 and V2
results must not be pooled.
