# Safe Ngon → Prepare CAD Mesh 集成 Handoff

> 日期：2026-07-19
>
> 状态：只读评估完成，尚未修改实现
>
> 目标版本：Blender 5.0+
>
> 目标入口：`hst.prepcadmesh`
>
> 外部参考：`D:\ArtPresets\Blender\BlenderConfig\scripts\addons\safe_ngon`

## 1. 目标与结论

将 Safe Ngon 的拓扑修复能力迁入 Hardsurface GameAsset Toolkit，并编排进 Prepare CAD Mesh：

```text
输入 Mesh
→ 创建修改前法线参考
→ Clean Verts
→ Merge by Distance
→ Safe Ngon topology repair
→ 恢复/传递修改前 custom split normals
→ 重建 Sharp / Seam
→ Auto Seam / UV Unwrap
→ 末端拓扑验证
```

结论：技术上可行，许可证兼容，但不能在 `HST_OT_PrepCADMesh.execute()` 中直接嵌套调用外部 `mesh.safe_ngon_operator`。应迁移并解耦 BMesh 核心算法，由 Prepare CAD Mesh 负责多对象、上下文、临时资源和失败回滚。

## 2. 已确认事实

### 2.1 当前 Prepare CAD Mesh

入口：`operators/cad_ops.py:16-116`。

当前顺序：

1. 检查选择、Collection 和水密性；
2. Apply Rotation / Scale；
3. `Mesh.clean_mid_verts()`；
4. `Mesh.clean_loose_verts()`；
5. 初始化 UV、Sharp Edge → Seam、Auto Seam；
6. 所有对象执行 `Mesh.merge_verts_ops()`；
7. UV Unwrap。

主要实现位置：

- `utils/mesh_utils.py:791-826`：溶解共线二价顶点；
- `utils/mesh_utils.py:829-851`：删除没有 linked faces 的顶点；
- `utils/mesh_utils.py:875-895`：通过 Edit Mode Operator 执行 remove doubles；
- `utils/mesh_utils.py:27-67`：根据 split normals 标记 Sharp / Seam。

当前流程原位修改选择对象，不创建法线参考，也没有 Safe Ngon 或最终法线恢复。

### 2.2 Safe Ngon 实际行为

核心文件：

- `safe_ngon/safe_ngon.py`：修正非三角面内部边流；
- `safe_ngon/convert_to_ngons.py`：溶解近共面内部边；
- `safe_ngon/tests/`：custom normals、Sharp/Seam、重复执行和异常清理回归。

Safe Ngon 的“法线修复”不是 Recalculate Outside，也不修复 Face winding。实际机制是：

1. 拓扑修改前复制 Mesh，保存 corner normals；
2. 修改目标 Mesh；
3. 用 Data Transfer 将 `CUSTOM_NORMAL` 从临时 source 传回目标；
4. 对能追踪到的原 Loop 精确恢复 corner normal；
5. 删除临时 Object、Mesh 和 Modifier。

相关证据：

- `safe_ngon.py:54-151`：`MeshDataBackup` 生命周期；
- `safe_ngon.py:110-130`：`CUSTOM_NORMAL` + `NEAREST_POLYNOR`；
- `safe_ngon.py:368-499`：重建 Face、连接/溶解 Edge；
- `safe_ngon.py:513-525`：完整执行顺序；
- `convert_to_ngons.py:57-135`：共面 Edge dissolve 与二价点清理。

仅当 source Mesh 已有 custom normals 时，Safe Ngon 的 transfer 才执行。无 custom normals 的 Mesh 会保持 Blender 自然重算法线的行为。

### 2.3 许可证

Safe Ngon 源码为 GPL v2-or-later；本项目 `blender_manifest.toml` 为 `SPDX:GPL-2.0-or-later`，许可证兼容。迁移代码时仍须：

- 保留原作者 Kushiro 和 GPL 来源声明；
- 在迁移模块中标明源文件与本项目修改；
- 不把外部插件的注册/UI代码整包复制进来。

## 3. 已定设计

### 3.1 “复制原 Mesh”的语义

默认按最小行为变化实现：

- Prepare 仍原位处理用户选择的 Object；
- 在任何拓扑修改前创建内部临时 source Object，使用独立 `mesh.data.copy()`；
- source 只用于法线参考，完成或失败后都删除；
- 不默认留下一个与结果重叠的永久可见副本。

如果产品目标其实是“保留永久原件并生成新结果 Object”，必须在实现前由用户确认；这会改变命名、Collection、选择、可见性、重复执行和下游工具语义，不应顺带加入。

### 3.2 拆分为三层

1. **纯拓扑层**：输入 BMesh / Face 集合和参数，输出统计；不读取 `bpy.context`，不切模式，不调用另一个 Operator。
2. **法线参考层**：创建/清理临时 source，执行最终 custom normal transfer，异常时补充对象名并 rethrow。
3. **Operator 编排层**：验证选择，逐对象按顺序运行，统一维护 Active、Selection、Mode、Undo 和报告。

建议新增：

```text
utils/safe_ngon_utils.py
```

禁止修改 `auto_load.py`。Operator 继续放在 `operators/cad_ops.py`；测试继续放在 `tests/blender_test_driver.py`。

### 3.3 拓扑阶段位置

在 `operators/cad_ops.py:90` 的逐对象循环内，Apply Transform 之后、UV/Seam 之前运行：

```text
snapshot source
→ apply transform
→ clean_mid_verts
→ clean_loose_verts
→ merge by distance
→ safe ngon repair
→ normal restore
→ sharp/seam/UV
```

`Mesh.merge_verts_ops(selected_meshes)` 不再适合保留在 UV 初始化之后。实施时应将其改为逐对象、显式参数的 BMesh helper，避免 Safe Ngon 前后反复切 Edit Mode。

### 3.4 Safe Ngon 范围

第一版迁移 Safe Ngon 默认主路径：

- `Move Edges = True`；
- Parallel Angle 默认 `10°`；
- 候选切点 Merge Distance 默认与原插件一致，但必须暴露并验证单位语义；
- Random Seed 默认 `0`；
- Multiple Split 默认 `False`；
- `Convert to Ngons` 默认 `False`，与外部插件一致。

不要把 `Convert to Ngons` 与 Safe Ngon edge repair 混成不可关闭的一步。两者应是独立 helper，Operator 可以编排，但测试要能分别定位失败。

### 3.5 法线恢复策略

不能原样把现有 `MeshDataBackup.__enter__()` 提前到 Clean Verts 之前。

原因：Safe Ngon 当前在 topology repair 前把当前 `loop.index` 写入 `safe_ngon_source_loop`。Clean / Merge 已改变 Loop 数量和顺序时，这些索引不能再索引 clean 前保存的 corner normals，可能恢复错误法线或越界。

实施应分两条映射：

- **Clean 前 source**：用于最终空间 Data Transfer；不依赖 Loop index；
- **Safe Ngon 局部 lineage**：只在确实需要精确保留未改 Loop 时使用，其索引只能对应 Safe Ngon 前的第二份 corner-normal 数组。

第一轮建议先做一个可验证的安全基线：

1. Clean 前创建 source；
2. 完成所有 topology 操作；
3. 对最终 Mesh 全量执行 source → result 的 custom normal Data Transfer；
4. 不混用 clean 前索引与 Safe Ngon 后 Loop；
5. 用回归样本比较 `NEAREST_POLYNOR` 与项目已有 `POLYINTERP_LNORPROJ`，以误差和薄壳错投影结果决定 mapping。

只有全量 Data Transfer 无法满足精度时，再加入 Safe Ngon 前的第二层精确 lineage。不要先实现未经验证的双快照复杂度。

Face winding / Recalculate Outside 不属于本次默认“法线恢复”。如果实际样本存在反面，应作为独立明确步骤和测试加入，不能用 custom normal transfer 代替。

### 3.6 属性保留

外部 Safe Ngon 重建 Face 时只显式保留：

- Face `smooth`；
- `material_index`；
- Edge `smooth` / `seam`；
- 用于 custom normal 的临时 Loop lineage。

迁移版的硬性要求是验证并保留：

- Material index；
- UV layers；
- Color / generic Point、Edge、Face、Corner Attributes；
- `sharp_edge`、Seam；
- Bevel Weight、Crease 等 Edge 数据；
- custom split normals。

实现前使用 Context7 查询 Blender 5.0 BMesh custom-data 拷贝 API，优先采用 Blender 原生插值/拷贝能力；不要只手抄已知 Attribute 名称。无法可靠保留的 Domain 必须 fail fast 或在本阶段明确列为不支持，不能 silent drop。

## 4. 实施阶段

### Phase 0：基线与测试夹具

先建立可重复失败/成功的最小 Mesh：

1. Safe Ngon edge repair 的非三角面；
2. 可被 Convert to Ngons 合并的三角化平面；
3. 带 custom normals 与明确 Sharp Edge 的 CAD-like closed Mesh；
4. 无 custom normals 的 Mesh；
5. 带 UV、Material、Color、Edge/Face Attributes 的 Mesh；
6. 两层距离很近的薄壳，用于 Data Transfer 错投影；
7. 多对象、Multi-user Mesh Data、重复运行；
8. 注入 topology repair 异常，验证临时资源清理和 Undo。

先单独在 Blender 5.0+ 跑外部 Safe Ngon 的相关测试，记录 topology count、normal angle error、Sharp/Seam 和临时数据清理作为迁移基线。

### Phase 1：迁移纯 BMesh 拓扑核心

在 `utils/safe_ngon_utils.py` 中实现小函数，而不是复制整个 Operator：

```python
repair_safe_ngon_topology(...)
convert_coplanar_faces_to_ngons(...)
```

要求：

- 所有 import 在文件头，包含 `import bpy`；
- 功能函数使用中文块注释，完整说明参数；
- 不访问隐式 Active Object；
- 不依赖 Edit Mode selection；显式传入 Faces，Prepare 默认处理全部 Faces；
- 返回统计，例如新顶点、重建 Face、连接 Edge、溶解 Edge 数；
- 几何不一致直接抛出带上下文异常，不 silent fallback；
- 通过属性保留专项测试后才接入 Operator。

### Phase 2：法线参考与资源生命周期

实现临时 source 生命周期 helper：

- `object.copy()` + `object.data.copy()`，不能共享 Mesh Data；
- 复制 `matrix_world`，保证 Apply Transform 前后世界空间对齐；
- 临时 Object 命名唯一，不依赖固定全局名称查找；
- 默认 hide render，不成为用户结果；
- Data Transfer apply 后立即删除；
- 成功、取消、异常都清理 Object、Mesh 和 Modifier；
- 恢复进入前 Active、Selection、Mode；
- 捕获异常只用于补对象名和 cleanup，然后 rethrow。

Data Transfer mapping 由 Phase 0 数据决定。不得仅凭外部插件默认值选定。

### Phase 3：接入 Prepare CAD Mesh

重排单对象流水线：

1. 入口一次性校验选择与上下文；
2. 保存 Active、Selection、Mode；
3. 对每个 Mesh 创建 source snapshot；
4. Apply transform；
5. Clean Mid / Loose / Merge；
6. Safe Ngon；
7. 恢复 custom normals；
8. 根据最终 normals 更新 Sharp；
9. 生成 Seam、Auto Seam 和 UV；
10. 验证 closed manifold、无 loose geometry、无 zero-area Face；
11. 清理 source，恢复用户上下文；
12. 汇总每对象统计到 Operator report / console。

失败策略：任一对象失败即抛错并停止，不继续为其生成 UV，也不跳过后伪装为成功。依赖 `UNDO` 作为整个 Operator 的用户级回滚；临时资源仍需 `finally` 清理。若 Blender Operator 异常不能可靠形成原子 Undo，则从 source 显式恢复当前对象，并补异常回归。

末端水密检查不能直接复用会移动对象到 `_BadMeshes` 的副作用路径；应抽出或新增只读 topology validation helper。

### Phase 4：Operator 交互

修改 `HST_OT_PrepCADMesh` 时遵循项目 Operator 规范：

- 保持 `bl_options = {"REGISTER", "UNDO"}`；
- 增加 `invoke()`，完成必要 context 校验后直接 `execute(context)`；
- 增加 `draw()`，参数显示在 Adjust Last Operation；
- 不使用阻塞 dialog / popup；
- 没有对应 scene/global 同步模式时，不新造持久化体系。

建议参数：

- `use_safe_ngon`，默认 `True`；
- `safe_ngon_convert_coplanar`，默认 `False`；
- `safe_ngon_parallel_angle`，默认 `10°`；
- `safe_ngon_merge_distance`，默认值需经单位测试确认；
- 高级参数 Multiple Split / Seed 可先保留原默认，不一定第一版全部暴露。

### Phase 5：回归、视觉验收与文档

测试统一增加到 `tests/blender_test_driver.py`：

- topology repair 确实改变目标 edge flow；
- source Object / Mesh 不泄漏；
- custom normal 最大角误差在约定阈值内；
- 无 custom normals 时正常完成且不制造无效 custom layer；
- Sharp / Seam 与预期一致；
- UV、Material 和通用 Attributes 未丢失；
- 结果仍 closed manifold；
- 多对象和 Multi-user 不互相污染；
- 第二次执行不叠加 source / modifier，不崩溃；
- 异常注入后没有临时数据，原对象可 Undo/恢复；
- 原有 `prepare_cad_mesh_sets_ue_centimeter_units` 继续通过。

完成前运行：

```powershell
python .\tools\run_blender_tests.py
```

并检查：

```text
tests/artifacts/results.json
```

最后在可见 Blender 5.0+ 人工验证：

- 多选 CAD Mesh；
- Adjust Last Operation 参数重跑；
- 一次 Undo 恢复完整输入；
- 正反面显示、Sharp、Seam、UV 和 viewport shading；
- 临时 source 不出现在 Outliner / datablocks。

## 5. 验收标准

同时满足以下条件才可称为完成：

1. Prepare CAD Mesh 默认运行 Clean → Safe Ngon → Normal Restore；
2. 外部 Safe Ngon add-on 未启用时也能独立工作；
3. 不修改 `auto_load.py`；
4. 不留下临时 Object、Mesh、Modifier 或 Attribute；
5. custom normals、Sharp、Seam、UV、Material 和约定 Attributes 通过回归；
6. 结果无新 boundary/non-manifold/zero-area 问题；
7. 多对象、Multi-user、重复执行、异常清理通过；
8. 完整 `python .\tools\run_blender_tests.py` 通过；
9. Blender GUI 中 Undo 与 Adjust Last Operation 通过人工验收；
10. Safe Ngon 来源与 GPL attribution 已记录。

## 6. 主要风险与处理

| 风险 | 后果 | 处理 |
|---|---|---|
| Clean 后 Loop index 变化 | 错法线或越界 | 空间 transfer 与局部 lineage 分离 |
| 薄壳 Data Transfer 错投影 | 法线来自相邻表面 | mapping 对比 fixture + 误差阈值 |
| Face 重建丢 Custom Data | UV/Attribute 损坏 | Blender 5.0 API 核验 + domain 回归 |
| 嵌套 Operator 污染 context | 多对象失败、Undo 不稳定 | 纯 helper + 单一编排层 |
| 中途异常留下 source | Outliner/datablock 泄漏 | `finally` cleanup + 异常注入测试 |
| Safe Ngon 破坏水密性 | 下游 unwrap/bake 出错 | 末端只读 topology gate |
| Merge Distance 单位不清 | 尺寸不同的模型结果不稳定 | 显式参数、单位样本、禁止隐藏常量 |
| 永久副本语义不明确 | 重叠对象和下游命名变化 | 默认仅临时 source；永久输出另行确认 |

## 7. 明确不做

- 不修改 `auto_load.py`；
- 不直接依赖外部 add-on 已安装或已启用；
- 不复制外部 UI、注册代码或 Context Menu；
- 不顺手重构整个 `cad_ops.py` / `mesh_utils.py`；
- 不把 Recalculate Outside 混同于 custom normal 恢复；
- 不默认创建永久可见的原件副本；
- 不吞异常或对失败对象 silent skip；
- 不在没有属性回归前启用默认集成。

## 8. 下一位 Agent 的启动入口

建议从 Phase 0 开始，不要直接改 Operator：

1. 阅读本文件；
2. 阅读 `tests/TESTING_POLICY.md` 和 `tests/README.md`；
3. 定位 `operators/cad_ops.py:16-116`、`utils/mesh_utils.py:27-67,791-895`；
4. 只读参考外部 `safe_ngon.py:54-151,368-525` 与 `convert_to_ngons.py:49-135`；
5. 用 Context7 核验 Blender 5.0 BMesh custom-data/loop interpolation 与 Data Transfer API；
6. 先补最小 fixture 和迁移前基线，再实现 `utils/safe_ngon_utils.py`；
7. 每个 Phase 独立验证，避免把 topology、normal、Operator context 三类问题混在一次调试里。

### Suggested skills

- `$context7-cli`：核验 Blender 5.0 BMesh / Mesh / Data Transfer API；
- 项目 `agent-skills/hst-blender-regression/SKILL.md`：运行并分析 Blender headless 回归；
- `$blender-cli`：真实 Blender 5.0+ CLI/GUI 验证；
- `$windows-patch-fallback`：在 Windows 上修改文件；
- `$verification-before-completion`：提交或宣称完成前运行完整验证。

## 9. 当前工作树提醒

编写本计划时工作树已有与 Feature Chamfer 等功能相关的未提交修改。它们属于用户现有工作，Safe Ngon 实施与提交时必须只暂存当前任务文件，避免混入：

```powershell
git status --short
git diff -- <target files>
git add -- <explicit target files>
git diff --cached --check
git diff --cached --stat
```

未经用户要求不得开分支。
