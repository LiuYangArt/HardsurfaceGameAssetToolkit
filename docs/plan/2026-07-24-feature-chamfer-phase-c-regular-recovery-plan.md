# Feature Chamfer Phase C — Blender Bridge 历史 Recovery

日期：2026-07-24
状态：`HISTORICAL / SUPERSEDED / DO NOT RESUME`

> 当前唯一执行计划：[`2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`](./2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md)。

## 保留的有效结论

- 用户已在 Blender 5.1.2 UI 手动验证普通 `Bridge Edge Loops` 能连接 Edge 数不同的两条 open loop；
- 真实 5-vs-3 输入已成功生成 8 个 Faces；
- 普通 Bridge 不启用 Merge，因此不受 Merge 模式的 equal-count 限制；
- Blender 可以扩展较短的一侧并生成 tri/quad 混合结果；
- Pipe 身份只负责选出左右两组完整边界，不负责逐点 correspondence；
- 失败应回滚，槽外 source 不得改变。

## 历史过度设计

此计划后来加入了逐边 ownership、Face consumer、port/setback、cyclic twist、width envelope、局部 Fill 阶段和大量前置门禁。这些内容把 Blender 已经负责的 Bridge 内部连接重新实现了一遍。

以下内容均已废弃：

- 对两侧 Edge 进行逐条 matching；
- 自研 DP、trim、zipper、rotation 或重采样；
- 为 Bridge 预先清理 duplicate/degenerate 或证明 canonicalization；
- 把 degree、branch、cycle 或零面积中间记录当作 Bridge Stop；
- 从旧 Session Prompt、Gate 或 Step 继续实现。

## 当前边界

当前只验证按 Pipe 自动取得两侧完整 Edge Loop，并一次性交给 Blender Bridge。是否需要额外 Fill、junction 收口或其他处理，必须由真实 Bridge 后的产品结果决定，不能从本文预设。
