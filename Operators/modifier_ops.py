# -*- coding: utf-8 -*-
"""
Modifier 操作 Operators
======================

包含批量应用/删除 Modifier 相关的操作。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *


class HST_OT_ApplyMirrorModifier(bpy.types.Operator):
    """批量应用选中物体的 Mirror Modifier"""
    bl_idname = "hst.apply_mirror_modifier"
    bl_label = "Apply Mirror Modifier"
    bl_description = "批量应用选中物体的Mirror Modifier"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            has_modifiers = False
            if mesh.modifiers is not None:
                has_modifiers = True
            if has_modifiers:
                for modifier in mesh.modifiers:
                    if modifier.type == "MIRROR":
                        mesh.select_set(True)
                        bpy.context.view_layer.objects.active = mesh
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
        return {"FINISHED"}


class HST_OT_RemoveEmptyMesh(bpy.types.Operator):
    """删除空的 Mesh 物体"""
    bl_idname = "hst.remove_empty_mesh"
    bl_label = "Remove Empty Mesh"
    bl_description = "删除空的Mesh物体"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        empty_mesh_count = 0
        temp_collection = Collection.create("_MeshCheck", type="PROXY")

        for mesh in selected_meshes:
            proxy_mesh = make_transfer_proxy_mesh(mesh, "_Check_", temp_collection)
            if Object.check_empty_mesh(proxy_mesh) is True:
                empty_mesh_count += 1
                print(f"{mesh.name} is empty mesh, remove it")

                bpy.data.meshes.remove(mesh.data)
            bpy.data.meshes.remove(proxy_mesh.data)

        bpy.data.collections.remove(temp_collection)

        self.report({"INFO"}, f"Removed {empty_mesh_count} empty mesh objects")
        return {"FINISHED"}
