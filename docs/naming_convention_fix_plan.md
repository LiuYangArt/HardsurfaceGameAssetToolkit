# Blender 命名规范修复计划 ✅ 已完成

## 概述

本文档记录了项目中 Operator、Panel 等命名与 Blender 官方规范的差异，并提供详细的修复方案。

---

## Blender 官方命名规范

| 类型 | 类名格式 | bl_idname 格式 | 示例 |
|------|----------|----------------|------|
| **Operator** | `{ADDON}_OT_{Name}` | `{addon}.{snake_case}` | 类名: `MESH_OT_Subdivide`, bl_idname: `mesh.subdivide` |
| **Panel** | `{ADDON}_PT_{Name}` | `{ADDON}_PT_{NAME}` | `VIEW3D_PT_tools` |
| **Menu** | `{ADDON}_MT_{Name}` | `{ADDON}_MT_{NAME}` | `OBJECT_MT_context_menu` |

> [!IMPORTANT]
> - Operator 的 `bl_idname` 中的类别前缀应使用插件专用前缀（如 `hst.`），避免与 Blender 内置操作符冲突
> - Panel/Menu 的类名应与 `bl_idname` 完全一致
> - 类名应使用 PascalCase，避免使用下划线

---

## 需要修复的问题

### 1. Panel bl_idname 大小写不一致

| 文件 | 类名 | 当前 bl_idname | 建议修改为 |
|------|------|----------------|------------|
| `UIPanel.py` | `HST_PT_EXPORT` | `HST_PT_Export` | `HST_PT_EXPORT` |
| `UIPanel.py` | `HST_PT_Skeletel` | `HST_PT_Skeletel` | `HST_PT_SKELETAL` (并修正拼写) |

---

### 2. Operator 使用了错误的类别前缀 (`object.`)

以下 Operator 使用了 `object.` 作为类别前缀，应改为 `hst.` 以避免潜在冲突：

#### BTMOperator.py

| 类名 | 当前 bl_idname | 建议 bl_idname | 建议类名 |
|------|----------------|----------------|----------|
| `BTMLowOperator` | `object.btmlow` | `hst.btm_low` | `HST_OT_BTMLow` |
| `BTMHighOperator` | `object.btmhigh` | `hst.btm_high` | `HST_OT_BTMHigh` |
| `OrgaCollOperator` | `object.orgacoll` | `hst.organize_collections` | `HST_OT_OrganizeCollections` |
| `ExportFBXOperator` | `object.exportfbx` | `hst.export_fbx` | `HST_OT_ExportFBX` |
| `OpenmMrmosetOperator` | `object.openmarmoset` | `hst.open_marmoset` | `HST_OT_OpenMarmoset` |
| `MoiTransStepOperator` | `object.moitransfile` | `hst.moi_transform_file` | `HST_OT_MoiTransformFile` |
| `ReloadObjOperator` | `object.reloadobj` | `hst.reload_object` | `HST_OT_ReloadObject` |
| `GetVerColOperator` | `object.getvercol` | `hst.get_vertex_color` | `HST_OT_GetVertexColor` |
| `BatchSetVerColOperator` | `object.setvercol` | `hst.set_vertex_color` | `HST_OT_SetVertexColor` |
| `TestButtonOperator` | `object.testbutton` | `hst.test_button` | `HST_OT_TestButton` |

#### MeshOps.py

| 类名 | 当前 bl_idname | 建议 bl_idname | 建议类名 |
|------|----------------|----------------|----------|
| `SetUECollisionOperator` | `object.adduecollision` | `hst.add_ue_collision` | `HST_OT_AddUECollision` |

#### SKMeshes.py

| 类名 | 当前 bl_idname | 建议 bl_idname | 建议类名 |
|------|----------------|----------------|----------|
| `DisplayUEBoneDirectionOperator` | `object.displayuebonedirection` | `hst.display_ue_bone_direction` | `HST_OT_DisplayUEBoneDirection` |

---

### 3. Operator 类名格式不规范

以下 Operator 类名未遵循 `{ADDON}_OT_{Name}` 格式：

#### HSTOps.py

| 当前类名 | 建议类名 | bl_idname |
|----------|----------|-----------|
| `HST_BevelTransferNormal` | `HST_OT_BevelTransferNormal` | `hst.hstbeveltransfernormal` |
| `HST_BatchBevel` | `HST_OT_BatchBevel` | `hst.hstbevelmods` |
| `HST_CreateTransferVertColorProxy` | `HST_OT_CreateTransferVertColorProxy` | `hst.hst_addtransvertcolorproxy` |
| `HST_BakeProxyVertexColorAO` | `HST_OT_BakeProxyVertexColorAO` | `hst.hst_bakeproxyvertcolrao` |
| `HST_CleanHSTObjects` | `HST_OT_CleanHSTObjects` | `hst.cleanhstobject` |
| `CurvatureVertexcolorOperator` | `HST_OT_CurvatureVertexcolor` | `hst.curvature_vertexcolor` |
| `HSTApplyMirrorModifierOperator` | `HST_OT_ApplyMirrorModifier` | `hst.apply_mirror_modifier` |
| `HSTRemoveEmptyMesh` | `HST_OT_RemoveEmptyMesh` | `hst.remove_empty_mesh` |
| `HSTActiveCollection` | `HST_OT_ActiveCollection` | `hst.active_current_collection` |
| `MakeDecalCollection` | `HST_OT_MakeDecalCollection` | `hst.make_decal_collection` |
| `MarkTintObjectOperator` | `HST_OT_MarkTintObject` | `hst.mark_tint_object` |
| `MarkAdditionalAttribute` | `HST_OT_MarkAdditionalAttribute` | `hst.mark_attribute` |
| `MarkNormalType` | `HST_OT_MarkNormalType` | `hst.mark_normal_type` |
| `MarkSpecType` | `HST_OT_MarkSpecType` | `hst.mark_spec_type` |
| `ReimportWearmaskNodeOperator` | `HST_OT_ReimportWearmaskNode` | `hst.reimportwearmasknode` |

#### MeshOps.py

| 当前类名 | 建议类名 |
|----------|----------|
| `PrepCADMeshOperator` | `HST_OT_PrepCADMesh` |
| `HST_MakeSwatchUVOperator` | `HST_OT_MakeSwatchUV` |
| `CleanVertexOperator` | `HST_OT_CleanVertex` |
| `FixCADObjOperator` | `HST_OT_FixCADObj` |
| `SeparateMultiUserOperator` | `HST_OT_SeparateMultiUser` |
| `AddSnapSocketOperator` | `HST_OT_AddSnapSocket` |
| `AddAssetOriginOperator` | `HST_OT_AddAssetOrigin` |
| `BatchAddAssetOriginOperator` | `HST_OT_BatchAddAssetOrigin` |
| `HST_SwatchMatSetupOperator` | `HST_OT_SwatchMatSetup` |
| `HST_PatternMatSetup` | `HST_OT_PatternMatSetup` |
| `BaseUVEditModeOperator` | `HST_OT_BaseUVEditMode` |
| `SetupLookDevEnvOperator` | `HST_OT_SetupLookDevEnv` |
| `PreviewWearMaskOperator` | `HST_OT_PreviewWearMask` |
| `SetTexelDensityOperator` | `HST_OT_SetTexelDensity` |
| `AxisCheckOperator` | `HST_OT_AxisCheck` |
| `HST_SetSceneUnitsOperator` | `HST_OT_SetSceneUnits` |
| `CheckAssetsOperator` | `HST_OT_CheckAssets` |
| `MarkDecalCollectionOperator` | `HST_OT_MarkDecalCollection` |
| `MarkPropCollectionOperator` | `HST_OT_MarkPropCollection` |
| `FixDuplicatedMaterialOperator` | `HST_OT_FixDuplicatedMaterial` |
| `SetUECollisionOperator` | `HST_OT_SetUECollision` |
| `HSTSortCollectionsOperator` | `HST_OT_SortCollections` |
| `IsolateCollectionsAltOperator` | `HST_OT_IsolateCollectionsAlt` |
| `BreakLinkFromLibraryOperator` | `HST_OT_BreakLinkFromLibrary` |
| `ResetPropTransformToOriginOperator` | `HST_OT_ResetPropTransformToOrigin` |
| `MarkSharpOperator` | `HST_OT_MarkSharp` |
| `ExtractUCXOperator` | `HST_OT_ExtractUCX` |
| `SnapTransformOperator` | `HST_OT_SnapTransform` |

#### SKMeshes.py

| 当前类名 | 建议类名 |
|----------|----------|
| `SkeletelSeparatorOperator` | `HST_OT_SkeletalSeparator` |
| `FillWeightOperator` | `HST_OT_FillWeight` |
| `FixSplitMesh` | `HST_OT_FixSplitMesh` |
| `Get_Bone_PosOperator` | `HST_OT_GetBonePos` |
| `DisplayUEBoneDirectionOperator` | `HST_OT_DisplayUEBoneDirection` |
| `FixRootBoneForUEOperator` | `HST_OT_FixRootBoneForUE` |

#### Rigging.py

| 当前类名 | 建议类名 |
|----------|----------|
| `SetSceneUnitForUnrealRigOperator` | `HST_OT_SetSceneUnitForUnrealRig` |
| `CleanupUESKMOperator` | `HST_OT_CleanupUESKM` |
| `QuickWeightOperator` | `HST_OT_QuickWeight` |
| `RenameBonesOperator` | `HST_OT_RenameBones` |
| `RenameTreeBonesOperator` | `HST_OT_RenameTreeBones` |
| `BoneDisplaySettingsOperator` | `HST_OT_BoneDisplaySettings` |
| `SetSocketBoneForUEOperator` | `HST_OT_SetSocketBoneForUE` |
| `SelectBoneInOutlinerOperator` | `HST_OT_SelectBoneInOutliner` |

#### Export.py

| 当前类名 | 建议类名 |
|----------|----------|
| `StaticMeshExportOperator` | `HST_OT_StaticMeshExport` |
| `OpenFileExplorer` | `HST_OT_OpenFileExplorer` |
| `TestFuncOperator` | `HST_OT_TestFunc` |

#### BakeOps.py

| 当前类名 | 建议类名 |
|----------|----------|
| `SetBakeCollectionLowOperator` | `HST_OT_SetBakeCollectionLow` |
| `SetBakeCollectionHighOperator` | `HST_OT_SetBakeCollectionHigh` |
| `SetObjectVertexColorOperator` | `HST_OT_SetObjectVertexColor` |
| `CopyColorAttributeFromActiveOperator` | `HST_OT_CopyColorAttributeFromActive` |
| `BlurVertexColorOperator` | `HST_OT_BlurVertexColor` |

#### DecalOps.py

| 当前类名 | 建议类名 |
|----------|----------|
| `ProjectDecalOperator` | `HST_OT_ProjectDecal` |

#### AssetLib.py

| 当前类名 | 建议类名 |
|----------|----------|
| `MakeAssetPreviewOperator` | `HST_OT_MakeAssetPreview` |
| `AddMatsToAssetLibraryOperator` | `HST_OT_AddMatsToAssetLibrary` |

---

### 4. 拼写错误

| 文件 | 当前名称 | 问题 | 建议修改 |
|------|----------|------|----------|
| `BTMOperator.py` | `OpenmMrmosetOperator` | 多余的 "m" | `OpenMarmosetOperator` |
| `UIPanel.py` | `HST_PT_Skeletel` | 拼写错误 | `HST_PT_SKELETAL` |

---

## 修复优先级

> [!WARNING]
> 修改 `bl_idname` 会导致 UI 中的按钮调用路径变化，需要同步更新所有调用该 Operator 的地方。

### 高优先级（可能导致冲突）
1. 使用 `object.` 前缀的 Operator → 改为 `hst.` 前缀

### 中优先级（规范性问题）
2. Panel bl_idname 大小写不一致
3. 拼写错误

### 低优先级（仅影响代码可读性）
4. Operator 类名格式不规范

---

## 修复步骤

1. **备份代码**：在进行任何修改前，确保代码已提交到 Git
2. **批量替换类名**：修改 Operator 类名为 `HST_OT_*` 格式
3. **修改 bl_idname**：将 `object.*` 改为 `hst.*`
4. **更新 UI 调用**：检查 `UIPanel.py` 中所有 `operator()` 调用，确保使用正确的 bl_idname
5. **修复拼写错误**
6. **测试验证**：在 Blender 中重新加载插件，验证所有功能正常

---

## 注意事项

> [!CAUTION]
> - 修改 `bl_idname` 后，用户自定义的快捷键绑定会失效
> - 如果有其他插件依赖此插件的 Operator，需要同步通知更新

---

## 参考资料

- [Blender Python API - Operators](https://docs.blender.org/api/current/bpy.ops.html)
- [Blender Python API - Panel](https://docs.blender.org/api/current/bpy.types.Panel.html)
- [Blender Add-on Tutorial](https://docs.blender.org/manual/en/latest/advanced/scripting/addon_tutorial.html)
