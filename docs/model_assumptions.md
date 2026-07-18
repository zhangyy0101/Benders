# Model assumptions

1. The decision is bay-level allocation and capacity reservation. It is not an
   exact row/tier/stack slot assignment.
2. Bays are pre-classified for 20-foot or 40-foot container resources.
3. One bay cannot contain standard- and high-cube groups during the same period.
4. A vessel's allocation is released as a whole at its external completion
   period; progressive box-by-box loading release is not represented.
5. Exact loading sequence and partial loading release are outside scope.
6. Container relocation, remarshalling, and prestacking are not modeled.
7. Realized inbound inventory is immutable until vessel release.
8. Arrival and outbound forecasts are external inputs rather than decisions.
9. The optimizer cannot observe hidden future realized arrivals or hidden
   realized schedule delays.
10. Same-block inbound/outbound overlap is a proxy for operation interference,
    not a detailed equipment-scheduling model.
11. Block balance measures inventory occupancy utilization, not equipment
    workload.
12. Realized release delays can be simulated, while planning continues to use
    the external planned release schedule.
13. In synthetic experiments, forecasts and hidden realized arrivals are
    separate reproducible draws from a public booking baseline; a zero-error
    scenario may make them equal by design, but forecast construction never
    reads the hidden realization.
