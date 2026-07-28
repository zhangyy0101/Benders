# External literature baseline adaptation protocol

Status: development and pilot-comparison protocol. This document does not
change the rolling-horizon mathematical model or the frozen
`full_bottleneck` candidate algorithm.

## Common comparison boundary

Every external method receives the same optimizer-visible rolling snapshot
and returns the same integer decision:

\[
q_{i,j,g}\in\mathbb Z_+,
\]

the number of box slots reserved in bay \(i\) for vessel \(j\) and group
\(g=(\mathrm{POD},\mathrm{size},\mathrm{height})\). No method receives hidden
realization data. All results pass through the existing independent validator
and rolling execution simulator.

The methods share:

- 6-hour buckets, a 24-hour replan cycle and a 96-hour lookahead;
- the same forecasts, lifecycle filtering, previous plan and realized path;
- integer arrivals, reservations and bay-level inbound flows;
- bay capacity, size compatibility, no-mixed-height feasibility and
  vessel-level release rules;
- shortage only when no compatible capacity remains;
- the same wall-clock boundary, fallback policy and ex-post evaluator;
- common shortage, stability, concentration, balance, distance and
  inbound/outbound-conflict metrics.

The candidate's MIP start, impact-region logic, bottleneck selector,
Progressive Repair and global MIP recovery are unavailable to the literature
baselines.

## Kim--Park 2003

K. H. Kim and K. T. Park, "A note on a dynamic space-allocation method for
outbound containers," European Journal of Operational Research 148(1),
92--101, 2003. DOI:
https://doi.org/10.1016/S0377-2217(02)00333-8.

The source allocates future outbound-container space by vessel and block over
a rolling horizon. Vacated space becomes available only after the relevant
stage, forecasts are deterministic within one solve, and only the first
rolling-stage decision is implemented.

### Mapping

| Source | Common adapted implementation |
|---|---|
| vessel-stage demand \(d_{ij}\) | forecast boxes by vessel/group/6-hour period |
| block allocation \(x_{ijk}\) | integer bay flows aggregated over the block |
| initial inventory \(x_{i0k}\) | actual and locked old-vessel inventory |
| block capacity \(C_k\) | physical bay capacities plus bay decoder checks |
| stage end | `ship_release_local` |
| block-to-berth cost | vessel-to-block distance |
| maximum blocks per vessel | omitted; optional in the source and absent from the common model |
| intra-yard equipment distance | omitted; no row/stack travel graph exists in the common data |

Both KP methods use one literature-neutral integer bay decoder. It scans the
method-ranked blocks and performs best-fit within compatible bays while
enforcing capacity, size, height and lifecycle constraints. It never invokes
the candidate algorithm's repair components.

### `kp_dos`

The adapted least-duration-of-stay rule:

1. processes forecast stages chronologically;
2. ranks same-stage demand by increasing vessel release time;
3. ranks feasible blocks by vessel-to-block travel distance;
4. assigns through the common bay decoder;
5. reports an unassignable residual as shortage.

Rolling-plan stability is measured ex post and is not optimized by KP-DOS.

### `kp_sg`

The publisher full text permits a substantially closer implementation than a
structure-only proxy:

1. relax the shared time-dependent block-capacity constraints;
2. decompose by vessel;
3. solve arrival stages in reverse order using travel cost plus the sum of
   relevant block-period multipliers;
4. form the block-period overload subgradient;
5. update nonnegative multipliers with a Held--Wolfe upper-bound-gap step;
6. halve the step parameter after repeated relaxed-bound non-improvement;
7. retain relaxed block preferences and recover an integer feasible plan by
   processing earlier-release vessels first and moving residual demand to the
   least-increase compatible block through the common bay decoder.

The update convention is:

\[
\eta_r =
\lambda_r\frac{UB-L(p^r)}{\lVert g^r\rVert_2^2},\qquad
p^{r+1}=\max\{0,p^r+\eta_rg^r\}.
\]

The source states that \(\lambda\) is halved after 5--10 non-improving
iterations and terminates below 0.025. It does not state the initial
\(\lambda\), the selected member of the 5--10 range, initial multipliers or
tie-breaking. Frozen disclosed conventions are:

- \(\lambda_0=2\), the standard Held--Wolfe convention;
- five non-improving iterations before halving;
- zero initial multipliers;
- termination below 0.025;
- deterministic identifier tie-breaking;
- a 200-iteration safety guard and the common wall-clock limit.

Fidelity status: the researcher-supplied publisher PDF was checked
equation-by-equation. The relaxation, vessel decomposition, reverse-stage
subproblem and overload-repair priority follow the full text. The result is
still named **adapted KP-SG**, not exact reproduction, because the common
problem adds groups, bay-level hard constraints and shortage, and because the
paper omits the parameter choices listed above.

## DRA-RPM 2024

B. Xuan, C. Liang, X. Yang, H. Li and Z. Yang, "A dynamic yard space
reservation algorithm based on reward-penalty mechanism," Heliyon 10,
e37817, 2024. DOI: https://doi.org/10.1016/j.heliyon.2024.e37817.

The full text defines conflict, distance, space, past-continuity and
future-potential reward/penalty terms.

### Mapping

| Source | Common adapted implementation |
|---|---|
| container group \(i\) | vessel/POD/size/height group |
| interval \(\Delta t\) | 6-hour period |
| free positions \(\theta_{bay}\) | feasible residual slots over the group's stay |
| group quantity \(\alpha_i\) | current-period remaining forecast boxes |
| operation count \(\tau_b\) | outbound forecast normalized to 0--10 |
| berth distance \(\gamma_{b\beta}\) | vessel-to-block distance |
| previous reservations | method-owned history carried between cycles |
| future potential | next-period group demand versus compatible residual capacity |

The common model has no business-defined \(\gamma_{\max}\); therefore the
source's \(-M\) distance exclusion is inactive. The source reserves whole
stacks and delegates container-slot placement to MCTS. The common model
instead requires exact integer box slots and forbids safety
over-reservation, so adapted DRA-RPM repeatedly selects the best feasible bay
and reserves only the required integer quantity.

The implementation follows Equations (19)--(27):

- conflict values \(-100,-20,20,100\);
- competing-group values \(-50,-20,0\);
- distance \(20-20\gamma/\bar\gamma\);
- space waste \(-10(\theta-\alpha)/\theta\) for \(\theta>\alpha\);
- past and future terms with frozen \(\mu=\nu=0.5\) and \(\phi=0.8\).

The paper does not publish numerical values for \(\mu,\nu,\phi\), so these
are disclosed adaptation parameters and require sensitivity analysis.
Equation (27) and the prose maximize reward, while Algorithm 3 initializes
positive infinity and tests for a smaller score. The adaptation follows the
mathematical definition and selects the maximum.

The main table freezes the profile `frozen` at
\((\mu,\nu,\phi)=(0.5,0.5,0.8)\). A separate one-factor-at-a-time experiment
uses `mu_low=0.25`, `mu_high=0.75`, `nu_low=0.25`, `nu_high=0.75`,
`discount_low=0.60`, and `discount_high=0.95`. These profiles do not alter the
candidate algorithm and are never selected post hoc per instance. The formal
runner records the profile and all three scalar parameters in every DRA-RPM
row.

Fidelity status: the supplied formal PDF confirms the open full text. The
method remains **adapted DRA-RPM** because of the operation proxy, exact-slot
output, common hard constraints and altered rolling state.

## Reporting and verification gate

Each cycle records source identity, DOI, fidelity status, native diagnostics,
wall time, common predicted components, realized KPIs and independent
validation. Heuristics have no valid MIP gap or branch-and-bound node count;
these remain null or zero.

Formal claims use paired instance/seed comparisons under the common
evaluator. Native reward and Lagrangian quantities explain behavior but are
never compared directly with the candidate's normalized objective.

### Cached implementation v1.1

Protocol identifier `adapted-literature-baselines-v1.1-sparse-cached`
replaces repeated evaluation of immutable inputs with exact caches:

- locked and actual inventory are indexed by bay;
- jobs, ship/arrival occupied periods, compatible bays/blocks, and mean
  ship-to-block distance are cached;
- KP-SG reuses those immutable values inside its subgradient iterations;
- DRA-RPM computes current compatible-bay capacity once per job and computes
  next-period capacity once per block, updating only the selected bay and
  block after a placement.

The KP relaxation, subgradient step, stopping parameters, DRA reward
equations, method parameters, candidate ordering, deterministic tie-breaking,
common decoder, constraints, and online time boundary are unchanged. Fixed
nonbinding test snapshots reproduce identical `din`, reservation, and
shortage dictionaries before and after caching.

Before formal experiments:

1. test demand conservation, integrality, size, height, capacity, release and
   deterministic tie-breaking;
2. verify DOS priority on a capacity-scarce hand instance;
3. verify KP-SG multiplier direction, reverse-stage ordering and recovery;
4. verify every DRA reward identity and Equation (27) maximization;
5. execute at least two rolling cycles for lifecycle and method-state checks;
6. run a paired small/medium/large development matrix;
7. retain source-PDF bibliographic checksums in the private research audit
   trail without redistributing publisher files through the repository.

The verified SHA-256 checksums are:

- Kim--Park PDF:
  `269d3c6b102de2cc2e1f46db563e4b9452915df2a2db8d519c4d3463286fe15c`;
- DRA-RPM PDF:
  `19d672e7fed8a017863a67566ca84ea573a3ab035b7fe21e4f8882d026aee466`.
