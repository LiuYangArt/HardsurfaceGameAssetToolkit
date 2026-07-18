# Experimental Sharp-Edge Multi-Pipe Chamfer — Handoff / 实施方案

> 日期：2026-07-18
> Blender：5.0+
> 状态：讨论方案已收敛，尚未按本版验收
> 目标：验证 CAD tessellated Mesh 能否通过“全部 Sharp Edge → 多 Pipe cutter → Boolean Cut → 分区 Patch”生成 mid-poly 单段 chamfer

## 1. 最终问题定义

用户只选择一个 Object，不手选 Edge Loop。

工具应自动：

1. 从 Object 读取全部 Sharp Edge，作为目标 feature edges。
2. 将 Sharp Edge 构成 FeatureGraph，并自动拆分成很多 Pipe Groups。
3. 每个 Pipe Group 生成一根独立 Pipe；Pipe 不要求彼此连续。
4. 所有 Pipe 整体 Exact Union，得到一个 cutter solid。
5. 对 duplicate source 执行 Difference：source - union cutter。
6. 删除 cutter 生成的临时切面，得到 BoundaryGraph。
7. 先补每根 Pipe 的规则 chamfer strip，再补多 Pipe 交叉处的 junction hole。
8. 检查结果是否 watertight、无非流形、自交和退化面。

实验的核心不是简单直边，而是截图所示：

- 多根 Pipe 在 sharp junction 处相交；
- 圆孔 closed Pipe 与直线 Pipe 相交；
- 曲线 Pipe 与直线 Pipe 相交；
- 不同半径圆柱的 feature curves 形成复杂 overlap；
- Patch 阶段能否稳定分成 Regular Strip 与 Junction Patch。

## 2. 核心判断

### 2.1 Pipe 必须按 FeatureGraph 分组

不能把所有相邻 Sharp Edge 合成一条折线 Pipe，也不能仅按世界方向全局聚类。

正确原则是：

- topology first：拓扑决定候选 chain 与 junction；
- surface context second：两侧 Surface Patch pair、convex/concave 决定能否连续；
- tangent continuity third：局部切向连续性用于识别 curve 与真正拐角。

### 2.2 Patch 必须分两阶段

推荐顺序：

1. 先补规则区域（此前截图的红色区域）。
2. 再补 Pipe overlap / junction 留下的小洞（蓝色区域）。

但规则 strip 不能补到互相穿插。应先划定 Junction Region，所有 strip 在其边界停止，形成 strip ports；最后统一补 junction hole。

### 2.3 Pipe Union 决定 junction 的挖除形状

每根 Pipe 是独立 cutter。它们先整体 Union，再对 source Difference。不要：

- 把多根 Pipe 拼成一根折线 sweep；
- 逐根按顺序 Difference source；
- 分别重建每根 chamfer 后再尝试相交。

整体 Union 后的 cutter 才定义了 junction 实际应该挖掉的区域。

## 3. 本轮范围

### 必须支持

- Object Mode 选择单个 closed manifold Mesh。
- 自动读取 Object 中全部 Sharp Edge。
- 支持多条 disjoint FeatureGraph components。
- 支持 open chains、closed loops、degree >= 3 junction。
- 支持一根 closed Pipe 与一根 open Pipe 相交，例如孔边接直边。
- 支持多 Pipe overlap / Exact Union。
- Patch 分成 RegularStripRegion 和 JunctionRegion。
- source 保持不变，结果写入 duplicate。
- 提供分阶段 debug artifacts 和机器可读统计。
- 以截图 two-pipe junction 作为第一核心验收，而不是边缘案例。

### 暂不处理

- Custom Normal、Weighted Normal。
- UV、lightmap UV、材质生产逻辑、LOD、导出。
- 自动生成不同 bevel 半径；本实验所有 Pipe 使用同一 radius。
- 非流形、开放壳体、未应用 Scale。
- 明显超过局部 clearance、导致 cutter 吃穿薄壁的 radius。
- 承诺任意 CAD tessellation 全自动成功。

临时 debug material/attribute 只用于 Boolean provenance，最终输出必须清除。

## 4. Operator 和深模块

建议 Operator：

- bl_idname：hst.experimental_pipe_chamfer
- 文件：operators/experimental_pipe_chamfer_ops.py
- REGISTER / UNDO
- invoke() 校验 Object、Mesh、Scale、Sharp Edge 后直接 execute()
- draw() 参数进入 Adjust Last Operation，不弹阻塞窗口
- 首版通过 F3 调用，不加入正式 panel

参数：

- radius
- pipe_resolution
- chain_turn_threshold_degrees
- chain_turn_spike_ratio
- junction_margin
- debug_stage
- keep_debug_objects

debug_stage：

- FEATURE_GRAPH：显示 Sharp Edge 分组和 junction nodes
- PIPES：显示每根独立 Pipe
- CUTTER_UNION：显示 Union cutter
- BOOLEAN_CUT：显示 cutter-derived Faces
- OPEN_BOUNDARY：删除 cutter Faces，显示 BoundaryGraph、rails、junction
- REGULAR_PATCHED：只补规则 strip，保留 junction hole
- PATCHED：补完 junction

核心模块建议文件：utils/experimental_pipe_chamfer_utils.py

外部 Interface 保持小：

    def build_pipe_chamfer(
        source_object,
        radius,
        pipe_resolution,
        chain_turn_threshold_degrees,
        chain_turn_spike_ratio,
        junction_margin,
        debug_stage,
        keep_debug_objects,
    ) -> dict[str, object]:
        ...

模块内部隐藏 Sharp 提取、Surface Patch、FeatureGraph、Pipe、Boolean provenance、BoundaryGraph、Regular Strip 和 Junction Patch。

## 5. Phase A：Object → Sharp Edge

1. 从 base Mesh 读取 sharp_edge attribute / edge.use_edge_sharp。
2. Sharp Edge 只作为 feature 候选，不读取用户 Edit Mode 选区。
3. 验证每条 Sharp Edge 为 manifold，恰好连接两个 Face。
4. 记录：
   - edge index、端点；
   - tangent；
   - 两侧 Face；
   - dihedral angle；
   - convex / concave；
   - 后续得到的 Surface Patch pair。
5. 无 Sharp Edge 时返回 no_sharp_edges，不自动回退 angle select。

Sharp 是用户/CAD 导入链提供的意图。本实验不混入“自动按角度重新发现 feature edge”，避免同时验证两个不同问题。

## 6. Phase B：Surface Patch 与 FeatureGraph

### 6.1 Surface Patch

通过 non-sharp Edge flood fill Face，得到 Surface Patches。

每条 Sharp Edge 绑定 unordered Patch Pair：

    patch_pair = {left_patch_id, right_patch_id}

Patch 可额外记录平均 normal、面积、平面/曲面粗分类，但第一版不必拟合精确 CAD surface。

### 6.2 FeatureGraph

- Graph Vertex：Sharp Edge 的 Mesh Vertex。
- Graph Edge：原始 Sharp Edge。
- Graph Vertex degree：连接的 Sharp Edge 数。
- degree != 2：天然 junction / endpoint。
- 全部 degree=2 的 component：可能是 closed loop。

### 6.3 Pipe Group 分组规则

从确定性 seed Edge 开始生长。两个相邻 Sharp Edge只在同时满足以下条件时属于同一 Pipe Group：

1. 它们在同一 Mesh Vertex相接。
2. 共享相同 unordered Surface Patch pair。
3. convex / concave 类型一致。
4. junction Vertex 的 Sharp degree = 2。
5. tangent continuity 通过。

否则在该 Vertex 断开，两边生成独立 Pipes。

这能避免顶部横边与垂直边在三叉点被误合成同一 Pipe，也能让圆孔轮廓成为 closed Pipe。

### 6.4 Tangent continuity

不能仅使用单个固定转角，因为 tessellated 圆弧每段都在转向。

推荐使用局部统计：

- turn_angle：相邻 edge tangent 的夹角。
- local_turn_median：chain 邻域若干 Vertex 的 turn_angle 中位数。
- turn_spike：turn_angle / max(local_turn_median, epsilon)。

首版断开条件建议：

- turn_angle > chain_turn_threshold_degrees，且
- turn_spike > chain_turn_spike_ratio。

初始值可取 35° 和 3.0，但必须做成可调参数并通过试件校准。若 Patch Pair 不同或 degree != 2，不需要角度判断，直接断开。

### 6.5 空间 Junction Cluster

Pipe Group 不因空间重叠而合并。重叠只影响 cutter 和 Patch。

Junction Cluster 来源：

- 拓扑 junction：多个 Pipe Group 共享 FeatureGraph Vertex；
- 空间 junction：Pipe solids 经 BVH/Boolean 检测相交，即使原 Sharp Edge 不共享 Vertex。

## 7. Phase C：独立 Pipe 生成与 Union

### 7.1 Pipe 生成

每个 Pipe Group 生成独立 closed manifold Pipe：

- spine 使用原始 Sharp polyline；
- closed group 生成 cyclic Pipe；
- open group 两端沿 tangent 延长至少 radius + tolerance，防止 end cap 停在 source 内；
- 圆截面 resolution 可调；
- 每根 Pipe 保留唯一 pipe_id；
- 不在 junction 处用 sweep miter/round transition 连接 Pipes。

### 7.2 整体 Exact Union

- 所有 Pipes 一次性参与 Exact Union。
- 不逐根 Difference source，避免顺序依赖。
- Union 后必须检查 closed manifold、内部 Face、零面积 Face、自交。
- Union Face 尽量保留 pipe provenance。
- 若 Boolean 不可靠保留 attribute/material，保留每根原始 Pipe BVH，后续按距离与 normal 分类来源。
- 同一 Union Face 可拥有一个或多个 pipe_id；multi-owner 是 Junction Region 的重要信号。

## 8. Phase D：Source Difference 与 BoundaryGraph

1. duplicate source Mesh/Data。
2. Exact Difference：duplicate - union cutter。
3. 识别 cutter-derived Faces：
   - 首轮 probe 验证 material_mode TRANSFER；
   - 生产实验不能只依赖 material index；
   - 需要 BVH 几何分类 fallback；
   - ambiguous Face 存在时不允许进入 PATCHED。
4. 删除 cutter-derived Faces，只删除 Face。
5. 提取所有 boundary edges，构成 BoundaryGraph。
6. Boundary Edge/Vertex 记录：
   - 最近 pipe_id 集合；
   - 对应 Pipe spine parameter u；
   - 到 Pipe surface 的距离；
   - 是否处于 union overlap；
   - 是否邻近 FeatureGraph junction。

删除后得到的不是固定两条 loops：

- 普通 Pipe 区域形成两条 rails；
- closed Pipe 可形成两组 cyclic rails；
- Pipe overlap 处形成 junction hole；
- BoundaryGraph degree > 2 在 junction 中是正常现象。

## 9. Phase E：划分规则区与 Junction 区

这是 Patch 成败的关键。

### 9.1 初始 ownership 分类

- nearest/owner pipe count = 1：Regular 候选。
- owner pipe count >= 2：Junction seed。
- provenance ambiguous：Junction seed，不在规则阶段猜测。

### 9.2 扩大 Junction Region

从 Junction seeds 沿 BoundaryGraph 向外扩 junction_margin，直到每个相邻 Pipe branch 都出现稳定的两条 rails。

扩张终止条件：

- boundary vertices 都只有单一 pipe owner；
- 两条 rails 对同一 Pipe 的 u 单调；
- 连续若干截面的 rail pairing 不交叉；
- 局部宽度/切向变化低于阈值。

宁可让蓝色 Junction Region 稍大，也不要让红色 Regular Strip 侵入 overlap 后产生 sliver。

### 9.3 Strip Ports

每个 Regular branch 在 Junction Region 边界停止，留下一个 strip port。

每个 port 至少记录：

- pipe_id；
- rail A endpoint / rail B endpoint；
- spine parameter u；
- strip 向 junction 的方向；
- 两侧所属 source Surface Patch；
- winding。

蓝色 patch 的输入不是整个 Pipe，而是 junction outer boundary + 一组 strip ports。

## 10. Phase F：先补规则 chamfer strip

对每个非 Junction 的 Pipe branch：

1. 依据 pipe_id 与 spine parameter u 提取两条 rails。
2. 确定两 rail 的方向、起点和 winding。
3. 不要求顶点数量相等。
4. 使用 normalized arc-length zipper：
   - 两侧同步前进生成 Quad；
   - 仅一侧前进生成 Triangle。
5. 每个 Face 必须跨两 rail，横向只有一个 span。
6. 在 strip port 停止，不封闭 junction。
7. 校验：
   - 无交叉 bridge edge；
   - 无 zero-area Face；
   - strip winding 正确；
   - strip 不与 source 或其他 strip 自交。

完成后，Mesh 应只剩每个 Junction Region 的小型闭合洞。REGULAR_PATCHED debug stage 用于直接观察这个中间状态。

## 11. Phase G：再补 Junction hole

### 11.1 Junction Patch 输入

- 已补好的 strip ports；
- Junction Region 的剩余 outer boundary；
- Pipe owner / Surface Patch 信息；
- 邻近 source Faces 的 normals 仅用于方向检查，本轮不做最终 Custom Normal。

### 11.2 首版算法

1. 验证剩余 junction boundary 是一个或多个简单闭环。
2. 估计 junction local frame / best-fit plane。
3. 将 boundary vertices 投影到 2D。
4. 保留 boundary edges 和 strip port edges 为 constraints。
5. 执行 constrained triangulation。
6. 复用原 3D boundary positions；如需内部 Vertex：
   - 先在 2D 生成；
   - 用 mean-value / harmonic interpolation 估计 3D position；
   - 不投影回 Pipe surface，因为 Pipe 只是 cutter。
7. 恢复 Face winding。
8. 可选 dissolve 近共面内部 edge，但不改变 boundary。
9. 最终 junction 允许 Triangle；不强求 Quad。

### 11.3 失败条件

以下情况返回稳定失败，不留下伪成功结果：

- junction boundary 非简单闭环；
- 2D projection 自交或翻转严重；
- constrained triangulation 失败；
- 回到 3D 后 triangle normal 大量翻转；
- patch 与 source/strip 自交；
- 最终仍有 boundary/non-manifold edge。

若 best-fit-plane 不适合非平面 junction，第二实验分支可以研究 3D harmonic/minimal patch；不要直接以 voxel/remesh 作为最终 mid-poly 结果。

## 12. CAD 对照与 Blender 实现依据

CAD kernel 的 Pipe/Fuse/Cut/History/Healing能力可参考：

- [Open CASCADE Pipe Shell](https://dev.opencascade.org/doc/refman/html/class_b_rep_offset_a_p_i___make_pipe_shell.html)
- [Open CASCADE Fuse](https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___fuse.html)
- [Open CASCADE Cut](https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___cut.html)
- [OCCT Boolean Operations / History](https://dev.opencascade.org/doc/overview/html/specification__boolean_operations.html)
- [ShapeUpgrade_UnifySameDomain](https://dev.opencascade.org/doc/refman/html/class_shape_upgrade___unify_same_domain.html)

Blender 侧基础能力：

- [Boolean Modifier](https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/booleans.html)
- [BooleanModifier Python API](https://docs.blender.org/api/current/bpy.types.BooleanModifier.html)
- [BMesh operators](https://docs.blender.org/api/current/bmesh.ops.html)

Blender 没有 CAD B-Rep history/wire builder/healing，因此 pipe provenance、BoundaryGraph、Regular/Junction 分解与 Patch solver 必须在模块内显式实现。

## 13. Debug artifacts 与结构化结果

每个阶段保存可观察对象/属性：

- FEATURE_GRAPH：group_id、junction node、Surface Patch pair。
- PIPES：pipe_id、open/closed、spine。
- CUTTER_UNION：owner pipe ids、overlap zones。
- BOOLEAN_CUT：cutter-derived / ambiguous Faces。
- OPEN_BOUNDARY：rails、owners、u、junction seeds。
- REGULAR_PATCHED：strip ports 与剩余 junction holes。
- PATCHED：最终 topology 检查。

返回 dict 至少包含：

    {
        "status": "...",
        "source_object_name": "...",
        "output_object_name": "...",
        "sharp_edge_count": 0,
        "surface_patch_count": 0,
        "pipe_group_count": 0,
        "open_pipe_count": 0,
        "closed_pipe_count": 0,
        "topology_junction_count": 0,
        "spatial_junction_count": 0,
        "union_face_count": 0,
        "cutter_face_count": 0,
        "ambiguous_face_count": 0,
        "regular_region_count": 0,
        "junction_region_count": 0,
        "strip_port_count": 0,
        "regular_patch_face_count": 0,
        "junction_patch_face_count": 0,
        "boundary_edge_count_after": 0,
        "non_manifold_edge_count_after": 0,
        "warnings": [],
    }

stdout 输出单行 JSON，prefix 建议 [HST_PIPE_CHAMFER_RESULT]。

## 14. 实施顺序

### Task 0：冻结现有实验状态

当前工作区已有未提交的 experimental operator/utils/tests 改动。实施者必须先检查 diff，判断哪些符合本方案；不要覆盖或假设它们属于本方案。

### Task 1：Sharp FeatureGraph probe

- Object → all Sharp Edges；
- non-sharp Face flood fill；
- Pipe Group 分组；
- debug group colors / ids；
- 用截图模型检查顶部、垂直边、孔边、凹槽曲线是否正确拆分。

### Task 2：独立 Pipes + Exact Union

- 为全部 Pipe Groups 生成独立 Pipes；
- open Pipe 延长；
- Union；
- 输出 owner/overlap 统计。

### Task 3：Difference + provenance

- source duplicate；
- Exact Difference；
- cutter-derived Face classifier；
- ambiguous Face 检查。

### Task 4：BoundaryGraph + Region split

- 删除 cutter Faces；
- 提取 rails；
- ownership 分类；
- junction_margin 扩张；
- 生成 strip ports。

### Task 5：Regular strips

- arc-length zipper；
- REGULAR_PATCHED 中间结果；
- 保留 junction holes。

### Task 6：Junction patch

- closed boundary 验证；
- constrained triangulation；
- 3D 恢复；
- topology/self-intersection 验证。

### Task 7：关键 CAD 试件

按下节测试，不先扩展 normals/UV。

## 15. 测试与验收

统一入口：

    python .\tools\run_blender_tests.py

第一批核心试件：

1. sharp_feature_graph_object_smoke
   - 只选 Object；
   - 自动发现全部 Sharp；
   - 验证 Pipe Group 数量和 junction 数量。

2. two_pipe_junction_regular_then_patch
   - 截图中的两 Pipe junction；
   - REGULAR_PATCHED 后只剩 junction hole；
   - PATCHED 后 watertight。

3. hole_loop_meets_open_pipe
   - closed 孔 Pipe 与垂直 open Pipe 相交；
   - ownership/Junction Region 正确。

4. different_radius_cylinders
   - 曲线 feature 和变化 dihedral；
   - 多 Pipe overlap 后能成功或稳定返回失败码。

5. three_pipe_corner
   - degree >= 3；
   - 三个或更多 strip ports。

6. grouping_curved_chain_regression
   - tessellated 圆弧不会被固定 angle 错切成很多 Pipe。

7. grouping_true_corner_regression
   - turn spike / Patch Pair 变化能正确断开。

8. near_tangent_failure
   - 返回 ambiguous_boundary / junction_projection_invalid，不产生半成品。

所有 PATCHED 成功结果断言：

- source topology/coordinates hash 不变；
- ambiguous_face_count = 0；
- boundary_edge_count_after = 0；
- non_manifold_edge_count_after = 0；
- zero_area_face_count = 0；
- self_intersection_count = 0；
- 每个 Regular Strip 与 Junction Patch 连通；
- 相同输入重复运行 topology hash 一致。

## 16. Stop / Go

Go：

- Object-only 输入可稳定得到正确 FeatureGraph/Pipe Groups；
- 截图 two-pipe junction 可先补 Regular，再补 Junction 并 watertight；
- 孔 closed Pipe 与 open Pipe junction 可处理；
- ownership 与 BoundaryGraph 对合理 tessellation / pipe_resolution 变化保持稳定；
- 失败大多可提前诊断。

Stop/Pivot：

- Sharp grouping 对 CAD tessellation 极度敏感；
- Exact Union/Difference 无法稳定提供可分类的 cutter boundary；
- Junction Region 边界随微小扰动改变拓扑；
- Regular rails 无法稳定配对；
- Junction projection/triangulation 经常自交；
- 修复 Boolean碎片所需逻辑接近完整 CAD surface kernel。

Pivot：patch-aware signed trim curves；但只有本实验覆盖 multi-pipe junction 后才能得出此结论。

## 17. 项目约束与复用入口

复用：

- operators/bevel_ops.py：REGISTER/UNDO、invoke → execute、draw。
- utils/mesh_utils.py：Sharp、selected/adjacency、BMesh 风险统计模式。
- operators/cad_ops.py：CAD split normal → Sharp 语义。
- tests/blender_test_driver.py：headless case 与断言模式。
- tests/TESTING_POLICY.md：新 Operator smoke / regression 规则。

约束：

- 每个 Python 文件头 import bpy；全部 import 在文件头。
- 非 Operator 固定方法的功能函数必须写中文 block comment，参数专业名词保留英文。
- auto_load 自动注册 Operator。
- Blender 5.0+ API需通过 Context7或真实 Blender probe 核验。
- Windows 编辑使用 windows-patch-fallback。
- 先检查 dirty worktree，保留用户/其他 Agent 的修改。
- 异常补充上下文后 rethrow，不 silent fallback。

## 18. Suggested Skills / 下一 Agent

建议顺序：

1. blender-cli：真实 Blender 5.0 background probe。
2. context7-cli：核验 Boolean/Curve/BMesh API；不可用时记录并以 probe 为证据。
3. tdd：FeatureGraph、grouping、Region split、junction tests。
4. codebase-design：保持一个深模块和小 Interface。
5. windows-patch-fallback：Windows 文件编辑。
6. verification-before-completion：运行最小 case 与完整回归。

下一 Agent 开工：

1. 读取 AGENTS.md、本方案、tests/TESTING_POLICY.md。
2. 检查当前 experimental files 的 diff，不覆盖未知改动。
3. 先运行/修正 FEATURE_GRAPH debug stage。
4. 用用户截图模型验证自动 Sharp 分组，再进入 Pipe/Boolean。
5. 实现顺序固定为 FeatureGraph → Pipes → Union → Difference → BoundaryGraph → Regular → Junction。
