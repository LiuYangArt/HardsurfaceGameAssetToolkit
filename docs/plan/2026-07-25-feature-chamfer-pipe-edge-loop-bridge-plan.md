# Feature Chamfer Phase C — Pipe Edge Loop 直接 Bridge 计划

日期：2026-07-25
状态：`AUTHORIZED / INTEGRATED / PRODUCT GATE PENDING`

2026-07-25 规格补充：Boundary Edge acquisition 已由受控 Boolean Pro 的
`Boundary Edges` 输出解决。正式 Preview 已将该 selection 保存到 evaluated
Mesh 的 EDGE 域；本阶段禁止再从槽面、FaceGraph、坐标距离或 Boolean 后
identity 恢复去反推切口边。

## 1. 产品语义

用户已在 Blender 5.1.2 中确认手工补面语义：没有交叉的连续 Pipe 槽，选中
槽口左右两侧完整 Edge Loop，执行 Blender 原生 `Bridge Edge Loops`；Pipe 与另一根
Pipe 交叉时，原本连续的槽必须在交叉区域两端断开，分别对每个“交叉点之间的连续
槽段”左右两侧完整边链执行 Bridge，最后对所有 Bridge 后剩余的交叉处孔洞执行 Fill。

固定规则：

- 左右两侧允许 Vertex / Edge 数量不同；
- 不要求逐 Vertex、逐 Edge 或逐 fragment 对应；
- 不要求预先生成相同分段，也不要求 quad-only；
- Blender 负责不等数量两侧的内部连接，可生成 tri/quad 混合结果；
- 中间 Boolean 数据中的重合点、零面积 Face、degree、branch、cycle 或 canonicalization 诊断，不是 Bridge 的前置门槛；
- 配对单位是交叉点之间的连续槽段，不是整根 Pipe，也不是整个连通 cutter network；
- 只要能够可靠选中同一槽段的左右两侧完整边链，就直接 Bridge，不研究 loop 内逐点、逐边 pairing；
- junction Fill 只消费所有槽段 Bridge 后自然剩余的交叉孔洞，不得提前用 Fill 替代可 Bridge 的普通槽段。

## 2. 目标入口契约

```text
UI Feature Chamfer GN
→ hst.feature_chamfer_gn(PREVIEW / FINALIZE)
→ 复用 Preview 的 Pipe cutter
→ Boolean Pro 生成可见槽与 Boundary Edges
→ 从 Boundary Edges 按 Pipe 与 junction 交叉处切出连续槽段
→ 将同一槽段左右两侧的完整边链配成一组
→ Blender Bridge Edge Loops
→ Fill Bridge 后剩余的 junction 孔洞
→ 输出最终 Mesh
```

用户可见结果：Preview 中已经正确的槽形状被保留；Finalize 后普通槽段由
Blender Bridge 生成、交叉孔洞由 Fill 封闭，原模型槽外区域不变。

## 3. 实现阶段与 Stop / Go

### Step 1 — 复用 Boolean Pro Boundary Edges

- 从真实目标 Operator 的 Boolean Pro evaluated result 开始；
- 直接读取 Boolean Pro 已输出的全部切口 Boundary Edges；
- 不再自行探测、恢复或重建 Boundary Edge identity；
- 没有 junction 的 cyclic 槽保留两条完整 cyclic Edge Loop；
- 在 junction 处，以 Boundary Edge 的多 Pipe owner 变化作为确定性交叉边界，把全局 Loop 切成单一 Pipe 的连续 runs；若交叉只在槽的一侧产生切点，则使用 Preview Pipe 同槽段携带的归一化弧长 station，在另一侧唯一对应的边内同步插入切点。station 只同步已经由 Pipe/槽段/Surface Patch 身份锁定的两侧，不承担 Pipe 猜测或逐边配对；
- 不按 edge 数、edge 长度或世界坐标选择“较大两条”，不按距离恢复 Pipe，不重排原始 Boundary Edge；
- 将同一 Pipe 在相邻两个 junction 之间、或 junction 与 terminal 之间的左右两条连续 run 配成一个槽段 Bridge job；
- 左右名称只表示两组输入，不表达逐边对应关系。
- 这里的“完整”是对单个槽段而言：从一个 junction/terminal 边界连续走到另一个 junction/terminal 边界；不得把跨过 junction 的整根 Pipe 强行视为一个 Bridge job。

Go：Boolean Pro Boundary Edges 被完整分成槽段左右边链与 junction 孔洞边界；每个 Bridge job 恰好包含同一槽段的两条完整边链，且不跨过 junction 或混入其他槽。
Stop：无法确定某条连续 run 的 Pipe owner、无法确定同槽段的另一侧，或者槽段范围跨过 junction / 混入其他槽。

以下情况不得单独触发 Stop：两侧数量不同、中间数据有重合/零面积记录、局部 degree>2、cycle、缺少逐边身份或无法建立 raw→canonical 映射。

Boundary Edge acquisition 已解决，不得恢复以下路线：从 Groove Faces 反推边界、
FaceGraph、坐标最近猜 Pipe、canonicalization、raw→canonical 或重新执行另一套
Object Boolean。当前唯一剩余算法问题是按 junction 切分完整槽段、同槽段两侧
配对，以及 Bridge 后剩余 junction 孔洞的 Fill。

当前接入状态：正式 Preview 已输出全局 Boundary Edge selection；受控 Boolean Pro
在每个 solver 的真实 Difference 输出上，把冻结 Pipe 合同中的槽段归属直接物化到
同一批 Boundary Edges。正式 Finalize 已消费该 evaluated Preview，按槽段选择两侧
完整边链并调用 Blender Bridge；它不再走历史后端，也不通过坐标最近关系猜 Pipe。

验证过但未采用的身份传播 spike：给 Preview 每条 Curve spline 写 Pipe ID 后，
Boolean Pro 只把它保留为 POINT 属性；287 条 Boundary Edges 中有 139 条两端为
默认值，另有多组默认值/不同 Pipe 混合端点。该字段不足以确定 Loop→Pipe 归属，
因此没有接入正式资产或 Finalize。

同时确认 source Surface Patch 身份能够随 Boolean Pro 保留，但多个 Pipe 可共享同一
Patch，单个 Loop 也可能跨多个 Patch；仅凭 Patch 不能唯一确定同槽配对。上述两项
只用于判定确定性不足，不把 Boundary Edge acquisition 重新解释为身份恢复问题。

Boolean Pro 内部采用的确定性分组接缝：在各 Boolean solver 的 Geometry B
进入求解前写 per-Pipe one-hot，并在同一 solver 输出 Geometry 上用它自己的
Intersecting Edges selection 立即物化为 EDGE 属性。该做法只写属性，不改变现有
Boolean 几何链；必须以正式输出 Mesh 指纹不变验证。单个整数 Pipe ID 会在多 Pipe
相交时丢失或择一，不能作为 owner 合同；第一阶段只允许 one-hot/多 owner 表达。

以下为历史 metadata spike 记录，不代表当前产品门禁通过。2026-07-25
`simple / Solid 44 / radius 0.01` 接缝 spike 已完成：正式 Preview
包含 13 根 Pipe spline、287 条 Boolean Pro Boundary Edges 和 14 个完整 cyclic
Loop。one-hot 在 Manifold solver 的实际 Difference 输出上物化后，输出
`287 vertices / 332 edges / 55 faces` 与写入前 Mesh 指纹完全一致，287/287 条
Boundary Edge 都有 Pipe 标记，证明 metadata 接缝可用且不改变几何。

该 spike 曾暴露 14 个全局完整 Loop 不是按每根 Pipe 两个 Loop 分区：多个 Loop 会在
junction 周围切换 Pipe 标记，同一 Pipe 也可能出现在多个 Loop 中。用户提供的手工
补面截图已解除此 Stop：全局 Loop 只作为 Boundary acquisition 结果；真正 Bridge
输入必须在 junction 处切成同一 Pipe 的连续槽段边链。这里允许按 owner 变化切分
全局 Loop，但禁止恢复逐边 correspondence、最近距离、dominant Pipe、坐标重建、
canonicalization 或 Bridge 后择优。

这是对正式 Preview 所持有的 Boolean Pro 副本补充分组 metadata，不是重新获取
Boundary Edges，也不改变共享资产。若 metadata 导致 Boolean 几何变化或无法覆盖
当前 solver 分支，则继续 Stop，不得退回 wrapper 输出后补写、坐标最近或另做 Boolean。

### Step 2 — 直接调用 Blender Bridge

- 将两组完整边界一次性交给 Blender 原生 Bridge；
- 使用普通 Bridge，不启用 Merge；
- 不在调用前执行逐边匹配、重采样、Merge by Distance、局部 rebuild 或自研 zipper。

Go：Blender 返回 Bridge Faces，选中的两侧均被连接。
Stop：Bridge 没有生成 Faces、连接到其他 Pipe，或产生明显翻面、跨槽连接。

### Step 2.5 — Fill junction 孔洞

- 所有可配对槽段必须先 Bridge；
- 在 Bridge 后 Mesh 上，仅收集自然剩余的 junction 孔洞边界；
- 每个孔洞一次交给 Blender Fill，禁止 center fan、fixture 特判或提前填掉普通槽段；
- Fill 失败必须完整回滚，不保留半成品。

Go：所有槽段 Bridge 已消费，剩余孔洞只位于 Pipe 交叉处；Fill 后最终 Mesh 封闭，没有跨孔连接、翻面或槽外变化。
Stop：剩余孔洞包含尚未 Bridge 的普通槽段、多个 junction 被错误连成一个孔，或 Fill 没有生成有效 Faces。

### Step 3 — 第一阶段优先验证

第一阶段优先让 `tricky` 以外的三个测试文件可用：

1. `simple`：2 个对象 × 2 个 radius，共 4 个 cell；
2. `tricky_b`：2 个对象 × 2 个 radius，共 4 个 cell；
3. `mixed`：1 个对象 × 2 个 radius，共 2 个 cell。

`tricky` 的 2 个对象 × 2 个 radius 共 4 个 cell 延后到第二阶段；它们允许安全失败，不阻塞第一阶段交付。

每个目标保存可打开的 `.blend` 和固定近景，检查：

- Bridge 后槽面连续、junction Fill 正确，视觉结果符合用户截图；
- 槽外原模型没有变化；
- 输出没有意外开放边或多面共边；
- 正逆 batch 顺序结果一致；
- 失败会完整回滚，不留下半成品。

第一阶段 Go：上述三个优先文件的 10 个 cell 全部从目标 Operator 得到 `PRODUCT_SUCCESS`；`tricky` 即使失败，也必须保持 source 不变、完整回滚且不留下半成品。不得用 fixture 特判换取这 10 个 cell 通过。

### Step 4 — 第一阶段正式验收与分层矩阵

- 确认正式 `FINALIZE` 已接入相同流程；
- 从 UI 入口先运行优先 10 cells × 3 repetitions；
- 另外运行或记录 `tricky` 4 cells 的安全失败结果，但不计入第一阶段产品成功率；
- 保存每个 cell 的结果、日志和近景；
- 独立 Spec Audit 核对正式 runtime 确实走槽段两侧完整边链 → Blender Bridge → junction Fill，而不是历史 pairing/canonicalization 旁路。

Go：优先 10 cells 全部通过，目标 Operator、视觉结果、source 不变和回滚门禁通过；此时可作为第一阶段可用成果交付。
Stop：任一优先 cell 只能靠 fixture 特判、距离猜 Pipe、忽略 Bridge/Fill 失败或修改槽外模型才能通过。

第二阶段再处理 `tricky` 4 cells。它们全部通过后，才把范围提升为完整 14-cell 产品矩阵通过。

## 4. 四层验收

1. `Algorithm`：不等数量的两组 open Edge Loop 可直接 Bridge；已有 5-vs-3 证据继续保留。
2. `Backend`：真实 Pipe 能在 junction 处切出槽段、Bridge 两侧边链并 Fill 剩余交叉孔洞。
3. `Operator`：正式 UI/Operator 已接入“槽段 Bridge → junction Fill”，失败可回滚。
4. `Visual/Product`：第一阶段先要求 `simple / tricky_b / mixed` 三个文件的 10 个 cell 真实文件和固定近景通过；`tricky` 留到第二阶段。

低层通过不能替代高层。当前为 `INTEGRATED / PRODUCT GATE PENDING`：正式 Operator runtime
已经接入，但优先 10 cells、固定近景与独立 Spec Audit 尚未全部通过，因此还不是
`VERIFIED` 或 `ACCEPTED`。

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

正式入口已经接入，优先 10 cells 的三次重复自动证据也已生成；但固定近景发现
`tricky_b / Extruded.002 / radius 0.03` 的 junction 区域存在明显错面，因此当前仍停在
`INTEGRATED / PRODUCT GATE PENDING`，自动闭合检查不得替代视觉失败。下一步先修正
“全部槽段 Bridge 后再 Fill junction”的视觉结果，再完整重跑优先 10 cells、保存可读
`.blend` 与固定近景；随后单独记录 `tricky` 4 cells 的安全结果并执行独立 Spec Audit。

本轮已把该视觉失败定位为真实几何自交：原实现把一条仍跨越 junction 的连续边链
整段交给 Bridge，会产生 147 组非邻接面相交。按截图语义在交叉 witness 两端分段后，
Bridge 阶段已降为 0；Fill 后仍有 6 组相交，全部来自同一个由 segment 13/18 与
四条 Bridge 连接边组成的 12-edge junction 孔。正式 Operator 现会检测并完整回滚，
不再把“封闭但自交”的结果误报为产品成功。剩余工作是让该交叉区域形成手工操作中
实际可见的独立孔洞，再逐孔 Fill，而不是把跨空间的整圈直接当作一个孔。
