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
16. A continuing vessel's outbound forecast uses visible actual inventory plus
    its remaining current arrival forecast. The nominal outbound rate is a
    public per-vessel, per-6-hour planning parameter.
17. Planned operation duration is the maximum of a public class duration and a
    public-booking-volume duration. Planned release remains external to hidden
    realization volume.
18. Initial synthetic inventory may fill each bay up to 95%. If the rounded
    requested total exceeds that physical limit, generation fails explicitly.
19. Realized peak utilization, utilization deviation, support activation, and
    bay concentration are sampled after every executed 6-hour period rather
    than inferred only from the cycle-end state.
