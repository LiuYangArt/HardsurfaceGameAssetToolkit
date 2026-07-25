# Feature Chamfer Phase C — 历史配对与 Boolean 诊断摘要

状态：`HISTORICAL DIAGNOSTIC / SUPERSEDED / NOT A CURRENT GATE`

> 当前执行计划：[`../../plan/2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`](../../plan/2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md)。
>
> 用户已确认：只需按同一根 Pipe 选中槽口左右两侧完整 Edge Loop，直接执行 Blender Bridge。两侧 Vertex / Edge 数量不必相同，也不需要逐点或逐边对应。本文记录的重合、零面积、degree、branch、cycle、身份冲突和 canonicalization 结果，不再是 Bridge 前置门槛。

## 1. 为什么这条路线被停止

早期实现试图在 Bridge 前证明：槽口一侧的每条 Edge 都有唯一对侧 Edge，每段输入只被消费一次，并且 Boolean 前后的 Face/Edge 身份可以完整传递。

这把两个不同问题混在了一起：

1. 项目需要确定“哪两组完整 Edge Loop 属于同一根 Pipe”；
2. Blender 负责“如何在两组 Edge Loop 之间生成 Faces”。

用户在 Blender 5.1.2 的真实模型上已经证明普通 Bridge 支持两侧 Edge 数量不同，并可生成 tri/quad 混合结果。因此项目不应继续自行建立逐边对应，也不应先整理两侧为相同分段。

## 2. 仍然有效的事实

- Preview 中的 Pipe 槽视觉结果正确；
- Blender Manifold Boolean 能生成该槽；
- 切口的两侧边界实际存在；
- 真实 5-vs-3 open Edge Loop 已成功 Bridge，并生成 8 个 Faces；
- 三个重点目标的 Manifold 只读验证均保持 source 不变，正逆 batch 结果一致；
- 把多 Pipe 批次拆成单 Pipe 后，中间诊断记录仍可能存在，说明这些记录不是“多 Pipe 一起切”独有现象。

这些事实支持直接验证 Pipe 两侧完整边界 → Blender Bridge，不支持继续扩展逐边配对或清理路线。

## 3. 历史诊断结果的正确解释

历史探针曾记录：

- 某些公共边图存在 degree-4 或 cycle；
- 某批次出现少量重合 Vertex / Edge、零长度 Edge 或零面积 Face 记录；
- 旧 witness 数量和实际公共 Edge 数量有差异；
- 逐边/逐段 pairing 无法得到唯一解释；
- Merge、局部重建与 canonicalization 无法同时满足旧门禁。

这些数据只描述中间计算结果。用户在可见槽中没有观察到对应的产品缺陷；现有证据也没有证明它们会阻止 Blender Bridge。此前把这些诊断描述为“槽切完后的内部结构不干净”并据此转向 operand、Merge 或 canonicalization，是过度推断。

以后只有当两侧完整 Edge Loop 已正确选中，而 Blender Bridge 实际失败、连接错误或破坏槽外模型时，才重新使用这些 artifact 排查。

## 4. 已废弃的开发方向

- Pre-Boolean profile-neighbor direct incidence；
- Groove FaceGraph → unique opposite chain；
- maximal source/candidate chain pairing；
- raw/normalized/candidate exactly-once 作为 Bridge 门禁；
- Bridge 前的 Merge by Distance、局部 rebuild 或 canonicalization；
- 为消除 degree/branch/cycle 而修改 cutter batching、端部或穿透范围；
- 要求两侧相同分段或建立逐 Vertex 对应。

相关代码和测试目前只作为历史诊断/回归保留；它们不得阻止当前 Direct Edge-Loop Bridge probe。

## 5. 历史证据索引

以下 artifact 保留用于复盘，不代表当前 Stop / Go：

- Manifold 三目标首轮：
  - `/private/tmp/hst-phase-c-manifold-tricky-r0030-20260725-02/report.json`
  - `/private/tmp/hst-phase-c-manifold-tricky-r0010-20260725-01/report.json`
  - `/private/tmp/hst-phase-c-manifold-mixed-r0030-20260725-01/report.json`
- `tricky r0.03` 边界诊断：
  - `/private/tmp/hst-phase-c-manifold-tricky-r0030-20260725-07/report.json`
- Merge 对照：
  - `/private/tmp/hst-phase-c-local-merge-campaign-20260725-01/report.json`
- Boolean 原始记录 census：
  - `/private/tmp/hst-phase-c-boolean-defect-census-r0030-20260725-04/report.json`
  - `/private/tmp/hst-phase-c-boolean-defect-census-r0030-20260725-04/phase_c_boolean_defect_census.blend`
- 单 Pipe 对照：
  - `/private/tmp/hst-phase-c-singleton-operand-census-r0030-20260725-01/report.json`

## 6. 当前状态

当前仍是 `PROTOTYPE / PHASE C STOP`，原因不是上述中间诊断未清理，而是新的 Direct Edge-Loop Bridge 路线尚未从真实目标 Operator 完成自动选择、Bridge 和产品验收。

下一步只执行新计划：从 `tricky / Solid.004 / r0.03` 的目标 Operator 结果中，按 Pipe 选出槽口两侧完整 Edge Loop，直接 Bridge，并检查最终可见结果、封闭性、槽外 source 不变和回滚。
