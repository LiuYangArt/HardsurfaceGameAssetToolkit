# -*- coding: utf-8 -*-
"""在用户提供的 .blend 上运行 Experimental Pipe Chamfer 分阶段 probe。"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import bpy


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
PACKAGE_NAME = "hst_pipe_probe_addon"
RESULT_KEYS = (
    "source_object_name",
    "sharp_edge_count",
    "surface_patch_count",
    "pipe_group_count",
    "open_pipe_count",
    "closed_pipe_count",
    "topology_junction_count",
    "spatial_junction_count",
    "cutter_set_object_count",
    "cutter_face_count",
    "ambiguous_face_count",
    "source_face_count_before_boolean",
    "preserved_original_face_count",
    "deleted_original_face_count",
    "deleted_groove_face_count",
    "boundary_edge_count_after",
    "non_manifold_edge_count_after",
    "zero_area_face_count",
    "regular_region_count",
    "junction_region_count",
    "regular_patch_face_count",
    "junction_patch_face_count",
    "rail_chain_count",
    "bridge_attempt_count",
    "bridge_failure_messages",
    "bridge_face_counts",
    "remaining_boundary_loop_count",
    "error_code",
    "error_message",
)


# 从工作区加载 add-on，确保 probe 使用尚未安装的最新代码。
def load_addon_module():
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


# 输出 compact JSON，供 agent 和后续 artifact diff 读取。
# stage: debug stage；payload: 本阶段结果或错误统计。
def emit(stage, payload):
    print("[HST_USER_BLEND_PROBE]" + json.dumps({"stage": stage, **payload}, ensure_ascii=False, separators=(",", ":")))


addon = load_addon_module()
source = next((obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.get("hst_experimental_pipe_chamfer_output")), None)
if source is None:
    raise RuntimeError("No source Mesh Object found in user blend")
utils = addon.utils.experimental_pipe_chamfer_utils
source_hash = (
    tuple(tuple(round(value, 8) for value in vertex.co) for vertex in source.data.vertices),
    tuple(tuple(edge.vertices) for edge in source.data.edges),
    tuple(tuple(polygon.vertices) for polygon in source.data.polygons),
)
for stage in ("FEATURE_GRAPH", "PIPES", "CUTTER_UNION", "BOOLEAN_CUT", "OPEN_BOUNDARY", "REGULAR_PATCHED", "PATCHED"):
    source.hide_set(False)
    try:
        result = utils.build_pipe_chamfer(
            source_object=source,
            radius=0.05,
            pipe_resolution=8,
            chain_turn_threshold_degrees=35.0,
            chain_turn_spike_ratio=3.0,
            junction_margin=1.5,
            debug_stage=stage,
            keep_debug_objects=True,
        )
        current_hash = (
            tuple(tuple(round(value, 8) for value in vertex.co) for vertex in source.data.vertices),
            tuple(tuple(edge.vertices) for edge in source.data.edges),
            tuple(tuple(polygon.vertices) for polygon in source.data.polygons),
        )
        if current_hash != source_hash:
            raise RuntimeError(f"Source Mesh changed during {stage}")
        compact_result = {key: result.get(key) for key in RESULT_KEYS if key in result}
        compact_result["extended_endpoint_count"] = sum(
            1
            for extension in result.get("pipe_endpoint_extensions", [])
            for endpoint in ("start", "end")
            if extension[endpoint] != 0.0
        )
        compact_result["endpoint_class_counts"] = {}
        for classification in result.get("pipe_endpoint_classifications", []):
            for endpoint in ("start", "end"):
                endpoint_class = classification[endpoint]
                compact_result["endpoint_class_counts"][endpoint_class] = (
                    compact_result["endpoint_class_counts"].get(endpoint_class, 0) + 1
                )
        if stage == "BOOLEAN_CUT":
            output = bpy.data.objects.get(result.get("output_object_name"))
            boolean_modifiers = (
                [modifier for modifier in output.modifiers if modifier.type == "BOOLEAN"]
                if output is not None
                else []
            )
            compact_result["boolean_modifier_count"] = len(boolean_modifiers)
            compact_result["boolean_modifier_applied"] = len(boolean_modifiers) == 0
            compact_result["boolean_solver"] = (
                boolean_modifiers[0].solver if boolean_modifiers else None
            )
        emit(stage, {"status": "finished", "result": compact_result})
        save_path = os.environ.get("HST_PIPE_PROBE_SAVE")
        if stage == "PATCHED" and save_path:
            bpy.ops.wm.save_as_mainfile(filepath=save_path)
    except utils.PipeChamferError as error:
        emit(stage, {"status": "failed", "result": {key: error.stats.get(key) for key in RESULT_KEYS if key in error.stats}})
    except Exception as error:
        emit(
            stage,
            {
                "status": "error",
                "exception_type": type(error).__name__,
                "exception_message": str(error),
            },
        )
        raise
