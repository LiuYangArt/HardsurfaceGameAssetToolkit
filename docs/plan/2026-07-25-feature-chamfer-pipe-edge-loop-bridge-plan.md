# Feature Chamfer Phase C — Pipe Edge Loop 直接 Bridge 计划

日期：2026-07-25
状态：`AUTHORIZED / PROTOTYPE / PHASE C STOP`

## 1. 产品语义

用户已在 Blender 5.1.2 中确认：一根 Pipe 切出槽后，只需选中槽口左右两侧的完整 Edge Loop，执行 Blender 原生 `Bridge Edge Loops` 即可。

固定规则：

- 左右两侧允许 Vertex / Edge 数量不同；
- 不要求逐 Vertex、逐 Edge 或逐 fragment 对应；
- 不要求预先生成相同分段，也不要求 quad-only；
- Blender 负责不等数量两侧的内部连接，可生成 tri/quad 混合结果；
- 中间 Boolean 数据中的重合点、零面积 Face、degree、branch、cycle 或 canonicalization 诊断，不是 Bridge 的前置门槛；
- 只要能够可靠选中同一根 Pipe 的两侧完整边界，就直接 Bridge，不再研究逐边 pairing 或局部拓扑清理。

## 2. 目标入口契约

```text
UI Feature Chamfer GN
→ hst.feature_chamfer_gn(PREVIEW / FINALIZE)
→ 复用 Preview 的 Pipe cutter
→ Manifold Boolean 生成可见槽
→ 按 Pipe 找出槽面
→ 删除槽面并保留槽口边界
→ 选中该 Pipe 左右两侧完整 Edge Loop
→ Blender Bridge Edge Loops
→ 输出最终 Mesh
```

用户可见结果：Preview 中已经正确的槽形状被保留；Finalize 后槽面由 Blender Bridge 生成，原模型槽外区域不变。

## 3. 实现阶段与 Stop / Go

### Step 1 — 从单根 Pipe 提取两侧完整边界

- 从真实目标 Operator 的 Boolean 结果开始；
- 用 Pipe 身份限定槽面和槽口边界；
- 删除该 Pipe 的槽面后，把留下的边界分成左右两组完整选择集合；
- 左右名称只表示两组输入，不表达逐边对应关系。
- 允许一侧完整边界在 Mesh 拓扑上包含局部汇合或复用顶点；这里的 Edge Loop 是用户产品语义中的完整槽边选择集合，不额外要求所有 Vertex 的 degree 都等于 2。

Go：同一根 Pipe 能稳定得到两组完整边界，且不混入其他 Pipe 或槽外 Edge。
Stop：无法确定哪两组边属于该 Pipe，或者选择范围混入其他槽。

以下情况不得单独触发 Stop：两侧数量不同、中间数据有重合/零面积记录、局部 degree>2、cycle、缺少逐边身份或无法建立 raw→canonical 映射。

### Step 2 — 直接调用 Blender Bridge

- 将两组完整边界一次性交给 Blender 原生 Bridge；
- 使用普通 Bridge，不启用 Merge；
- 不在调用前执行逐边匹配、重采样、Merge by Distance、局部 rebuild 或自研 zipper。

Go：Blender 返回 Bridge Faces，选中的两侧均被连接。
Stop：Bridge 没有生成 Faces、连接到其他 Pipe，或产生明显翻面、跨槽连接。

### Step 3 — 真实目标验证

按以下顺序从目标 Operator 运行：

1. `tricky / Solid.004 / r0.03`；
2. `tricky / Solid.004 / r0.01`；
3. `mixed / Extruded.002 / r0.03`。

每个目标保存可打开的 `.blend` 和固定近景，检查：

- Bridge 后槽面连续，视觉结果符合用户截图；
- 槽外原模型没有变化；
- 输出没有意外开放边或多面共边；
- 正逆 batch 顺序结果一致；
- 失败会完整回滚，不留下半成品。

三个目标都通过后，才进入正式接入。

### Step 4 — 正式接入与完整矩阵

- 将相同流程接入正式 `FINALIZE`；
- 从 UI 入口运行完整 14 cells × 3 repetitions；
- 保存每个 cell 的结果、日志和近景；
- 独立 Spec Audit 核对正式 runtime 确实走 Pipe 两侧完整边界 → Blender Bridge，而不是历史 pairing/canonicalization 旁路。

Go：完整矩阵和回滚门禁通过，目标 Operator 与视觉结果通过。
Stop：任何目标只能靠 fixture 特判、距离猜 Pipe、忽略 Bridge 失败或修改槽外模型才能通过。

## 4. 四层验收

1. `Algorithm`：不等数量的两组 open Edge Loop 可直接 Bridge；已有 5-vs-3 证据继续保留。
2. `Backend`：真实 Pipe 能提取两侧完整边界并生成 Bridge Faces。
3. `Operator`：正式 UI/Operator 已接入该路径，失败可回滚。
4. `Visual/Product`：三个重点目标及完整矩阵的真实文件和固定近景通过。

低层通过不能替代高层。当前仍为 `PROTOTYPE / PHASE C STOP`，尚未接入正式 runtime。

## 5. 明确废弃

以下内容不再是当前实现方向或 Bridge 前置条件：

- source Edge → opposite Edge 的逐条 pairing；
- maximal source/candidate chain 的逐段独占关系；
- 两侧相同 Vertex/Edge 数量；
- Bridge 前先解决 duplicate/degenerate/canonicalization；
- 以 degree、branch、cycle 或零面积诊断阻止已正确选中的两侧 Edge Loop 进入 Bridge；
- 通过 Merge、局部重建、重采样或坐标最近关系制造两侧对应。

历史探针和 artifact 只保留为排查记录，不能再决定当前 Stop / Go。

## 6. 当前下一步

先在 `tricky / Solid.004 / r0.03` 上，从目标 Operator 的 Manifold Boolean 结果按 Pipe 提取两侧完整边界，直接执行 Blender Bridge，并输出可检查 `.blend` 与近景。通过后再依次验证另外两个目标。
