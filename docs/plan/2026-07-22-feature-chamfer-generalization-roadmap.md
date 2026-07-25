# Feature Chamfer 通用化历史 Roadmap

日期：2026-07-22
状态：`HISTORICAL / SUPERSEDED / DO NOT RESUME`

> 当前唯一执行计划：[`2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`](./2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md)。

## 历史用途

本文曾把 Feature Chamfer 通用化拆成 Preview 计划、Boolean、Boundary 绑定、junction、rail correspondence 和产品矩阵等阶段。它建立了真实文件矩阵、目标 Operator 验收和分层证据规则，但后续把 Bridge 输入选择问题扩展成了逐边 correspondence 与完整消费账本。

## 仍然有效的基线

- 目标入口始终是 UI `Feature Chamfer GN` → `PREVIEW / FINALIZE`；
- Preview 和 Finalize 必须复用同一 Pipe/Radius 语义；
- 测试输入来自仓库内四个 fixture，共 7 个对象 × 两个 radius，即 14 个 cell；
- 定向 probe、少量回归或安全停止不能冒充产品成功；
- source 不得被误改，失败必须回滚；
- 最终需要从目标 Operator 保存可检查 `.blend`、固定近景和结构化结果；
- 完整矩阵与独立 Spec Audit 通过前，不能声明 `VERIFIED`。

## 已废弃内容

- 把 degree、branch、cycle 当作必须先解决的 Boundary 阻塞；
- 为左右槽边建立逐 Vertex / Edge / fragment correspondence；
- 要求左右两侧相同采样数；
- 自研 zipper、DP、trim、rotation 或 seam 选择来替代 Blender Bridge；
- 以 duplicate、zero-area 或 canonicalization 诊断阻止已正确选中的两侧 Edge Loop；
- 依据历史失败家族继续实现旧 Phase 3–5。

## 当前解释

用户已在 Blender 5.1.2 中确认：同一根 Pipe 的槽口两侧完整 Edge Loop 可以直接执行普通 Bridge，两侧 Edge 数量不同没有问题，Blender 会自行生成 tri/quad 混合连接。

因此当前工作只需解决“按 Pipe 取得正确的两组完整 Edge Loop”，再验证实际 Bridge 结果；本文不再包含任何可执行的下一步。
