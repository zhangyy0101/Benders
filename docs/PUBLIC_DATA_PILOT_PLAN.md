# Public-data pilot plan

## Data split

- Development/calibration set: may be used for field mapping, runtime-share calibration, aggregate-LB checks, and diagnosing whether a primal module is needed.
- Final holdout set: must remain untouched until the final algorithm is frozen. It must not be used for repeated tuning.

## Development workflow

1. Freeze and record the dataset split before adapting fields.
2. Validate units, identifiers, time intervals, capacities, handling rates, and missing-value policies on the development set.
3. Run `algorithm-candidate-v1` only after schema validation passes.
4. Record configuration version/hash, dataset digest, budget, environment, and anytime trace for every run.
5. Treat public-data performance as development evidence, not a paper conclusion or holdout result.

## Revision policy

Algorithm changes remain allowed on the development set. If candidate-v1 performs poorly:

- diagnose field mapping and data semantics before changing the algorithm;
- change only the component or time allocation supported by development evidence;
- create `algorithm-candidate-v2` with a new configuration hash;
- never mix v1 and v2 results;
- rerun only affected synthetic confirmation pairs, not all historical experiments.

## Holdout policy

P4 authorizes development/calibration-set adaptation and testing. It does not authorize final holdout execution. The holdout may be opened once, only after a later decision explicitly freezes the final algorithm.

## Paper ablation reservation

The unique planned variants are:

| Variant | Aggregate LB | Root | Primal module |
|---|---:|---:|---:|
| BBC core |  |  |  |
| Candidate v1 / + aggregate | ✓ |  |  |
| + aggregate + root | ✓ | ✓ |  |

Analytic LB is omitted unless later development produces new isolated evidence. Candidate-v1 remains the `+ aggregate` row; it is not duplicated under a second label.
