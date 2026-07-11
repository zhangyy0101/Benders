# Algorithm component pilot

No component is frozen or deleted in this stage.

- **bbc_valid**: Needs more evidence; median gap change vs core = 0.00033001522871312083.
- **bbc_root**: Keep for next round; median gap change vs core = 0.9402750251475055.
- **bbc_warm**: Needs more evidence; median gap change vs core = 0.003104226124211462.
- **bbc_alns**: Keep for next round; median gap change vs core = 0.939496745850532.
- **bbc_root_warm**: Keep for next round; median gap change vs core = 0.9404545774516717.
- **bbc_root_alns**: Keep for next round; median gap change vs core = 0.9548763282176312.
- **bbc_full_current**: Keep for next round; median gap change vs core = 0.9580322735947555.

## Collected component diagnostics

- **bbc_core**: root improvement median=None, root time median=0.0s, warm initial UB median=None, ALNS improvement median=0.0, ALNS time median=0.0s, nodes median=19.0.
- **bbc_valid**: root improvement median=None, root time median=0.0s, warm initial UB median=None, ALNS improvement median=0.0, ALNS time median=0.0s, nodes median=1.0.
- **bbc_root**: root improvement median=None, root time median=1.1088543999940157s, warm initial UB median=None, ALNS improvement median=0.0, ALNS time median=0.0s, nodes median=1.0.
- **bbc_warm**: root improvement median=None, root time median=0.0s, warm initial UB median=44239.20227200602, ALNS improvement median=0.0, ALNS time median=0.0s, nodes median=1.0.
- **bbc_alns**: root improvement median=None, root time median=0.0s, warm initial UB median=47446.86961279705, ALNS improvement median=0.0, ALNS time median=3.755182799999602s, nodes median=643.0.
- **bbc_root_warm**: root improvement median=None, root time median=1.0114969999995083s, warm initial UB median=44239.20227200602, ALNS improvement median=0.0, ALNS time median=0.0s, nodes median=1.0.
- **bbc_root_alns**: root improvement median=None, root time median=0.0746878000209108s, warm initial UB median=47446.86961279705, ALNS improvement median=0.0, ALNS time median=3.755326599930413s, nodes median=1.0.
- **bbc_full_current**: root improvement median=None, root time median=0.0722053999779746s, warm initial UB median=50537.25442960891, ALNS improvement median=3085.6444982163666, ALNS time median=3.7533442999701947s, nodes median=1.0.

Successful ALNS operator counts remain available per run in `method_diagnostics.alns.successful_operators` within `raw_results.jsonl`.

Aggregate/analytic LB are jointly present in root/full configurations in this first progressive screen; separating their individual effects requires next-round ablation.

Stabilized and node-cut configurations were not run because no prior evidence yet justified their callback cost.

Final algorithm is not frozen in Task 10.
