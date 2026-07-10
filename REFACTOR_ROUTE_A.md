# Route A: Strengthened MIP–ALNS

## 定位与量纲修正

默认算法现在是完整单体 MIP、adaptive LNS、证明导向 MIP 重启和 ε-constrained attribute refinement。分解算法不再作为默认入口或算法贡献。存储容量始终以 boxes 表示；处理能力改为 `Bay_Handling_Rate[bay, interval]`（boxes/hour）乘 interval hours。默认 50 boxes/hour 是模型校准参数，不来源于 BAPTBI 或 Barcelona 原始数据。

## 完整 core MIP

`model_core.build_core_monolithic_model()` 是主流程、repair、refinement 和 direct baseline 的唯一公开 builder。变量包括整数/连续 `alloc_boxes`、二元 `x`/`block_use`，以及连续 `din`、`inv`、`in_share`、`in_total`、`avg` 和 `g_bal`。它统一包含固定 bay size、存储容量、allocation/activation 双向连接、累计 allocation、arrival conservation、库存平衡、handling rate、block/bay flow 等式、fixed inbound、L1 balance 和 block activation 约束。

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
python run_experiments.py --instances 3new6old --seeds 0 1 2 --phase-time 20
pytest -q
```

主 summary 记录 allocation domain、handling-rate base/scale/source、valid inequalities、各阶段指标、core UB/LB/gap 和 refinement 的退化/改善。`run_experiments.py` 输出 CSV/JSON，可覆盖 domain、rate scale、epsilon 与 valid-inequality 消融。

## 已知限制

旧文件仍作为迁移兼容层保存，其中的 group/occupancy/scale 和既有业务约束由新公共接口复用；默认入口不调用其 callback 或分解求解器。默认 3new6old 模型规模较大，极短 time limit 可能没有 incumbent；此时程序明确报告失败，不生成虚构数值。Barcelona/BAPTBI adapter 规则和数据集未改动。
