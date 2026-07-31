# Feature Chamfer Python Boolean 后身份整理验证计划

日期：2026-07-31

状态：`PROTOTYPE / STOP`

执行结果：Phase 0 `PASS`；Phase 1 固定 Intersection 与几何合同 `PARTIAL PASS`；Phase 2 在第一条
Boundary 的 Pipe 0 身份缺失处 `STOP`；Phase 3–4 按硬门槛 `NOT RUN`。详见
[`../validation/2026-07-31-feature-chamfer-python-post-boolean-materializer-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-post-boolean-materializer-validation-result.md)。

## 1. 要回答的问题

在正式入口已经使用 Python 生成 Boolean 前完整属性、Boolean Pro 保持不变的前提下，验证能否删除
Boolean 后按 Pipe、segment 和 Patch 动态展开的 Geometry Nodes 身份整理网络，改为：

1. 固定规模节点只导出同一次 Manifold Difference 的真实 `Intersection Edges`；
2. Python 从该 Boolean 输出上已经传播的 FACE 属性和 Mesh 邻接关系，一次性生成当前 Direct Bridge
   读取的全部 Boundary EDGE/POINT 属性；
3. 不修改 Direct Bridge/Fill，得到与当前正式入口完全相同的最终结果。

验证对象是上述真实 Boolean 后数据边界，不是重新实现 Cutter、替换 Boolean、压缩 owner 数据、空间
近似匹配或只比较最终健康指标。

## 2. 固定环境、样本与 oracle

- 项目规范：`/Users/apple/CodeProjects/blender-addons/HardsurfaceGameAssetToolkit/AGENTS.md`
- 总体路线：`docs/plan/2026-07-30-feature-chamfer-performance-optimization-replan.md`
- 前置集成结果：`docs/validation/2026-07-31-feature-chamfer-python-pre-boolean-formal-integration-result.md`
- 既有完整属性验证：`docs/validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md`
- 固定环境：macOS、Blender 5.1.2；实际完整版本与 fixture SHA 必须写入 artifact。
- 固定样本：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- 固定对象与参数：`Extruded.002`、Radius `0.01`、Keep Cutter `false`。
- 代码起点：包含正式 Boolean 前 Python producer 的提交 `46fa628`，加本验证计划；正式代码只读。
- Oracle：当前正式一步入口中，原有 Boolean 后动态 materializer 输出的 evaluated Mesh，以及未修改
  Bridge/Fill 的冻结业务记录和最终产品矩阵合同。

Phase 0 必须先从同一次输入冻结 oracle，再执行目标路径。不得使用不同 fixture、不同 plan、不同 Curve、
不同 Cutter Mesh 或不同 Boolean 参数作比较。既有 worktree artifacts 只作路线参考，不代替本轮 oracle。

## 3. 允许与禁止机制

### 3.1 允许

- 复用正式 Python Boolean 前 producer 生成的同一 source/Cutter Mesh 和完整 FACE 属性；
- 复制受控 Boolean Pro，仅把 active Manifold Difference 的 `Intersection Edges` 写入一个固定 EDGE
  布尔属性；固定出口节点和连接数量不得随 Patch、Pipe、segment、Point 或 Face 数量增长；
- Python 读取 Boolean 输出 Mesh 的原生 FACE 属性、Edge/Vertex/Face 邻接和 plan；
- Python 批量创建 Direct Bridge 当前读取的 EDGE/POINT Mesh attributes；
- 旁路调用未修改的 Direct Bridge/Fill，并保存 JSON、日志和必要的 `.blend` 诊断文件；不得读图验收。

### 3.2 禁止

- 修改正式入口、UI、`auto_load.py`、Boolean Pro 或 Bridge/Fill；
- 调用现有动态 Boolean 后 materializer 生成目标结果，或读取其输出后复制为目标结果；
- 为每个 owner 动态创建 GN 节点、连接或属性出口；
- nearest、BVH、centroid、固定 Edge/Face ID、fixture 名称分支、手工补表、station clamp；
- 单 owner、固定槽位、固定 bitmask 或其他不能表达任意多归属的压缩；
- 看到差异后修改 oracle、放宽容差或跳过失败阶段；
- 用 Boundary 数量、最终面数或“看起来正确”代替完整身份和业务记录比较。

## 4. 分阶段硬门槛

### Phase 0 — 冻结本轮正式 oracle

必须保存：

- Blender 版本、fixture SHA、代码状态、对象、参数、plan ID/fingerprint；
- source/Cutter Boolean 输入几何与完整属性 manifest；
- Boolean Pro 节点树、solver、operation、输入顺序和参数 fingerprint；
- 当前 materializer 的节点数、连接数、按 owner 增长项和构建时间；
- Boolean 后、Bridge 前全部 Mesh schema；
- 3872 raw / 3868 unique / 4 duplicate 的 Boundary multiplicity 口径；
- 逐 Boundary Edge 的 Pipe、segment、Patch、Edge/Point membership、station、station²、cyclic interval；
- Bridge/Fill 完整稳定业务记录和最终冻结产品合同。

状态：完整且三次读取稳定为 `PASS`；否则 `BLOCKED`，后续 `NOT RUN`。

### Phase 1 — 固定出口与原始 Boolean 输出可读性

目标路径必须绕过现有动态 materializer，只运行同一 Boolean 和固定 Intersection 出口。比较：

- source/Cutter 输入与 Phase 0 完全一致；
- Boolean 节点、参数和输入顺序完全一致；
- Boundary raw/unique/multiplicity 完全一致；
- Boolean 输出上的所需 FACE 属性 schema、domain、type、长度和完整值可读取；
- 固定出口自身节点数、连接数不随 owner 数增长。

任何第一处缺失或差异保存完整上下文后为 `STOP`，Phase 2–4 `NOT RUN`。

### Phase 2 — Python 完整 materializer 等价性

Python 只能从 Phase 1 目标输出和同一 plan 生成旧 Bridge 所需身份。必须完整比较：

- 属性名、domain、type、元素数完全一致；
- Boundary、Pipe、Patch 的布尔身份逐元素一致；
- segment membership 的全部 Edge/Point 值及其 `> 1e-6` 消费决策一致；
- station、station² 和 cyclic interval 全量比较；
- 离散 owner 集合、共享 owner、端点贡献和排序完全一致；
- 逐 Edge 稳定 ledger fingerprint 一致。

派生 FLOAT 延用此前用户批准且已经冻结的双重门槛：ULP `≤ 8` 且绝对差 `≤ 1e-6`；同时必须保留
bitwise 差异数、最大 ULP、最大绝对差和第一处差异。布尔、ID、集合、连接关系及消费决策没有容差。

全部通过为 `PASS`；出现超容差或离散首差为 `STOP`，Phase 3–4 `NOT RUN`。

### Phase 3 — 未修改 Bridge/Fill 与最终结果

仅 Phase 2 `PASS` 后运行。目标 materializer 输出交给未修改 Bridge/Fill，比较：

- Bridge job 集合、顺序、owner surface pair、segment/pipe 分组、station interval、turn/cyclic split；
- Bridge/Fill Face 数与稳定业务记录；
- 最终 fingerprint `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107`；
- 3922 Vertex / 8054 Edge / 4134 Face / 3454 Chamfer Face；
- Boundary、non-manifold、zero-area、self-intersection 均为 0；
- source 不变，无临时对象、Mesh、Curve、modifier 或 Node Group 残留。

全部逐项一致为 `PASS`，否则保存第一处业务差异后 `STOP`。

### Phase 4 — 三次独立性能

仅 Phase 3 `PASS` 后运行三次独立冷任务；Blender 启动时间不计。每次重跑分析、Boolean 前 producer、
同一 Boolean、Python 后整理、未修改 Bridge/Fill 和清理。记录统一分时、节点/连接/属性规模。

- Python Boolean 后 materializer：中位数 `≤ 0.50s`，单次最大 `≤ 0.75s`；
- 正式等价旁路端到端：中位数 `≤ 2.00s`，单次最大 `≤ 2.50s`；
- 三次结果 fingerprint、Bridge/Fill ledger 和清理合同一致。

全部满足为最终 `PROTOTYPE / PASS`。结果正确但超预算仍为性能 `STOP`，不得包装成完整通过。

## 5. 状态边界与停止规则

- `PASS`：本阶段实际目标、完整比较和全部门槛同时通过。
- `STOP`：出现明确、可复现的首处语义、结果或性能差异。
- `BLOCKED`：外部条件阻止验证，且已保存反证审计；实现尚未完成不构成 BLOCKED。
- `NOT RUN`：前一硬门槛未通过。
- `REJECTED` / `SUPERSEDED`：保留被主任务驳回或后续证据取代的旧轮次及原因。

每阶段结束立即写 artifact 和结果文档。前一阶段失败后不得继续运行下一阶段，不得接正式入口。

## 6. 必须交付的持久证据

独立任务至少维护：

- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/summary.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/environment.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/oracle.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/fixed_export.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/identity_comparison.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/downstream_comparison.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/timings.json`
- `tests/artifacts/feature_chamfer_python_post_boolean_materializer/logs/`
- `docs/validation/2026-07-31-feature-chamfer-python-post-boolean-materializer-validation-result.md`

结果文档使用
`/Users/apple/.codex/skills/isolated-validation-orchestrator/assets/validation-result-template.md`，必须记录每阶段
真实机制、状态、关键数字、首差、禁止机制使用情况、被驳回轮次、尚未验证事项和 artifact 绝对路径。

## 7. 当前授权边界

本轮只允许旁路验证和验证文档。即使全部 `PASS`，也不得修改正式入口或集成目标实现；主任务复核后，
由用户决定是否进入正式替换。
