# Feature Chamfer 分批 Cut / Fill 历史 Handoff

日期：2026-07-23
状态：`HISTORICAL / SUPERSEDED / DO NOT RESUME`

> 当前唯一执行计划：[`2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`](./2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md)。本文不再提供恢复点或后续任务。

## 历史成果

- 正式 Preview 已能冻结 Pipe、Radius 和 source 合同；
- 分批 Boolean 的正逆顺序验证、source 不变和失败回滚基础设施已经建立；
- 曾运行 14 cells × 3 repetitions，但历史自动绿包含过宽的安全停止语义，不能视为产品通过；
- 真实 `tricky / Solid.004 / r0.03` 曾用 Blender Bridge 成功连接 5-vs-3 的两侧边并生成 8 个 Faces；
- 正式 `FINALIZE` 尚未切换到当时的实验 backend。

## 历史误区

这条路线后来持续把 Boundary Edge 切成 fragments，要求每条边都有唯一 owner、consumer、setback 或 correspondence，并尝试用 DP、trim、cyclic lift 和逐 Edge 账本消除 unresolved。

用户截图已经证明：只要按同一根 Pipe 取得槽口左右两侧完整 Edge Loop，就可以直接交给 Blender Bridge。项目不需要为两侧建立逐段对应，也不需要先让两侧分段相同。

## 不得恢复的内容

- residual ownership / maximal-chain pairing；
- short-component setback 与逐 Edge exactly-once 作为 Bridge 门槛；
- zipper、DP、trim、width matching 或坐标最近关系；
- 因 degree、branch、cycle、重合或零面积记录提前阻止 Bridge；
- 从本文任何旧状态继续 Phase C 实现。

历史 artifact 只用于复盘。当前 Stop 原因是新的 Direct Edge-Loop Bridge 路线尚未完成真实 Operator 验证和正式接入。
