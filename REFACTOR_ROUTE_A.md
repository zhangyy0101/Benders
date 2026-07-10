# Route A: Strengthened MIP–ALNS

## 定位与量纲修正

默认算法现在是完整单体 MIP、adaptive LNS、证明导向 MIP 重启和 ε-constrained attribute refinement。分解算法不再作为默认入口或算法贡献。存储容量始终以 boxes 表示；处理能力改为 `Bay_Handling_Rate[bay, interval]`（boxes/hour）乘 interval hours。默认 50 boxes/hour 是模型校准参数，不来源于 BAPTBI 或 Barcelona 原始数据。

## 完整 core MIP

`model_core.build_core_monolithic_model()` 是主流程、repair、refinement 和 direct baseline 的唯一公开 builder；默认路径不再导入旧 `solver_bbc.py`。变量包括整数/连续 `alloc_boxes`、二元 `x`/`block_use`，以及连续 `din`、`inv`、`in_share`、`in_total`、`avg` 和 `g_bal`。它统一包含固定 bay size、存储容量、allocation/activation 双向连接、累计 allocation、arrival conservation、库存平衡、handling rate、block/bay flow 等式、fixed inbound、L1 balance 和 block activation 约束。

核心目标只含 open-bay-time、berth-to-block distance、L1 balance 和 outbound conflict。所有阶段共享同一组与解无关且严格为正的 scale。`evaluate_core_solution()` 从变量值重算 raw、normalized、weighted components 和 total；求解时强制检查其与 `ObjVal` 的误差不超过 `1e-5`。

## 四阶段职责

1. Phase 1 使用 `MIPFocus=1, Presolve=2, Cuts=1, Heuristics=.20` 获取 incumbent 和合法全局 LB。
2. ALNS 提供 random、active-biased、block/interval/ship/conflict/distance-focused operators。每个 repair 重建完整单体模型，固定未 destroy 的变量；释放一个 `(bay, ship)` activation 时释放其完整时间轴 allocation。repair bound 绝不作为全局 LB。
3. Phase 3 注入 ALNS MIP start，以 `MIPFocus=3, Cuts=2, Presolve=2, Heuristics=.02, Symmetry=2` 改善证明。最终 LB 仅取 Phase 1/3 合法界的最大值，且断言 `LB <= UB + 1e-5`。
4. refinement 在完整可行域上最小化 attribute score，并约束 `core_objective <= core_best_ub*(1+epsilon)`。仅当 core cap、完整可行性及属性严格改善同时成立时接受。

POD、weight 和 height 使用相同的 `final`（默认）或 `horizon` scope。core-best 与 refined solution 分别写入两个 JSON；core LB/gap 只属于 core-best，不能解释为 refined solution 的 gap。

## Valid inequalities 与变量域

没有 new-container outbound 时加入 `x` 和 `block_use` 时间单调性；`--no-valid-inequalities` 支持消融。branch priorities 为 block 30、x 20、allocation 5。`--alloc-domain integer|continuous` 控制 allocation；连续域 start/repair 从不 round。

## 运行

```bash
python -u main.py --instance 3new6old --phase1-time 20 --lns-time 45 --phase3-time 20 --attribute-time 20 --attribute-epsilon .01
python solve_direct_gurobi.py --instance 3new6old --time 60 --alloc-domain integer
python run_experiments.py --instances 3new6old --seeds 0 1 2 --time 20 --suite full
pytest -q
```

`--suite quick` 执行核心算法对比，`--suite full` 进一步执行 allocation domain、handling-rate、epsilon 和 POD/weight/height 消融。

主 summary 记录 allocation domain、handling-rate base/scale/source、valid inequalities、各阶段指标、core UB/LB/gap 和 refinement 的退化/改善。`run_experiments.py` 输出 CSV/JSON，可覆盖 domain、rate scale、epsilon 与 valid-inequality 消融。

## 已运行验证与实验（2026-07-10）

- `python -m pytest -q`：33 passed。
- tiny instance：Phase 1、Phase 3 和 plain baseline 均达到 OPTIMAL，UB=LB=16000，gap=0；目标重算误差在 `1e-5` 内。
- tiny full suite：2 seeds × 21 configurations = 42 rows，保存在 `experiment_results/tiny_full/results.csv` 和 JSON。
- 默认 3new6old（Phase 1/ALNS/Phase 3/refinement = 30/10/20/10 秒）：Phase 1 UB 18206.817915、LB 15720.767818；ALNS 将 UB 改善 418.098623 至 17788.719292；Phase 3 保持 LB 15720.767818，最终 gap 11.6251%。refinement 候选属性分数与起点同为 5977.777778，未满足严格改善条件，因此正确拒绝。

## 已知限制

旧 `solver_bbc.py` 仅作为历史实现留存，默认入口、公共 helper、core builder、ALNS、refinement 和 direct baseline 均不再导入它。默认 3new6old 在当前受控时间预算内尚未完成最优性证明；上述 UB/LB/gap 是真实 time-limit 结果，而不是最终最优值。属性 refinement 在本次默认实验中没有找到严格改善方案。Barcelona/BAPTBI adapter 规则和数据集未改动，更大规模多 seed 论文实验仍需按可用计算预算继续运行。
