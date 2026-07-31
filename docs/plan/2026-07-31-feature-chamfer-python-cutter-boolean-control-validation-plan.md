# Feature Chamfer Python Cutter 与 Boolean 控制验证计划

日期：2026-07-31
状态：`EXECUTED / CUTTER NOT ESTABLISHED / BOOLEAN CONTROL VERIFIED`

执行结果：[`../validation/2026-07-31-feature-chamfer-python-cutter-boolean-control-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-cutter-boolean-control-validation-result.md)

本计划已执行。Python Cutter 的 frame/tilt transport 尚未完整复刻；Boolean Pro 当前消费路径的两阶段固定替代
已通过正确性与阶段性能门槛。以下内容保留为冻结合同与审计记录。

## 1. 要回答的问题

在不自研几何 Boolean 算法的前提下，分别回答：

1. Python 能否直接生成与正式 Curve Pipe 完全等价的 Cutter Mesh，而不是求值或复制旧 GN Cutter；
2. Python 能否移除 Boolean Pro custom group，控制 Blender 原生 Boolean、切口边界物化、当前实际启用的静态后处理，并产生相同输出；
3. 若完全无 GN 的 Boolean API 无法暴露相同能力，最小的固定原生 Mesh Boolean 节点是否是唯一仍需保留的执行内核；
4. 仅当前两项分别通过后，组合路径是否仍保持相同结果并明显快于当前正式入口。

这是旁路可行性验证，不修改或接入正式入口。Cutter 与 Boolean 两项独立验证：一项失败不得阻止另一项继续；
组合阶段则要求两项均通过。

## 2. 固定环境、样本与 oracle

- macOS / Blender 5.1.2；记录 build hash、代码提交、worktree 状态与 fixture SHA-256。
- 固定样本：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`，`Extruded.002`，Radius `0.01`，Keep Cutter `false`。
- Oracle：当前正式一步式路径生成的同一 FeatureGraph/Plan、Cutter、Boolean Pro active path、Boundary、236 层身份与最终 Bridge/Fill 输入。
- Cutter 已知基线：4012 Vertex / 7972 Edge / 3986 Face，fingerprint `51a31aa8362b6370e1f879b90e5314bfb4a69e16853f40a2ba4084e471556e70`。
- Boolean 后几何基线：4195/4866/680，fingerprint `54b68282bb2fb8c0865cf4c2ee5ec6c15fa10a64737a4fa2f2a2b77d5ce5aa9f`。
- Boundary 基线：3872 raw / 3868 unique / 4 duplicate；端点身份 7744 组。
- 派生 FLOAT：ULP≤8 且绝对差≤1e-6；离散身份、schema、集合、拓扑、选择与消费决策严格一致。
- Oracle 必须在 actual 独立产生后比较；不得读取 oracle Mesh/数组来构造 actual。

## 3. 允许与禁止

允许：

- 复用正式 FeatureGraph、ChamferPlan、Pipe/segment/station 分析结果；
- Python 直接建立 Mesh、批量写属性并管理临时 Object/Mesh；
- 调用 Blender 原生 Boolean 实现；不要求 Python 重写几何内核；
- 从 Boolean Pro JSON 与正式 runtime 连接中读取 active path、参数、domain、selection 和静态尾部合同；
- 为验证“Boolean Pro 是否可移除”，建立不随输入规模增长的最小原生 Mesh Boolean 节点组，并把 Intersecting Edges 立即物化为 EDGE attribute；
- 复用已经通过的 Python FACE→EDGE/POINT 转换实现，但必须从本轮真实 raw Boolean 输出独立计算。

禁止：

- 修改正式入口、UI、Bridge/Fill、`auto_load.py` 或正式资产；
- 自研或近似实现几何 Boolean；
- actual 求值、复制或包装旧 Cutter/Boolean Pro；
- 用旧 Boolean 后 EDGE/POINT 输出构造 actual；
- nearest/BVH/centroid、空间容差、坐标匹配、旧新 Edge index 对照、最终 Face 邻接猜测切口；
- 多次 Boolean、固定槽/bitmask、单 owner、fixture/object/segment 特判、station clamp、手工补表；
- 图片、截图或渲染作为验证证据。

## 4. Phase C — Python Cutter 独立验证

### C0：冻结真实生成合同

从正式分析输入一直追到 Cutter Mesh，冻结截面、半径、方向、扭转、端点、cyclic/open、junction、闭合、
face winding、material slot、119 列 FACE schema 与对象变换。不得只冻结最终 fingerprint。

### C1：Python 直接生成 Cutter

actual 必须从同一 Plan/strand 数据直接建立 Mesh；禁止调用旧 Curve Pipe 节点组、evaluated Cutter 或复制 oracle。
比较：

- 规范化几何、拓扑、连通分量和 face winding；
- 4012/7972/3986 与完整 fingerprint；
- closed-manifold、loose geometry、zero-area、self-intersection；
- 119 列属性的 name/domain/type/length 与全部离散、浮点值；
- open/cyclic、junction 与 terminal coverage 合同。

Go：全部合同通过且三次独立结果稳定。
Stop：出现可重复的第一处几何、拓扑、属性或覆盖差异。Cutter Stop 不阻止 Phase B。

### C2：Cutter 性能

仅 C1 通过后运行三次独立冷任务；记录分析外纯生成、属性写入、对象发布与清理时间。阶段中位数≤0.15秒，
最大≤0.25秒。正确但超预算为 Cutter 性能 `STOP`。

## 5. Phase B — Boolean Pro 移除独立验证

本阶段始终使用冻结的正式 Cutter 输入，不依赖 Python Cutter 是否通过。

### B0：冻结 Boolean Pro active path

结合导出 JSON 和 Blender 5.1.2 正式 runtime，冻结实际启用的：原生 Boolean operation/solver、输入顺序、
Intersecting Edges、Surface/Cutter 选择、Face/Edge 属性、材质、Sharp、法线、Weld/Merge/Delete 及 Group Output
连接。未启用分支仅记录，不纳入 actual。

### B1：完全无 GN 的 Python 控制路径

Python 使用 Blender 对外 API 调用原生 Boolean，并尝试从输入属性与原生输出直接得到相同结果 Mesh 和切口
selection。不得反推、猜测或坐标匹配 Boundary。

Go：同一 Manifold 语义、raw Boolean geometry、3872 Boundary 与所需传播属性均可直接获得且一致。
Stop：正式 API 不提供同一 solver/Intersecting Edges 或产生明确首差。此 Stop 只否定“完全无 GN”，不否定 B2。

### B2：Python 控制的最小固定原生节点内核

无论 B1 是否通过都执行。Python 建立固定规模节点组，只保留当前 active path 所需的 Blender 原生 Mesh
Boolean，并在原始输出处把 Intersecting Edges 立即写为持久 EDGE attribute；不得实例化或包装 Boolean Pro。
节点和连线数量必须固定，不随 Face/Pipe/segment/Point 增长。

比较：

- raw Boolean Mesh、4195/4866/680 与完整 fingerprint；
- 3872 raw / 3868 unique / 4 duplicate Boundary；
- Boolean 传播后的完整 FACE schema 与值；
- 236 层 Python 转换后的 3872 Boundary / 7744 endpoint-segment 身份；
- 三次独立求值的确定性和临时数据清理。

Go：全部合同通过。
Stop：出现可重复首差，或必须引入随 owner 增长的节点网络。

### B3：复刻 active static tail

仅 B2 通过后，用 Python 或第二个固定规模阶段逐项复刻 B0 中实际启用的 Surface 选择、材质、Sharp、法线、
Weld/Merge/Delete。每加入一项立即与 Boolean Pro 对应出口比较，记录第一处差异；不得用最终计数代替属性与
selection 对照。

Go：Boolean Pro 所有当前被 Feature Chamfer 消费的输出完全一致。
Stop：任一消费输出、法线、材质、Sharp、拓扑或属性超出合同。

### B4：Boolean 路径性能

仅 B3 通过后运行三次独立冷任务。记录 raw Boolean、Boundary 物化、236 层转换、static tail、Mesh/Object
持久化与清理；Boolean 控制路径中位数≤0.35秒，最大≤0.50秒。正确但超预算为 Boolean 性能 `STOP`。

## 6. Phase CB — 组合路径与未修改下游

仅 C1/C2 与 B2/B3/B4 全部通过后运行。组合 Python Cutter 与已通过的 Boolean 控制路径，把结果交给未经
修改的 Bridge/Fill，比较完整业务 ledger、最终 3922/8054/4134、Chamfer Face 3454、最终 fingerprint、
法线/材质/Sharp、source 不变、Undo/Redo 所需生命周期与失败清理。

三次完整旁路冷运行：中位数≤2.00秒，最大≤2.50秒。任何结果差异或超预算均为 `STOP`；即使通过也只到
`PROTOTYPE / VERIFIED`，禁止接正式入口。

## 7. 状态与证据

- `PASS`：该阶段目标路径和全部门槛成立。
- `STOP`：出现明确、可复现的首处差异或性能超预算。
- `BLOCKED`：外部条件真实阻止验证，且替代 API/路径已审计；实现未完成不是 BLOCKED。
- `NOT RUN`：组合阶段的前置门槛未通过。
- `REJECTED` / `SUPERSEDED`：错误装配或被新证据取代的轮次，保留原因。

机器证据：`tests/artifacts/feature_chamfer_python_cutter_boolean_control/`，至少包含：

- `environment.json`
- `cutter_oracle.json`、`cutter_comparison.json`、`cutter_timings.json`
- `boolean_active_path.json`、`boolean_raw_comparison.json`
- `boundary_comparison.json`、`identity_comparison.json`
- `static_tail_comparison.json`、`boolean_timings.json`
- `combined_downstream_comparison.json`、`summary.json`、`logs/`

结果文档：`docs/validation/2026-07-31-feature-chamfer-python-cutter-boolean-control-validation-result.md`

每阶段结束立即落盘并重读；不得用聊天摘要替代 artifacts 或结果文档。
