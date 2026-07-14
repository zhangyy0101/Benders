# Aggregate-Guided Fix-and-Repair Method Specification

Standalone AGFR uses one wall-clock deadline for an aggregate guide, deterministic candidate-domain construction and coverage checks, restricted monolithic repair, independent checking, and exact global-recourse canonicalization.

The guide consumes at most 25% of the supplied budget and never reports an UB. A size/deadline guard may return static support immediately when building the aggregate guide would consume its useful budget. In that case, an objective-free continuous coverage LP may provide sparse reserve support to candidate generation. Candidate levels 0, 1, and 2 are attempted in order. Proven continuous or integer reserve infeasibility triggers the next level; at level 2, stable breadth expansion may continue within the same deadline but must stop before a full-domain fallback.

The restricted repair retains the exact original objective and constraints. Guide and coverage information is used only as a nonbinding MIP start. Standalone mode accepts the first repair incumbent and reserves time for validation. Every reported UB equals original first-stage cost plus `GlobalRecourseOracle` recourse and must pass the independent checker and common evaluator.

Standalone failure returns diagnostics and no UB. It does not invoke candidate-v1 BBC fallback.
