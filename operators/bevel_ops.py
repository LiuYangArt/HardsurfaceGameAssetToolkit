# -*- coding: utf-8 -*-
"""
Bevel 操作 Operators
===================

包含 Bevel 修改器相关的批量操作。
"""

import bpy
from ..const import *
from ..functions.hst_functions import *
from ..functions.common_functions import *
from ..utils.mesh_utils import apply_safe_bevel_weight


class HST_OT_BevelTransferNormal(bpy.types.Operator):
    """添加倒角并从原模型传递法线到倒角后的模型，解决复杂曲面法线问题"""
    bl_idname = "hst.hstbeveltransfernormal"
    bl_label = "HST Batch Bevel And Transfer Normal"
    bl_description = "添加倒角并从原模型传递法线到倒角后的模型，解决复杂曲面法线问题"
    bl_options = {"REGISTER", "UNDO"}

    bevel_width: bpy.props.FloatProperty(name="set_bevel_width", default=0.5)
    bevel_segments: bpy.props.IntProperty(
        name="set_bevel_segments", default=1, min=1, max=100
    )

    def invoke(self, context, event):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        collection = get_collection(selected_objects[0])
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        self.target_meshes = selected_meshes

        if collection is None:
            self.report(
                {"ERROR"},
                "Not in collection, please put selected objects in collections and retry | \n"
                + "所选物体需要在Collections中",
            )
            return {"CANCELLED"}
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        parameters = context.scene.hst_params
        self.bevel_width_global = parameters.set_bevel_width
        self.bevel_segments_global = parameters.set_bevel_segments
        self.bevel_width = self.bevel_width_global
        self.bevel_segments = self.bevel_segments_global

        return self.execute(context)

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        parameters = context.scene.hst_params
        parameters.set_bevel_width = self.bevel_width
        parameters.set_bevel_segments = self.bevel_segments
        b_width = convert_length_by_scene_unit(self.bevel_width)
        bevel_width = b_width

        rename_prop_meshes(selected_objects)
        transfer_collection = Collection.create(TRANSFER_COLLECTION, type="PROXY")
        set_visibility(transfer_collection, True)
        transfer_object_list = []
        for mesh in selected_meshes:
            Transform.apply(mesh)
            remove_modifier(mesh, WEIGHTEDNORMAL_MODIFIER)
            transfer_object_list.append(
                make_transfer_proxy_mesh(
                    mesh, TRANSFER_MESH_PREFIX, transfer_collection
                )
            )
            add_bevel_modifier(mesh, bevel_width, self.bevel_segments)
            add_triangulate_modifier(mesh)
            add_datatransfer_modifier(mesh)
            mesh.select_set(True)

        set_visibility(transfer_collection, False)

        self.report(
            {"INFO"},
            "Added Bevel and Transfer Normal to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.label(text="Set Bevel Parameters")
        box_column.prop(self, "bevel_width")
        box_column.prop(self, "bevel_segments")


class HST_OT_SafeBevelWeight(bpy.types.Operator):
    """局部降低危险 corner 附近的 bevel weight，减少 Bevel 破面风险"""
    bl_idname = "hst.safe_bevel_weight"
    bl_label = "Safe Bevel Weight"
    bl_description = "降低高风险 corner 附近的 bevel weight，减少局部 bevel 破面"
    bl_options = {"REGISTER", "UNDO"}

    selected_only: bpy.props.BoolProperty(name="Selected Only", default=False)
    min_weight: bpy.props.FloatProperty(name="Min Weight", default=0.2, min=0.0, max=1.0)
    aggressiveness: bpy.props.FloatProperty(name="Aggressiveness", default=0.6, min=0.0, max=1.0)
    falloff_steps: bpy.props.IntProperty(name="Falloff Steps", default=1, min=0, max=5)
    short_edge_ratio: bpy.props.FloatProperty(name="Short Edge Ratio", default=2.2, min=0.5, max=10.0)
    sharp_angle_degrees: bpy.props.FloatProperty(name="Sharp Angle", default=35.0, min=1.0, max=120.0)
    corner_edge_count: bpy.props.IntProperty(name="Corner Edge Count", default=3, min=2, max=8)
    preserve_user_lower_weight: bpy.props.BoolProperty(name="Preserve Lower User Weight", default=True)

    def invoke(self, context, event):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}

        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        return self.execute(context)

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")

        processed_objects = 0
        skipped_objects = 0
        adjusted_edge_count = 0
        non_weight_modifier_objects = 0
        no_selection_objects = 0

        for mesh in selected_meshes:
            bevel_modifier = mesh.modifiers.get(BEVEL_MODIFIER)
            if bevel_modifier is None:
                skipped_objects += 1
                continue

            attribute_name = bevel_modifier.edge_weight or "bevel_weight_edge"
            result = apply_safe_bevel_weight(
                mesh,
                bevel_width=bevel_modifier.width,
                attribute_name=attribute_name,
                selected_only=self.selected_only,
                min_weight=self.min_weight,
                aggressiveness=self.aggressiveness,
                falloff_steps=self.falloff_steps,
                short_edge_ratio=self.short_edge_ratio,
                sharp_angle_degrees=self.sharp_angle_degrees,
                corner_edge_count=self.corner_edge_count,
                preserve_user_lower_weight=self.preserve_user_lower_weight,
            )

            if result["status"] == "no_selected_edges":
                no_selection_objects += 1
                continue

            processed_objects += 1
            adjusted_edge_count += result["adjusted_edge_count"]
            if bevel_modifier.limit_method != "WEIGHT":
                non_weight_modifier_objects += 1

        message = (
            f"Safe Bevel Weight: processed {processed_objects} objects, "
            f"adjusted {adjusted_edge_count} edges, skipped {skipped_objects} objects"
        )
        if self.selected_only and no_selection_objects > 0:
            message += f", no selection on {no_selection_objects} objects"
        if non_weight_modifier_objects > 0:
            message += f", {non_weight_modifier_objects} modifiers not in WEIGHT mode"

        self.report({"INFO"}, message)
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.prop(self, "selected_only")
        box_column.prop(self, "min_weight")
        box_column.prop(self, "aggressiveness")
        box_column.prop(self, "falloff_steps")
        box_column.prop(self, "short_edge_ratio")
        box_column.prop(self, "sharp_angle_degrees")
        box_column.prop(self, "corner_edge_count")
        box_column.prop(self, "preserve_user_lower_weight")


class HST_OT_BatchBevel(bpy.types.Operator):
    """批量添加 Bevel 和 WeightedNormal 修改器"""
    bl_idname = "hst.hstbevelmods"
    bl_label = "Batch Add Bevel Modifiers"
    bl_description = "批量添加Bevel和WeightedNormal\
        在已有Bevel修改器的情况下使用会根据参数设置修改Bevel修改器宽度和段数"
    bl_options = {"REGISTER", "UNDO"}

    bevel_width: bpy.props.FloatProperty(name="set_bevel_width", default=0.5)
    bevel_segments: bpy.props.IntProperty(
        name="set_bevel_segments", default=1, min=1, max=100
    )

    def invoke(self, context, event):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        collection = get_collection(selected_objects[0])
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        self.target_meshes = selected_meshes

        if collection is None:
            self.report(
                {"ERROR"},
                "Not in collection, please put selected objects in collections and retry | \n"
                + "所选物体需要在Collections中",
            )
            return {"CANCELLED"}
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        # 从Global参数中获取参数
        parameters = context.scene.hst_params
        self.bevel_width_global = parameters.set_bevel_width
        self.bevel_segments_global = parameters.set_bevel_segments
        self.bevel_width = self.bevel_width_global
        self.bevel_segments = self.bevel_segments_global

        return self.execute(context)

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")

        # 同步Bevel参数到Global
        parameters = context.scene.hst_params
        parameters.set_bevel_width = self.bevel_width
        parameters.set_bevel_segments = self.bevel_segments
        b_width = convert_length_by_scene_unit(self.bevel_width)
        bevel_width = b_width

        selected_collections = filter_collections_selection(selected_objects)
        for collection in selected_collections:
            collection_meshes, ucx_meshes = filter_static_meshes(collection)
            rename_meshes(collection_meshes, collection.name)

        for mesh in selected_meshes:
            remove_modifier(mesh, NORMALTRANSFER_MODIFIER, has_subobject=True)
            add_bevel_modifier(
                mesh,
                bevel_width,
                self.bevel_segments,
            )
            add_weightednormal_modifier(mesh)
            add_triangulate_modifier(mesh)
            mesh.select_set(True)

        self.report(
            {"INFO"},
            "Added Bevel and WeightedNormal modifier to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.label(text="Set Bevel Parameters")
        box_column.prop(self, "bevel_width")
        box_column.prop(self, "bevel_segments")
