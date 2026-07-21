# Feature Chamfer GN Preview 恢复 Tasklist

> 日期：2026-07-20  
> 目标入口：`hst.feature_chamfer_gn`，首次点击 action=`PREVIEW`，再次点击 action=`FINALIZE`
> 当前状态：Phase 0 VERIFIED；Phase 1A PROTOTYPE；Phase 1B / Task 2 ACCEPTED（含 2.2A–C）；Phase 2 VERIFIED；Phase 3–6 INTEGRATED / 自动验证通过，等待真实 UI 视觉验收。
> 复盘：`docs/postmortem/2026-07-20-feature-chamfer-preview-integration-drift.md`  
> 主计划：`docs/plan/2026-07-19-feature-chamfer-structured-curve-pipe-handoff.md`

## 使用方式

每个 Task 单独执行、单独验收。前一个 Task 未通过，不得开始后一个。新 session 不得直接接受“按整个计划做”。

## Task 0：恢复干净的阶段边界

目标：移除越过 Phase 2 Stop 门槛的实现，但保留可复用 Phase 0/1A 工作。

保留：

- `utils/feature_chamfer_patch_utils.py` 中 complex region fail-closed；
- `const.py` 中 Even-Thickness asset 常量；
- `preset_files/Presets.blend` 中 Even-Thickness 与依赖；
- FeatureGraph maximum-weight matching、逐 Edge Patch ownership；
- Curve Pipe backend、degree-3/asset/probe tests；
- Phase 2 Rail A/B 代码和 artifacts 仅作诊断。

撤回或隔离：

- `operators/feature_chamfer_gn_ops.py` 的 structured Finalize preflight；
- `build_structured_feature_chamfer_artifacts`；
- StripPort/JunctionRecord/Junction Mesh builders；
- junction center-fan/投影排序 filler；
- `structured_feature_chamfer_preflight_contract_smoke`；
- 任何 Phase 3–6 已完成的测试或说明。

验收：

- `hst.feature_chamfer_gn` 的 Preview/Finalize runtime 行为恢复为修改前基线，除 complex region fail-closed；
- 无 Strip/Junction prototype 被正式入口调用；
- `git diff` 只剩 Phase 0、Phase 1A、Phase 2 diagnostic；
- `python .\tools\run_blender_tests.py` 通过；
- 审查结果写明 KEEP/REVERT 文件和函数。

## Task 1：冻结目标 Operator acceptance（先写失败测试）

目标：测试必须从用户按钮对应的 Operator 开始，而不是直接调用底层 builder。

新增失败测试应调用：

```python
bpy.ops.hst.feature_chamfer_gn(action="PREVIEW")
```

断言：

- Preview 创建由本 Operator 拥有的 Python Curve source；
- Curve 包含 FeatureGraph 输出的无分支 splines；
- degree-3 选择最直主 strand，unmatched branch 独立；
- 急转角/miter 不合格位置断开；
- Preview modifier 实际消费该 Curve source；
- modifier/Node Group 实际引用受控 Even-Thickness asset；
- 默认 Preview 不再使用旧 SDF cutter 作为唯一 geometry source。

验收：测试在实现前因“仍走旧 SDF Preview”稳定失败；记录失败输出。

## Task 2：实现正式 Preview seam

目标链路：

```text
source Sharp Mesh
→ Python FeatureGraph/CutterStrands
→ owned Curve Object or Collection
→ Preview GN
→ Curve-To-Mesh Even-Thickness
→ 受控 Boolean Pro Preview
```

约束：

- Python 做分组、配对、断开和 stable ordering；
- GN 只消费分组 Curve 并生成 Pipe；viewport Boolean 必须复用受控 `Boolean Pro` 主链；
- 禁止在正式 Preview runtime 中使用原生 `GeometryNodeMeshBoolean` 替代 `Boolean Pro`；
- degree-2 普通 90° miter 必须连续；极锐角超过 geometry guard 时才断开；
- degree-3/4 junction 使用 deterministic maximum-weight matching，禁止因等角候选全部断开或使用非确定随机配对；
- Preview Curve 的 ownership、source fingerprint、参数和清理生命周期由 `hst.feature_chamfer_gn` 管理；
- Preview/Cancel/Redo/Undo 不留下 orphan Objects/Mesh/Curves；
- 此 Task 不修改 Finalize、Rail、Strip、Port 或 Junction。

验收：

- Task 1 的 Operator acceptance 转绿；
- 第一次点击 `Feature Chamfer GN Preview` 就能看到不同于旧 SDF 的 Curve Pipe Preview；
- Adjust Last Operation 修改 radius 后正确重建；
- Cancel Preview 清理 modifier 和 owned Curves；
- source fingerprint 不变。
- Preview wrapper 保留受控 `Boolean Pro`、nested dependencies 与 source/cutter runtime links；
- degree-2 90° 生成单一 3-point spline，极锐角 fixture 仍拆成两个 splines；
- degree-3 生成一对连续 strand 与一根 unmatched branch；degree-4 生成两对连续 strands；
- 重复 Preview/Redo 的 pairing signature 稳定；
- 目标 Operator 的 evaluated cutter closed manifold；Boolean Pro result 非空、改变 source 且无 zero-area，并记录 boundary/non-manifold 统计供真实 UI 验收。

### 2026-07-20 首轮验收记录（已撤回）

- Task 1 RED：目标 Operator acceptance 首次运行稳定失败，原因是旧 SDF Preview 未创建 owned Python Curve source。
- Task 2 首轮曾记录 GREEN：`hst.feature_chamfer_gn(action="PREVIEW")` 已创建 owned Curve，并由 Preview modifier 的 Object Info 实际消费。
- degree-3 fixture 生成一条 3-point 主 strand 与一条 2-point unmatched branch。
- miter scale 超限的急转 fixture 生成两个独立 2-point splines。
- Preview wrapper 直接引用受控 `GN_HSTFeatureChamferCurvePipe` Even-Thickness asset，但错误改用了原生 Mesh Boolean。
- Radius redo 会替换 Curve/wrapper，不保留旧 Object、Curve datablock 或 Node Group；Cancel 在 source 重命名后仍能清理。
- 自动证据：`tests/artifacts/feature_chamfer_gn_curve_preview_operator.json`。
- 回归：Blender 5.1.2，64/64 passed。
- 撤回原因：正式 runtime 删除了既有 `Boolean Pro` 主链保护；`miter_scale_limit=1.25` 还会必然拆开 90°，并导致多根直角 branch 全部 unmatched。
- 当前状态：`INTEGRATED / REJECTED`；Task 2 必须完成 Boolean Pro seam 与 90°/junction continuity 纠偏后重新验收。
- Stop/Go：Task 2 纠偏未通过前禁止进入 Task 3。

### 2026-07-20 Task 2 纠偏实现记录

- 正式 Preview wrapper 改为复制受控 `GN_HSTFeatureChamferSDFPreview` 基线，保留 `Boolean Pro`、provenance nodes 与 nested dependencies。
- 仅替换 cutter seam：owned Python Curve → `GN_HSTFeatureChamferCurvePipe` → `Boolean Pro.Geometry B` / Show Cutter。
- Operator acceptance 明确禁止 wrapper 中出现 `GeometryNodeMeshBoolean`。
- Preview 使用 `miter_scale_limit=1.5`，普通 90° 连续；旧 experimental/finalize 默认仍保持 `1.25`，避免扩大其行为范围。
- strand traversal 改为沿每个 half-edge pair 直接 walk，避免多个独立 strands 因共享 junction vertex 被误合并为一个 component。
- 新增目标 Operator 回归：90° 单一 3-point spline、极锐角继续断开、degree-3 redo signature 稳定、三根彼此正交 branch 形成一对加一根 unmatched、degree-4 两条 3-point strands 且 redo 稳定。
- 自动证据：`tests/artifacts/feature_chamfer_gn_curve_preview_operator.json`、`feature_chamfer_gn_right_angle_operator.json`、`feature_chamfer_gn_orthogonal_junction_operator.json`、`tests/artifacts/results.json`。
- 回归：Blender 5.1.2，67/67 passed；机器结果以 `tests/artifacts/results.json` 为准。
- 当前状态：`INTEGRATED`；等待用户在真实 UI 中继续 Task 2 可见验收，通过固定近景后再升级为 `VERIFIED / ACCEPTED`。

## Task 2.1：Coplanar Strand Correction

触发原因：真实 UI 验收发现，相邻等角 90° junction 虽各自连续，但局部 matching 会在后续顶点切换支撑 Surface Patch，生成跨平面的空间折线；Even-Thickness miter 因此扭曲，Boolean 切口不适合补面。

目标入口契约：

```text
Feature Chamfer GN Preview 按钮
→ hst.feature_chamfer_gn(action="PREVIEW")
→ _rebuild_owned_preview_curve
→ _build_feature_graph / global Surface Patch matching
→ owned coplanar Curve splines
→ GN_HSTFeatureChamferCurvePipe
→ Boolean Pro
→ 共面 ]/U 形 cutter 与正确可见切口
```

实现边界：

- 保留 `Boolean Pro` 与受控 Even-Thickness asset，不修改 Finalize/Rail/Strip/Port/Junction；
- 先保留每个 Vertex 的 maximum pair count 与 connection-angle/miter guard；
- 对等分局部 matching 做 component-level 组合，优先让整条 Strand 持续共享同一 Surface Patch；
- 优先级为：零 unsupported turns、较少 strands、较多 supported turns、较多 pair、较大 angle weight；
- 最后使用几何坐标 signature tie-break，不使用 Edge ID 或随机数。

自动验收：

- 从目标 Operator 对完整 Sharp cube 建 Preview；
- 输出四条 4-point 共面 `]`/`U` splines，每条只使用两个轴且首尾 segment 平行；
- 对同一 Sharp frame 的正交旋转变体仍输出四条 4-point 共面 bracket strands；
- 原 90°、acute split、degree-3/4、Boolean Pro seam 与生命周期回归继续通过；
- artifact：`tests/artifacts/feature_chamfer_gn_coplanar_bracket_operator.json`；完整结果：`tests/artifacts/results.json`。

Stop/Go：

- 当前状态：`INTEGRATED`，68/68 headless regression 通过；等待用户在真实文件中复验固定近景；
- 用户确认 90° 管体与 Boolean 切口后才升级 `VERIFIED / ACCEPTED`；
- 若正式入口已输出严格共面 `]`/`U` Curve 仍扭曲，停止继续调整 pairing，改进入 Even-Thickness planar sweep/backend 诊断；
- Task 2.1 未获用户可见验收前，Task 3 继续 STOP。
## Task 2.2：Curve 连续性与 Boolean-aware Junction Orientation

触发原因：Task 2.1 UI 验收确认共面 90° 不再扭曲，但仍存在两类产品缺陷：平滑 degree-2/cyclic Curve 因 Surface Patch/convexity metadata 波动被断开；degree-3 等价共面 pairing 可能选择 Boolean 切口带圆弧的 U 形朝向。

### Task 2.2A：拓扑优先的平滑链/闭环连续性

目标入口：`hst.feature_chamfer_gn(action="PREVIEW")`。

规则：

- degree-2 Vertex 以原 Sharp topology 连续为主合同；
- 只在 miter scale 超限或明确几何退化时断开；
- Surface Patch ID 和离散 convexity 只作 ownership/诊断，不得切断平滑 degree-2 chain；
- 全 degree-2 connected component 必须输出单一 cyclic spline；
- 每个真实断点记录坐标、connection angle、miter scale、patch pairs、convexity 与 split reason；
- degree-3/4 junction 仍交给 junction matching，不改变 Boolean Pro seam。

自动验收：目标 Operator 对多段平滑环输出一个 cyclic spline；平滑开链输出一个 spline；acute fixture 继续断开；artifact 包含 machine-readable split diagnostics。

Stop/Go：2.2A 通过后先做真实 UI 圆环/蓝色断点复验；未通过不得用 2.2B 的 junction 结果掩盖中心线缺陷。

当前证据（2026-07-20）：

- `hst.feature_chamfer_gn(action="PREVIEW")` 已接入 topology-first degree-2 pairing；metadata 变化只写 `SURFACE_CONTEXT_CHANGED_BUT_TOPOLOGY_CONTINUES`；
- Blender 5.1.2 完整回归 69/69 passed；Operator artifact：`tests/artifacts/feature_chamfer_gn_smooth_degree_two_operator.json`；
- 真实 `pipe-chamfer-mixed.blend / Extruded.002` 只读诊断：group 58→38，cyclic 8→9，degree-2 unmatched 25→4；剩余 4 个均为 `MITER_SCALE_EXCEEDED`；
- 真实文件 artifact：`tests/artifacts/task22a_real_preview_diagnostic.json`；当前状态 `INTEGRATED / awaiting Visual`；
- 下一门槛：用户确认图 2 蓝色平滑断点与圆环 seam 消失；未确认前 Task 2.2B 保持 STOP。
- 用户 UI 验收（2026-07-20）：环形 Curve 不再中间断开；Task 2.2A 升级 `ACCEPTED`，允许进入 Task 2.2B。

### Task 2.2C：Four-sided Cutter Profile Gate

触发原因：Task 2.2B UI 复验仍存在少量错误 U 朝向与圆弧端盖切口；用户实测正式 Curve Circle resolution=4 会把圆弧变为更适合后续 Patch 的直线斜角。

目标入口：`hst.feature_chamfer_gn(action="PREVIEW") → _build_curve_preview_node_group → Curve Circle → Even-Thickness → Boolean Pro`。

实现边界：

- 仅把正式 Preview profile resolution 从 8 改为 4；不修改 experimental/finalize 的公开 `pipe_resolution` 默认值；
- 保持 Radius socket 表示 profile 中心到菱形顶点的距离，不额外乘 `sqrt(2)`；
- 保持 Fill Caps、Even-Thickness 与 Boolean Pro 主链；
- 90° miter、cyclic continuity、source fingerprint、redo/cancel 必须继续通过；
- 若四边 profile 在 cyclic seam 或非共面转角翻转，停止推进并改为 Surface Patch normals 定向的自定义 diamond profile。

自动验收：正式 Operator wrapper 的 Curve Circle resolution=4；cutter closed manifold；90° cutter face 数低于旧 resolution=8 基线；radius 沿截面主轴不放大；完整回归通过。

Stop/Go：自动证据通过后回到真实文件检查直线宽度、90° 单一斜角、cyclic seam、短边/尖刺。用户通过后才结束 Task 2；否则不得进入 Patch。

当前实现证据（2026-07-20）：

- 正式 Preview owned Curve Circle resolution 已从 8 改为 4，Radius socket 保持直接连接，不做 `sqrt(2)` 补偿；
- RED→GREEN：正式 Operator profile contract、right-angle cutter closed-manifold 与 zero-area guard；Blender 5.1.2 完整回归 72/72 passed；
- Operator artifact：`tests/artifacts/feature_chamfer_gn_four_sided_profile_operator.json`；
- 真实 `pipe-chamfer-mixed.blend / Extruded.002 / radius=0.01` 从目标 Operator 输出 resolution=4 cutter（4012 Vert / 3986 Face）；artifact：`tests/artifacts/task22c_real_preview_diagnostic.json`；
- 该条自动证据阶段状态已由下方用户 UI 验收覆盖；Task 2 最终状态以 `ACCEPTED` 为准。
- 用户 UI 验收（2026-07-20）：resolution=4 的整体 Preview 与凸台固定近景外观可用，切口为连续直线/斜角；Task 2.2C 与 Task 2 升级为 `ACCEPTED`。
- profile 全局旋转 45° 的 A/B 被否决：它虽能把局部 U 形斜角变成方角，却在下方圆柱/主体连接与 curved/cyclic Curve 上引入新瑕疵；正式 Preview 冻结为 resolution=4、profile rotation=0°。
- 下一阶段仍遵守既有 Stop/Go：本次验收不自动解除 Phase 2 Rail 17/51 门槛，也未开始 Patch 实现。

### Task 2.2B：Boolean-aware Junction Pairing

目标：degree-3 等价共面候选不能只按 Edge ID、轴向或固定 strand 数选；应选择在 source Surface Patch 上产生最干净 Boolean boundary rail 的候选。

候选评分：

- 枚举 junction 局部 matching，使用正式 Even-Thickness cutter 与 Boolean Pro 语义；
- 优先无端盖轮廓、无 radius 圆弧残留、无短边/sliver/zero-area；
- 平面 Patch 上 boundary rail 应可拟合直线，并在 90° 位置形成单一 miter 交点；
- 使用用户手摆的干净 U 形作为 golden fixture，自动评分必须严格优于错误朝向；
- 删除任何针对 cube 的固定“四条 strand”目标或其他 fixture-specific preference。

Stop/Go：2.2B 自动证据通过后回到真实文件固定近景；只有用户确认直角切口和圆环均可用，Task 2 才能升级为 `VERIFIED / ACCEPTED`。Task 3 继续 STOP。

当前实现证据（2026-07-20）：

- 保留 Surface Patch consistency 主约束；仅对 analytic 同分候选增加 source-solid endpoint containment tie-break，优先让 open cap 沿 terminal tangent 落入 attachment body；
- containment 使用 closed Mesh BVH ray parity，避免 corner nearest-normal 歧义；正式 Operator 把当前 `radius` 作为 endpoint clearance；
- 已删除 cube-specific `-abs(strand_count - 4)` 偏好；对真正几何等价的候选仍仅使用 geometry signature 保证可复现，不声明语义唯一；
- RED→GREEN：hidden cap `(exposed=0)` 严格优于 exposed cap `(exposed=2)`；另有真实 closed Mesh BVH ray-parity 回归；完整 Blender 5.1.2 回归 71/71 passed；
- 修复 pair-connected group traversal 重复消费 Edge；真实 `Extruded.002 / radius=0.01` artifact 为 23 groups / 10 cyclic / 13 open，990/990 unique Edge、重复 0；12/12 junction 均记录 containment score；
- 真实 artifact：`tests/artifacts/task22b_real_preview_diagnostic.json`；
- 2.2B 的精确 U orientation 未单独升级为 ACCEPTED；后续由 2.2C resolution=4 的产品决策替代该可见门槛，并冻结当前 junction pairing。Task 2 整体已经用户 UI 验收为 ACCEPTED。
## Task 3：真实主文件 Phase 1 可见验收

固定输入：

```text
C:\Users\LiuYang\Desktop\pipe-chamfer\pipe-chamfer-mixed.blend
Object: Extruded.002
Radius: 0.01
Blender: C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe
```

必须保存由目标 Operator 产生的同机位 wireframe + solid 近景：

- 急转角；
- cyclic hole；
- degree-3 junction；
- 邻近圆柱；
- 旧 SDF 与新 Curve Pipe A/B。

数值验收：

- 预期 cyclic components 100% 映射到单一 closed spline；
- geometry guards 全部通过；
- 无明显大于 radius 的 junction extension；
- source fingerprint 不变；
- artifact 明确记录 Operator、action、Node Group、Curve source 名称。

只有用户确认可见方向正确，Phase 1 才标记 ACCEPTED。

当前验收（2026-07-20）：`ACCEPTED`。

- 用户确认 resolution=4 的整体 Preview 与 junction 固定近景“看上去 ok”；截图保存为 `tests/artifacts/task3_phase1_visual_overview.png` 与 `task3_phase1_visual_junction_closeup.png`；
- 目标 Operator artifact：`tests/artifacts/task3_phase1_operator_acceptance.json`；正式入口返回 FINISHED，backend=`PYTHON_CURVE_PIPE`，profile resolution=4，Curve Pipe 与 Boolean Pro 资产均已记录；
- 23 splines / 10 cyclic，cyclic 全部 closed；source fingerprint 前后相同；
- 旧 SDF A/B 因本轮产品决策已由四边 Curve Pipe 取代，不再作为继续 Rail 的比较门槛；保留历史 artifacts 仅作诊断。

## Task 4：重新评估 Phase 2

前置：Task 3 ACCEPTED。

- 普通可见 span 必须形成真实 Boundary Rail A/B，且 geometry guard 达到 100%；
- 被相邻 Pipe union 物理遮挡、无法存在第二条 Rail 的 endpoint，不伪造 Rail，必须有局部 BVH 遮挡证据并转为 Junction input；
- 所有最终 Boolean Boundary Edge 必须进入可审计的 consumption ledger，禁止遗漏、插值、重排或跨面 chord；
- Go 条件：pairable Rail 100% guard + occluded endpoint 100% classified + Boundary 100% consumed。满足后允许进入 Strip/Junction，但不得据此宣称 Operator 完成。

当前诊断（2026-07-20，Task 4.0 Graph Alignment）：

- 已提取唯一 `GN_PREVIEW_V1` FeatureGraph contract；正式 Operator 与 Rail diagnostic 均复用 miter=1.5、global matching、endpoint clearance=radius；Experimental 默认行为未改变；
- alignment 回归比较完整 `edge_indices + cyclic` signature，Blender 5.1.2 完整回归 73/73 passed；
- 旧 48 groups / 51 spans / 17 valid 是 legacy graph 历史基线，不再代表正式产品路径；
- Task 4.0 旧 extraction 基线：23 groups / 51 spans；source-surface extraction coverage 51/51，但 guard valid 17/51；Boolean coverage 14/51，guard valid 0/51；此条已被下方 Task 4.1 当前 artifact 更新；
- artifact：`tests/artifacts/feature_chamfer_rail_phase2_resolution4_probe.json`；`graph_alignment=true`，source fingerprint unchanged，`phase2_go=false`；
- Task 4.1 加入 owner-patch 小步 Surface walk、intrinsic offset、projection/continuity diagnostics，以及 curved Surface 上 intrinsic=1.200 / chord=1.130 的区分回归；Blender 5.1.2 完整回归 75/75 passed；
- 真实文件复验仍未过门槛：51 spans 中仅 17 paired / 15 guard-valid（33.3% coverage、29.4% guarded coverage）；失败已细分为 walk 无法完成、owner-patch continuity 与 cyclic self-intersection，不再误把 3D 欧氏距离当 intrinsic radius；
- Task 4.2 将全 Patch nearest 替换为 Surface Patch adjacency 驱动的 owner Face walk，并为失败 span 记录 failed sample/source Edge、为成功 rail 记录左右 owner Face path；平面/折叠曲面与非相邻同 Patch 防跳转回归均通过；
- 真实 Rail probe 当前为 51 spans 中 10 paired / 9 guard-valid（19.6% coverage、17.6% guarded coverage），唯一已配对 guard failure 为 group 9 / span 2 的 `SAMPLE_DENSITY_EXCEEDED`，其余失败保持逐 span `OWNER_FACE_WALK_FAILED` 诊断；source fingerprint 未变化；
- Task 4.2 cutter-driven pivot 已改为对每根正式四边 Curve Pipe 单独执行 Exact Difference，并从 `original Face ↔ cutter-derived Face` 邻接边直接提取 Surface Patch 交线；ownership backend 为 `CUTTER_FACE_COMPONENT_PROVENANCE`，不再以 nearest Pipe 猜 owner；
- 真实 cutter-driven probe 当前为 51 spans 中 11 paired / 0 guard-valid（21.6% coverage、0% guarded coverage）；所有 23 根 Pipe 都提取到逐 Patch 交线，但当前 chain/span 切分与 guard 仍沿用旧 Boundary rail 假设，出现 sample density、self-intersection、radius tolerance 失败；
- cutter-driven 交线现已按最近 Feature Edge ownership 裁成 span-local runs，并以 `1.5 * radius` 最大边长重采样；真实 probe 提升到 51 spans 中 34 paired / 5 guard-valid（66.7% coverage、9.8% guarded coverage），sample-density failure 已消失；
- 剩余 17 个 unresolved spans 集中在 group 3/4/18–22；29 个 guard failure 以 radius tolerance 为主，另有 cyclic self-intersection/ordering。当前证据说明 span 裁切方向有效，但还不能进入 Patch；
- **2026-07-21 用户视觉拒收**：cutter-driven 交线的 centerline 参数排序与线性重采样会把非邻接 Boundary vertices 连成跨面的 chord，造成 Rail 离开切口、环形断开和丢失；该方向已撤回到 `f39383e` 后重做，上一轮 34/51 或更高 coverage 数字作废；
- Task 4.2 当前只从最终 all-pipe Exact Boolean 的 open Boundary Edges 提取 Rail；坐标保持 Boolean 原始顶点，顺序只来自 BMesh edge adjacency，禁止 centerline sorting、线性坐标重建与独立 per-pipe Difference 交线进入正式 Rail；
- 新真实 artifact：`tests/artifacts/feature_chamfer_rail_phase2_resolution4_probe.blend`；绿色为已归属的真实 Boundary Edges，橙色为 owner 未解决但仍是原始 Boundary Edge。3898 条洞口边全部进入 topology partition，adjacency guard=PASS；其中 3856 owned、42 unowned，ownership coverage=98.92%；
- **用户视觉验收（2026-07-21）**：最终 Boolean Boundary Rail 已确认“跟切口一致”；该 Rail geometry/topology 层状态记为 `ACCEPTED`。后续 owner/span 工作不得重排、插值或移动这些 Boundary coordinates；
- owner 归属续作（2026-07-21）：先用 Surface Patch compatibility 筛选 Pipe BVH candidates，再仅沿同 Patch Boundary adjacency 传播唯一 owner；真实 probe 从 3856/3898 提升到 3885/3898 single-owner Boundary edges；
- final Boolean open Boundary 先以 `1e-7 * radius` 清理 Exact Boolean 重合顶点：真实 probe 清理前 100 条零长度 Boundary edges、清理后 0；Boundary 从 3898 条有效归一为 3798 条，未移动非重合坐标，consumable Rail guard=PASS；
- 剩余 11 条 overlap seam 不再猜成单一 Pipe：每条保留全部 compatible Pipe/Patch owner，并真正进入每个 owner 的 `_ordered_edge_chains`。机器集合核对 11/11 的 `owner_pairs` 均由对应 Rail chains 消费；
- span slicing 只裁分原始 Boundary edge runs。group 17/span 1 的 5 条 overlap endpoint outlier 被裁为 `endpoint_trim`，剩余 Rail core 保持原始 Edge adjacency 并通过 guard；真实 51 spans 形成 44 个可见 Rail A/B，44/44 correspondence guard PASS；
- 其余 7 spans 为 all-pipe union 遮蔽的 endpoint：group/span 3/0、16/0、17/0、18/0、20/0、22/0、22/4。每条均记录 endpoint class、邻 Pipe BVH inside/surface-distance 和可见 Boundary edge indices；其 guard 明确为 `NOT_APPLICABLE / OCCLUDED_ENDPOINT_CLASSIFICATION`，不伪装为 Rail A/B geometry PASS；
- 建立全 Boundary consumption ledger：3798 edges 中 paired Rail 3729、occluded endpoint 54、shared overlap 11；余下 15 条 Pipe 8/9 fragments 均位于包含 shared multi-owner seam vertex 的同一原始 Boundary chain component，归类为 `shared_seam_chain_component`。集合核对 consumed=3798、missing=0、extra=0、unclassified=0，boundary consumption guard=PASS；
- artifact：`tests/artifacts/feature_chamfer_rail_phase2_resolution4_probe.json` 与 `.blend`。Blender 5.1.2 完整回归当前为 79/79 passed；endpoint core trim 仍由独立 BMesh 回归证明不插值、不重排 Edge；
- **2026-07-21 产品门禁决策与接入结果**：最终需求是 PipeCut → 自动补面 → Chamfer。44 个可见 span 的 Rail A/B 为 44/44 guard PASS；其余 7 个 endpoint 由 all-pipe union 遮挡证据转为 Junction inputs；Boundary consumption 为 3798/3798。Phase 3 生成 3661 个 regular strip Faces，Phase 4 生成 89 个 local junction Faces；目标 `hst.feature_chamfer_gn` 的 `PREVIEW → FINALIZE` 已接入同一 `GN_PREVIEW_V1` Pipe backend。真实 mixed 文件 Operator probe 返回 FINISHED，独立 output 为 closed manifold：Boundary=0、non-manifold=0、zero-area=0，并保存 `tests/artifacts/feature_chamfer_operator_product_probe.blend`。当前状态 `INTEGRATED`，等待用户真实 UI 视觉验收后升级为 `ACCEPTED`。

## 禁止事项

- 禁止一个 session 同时做 Task 0–4；
- Phase 2 已按“可见 Rail 44/44 + 遮挡 Junction input 7/7 + Boundary 3798/3798”通过；后续 StripPort/JunctionSolver 必须消费这些真实 Boundary inputs；
- 禁止用底层 probe、字段存在、topology clean 或测试总数宣称 Operator 完成；
- 禁止 junction center fan、通用 Fill 或 Boolean groove 成功路径；
- 禁止修改 `auto_load.py`；
- 禁止修改用户原始 `.blend`。

## 每次交付模板

```text
状态：PROTOTYPE / INTEGRATED / VERIFIED / ACCEPTED
目标 Operator：
本轮唯一 Task：
用户可见变化：
直接证据：
未通过门槛：
本轮未做：
验证命令与结果：
```
