# -*- coding: utf-8 -*-
"""
UV 操作 Operators
================

包含 UV 编辑、Texel Density 设置等功能。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *


class HST_OT_MakeSwatchUV(bpy.types.Operator):
    """为 CAD 模型添加 Swatch UV"""
    bl_idname = "hst.makeswatchuv"
    bl_label = "HST Make Swatch UV"
    bl_description = "为CAD模型添加Swatch UV"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        for mesh in selected_meshes:
            mesh.select_set(True)
            uv_swatch = add_uv_layers(mesh, uv_name=UV_SWATCH)
            uv_swatch.active = True
            scale_uv(uv_layer=uv_swatch, scale=(0.001, 0.001), pivot=(0.5, 0.5))

        self.report({"INFO"}, "Swatch UV added")
        return {"FINISHED"}


class HST_OT_BaseUVEditMode(bpy.types.Operator):
    """Base UV 编辑模式"""
    bl_idname = "hst.baseuveditmode"
    bl_label = "HST BaseUV Edit Mode"
    bl_description = "Base UV编辑环境"

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

        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"

        UV.show_uv_in_object_mode()

        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        for mesh in selected_meshes:
            mesh.select_set(True)
            has_uv = has_uv_attribute(mesh)
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

        uv_space.image = None
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        self.report({"INFO"}, "Base UV edit mode")
        return {"FINISHED"}


class HST_OT_SetTexelDensity(bpy.types.Operator):
    """设置 BaseUV 的 Texel Density"""
    bl_idname = "hst.setbaseuvtexeldensity"
    bl_label = "Set BaseUV TexelDensity"
    bl_description = "设置选中模型的BaseUV的Texel Density\
        选中模型后运行，可以设置模型的Texel Density\
        贴图大小和TD使用默认值即可，通常不需要设置"

    def execute(self, context):
        parameters = context.scene.hst_params
        texel_density = parameters.texture_density * 0.01
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        texture_size_x = parameters.texture_size
        texture_size_y = parameters.texture_size

        store_mode = prep_select_mode()

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            if uv_layer is None:
                self.report(
                    {"ERROR"},
                    "Selected mesh has no UV layer named 'UV0_Base', setup uv layer first\n"
                    + "选中的模型没有名为'UV0_Base'的UV，请先正确设置UV",
                )
                return {"CANCELLED"}

        uv_average_scale(selected_objects, uv_layer_name=UV_BASE)

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            old_td = get_texel_density(mesh, texture_size_x, texture_size_y)
            scale_factor = texel_density / old_td
            scale_uv(mesh, uv_layer, (scale_factor, scale_factor), (0.5, 0.5))

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Texel Density set to " + str(texel_density))
        return {"FINISHED"}
