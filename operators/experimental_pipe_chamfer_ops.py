# -*- coding: utf-8 -*-
"""实验性多 Pipe Chamfer Operator。"""

import json

import bpy

from ..utils.experimental_pipe_chamfer_utils import PipeChamferError
from ..utils.experimental_pipe_chamfer_utils import build_pipe_chamfer


RESULT_PREFIX = "[HST_PIPE_CHAMFER_RESULT]"


class HST_OT_ExperimentalPipeChamfer(bpy.types.Operator):
    """从 Object 的全部 Sharp Edge 构建多 Pipe Chamfer"""

    bl_idname = "hst.experimental_pipe_chamfer"
    bl_label = "Experimental Pipe Chamfer"
    bl_description = "Build a multi-Pipe chamfer from all Sharp Edges"
    bl_options = {"REGISTER", "UNDO"}

    radius: bpy.props.FloatProperty(name="Radius", default=0.05, min=1.0e-5)
    pipe_resolution: bpy.props.IntProperty(name="Pipe Resolution", default=8, min=3, max=64)
    chain_turn_threshold_degrees: bpy.props.FloatProperty(
        name="Turn Threshold", default=35.0, min=1.0, max=179.0
    )
    chain_turn_spike_ratio: bpy.props.FloatProperty(name="Turn Spike Ratio", default=3.0, min=1.0)
    junction_margin: bpy.props.FloatProperty(name="Junction Margin", default=1.5, min=0.0)
    debug_stage: bpy.props.EnumProperty(
        name="Debug Stage",
        items=(
            ("FEATURE_GRAPH", "Feature Graph", "Show Sharp groups and junction nodes"),
            ("PIPES", "Pipes", "Show every independent Pipe"),
            ("CUTTER_UNION", "Cutter Set", "Show all independent Pipe cutters"),
            ("BOOLEAN_CUT", "Boolean Preview", "Keep an editable, unapplied Boolean Modifier"),
            ("OPEN_BOUNDARY", "Open Boundary", "Delete cutter Faces and show BoundaryGraph"),
            ("REGULAR_PATCHED", "Regular Patched", "Patch regular strips and leave junction holes"),
            ("PATCHED", "Patched", "Patch regular strips and junctions"),
        ),
        default="PATCHED",
    )
    keep_debug_objects: bpy.props.BoolProperty(name="Keep Debug Objects", default=False)
    source_object_name: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        source_object = context.active_object
        if source_object is None or source_object.type != "MESH":
            self.report({"ERROR"}, "Select one Mesh Object")
            return {"CANCELLED"}
        if source_object.mode != "OBJECT":
            self.report({"ERROR"}, "Experimental Pipe Chamfer requires Object Mode")
            return {"CANCELLED"}
        if len(context.selected_objects) != 1:
            self.report({"ERROR"}, "Select exactly one Mesh Object")
            return {"CANCELLED"}
        self.source_object_name = source_object.name
        return self.execute(context)

    def execute(self, context):
        source_object = bpy.data.objects.get(self.source_object_name) or context.active_object
        if source_object is None:
            self.report({"ERROR"}, "Source Object no longer exists")
            return {"CANCELLED"}
        try:
            result = build_pipe_chamfer(
                source_object=source_object,
                radius=self.radius,
                pipe_resolution=self.pipe_resolution,
                chain_turn_threshold_degrees=self.chain_turn_threshold_degrees,
                chain_turn_spike_ratio=self.chain_turn_spike_ratio,
                junction_margin=self.junction_margin,
                debug_stage=self.debug_stage,
                keep_debug_objects=self.keep_debug_objects,
            )
        except PipeChamferError as error:
            print(RESULT_PREFIX + json.dumps(error.stats, ensure_ascii=False, separators=(",", ":")))
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except Exception as error:
            raise RuntimeError(
                f"Experimental Pipe Chamfer failed unexpectedly: object={source_object.name}, "
                f"stage={self.debug_stage}, radius={self.radius}"
            ) from error
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        self.report(
            {"INFO"},
            f"pipes={result['pipe_group_count']}, junctions={result['junction_region_count']}, "
            f"regular_faces={result['regular_patch_face_count']}, "
            f"junction_faces={result['junction_patch_face_count']}",
        )
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "radius")
        layout.prop(self, "pipe_resolution")
        layout.prop(self, "chain_turn_threshold_degrees")
        layout.prop(self, "chain_turn_spike_ratio")
        layout.prop(self, "junction_margin")
        layout.prop(self, "debug_stage")
        layout.prop(self, "keep_debug_objects")
