# Marmoset 5 Bake Scene Bridge 计划

日期：2026-07-07

本文档用于 handoff 给后续实现 agent。范围：给 Bake Prep Tool 增加一键发送到 Marmoset Toolbag 5，并按已标记 high / low collection 自动设置 bake scene；本阶段只写计划，不改功能代码。

## 1. 已确认需求

- 目标版本：Marmoset Toolbag 5。
- 默认安装目录：`C:\Program Files\Marmoset\Toolbag 5`。
- 插件偏好设置新增 Toolbag 路径参数，默认使用上面的路径。
- Bake Prep 面板新增按钮：发送到 Marmoset 并设置 bake scene。
- 不自动开始 bake，只完成 scene / baker / bake group / material bevel 配置。
- high / low 匹配规则按命名：`a_low` 对应 `a_high`，base name 为 `a`。
- 使用项目已有 bake collection 标记：`BAKE_LOW` / `BAKE_HIGH`。
- 需要参考 Zen BBQ：通过 vertex color mask 控制 Toolbag bevel shader，高模 material 需要自动设置 bevel 参数。

## 2. 当前代码入口

- Bake collection 标记逻辑：`bake_ops.py`
  - `set_bake_collection(collection, type="LOW")`
  - `HST_OT_SetBakeCollectionLow`
  - `HST_OT_SetBakeCollectionHigh`
- Bake Prep UI：`ui_panel.py` 的 `HST_PT_BakeTool.draw()`。
- Collection 类型排序：`utils/collection_utils.py` 的 `Collection.sort_hst_types()`。
- 旧 Marmoset / BTM 代码：`functions/btm_functions.py`、`btm_operator.py`。
  - 有可参考思路，但实现较旧，且当前项目没有真正注册 `toolbag_app_path` preference。
- 导出工具：`utils/export_utils.py` 的 `FBXExport`，可复用或参考。

## 3. 外部依据

- Marmoset 官方 Python scripting：`https://marmoset.co/posts/python-scripting-toolbag/`
  - 支持通过 `toolbag.exe "script.py"` 启动并执行脚本。
  - `mset` 模块用于创建对象、导入模型、保存 scene 等。
- Toolbag 5 Python API：`https://marmoset.co/python/reference5.html`
  - `mset.importModel(path)`：导入模型。
  - `mset.BakerObject()`：创建 Baker。
  - `BakerObject.importModel(path)`：通过 Baker quick loader 导入模型。
  - `BakerObject.addGroup(name)`：新增 bake group。
  - `BakerObject.outputPath/outputWidth/outputHeight/outputBits/outputSamples`：设置输出。
  - `mset.saveScene(path)`：保存 Toolbag scene。
- Zen BBQ vertex color mask 指南：`https://zen-masters.github.io/Zen-BBQ/guide_using_vc_mask/`
  - Toolbag bevel shader 不支持 Raster，需要 Hybrid 或 Ray Tracing 才能预览。
  - Bevel Width 是 Toolbag bevel shader 的最大宽度；本插件实现中由独立 UI 参数提供，不从 HST bevel modifier 推断。
  - Vertex Color Mask 用颜色值乘以 Bevel Width，例如 0.5 会得到一半宽度。
  - 建议 FBX，因为需要保留 vertex color。

## 4. 推荐实现结构

新增模块：

- `operators/marmoset_bake_ops.py`
  - Operator：`HST_OT_SendBakeToMarmoset`
  - 负责 Blender 侧收集、校验、导出、生成 loader、启动 Toolbag。
- `utils/marmoset_bake_utils.py`
  - collection 配对、路径计算、FBX 导出、loader 脚本生成等纯逻辑。
- `preferences.py`
  - 新增 `AddonPreferences`，注册 Toolbag executable / install path。
  - 注意 `auto_load.py` 已支持 `AddonPreferences`。

也可以先少建文件，把 operator 放 `bake_ops.py`，但建议独立文件，避免 bake_ops 继续变长。

## 5. 数据流

1. 从当前 scene 可见 collection 中筛选 `BAKE_LOW` / `BAKE_HIGH`。
2. 对每个 collection 生成 base key：
   - 去掉 `_low` / `_high` 后缀。
   - 去掉 Blender 自动 `.001` 后缀。
   - 建议大小写敏感，先不做 fuzzy match。
3. 校验配对：
   - 有 low 无 high：报错并列出名称。
   - 有 high 无 low：报错并列出名称。
   - base name 重复：报错，避免 silent fallback。
4. 导出 FBX：
   - 输出目录：`<blend>/Bake/Marmoset/Models/`。
   - 每组建议导出一个 FBX：`<base>_bake.fbx`，其中包含对应 low/high mesh。
   - 保留 vertex color。
5. 生成 loader：`<blend>/Bake/Marmoset/hst_marmoset_loader.py`。
6. 启动 Toolbag：`<toolbag_exe> <loader.py>`。
7. Loader 内：
   - 新建 scene。
   - 创建 `mset.BakerObject()`。
   - 设置输出路径：`<blend>/Bake/Marmoset/Textures/<base>` 或统一 textures 目录。
   - 设置分辨率、bit depth、samples。
   - 对每组调用 `baker.addGroup(base)`。
   - 导入 FBX，并把 `_low` / `_high` 物体分配到 group 的 low/high 子节点。
   - 保存 scene：`<blend>/Bake/Marmoset/<blend_name>_bake.tbscene`。

## 6. Toolbag bevel material 方案

目标：让 high poly material 自动启用 Bevel surface shader，并用 vertex color mask 控制宽度。

已实测 Toolbag 5 API，探针输出：

- `tests/artifacts/marmoset_material_bevel_probe.txt`
- `tests/artifacts/marmoset_material_bevel_setfield_probe.txt`

确定 API：

```python
mat.setSubroutine("surface", "Bevel")
surface = mat.getSubroutine("surface")
surface.setField("Bevel Width (mm)", bevel_width_mm)
surface.setField("Bevel Angle", 90.0)
surface.setField("Bevel Samples", bevel_samples)
surface.setField("Bevel Hard Edges", True)
surface.setField("Bevel Same Surface Only", False)
surface.setField("Vertex Color Mask", 1)  # 0=None, 1=R, 2=G, 3=B, 4=A
```

实测字段名：

- `Normal Map`
- `Scale & Bias`
- `Flip X`
- `Flip Y`
- `Flip Z`
- `Generate Z`
- `Object Space`
- `Bevel Width (mm)`
- `Bevel Angle`
- `Bevel Samples`
- `Bevel Hard Edges`
- `Bevel Same Surface Only`
- `Vertex Color Mask`

实现约定：

- 不需要单独导出 manifest JSON；`loader.py` 可直接内嵌统一参数。
- `Bevel Width (mm)` 是 Bake Prep / Marmoset 发送功能自己的统一参数，只用于 Toolbag Bevel shader。
- 该参数与 HST 的 Blender bevel modifier 完全无关；不得读取、复用、同步或推断 `HSTBevel` modifier 的 `width`。
- vertex color 只保存 `0..1` mask / multiplier；最终宽度 = `Bevel Width (mm) * vertex color channel value`。
- `Vertex Color Mask` 必须传 int，不接受字符串 `"R"`。
- UI 可显示 `R/G/B/A`，loader 生成时映射为 `1/2/3/4`。
- 如需关闭 mask，传 `0`。

本地 shader 依据：`C:\Program Files\Marmoset\Toolbag 5\data\shader\mat\surface\bevel.frag` 中 `Vertex Color Mask` 对应低 3 bit：`1=R, 2=G, 3=B, 4=A`。


## 7. UI / 参数

Bake Prep 面板新增：

- `Send to Marmoset` 按钮。
- 可选 scene 参数：
  - texture size，默认沿用 `UIParams.texture_size`。
  - output bits，默认 16。
  - samples，默认 64 或 16，需按 Toolbag 5 API 实测有效范围。
  - marmoset bevel width mm，默认建议 `1.0`，独立于 HST bevel modifier。
  - bevel samples，默认建议 16 或 32。
  - vertex color mask channel，默认 R。
  - open/save scene only，第一版固定 true。

插件偏好设置：

- `toolbag_app_path: StringProperty(subtype="FILE_PATH")`
- 默认值建议：`C:\Program Files\Marmoset\Toolbag 5\Toolbag.exe`
- 如果用户填的是目录，则自动拼 `Toolbag.exe`；如果不存在，直接报错。

## 8. 验证计划

最小验证：

1. 新增 headless test：创建 `a_low` / `a_high` 两个 bake collection，验证命名配对。
2. 验证缺失 high / low 会失败并输出明确错误。
3. 验证 loader 脚本生成路径、内嵌统一 bevel 参数、FBX 输出路径。
4. 若本机可启动 Toolbag 5：运行一次手动 smoke，确认 `.tbscene` 生成。

回归入口：

- `python .\tools\run_blender_tests.py`

新增测试位置：

- `tests/blender_test_driver.py`

## 9. 实现顺序

1. 加 `preferences.py`，注册 Toolbag 路径。
2. 加配对/manifest 纯函数和测试。
3. 加 FBX 导出和 loader 生成，不启动 Toolbag。
4. 加 operator 和 Bake Prep UI 按钮。
5. 加启动 Toolbag 逻辑。
6. 做 Toolbag material bevel API 探针。
7. 接入 high material bevel 设置。
8. 跑回归测试，写必要 postmortem。

## 10. 非目标

- 不自动开始 bake。
- 不做复杂 fuzzy matching。
- 不兼容 Toolbag 3 / 4。
- 不吞掉导出或 Toolbag 启动错误。
- 不在失败时静默改用旧 BTM 逻辑。

## 11. Suggested Skills

后续实现建议使用：

- `context7-cli`：确认 Blender 5.0 FBX / vertex color 导出 API。
- `systematic-debugging`：Toolbag loader 或 API 字段名不明时。
- `hst-blender-regression`：跑项目内 Blender 回归测试。
- `windows-patch-fallback`：Windows 下稳定编辑文件。
