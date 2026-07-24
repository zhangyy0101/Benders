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
13. Synthetic experiments create a public booking baseline, one hidden final
    truth, and a temporally correlated noisy forecast trajectory around that
    truth. Forecast uncertainty declines with lead time.
14. Using hidden truth to generate offline simulated observations is permitted;
    the optimization snapshot contains only the current forecast and never
    contains truth or truth-based error diagnostics.
15. Current actual inventory is observed operational state and is visible to
    optimization; future realized arrivals and realized release delays are not.
16. An outbound-relevant vessel has ETA before the current look-ahead end and a
    planned release after now. This includes receiving vessels whose ETA falls
    inside the horizon and loading-phase vessels that have already reached ETA.
17. An outbound-relevant vessel's forecast uses visible actual inventory plus
    its remaining current arrival forecast. It does not use true flow, true
    total, realized outbound flow, or realized release time.
18. Planned outbound workload and capacity release are separate concepts. The
    workload profile is generated over the complete `[ETA, planned release)`
    interval and may vary by period; past or out-of-horizon periods are then
    truncated without redistributing their quantity.
19. A changing outbound workload profile does not imply progressive capacity
    release. Inventory capacity remains occupied until the vessel's whole
    planned release in optimization or realized release in simulation.
20. The nominal outbound rate is a public per-vessel, per-6-hour planning
    parameter.
21. Planned operation duration is the maximum of a public class duration and a
    public-booking-volume duration. Planned release remains external to hidden
    realization volume.
22. Initial synthetic inventory may fill each bay up to 95%. If the rounded
    requested total exceeds that physical limit, generation fails explicitly.
23. Realized peak utilization, utilization deviation, support activation, and
    bay concentration are sampled after every executed 6-hour period rather
    than inferred only from the cycle-end state.
24. Oracle-certified experiments separate vessel-admission cycles from three
    terminal execution cycles. No new vessel is admitted in the terminal
    cycles; they execute the complete receiving tails of already admitted
    vessels and remove right-censoring from realized arrival metrics.
25. The full-information integer packing oracle is used only for offline
    instance certification. Its true-flow and realized-release inputs are not
    exposed to any rolling optimization method.
