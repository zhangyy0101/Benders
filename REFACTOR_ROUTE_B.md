# Route B：True BBC + ALNS + 贝位级联合属性集中度

## 核心目标

核心目标同时包含 open-bay-time、joint-group bay concentration、distance、L1
workload balance 和 outbound conflict。旧的 attribute refinement、POD spread、
weight spread、height mix，以及箱区级 excess-block 指标均已删除。

每个 group 联合编码 size、POD、height、weight class。高度仍属于联合分组属性，
但不再单独惩罚同一贝位内不同高度。

## 贝位级集中度

只在最终时段、只对箱型兼容且剩余容量为正的组合创建：

```text
u[j,g,i] = 1  当 ship j 的 joint group g 使用 bay i
alloc[i,j,g,final] <= M[j,g,i] u[j,g,i]
u[j,g,i] <= x[i,j,final]
```

整数 allocation 下还有 `alloc >= u`，因此 binary 与正 allocation support 完全
一致。tight Big-M 为：

```text
M[j,g,i] = min(required_final[j,g], remaining_capacity[i,final])
```

直接定义：

```text
C_raw   = sum_(j,g,i) u[j,g,i]
C_scale = max(1, 所有可行 (j,g,i) 组合数)
C_norm  = C_raw / C_scale
```

不再计算 minimum usage，也不再最小化 usage 与 minimum 的差。指标的业务含义是
“联合属性组占用的 ship–group–bay 总数”，其中包含容量导致的必要贝位占用。

## Benders 一致性

Concentration binary 位于 master，不进入 global recourse：

```text
Master = weighted_open + weighted_concentration + eta
Q      = weighted_distance + weighted_balance + weighted_conflict
UB     = open + concentration + exact Q(x,alloc)
LB     = master.ObjBound
```

aggregate/analytic relaxation 仍只下界 Q。callback 从 alloc 重建全部 bay-level u，
与 x、alloc、`eta=Q` 一起提交。direct、monolithic、ALNS、BBC exact UB 和独立
solution checker 共用 `model_concentration.py` 中的同一套计算。

## ALNS

Concentration destroy 找到使用贝位最多的 `(j,g)`，释放该 group 当前使用贝位上
对应 ship 的 x 与 allocation 时间轴，让 repair 有机会将其搬到更少贝位。该
operator 参与 adaptive roulette 统计，不是 random fallback。

## 可用性与规模

只有显式完整提供 POD、height、weight class 的联合 group 才启用。BAPTBI 和
Barcelona 公开适配器返回 `NOT_APPLICABLE`，raw 为 null、cost 为 0。

`tiny_concentration` 有 2 个 group、3 个兼容贝位/组，共 6 个 u。3new6old 在典型
50/50 箱型模式下约创建 900 个 u，而原箱区级模型为 180 个，因此求解时间可能
增加，但业务粒度更精确。

## 运行

```bash
python -m pytest -q
python main.py --instance tiny_concentration --total-core-time 20 --concentration-mode joint-group-bay --concentration-weight 10 --mip-gap 0
python solve_direct_gurobi.py --instance tiny_concentration --time 20 --concentration-mode joint-group-bay --concentration-weight 10 --mip-gap 0
python main.py --instance 3new6old --total-core-time 180 --concentration-weight 10
python run_experiments.py --instances 3new6old --total-core-time 60 --suite concentration
```

论文的算法对比应同时报告裸 `Direct`、共享同一 warm/ALNS 的 `Direct+ALNS` 和
`BBC+ALNS`。`solve_direct_alns_pipeline` 默认把总预算的 15%/25%/60% 分给
warm、ALNS、monolithic main；BBC 使用 5%/15%/25%/55% 分给 root、warm、
ALNS、BBC main。二者复用完全相同的 warm-start 函数和 ALNS 实现。

ALNS 的 destroy 单元是完整 `(bay,ship)` trajectory；interval 只释放时间后缀，
其余 operator 释放全轨迹，并同时开放高成本 source 与评分更优的 destination。
repair 时间随实际释放的 x/alloc 比例自适应。main BBC 默认关闭 MIPNODE cuts，
但保留所有 MIPSOL lazy cuts；重复整数 master point 使用 exact recourse cache。

权重敏感性使用 0、2、5、10、20，并应采用多 seed、统一充分预算。由于目标已从
block excess 改为直接 bay usage，旧实验数值不可与新指标直接比较。
