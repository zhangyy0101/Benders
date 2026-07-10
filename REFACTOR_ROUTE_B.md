# Route B：True BBC + ALNS + 联合属性集中度

## 核心目标

当前核心目标同时优化 open-bay-time、joint group concentration、distance、L1
workload balance 和 outbound conflict。旧的 ε-constrained attribute refinement、
POD spread、weight spread 与 bay-level height mix 已全部删除。高度仍属于 group 的
联合属性，但不再单独惩罚同一 bay 内不同高度。

一个 group 同时编码 size、POD、height、weight class。对最终时段定义
`u[j,g,k]=1` 表示 ship–group 在 block 中有正预留量。binary 只在 master 与
monolithic 中建立，不进入 global recourse，因此 recourse 仍是纯 LP，原有
optimality/Farkas cuts 仍只包含 x、alloc 和 eta。

## 集中度数学定义

对正需求 `(j,g)`：

```text
block_alloc[j,g,k] <= M[j,g,k] u[j,g,k]
sum_k M[j,g,k] u[j,g,k] >= required_final[j,g]
sum_k u[j,g,k] >= L[j,g]
```

整数 allocation 还使用合法的 `block_alloc >= u`，保证保存的 binary 与 support
完全一致。tight Big-M 为：

```text
M[j,g,k] = min(required_final[j,g],
               compatible remaining capacity in block k)
```

`L[j,g]` 是按 M 降序累加至 required demand 所需的最少 block 数。指标为：

```text
C_raw   = sum_(j,g) (sum_k u[j,g,k] - L[j,g])
C_scale = max(1, sum_(j,g) (B[j,g] - L[j,g]))
C_norm  = C_raw / C_scale
```

因此 raw=0 表示每个 group 都达到容量条件下的最低 block 数，而不是错误地惩罚
不可避免的分散。统一实现位于 `model_concentration.py`，master、monolithic、
direct、ALNS、BBC exact UB 与 solution checker 均调用同一 evaluator。

## Benders 目标一致性

```text
Master objective = weighted_open + weighted_concentration + eta
Recourse Q        = weighted_distance + weighted_balance + weighted_conflict
Exact UB          = open + concentration + exact Q(x,alloc)
LB                = master.ObjBound
```

aggregate/analytic lower bound 仍只下界 Q，不包含 concentration。callback 从 alloc
重建 concentration binaries，与 x、alloc、`eta=Q` 一起提交。summary 分别输出
root open、concentration、eta 和 aggregate recourse。

## ALNS

ALNS repair 使用完整 monolithic 核心目标，所有 start/candidate/best UB 均包含
concentration。新增 concentration destroy：选取 excess spread 最大的 `(j,g)`，
释放其已使用 blocks 上对应 ship 的 x 与 allocation 时间轴。该 operator 参与与
其他 operators 相同的 roulette 权重更新。

## 数据可用性

只有显式完整提供 POD、height、weight class 联合 group 的实例启用集中度。
BAPTBI/Barcelona 公开适配器返回 `NOT_APPLICABLE`；其 concentration raw 为 null、
cost 为 0，不能解释为“完美集中”。`tiny_concentration` 是三 block 专项 fixture。

## 运行

```bash
python -m pytest -q
python main.py --instance tiny_concentration --total-core-time 20 --concentration --concentration-weight 10 --mip-gap 0
python solve_direct_gurobi.py --instance tiny_concentration --time 20 --concentration --concentration-weight 10 --mip-gap 0
python main.py --instance 3new6old --total-core-time 180 --concentration-weight 10
python run_experiments.py --instances 3new6old --seeds 0 1 2 --total-core-time 60 --suite concentration
```

`--suite concentration` 运行权重 0、2、5、10、20。短预算结果不可用于声称
单调 trade-off 或选择最终权重；论文应使用多 seed、足够预算，并依据 elbow、
运营偏好与稳定性选择默认值。

## 当前验证结果

- 44 项测试通过。
- tiny_concentration：direct=BBC=16000，gap=0，raw excess=0，used/minimum=2/2。
- 3new6old，weight=10，180 秒：UB=18357.506827，LB=15889.448680，
  gap=13.4444%；open=1133.333333，concentration=2345.679012，
  distance=6857.636474，balance=519.722327，conflict=7501.135681；
  raw excess=38，used/minimum=56/18。
- 该次 ALNS 将 18453.331701 改善至 18441.740792；concentration operator 被真实
  使用并接受一次。60 秒 BBC 未找到 exact incumbent，说明加入 180 个 first-stage
  concentration binaries 后需要更长预算。
- 单 seed、30 秒权重敏感性保存在 `experiments_joint_sensitivity`；结果尚未收敛，
  raw 并非单调，不能作为业务权重结论。
