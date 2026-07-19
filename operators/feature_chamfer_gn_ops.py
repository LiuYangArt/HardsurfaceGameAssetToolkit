# -*- coding: utf-8 -*-
"""两阶段 Feature Chamfer Geometry Nodes Operator。"""

import bpy

from ..const import FEATURE_CHAMFER_GN_LAST_ACTION_TAG
from ..const import FEATURE_CHAMFER_GN_MODIFIER
from ..utils.feature_chamfer_gn_utils import FeatureChamferPreviewError
from ..utils.feature_chamfer_gn_utils import PREVIEW_VALID
from ..utils.feature_chamfer_gn_utils import cancel_gn_feature_chamfer_preview
from ..utils.feature_chamfer_gn_utils import ensure_gn_feature_chamfer_preview
from ..utils.feature_chamfer_gn_utils import live_preview_parameters
from ..utils.feature_chamfer_gn_utils import owned_preview_modifier
from ..utils.feature_chamfer_gn_utils import preview_state


# 返回 source 是否有至少一条显式 sharp_edge。
# source_object: 待验证 Mesh Object。
def _has_sharp_edge(source_object):
    attribute = source_object.data.attributes.get("sharp_edge")
    return (
        attribute is not None
        and attribute.domain == "EDGE"
        and any(bool(item.value) for item in attribute.data)
    )


# 验证 Feature Chamfer 上下文并返回 source Object。
# operator/context: 当前 Blender Operator 与 Context。
def _validated_source(operator, context, require_feature_input=True):
    source_object = context.active_object
    if source_object is None or source_object.type != "MESH":
        operator.report({"ERROR"}, "Select one Mesh Object")
        return None
    if source_object.mode != "OBJECT":
        operator.report({"ERROR"}, "Feature Chamfer GN requires Object Mode")
        return None
    if len(context.selected_objects) != 1:
        operator.report({"ERROR"}, "Select exactly one Mesh Object")
        return None
    if require_feature_input and any(abs(value - 1.0) > 1.0e-6 for value in source_object.scale):
        operator.report({"ERROR"}, "Apply Object Scale before Feature Chamfer GN")
        return None
    if require_feature_input and not _has_sharp_edge(source_object):
        operator.report({"ERROR"}, "Mesh has no explicit sharp_edge selection")
        return None
    return source_object


class HST_OT_FeatureChamferGN(bpy.types.Operator):
    """创建 procedural Feature Chamfer Preview，或固化有效 Preview"""

    bl_idname = "hst.feature_chamfer_gn"
    bl_label = "Feature Chamfer GN Preview"
    bl_description = "Preview or finalize a Geometry Nodes Feature Chamfer"
    bl_options = {"REGISTER", "UNDO"}

    action: bpy.props.EnumProperty(
        items=(
            ("AUTO", "Auto", "根据 Object 上的状态自动 Preview 或 Finalize"),
            ("PREVIEW", "Preview", "创建或重建 procedural GN preview"),
            ("FINALIZE", "Finalize", "固化当前 preview 并 Patch"),
            ("CANCEL_PREVIEW", "Cancel Preview", "移除本工具创建的 preview"),
        ),
        default="AUTO",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    resolved_action: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    source_object_name: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    radius: bpy.props.FloatProperty(name="Radius", default=0.03, min=1.0e-5)
    sample_length: bpy.props.FloatProperty(name="Sample Length", default=0.01, min=1.0e-5)
    voxel_size: bpy.props.FloatProperty(name="Voxel Size", default=0.0075, min=1.0e-5)
    adaptivity: bpy.props.FloatProperty(name="Adaptivity", default=0.05, min=0.0, max=1.0)
    show_cutter: bpy.props.BoolProperty(name="Show Cutter", default=False)

    def invoke(self, context, event):
        del event
        source_object = _validated_source(
            self,
            context,
            require_feature_input=self.action != "CANCEL_PREVIEW",
        )
        if source_object is None:
            return {"CANCELLED"}
        self.source_object_name = source_object.name
        if self.action == "AUTO":
            self.resolved_action = (
                "FINALIZE" if preview_state(source_object) == PREVIEW_VALID else "PREVIEW"
            )
        else:
            self.resolved_action = self.action
        return self.execute(context)

    def execute(self, context):
        source_object = bpy.data.objects.get(self.source_object_name) or _validated_source(
            self,
            context,
            require_feature_input=(self.resolved_action or self.action) != "CANCEL_PREVIEW",
        )
        if source_object is None:
            return {"CANCELLED"}
        actual_action = self.resolved_action or self.action
        if actual_action == "AUTO":
            actual_action = "FINALIZE" if preview_state(source_object) == PREVIEW_VALID else "PREVIEW"
        source_object[FEATURE_CHAMFER_GN_LAST_ACTION_TAG] = actual_action

        if actual_action == "CANCEL_PREVIEW":
            cancel_gn_feature_chamfer_preview(source_object)
            self.report({"INFO"}, "Feature Chamfer Preview removed")
            return {"FINISHED"}
        if actual_action == "FINALIZE":
            if preview_state(source_object) != PREVIEW_VALID:
                self.report({"WARNING"}, "Feature Chamfer Preview is stale; rebuild Preview first")
                return {"CANCELLED"}
            self.report(
                {"ERROR"},
                "Finalize is unavailable: SDF Boolean provenance/rail ownership has not passed the fail-closed gate",
            )
            return {"CANCELLED"}
        if actual_action != "PREVIEW":
            self.report({"ERROR"}, f"Unsupported Feature Chamfer action: {actual_action}")
            return {"CANCELLED"}

        preview_modifier = owned_preview_modifier(source_object)
        if preview_modifier is not None and preview_state(source_object) != PREVIEW_VALID:
            live_parameters = live_preview_parameters(preview_modifier)
            self.radius = live_parameters["radius"]
            self.sample_length = live_parameters["sample_length"]
            self.voxel_size = live_parameters["voxel_size"]
            self.adaptivity = live_parameters["adaptivity"]
            self.show_cutter = live_parameters["show_cutter"]
        try:
            ensure_gn_feature_chamfer_preview(
                source_object=source_object,
                radius=self.radius,
                sample_length=self.sample_length,
                voxel_size=self.voxel_size,
                adaptivity=self.adaptivity,
                show_cutter=self.show_cutter,
            )
        except FeatureChamferPreviewError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Feature Chamfer GN Preview ready")
        return {"FINISHED"}

    def draw(self, context):
        del context
        layout = self.layout
        layout.prop(self, "radius")
        layout.prop(self, "sample_length")
        layout.prop(self, "voxel_size")
        layout.prop(self, "adaptivity")
        layout.prop(self, "show_cutter")
