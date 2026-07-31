# Feature Chamfer Python Boolean 后 field adaptation 验证计划

日期：2026-07-31
状态：`FROZEN / PROTOTYPE ONLY`

## 1. 要回答的问题

Feature Chamfer 已经在 Boolean 前用 Python 向 Cutter FACE 写入每个 Pipe/segment 的完整属性；同一次
Manifold Difference 后，当前 GN 副本为每个属性动态创建 EDGE/POINT Store。验证能否：

1. 保留完全相同的 source、Cutter、逐 segment FACE schema 与单次 Boolean；
2. 绕过 Boolean 后动态 Store，仅导出同一次 Boolean 的真实 Intersection Edges 与传播后的 FACE 属性；
3. 用 Python 精确复刻现有 GN 的 FACE → EDGE、FACE → POINT field adaptation；
4. 生成未修改 Bridge/Fill 当前读取的完整身份，并达到阶段性能预算。

这不是固定 carrier、来源映射或身份压缩实验。属性数量允许随 Pipe/segment 数增长；禁止的是运行时 GN
node/link 随其增长。也不重新实现 Boolean，不猜测 domain：输入为现有 FACE，输出为现有 EDGE/POINT。

## 2. 固定环境、样本与 oracle

- macOS、Blender 5.1.2；记录 build hash、代码状态与 fixture SHA。
- 样本：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend` / `Extruded.002` / Radius `0.01` /
  Keep Cutter `false`。
- 代码起点包含正式 Python Boolean 前 producer 提交 `46fa628`。
- 输入快照可复用 `/private/tmp/hst-prepared-preview.blend`，使用前必须核对 SHA-256
  `d6e81f6accd181b5efa8d60a04b60018e3df4ce30672e586430b7505a4f2ddda`。
- Oracle：同一输入、同一 Boolean 后的现有动态 GN materializer。冻结范围为 3872 raw / 3868 unique /
  4 duplicate Boundary，以及 7744 endpoint-segment 的 membership、station、station² 和完整 Pipe、Patch、
  port、cyclic interval 业务记录。
- 离散身份、schema、集合与消费决策严格一致；派生 FLOAT 同时满足 ULP ≤ 8 与绝对误差 ≤ 1e-6。
- Oracle 只在 actual 独立生成后末端比较；不得用于构造 Python 输出或修补差异。

## 3. 允许与禁止

允许：

- 复用正式 Python producer 生成的同一 source/Cutter Mesh 及全部逐 owner FACE attribute；
- 复制同一 Boolean Pro，只保留固定 Intersection 出口和为观察“Boolean 刚输出”所必需的固定诊断出口；
- Python 读取 evaluated Mesh 的 FACE attribute 与 Mesh 拓扑，并实现 Blender/GN 已有的 field adaptation；
- 通过 Blender MCP 任务 `019fb787-57ed-7af2-8301-1a10b5bcc3b3` 补充节点结构证据；MCP 证据不能替代
  Blender 5.1.2 正式 runtime 实跑。

禁止：

- 修改正式入口、Boolean、Cutter、Bridge/Fill、UI 或 `auto_load.py`；
- 调用旧 Boolean 后动态 materializer 生成 actual，或复制 oracle 的 EDGE/POINT 输出；
- 为每个 Pipe/segment/Patch 动态创建 GN 节点或连接；
- 多次 Boolean、overlap batch、固定 carrier、record moments、固定槽、bitmask、单 owner；
- nearest、BVH、centroid、空间容差、固定元素 ID、fixture 特判、手工补表、station clamp；
- 用最终 Face 邻接的 any/max 等猜测代替现有 field adaptation；
- 生成、读取或判断 PNG/JPEG/截图。

## 4. Phase 0 — 冻结真实转换链

从正式运行时副本按真实连接导出每类属性的完整链：Boolean 前属性名/domain/type、Boolean 刚输出时的
属性存在性与值、Named Attribute 求值位置、Store domain、Selection 输入和最终属性名。至少覆盖：

- Pipe、source Patch 与 segment EDGE membership；
- segment POINT membership；
- EDGE/POINT station 与 station²；
- 历史首差 Edge 133 / Pipe 4 / segment 24。

同时对照原始 Boolean Pro MCP JSON，明确原始资产 184/260 与正式注入副本 592/808 的区别。不得把
Feature Chamfer 注入通道归因于 Boolean Pro 本体。

Go：每类输出都能唯一追溯到现有 FACE field 与明确的 GN field context。
Stop：只能看到最终值，无法确定真实转换边界。后续 `NOT RUN`。

## 5. Phase 1 — 首差规则复刻

先只处理 Edge 133 / segment 24 的两个端点。actual 必须从绕过动态 Store 的同一次 Boolean 输出独立生成。
Python 复刻现有 field adaptation 后，逐项比较：

- Edge membership、station、station²；
- 两端 Point membership、station、station²；
- domain adaptation 参与的全部 Face/Corner/Point 来源与权重。

不得使用 oracle 值反推规则。六项离散/浮点合同全部命中才为 `PASS`；明确首差为 `STOP`。

## 6. Phase 2 — 完整身份等价

仅 Phase 1 通过后运行。对全部 3872 raw Boundary、7744 endpoint-segment 比较：

- schema、domain、type、元素数；
- Pipe、Patch、segment、port 多 owner 集合；
- EDGE/POINT membership、station、station²；
- cyclic interval、排序和下游 `>1e-6` 消费决策；
- bitwise 差异数、最大 ULP、最大绝对误差与第一处差异。

完整通过为 `PASS`；任一离散差或超容差为 `STOP`。

## 7. Phase 3 — 未修改下游与性能

仅 Phase 2 通过后，将 Python 生成的属性交给未修改 Bridge/Fill，比较冻结业务记录、最终 fingerprint
`f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107`、3922/8054/4134/3454 和四项
健康计数。全部一致后运行三次独立冷任务：

- Python Boolean 后 materializer：中位数 ≤ 0.50 秒、最大值 ≤ 0.75 秒；
- 完整旁路端到端：中位数 ≤ 2.00 秒、最大值 ≤ 2.50 秒；
- 三次 fingerprint、业务 ledger 与清理合同一致。

正确但超预算仍为性能 `STOP`。本轮即使通过也只到 `PROTOTYPE / VERIFIED`，不得接正式入口。

## 8. 状态与交付物

- `PASS`：阶段全部目标和硬门槛成立。
- `STOP`：出现明确可复现的语义、结果或性能差异。
- `BLOCKED`：外部条件确实阻止验证，且已有反证审计；实现未完成不构成阻塞。
- `NOT RUN`：前一门槛未通过。
- `REJECTED` / `SUPERSEDED`：错误或被新证据取代的轮次，必须保留原因。

机器证据：`tests/artifacts/feature_chamfer_python_field_adaptation/`

至少包含 `environment.json`、`runtime_chain.json`、`first_edge_comparison.json`、
`full_identity_comparison.json`、`downstream_comparison.json`、`timings.json`、`summary.json`、`logs/`。

结果文档：
`docs/validation/2026-07-31-feature-chamfer-python-field-adaptation-validation-result.md`

每阶段结束立即落盘；前一阶段失败后不得继续。
