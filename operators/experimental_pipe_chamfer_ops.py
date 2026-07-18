# -*- coding: utf-8 -*-
"""实验性 Pipe Chamfer Operator。"""

import json

import bpy

from ..utils.experimental_pipe_chamfer_utils import PipeChamferError
from ..utils.experimental_pipe_chamfer_utils import build_feature_chamfer
from ..utils.experimental_pipe_chamfer_utils import build_experimental_pipe_chamfer


RESULT_PREFIX = "[HST_PIPE_CHAMFER_RESULT]"


class HST_OT_ExperimentalPipeChamfer(bpy.types.Operator):
    """一次处理对象的全部 Sharp/Seam feature edges"""

    bl_idname = "hst.experimental_pipe_chamfer"
    bl_label = "Feature Chamfer"
    bl_description = "Chamfer all Sharp/Seam feature edges in one operation"
    bl_options = {"REGISTER", "UNDO"}

    radius: bpy.props.FloatProperty(name="Radius", default=0.05, min=1.0e-5)
    pipe_resolution: bpy.props.IntProperty(name="Segments", default=0, min=0, max=16)
    edge_source: bpy.props.EnumProperty(
        name="Edge Source",
        items=(
            ("AUTO_SHARP", "All Sharp/Seam", "Process all manifold Sharp and Seam edges"),
            ("SELECTED", "Selected Loop (Experimental)", "Use the original selected closed-loop Pipe experiment"),
        ),
        default="AUTO_SHARP",
    )
    debug_stage: bpy.props.EnumProperty(
        name="Debug Stage",
        items=(
            ("PIPE_ONLY", "Pipe Only", "Only create source duplicate and Pipe cutter"),
            ("BOOLEAN_CUT", "Boolean Cut", "Stop after Exact Boolean and marker transfer"),
            ("RECONSTRUCT", "Reconstruct", "Delete Pipe faces and bridge trim loops"),
        ),
        default="RECONSTRUCT",
    )
    keep_cutter: bpy.props.BoolProperty(name="Keep Cutter", default=True)
    source_object_name: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    selected_edge_indices_json: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        source_object = context.active_object
        if source_object is None or source_object.type != "MESH":
            self.report({"ERROR"}, "Select one Mesh Object")
            return {"CANCELLED"}
        self.source_object_name = source_object.name
        if self.edge_source == "SELECTED":
            if source_object.mode != "EDIT":
                self.report({"ERROR"}, "Selected mode requires Edit Mode")
                return {"CANCELLED"}
            source_object.update_from_editmode()
            selected_edge_indices = [edge.index for edge in source_object.data.edges if edge.select]
            if not selected_edge_indices:
                self.report({"ERROR"}, "No selected Edges")
                return {"CANCELLED"}
            self.selected_edge_indices_json = json.dumps(selected_edge_indices)
        else:
            self.selected_edge_indices_json = "[]"
        return self.execute(context)

    def execute(self, context):
        source_object = bpy.data.objects.get(self.source_object_name)
        try:
            selected_edge_indices = json.loads(self.selected_edge_indices_json or "[]")
        except json.JSONDecodeError as error:
            self.report({"ERROR"}, f"Invalid cached Edge indices: {error}")
            return {"CANCELLED"}
        if source_object is None:
            self.report({"ERROR"}, "Cached source Object no longer exists")
            return {"CANCELLED"}
        if source_object.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            if self.edge_source == "AUTO_SHARP":
                result = build_feature_chamfer(
                    source_object=source_object,
                    radius=self.radius,
                    pipe_resolution=self.pipe_resolution,
                    edge_source=self.edge_source,
                    selected_edge_indices=selected_edge_indices,
                )
            else:
                result = build_experimental_pipe_chamfer(
                    source_object=source_object,
                    selected_edge_indices=selected_edge_indices,
                    radius=self.radius,
                    pipe_resolution=self.pipe_resolution,
                    debug_stage=self.debug_stage,
                    keep_cutter=self.keep_cutter,
                )
        except PipeChamferError as error:
            print(RESULT_PREFIX + json.dumps(error.stats, ensure_ascii=False, separators=(",", ":")))
            self.report({"ERROR"}, f"{error.error_code}: {error}")
            return {"CANCELLED"}
        except Exception as error:
            raise RuntimeError(
                f"Feature Chamfer failed unexpectedly: object={source_object.name}, "
                f"stage={self.debug_stage}, radius={self.radius}"
            ) from error
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        self.report(
            {"INFO"},
            f"chains={result.get('feature_chain_count', 1)}, "
            f"open={result.get('open_chain_count', 0)}, "
            f"junctions={result.get('junction_vertex_count', 0)}, "
            f"skipped={result.get('skipped_edge_count', 0)}, "
            f"chamfer_faces={result['chamfer_face_count']}",
        )
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "edge_source")
        layout.prop(self, "radius")
        layout.prop(self, "pipe_resolution")
        if self.edge_source == "SELECTED":
            layout.prop(self, "debug_stage")
            layout.prop(self, "keep_cutter")
