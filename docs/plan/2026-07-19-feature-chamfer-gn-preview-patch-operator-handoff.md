# Feature Chamfer GN Preview → Patch Operator Handoff

> 日期：2026-07-19
> Blender：5.0+（原型验证版本 5.1.2）
> 状态：Phase 0–2 已实现；Phase 3–5 因 Stop/Go 门槛暂停
> 决策：新增一个具有 Preview / Finalize 两阶段的新 Operator，不覆盖现有 `hst.experimental_pipe_chamfer`

## 1. 目标与结论

## 0. 2026-07-19 实施记录

- 已完成 Phase 0/1：清理后的原生 GN SDF/Boolean 资产、exact/version loader、单一 Operator 的 Preview/AUTO/Cancel、Object/Modifier 状态、动态面板与 Adjust Last Operation 参数。
- 已完成 Phase 2 spike：本机 Blender 5.1.2 上 SDF cutter closed manifold；`tests/artifacts/feature_chamfer_gn_probe.json` 显示原生 evaluated Boolean 丢失 original-face attribute，coverage=0，且 SDF junction 合并后没有稳定 per-feature rail owner。
- 因未满足本文 Stop/Go 的 provenance 与 rail ownership Go 条件，Finalize 当前明确 fail-closed；没有用最近距离猜测或旧 Pipe builder 伪造 Patch。
- 本机没有 Blender 5.0，且发布 `Presets.blend` 暂由 5.1.2 保存；最低版本 5.0 的 asset/API 验收仍是硬门槛。
- 已加入 4 个 headless cases，覆盖 exact/idempotent import、参数更新/source 不变、cutter manifold、stale reject 与 action/cancel lifecycle。Finalize/Patch/Undo/viewport artifact 测试等待上述 Go 条件。

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

### Phase 3：Patch Module 抽取

- 从旧实现抽出 `patch_boolean_result(...)`；
- 旧 Operator 继续通过 Adapter 调用，行为与测试保持不变；
- 新 Operator 的 Finalize 阶段通过同一 interface 调用。

### Phase 4：同一 Operator 的 Finalize 阶段

- duplicate evaluated result；
- open boundary → regular bridge → junction fill；
- `AUTO/FINALIZE` dispatch、topology/shading validation；
- stale/failure 可诊断且不破坏 source/preview。

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

Stop / Pivot：

- Blender 5.0 不支持当前 SDF/Grid nodes 或 modifier evaluation 不稳定；
- GN Boolean 无法提供可靠 provenance，且 fallback classifier 大量 ambiguous；
- SDF 面数使交互预览不可接受；
- 现有 Patch 强依赖 per-pipe ownership，无法从 SDF Boundary 重建稳定 regions。

Pivot 时仍保留 GN procedural cutter preview；Finalize 可改为由 Python 读取 GN cutter geometry 后执行 Boolean/provenance/patch，而不是退回旧手写 Pipe。

## 12. 最终建议

按此方案实施：新增一个 `hst.feature_chamfer_gn` Operator，通过 Object/Modifier 上的持久状态和 `action` 在 Preview / Finalize 两阶段 dispatch；旧 Feature Chamfer 完全保留。GN 是 procedural cutter/Boolean preview 的 Adapter；Finalize Patch 是同一工具的显式固化步骤。内部仍以小 interface 分隔 Preview 与 Patch Module，用户既能实时调 cutter，也不会把不可逆 BMesh patch 假装成 procedural modifier。
