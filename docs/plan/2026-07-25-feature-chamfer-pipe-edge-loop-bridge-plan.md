# Feature Chamfer Phase C — Pipe Edge Loop 直接 Bridge 计划

日期：2026-07-25
状态：`VERIFIED`（simple cyclic 共同切点、Tricky-b 输入清理与第一阶段 10-cell 正式入口均已通过；等待用户真实 UI 复核后再决定是否 `ACCEPTED`）

2026-07-25 规格补充：Boundary Edge acquisition 已由受控 Boolean Pro 的
`Boundary Edges` 输出解决。正式 Preview 已将该 selection 保存到 evaluated
Mesh 的 EDGE 域；本阶段禁止再从槽面、FaceGraph、坐标距离或 Boolean 后
identity 恢复去反推切口边。

## 1. 产品语义

用户已在 Blender 5.1.2 中确认手工补面语义：没有交叉的连续 Pipe 槽，选中
槽口左右两侧完整 Edge Loop，执行 Blender 原生 `Bridge Edge Loops`；Pipe 与另一根
Pipe 交叉时，原本连续的槽必须在交叉区域两端断开，分别对每个“交叉点之间的连续
槽段”左右两侧完整边链执行 Bridge，最后对所有 Bridge 后剩余的交叉处孔洞执行 Fill。
原生 Bridge 若在已确认的 open 左右链之间生成明显越过槽宽的内部连接，则产品门禁失败；
不得用自定义逐点、逐边对应替换原生 Bridge。对于已经确认配对正确、但包含多个显著
空间转折且整段原生 Bridge 可复现跨槽错连的 open 槽段，允许在两侧共同的大转折边界
同步切成较短的连续子段，再逐段调用原生 Bridge。配对正确的 cyclic 左右 Boundary Loop
若因两侧采样差异导致整环原生 Bridge 扭曲，也允许在 Boolean 完成后、Bridge 调用前按共同
环绕 station 划成局部弧段。两类分段都只限定 Bridge job 的范围，不修改 Cutter Curve、
不修改 Boolean 切槽结果，不生成逐点对应、不重采样、不重建边界。正式 fail-closed 门禁
只有在不误拦既有正确场景时才能接入。

固定规则：

- 左右两侧允许 Vertex / Edge 数量不同；
- 不要求逐 Vertex、逐 Edge 或逐 fragment 对应；
- 不要求两侧预先具有相同 Edge/Vertex 分段，也不要求 quad-only；允许用两侧共同的显著
  转折或共同 cyclic station 作为 Bridge job 边界，但不得为了等点数而细分或重采样；
- Blender 负责不等数量两侧的内部连接，可生成 tri/quad 混合结果；若结果越过槽宽则
  产品不能通过；
- 中间 Boolean 数据中的重合点、零面积 Face、degree、branch、cycle 或 canonicalization 诊断，不是 Bridge 的前置门槛；
- 配对单位是交叉点之间的连续槽段，不是整根 Pipe，也不是整个连通 cutter network；
- 只要能够可靠选中同一槽段的左右两侧完整边链，就直接 Bridge；若整段包含多个显著
  转折且原生 Bridge 产生跨槽错连，则先按两侧共同转折切成完整连续子段；若两侧均为
  完整 cyclic Boundary Loop，则只在 Bridge 前按冻结 Pipe 合同的共同环绕 station 逻辑分段。
  不得用距离、fixture 身份或自定义逐点对应生成补面；
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
诊断，不等同于孔洞。正式产品验收必须先确认边界已封闭；法线视觉恢复本轮不再作为
急角 Curve 修复的 Stop / Go，也不得用关闭法线恢复的诊断图否决
已经完整补面的结果。
孔洞只由真实 Mesh 边界、non-manifold 结果和 Blender 线框拓扑确认；禁止用渲染图中的
极暗像素数量、黑色连通块或类似颜色阈值推断孔洞，因为这些指标会把线框、轮廓、阴影
和 Custom Normal 一并误计。

法线问题暂缓：正式 FINALIZE 不执行法线恢复，也不接入本轮试验的 Set from Faces、
全对象 Data Transfer、烘焙、新面 flat shading 或 Corner 重写。后续单独以更简单的
法线方案处理。

## 3. 实现阶段与 Stop / Go

### Step 1 — 复用 Boolean Pro Boundary Edges

- 从真实目标 Operator 的 Boolean Pro evaluated result 开始；
- 直接读取 Boolean Pro 已输出的全部切口 Boundary Edges；
- 不再自行探测、恢复或重建 Boundary Edge identity；
- Cutter Curve 与 Boolean 切槽阶段，没有 junction 的 cyclic Pipe 必须保持完整闭环，以生成
  连续干净的槽；Boolean 输出的两条 Boundary Loop 也必须先以完整环参与配对和身份校验；
- 在 junction 处，以 Boundary Edge 的多 Pipe owner 变化作为确定性交叉边界，把全局 Loop 切成单一 Pipe 的连续 runs；若交叉只在槽的一侧产生切点，则使用 Preview Pipe 同槽段携带的归一化弧长 station，在另一侧唯一对应的边内同步插入切点。station 只同步已经由 Pipe/槽段/Surface Patch 身份锁定的两侧，不承担 Pipe 猜测或逐边配对；
- 实现中的 edge-count、局部长度和 station 数值阈值，只用于已经锁定 Pipe、槽段和 Surface Patch 后的 junction witness 有效性、共同大转折确认与切点分段；它们不得用于猜 Pipe、从候选中挑“较像”的两侧，也不得成为普通完整 Loop 进入 Bridge 的前置门槛；
- 不按 edge 数、edge 长度或世界坐标选择“较大两条”，不按距离恢复 Pipe，不重排原始 Boundary Edge；
- 将同一 Pipe 在相邻两个 junction 之间、或 junction 与 terminal 之间的左右两条连续 run 配成一个槽段 Bridge job；
- 左右名称只表示两组输入，不表达逐边对应关系。
- 这里的“完整”首先是对单个槽段而言：从一个 junction/terminal 边界连续走到另一个
  junction/terminal 边界；不得把跨过 junction 的整根 Pipe 强行视为一个 Bridge job。
  对已锁定的复杂 open 槽段，显著转折可以继续成为子段边界；全部子段必须按顺序、无重叠、
  无遗漏地覆盖原左右链。

Go：Boolean Pro Boundary Edges 被完整分成槽段左右边链与 junction 孔洞边界；每个 Bridge
job 恰好包含同一槽段的两条完整边链，或由共同显著转折确定的一对连续子链，且不跨过
junction、不混入其他槽，所有子段合计完整覆盖原槽段。
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

- 普通、短且形态单一的槽段，将两组完整边界一次性交给 Blender 原生 Bridge；
- 对已确认配对正确但包含多个显著空间转折的 open 槽段，先忽略重合短边等数值噪声，
  以链的累计弧长与局部转向确认两侧共同的大转折；仅在双方都有唯一对应转折时同步切段；
- 共同转折逐处独立生效：任何 open 槽段只要两侧在同一 station 区间都存在唯一、显著的
  局部转折，就在该处同步切段；不设置累计转向或最少转折数量门槛，也不要求特定 U 形复杂度；
- cyclic 的 Cutter Curve、Boolean 槽和 Bridge 配对输入保持完整闭环，不走 open 槽段转折
  分段；仅在上述阶段全部完成后，Bridge 预处理可按冻结 Pipe 合同的共同环绕 station 将
  一对完整 cyclic Boundary Loop 逻辑划成局部开放弧段，原环 Edge 全集不得改变；
- 普通直段与单侧转折保持原任务；有效冻结 cyclic 合同内的重复 plateau 必须以两侧局部
  Boundary 邻接关系确定共同切点，不得取消、跳过或回退整环；
- 每一对子段分别交给 Blender 原生 Bridge；不得新增 Vertex、不得把一侧投影到另一侧、
  不得按最近距离建立逐点关系；
- 子段必须保持原链拓扑顺序，首尾连续且 Edge 全集无重叠、无遗漏；相邻子段只共享已有
  Boundary Vertex。open 共同转折无法同步属于合同失败；cyclic 有效合同中的非连续重复
  station 必须完成确定性消歧，不能作为产品安全停止路径；
- 使用普通 Bridge，不启用 Merge；
- 不在调用前执行逐边匹配、重采样、跨侧 Merge by Distance、局部 rebuild 或自研 zipper；
  允许按下文严格规则分别清理每侧极近点与无形状影响的共线零散点。

Go：每个普通槽段或转折子段均由 Blender 返回 Bridge Faces，选中的两侧全部被连接，
子段合计完整消费原左右链。
Stop：共同转折无法同步、cyclic provenance 缺失、子段覆盖不完整、Bridge 没有生成 Faces、连接到其他 Pipe，
或产生明显翻面、跨槽连接。

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
2. `tricky_b`：长期范围为 2 个对象 × 2 个 radius，共 4 个 cell；本轮 cyclic 修复不运行
   `Extruded.002` Radius `0.03`，临时门禁只计其余 3 个；
3. `mixed`：1 个对象 × 2 个 radius，共 2 个 cell。

`tricky` 的 2 个对象 × 2 个 radius 共 4 个 cell 延后到第二阶段；它们允许安全失败，不阻塞第一阶段交付。

每个目标保存可打开的 `.blend` 和固定近景，检查：

- Bridge 后槽面连续、junction Fill 正确，视觉结果符合用户截图；
- 法线视觉问题单独记录，不与急角 Curve / Cutter 拓扑修复混合验收；
- 槽外原模型没有变化；
- 输出没有意外开放边或多面共边；
- 正逆 batch 顺序结果一致；
- 可定位的 Bridge/Fill/最终几何失败必须 source 不变且没有坏输出，同时 Preview 与红色问题位置可见；更早的合同失败保留已有现场与明确提示；
- 用户显式降低 Radius 的重试与原 Radius 结果分开记录，Operator 不静默改值。

2026-07-29 Bridge 输入清理规格补充：用户确认实际任务 `37a/37b` 与 `40a/40b` 配对本身
无明显错误，残余扭曲更可能来自 Boolean Boundary 上的极近重复点与直线零散点干扰原生
Bridge。正式方向改为在所有 open / cyclic 分段完成后、每个原生 Bridge job 执行前，同时做：

- 左右侧分别以远小于 Radius 的相对阈值执行 Merge by Distance，只合并极近点；不得把两侧
  放在同一个 merge selection，也不得使用 fixture 固定距离；
- 对 merge 后每侧链中没有第三条 Boundary Edge 接入、几何上严格落在相邻两点直线段内、
  且移除不会改变链端点或 cyclic/open 形态的 degree-2 Vertex 执行 Dissolve；
- Dissolve 只清理不改变形状的零散 Vertex，不按目标点数、采样均匀度或对侧点位做简化；
- 清理后重新取得实际 Bridge Edge Loop，并验证仍为两条完整简单链、source 外形不变、没有
  分支；无法证明时安全停止；
- 分段只负责大范围空间转折或 cyclic 累计错位；极近/共线碎点优先由 Merge + Dissolve
  处理，不继续无限增加 Bridge job。

旧条目中“Bridge 前不得 Merge by Distance”只针对用 merge 制造左右侧对应或修改 Boundary
身份的方案，现由以上严格局部清理规则取代；仍禁止跨侧合并、重采样、局部重建和逐点对应。

长期第一阶段 Go：上述三个优先文件的 10 个目标场景均从目标 Operator 得到
`PRODUCT_SUCCESS`，或满足严格四项条件的 `PRODUCT_SUCCESS_WITH_RADIUS_RETRY`；
后者必须保留原 Radius 的 `RADIUS_LIMIT_DIAGNOSTIC` 与更小 Radius 的独立成功证据，
不得把原失败档位改写为成功。`tricky` 即使失败，也必须保持 source 不变、无坏输出；
可定位的几何失败保留红色位置，较早的合同失败保留已有现场和明确提示。不得用 fixture
特判换取这 10 个场景通过。本轮 cyclic 修复单独以目标 Radius `0.01` 连续 3 次通过，且
其余 8 个第一阶段 cell 连续 3 次无回归作为临时 Go；不执行的 `0.03` 不得伪装成通过。

### Step 4 — 第一阶段正式验收与分层矩阵

- 确认正式 `FINALIZE` 已接入相同流程；
- 长期验收从 UI 入口运行优先 10 cells × 3 repetitions；本轮 cyclic 修复运行目标 Radius
  `0.01` × 3 与其余 8 cells × 3；若某个已运行 cell 触发半径限制，另以用户显式操作等价的独立 Operator 调用验证更小 Radius；
- 另外运行或记录 `tricky` 4 cells 的安全失败结果，但不计入第一阶段产品成功率；
- 保存每个 cell 的结果、日志和近景；
- 独立 Spec Audit 核对正式 runtime 确实走槽段两侧完整边链 → Blender Bridge → junction Fill，而不是历史 pairing/canonicalization 旁路。

Go：长期范围仍要求优先 10 个目标场景全部直接通过或严格满足“降低半径后通过”；本轮只在
目标 `0.01` 与其余 8 cells 的 Operator、视觉结果、source 不变、诊断可见和回滚门禁全部
通过后恢复 `VERIFIED`，不据此声明未运行的目标 `0.03` 或完整 10-cell 新证据通过。
Stop：任一优先 cell 只能靠 fixture 特判、距离猜 Pipe、忽略 Bridge/Fill 失败或修改槽外模型才能通过。

第二阶段再处理 `tricky` 4 cells。它们全部通过后，才把范围提升为完整 14-cell 产品矩阵通过。

## 4. 四层验收

1. `Algorithm`：不等数量的两组 open Edge Loop 可直接 Bridge；已有 5-vs-3 证据继续保留。
2. `Backend`：真实 Pipe 能在 junction 处切出槽段、Bridge 两侧边链并 Fill 剩余交叉孔洞。
3. `Operator`：正式 UI/Operator 已接入“槽段 Bridge → junction Fill”；失败可回滚 source 与坏输出；可定位的几何失败保留 Preview 和红色问题位置供用户调小 Radius，较早的合同失败保留已有现场和明确提示。
4. `Visual/Product`：第一阶段先要求 `simple / tricky_b / mixed` 三个文件的 10 个 cell 真实文件和固定近景通过；`tricky` 留到第二阶段。

低层通过不能替代高层。实现接入时曾处于 `INTEGRATED`：用户否决的“所有 junction 一律拆成短 spline”
方案已撤回，恢复既有完整 strand 连续性。正式 Operator 在全局连接选择阶段把每个急角的
两侧设为不可回连关系；普通转角尽量连续，连接角大于 90° 时优先相连，同分时沿用端点
埋入主体的评分选择更贴主体的 U 形。真实 `Solid 44` 回归直接检查两处急角两侧属于不同
连续 spline、全部 Sharp Edge 唯一覆盖，且不会把普通转角拆成短段。法线按用户决定暂缓；
自动矩阵、固定视图与独立审计支持 `VERIFIED`；用户在真实 UI 打开 Show Cutter / Boolean
Preview 复核前，不声明 `ACCEPTED`。

## 5. 明确废弃

以下内容不再是当前实现方向或 Bridge 前置条件：

- source Edge → opposite Edge 的逐条 pairing；
- maximal source/candidate chain 的逐段独占关系；
- 两侧相同 Vertex/Edge 数量；
- Bridge 前先解决 duplicate/degenerate/canonicalization；
- 以 degree、branch、cycle 或零面积诊断阻止已正确选中的两侧 Edge Loop 进入 Bridge；
- 通过 Merge、局部重建、重采样或坐标最近关系制造两侧对应。

历史探针和 artifact 只保留为排查记录，不能再决定当前 Stop / Go。

## 6. 历史纠偏与当前验证

正式入口已经接入 Direct Edge-Loop Bridge 与 junction Fill。2026-07-26 用户两次复核
`simple / Solid 44`：第一次定位到急角 closed Curve 的 cyclic 回连；改为 open 后，第二次
复核确认它仍通过下方路径绕回急角，实际依旧是一条 spline，并未得到用户要求的两条
真正独立 Curve。现有自动测试只证明 Curve 不再 cyclic、输出拓扑闭合，未证明 Cutter
形状与 Boolean 结果正确；相关 `PRODUCT_SUCCESS` 记录作废，不得作为产品验收证据。

2026-07-27 用户确认最终 Curve 规则：急角断开是全局硬约束，不能在另一端重新连接；
其余连接尽量保持完整，大于 90° 的转角优先相连；等价 U 形优先选择整体贴主体且端点
埋入主体的方案。实现已回到全局 strand matching 阶段解决，不再让 Boolean 后的槽段
划分控制 Preview Curve spline。普通 90°、三/四叉配对、共面 U 形与平滑闭环合同均恢复。

当前代码的第一阶段自动 required scope 位于
`tests/artifacts/feature_chamfer_phase1_required_global_curve_final_no_normals/results.json`：
`simple / tricky_b / mixed` 10 个目标 cell 曾被自动分类为连续 3 次 `PRODUCT_SUCCESS`，
source 不变，最终 Mesh 无开放边、多面共边或零面积 Face，且 runtime
明确使用 Boolean Pro Boundary Edges → 槽段 Bridge → residual Fill。每个 cell 的目录保存
可打开的 `preview.blend`、`final.blend` 和 overview / wire 固定视图；这些视图只检查轮廓、
线框和补面位置，不用于法线验收。2026-07-27 用户真实 UI 复核发现 `mixed` 两个 Radius
存在错误 Bridge 形态：部分任务虽然封闭 Mesh，却选择了不属于同一槽段左右侧的 Edge
Loop，产生跨槽长斜面、扭曲面和错误 chamfer 轮廓。因此 `mixed` 的 2 个 cell 以及旧矩阵的
`first_stage_go / VERIFIED` 结论作废；自动“闭合、无零面积、无自交”不足以代表产品成功。

现有诊断直接暴露错误选择：`mixed` Radius 0.01 至少有一组 Bridge 两侧长度约为
`0.014 / 0.335`，另一个任务把 56 条 junction residual Edge 混入普通槽段 Bridge。后续修复
必须从正式 Operator 复现并逐 Bridge 任务标色，核对左右链的 Pipe、槽段区间和 junction
端点；不得恢复逐边对应、距离猜 Pipe 或 fixture 特判。

延后范围位于
`tests/artifacts/feature_chamfer_tricky_safety_global_curve_final_no_normals/results.json`：
4 个 `tricky` cell 均连续 3 次 `SAFETY_PASS`，source 不变、没有坏输出；其中可运行
Preview 的失败保留 Preview，尚未形成真实边界坐标的早期失败不伪造红色位置。该结果
满足第一阶段的 deferred safety，不代表第二阶段产品成功。

法线问题明确暂缓。本轮已从正式 FINALIZE 撤回 Set from Faces、全对象 Data Transfer、
烘焙、新面 flat shading 和 Corner 重写。不使用法线结果声明本轮修复完成。

重点回归曾证明普通 90°、三/四叉配对、共面 U 形、平滑闭环、端点贴主体评分和急角全局
禁回连合同；当时完整项目回归虽为 146/146，通过的自动门禁仍缺少 Bridge 选链形态约束，
因此状态一度回退为 `INTEGRATED`。以下记录修复后的新证据；用户复核前仍不得声明
`ACCEPTED`。

2026-07-27 已完成 Mixed Bridge 选链修复。根因有两处：旧 Finalize 把整条 Curve 的全部
Surface pair 都交给单个槽段，导致短 junction fragment 抢占真正的另一侧；同时把完整链
自然端点上的相邻槽段 witness 当成槽内交叉点，错误切掉了槽段主体。现在 Preview 合同按
source Edge 冻结每个槽段自己的 owner Surface pair 与 source Edge identity；Finalize 只在
该 pair 内选择两侧完整 Edge Loop，并把自然端点与槽内 witness 分开。Bridge 前后新增
station 区间、junction fragment 和跨其他槽段复用 Edge 的通用形态门禁。未恢复逐边配对、
距离猜 Pipe、fixture 特判或 canonicalization；法线仍按既定决定暂缓。

2026-07-27 的历史 Operator 验证证据（已被 2026-07-28 的下方槽复核替代，不得用于当前
完成声明）：

- `/private/tmp/hst-required10x3-final7-20260727/results.json`：第一阶段 10 cells × 3 全部稳定
  `PRODUCT_SUCCESS`，`first_stage_go / run_go` 均为 true，source 全部不变；每个 Bridge
  record 均通过 `SEGMENT_OWNER_INTERVAL_OVERLAP_V1` 形态合同。
- 同一目录的每个 cell 保存 `preview.blend`、`final.blend` 与 `evidence/final_overview.png`、
  `evidence/final_closeup_wire.png`；Mixed 两个 Radius 的固定近景不再出现用户截图中的
  跨槽斜面和扭曲面。
- `/private/tmp/hst-tricky-safety-final2-20260727/results.json`：延期 4 cells × 3 全部稳定
  `SAFETY_PASS`，source 不变且没有坏输出；这仍不是第二阶段产品成功。
- `/private/tmp/hst-full-regression-final3-20260727/results.json`：完整项目回归 146/146 通过，
  包含 Mixed 0.01 / 0.03 exact owner pair 与完整左右 Edge Loop 回归。

独立 Spec Audit 结论：正式入口仍为 UI Operator → Preview immutable plan → Boolean Pro
Boundary Edges → segment-local 两侧完整 Edge Loop → Blender Bridge Edge Loops → residual
junction Fill → clean separate Mesh；矩阵把形态合同纳入产品成功条件。实现未引用 fixture
名称、对象名或测试 Edge ID；测试中的 Edge ID 只作为真实 Mixed 回归断言。当前可声明
`VERIFIED`，但在用户用真实 UI 复核 Show Cutter / Boolean Preview 前不得声明 `ACCEPTED`。

2026-07-28 用户再次复核指出 Mixed 下方 U 形凹槽仍有跨槽长斜边。新诊断证明当前左右
槽段和 owner Surface pair 身份相同；早期诊断曾把另一组 `13 / 46` 不均匀采样链误认为
目标，并由此得到最长新边约 `1.23` 的非目标证据。变更 Edge 输入顺序、twist、pair 模式
以及只细分最长边均不能解释用户指出的位置。曾验证过 main 旧方案的单调 Strip 能得到
局部正确形态，但独立审计
确认它实质恢复了用户禁止的逐点对应，因此已撤回，不能作为产品修复。另一个原生
Bridge 后槽宽门禁试验能拦住 Mixed，却同时拦住此前通过的 5/8 个对照场景，因此也已撤回，
没有接入正式实现。

该阶段状态曾为 `INTEGRATED / STOP`：当时正式实现仍会产出用户截图中的错误结果，Mixed
Radius `0.01 / 0.03` 的正确原生 Bridge 输出尚未恢复，旧第一阶段 10-cell 产品门禁因此作废。

2026-07-28 第三次人工诊断已定位实际错误任务：把正式 runtime 的全部 32 组 Bridge 输入
分别保存为 `1a/1b ... 32a/32b` 后，用户确认问题来自 `26a/26b`。这两条链配对正确，均为
长度约 `5.73`、包含多个显著转折的长 open Edge Loop；用户手动整组选中后执行 Blender
Bridge 能复现同样的跨槽错误，而在大转折处分段并逐段 Bridge 可以得到正确结果。这推翻了
“当前错误来自左右链选错”以及“只能自定义补面或重采样”的判断：根因是一次原生 Bridge
跨越巨大 U 形和多重转折时内部对应关系错位。用户已授权扩展正式规格，允许已锁定的左右链
在双方共同的显著转折处分成连续子段，再分别调用原生 Bridge；仍禁止逐点对应、重采样、
局部 rebuild、距离猜 Pipe 与 fixture 特判。以下新证据完成后，状态已由该次
`INTEGRATED / STOP` 提升为 `VERIFIED`；法线继续暂缓。

2026-07-28 曾以至少四处共同转折、累计 360° 作为门槛并完成一次自动验收；用户随后用
Tricky-b `32a/32b` 的标准 open U 形证明该门槛过拟合 Mixed。该 U 形约转向 180°，整组
原生 Bridge 同样产生转角扭曲，却因旧门槛未分段。旧 `VERIFIED` 结论及“其他任务不得
触发分段”的断言因此作废，状态退回 `INTEGRATED`。正式通用语义改为逐处识别双方共同
局部大转折，不再检查累计角度或最少转折数；Mixed `26a/26b` 与 Tricky-b `32a/32b`
必须由同一几何规则自然命中，禁止 fixture、对象名或组号特判。

- `/private/tmp/hst-turn-split-final-required10-20260728/results.json`：第一阶段 10 cells × 3 全部稳定
  `PRODUCT_SUCCESS`，`first_stage_go / run_go` 均为 true；source 全部不变，正式 runtime、
  形态合同、clean output 与 Mixed 六切点/七子段合同全部通过。
- `/private/tmp/hst-turn-split-tricky-safe-20260728/results.json`：延期 4 cells × 3 全部稳定
  `SAFETY_PASS`，`deferred_tricky_go=true`；source 不变且没有坏输出，仍不代表第二阶段产品成功。
- `/private/tmp/hst-turn-split-final-full-regression-20260728/results.json`：完整项目回归 `146 / 146` 通过。
- `/private/tmp/hst-mixed-turn-split-gate-20260728/`：Mixed 两个 Radius 的可打开 `final.blend`、
  正式矩阵诊断与下方槽固定 wire 近景；补面限制在槽宽内，不再出现跨槽扇形/长斜面。

旧证据仍可证明切点复用既有 BMesh Vertex、分段覆盖无遗漏无重叠，以及 Mixed 结果已修复；
但不能证明新的通用规则。完成 Tricky-b `32a/32b` 修复、重跑第一阶段 10 cells × 3、固定
近景与独立 Spec Audit 前不得恢复 `VERIFIED`。法线和第二阶段 tricky 产品支持仍不在本轮范围。

2026-07-28 通用逐处规则已接入正式 runtime。任何 open 双链只要双方在同一 station 区间
都有唯一的局部大转折，就复用现有 Boundary Vertex 同步切开；没有累计角度或最少转折数
门槛。该次实现仅覆盖 open 分段，当时 cyclic Loop 尚未参与 Bridge 前分段。Tricky-b
`32a/32b` 在 Radius `0.01 / 0.03` 均识别两处
约 90° 共同转折并拆成 3 个原生 Bridge job；Mixed `26a/26b` 仍由同一规则识别六处转折
并拆成 7 个原生 Bridge job。实现未读取 fixture、对象、组号或测试 Edge ID，也未增加
逐点对应、重采样、局部重建或 canonicalization。

- `/private/tmp/hst-general-turn-split-required10-final-20260728/results.json`：第一阶段 10 cells × 3
  全部稳定 `PRODUCT_SUCCESS`，`first_stage_go / run_go=true`，source 全部不变；
- `/private/tmp/hst-general-turn-split-targets-final-20260728/results.json`：Tricky-b `32a/32b` 与
  Mixed `26a/26b` 两个 Radius 的正式 Operator 分段合同均连续 3 次通过；
- `/private/tmp/hst-general-turn-split-tricky-safe-final-20260728/results.json`：第二阶段延期 4 cells × 3
  全部稳定 `SAFETY_PASS`，`deferred_tricky_go=true`；
- `/private/tmp/hst-general-turn-split-full-regression-final-20260728/results.json`：完整项目回归
  `147 / 147` 通过；
- `/private/tmp/hst-general-turn-split-visual-20260728/`：Tricky-b 两个 Radius 的固定 wire 近景。

该次独立 Spec Audit 只确认 open 分段的正式 runtime、测试和本文一致：切点复用既有
Boundary Vertex，分段前后原 Edge 全集完整且互斥；生产实现没有 fixture、对象名、组号或
测试 Edge ID 特判，也没有逐点对应、重采样、局部重建或 canonicalization。该审计曾支持
open 范围恢复为 `VERIFIED`，但其“cyclic 不分段”边界已被 2026-07-29 的真实 UI 证据推翻，
不能继续作为整体状态或 cyclic 行为的完成证据。

2026-07-29 用户真实 UI 复核确认 Mixed 与 Tricky-b 的大范围错误补面已消失，通用 U 形
分段可保留 `VERIFIED`；但 Tricky-b `Extruded.002` 的局部环形补面仍可见轻微布线扭曲，
因此整体仍不提升为 `ACCEPTED`。当前 Stop / Go 回到 Bridge 输入核对：已从 Radius `0.01`
正式 Preview / Finalize runtime 捕获 U 形分段之后、实际交给 Blender 原生 Bridge 的全部
32 组左右链，按 `1a/1b ... 32a/32b` 保存到
`/private/tmp/hst-tricky-b-ext002-runtime-pairs-20260729/tricky-b-ext002-actual-bridge-pairs.blend`；
配套 `pair-manifest.json` 已确认 32 组均恰有两侧且 runtime 序号连续。用户指出具体组号前，
不得根据截图猜边或修改 Bridge 配对规则。

随后用户确认问题来自实际 Bridge 输入 `26a/26b` 与 `31a/31b`。两组均为已经正确、完整
配对的 cyclic Boundary Loop，边数分别约为 `86/27` 与 `122/31`；把整环交给 Blender 原生
Bridge 时，手工操作也能复现累计错位。因此本轮只在 Boolean 与完整环配对完成后增加通用
cyclic Bridge 预处理：沿冻结 Pipe 合同累计包含闭合边的无符号转向，以合同 seam 与方向为
唯一锚点，按累计转向划出约 90° 的共同环绕 station，再用两侧已有 Boundary Vertex 划成
局部弧段并逐段调用原生 Bridge；归一化弧长每 `0.25` 不能冒充 90° 转向。不得插点、重采样、要求等边数、
建立逐边对应、搜索最佳旋转起点，或对对象名、组号和 fixture 特判。同一 station 的连续
碎点可以归并为一个 plateau；同一侧若在冻结 station 邻域出现非连续重复 plateau，必须只在
已锁定的 Pipe、槽段与 owner pair 内，以两侧 Boundary 的局部空间邻接关系确定共同切点，
不能取消、跳过或回退整环。分段前后的原 Boundary Edge 全集必须不变、无遗漏、无重叠，相邻弧段
只共享已有端点。本轮 Tricky-b `Extruded.002` 只验收 Radius `0.01`，不运行 `0.03`。

2026-07-29 cyclic Bridge 预处理已接入正式 Preview → Finalize runtime。目标 Radius `0.01`
连续 3 次稳定成功：实际输入 26（`86/27`）与 31（`122/31`）均按共同 station 划为
4 个局部原生 Bridge job，两侧原 Edge 精确、互斥且完整覆盖；另外 4 组 cyclic 双环也使用
同一通用规则。其余 8 个第一阶段 cell 各连续 3 次全部成功，完整项目回归 `150 / 150`
通过。固定近景未见此前的环绕扭曲；独立规格审计确认正式入口、生产实现、测试合同和本文
一致，未发现对象名、组号、目标边数或 fixture 特判。旧版本曾把非连续重复 plateau 当作
歧义并安全停止；该规则已被 simple 回归推翻，不再是当前规格。provenance 缺失与无效 cyclic
合同只作为实现或数据合同错误让测试失败。少于 8 条边的最小 cyclic 双环保留原生整环 Bridge，避免把分段用于
没有足够内部端点形成四个非空局部弧段的闭环。自动证据支持状态恢复为 `VERIFIED`，用户真实 UI 复核前仍不得声明
`ACCEPTED`。

- 目标矩阵：`/private/tmp/hst-cyclic-target-matrix-final4-20260729/results.json`；
- 其余 8 cells：`/private/tmp/hst-cyclic-other-eight-final-20260729/results.json`；
- 完整回归：`/private/tmp/hst-cyclic-full-regression-final3-20260729/results.json`；
- 可打开结果与固定近景：`/private/tmp/hst-cyclic-target-matrix-final4-20260729/` 与
  `/private/tmp/hst-cyclic-target-matrix-audit-final-20260729/evidence/`。

2026-07-29 用户继续确认实际 runtime 组 37 与 40 的左右链配对无明显错误，问题来自 Bridge
输入上的退化采样而非需要继续分段。正式实现现于所有 open / cyclic 分段之后、每个原生
Bridge job 之前，对左右侧分别执行受限清理：Merge 距离为 `Radius × 1e-6`，只在同侧连通
selection 内合并，open 端点受保护；随后只 Dissolve 没有第三条 Edge 接入、偏离直线不超过
`0.1°` 且点到弦线距离不超过同一 Merge 阈值的中间 Vertex。清理后重新验证 chain 仍为同一
open/cyclic 形态和端点，并双向核对清理前后折线的最大空间偏差及弧长变化；不能证明几何
等价时安全停止。该规则不读取对象名、组号或 fixture，不按对侧点位简化，也不建立逐点对应。

以上为已被后续真实 UI 推翻的历史规则；当前规则见本文末尾的 `Radius × 0.01`、单侧链
中位 Edge 长度 `1%` 上限与逐个极短 Edge 连通簇约束。

目标 Radius `0.01` 连续 3 次稳定 `PRODUCT_SUCCESS`。用户确认的 runtime 37 由 `22/7`
清为 `21/7`，runtime 40 由 `21/20` 清为 `20/20`，两组极近边均归零；全对象共合并 6 个
极近点并 Dissolve 13 个严格共线零散点，最终 Mesh 闭合、无零面积或自交，source 不变。
其余 8 个第一阶段 cell 各连续 3 次全部 `PRODUCT_SUCCESS`。独立审计指出原清理只证明
拓扑形态、未显式证明几何等价，并且旧完整回归只有 `150 / 151`；现已补上双向空间偏差、
弧长变化门禁，以及跨侧极近、open 端点、第三条 Edge、轻微折角和偏线超阈值合同测试。
修正后的完整项目回归统一入口为 `152 / 152` 全绿。延期 `tricky` 4 cells × 3 仍全部稳定
`SAFETY_PASS`、source 不变、没有坏输出；runner 因仅选择延期 scope 而返回非零，但安全门禁
`deferred_tricky_go=true`。用户真实 UI 复核前状态仍为 `VERIFIED`，不声明 `ACCEPTED`。

- 目标矩阵与可打开结果：`/private/tmp/hst-bridge-cleanup-target2-20260729/`；
- 其余 8 cells：`/private/tmp/hst-bridge-cleanup-other8-20260729/results.json`；
- 完整回归：`/private/tmp/hst-bridge-cleanup-full-regression-final-20260729/results.json`；
- 延期 tricky 安全矩阵：`/private/tmp/hst-bridge-cleanup-tricky-safe-20260729/results.json`；
- 37 / 40 固定近景：`/private/tmp/hst-bridge-cleanup-target2-20260729/evidence/`。

2026-07-29 用户真实 UI 复核推翻了上述 `Radius × 1e-6` 阈值及 runtime 40 的自动通过结论：
40 的配对正确，但正式结果仍有局部扭曲；在同一真实输入上手动以 `0.01 cm` 执行 Merge by
Distance 后再 Bridge，布线正常，不 Merge 则稳定复现扭曲。该 fixture 使用 `METRIC / CENTIMETERS`
且 `scale_length=1`，因此手动 `0.01 cm` 等于 `1e-4` Blender unit；目标 Radius `0.01` 下对应
`Radius × 0.01`。逐 Bridge 任务探针进一步证明：旧阈值只清掉 40a 的一条 `7.45e-9` 近零边，
却遗漏 40b 的 `6.59e-5` 极短边；`1e-4` 阈值会额外清掉该点，而不会吞并下一条
`8.11e-4` 边。正式通用阈值因此改为 `Radius × 0.01`，并再受当前单侧链中位 Edge 长度的
`1%` 上限约束，避免大 Radius 在本身采样很密的链上吞掉连续短边；仍严格限定同侧连通
selection、保护 open 端点，并保留第三条 Edge、拓扑、双向空间偏差和弧长门禁。该相对规则不读取 scene
单位、对象名、组号或 fixture。完成新目标近景、其余场景、完整回归与独立审计前，状态退回
`INTEGRATED`，旧目标 artifact 不得继续证明 40 已修复。

2026-07-29 用户确认 Tricky-b 的 Bridge 输入清理已在真实 UI 中修复，但随后在
`simple / Extruded.002` 发现 cyclic 双环分段回归。正式 runtime 的 `3a/3b`、`4a/4b`、
`7a/7b`、`8a/8b` 中，一侧 Boolean Boundary 会在两个不连续位置出现近乎相同的 station
plateau；旧逻辑只按接近合同 station 的数值排序，选中了远离另一侧真实槽边的错误切点，
使后半圈被配成一长一短的错误弧段。目标 `0.01 / 0.03` 均稳定复现，证明这是共同切点消歧
合同缺失，而非原生 Bridge、Radius 或点清理阈值问题。

正式规格新增硬要求：cyclic 双环必须先由冻结 Pipe station 锁定同一目标区间；若同一侧在
该 station 邻域存在多个不连续 plateau，只能在已锁定的 Pipe、槽段、owner pair 和 station
候选内，以两侧 Boundary 的局部空间邻接关系确定同一槽宽上的切点。这不是用距离猜 Pipe，
也不建立逐点对应。随后按同一对相邻共同 station 生成 Bridge job；每个 job 的两侧必须覆盖
相同环绕区间，全部 job 合计仍须精确、互斥地覆盖原环。该类错配属于实现 bug，禁止通过
安全停止、跳过、整环回退或降级路径掩盖。修复 simple 两个 Radius、复核 Tricky-b cyclic
目标、其余第一阶段场景和完整回归前，当前状态退回 `INTEGRATED / STOP`。

2026-07-29 最终修复与审计完成。simple `Extruded.002` 的两个 Radius 各连续 3 次从正式
Preview → Finalize 成功，实际输入 3/4/7/8 的两侧 station 区间完全一致，弧长比均小于
`1.04`，最终 Mesh 闭合、无零面积、整体朝向为正且逐 Face 与重新计算结果一致。修复没有
以安全停止或整环回退处理重复 plateau，而是在冻结 station 邻域内确定真实相邻的两侧切点。
同时把 Bridge 输入 Merge 收紧为逐个极短 Edge 连通簇处理，第三条 Edge 继续受保护，避免
一次大范围合并在 Tricky-b Radius `0.03` 上破坏 cyclic 形态。第一阶段 10 cells × 3 全部
稳定 `PRODUCT_SUCCESS`、source 不变；统一完整回归 `154 / 154` 通过。独立规格审计确认
正式 runtime、矩阵硬门禁、测试说明与本文一致，状态恢复为 `VERIFIED`；用户尚未在真实
Blender UI 验收，因此不声明 `ACCEPTED`。

- 第一阶段 10-cell 矩阵：`/private/tmp/hst-simple-cyclic-final-10cells-20260729/results.json`；
- 完整项目回归：`/private/tmp/hst-simple-cyclic-final-regression2-20260729/results.json`；
- simple 配对可检查文件：`/private/tmp/hst-simple-extruded002-fixed-bridge-pairs-r001-20260729/bridge-pairs.blend` 与 `/private/tmp/hst-simple-extruded002-fixed-bridge-pairs-r003-20260729/bridge-pairs.blend`。
