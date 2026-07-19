# -*- coding: utf-8 -*-
"""实验性多 Pipe Chamfer Operator。"""

import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import bpy

from ..utils.experimental_pipe_chamfer_utils import PipeChamferError
from ..utils.experimental_pipe_chamfer_utils import build_pipe_chamfer


RESULT_PREFIX = "[HST_PIPE_CHAMFER_RESULT]"
DIAGNOSTIC_LOG_PATH = Path(tempfile.gettempdir()) / "hst_feature_chamfer_diagnostic.jsonl"


# 生成源 Mesh 的稳定指纹，用来区分磁盘原始文件、Undo 后 Mesh 和不同插件副本收到的输入。
# source_object: 当前 Feature Chamfer 输入 Mesh；返回可写入 JSON 的诊断字段。
def _source_diagnostic(source_object):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    fingerprint_payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in mesh.vertices],
        "edges": [tuple(edge.vertices) for edge in mesh.edges],
        "polygons": [tuple(polygon.vertices) for polygon in mesh.polygons],
        "sharp_edges": [
            edge.index
            for edge in mesh.edges
            if sharp_attribute is not None and sharp_attribute.data[edge.index].value
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "blend_file": bpy.data.filepath,
        "object_name": source_object.name,
        "mesh_name": mesh.name,
        "mesh_fingerprint": fingerprint,
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "sharp_edge_count": len(fingerprint_payload["sharp_edges"]),
        "object_scale": list(source_object.scale),
        "modifier_types": [modifier.type for modifier in source_object.modifiers],
    }


# 追加一次 Feature Chamfer 诊断事件；写入失败时输出明确上下文但不改变几何流程。
# event: 事件名称；payload: 参数、代码来源、Mesh 指纹或阶段统计。
def _write_diagnostic_event(event, payload):
    record = {
        "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "event": event,
        "blender_version": bpy.app.version_string,
        "operator_module": __file__,
        "utils_module": sys.modules[build_pipe_chamfer.__module__].__file__,
        **payload,
    }
    try:
        with DIAGNOSTIC_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as error:
        print(f"[HST_PIPE_CHAMFER_DIAGNOSTIC_ERROR] path={DIAGNOSTIC_LOG_PATH}: {error}")


# 为 GUI 闪退补写当前执行状态；应用退出或正常 Blender shutdown 时不会写入误报。
# dummy: Blender handler 兼容参数；只有仍存在 active run 时记录。
def _write_crash_diagnostic(dummy):
    del dummy
    if _ACTIVE_DIAGNOSTIC_RUN is not None:
        _write_diagnostic_event("application_crash", _ACTIVE_DIAGNOSTIC_RUN)


_ACTIVE_DIAGNOSTIC_RUN = None
if hasattr(bpy.app.handlers, "load_post_fail"):
    if _write_crash_diagnostic not in bpy.app.handlers.load_post_fail:
        bpy.app.handlers.load_post_fail.append(_write_crash_diagnostic)

class HST_OT_ExperimentalPipeChamfer(bpy.types.Operator):
    """从 Object 的全部 Sharp Edge 构建多 Pipe Chamfer"""

    bl_idname = "hst.experimental_pipe_chamfer"
    bl_label = "Experimental Pipe Chamfer"
    bl_description = "Build a multi-Pipe chamfer from all Sharp Edges"
    bl_options = {"REGISTER", "UNDO"}

    radius: bpy.props.FloatProperty(name="Radius", default=0.05, min=1.0e-5, options={"SKIP_SAVE"})
    pipe_resolution: bpy.props.IntProperty(
        name="Pipe Resolution",
        default=8,
        min=3,
        max=64,
        options={"SKIP_SAVE"},
    )
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
        global _ACTIVE_DIAGNOSTIC_RUN

        source_object = bpy.data.objects.get(self.source_object_name) or context.active_object
        if source_object is None:
            self.report({"ERROR"}, "Source Object no longer exists")
            return {"CANCELLED"}
        _ACTIVE_DIAGNOSTIC_RUN = {
            "parameters": {
                "radius": self.radius,
                "pipe_resolution": self.pipe_resolution,
                "chain_turn_threshold_degrees": self.chain_turn_threshold_degrees,
                "chain_turn_spike_ratio": self.chain_turn_spike_ratio,
                "junction_margin": self.junction_margin,
                "debug_stage": self.debug_stage,
                "keep_debug_objects": self.keep_debug_objects,
            },
            "source": _source_diagnostic(source_object),
        }
        _write_diagnostic_event(
            "execute_start",
            {
                "parameters": {
                    "radius": self.radius,
                    "pipe_resolution": self.pipe_resolution,
                    "chain_turn_threshold_degrees": self.chain_turn_threshold_degrees,
                    "chain_turn_spike_ratio": self.chain_turn_spike_ratio,
                    "junction_margin": self.junction_margin,
                    "debug_stage": self.debug_stage,
                    "keep_debug_objects": self.keep_debug_objects,
                },
                "source": _source_diagnostic(source_object),
            },
        )
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
            _ACTIVE_DIAGNOSTIC_RUN["failure"] = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "stats": error.stats,
            }
            _write_diagnostic_event(
                "geometry_failure",
                {
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "stats": error.stats,
                },
            )
            print(RESULT_PREFIX + json.dumps(error.stats, ensure_ascii=False, separators=(",", ":")))
            self.report({"WARNING"}, str(error))
            _ACTIVE_DIAGNOSTIC_RUN = None
            return {"FINISHED"}
        except Exception as error:
            raise RuntimeError(
                f"Experimental Pipe Chamfer failed unexpectedly: object={source_object.name}, "
                f"stage={self.debug_stage}, radius={self.radius}"
            ) from error
        _write_diagnostic_event("geometry_success", {"stats": result})
        _ACTIVE_DIAGNOSTIC_RUN = None
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
