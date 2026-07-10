# Route B：强化 True Branch-and-Benders-Cut + 自适应 ALNS

## 数学结构

Master 仅保留 `x[i,j,n]`、`alloc_boxes[i,j,g,n]` 与 `eta`，目标为
`open_cost(x) + eta`。默认不再创建冗余的 block binary。整数分配采用
`ceil(Alpha * cumulative_arrival)`，连续分配采用精确实数等式；master 与
monolithic 共用同一组必要 handling/capacity 有效不等式。

Global recourse LP 仍独立包含 `din/inv/in_share/in_total/avg/g_bal`，并完整承担
distance、L1 workload balance 与 outbound conflict。因而这仍是真正的 Benders
分解，不是把完整 recourse 搬回 master。

## 解决弱下界

`model_aggregate_recourse_lb.py` 在 master 中加入合法的 size-level 投影松弛：

```text
sum_k z[j,k,s,n] = arrival[j,s,n]
Alpha*z[j,k,s,n] <= aggregate same-period handling capacity
Alpha*sum_{t<=n} z[j,k,s,t] <= aggregate cumulative allocated storage
eta >= weighted_distance(z) + weighted_L1_balance(z) + weighted_conflict(z)
```

任何真实 SP 可行解均可投影为该松弛的可行解，所以其目标不会超过真实 recourse
最优值。此外还有可单独消融的 distance、balance、conflict 解析下界。summary
分别记录 root 的 open、eta、aggregate 及三个目标分量。

tiny 的强化 root 为：

```text
open = 4,000
eta = aggregate = 12,000
LB = 16,000
```

无需依赖多轮 cuts 即已达到真实最优值。3new6old 的短测 root 从旧版本约 843
提高到 15,647.842，其中 open=842.133、eta=14,805.709；因此原 95% gap 的
主因（`eta≈0`）已经消除。

## Cuts 与数值策略

Optimality cut 使用全局 LP 对 master linking RHS 的对偶次梯度，并在生成点检查
紧性。Farkas cut 固定采用 Gurobi certificate 的统一方向
`constant + xcoef*x + alloccoef*alloc >= 0`，方向不再根据当前点临时翻转。
`cut_validation.py` 可独立检查 cut。

root prepass 根据相对 LB 改善、violation、stall、迭代数和时间自适应停止。
主流程只运行一个正式 BBC；root、warm start、ALNS 和 main BBC 从同一个
`total_core_time` 分配预算。节点分离支持 root-only、periodic、adaptive，并限制
callback 时间占比。`stabilized` 策略在 node point 与 core point 的凸组合处求合法
次梯度（不是 Magnanti-Wong cut）。

## UB、ALNS 与属性优化

UB 只接受独立 `solution_validation.py` 检查通过且由 exact global recourse 评价的
解。LB 只取 Benders master bound，gap 使用同一 core objective。

ALNS 持久复用一个 repair model，真实执行 random/active/block/interval/ship/
conflict/distance destroy，roulette 权重依据 accepted、improved、best-improved
反馈更新，并支持 destroy fraction 调节与停滞重启。属性 refinement 按库存而非
累计流量构造指标，使用剩余容量 Big-M；缺少属性字段时明确返回
`NOT_APPLICABLE`，且 refinement 永不改变 core gap。

公开适配数据的合成 outbound 会显式裁剪到可用初始库存，并记录
`inferred_outbound_clipped_boxes`；用户提供与核心实例仍执行严格的容量和残余
出库校验。release policy 可选 proportional、legacy_sorted、conservative。

## 运行与公平实验

```bash
python -m pytest -q
python main.py --instance tiny --total-core-time 10 --mip-gap 0
python main.py --instance 3new6old --total-core-time 60 --cut-strategy stabilized
python solve_direct_gurobi.py --instance tiny --time 10 --mip-gap 0
python run_experiments.py --instances tiny 3new6old --total-core-time 60 --suite full
```

实验脚本对 direct、weak、analytic、aggregate、aggregate+stabilized 使用完全相同
的核心 wall-clock budget，并输出 UB/LB/gap、root 分解、各类 cut、SP 次数与耗时、
callback 占比、ALNS 改善及 anytime trace。属性 refinement 时间独立记录，不混入
核心算法公平预算。

## 当前验证

- 35 项测试通过，包括聚合下界有效性、tiny 最优值、精确 reserve、独立解检查、
  Farkas/optimality cuts、ALNS 状态与全部公开数据适配器。
- tiny：BBC 与 direct 均为 UB=LB=16,000。
- 3new6old 20 秒诊断：强化 root LB=15,647.842；同预算 direct LB=15,665.028。
  该极短预算尚未找到可行整数 incumbent，因此不能报告 gap；应使用 60 秒或更长
  的统一预算完成论文表格，不能把“无 incumbent”伪装为收敛结果。
