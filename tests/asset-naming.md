# Prop、Decal 和 FBX 命名整理

状态：VERIFIED，等待用户人工确认。实现入口为 Mark Prop Collection、Mark Decal Collection、Make Decal Collection 和 Export FBX。

## 行为

- 设置 Prop / Decal 时自动整理名称，移除原来的可选命名开关。
- 分隔符统一为下划线；文字段只把首字母转为大写，其余大小写保留；纯数字段至少两位。
- 不维护名称词库，不猜单词，不翻译中文。无法自动处理的字符保留并提示。
- 集合使用基名；Decal 统一使用一个 `_Decal` 后缀。重名自动使用两位序号。
- FBX 按类型生成单一 `SM_` 或 `SK_` 前缀，用户导出前缀也按相同规则处理。
- 修正后的集合和模型名称写回 Blender。导出专用的类型前缀和用户前缀不反复加到集合基名中。
- 模型保留原有名称含义，只整理格式；UCX 根据原模型名跟随改名，不再把所有碰撞体关联到第一个模型。
- 不修改材质、贴图或共享 Mesh 数据名称。Bake 的命名开关保留，使用同一通用大小写和数字规则。

## 验证

完整回归：`python tools/run_blender_tests.py`。

定向检查：`python tools/run_blender_tests.py --case collection_unreal_rename_smoke --case collection_marker_optional_rename_regression --case make_decal_collection_naming_regression --case staticmeshexport_asset_naming_regression --case staticmeshexport_skeletal_naming_regression --case staticmeshexport_cat_meshgroup_instance_fbx`。

结果：`tests/artifacts/results.json`。完整日志：`tests/artifacts/asset_naming_full.log`。正式 FBX 导出测试包含重新导入后核对模型和碰撞体名称。

## 人工检查

打开 `tests/artifacts/asset_naming_review.blend`，在 Outliner 中集中检查：

1. Prop 与 Decal 集合名称的大小写、两位序号和 `_Decal` 后缀。
2. 两个模型分别具有对应的 UCX 碰撞体。
3. 再次设置集合或导出，确认名称不继续变化。
4. 材质名称仍保持原样。

对应 FBX 位于 `tests/artifacts/exports/asset_naming/`。此次检查不生成图片；用户确认前不标记 ACCEPTED。旧 UE 资产若名称变化，重导时需选择正确的已有资产。
