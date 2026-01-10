# -*- coding: utf-8 -*-
"""
Mesh Attribute 标记 Operators
============================

包含 TintMask、NormalType、SpecType 等 Attribute 标记操作。
"""

import bpy
from ..const import *
from ..functions.common_functions import *


class HST_OT_MarkTintObject(bpy.types.Operator):
    """为选中的物体添加 TintMask，储存于 WearMask 的 Alpha 通道"""
    bl_idname = "hst.mark_tint_object"
    bl_label = "Mark Tint Object"
    bl_description = "为选中的物体添加TintMask，储存于WearMask的Alpha通道"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        target_collections = filter_collections_selection(selected_objects)
        if target_collections is None:
            self.report(
                {"ERROR"},
                "Not in collection",
            )
            return {"CANCELLED"}
        for collection in target_collections:
            if collection is not None:
                collection_objects = collection.objects

                for object in collection_objects:
                    if object.type == "MESH":
                        tint_attr = MeshAttributes.add(
                            object,
                            attribute_name=Const.TINT_ATTRIBUTE,
                            data_type="FLOAT",
                            domain="POINT",
                        )

                        if object not in selected_meshes:
                            MeshAttributes.fill_points(object, tint_attr, value=0.0)
                        if object in selected_meshes:
                            MeshAttributes.fill_points(object, tint_attr, value=1.0)
        self.report({"INFO"}, f"{len(selected_meshes)} Tint Object(s) marked")
        return {"FINISHED"}


class HST_OT_MarkAdditionalAttribute(bpy.types.Operator):
    """为选中的物体添加额外的 Attribute，用于特殊材质混合"""
    bl_idname = "hst.mark_attribute"
    bl_label = "Mark Additional Attribute"
    bl_description = "为选中的物体添加额外的Attribute，用于特殊材质混合"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        target_collections = filter_collections_selection(selected_objects)
        if target_collections is None:
            self.report(
                {"ERROR"},
                "Not in collection",
            )
            return {"CANCELLED"}
        for collection in target_collections:
            if collection is not None:
                collection_objects = collection.objects

                for object in collection_objects:
                    if object.type == "MESH":
                        spec_attr = MeshAttributes.add(
                            object,
                            attribute_name=Const.SPEC_ATTRIBUTE,
                            data_type="FLOAT",
                            domain="POINT",
                        )

                        if object not in selected_meshes:
                            MeshAttributes.fill_points(object, spec_attr, value=0.0)
                        if object in selected_meshes:
                            MeshAttributes.fill_points(object, spec_attr, value=1.0)
        self.report({"INFO"}, f"{len(selected_meshes)} Tint Object(s) marked")
        return {"FINISHED"}


class HST_OT_MarkNormalType(bpy.types.Operator):
    """为选中的物体标记 Normal Type，储存于 WearMask 的 B 通道"""
    bl_idname = "hst.mark_normal_type"
    bl_label = "Mark Normal Type"
    bl_description = "为选中的物体标记Normal Type，储存于WearMask的B通道"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params
        normal_type = parameters.normal_type / NORMAL_TYPE_NUM
        print(normal_type)

        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            normal_attr = MeshAttributes.add(
                mesh,
                attribute_name=NORMAL_TYPE_ATTRIBUTE,
                data_type="FLOAT",
                domain="POINT",
            )

            MeshAttributes.fill_points(mesh, normal_attr, value=normal_type)

        self.report({"INFO"}, f"{len(selected_meshes)} Object(s) marked")
        return {"FINISHED"}


class HST_OT_MarkSpecType(bpy.types.Operator):
    """为选中的物体标记 Spec Type，用于特殊材质混合"""
    bl_idname = "hst.mark_spec_type"
    bl_label = "Mark Spec Type"
    bl_description = "为选中的物体标记Spec Type，用于特殊材质混合"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params
        spec_type = parameters.spec_type / SPEC_TYPE_NUM
        print(spec_type)

        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            spec_attr = MeshAttributes.add(
                mesh,
                attribute_name=SPEC_TYPE_ATTRIBUTE,
                data_type="FLOAT",
                domain="POINT",
            )

            MeshAttributes.fill_points(mesh, spec_attr, value=spec_type)

        self.report({"INFO"}, f"{len(selected_meshes)} Object(s) marked")
        return {"FINISHED"}
