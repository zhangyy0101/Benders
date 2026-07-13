# algorithm-candidate-v1

Status: frozen candidate; not the final algorithm.

Configuration hash: `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`.

## Algorithm structure

1. Solve the exact BBC master.
2. Evaluate master points with the global recourse oracle.
3. Add globally valid feasibility and optimality cuts.
4. Strengthen the master with the aggregate recourse lower bound.

Enabled configuration fields:

```json
{
  "aggregate_recourse_lb": true,
  "analytic_recourse_lb": false,
  "root_prepass": false,
  "warm_start": false,
  "alns": false,
  "valid_inequalities": false,
  "node_cuts": false,
  "cut_strategy": "standard"
}
```

The whole time budget belongs to the main BBC phase. The candidate has no primal initialization/improvement module.

Changing any algorithm field requires a new hash and the name `algorithm-candidate-v2`; v1 and v2 results must not be pooled.
