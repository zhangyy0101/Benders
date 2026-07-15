# paper-exp-v1 实验协议

本文件冻结当前代码的问题与评价口径。公式以 `model_common.py`、`model_master.py`、
`model_monolithic.py`、`model_concentration.py` 和 `model_recourse.py` 为准。

> Problem protocol: `paper-exp-v1`（fixed）。Algorithm status: `provisional`。
> 本协议不把当前 full BBC、warm start、ALNS、root/lower-bound strengthening、
> node cuts、cut strategy 或时间占比声明为最终算法；候选配置及其评估状态见
> `ALGORITHM_CONFIGURATION_SCHEMA.md`。

## 1. Problem scope

模型在贝位（bay）层级为新出口箱安排储存预留和入场流。新箱以船舶 `j` 和联合箱组
`g` 区分；联合箱组由 size、POD、height、weight class 共同定义。时间被离散为有
明确起止和小时数的 period。旧箱初始库存、固定入场流会占用物理容量；旧箱出场量
形成与新箱分配相关的冲突压力。

`alloc_boxes[i,j,g,n]` 是截至时期 `n` 为某船某组在贝位预留的累计容量，不是该时期
实际到场量；实际入场和库存分别由 `din` 与 `inv` 表示。当前模型不描述场桥路径、
箱位/层高、翻箱序列、车辆调度、潮汐、泊位计划优化或新箱离场过程。不同船可以共用
同一贝位，只受合计容量约束；装卸能力约束目前按 `(bay, ship, period)` 分别计算，
不是跨船共享的总能力约束。

`3new6old` 是代码生成的 synthetic legacy/reference 实例，不是真实公开港口数据。

## 2. Sets, indices and units

| 记号/代码 | 含义 | 单位 |
|---|---|---|
| `K` / `k` | 箱区集合 | — |
| `I_list` / `i` | 贝位集合，`Bays_in_Block[k]` 给出所属箱区 | — |
| `J_new` / `j` | 新出口船舶 | — |
| `J_old` | 旧库存关联船舶 | — |
| `S` / `s` | 箱型，当前用 20/40 ft 标签 | ft（类别） |
| `G` / `g` | size–POD–height–weight class 联合组 | — |
| `N` / `n` | 连续整数时期 | — |
| `Intervals[n].dur` | 时期长度 | hour |
| `I[i].cap`、所有 flow/inventory/allocation | 箱量 | boxes |
| `Bay_Handling_Rate[i,n]` | 装卸率 | boxes/hour |
| `Dist[j,k]` | 船舶泊位至箱区距离 | 当前数据的距离单位；`3new6old` 元数据为 meter |
| `Alpha` | 库容/处理需求放大系数 | dimensionless |

## 3. Decision variables

Monolithic 模型包含：二元 `x[i,j,n]`（船舶是否使用贝位）、非负整数（或显式选择
continuous 时连续）`alloc_boxes[i,j,g,n]`、非负 `din[j,g,i,n]`、`inv[j,g,i,n]`、
`in_share[j,k,g,n]`、`in_total[k,n]`、`avg[n]` 和 `g_bal[k,n]`。启用集中性时，二元
`joint_group_bay_use[j,g,i]` 表示最终时期该 ship-group 是否使用贝位。

Benders master 只含 `x`、`alloc_boxes`、`joint_group_bay_use` 和非负 `eta`；`eta` 是
recourse 目标的下界。Global recourse LP 含 `din`、`inv`、`in_share`、`in_total`、
`avg`、`g_bal`，其 RHS 由 master 点的 `x` 和 `alloc_boxes` 决定。

## 4. Constraints

令 `R[i,n]` 为 `simulate_old_inventory` 得到的旧箱占用后的剩余容量，`A[j,g,n]`
为到达量，`d[n]` 为时长，`alpha=Alpha`。

- `bay_capacity`: `sum_(j,g) alloc[i,j,g,n] <= R[i,n]`。
- `alloc_x`: `sum_g alloc[i,j,g,n] <= R[i,n] x[i,j,n]`；`x_alloc`:
  `x[i,j,n] <= sum_g alloc[i,j,g,n]`。
- `alloc_mono`: `alloc[i,j,g,n] >= alloc[i,j,g,n-1]`。
- `mode`: 与 `Fixed_Bay_Mode[i]` 箱型不兼容的组在该贝位 allocation 为 0。
- `exact_reserve`: `sum_i alloc[i,j,g,n] = sum_(t<=n) A[j,g,t]`；V2 中
  `alloc_boxes` 是整数箱位数，`Alpha` 不再进入模型。
- `arrival`: `sum_i din[j,g,i,n] = A[j,g,n]`。
- `inventory`: `inv[n] = inv[n-1] + din[n]`，初值来自
  `initial_inventory_data[(i,j,g)]`（新船通常为 0）。
- `storage_link`: `inv[j,g,i,n] <= alloc[i,j,g,n]`。
- `handling_link`: `sum_g din[j,g,i,n] <= rate[i,n] d[n] x[i,j,n]`。
- `share`: `in_share[j,k,g,n] = sum_(i in k) din[j,g,i,n]`。
- `total`: `in_total[k,n] = fixed_in_block[k,n] + sum_(j,g) in_share[j,k,g,n]`；
  `avg` 是箱区均值，`g_bal >= |in_total-avg|`，形成 L1 平衡项。
- `concentration_link`: 最终期 `alloc <= M u`，其中
  `M=min(required_final, R[i,final])`；整数 allocation 另有 `alloc >= u`，并有
  `u <= x[i,j,final]`。
- `simulate_old_inventory`: 每期先加入 `Fixed_In_Flow`，再按选定 release policy
  扣减 `Block_Outbound_Req`；不可服务出场量或容量超限会由数据验证拒绝，不会剪裁。

标准配置还启用 `add_common_master_valid_inequalities`；它们强化模型但不改变可行域。

## 5. Objective

每项 weighted component 均为 `objective_scale * weight * raw / scale`，默认
`objective_scale=1000`。

| 项 | raw | normalization scale | weight |
|---|---|---|---:|
| open | `sum x[i,j,n] d[n]` | `max(1, |I||J| sum d[n])` | 8 |
| concentration | 最终期 `sum u[j,g,i]` | `max(1, 可行 (j,g,i) 组合数)` | 10 |
| distance | `sum Dist[j,k] in_share[j,k,g,n]` | `max(1, max(Dist) * total arrivals)` | 16 |
| balance | `sum g_bal[k,n]` | `max(1, |K||N| * max period arrivals)` | 24 |
| conflict | `sum pressure[k,n] in_share[j,k,g,n]` | `max(1, max pressure * total arrivals)` | 42 |

`pressure[k,n] = outbound[k,n] + 0.5 outbound[k,n-1] + 0.5 outbound[k,n+1]`
（边界缺项为 0）。集中性 scale 是所有有正最终需求且容量兼容的 `(ship,group,bay)`
组合数，不是理论最少贝位数，也不减去任何 minimum usage。

## 6. Benders decomposition

```text
Master objective = weighted open + weighted concentration + eta
Recourse Q        = weighted distance + weighted balance + weighted conflict
UB                = exact first-stage cost + exact global recourse Q
LB                = Benders master bound
```

aggregate recourse relaxation 和 analytic lower bound 仅强化 `eta` 的 recourse 下界，
不参与精确 UB 的计算。Lazy optimality/feasibility cuts 来自同一个 global recourse LP。

## 7. Fixed problem defaults and provisional algorithm settings

本节中 allocation domain、数据准备参数、目标、归一化与 concentration mode 属于
fixed problem/evaluation protocol。MIP gap、threads、seed、算法开关、ALNS 参数和
phase shares 仅是 **provisional candidate defaults**，不得解释为最终论文算法。

机器可读值见 `paper_exp_v1_defaults.json`。fixed defaults 是 integer allocation、
handling scale 1.0、proportional old-outbound release 与 joint-group-bay concentration。
当前候选配置的 gap 0.03、threads 1、基准 seed 0 均为 provisional。集中性仅在属性
完整、group arrivals 完整、开关开启且权重大于 0 时启用。

主合成设置的 time bucket 为 6 hours；tiny/tiny_concentration 是 1-hour 测试夹具，
不属于正式 benchmark。`Alpha` 是实例输入：`3new6old=1.1`，tiny fixtures=1.0；未来
固定 benchmark 必须随实例 digest 记录，最终 benchmark 的 Alpha 属于 **TO BE
CALIBRATED**。

BBC+ALNS 总 wall-clock 预算默认分为 root/warm/ALNS/main = 5%/15%/25%/55%。
Direct+ALNS 为 warm/ALNS/main = 15%/25%/60%。构建、启发式和求解均计入同一 pipeline
wall-clock deadline。正式总预算、实例规模、seed 数量属于 **TO BE CALIBRATED**；
当前 CLI 的 30/60/180 秒默认值是运行入口默认值，不代表论文最终预算。

## 8. Algorithm comparison rules

- 所有方法读取同一固定实例文件/digest，使用相同 prepare 参数、权重、总 wall-clock、
  threads、allocation domain、集中性口径和 independent feasibility checker。
- stochastic 方法使用相同 seed 集；确定性方法也记录 seed。运行顺序与机器信息需记录。
- 不跨论文机器直接比较 CPU/wall time；主要报告同机 wall-clock。
- 有 LB 的方法报告 UB/LB/gap；无 LB 的 heuristic 对同一 BKS 报告 RPD。
- 异常、无可行 incumbent、TIME_LIMIT、未证明最优必须分别记录；TIME_LIMIT 不得标为
  OPTIMAL。任何作为 UB 的解都必须通过 checker。

## 9. Required result metrics

求解指标至少包括 status、termination、wall-clock、各阶段时间、UB、LB、gap、nodes、
cuts、SP solves、cache、first/best feasible time 和 solution source。目标需报告总值以及
五项 raw、normalized、weighted component。业务 KPI 至少包括到达量、open-bay hours、
ship-group 贝位使用、单位箱距离、workload L1/CV、conflict exposure、reserved/physical
utilization。业务 KPI 的 canonical 实现由 Task 03 完成；本协议不预先伪造数值。

## 10. Versioning rule

模型业务含义、约束、权重、归一化或数据 schema 任一改变，都必须提升 protocol
version。已生成 benchmark 不得静默覆盖；schema/generator 变化需迁移或生成新版本。
正式实验的每个结果必须记录 protocol version、instance digest、Git commit 和 dirty
状态。
# Pilot2 experiment extension

All methods expose `anytime_trace` records with `time`, `phase`, `source`, `ub`, `lb`, and `gap`. Time is measured from pipeline start; best UB cannot increase and valid LB cannot decrease. Gap integration excludes intervals missing either bound. Primal integrals are post-processed after the same-instance best known solution is available.

Paired ablations match exactly on instance, seed, budget, threads, and problem protocol. Seeds are 0, 1, and 2. Missing pairs are reported and are never replaced by unpaired configuration medians.

Direct records MIPSOL incumbents and significant MIP bounds. BBC records completed root LP bounds, warm/ALNS incumbents, exact-recourse MIPSOL upper bounds, and valid main-master bounds. ALNS and Classical Benders expose their meaningful iteration events on the same pipeline-relative time axis. Post-processing derives `time_to_first_feasible`, `time_to_best`, `primal_integral`, and `gap_integral`; the primal reference is the same-instance BKS, while gap integration excludes intervals lacking either valid bound.
