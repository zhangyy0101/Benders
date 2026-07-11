# paper-exp-v1 内存数据 schema

当前求解器接收 Python `dict`。Task 05 之前尚无冻结的磁盘 JSON schema；本文件描述
`prepare_instance` 后的内存边界。tuple key 的顺序是接口的一部分。

## Required fields

| 字段 | 类型/键顺序 | 值与单位 | 完整性条件 |
|---|---|---|---|
| `K` | `list[str]` | blocks | 模型要求可迭代；当前 validator 未检查非空/唯一 |
| `I`, `I_list` | `dict[bay, metadata]`, list | `cap` boxes、`block` | 每个 bay 有非负 capacity，归属有效 block |
| `Bays_in_Block` | `dict[block,list[bay]]` | membership | 与 `I_list`/`I` 一致 |
| `J_new`, `J_old` | lists | ships | 标识唯一 |
| `S` | list[int] | 20/40 ft 类别 | 与 mode/group size 一致 |
| `N` | list[int] | periods | 必须为 `0..len(N)-1` |
| `Intervals` | `list[dict]` | `id,start,end,dur`; 时间为 hours | id 对应 period，dur > 0 |
| `Alpha` | number | dimensionless reserve factor | 模型语义要求 > 0；当前 validator 未显式检查 |
| `Dist` | `dict[(new_ship,block),number]` | 距离；主实例为 meters | 每个 `(j,k)` 完整且有限；当前 validator 未拒绝负值 |
| `Arrivals_interval` | `dict[(new_ship,size,period),number]` | boxes arriving | 每个组合完整、非负 |
| `initial_inventory_data` | `dict[(bay,old_ship,size),number]` | initial boxes | 非负，每 bay 合计不超 capacity |
| `Fixed_In_Flow` | `dict[(old_ship,size,bay,period),number]` | fixed inbound boxes | 非负；缺省键按 0 读取 |
| `Block_Outbound_Req` | `dict[(block,old_ship,period),number]` | requested outbound boxes | 非负且按期不超过可用旧库存 |
| `Block_Outbound_Vol` | `dict[(block,period),number]` | outbound boxes | 应等于该 block-period 各旧船 request 之和 |
| `Fixed_Bay_Mode` | `dict[bay,size]` | 20/40 ft category | 每 bay 完整且属于 `S` |
| `Fixed_Mode_Force` | `dict[(bay,period), size-or-None]` | mode override metadata | 当前模型仍以 `Fixed_Bay_Mode` 为实际固定 mode |
| `Bay_Handling_Rate` | `dict[(bay,period),number]` | boxes/hour | 每个组合完整、非负 |

`validate_instance_units` 还要求 `J_all` 的实际生成实例保持新旧船并集语义，但当前
required-key 检查没有强制该字段。

## Joint-group fields

具有联合组的实例使用：

- `G: list[group]`；
- `GroupAttrs[group] = {size, pod, height, weight_class}`；
- `GroupSize`, `GroupPOD`, `GroupHeight`, `GroupWeightClass` 为同属性的显式映射；
- `Arrivals_group_interval[(new_ship, group, period)]`，单位 boxes。

对每个 `(ship,size,period)`，同 size 的 group arrivals 之和必须等于
`Arrivals_interval[(ship,size,period)]`。属性或 grouped arrival 不完整时集中性为
`NOT_APPLICABLE`，但 size-level fallback 仍由 `model_common.arrival` 支持。

## Optional and metadata fields

常见可选字段包括 `ScenarioName`、`TimeBucketHours`、`NumBerths`、`Berths`、
`ShipBerth`、`YardStructure`、`OldShipType`、`New_Outbound_Req`、
`Old_Box_Occupancy_Map`、`Old_Ship_Size_Map` 及生成过程审计 metadata。它们不是全部
由 `validate_instance_units` 强制。`New_Outbound_Req` 缺失或全零时，有效不等式会令
`x` 随时间单调；当前核心模型没有新箱离场递推。

## prepare boundary

`prepare_instance(raw, handling_rate_scale, old_outbound_release_policy)` 深拷贝输入，
因此不修改 raw object。它会覆盖/派生：

| 字段 | 规则 |
|---|---|
| `Bay_Handling_Rate[(i,n)]` | `50 boxes/hour * handling_rate_scale`，会覆盖 raw rate |
| `handling_rate_base` | `50.0` boxes/hour |
| `handling_rate_scale` | 显式参数 |
| `handling_rate_source` | `model_calibration` |
| `old_outbound_release_policy` | 显式参数，默认 `proportional` |

随后立即调用 `validate_instance_units`。scale 必须有限且非负；policy 只能是
`legacy_sorted`、`proportional`、`conservative`。不会剪裁出场需求或静默修复实例。

## Old inventory semantics

`simulate_old_inventory` 每期先加入 fixed inbound，再按 block/old-ship request 释放。
`proportional` 按该 block 内库存比例扣减 logical 与 capacity occupancy；
`legacy_sorted` 按排序贝位扣减两者；`conservative` 从 logical inventory 扣减，但不释放
capacity occupancy。验证要求 unserved outbound 为 0，且模拟 occupancy 不超过 capacity。

## On-disk benchmark schema

正式 benchmark 交换格式为 JSON `yard-bay-instance-v1`，顶层固定包含
`schema_version`、`problem_protocol`、`instance_id`、`digest`、`instance_state=raw`
和 `data`。只保存 raw instance；加载后由运行入口以显式协议参数调用一次
`prepare_instance`。带 `handling_rate_source` 等 prepared-only 字段的对象会被拒绝，
从而防止重复 prepare。

Tuple-key 字段按 `benchmark_schema.RECORD_SCHEMAS` 保存为带 `record_schema`、显式
`columns` 和稳定排序 `records` 的对象。当前覆盖 distance、initial inventory、两级
arrivals、outbound volume/request、fixed inbound/mode、bay mode、handling rate 和
两个 old maps。未注册的非字符串 dict key 会失败；不使用 `eval`、拼接 key 或 pickle。

Digest 为 canonical UTF-8 compact JSON 的 SHA-256，覆盖 schema version、problem
protocol、raw data、generator spec 和 seed；不覆盖保存时间、绝对路径或算法配置。
加载默认重新计算并验证。字段、schema 或 protocol 迁移不得静默进行；未知顶层字段、
record schema 不匹配、重复 record 和 digest 错误都会失败。
