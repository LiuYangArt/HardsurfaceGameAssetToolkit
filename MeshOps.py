import bpy
from .Functions.CommonFunctions import *

UV_BASE = "UV0_Base"
UV_SWATCH = "UV1_Swatch"


class CleanupSpaceClaimCADMeshOperator(bpy.types.Operator):
    bl_idname = "object.cleanupspaceclaimcadmesh"
    bl_label = "CleanupSpaceClaimCADMesh"
    bl_description = "清理导入的SpaceClaim CAD模型"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        bpy.ops.object.mode_set(mode="OBJECT")

        # 清理multi user
        for object in selected_objects:
            clean_user(object)
            object.select_set(False)

        # 获取所有选中的mesh
        meshes = filter_type(selected_objects, "MESH")

        for mesh in meshes:
            mesh.select_set(True)

            has_uv = has_uv_attribute(mesh)
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

            uv_swatch = add_uv_layers(mesh, uv_name=UV_SWATCH)
            uv_swatch.active = True
            scale_uv(uv_layer=uv_swatch, scale=(
                0.001, 0.001), pivot=(0.5, 0.5))
            uv_base.active = True

            # 从锐边生成UV Seam
            for edge in mesh.data.edges:
                edge.use_seam = True if edge.use_edge_sharp else False

        # uv unwrap
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.unwrap(method='CONFORMAL', fill_holes=True,
                          correct_aspect=True, margin=0.005)
        bpy.ops.object.mode_set(mode="OBJECT")

        return {'FINISHED'}


class MakeSwatchUVOperator(bpy.types.Operator):
    bl_idname = "object.makeswatchuv"
    bl_label = "MakeSwatchUV"
    bl_description = "为CAD模型添加Swatch UV"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        bpy.ops.object.mode_set(mode="OBJECT")

        # 清理multi user
        for object in selected_objects:
            clean_user(object)
            object.select_set(False)

        # 获取所有选中的mesh
        meshes = filter_type(selected_objects, "MESH")

        for mesh in meshes:
            mesh.select_set(True)
            uv_swatch = add_uv_layers(mesh, uv_name=UV_SWATCH)
            uv_swatch.active = True
            scale_uv(uv_layer=uv_swatch, scale=(
                0.001, 0.001), pivot=(0.5, 0.5))

        return {'FINISHED'}


class CleanVertexOperator(bpy.types.Operator):
    bl_idname = "object.cleanvert"
    bl_label = "clean vert"
    bl_description = "清理模型直线中的孤立顶点"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        bpy.ops.object.mode_set(mode="EDIT")

        meshes = filter_type(selected_objects, "MESH")
        for mesh in meshes:
            clean_lonely_verts(mesh)
        bpy.ops.object.mode_set(mode="OBJECT")

        clean_loose_verts(meshes)

        return {"FINISHED"}


class FixSpaceClaimObjOperator(bpy.types.Operator):
    bl_idname = "object.fixspaceclaimobj"
    bl_label = "FixSpaceClaimObj"
    bl_description = "修理spaceclaim输出的obj"

    def execute(self, context):
        SHARP_ANGLE = 0.08
        MERGE_DISTANCE = 0.01
        DISSOLVE_ANGLE = 0.00174533

        selected_objects = bpy.context.selected_objects
        bpy.ops.object.mode_set(mode="OBJECT")

        # 清理multi user
        for object in selected_objects:
            clean_user(object)
            object.select_set(False)

        # 获取所有选中的mesh
        meshes = filter_type(selected_objects, "MESH")

        # 缝合边缘
        merge_vertes_by_distance(meshes, merge_distance = MERGE_DISTANCE)
        # 标记锐边
        mark_sharp_edge_by_angle(meshes, sharp_angle = SHARP_ANGLE)

        #limited dissolve 清理三角面，变成ngon
        for mesh in meshes:
            mesh.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.dissolve_limited(angle_limit=DISSOLVE_ANGLE)
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode="OBJECT")

        return {'FINISHED'}


classes = (CleanupSpaceClaimCADMeshOperator,
           MakeSwatchUVOperator,
           CleanVertexOperator,
           FixSpaceClaimObjOperator
           )
