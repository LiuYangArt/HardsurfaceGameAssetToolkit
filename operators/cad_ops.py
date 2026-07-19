# -*- coding: utf-8 -*-
"""
CAD 模型处理 Operators
====================

包含 CAD 模型导入后的预处理、修复、清理等功能。
"""

import math

import bpy
from ..const import *
from ..functions.common_functions import *
from ..utils.mesh_utils import check_non_solid_meshes
from ..utils.misc_utils import set_default_scene_units
from ..utils.safe_ngon_utils import repair_cad_mesh


# 校验 CAD Operator 的选择上下文；context 为 Blender Context，operator 为报告错误的 Operator。
def _validate_cad_context(context: bpy.types.Context, operator: bpy.types.Operator) -> bool:
    selected_meshes = filter_type(context.selected_objects, "MESH")
    if not selected_meshes:
        operator.report(
            {"ERROR"},
            "No selected mesh object, please select mesh objects and retry\n"
            + "没有选中Mesh物体，请选中Mesh物体后重试",
        )
        return False
    return context.mode in {"OBJECT", "EDIT_MESH"}


# 检查共享 CAD pipeline 的末端 topology gate；obj 为目标 Object，stats 为 pipeline 统计。
def _raise_for_invalid_topology(obj: bpy.types.Object, stats: dict) -> None:
    topology = stats["topology"]
    if any(topology.values()):
        raise RuntimeError(f"{obj.name!r} topology validation failed: {topology}")


# 为多对象 CAD Operator 创建显式回滚快照；objects 为待处理 Mesh Object 列表。
def _create_cad_rollback_snapshots(objects: list) -> list:
    return [
        (obj, obj.data.copy(), obj.matrix_world.copy())
        for obj in objects
    ]


# 释放成功执行后不再需要的回滚 Mesh；snapshots 为 _create_cad_rollback_snapshots 的结果。
def _discard_cad_rollback_snapshots(snapshots: list) -> None:
    for _obj, mesh_data, _matrix_world in snapshots:
        if mesh_data.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh_data)


# 从快照恢复所有已处理对象，并清理失败结果 Mesh；snapshots 为回滚快照。
def _restore_cad_rollback_snapshots(snapshots: list) -> None:
    for obj, mesh_data, matrix_world in snapshots:
        failed_mesh = obj.data
        obj.data = mesh_data
        obj.matrix_world = matrix_world
        if failed_mesh.users == 0 and failed_mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(failed_mesh)


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

    use_safe_ngon: bpy.props.BoolProperty(name="Safe Ngon", default=True)
    safe_ngon_convert_coplanar: bpy.props.BoolProperty(name="Convert to Ngons", default=False)
    safe_ngon_parallel_angle: bpy.props.FloatProperty(
        name="Parallel Angle", subtype="ANGLE", default=math.radians(10.0), min=math.radians(0.0001)
    )
    safe_ngon_merge_distance: bpy.props.FloatProperty(
        name="Merge Distance", subtype="DISTANCE", default=0.01, min=0.0001
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "uv_seam_mode")
        layout.prop(self, "use_safe_ngon")
        layout.prop(self, "safe_ngon_convert_coplanar")
        layout.prop(self, "safe_ngon_parallel_angle")
        layout.prop(self, "safe_ngon_merge_distance")

    def invoke(self, context, event):
        if not _validate_cad_context(context, self):
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        active_object = bpy.context.active_object

        # clean up
        bad_collection = Collection.get_by_name(BAD_MESHES_COLLECTION)
        if bad_collection is not None and len(bad_collection.all_objects) == 0:
            bpy.data.collections.remove(bad_collection)

        if not selected_meshes:
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
                if collection_type == "DECAL":
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

        pipeline_stats = []
        rollback_snapshots = _create_cad_rollback_snapshots(selected_meshes)
        try:
            for mesh in selected_meshes:
                if mesh.data.users > 1:
                    mesh.data = mesh.data.copy()
                Transform.apply(mesh, location=False, rotation=True, scale=True)
                stats = repair_cad_mesh(
                    context,
                    mesh,
                    clean_mid_vertices=True,
                    clean_loose_vertices=True,
                    use_safe_ngon=self.use_safe_ngon,
                    convert_coplanar=self.safe_ngon_convert_coplanar,
                    parallel_angle=math.degrees(self.safe_ngon_parallel_angle),
                    merge_distance=self.safe_ngon_merge_distance,
                )
                _raise_for_invalid_topology(mesh, stats)
                pipeline_stats.append(stats)
                Object.mark_hst_type(mesh, "STATICMESH")

                has_uv = has_uv_attribute(mesh)
                if has_uv is True:
                    uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
                else:
                    uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
                uv_base.active = True

                mark_sharp_edges_by_split_normal(mesh)
                for edge in mesh.data.edges:
                    edge.use_seam = edge.use_edge_sharp

                Mesh.auto_seam(mesh, mode=self.uv_seam_mode)
        except Exception as error:
            _restore_cad_rollback_snapshots(rollback_snapshots)
            restore_select_mode(store_mode)
            self.report({"ERROR"}, str(error))
            raise
        else:
            _discard_cad_rollback_snapshots(rollback_snapshots)

        uv_unwrap(
            selected_meshes, method="ANGLE_BASED", margin=0.005, correct_aspect=True
        )
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        restore_select_mode(store_mode)
        print(f"Prepare CAD Mesh stats: {pipeline_stats}")
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
        if not selected_meshes:
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
    bl_options = {"REGISTER", "UNDO"}

    use_safe_ngon: bpy.props.BoolProperty(name="Safe Ngon", default=True)
    safe_ngon_convert_coplanar: bpy.props.BoolProperty(name="Convert to Ngons", default=False)
    safe_ngon_parallel_angle: bpy.props.FloatProperty(
        name="Parallel Angle", subtype="ANGLE", default=math.radians(10.0), min=math.radians(0.0001)
    )
    safe_ngon_merge_distance: bpy.props.FloatProperty(
        name="Merge Distance", subtype="DISTANCE", default=0.01, min=0.0001
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_safe_ngon")
        layout.prop(self, "safe_ngon_convert_coplanar")
        layout.prop(self, "safe_ngon_parallel_angle")
        layout.prop(self, "safe_ngon_merge_distance")

    def invoke(self, context, event):
        if not _validate_cad_context(context, self):
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        if not selected_meshes:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()

        for object in selected_objects:
            object.select_set(False)

        pipeline_stats = []
        rollback_snapshots = _create_cad_rollback_snapshots(selected_meshes)
        try:
            for mesh in selected_meshes:
                if mesh.data.users > 1:
                    mesh.data = mesh.data.copy()
                Transform.apply(mesh, location=False, rotation=True, scale=True)
                stats = repair_cad_mesh(
                    context,
                    mesh,
                    clean_mid_vertices=False,
                    clean_loose_vertices=False,
                    use_safe_ngon=self.use_safe_ngon,
                    convert_coplanar=self.safe_ngon_convert_coplanar,
                    parallel_angle=math.degrees(self.safe_ngon_parallel_angle),
                    merge_distance=self.safe_ngon_merge_distance,
                )
                _raise_for_invalid_topology(mesh, stats)
                pipeline_stats.append(stats)
                mark_sharp_edges_by_split_normal(mesh)
                mesh.select_set(True)
        except Exception as error:
            _restore_cad_rollback_snapshots(rollback_snapshots)
            restore_select_mode(store_mode)
            self.report({"ERROR"}, str(error))
            raise
        else:
            _discard_cad_rollback_snapshots(rollback_snapshots)

        restore_select_mode(store_mode)
        print(f"Fix CAD Obj stats: {pipeline_stats}")
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
