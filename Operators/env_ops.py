# -*- coding: utf-8 -*-
"""
环境设置 Operators
=================

包含材质环境设置、LookDev 预览等功能。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *


class HST_OT_SwatchMatSetup(bpy.types.Operator):
    """设置 Swatch 材质编辑环境"""
    bl_idname = "hst.swatchmatsetup"
    bl_label = "HST Swatch Edit Mode"
    bl_description = "设置Swatch材质的编辑环境，如果没有Swatch材质会自动导入"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()
        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space
        UV.show_uv_in_object_mode()
        scene_swatch_mat = get_scene_material(SWATCH_MATERIAL)
        if scene_swatch_mat is None:
            scene_swatch_mat = import_material(PRESET_FILE_PATH, SWATCH_MATERIAL)

        for mesh in selected_meshes:
            mesh.select_set(True)
            pattern_uv = check_uv_layer(mesh, Const.UV_PATTERN)

            if pattern_uv is not None:
                pattern_uv.name = UV_SWATCH

            swatch_uv = check_uv_layer(mesh, UV_SWATCH)
            if swatch_uv is None:
                swatch_uv = add_uv_layers(mesh, uv_name=UV_SWATCH)
                scale_uv(
                    mesh, uv_layer=swatch_uv, scale=(0.001, 0.001), pivot=(0.5, 0.5)
                )
            swatch_uv.active = True

            swatch_mat = get_object_material(mesh, SWATCH_MATERIAL)
            mat_slot = get_object_material_slots(mesh)
            if swatch_mat is None:
                if len(mat_slot) == 0:
                    mesh.data.materials.append(scene_swatch_mat)
                elif len(mat_slot) > 0:
                    mat_slot[0].material = scene_swatch_mat

        for subnode in scene_swatch_mat.node_tree.nodes:
            if subnode.type == "GROUP" and subnode.label == "BaseMat_Swatch":
                for nodegroup in subnode.node_tree.nodes:
                    if nodegroup.type == "TEX_IMAGE":
                        swatch_texture = nodegroup.image
                        break

        uv_space.image = swatch_texture
        uv_space.display_channels = "COLOR"
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        switch_to_eevee()
        viewport_shading_mode("VIEW_3D", "RENDERED", mode="CONTEXT")

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Swatch material initialized")
        return {"FINISHED"}


class HST_OT_PatternMatSetup(bpy.types.Operator):
    """设置 Pattern 材质编辑环境"""
    bl_idname = "hst.patternmatsetup"
    bl_label = "PatternUV"
    bl_description = "设置Pattern材质的编辑环境，如果没有Pattern材质会自动导入"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()
        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"
            uv_editor.show_uv = True
            uv_editor.uv_face_opacity = 1
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        scene_pattern_mat = get_scene_material(PATTERN_MATERIAL)
        if scene_pattern_mat is None:
            scene_pattern_mat = import_material(PRESET_FILE_PATH, PATTERN_MATERIAL)

        for mesh in selected_meshes:
            mesh.select_set(True)
            swatch_uv = check_uv_layer(mesh, UV_SWATCH)

            if swatch_uv is not None:
                swatch_uv.name = Const.UV_PATTERN

            pattern_uv = check_uv_layer(mesh, Const.UV_PATTERN)

            if pattern_uv is None:
                pattern_uv = add_uv_layers(mesh, uv_name=Const.UV_PATTERN)
            pattern_uv.active = True

            pattern_mat = get_object_material(mesh, PATTERN_MATERIAL)
            mat_slot = get_object_material_slots(mesh)
            if pattern_mat is None:
                if len(mat_slot) == 0:
                    mesh.data.materials.append(scene_pattern_mat)
                elif len(mat_slot) > 0:
                    mat_slot[0].material = scene_pattern_mat

        uv_space.image = None
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        switch_to_eevee()
        viewport_shading_mode("VIEW_3D", "RENDERED", mode="CONTEXT")

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Swatch material initialized")
        return {"FINISHED"}


class HST_OT_SetupLookDevEnv(bpy.types.Operator):
    """设置 LookDev 预览环境"""
    bl_idname = "hst.setuplookdevenv"
    bl_label = "Setup LookDev Env"
    bl_description = "设置LookDev预览环境"

    def execute(self, context):
        file_path = PRESET_FILE_PATH
        world_name = LOOKDEV_HDR
        store_mode = prep_select_mode()

        import_world(file_path=file_path, world_name=world_name)
        for world in bpy.data.worlds:
            if world.name == world_name:
                world = world
                break
        if bpy.context.scene.world is not world:
            bpy.context.scene.world = world

        switch_to_eevee()
        viewport_shading_mode("VIEW_3D", "RENDERED")

        restore_select_mode(store_mode)
        self.report({"INFO"}, "LookDev environment setup finished")
        return {"FINISHED"}


class HST_OT_PreviewWearMask(bpy.types.Operator):
    """预览 WearMask 效果"""
    bl_idname = "hst.previewwearmask"
    bl_label = "Preview WearMask"
    bl_description = "预览WearMask效果，需要Mesh有顶点色属性'WearMask'\
        选中模型后运行，可以自动切换激活的顶点色"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is not None:
            for mesh in selected_meshes:
                set_active_color_attribute(mesh, WEARMASK_ATTR)

        viewports = viewport_shading_mode("VIEW_3D", "SOLID", mode="CONTEXT")

        for viewport in viewports:
            viewport.shading.color_type = "VERTEX"

        self.report(
            {"INFO"},
            "Switch preview wearMask in viewport | 在viewport切换预览WearMask",
        )
        return {"FINISHED"}
