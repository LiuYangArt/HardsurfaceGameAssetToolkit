# Feature Chamfer Phase C — Pipe Edge Loop 直接 Bridge 计划

日期：2026-07-25
状态：`AUTHORIZED / VERIFIED`（尚未由用户在真实 UI 中 `ACCEPTED`）

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

失败与半径重试规则：

- “完整回滚”只指 source 与最终产品事务：source Mesh、变换和已有数据保持不变，坏的最终 Mesh 不得交付；它不等于删除诊断现场；
- 当前 Radius 无法安全补面时，正式 Finalize 必须保留同一 Preview，并在失败边界留下醒目的红色诊断，直接告诉用户此处空间不足或边界过于复杂，建议减小 Radius 后重试；
- Radius 只能由用户显式修改后重新执行 Preview → Finalize；Operator 不得自动或静默降低 Radius；
- 原请求 Radius 必须如实记录为 `RADIUS_LIMIT_DIAGNOSTIC`，不能伪装成成功。若同一对象由正式 Operator 在明确更小的 Radius 得到 `PRODUCT_SUCCESS`，该场景可记为 `PRODUCT_SUCCESS_WITH_RADIUS_RETRY`，并同时保留失败 Radius 与成功 Radius 两份证据；
- 只有失败位置可见、source 不变、坏输出不存在、较小 Radius 正式成功四项同时成立，才允许按“降低半径后通过”计入阶段验收。其他 Bridge/Fill 或产品失败不得借此放行。
- 红色位置合同只适用于已经得到真实边界坐标的 Bridge、Fill 或最终几何失败。若流程在尚未形成可定位边界的 Preview/身份合同阶段停止，应保留已有 Preview、保持 source 不变并给出明确错误提示；不得为了满足视觉形式而猜测或伪造问题位置。

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
Blender Bridge 生成、交叉孔洞由 Fill 封闭，原模型槽外区域不变。若当前 Radius
无法可靠完成，用户会在保留的 Preview 上直接看到红色问题边界和减小 Radius 的提示。
Bridge/Fill 新面在尚未恢复 Custom Normal 时可能显示为黑色三角或楔形；这属于 shading
诊断，不等同于孔洞。正式产品验收必须先确认边界已封闭，再启用与旧 Feature Chamfer
一致的 source Custom Normal Transfer 后检查最终视图；不得用关闭法线传递的诊断图否决
已经完整补面的结果。
孔洞只由真实 Mesh 边界、non-manifold 结果和 Blender 线框拓扑确认；禁止用渲染图中的
极暗像素数量、黑色连通块或类似颜色阈值推断孔洞，因为这些指标会把线框、轮廓、阴影
和 Custom Normal 一并误计。

最终法线处理按旧 Feature Chamfer 的既有模式：完成全部 Bridge / Fill 并重新计算几何
朝向后，从 source 传递 Custom Normal；若还需要对新补面执行 Set from Faces，必须以真实
Blender 结果证明它不会被后续传递覆盖。产品近景必须使用正式输出的最终法线结果。

## 3. 实现阶段与 Stop / Go

### Step 1 — 复用 Boolean Pro Boundary Edges

- 从真实目标 Operator 的 Boolean Pro evaluated result 开始；
- 直接读取 Boolean Pro 已输出的全部切口 Boundary Edges；
- 不再自行探测、恢复或重建 Boundary Edge identity；
- 没有 junction 的 cyclic 槽保留两条完整 cyclic Edge Loop；
- 在 junction 处，以 Boundary Edge 的多 Pipe owner 变化作为确定性交叉边界，把全局 Loop 切成单一 Pipe 的连续 runs；若交叉只在槽的一侧产生切点，则使用 Preview Pipe 同槽段携带的归一化弧长 station，在另一侧唯一对应的边内同步插入切点。station 只同步已经由 Pipe/槽段/Surface Patch 身份锁定的两侧，不承担 Pipe 猜测或逐边配对；
- 实现中的 edge-count、局部长度和 station 数值阈值，只用于已经锁定 Pipe、槽段和 Surface Patch 后的 junction witness 有效性与切点分段；它们不得用于猜 Pipe、从候选中挑“较像”的两侧，也不得成为普通完整 Loop 进入 Bridge 的前置门槛；
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
- Fill 或 Fill 后几何检查失败必须回滚 source 与最终输出，不保留坏 Mesh；有真实孔洞边界坐标时，同时保留 Preview并在该边界留下红色诊断。

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
- 输出保持旧 Feature Chamfer 的 source Custom Normal Transfer，固定近景必须使用正式法线结果；
- 槽外原模型没有变化；
- 输出没有意外开放边或多面共边；
- 正逆 batch 顺序结果一致；
- 可定位的 Bridge/Fill/最终几何失败必须 source 不变且没有坏输出，同时 Preview 与红色问题位置可见；更早的合同失败保留已有现场与明确提示；
- 用户显式降低 Radius 的重试与原 Radius 结果分开记录，Operator 不静默改值。

第一阶段 Go：上述三个优先文件的 10 个目标场景均从目标 Operator 得到
`PRODUCT_SUCCESS`，或满足严格四项条件的 `PRODUCT_SUCCESS_WITH_RADIUS_RETRY`；
后者必须保留原 Radius 的 `RADIUS_LIMIT_DIAGNOSTIC` 与更小 Radius 的独立成功证据，
不得把原失败档位改写为成功。`tricky` 即使失败，也必须保持 source 不变、无坏输出；
可定位的几何失败保留红色位置，较早的合同失败保留已有现场和明确提示。不得用 fixture
特判换取这 10 个场景通过。

### Step 4 — 第一阶段正式验收与分层矩阵

- 确认正式 `FINALIZE` 已接入相同流程；
- 从 UI 入口先运行优先 10 cells × 3 repetitions；若某个 cell 触发半径限制，另以用户显式操作等价的独立 Operator 调用验证更小 Radius；
- 另外运行或记录 `tricky` 4 cells 的安全失败结果，但不计入第一阶段产品成功率；
- 保存每个 cell 的结果、日志和近景；
- 独立 Spec Audit 核对正式 runtime 确实走槽段两侧完整边链 → Blender Bridge → junction Fill，而不是历史 pairing/canonicalization 旁路。

Go：优先 10 个目标场景全部直接通过或严格满足“降低半径后通过”，目标 Operator、视觉结果、source 不变、诊断可见和回滚门禁通过；此时可作为第一阶段可用成果交付。
Stop：任一优先 cell 只能靠 fixture 特判、距离猜 Pipe、忽略 Bridge/Fill 失败或修改槽外模型才能通过。

第二阶段再处理 `tricky` 4 cells。它们全部通过后，才把范围提升为完整 14-cell 产品矩阵通过。

## 4. 四层验收

1. `Algorithm`：不等数量的两组 open Edge Loop 可直接 Bridge；已有 5-vs-3 证据继续保留。
2. `Backend`：真实 Pipe 能在 junction 处切出槽段、Bridge 两侧边链并 Fill 剩余交叉孔洞。
3. `Operator`：正式 UI/Operator 已接入“槽段 Bridge → junction Fill”；失败可回滚 source 与坏输出；可定位的几何失败保留 Preview 和红色问题位置供用户调小 Radius，较早的合同失败保留已有现场和明确提示。
4. `Visual/Product`：第一阶段先要求 `simple / tricky_b / mixed` 三个文件的 10 个 cell 真实文件和固定近景通过；`tricky` 留到第二阶段。

低层通过不能替代高层。当前为 `VERIFIED`：正式 Operator runtime、优先 10 cells、
最终法线后的固定近景和独立 Spec Audit 均已通过。用户尚未在真实 UI 中验收，因此不是
`ACCEPTED`。

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

正式入口已经接入 Direct Edge-Loop Bridge 与 junction Fill。最终自动矩阵
`tests/artifacts/feature_chamfer_phase1_normal_final/results.json` 中，
`simple / tricky_b / mixed` 的 10 个第一阶段目标场景均在原请求 Radius 直接得到
`PRODUCT_SUCCESS`，每项连续 3 次稳定，source 不变，最终 Mesh 无开放边、无多面共边、
无零面积 Face，并保留正式 source Custom Normal Transfer；这份证据支持 Algorithm、
Backend 和 Operator 三层，不单独构成视觉通过。

延后范围 `tests/artifacts/feature_chamfer_tricky_safety_normal_final/results.json` 中的
4 个 `tricky` cell 均连续 3 次 `SAFETY_PASS`：source 不变、没有坏输出；其中可运行
Preview 的失败保留 Preview，尚未形成真实边界坐标的早期失败不伪造红色位置。该结果
满足第一阶段的 deferred safety，不代表第二阶段产品成功。

先前把固定近景中的黑色三角判成缺面属于错误验收：用户已确认它是 Fill 新面的
Custom Normal 表现，渲染颜色阈值也已明确废弃。现有输出原本已复用旧 Feature Chamfer
的 source Normal Transfer。额外尝试“新面 Set from Faces、原区域 Normal Transfer”时，
发现 Vertex Group 无法准确表达 shared boundary loop 的逐 corner 法线归属，不能作为正确
实现接入。当前保留旧工具的全量 Normal Transfer，并把法线表现与真实孔洞分开验收；
最终法线后的全部 10 个目标 cell 均保存 overview / wireframe 固定近景；视觉验收没有
使用极暗像素或颜色阈值。逐项肉眼复核未发现跨槽、翻面、异常长三角、未 Fill 孔洞或
槽外明显变化。状态提升为 `VERIFIED`，但尚未由用户在真实 UI 中 `ACCEPTED`。

正式入口相关的 5 项重点回归已经通过；独立 Spec Audit 也确认 runtime 为
Boolean Pro Boundary Edges → junction 分段 → Blender Bridge → residual Fill → 正式法线恢复，
没有 fixture 特判、逐边 pairing 或 Bridge 前 canonicalization。完整项目回归共 145 项；
首次运行 143 项通过，2 项为仍断言旧 Preview 直连与旧 Boundary binding 字段的过时预期，
已更新为验证当前属性链和 Direct Bridge runtime；这 2 项随后在同一最终代码上单独通过，
因此本轮变更相关的 145 项均有通过证据。提交前保留上述
自动矩阵、固定近景、重点回归、完整回归与独立审计证据。用户真实 UI 验收前不声明
`ACCEPTED`。
