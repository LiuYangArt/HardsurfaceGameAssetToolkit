# Feature Chamfer Phase C — 历史逐边配对路线

日期：2026-07-24
状态：`HISTORICAL / SUPERSEDED / DO NOT RESUME`

> 2026-07-25 用户再次确认 Blender 中的真实工作流：选中同一根 Pipe 槽口左右两侧的完整 Edge Loop，直接执行 Blender Bridge。两侧 Vertex / Edge 数量无需一致，也不要求逐点、逐边或逐 fragment 对应。
>
> 当前唯一执行计划：[`2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`](./2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md)。本文不再提供后续步骤、Stop / Go 或实现门槛。

## 历史目标

这条路线曾尝试在删除槽面之前，为槽口的一侧每条 Edge 找到对侧的唯一 Edge 或 Edge chain，并要求完整身份传播、单次消费和正逆顺序一致。随后又尝试：

- 通过 Groove FaceGraph 推导对侧；
- 把连续 fragment 合并为 maximal chain；
- 检查公共边的 branch / cycle；
- 清理重合 Vertex / Edge 和零面积 Face；
- 证明 raw → canonical 的唯一映射后再 Bridge。

这些工作产生了诊断证据，但把“选择同一 Pipe 的两侧完整 Edge Loop”和“Blender 如何在两侧之间生成 Faces”混成了一个问题。

## 废弃原因

用户的 Blender 实测和截图已经确认：普通 `Bridge Edge Loops` 能直接连接 Edge 数量不同的两侧，并由 Blender 决定内部 tri/quad 拓扑。产品只需要可靠选中同一根 Pipe 的两侧完整边界，不需要项目自行证明逐边对应。

因此以下历史阻塞均不再作为 Bridge 前置门槛：

- 两侧数量不同；
- 无法逐条建立 source/opposite Edge 对应；
- candidate Edge 无法逐段独占；
- 公共边图出现 degree>2、branch 或 cycle；
- 中间 Boolean 数据记录到重合点、重合边或零面积 Face；
- 无法证明唯一 canonicalization；
- 无法为每条 Edge 保留完整的配对身份。

这些诊断只有在最终 Bridge 实际失败、连接错误或破坏槽外模型时，才可作为排查线索；不得提前阻断已经正确选中的两侧 Edge Loop。

## 可复用成果

- Preview 生成的 Pipe 和用户可见槽形状继续复用；
- Manifold Boolean 已证明可产生正确的可见槽；
- 真实 5-vs-3 Bridge 已成功，证明两侧数量不等不是问题；
- Pipe、source、回滚和正逆顺序检查可以继续用于选择范围与安全验证；
- 历史 probe、报告和 `.blend` 保留为诊断资料，不再决定当前路线。

## 当前状态

- `Algorithm`：不等数量 Edge Loop 的 Blender Bridge 能力已有证据；
- `Backend`：尚未从真实目标自动提取同一 Pipe 的两侧完整边界并直接 Bridge；
- `Operator`：未接入正式 `FINALIZE`；
- `Visual/Product`：未完成三个重点目标和完整矩阵验收；
- `Phase C`：`PROTOTYPE / STOP`。

后续不得从本文恢复逐边 pairing、canonicalization、Merge 或 operand 调整路线。所有执行以新的 Pipe Edge Loop 直接 Bridge 计划为准。
