# -*- coding: utf-8 -*-
"""在真实 mixed fixture 上生成 Phase 3 regular strip artifact。"""

import json
import os
import sys
from pathlib import Path

import bpy

REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
sys.path.insert(0, str(REPO_ROOT.parent))
ADDON = __import__(REPO_ROOT.name)
UTILS = ADDON.utils.experimental_pipe_chamfer_utils
SOURCE = bpy.data.objects.get("Extruded.002")
if SOURCE is None:
    raise RuntimeError("Extruded.002 missing")

OUTPUT_PATH = Path(os.environ["HST_PHASE3_PROBE_PATH"])
try:
    stats = UTILS.build_pipe_chamfer(
        source_object=SOURCE,
        radius=float(os.environ.get("HST_PHASE3_RADIUS", "0.01")),
        pipe_resolution=int(os.environ.get("HST_PHASE3_RESOLUTION", "4")),
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="REGULAR_PATCHED",
        keep_debug_objects=False,
        feature_graph_contract="GN_PREVIEW_V1",
    )
except UTILS.PipeChamferError as error:
    stats = error.stats

output = bpy.data.objects.get(stats.get("output_object_name", ""))
if output is not None:
    output.display_type = "SOLID"
    output.show_name = True
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
blend_path = OUTPUT_PATH.with_suffix(".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
summary = {
    "status": stats.get("status"),
    "error_code": stats.get("error_code"),
    "output_object_name": stats.get("output_object_name"),
    "regular_region_count": stats.get("regular_region_count"),
    "regular_patch_face_count": stats.get("regular_patch_face_count"),
    "junction_region_count": stats.get("junction_region_count"),
    "strip_port_count": stats.get("strip_port_count"),
    "remaining_boundary_edge_count": stats.get("boundary_edge_count_after"),
    "port_guard": stats.get("regular_patch_port_guard"),
    "visual_artifact": str(blend_path),
}
OUTPUT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print("HST_PHASE3_REGULAR_PROBE=" + json.dumps(summary, ensure_ascii=False))