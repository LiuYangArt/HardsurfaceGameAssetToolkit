# -*- coding: utf-8 -*-
"""在真实主文件上只读比较 Boolean rail oracle 与 source-surface offset rails。"""

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

RADIUS = float(os.environ.get("HST_PHASE2_RADIUS", "0.01"))
RESOLUTION = int(os.environ.get("HST_PHASE2_RESOLUTION", "4"))
OUTPUT_PATH = Path(
    os.environ.get(
        "HST_PHASE2_PROBE_PATH",
        str(REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_rail_phase2_probe.json"),
    )
)

fingerprint_before = ADDON.utils.feature_chamfer_gn_utils.source_fingerprint(SOURCE)
try:
    stats = UTILS.build_pipe_chamfer(
        source_object=SOURCE,
        radius=RADIUS,
        pipe_resolution=RESOLUTION,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="OPEN_BOUNDARY",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
    )
except UTILS.PipeChamferError as error:
    stats = error.stats
fingerprint_after = ADDON.utils.feature_chamfer_gn_utils.source_fingerprint(SOURCE)

for key in ("boolean_rail_pairs", "surface_offset_rail_pairs"):
    for record in stats.get(key, []):
        record["max_width_error"] = max(record["width_error"], default=0.0)
        record["mean_width_error"] = (
            sum(record["width_error"]) / len(record["width_error"])
            if record["width_error"]
            else 0.0
        )

boolean_summary = stats.get("rail_oracle_summary", {}).get("boolean", {})
surface_summary = stats.get("rail_oracle_summary", {}).get("source_surface", {})
summary = {
    "status": stats.get("status"),
    "error_code": stats.get("error_code"),
    "source_file": bpy.data.filepath,
    "object": SOURCE.name,
    "radius": RADIUS,
    "profile_resolution": RESOLUTION,
    "feature_graph_contract": stats.get("feature_graph_contract"),
    "graph_alignment": stats.get("feature_graph_contract") == "GN_PREVIEW_V1",
    "source_fingerprint_unchanged": fingerprint_before == fingerprint_after,
    "boolean": boolean_summary,
    "source_surface": surface_summary,
    "boolean_max_width_error": max(
        (
            record["max_width_error"]
            for record in stats.get("boolean_rail_pairs", [])
        ),
        default=None,
    ),
    "surface_max_width_error": max(
        (
            record["max_width_error"]
            for record in stats.get("surface_offset_rail_pairs", [])
        ),
        default=None,
    ),
    "phase2_go": (
        stats.get("feature_graph_contract") == "GN_PREVIEW_V1"
        and (
            boolean_summary.get("guarded_coverage") == 1.0
            or surface_summary.get("guarded_coverage") == 1.0
        )
    ),
    "scope": "RAIL_DIAGNOSTIC_ONLY",
}
stats["phase2_summary"] = summary
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(
    json.dumps(stats, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("HST_PHASE2_PROBE=" + json.dumps(summary, ensure_ascii=False))
