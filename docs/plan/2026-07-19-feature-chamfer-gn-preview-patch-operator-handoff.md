# Feature Chamfer GN Preview → Patch Operator Handoff

> 日期：2026-07-19
> 验证环境：固定使用本机 Blender 5.1.2；本轮不再以 Blender 5.0 为阻塞项
> 状态：**已停止 / 被取代**。SDF Finalize 与复杂 Patch 已被真实文件证明几何语义错误；本文仅保留历史过程
> 后续方案：`docs/plan/2026-07-19-feature-chamfer-structured-curve-pipe-handoff.md`
> 失败复盘：`docs/postmortem/2026-07-19-feature-chamfer-sdf-patch-failure.md`
> 原决策：新增一个具有 Preview / Finalize 两阶段的新 Operator，不覆盖现有 `hst.experimental_pipe_chamfer`

## 1. 目标与结论

## 0. 2026-07-19 实施记录

- 用户提供的 `pipe-chamfer-mixed.blend::Extruded.002` 真实复现揭示：旧复杂 filler 会把 4 个 `END_CAP` 与 13 个 `JUNCTION` 的超大非平面 Boundary loops 投影后 CDT/centroid fan，虽然 topology gate 为 closed manifold，仍生成 17498 个跨模型坏面。复杂 regions 现改为直接保留已通过 provenance 与 closed-manifold gate 的 Python tracked Boolean groove surface；regular-only 路径仍使用 zipper bridge。相同文件重跑为 67026 个局部 groove Faces，boundary/non-manifold/zero-area 均为 0，视觉 artifact 不再出现跨模型 fan Faces。
- Phase 2B 已在局部 terminal case 与真实 junction-safe fixture 达到 Go：GN cutter closed manifold、所有 endpoints 非 `AMBIGUOUS`、tracked Boolean provenance coverage=100%/ambiguous=0、BoundaryGraph coverage=100% 且每个 region 都归入 `CYCLIC_TWO_RAIL / END_CAP / JUNCTION / REGULAR_TWO_RAIL`。
- Phase 3 已抽出 `utils/feature_chamfer_patch_utils.py::patch_boolean_result(...)`，不再依赖旧 `pipe_trees / pipe_bounds` owner 真源；局部 terminal 与真实 junction-safe fixture 都能生成 closed manifold output，同一 Operator 的 `FINALIZE` 已接通该安全路径。
- 后续已修正 filler 回滚与 topology cleanup：planar CDT 产生部分 Faces 后失败会先回滚，再由 centroid fan 填充；删除 groove 后遗留的 loose Edges 在 final validation 前清理。真实 junction-safe fixture 最终 output 为 closed manifold（boundary/non-manifold/zero-area 均为 0），包含 18175 Faces，并保留 source、禁用 Preview、添加 chamfer Face attribute 与 source normal Data Transfer。当前 63/63 headless cases 通过；Panel 动态 label/Cancel 已覆盖，background mode 仅能验证 `UNDO` contract，真实 Undo 操作仍需 GUI 环境。
- Phase 2B 已落地第一段 preflight seam：`utils/feature_chamfer_finalize_utils.py` 会验证 owner/version/fingerprint/live parameters，复用 Sharp FeatureGraph 生成 endpoint class、Surface Patch pair、feature degree 与 extension metadata；Finalize 内部复制 source 与受控 GN modifier，对 `TERMINAL_FACE` Feature 顶点沿 tangent 延伸，再临时读取 `Show Cutter=True` 的 evaluated SDF cutter，全程不改变用户可见 Preview。
- 新增 headless 覆盖验证 cutter closed manifold、zero-area=0、source/参数/Show Cutter 不变，以及 `TERMINAL_FACE` extension 已真实进入 evaluated cutter；随后用 Python Exact Boolean 保留 original Face/Surface Patch provenance，当前局部 terminal case 达到 coverage=100%、ambiguous=0，并在删除 groove Faces 后生成一个 `REGULAR_TWO_RAIL` Boundary region。诊断产物为 `tests/artifacts/feature_chamfer_gn_finalize_probe.json`。
- 局部 artifact 与真实 fixture 均已通过 Phase 2B gate；真实 fixture 覆盖 surface continuation、degree-3 junction、cyclic hole 与 junction volume。
- 真实 `feature-chamfer-gn-junction-safe.blend::Extruded.002` 已通过 Phase 2B/Finalize probe：degree>2 endpoints 强制分类为 `JUNCTION_BRANCH`，内部 evaluation Mesh 为每个 branch 增加独立 Sharp extension Edge，使 GN SDF 在共同 junction volume 合并；tracked Boolean provenance coverage=100%、ambiguous Faces=0，33 个 Boundary components 全部可解释，final topology gate 通过。
- 已完成 Phase 0/1 修正：发布资产直接从 fixture 的 `pipecut` 迁移，完整保留 `Boolean Pro` 与 nested Node Groups；只新增公开参数、Cutter switch 和诊断 Named Attributes，不再用原生 Mesh Boolean 替换已验证主链。
- 已完成 Phase 2 spike：本机 Blender 5.1.2 上 SDF cutter closed manifold。`Boolean Pro` 的 `New Faces` / `Slice Faces` 在当前 fixture 配置均为空，`Boundary Edges` 能保存但包含大量 loose Edge；因此仍不足以直接驱动 Patch，需转向 Python 读取 GN cutter 后做可追踪 Boolean。
- provenance、rail ownership 与 final topology gate 已满足，Finalize 已启用；任一 gate 不满足时仍明确 fail-closed，不会覆盖 source 或留下伪 Patch。
- 本机没有 Blender 5.0，且发布 `Presets.blend` 暂由 5.1.2 保存；最低版本 5.0 的 asset/API 验收仍是硬门槛。
- GN headless 覆盖已扩展到资产、参数、cutter、stale/cancel、endpoint/junction extension、tracked Boolean、Boundary regions、Patch Module、真实 fixture Finalize 与 source/Preview 生命周期。Undo/viewport screenshot 与 Blender 5.0 仍待人工环境验收。
- 已生成 Finalize PNG/.blend 视觉 artifact；尝试在可见 Blender timer 中自动执行 `bpy.ops.ed.undo()`，即使提供 VIEW_3D override，Blender 仍以 `poll() failed, context is incorrect` 拒绝，因此真实两步 Undo 保留为用户交互验收项，失败记录见 `tests/artifacts/feature_chamfer_gn_gui_undo.json`。
- 进一步用显式 `undo_push` 证明 Finalize 状态可恢复到 Preview；但这种人工 checkpoint 会改变第二步栈语义，不能替代用户按键验收。Operator 自身仍声明 `UNDO` 且 headless 生命周期测试通过。

### 0.1 当前决策与后续入口

当前 GN Preview 的视觉结果不能直接作为 Patch 输入，但 SDF cutter 可以继续使用：

- 发布资产必须以 `tests/fixtures/feature-chamfer-gn-junction-safe.blend::pipecut` 为唯一基线，保留 `Boolean Pro` 与全部受控 nested Node Groups；禁止再次用原生 `Mesh Boolean` 或其他临时主链替换。
- `Boolean Pro` 继续负责 viewport Boolean Preview；Finalize 不直接消费它当前的 evaluated Boolean result。
- `Boolean Pro.New Faces / Slice Faces` 在当前 fixture 配置下为空，`Boundary Edges` 含大量 loose Edge，不能作为槽面 provenance 或 BoundaryGraph 真源。
- 后续采用本文既定 Pivot：Python 从同一 GN modifier 读取 `Show Cutter=True` 的 evaluated closed-manifold SDF cutter，再执行可追踪 Boolean、groove classification 与 Patch。

SDF 开放链端点会形成球形端帽，并在 source 表面留下圆弧形切口。它不是普通 regular rail，必须在 Boolean 前处理：

- `TERMINAL_FACE`：沿 Feature tangent 延长 cutter，目标是把球形端帽完整推到 terminal surface 外；延长量必须由几何相交验证确定，不能只写死倍数。
- `JUNCTION_BRANCH`：延长至共同 junction volume，由 junction region 统一处理。
- `SURFACE_CONTINUATION`：不得默认延长；若端点确实需要停在表面，分类为 `END_CAP` region。
- `AMBIGUOUS`：拒绝 Finalize并保留 Preview/诊断。

删除 groove faces 后，Boundary region 必须显式分类为：

```text
REGULAR_TWO_RAIL
CYCLIC_TWO_RAIL
END_CAP
JUNCTION
AMBIGUOUS
```

只有前四类能进入各自 Patch；任何 `AMBIGUOUS`、未闭合 region、rail ownership 冲突或 coverage 不足都必须 fail-closed。

新增一个两阶段 Feature Chamfer Operator workflow：

1. `Preview`：Operator 从插件资产导入 Geometry Nodes，在 source Object 上生成 procedural SDF pipe cutter 和 Boolean Difference 预览；用户可在 Modifier / `Adjust Last Operation` 中调整参数。
2. `Patch`：用户确认预览后点击独立的下一步按钮，复制并固化 evaluated Boolean 结果，删除 cutter-derived groove faces，再复用现有 BoundaryGraph / Bridge / Fill patch 实现生成最终 Mesh。

采用 **GN 负责 cutter + Boolean preview，Python/BMesh 负责 finalize + patch**。不要把 Patch 强塞进 GN，也不要把已经验证成功的 SDF cutter 重写回 Python。

## 2. 用户交互与 Operator 状态机

HST 面板 `Feature Chamfer (Sharp/Seam)` 下方新增一个动态主按钮；现有按钮与 Operator 保持不变：

```text
Feature Chamfer (Sharp/Seam)        ← 现有，完全保留
Feature Chamfer GN Preview          ← NONE / PREVIEW_STALE 时
Finalize Feature Chamfer Patch      ← PREVIEW_VALID 时，同一 Operator
```

只新增一个 Operator 类型：

```python
bl_idname = "hst.feature_chamfer_gn"

action: EnumProperty(
    items=(
        ("AUTO", "Auto", "根据 Object 上的状态自动 Preview 或 Finalize"),
        ("PREVIEW", "Preview", "创建或重建 procedural GN preview"),
        ("FINALIZE", "Finalize", "固化当前 preview 并 Patch"),
        ("CANCEL_PREVIEW", "Cancel Preview", "移除本工具创建的 preview"),
    ),
    default="AUTO",
    options={"HIDDEN", "SKIP_SAVE"},
)
```

面板动态按钮默认传 `action="AUTO"`；可在旁边提供一个较小的 `Cancel Preview` 辅助按钮，它仍调用同一个 Operator，只传 `action="CANCEL_PREVIEW"`。

Blender 普通 Operator 在 `execute()` 返回后实例即结束，因此这里不是让一次 Operator 调用一直驻留。每次点击都是同一 Operator 类型的新调用，阶段状态必须持久化到 Object / Modifier custom properties，不能存在 Operator 实例字段中。

### 2.1 Preview 阶段

Operator 建议：

- `bl_options = {"REGISTER", "UNDO"}`
- `invoke()` 校验单个 active Mesh、Object Mode、已应用 Scale、存在 `sharp_edge` 后直接 `execute()`；不弹阻塞窗口。
- `draw()` 暴露 Radius、Sample Length、Voxel Size、Adaptivity 和是否显示 cutter。
- `AUTO` 在 `NONE / PREVIEW_STALE` 状态进入 Preview；显式 `PREVIEW` 始终创建或重建 Preview。

执行后：

- source Mesh data 不变；
- 添加或更新一个命名稳定的 Geometry Nodes modifier；
- 导入并绑定插件内置 node group；
- modifier 输出保持 Boolean Difference 预览；
- 写入 owner/source fingerprint、node group version、参数和 preview 状态等自定义属性；
- 重复执行只更新同一 modifier，不叠加副本。

### 2.2 Finalize 阶段

同一个 Operator 的 `AUTO` 在 `PREVIEW_VALID` 状态进入 Finalize；显式 `FINALIZE` 只接受有效 Preview：

- 只接受由本 Operator Preview 阶段建立、状态有效的 preview；不猜测任意 Geometry Nodes modifier。

执行后：

1. 验证 source fingerprint、modifier owner、node group version 与参数；
2. 从 depsgraph 取得 evaluated Boolean result；
3. duplicate 为新的 output Object，不 Apply/覆盖 source；
4. 从预览阶段保存的 provenance 识别 cutter-derived groove faces；
5. 删除 groove faces，提取 BoundaryGraph；
6. 复用现有 regular rail bridge + junction fill；
7. 写入 chamfer face attribute、normal transfer 和结果统计；
8. final topology 验证失败则 fail-closed，保留 source 与 preview 供诊断。

Finalize 后默认保留 source，但隐藏或禁用 preview modifier；不要让用户误以为 final output 仍是 procedural。Radius 等参数修改后必须重新 Preview，再 Finalize。

### 2.3 Undo 与取消语义

两次调用形成两个独立 Undo step：

1. Preview 后 Undo：移除或恢复 Preview 前的 modifier 状态；
2. Finalize 后 Undo：删除 final output，并回到仍可调整的 Preview；
3. `CANCEL_PREVIEW`：只删除本 Operator 拥有的 preview modifier/tags，不删除 source 或 final output。

`AUTO` 的阶段判断必须发生在 `invoke()` 校验之后、`execute()` 几何修改之前，并把本次实际 action 记录到诊断结果。

## 3. Geometry Nodes 资产

已验证原型：

```text
tests/fixtures/feature-chamfer-gn-junction-safe.blend
```

它是回归 fixture，不应作为发布资产直接加载。将清理后的 node group 迁入：

```text
preset_files/Presets.blend
NodeTree: GN_HSTFeatureChamferSDFPreview
```

GN 核心链：

```text
Named Attribute(sharp_edge)
→ Mesh to Curve
→ Curve to Points
→ Points to SDF Grid
→ Grid to Mesh
→ Boolean Difference
```

当前验证参数基线：

- Radius：`0.03`
- Sample Length：`0.01`
- Voxel Size：`0.0075`
- Adaptivity：`0.05`

这组数值只用于 fixture 基线；正式 interface 应以 Radius 为主参数，其余允许显式输入或按比例给出可见默认值，不能把绝对值隐藏在 Python 中。

### 3.1 Node Group interface

至少提供：

- Geometry input / output；
- Radius；
- Sample Length；
- Voxel Size；
- Adaptivity；
- Preview Mode：`BOOLEAN_RESULT / CUTTER`；
- cutter-derived Face selection 或稳定 Named Attribute；
- 可选 `sharp_edge` attribute name，首版可固定。

必须验证 Blender 5.0 中实际可用的 nodes、socket identifiers 和 attribute propagation；不能只在 5.1.2 中验收。

## 4. 复用项目现有 GN 导入模式

项目已有：

- `const.py::PRESET_FILE_PATH` 指向 `preset_files/Presets.blend`；
- `utils/import_utils.py::import_node_group(file_path, node_name)` 使用 `bpy.ops.wm.append` 导入 `NodeTree`；
- `utils/modifier_utils.py::Modifier.add_geometrynode(...)` 复用同名 modifier；
- WearMask 和 Vertex Color Blur 已使用这条路径。

新实现应复用这条 seam，但先补强导入语义：

- 现有 `import_node_group()` 使用 substring 判定，容易把 `.001` 或旧版本误认为目标；新模块必须 exact-name 校验；
- 校验 `bl_idname == "GeometryNodeTree"`；
- node group 增加版本属性，例如 `hst_asset_version`；
- 已存在同名且版本匹配则复用；版本不匹配时安全重导入并重新绑定本工具自己的 modifiers；
- 不删除或重绑用户创建的同名 node group；冲突时明确报错或导入带版本后缀的受控副本；
- 必须保证 nested node groups/material 等依赖随 asset 一起 append。

建议新增一个小而深的资产加载 Module，而不是把版本判断散落到 Operator：

```python
node_group = ensure_feature_chamfer_preview_node_group()
```

## 5. 新 Module seam

不要继续扩大现有 `build_pipe_chamfer()`。建议拆出两个外部 interface：

```python
preview_result = ensure_gn_feature_chamfer_preview(
    source_object,
    radius,
    sample_length,
    voxel_size,
    adaptivity,
)

patch_result = finalize_feature_chamfer_preview(
    source_object,
    preview_modifier,
)
```

第一 Module 隐藏 node asset 导入、modifier/socket lookup、幂等更新、tagging 与 evaluated preview 验证。第二 Module 隐藏 evaluated Mesh 复制、provenance、open boundary、patch、cleanup 与最终验证。

现有 `utils/experimental_pipe_chamfer_utils.py` 中可复用的后半段包括：

- `_source_face_patch_ids()`；
- `_open_boundary()`；
- `_ordered_edge_chains()` / rail pairing；
- `_bridge_then_fill()` / `_patch_boundaries()`；
- `_mark_chamfer_attribute()`；
- `_add_source_normal_transfer()`；
- `_mesh_risk_counts()`。

但这些 private 函数目前依赖旧 `groups / pipe_trees / pipe_bounds`。实现前应抽出一个明确的 `patch_boolean_result(...)` 深 Module；不要从新 Operator 直接串联一长串 private 函数。

## 6. Provenance 与 Patch 输入

这是实施前必须验证的最高风险点。现有 Patch 通过 marker material、BVH 与 source patch ID 识别 groove faces；新的 GN preview 必须提供等价或更稳定的证据。

优先级：

1. GN Boolean 前给 source/cutter 写 Named Attribute，并确认 Boolean 后 Face-domain propagation；
2. node group 输出 cutter-derived Face selection，并在 evaluated Mesh 上保存为 Named Attribute；
3. 若 Blender Boolean 丢失 attribute，使用 source-face fingerprint + cutter SDF distance/BVH classifier；
4. ambiguous coverage 非 100% 时禁止 Finalize，不允许靠最近距离静默猜测。

Finalize 所需 patch context 不能只依赖旧 FeatureGraph 的 Pipe IDs。SDF 将 junction 合并成统一体积，因此至少需要：

- source Surface Patch IDs；
- groove face provenance；
- Boundary Edge 两侧 source patch ownership；
- Boundary connected regions；
- regular 2-rail region 与 junction region 分类。

如果现有 `_bridge_then_fill()` 无法在没有 `pipe_id` 的情况下工作，应由 Boundary geometry / patch pair 重建 rail regions，或由 preview 前的 source Sharp graph只生成 metadata；不要恢复旧 Pipe mesh builder。

## 7. 状态与生命周期

建议常量：

```text
GN_HSTFeatureChamferSDFPreview
HST Feature Chamfer GN Preview
hst_feature_chamfer_preview_owner
hst_feature_chamfer_source_fingerprint
hst_feature_chamfer_asset_version
hst_feature_chamfer_preview_state
```

状态机：

```text
NONE
  └─ AUTO / PREVIEW ─→ PREVIEW_VALID
                           ├─ AUTO / FINALIZE ─→ PATCHED
                           ├─ source/asset/parameter mismatch ─→ PREVIEW_STALE
                           └─ CANCEL_PREVIEW ─→ NONE

PREVIEW_STALE
  ├─ AUTO / PREVIEW ─→ PREVIEW_VALID
  └─ CANCEL_PREVIEW ─→ NONE
```

以下情况视为 stale 并拒绝 Finalize：

- source topology / Sharp Edge fingerprint 改变；
- preview modifier/node group 被替换；
- asset version 不匹配；
- modifier 参数与保存记录不一致；
- evaluated result 为空或 provenance 无效。

## 8. 文件范围

建议新增：

- `operators/feature_chamfer_gn_ops.py`
- `utils/feature_chamfer_gn_utils.py`
- `utils/feature_chamfer_patch_utils.py`（若从旧文件抽取 Patch Module）

建议修改：

- `const.py`：node group/modifier/tag 名称与 asset version；
- `ui_panel.py`：在旧按钮下增加一个按状态切换 label 的动态主按钮；可选增加调用同一 Operator 的小型 Cancel 按钮；
- `preset_files/Presets.blend`：发布用清理后 node group；
- `tests/blender_test_driver.py`；
- `tests/README.md`。

禁止修改 `auto_load.py`；项目会自动发现新 Operator。

## 9. 实施阶段

### Phase 0：冻结资产基线

- 从 fixture 提取并清理 `pipecut`；
- 移除第三方/无关 node group 依赖，或明确将必要依赖一并迁移；
- 重命名并写入 asset version；
- 在 Blender 5.0 与 5.1.2 打开 `Presets.blend` 验证。

### Phase 1：单一 Operator 的 Preview 阶段

- exact/versioned node asset import；
- 创建/复用 modifier；
- 按 socket identifier 写参数；
- cutter / Boolean 两种 preview；
- source fingerprint、持久状态、`AUTO/PREVIEW/CANCEL_PREVIEW` dispatch 与幂等更新。

Go 条件：重复执行只有一个 modifier；修改 Radius 后 viewport procedural 更新；source Mesh data fingerprint 不变。

### Phase 2：Provenance spike

- 只验证 evaluated Boolean 的 groove face selection 能否 100% 恢复；
- 生成 coverage/ambiguous 统计和局部 artifact；
- provenance 未解决前不接 Patch。

当前结论：GN/Boolean Pro evaluated result 不能提供所需 provenance，本阶段已触发 Pivot；不要继续尝试把 `New Faces`、`Slice Faces` 或 loose `Boundary Edges` 强行解释为 groove faces。

### Phase 2B：Pivot — GN Cutter 提取与端点治理（下一步）

1. 复用 source Sharp FeatureGraph metadata，只用于 endpoint/region ownership；禁止恢复旧 Pipe Mesh builder。
2. 从同一个受控 GN Preview modifier 临时读取 `Show Cutter=True` 的 evaluated SDF cutter，复制为 Finalize 内部临时 Mesh；不得改变用户可见 Preview 状态。
3. 断言 cutter：非空、closed manifold、无 zero-area、asset/source fingerprint 与 live parameters 有效。
4. 对每个开放 Feature chain 分类 `TERMINAL_FACE / JUNCTION_BRANCH / SURFACE_CONTINUATION / AMBIGUOUS`。
5. 在 GN cutter 生成前传入端点 extension metadata，或在 Python 中对提取 cutter 做等价、可验证的延伸；优先让球形端帽位于 source 外部。
6. 用 Python 对 source duplicate 与 GN cutter 执行可追踪 Boolean；Boolean 前写 source Face Patch ID / original-face marker，并验证 Boolean 后传播。
7. provenance 不能只检查 attribute 存在；必须统计 original/groove coverage、ambiguous faces、loose geometry，并把诊断写入 artifact。
8. 删除 groove faces后构建 BoundaryGraph，分类 `REGULAR_TWO_RAIL / CYCLIC_TWO_RAIL / END_CAP / JUNCTION / AMBIGUOUS`。

Phase 2B Go 条件：

- cutter closed manifold；
- 所有开放端点均非 `AMBIGUOUS`；
- regular/cyclic 槽没有残留球形端帽，或被明确归入 `END_CAP`；
- groove provenance coverage = 100%，ambiguous = 0；
- BoundaryGraph 每个 connected region 恰有一个可解释分类；
- source 与 Preview 在失败路径完全不变。

Phase 2B 建议产出：

- `utils/feature_chamfer_finalize_utils.py`：cutter evaluation、endpoint context、tracked Boolean 与 region classification；
- `tests/artifacts/feature_chamfer_gn_finalize_probe.json`；
- 至少保留 terminal、surface-stop、degree-3/4 junction、cyclic hole 四类局部诊断 artifact。

后续 Agent 的起始顺序：

1. 先运行 `python .\tools\run_blender_tests.py`，记录已知 legacy 红灯，不要把它们误归因于 Phase 2B。
2. 读取 `tests/artifacts/feature_chamfer_gn_probe.json` 和 `tools/probe_boolean_pro_provenance.py`，确认当前 Stop 证据。
3. 只实现 GN cutter evaluation + endpoint classification，不同时进入 Patch。
4. 用真实 fixture 验证 round cap 治理；Phase 2B Go 条件未全部满足时不得启用 Finalize。

### Phase 3：Patch Module 抽取

- 从旧实现抽出 `patch_boolean_result(...)`；
- 旧 Operator 继续通过 Adapter 调用，行为与测试保持不变；
- 新 Operator 的 Finalize 阶段通过同一 interface 调用。
- `patch_boolean_result(...)` 不再接收旧 `pipe_trees / pipe_bounds` 作为唯一 owner 真源；改接 Phase 2B 产出的显式 Boundary region records。
- regular rail 使用 arc-length zipper/resample bridge，不能假设两侧 Vertex 数相等。
- `END_CAP` 与 `JUNCTION` 必须走各自 filler；禁止把它们送入 regular two-rail bridge。

### Phase 4：同一 Operator 的 Finalize 阶段

- duplicate evaluated result；
- open boundary → regular bridge → junction fill；
- `AUTO/FINALIZE` dispatch、topology/shading validation；
- stale/failure 可诊断且不破坏 source/preview。
- Finalize 的 Boolean 输入必须是 Phase 2B 提取的 GN SDF cutter，不得直接把当前 Boolean Pro evaluated result 当作可 Patch Mesh。

### Phase 5：UI 与完整回归

- 单一动态主按钮位于旧按钮下方，并按 `NONE / PREVIEW_VALID / PREVIEW_STALE` 切换 label/action；
- 可选 Cancel 按钮仍调用相同 `hst.feature_chamfer_gn`；
- 旧 `hst.experimental_pipe_chamfer` 不改名、不覆盖、不改变默认行为；
- 加入 headless smoke、真实 fixture regression 与局部截图 artifact。

## 10. 测试与验收

新增测试至少包括：

1. `gn_preview_asset_import_exact_and_idempotent`；
2. `gn_preview_modifier_parameter_update`；
3. `gn_preview_source_fingerprint_unchanged`；
4. `gn_preview_cutter_closed_manifold`；
5. `gn_preview_junction_and_tight_bend_radius_regression`；
6. `gn_finalize_rejects_stale_preview`；
7. `gn_finalize_provenance_coverage`；
8. `gn_finalize_patch_closed_manifold`；
9. `legacy_feature_chamfer_operator_unchanged`；
10. `feature_chamfer_single_operator_action_dispatch`；
11. `feature_chamfer_panel_dynamic_label_and_cancel`；
12. `feature_chamfer_preview_finalize_undo_steps`。

Pivot 后追加：

13. `gn_asset_preserves_fixture_boolean_pro_main_chain`；
14. `gn_cutter_terminal_extension_moves_round_cap_outside_source`；
15. `gn_cutter_surface_stop_classifies_end_cap`；
16. `gn_finalize_tracked_boolean_provenance_coverage`；
17. `gn_finalize_boundary_region_classification`；
18. `gn_finalize_ambiguous_endpoint_fails_closed`；
19. `gn_regular_rail_bridge_accepts_mismatched_vertex_counts`。

验收不能只看 boundary/non-manifold 数字，还必须保留与用户截图对应的局部 viewport artifact：

- degree-3/4 junction；
- 大转角；
- 孔圈与直线 feature 相交；
- Patch 后 shading。

统一回归：

```powershell
python .\tools\run_blender_tests.py
```

## 11. Stop / Go

Go：

- SDF cutter 在 Blender 5.0/5.1 都 closed manifold；
- preview 参数可 procedural 更新；
- groove face provenance coverage = 100%；
- Patch Module 可同时服务旧/new adapters；
- final result 拓扑与局部 shading 验收通过。

当前 Gate 状态：

- Blender 5.1.2 SDF cutter closed manifold：通过；
- 发布资产保留 fixture `pipecut + Boolean Pro` 主链：通过；
- Blender 5.0 asset/API 验收：未执行；
- GN Boolean groove provenance：不通过，已 Pivot；
- Python tracked Boolean provenance：通过（coverage=100%，ambiguous=0）；
- endpoint extension 与 Boundary region classification：通过；
- Patch / Finalize：Blender 5.1.2 headless 真实 fixture 通过；
- viewport/shading PNG artifact：通过；
- 真实 GUI Undo：待人工验收；
- 旧 Operator 迁移到统一 Patch adapter：通过，旧行为由回归保护。

Stop / Pivot：

- Blender 5.0 不支持当前 SDF/Grid nodes 或 modifier evaluation 不稳定；
- GN Boolean 无法提供可靠 provenance，且 fallback classifier 大量 ambiguous；
- SDF 面数使交互预览不可接受；
- 现有 Patch 强依赖 per-pipe ownership，无法从 SDF Boundary 重建稳定 regions。

Pivot 时仍保留 GN procedural cutter preview；Finalize 可改为由 Python 读取 GN cutter geometry 后执行 Boolean/provenance/patch，而不是退回旧手写 Pipe。

## 12. 当前结论与剩余验收

Pivot 方案已落地：`hst.feature_chamfer_gn` 提供 Preview/AUTO/Finalize/Cancel，viewport 继续使用 fixture `pipecut + Boolean Pro`，Finalize 从同一 GN modifier 提取 extended SDF cutter，经 endpoint governance、Python tracked Boolean、显式 Boundary regions 与 Patch Module 生成独立 output。旧 Feature Chamfer 保留；不可逆 BMesh Patch 仍是独立 Finalize step。

尚未满足的最终验收只有：Blender 5.0 asset/API 与真实 GUI 两步 Undo。在这些证据补齐前，本 handoff 不宣称整个跨版本计划完成。
