# -*- coding: utf-8 -*-
"""
CAD 模型处理 Operators
====================

包含 CAD 模型导入后的预处理、修复、清理等功能。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *
from ..MeshOps import check_non_solid_meshes


class HST_OT_PrepCADMesh(bpy.types.Operator):
    """初始化导入的 CAD 模型 FBX"""
    bl_idname = "hst.prepcadmesh"
    bl_label = "Prep CAD FBX Mesh"
    bl_description = "初始化导入的CAD模型fbx，清理孤立顶点，UV初始化\
        需要保持模型水密\
        如果模型的面是分开的请先使用FixCADObj工具修理"
    bl_options = {'REGISTER', 'UNDO'}

    uv_seam_mode: bpy.props.EnumProperty(
        name="UV Seam Mode",
        description="选择自动UV Seam的处理模式",
        items=[
            ('STANDARD', "Standard", "标准模式：适用于两端开口的管道/圆柱（在两个 boundary 之间找 seam）"),
            ('CAPPED', "Capped", "带盖模式：适用于单端或双端封闭的回转体模型（智能识别 Side Faces）"),
        ],
        default='STANDARD'
    )

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        active_object = bpy.context.active_object

        # clean up
        bad_collection = Collection.get_by_name(BAD_MESHES_COLLECTION)
        if bad_collection is not None and len(bad_collection.all_objects) == 0:
            bpy.data.collections.remove(bad_collection)

        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        set_default_scene_units()

        collections = []

        for mesh in selected_meshes:
            if mesh.users_collection[0] not in collections:
                collections.append(mesh.users_collection[0])
            if Object.check_empty_mesh(mesh) is True:
                bpy.data.objects.remove(mesh)
                selected_meshes.remove(mesh)
        if active_object not in selected_meshes:
            bpy.context.view_layer.objects.active = selected_meshes[0]

        store_mode = prep_select_mode()
        if len(collections) > 0:
            for collection in collections:
                collection_type = Collection.get_hst_type(collection)
                if collection_type == Const.TYPE_DECAL_COLLECTION:
                    self.report(
                        {"ERROR"},
                        "Selected collections has decal collection, operation stop\n"
                        + "选中的Collection包含Decal Collection，操作停止",
                    )
                    return {"CANCELLED"}
                new_collection_name = clean_collection_name(collection.name)
                if collection.name != "Scene Collection":
                    collection.name = new_collection_name

        bad_meshes = check_non_solid_meshes(selected_meshes)
        if bad_meshes:
            bad_mesh_count = len(bad_meshes)
            self.report(
                {"ERROR"},
                f"{bad_mesh_count} selected meshes has open boundary | {bad_mesh_count}个选中的模型有开放边界",
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            Transform.apply(mesh, location=False, rotation=True, scale=True)
            Mesh.clean_mid_verts(mesh)
            Mesh.clean_loose_verts(mesh)
            Object.mark_hst_type(mesh, "STATICMESH")

            has_uv = has_uv_attribute(mesh)
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

            for edge in mesh.data.edges:
                edge.use_seam = True if edge.use_edge_sharp else False

            Mesh.auto_seam(mesh, mode=self.uv_seam_mode)

        Mesh.merge_verts_ops(selected_meshes)

        uv_unwrap(
            selected_meshes, method="ANGLE_BASED", margin=0.005, correct_aspect=True
        )
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        restore_select_mode(store_mode)
        self.report({"INFO"}, "Selected meshes prepped")
        return {"FINISHED"}


class HST_OT_CleanVertex(bpy.types.Operator):
    """清理模型中的孤立顶点"""
    bl_idname = "hst.cleanvert"
    bl_label = "Clean Verts"
    bl_description = "清理模型中的孤立顶点，只能用在水密模型上，否则会造成模型损坏"

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

        store_object_mode = bpy.context.active_object.mode
        bpy.ops.object.mode_set(mode="OBJECT")
        for mesh in selected_meshes:
            check_mesh = Mesh.check_open_bondary(mesh)
            if check_mesh is True:
                self.report(
                    {"ERROR"},
                    "Selected mesh has open boundary, please check\n"
                    + "选中的模型有开放边界，请检查",
                )
                return {"CANCELLED"}
            Mesh.clean_mid_verts(mesh)
            Mesh.clean_loose_verts(mesh)
        bpy.ops.object.mode_set(mode=store_object_mode)
        self.report({"INFO"}, "Selected meshes cleaned")
        return {"FINISHED"}


class HST_OT_FixCADObj(bpy.types.Operator):
    """修理 CAD 输出的 OBJ 文件"""
    bl_idname = "hst.fixcadobj"
    bl_label = "Fix CAD Obj"
    bl_description = "修理CAD输出的obj，以便进行后续操作\
        自动合并面，并根据顶点法线标记锐边"

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

        for mesh in selected_meshes:
            Transform.apply(mesh, location=False, rotation=True, scale=True)
        Mesh.merge_verts_ops(selected_meshes)

        bad_meshes = check_non_solid_meshes(selected_meshes)
        if bad_meshes:
            bad_mesh_count = len(bad_meshes)
            self.report(
                {"ERROR"},
                f"{bad_mesh_count} selected meshes has open boundary | {bad_mesh_count}个选中的模型有开放边界",
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            mark_sharp_edges_by_split_normal(mesh)
            mesh.select_set(True)

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Selected meshes fixed")
        return {"FINISHED"}


class HST_OT_SeparateMultiUser(bpy.types.Operator):
    """清理 Multi User"""
    bl_idname = "hst.sepmultiuser"
    bl_label = "Clean Multi User"
    bl_description = "清理multi user，可能会造成冗余资源，请及时清除"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            message_box(
                "No selected object, please select objects and retry | "
                + "没有选中物体，请选中物体后重试"
            )
            return {"CANCELLED"}
        bpy.ops.object.make_single_user(
            type="SELECTED_OBJECTS", object=True, obdata=True
        )

        self.report({"INFO"}, "Done")
        return {"FINISHED"}


class HST_OT_MarkSharp(bpy.types.Operator):
    """根据法线标记锐边"""
    bl_idname = "hst.marksharp"
    bl_label = "Mark Sharp by Normal"
    bl_description = "Mark Sharp Edge by Split Normal"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        for mesh in selected_meshes:
            mark_sharp_edges_by_split_normal(mesh)
        return {"FINISHED"}
