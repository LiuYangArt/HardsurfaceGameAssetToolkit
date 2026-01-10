# -*- coding: utf-8 -*-
"""
碰撞体和材质 Operators
=====================

包含 UE 碰撞体设置、材质修复等功能。
"""

import bpy
from ..const import *
from ..functions.common_functions import *


class HST_OT_SetUECollision(bpy.types.Operator):
    """设置选中 mesh 为 UE 碰撞体"""
    bl_idname = "hst.add_ue_collision"
    bl_label = "Set UE Collision"
    bl_description = "设置选中mesh为UE碰撞体，并设置命名与collection内的mesh对应\
        例如Collection内只有Mesh_01，那么碰撞体的命名需要是UCX_Mesh_01或者UCX_Mesh_01_01\
        制作好碰撞体模型后使用本工具进行设置，如果对应模型命名有修改请重新运行本工具配置碰撞体"

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

        selected_collections = filter_collections_selection(selected_objects)
        if len(selected_collections) == 0:
            self.report(
                {"ERROR"},
                "Selected object not in collection, please set collection and retry\n"
                + "选中的物体不在Collection中，请设置Collection后重试",
            )
            return {"CANCELLED"}
        for collection in selected_collections:
            collection_meshes, ucx_meshes = filter_static_meshes(collection)
            static_mesh = None
            for mesh in collection_meshes:
                if mesh not in selected_meshes:
                    static_mesh = mesh
                    break
            for mesh in selected_meshes:
                if mesh.users_collection[0] == collection:
                    if static_mesh is not None:
                        set_collision_object(mesh, static_mesh.name)
                    else:
                        self.report(
                            {"ERROR"},
                            "Collection: "
                            + collection.name
                            + " has no static mesh left in collection, UCX won't work | "
                            + "Collection内没有剩余的StaticMesh，无法设置。UCX需要对应的StaticMesh以正确命名",
                        )

        restore_select_mode(store_mode)
        return {"FINISHED"}


class HST_OT_ExtractUCX(bpy.types.Operator):
    """提取 UCX 碰撞体"""
    bl_idname = "hst.extractucx"
    bl_label = "ExtractUCX"

    def execute(self, context):
        ucx_meshes = []
        non_ucx_meshes = []
        current_mode = bpy.context.active_object.mode
        if current_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        all_objects = bpy.data.objects
        selected_meshes = filter_type(all_objects, "MESH")
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected_meshes:
            if obj.name.startswith("UCX_") or obj.name.startswith("U_"):
                ucx_meshes.append(obj)
            else:
                non_ucx_meshes.append(obj)

        if len(ucx_meshes) == 0:
            self.report({"ERROR"}, "No UCX mesh selected, please select UCX mesh and retry")
            return {'CANCELLED'}

        for mesh in non_ucx_meshes:
            bpy.data.objects.remove(mesh)

        for mesh in ucx_meshes:
            mesh.name = mesh.name.replace("UCX_", "U_")
            mesh.select_set(True)
        for mesh in ucx_meshes:
            bpy.context.view_layer.objects.active = mesh
            break

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        self.report({"INFO"}, f"{len(non_ucx_meshes)} meshes removed, {len(ucx_meshes)} UCX meshes extracted")
        return {"FINISHED"}


class HST_OT_FixDuplicatedMaterial(bpy.types.Operator):
    """修复重复材质"""
    bl_idname = "hst.fixduplicatedmaterial"
    bl_label = "Fix Duplicated Material"
    bl_description = "修复选中模型中的重复材质，例如 MI_Mat.001替换为MI_Mat"

    def execute(self, context):
        selected_objects = Object.get_selected()
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        bad_materials = []
        bad_meshes = []
        store_mode = prep_select_mode()

        for mesh in selected_meshes:
            bpy.ops.object.material_slot_remove_unused()
            bad_mat_index = []

            for i in range(len(mesh.material_slots)):
                is_bad_mat = False
                mat = mesh.material_slots[i].material
                if mat in bad_materials:
                    is_bad_mat = True
                elif mat not in bad_materials:
                    mat_name_split = mat.name.split(".00")
                    if len(mat_name_split) > 1:
                        mat_name = mat_name_split[0]
                        mat_good = get_scene_material(mat_name)
                        if mat_good is not None:
                            is_bad_mat = True
                        else:
                            mat.name = mat_name
                if is_bad_mat:
                    bad_mat_index.append(i)
                    bad_materials.append(mat)

            if len(bad_mat_index) > 0:
                bad_meshes.append(mesh)
                for i in bad_mat_index:
                    mat = mesh.material_slots[i].material
                    mat_name_split = mat.name.split(".00")
                    mat_name = mat_name_split[0]
                    mat_good = get_scene_material(mat_name)
                    mesh.material_slots[i].material = mat_good

            has_duplicated_mats = False
            mat_names = []
            for i in range(len(mesh.material_slots)):
                mat = mesh.material_slots[i].material
                mat_name = mat.name
                if mat_name not in mat_names:
                    mat_names.append(mat_name)
                else:
                    has_duplicated_mats = True
                    break

            if has_duplicated_mats:
                Material.remove_duplicated_mats_ops(mesh)

        restore_select_mode(store_mode)
        self.report(
            {"INFO"},
            str(len(bad_materials))
            + " Materials in "
            + str(len(bad_meshes))
            + " Meshes fixed",
        )
        return {"FINISHED"}
