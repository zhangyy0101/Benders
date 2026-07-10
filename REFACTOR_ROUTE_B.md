# Route B：True Branch-and-Benders-Cut + ALNS

## 为什么旧版本不能称为 True BBC

旧 master 已包含 `in_share/in_total/g_bal` 以及 distance、balance、conflict，同时 per-ship SP 又重复部分动态流约束；它没有 `eta` 和真实 recourse optimality cut，并在 Farkas 构造失败时退回 x-only no-good。这样的结构无法证明 master bound 是完整 core objective 的 LB，也不能处理跨船 L1 average 耦合。

## 新 Master

`model_master.py` 只包含：

```text
x[i,j,n]                 binary
alloc_boxes[i,j,g,n]     integer/continuous
block_use[j,k,n]         binary
eta                      continuous, eta >= 0
```

目标严格为：

```text
min open_bay_cost(x) + eta
```

master 保留 fixed mode、bay reserve capacity、alloc/x 双向连接、allocation 与 activation 时间单调性、block-use links、累计全 yard reserve 下界以及 per-size necessary handling inequalities。master 不含 `din/inv/in_share/in_total/avg/g_bal`，也不含 distance/balance/conflict。

## Global Recourse LP

`GlobalRecourseOracle` 是单一全局 LP，不按 ship 拆分。变量为 `din/inv/in_share/in_total/avg/g_bal`；它包含 arrival conservation、inventory balance、storage/handling coupling、block aggregation、fixed inbound、global average 和 L1 linearization。

recourse 唯一承担：

```text
distance + L1 workload balance + outbound conflict
```

handling RHS 为 `Bay_Handling_Rate × duration × x_hat`，单位 boxes；storage coupling 为 `Alpha × inv <= alloc_hat`。50 boxes/hour 是 `model_calibration`，不是公开数据。

oracle 只构造一次，callback 中只更新 linking RHS，使用 dual simplex (`Method=1`) 保留 basis。统计 solve/optimal/infeasible 次数和总/平均/最大时间。

## Optimality cut 与 dual 符号

对所有 RHS linking constraints，Gurobi 最小化 LP 的 `<=` 行 dual 满足 `Pi <= 0`。令 `a(y)` 为由 master point 决定的 RHS，则：

```text
eta >= Q(y_hat) + sum_r Pi_r [a_r(y) - a_r(y_hat)]
```

代码在每次生成时检查 cut 在 `y_hat`、`eta=Q(y_hat)` 处误差不超过 `1e-5`。测试还在另一可行点验证 cut RHS 不超过真实 `Q`。distance/balance/conflict 只出现于 SP，因此不存在 double counting。

## Farkas feasibility cut

SP infeasible 时，对所有行（包括 arrival、initial inventory、fixed inbound 等 constant RHS）读取 `FarkasDual`，构造完整 affine certificate。生成点必须严格违反，已知可行点必须被保留。cut 同时允许包含 x 与 alloc 系数；代码没有 x-only no-good fallback。certificate 构造失败会写出 LP、终止 master 并抛出日志化异常。

## Root prepass、callback 与 cut pool

Phase 0 反复求 master LP、调用 global oracle、添加 optimality/Farkas cut，直到 violation 收敛、迭代上限或时间上限。Phase 1 在 MIPSOL 添加 lazy cuts，在 optimal MIPNODE 添加 user cuts。node cut budget 只限制 MIPNODE，不影响 MIPSOL correctness。

`BendersCutRecord` 保存 constant、eta/x/alloc coefficients、origin、violation 和 coefficient signature；`BendersCutPool` 去重。Phase 3 重建 master 后加载 Phase 1 全部 unique cuts，并注入 ALNS solution 作为 MIP start。

## UB、LB 和 gap

UB 只来自 SP-optimal incumbent：

```text
exact UB = exact open cost + exact global SP objective
```

master incumbent `open+eta` 不被当作 exact UB。LB 为包含全部有效 cuts 的 `master.ObjBound`。ALNS 和 refinement bound 均不进入 LB：

```text
gap = (best_exact_ub - best_master_lb) / abs(best_exact_ub)
```

## ALNS 与 refinement

BBC 负责 global LB 和 exact search；ALNS 使用完整 `model_monolithic.py` repair，只改善 primal UB。Phase 3 继承 cut pool。属性目标后置为完整 monolithic ε-constraint refinement，core-best 与 refined solution 分开保存，refinement 不修改 BBC gap。

## Direct baseline

`solve_direct_gurobi.py`、ALNS repair 与 refinement 共享 `model_monolithic.py`。direct 与 BBC 使用同一 data、scales、handling rate、allocation domain 和 core objective。tiny 的 direct optimum 用于验证 cut、UB/LB 和 BBC optimum。

## 运行

```bash
python -m pytest -q
python -u main.py --instance tiny --phase1-time 10 --lns-time 5 --phase3-time 10 --root-cut-time 5 --attribute-time 5
python solve_direct_gurobi.py --instance tiny --time 10 --mip-gap 0
python run_experiments.py --instances tiny --seeds 0 1 --time 3 --suite full
```

## 已验证结果

- tiny direct：UB=LB=16000。
- tiny BBC：UB=LB=16000；正 recourse=12000。
- tiny root prepass：bound 4000 → 16000，4 条 root cuts。
- 无 root prepass：1 条 initial optimality cut、2 条 incumbent optimality cuts。
- Phase 3 在 tiny 中继承 5 条 unique cuts。
- zero-capacity SP 的 Farkas cut 在生成点违反 8，在已知可行点裕量 192，且包含 alloc coefficients。

3new6old 的 10/5/10 秒 smoke test：Phase 1 UB=21571.029743、LB=842.133333；ALNS 将 UB 改善 2314.133065 到 19256.896678；Phase 3 LB=843.155556，最终 gap=95.6215%。Phase 3 继承 16 条 cuts、新增 11 条，总 unique cuts=27。短预算 gap 较大，不能解释为算法最终质量。

## 已知限制

大实例 callback 会频繁调用全局 LP，短预算主要验证数学正确性而非收敛性能。当前默认不缓存 fractional points，避免粗 rounding 导致无效 dual cut。公开 benchmark 的属性字段有限，属性实验需要明确的数据来源。任何 Farkas failure 都会终止并留下诊断文件，不会静默添加未经证明的 cut。
