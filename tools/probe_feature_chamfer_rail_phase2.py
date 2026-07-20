# -*- coding: utf-8 -*-
"""在真实主文件上比较 Boolean rail oracle 与 source-surface offset rails。"""

import json
import os
import sys
from pathlib import Path

import bpy


repo_root = Path(os.environ["HST_ADDON_ROOT"])
sys.path.insert(0, str(repo_root.parent))
addon = __import__(repo_root.name)
utils = addon.utils.experimental_pipe_chamfer_utils
source = bpy.data.objects.get("Extruded.002")
if source is None:
    raise RuntimeError("Extruded.002 missing")
fingerprint_before = addon.utils.feature_chamfer_gn_utils.source_fingerprint(source)
try:
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=float(os.environ.get("HST_PHASE2_RADIUS", "0.01")),
        pipe_resolution=int(os.environ.get("HST_PHASE2_RESOLUTION", "8")),
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="OPEN_BOUNDARY",
        keep_debug_objects=True,
    )
except utils.PipeChamferError as error:
    stats = error.stats
fingerprint_after = addon.utils.feature_chamfer_gn_utils.source_fingerprint(source)
feature_groups = utils._build_feature_graph(
    source,
    35.0,
    3.0,
    utils._base_stats(
        source,
        float(os.environ.get("HST_PHASE2_RADIUS", "0.01")),
        int(os.environ.get("HST_PHASE2_RESOLUTION", "8")),
        35.0,
        3.0,
        1.5,
        "FEATURE_GRAPH",
    ),
)
strip_ports = utils.extract_feature_chamfer_strip_ports(
    feature_groups,
    stats["surface_offset_rail_pairs"],
    float(os.environ.get("HST_PHASE2_RADIUS", "0.01")),
)
junction_records = utils.build_feature_chamfer_junction_records(
    strip_ports,
    float(os.environ.get("HST_PHASE2_RADIUS", "0.01")),
    1.5,
)
stats["strip_ports"] = strip_ports
stats["junction_records"] = junction_records
junction_artifact, junction_guard = utils.build_feature_chamfer_junction_artifact(
    source,
    junction_records,
)
strip_artifact, strip_guard = utils.build_feature_chamfer_strip_artifact(
    source,
    feature_groups,
    stats["surface_offset_rail_pairs"],
)
blend_path = Path(
    os.environ.get(
        "HST_PHASE2_BLEND_PATH",
        str(Path(os.environ["HST_PHASE2_PROBE_PATH"]).with_suffix(".blend")),
    )
)
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
for key in ("boolean_rail_pairs", "surface_offset_rail_pairs"):
    for record in stats.get(key, []):
        record["max_width_error"] = max(record["width_error"], default=0.0)
        record["mean_width_error"] = (
            sum(record["width_error"]) / len(record["width_error"])
            if record["width_error"]
            else 0.0
        )
summary = {
    "status": stats.get("status"),
    "source_fingerprint_unchanged": fingerprint_before == fingerprint_after,
    "boolean": stats.get("rail_oracle_summary", {}).get("boolean", {}),
    "source_surface": stats.get("rail_oracle_summary", {}).get(
        "source_surface",
        {},
    ),
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
    "strip_artifact": strip_artifact.name,
    "strip_artifact_path": str(blend_path),
    "strip_port_count": len(strip_ports),
    "junction_record_count": len(junction_records),
    "junction_type_counts": {
        junction_type: sum(
            1 for record in junction_records if record["type"] == junction_type
        )
        for junction_type in {record["type"] for record in junction_records}
    },
    "junction_artifact": junction_artifact.name,
    "junction_guard": junction_guard,
    "strip_guard": strip_guard,
}
stats["phase2_summary"] = summary
output_path = Path(os.environ["HST_PHASE2_PROBE_PATH"])
output_path.write_text(
    json.dumps(stats, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("HST_PHASE2_PROBE=" + json.dumps(summary, ensure_ascii=False))