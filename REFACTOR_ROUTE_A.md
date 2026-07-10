# Route A：Strengthened MIP–ALNS 后续正确性说明

## 1. 统一单体模型

`model_core.build_core_monolithic_model()` 是 Phase 1、ALNS repair、Phase 3、attribute refinement 和 direct Gurobi baseline 的唯一模型构造器。核心变量为 `alloc_boxes`、`x`、`block_use`、`din`、`inv`、`in_share`、`in_total`、`avg` 和 `g_bal`。旧分解求解代码已删除。

核心目标只包含 open-bay-time、berth-to-block distance、L1 workload balance 和 outbound conflict。`evaluate_core_solution()` 从 solution 字典独立重算目标；求解器目标与重算值误差超过 `1e-5` 时立即报错。

## 2. Reserve conservation

`alloc_boxes` 表示必要空间预留，不再允许无成本过度预留。令截至时段 `n` 的累计到达量为 `A[j,g,n]`：

- integer domain：`required_reserve = ceil(Alpha × A - tolerance)`；
- continuous domain：`required_reserve = Alpha × A`。

模型强制：

```text
sum_i alloc_boxes[i,j,g,n] = required_reserve[j,g,n]
```

这减少了退化和对称性，也使不同 seed 下的 allocation 更稳定。

## 3. Inventory-based attribute refinement

论文默认使用：

```text
--attribute-basis inventory
```

POD spread、weight spread 和 height mix 均由实际累计库存 `inv[j,g,i,n]` 定义，而不是 reservation。POD/weight helper 的 Big-M 为：

```text
min(cumulative actual demand,
    sum remaining_capacity / Alpha)
```

bay-height helper 使用 `remaining_capacity / Alpha`。可选 `reservation` 模式仅用于消融；其 Big-M 使用 `Alpha × cumulative demand`，summary 会明确记录 basis。

属性尺度由 `attribute_scales(data, scope)` 统一提供。`final` 的 period count 为 1，`horizon` 为 `len(N)`；模型目标、起点重算、候选重算和 CSV 使用完全相同的尺度。CLI 为：

```text
--attribute-scope final|horizon
--attribute-basis inventory|reservation
```

没有显式 group 属性的 BAPTBI/Barcelona 实例返回 `attribute_refinement.status = NOT_APPLICABLE`，不会把 0 分解释为完美布局。当前代码没有为公开数据伪造 POD、weight 或 height。

## 4. 旧箱动态库存与释放策略

`simulate_old_inventory()` 独立模拟 initial inventory、fixed inbound 和 old outbound，并报告未满足 outbound 与容量违反。数据验证拒绝任何超容、未满足 outbound、grouped-arrival 不一致、缺字段或非连续 period id。

block-level outbound 没有公开的 bay-level 释放位置，因此策略必须显式选择：

- `proportional`（默认）：按同一 block、old ship 的 bay 库存比例释放；
- `conservative`：验证 outbound 数量，但不提前把推断释放量作为新箱可用容量；
- `legacy_sorted`：按 bay 名称顺序释放，仅用于复现旧结果。

若实例提供 `Old_Outbound_By_Bay[(i,j,s,n)]`，则优先使用真实 bay-level 数据。公开 adapter 不声称原数据提供了该字段。

## 5. 独立可行性检查

`solution_validation.validate_core_solution()` 不依赖 Gurobi，检查 arrival、inventory balance/nonnegativity、inventory–allocation、storage、handling、bay mode、activation、block flow/use、in-total、average、L1 auxiliary、时间单调性、整数残差和 exact reserve equality。

Phase 1、每个 ALNS repair、Phase 3、direct baseline 和 refinement candidate 只有在 `feasible=true` 后才可成为 UB。summary 和 CSV 保存 `max_solution_violation`。

## 6. ALNS、证明阶段与诊断

ALNS 保留七类 operator，并支持 repair time/gap、destroy 范围、stall threshold、minimum iterations、restart、temperature 和 cooling rate。无改善时逐步扩大 destroy fraction，改善后缩小；达到 stall threshold 时从 best solution restart。所有 operator 即使使用次数为 0 也出现在 summary。

Phase 1 和 Phase 3 的完整模型 bound 才能作为全局 LB；repair/refinement bound 不参与 core gap。root callback 单独记录 `root_relaxation_bound`，最终 `ObjBound` 记录为 `final_global_bound`，两者不会混用。

handling diagnostics 输出最大/平均 active utilization、binding handling constraints 和 active bay 数。默认 50 boxes/hour/bay 是 `model_calibration`，不是公开数据或现场测量值。实验 sensitivity 使用 0.25、0.5、1.0 和 1.5 scale。

## 7. Symmetry breaking

仅对 block、size mode、remaining-capacity profile 和 handling-rate profile 完全相同的 bays 分组。安全约束按所有新船的总 activation 排序：

```text
sum_j x[left,j,n] >= sum_j x[right,j,n]
```

可用 `--symmetry-breaking on|off` 消融；tiny 实例开关前后最优值一致。当前默认设为 `off`：在 3new6old 的短预算实测中，该排序会显著增加 presolve/root 时间，因此不能在没有实例级证据时默认宣称它改善性能。

## 8. 公平实验预算

`run_experiments.py` 使用：

```text
--total-core-time
--refinement-time
--threads
--mip-gap
```

plain core MIP 与 Route A 使用相同总核心时间、threads、gap、seed、domain、handling scale 和 release policy。完整 Route A 默认分配 Phase 1/ALNS/Phase 3 = 25%/40%/35%；refinement 时间单独记录。base formulation 关闭 valid inequalities 和 symmetry breaking；strengthened formulation 开启强化约束，因而能区分 formulation strengthening 与 ALNS 的贡献。

CSV 的 core 属性来自真正的 `core_best_solution`，candidate 属性来自 refinement candidate，final 属性来自实际选中的 final solution，不再固定读取 Phase 1。core degradation 同时输出 absolute 和 relative。

## 9. 运行命令

```bash
python -m py_compile config.py data.py model_common.py model_core.py solution_validation.py solver_mip_alns.py solve_direct_gurobi.py main.py experiment_configs.py run_experiments.py
python -m pytest -q

python -u main.py --instance tiny --phase1-time 10 --lns-time 10 --phase3-time 10 --attribute-time 10 --attribute-scope final --attribute-basis inventory
python solve_direct_gurobi.py --instance tiny --time 30 --formulation base
python run_experiments.py --instances tiny --seeds 0 1 --total-core-time 20 --refinement-time 5 --threads 1 --suite full
```

## 10. 当前限制

公开 benchmark 缺少真实 POD、weight 和 height，因此属性 refinement 对这些实例不适用。默认 3new6old 是项目内带显式属性的合成业务实例。大型实例能否在短预算内得到 incumbent 或关闭 gap 取决于计算预算；程序会如实输出 TIME_LIMIT、空 UB 或未接受 refinement，不会生成虚构结果。

## 11. 本次审查的实测结果（2026-07-10）

- static compile：通过；`python -m pytest -q`：69 passed。
- tiny Route A 与 direct baseline：UB=LB=16000，gap=0；core objective consistency error=0，独立 checker max violation=0。
- 3new6old，Phase 1/ALNS/Phase 3/refinement=30/30/30/20 秒：Phase 1 UB=16595.808342、LB=15721.019466；ALNS UB=16524.528065，改善 71.280277；Phase 3 UB=16504.459291、LB=15721.019466、gap=4.7468%。core-best 来源为 Phase 3，max violation=`3.68e-12`。
- 3new6old handling：max utilization=0.127887，active average=0.013174，binding constraints=0，说明默认 rate 下 handling 不是主要瓶颈，必须结合 0.25/0.5/1.0/1.5 sensitivity 解读。
- inventory/final refinement：8055.555556 → 8055.555556，未严格改善，正确拒绝；absolute degradation=`3.64e-12`，relative=`2.20e-16`，attribute objective consistency error=`9.09e-13`。
- 公平 90 秒 plain base formulation：UB=16103.678364、LB=15649.387184、gap=2.8210%，root relaxation bound=15649.218380，nodes=1，max violation=`2.58e-11`。该次 plain baseline 优于短预算 Route A，结果如实保留，不将 ALNS 宣称为必然占优。
