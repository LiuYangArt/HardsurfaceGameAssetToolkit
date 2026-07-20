# -*- coding: utf-8 -*-
"""在真实 pipe-chamfer-mixed.blend 上执行 Phase 1 structured Curve cutter probe。"""

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
source_fingerprint = addon.utils.feature_chamfer_gn_utils.source_fingerprint(source)
try:
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=float(os.environ.get("HST_PHASE1_RADIUS", "0.01")),
        pipe_resolution=int(os.environ.get("HST_PHASE1_RESOLUTION", "8")),
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="PIPES",
        keep_debug_objects=True,
    )
except utils.PipeChamferError as error:
    stats = error.stats
stats["source_fingerprint_before"] = source_fingerprint
stats["source_fingerprint_after"] = addon.utils.feature_chamfer_gn_utils.source_fingerprint(
    source
)
stats["source_counts"] = {
    "vertices": len(source.data.vertices),
    "edges": len(source.data.edges),
    "faces": len(source.data.polygons),
}
stats["phase1_go"] = (
    stats.get("status") == "finished"
    and stats["source_fingerprint_before"] == stats["source_fingerprint_after"]
    and all(
        strand["generation_backend"] == "EVEN_THICKNESS_GN"
        and strand["geometry_guard"]["status"] == "PASS"
        for strand in stats.get("cutter_strands", [])
    )
)
output_path = Path(os.environ["HST_PHASE1_PROBE_PATH"])
output_path.write_text(
    json.dumps(stats, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("HST_PHASE1_PROBE=" + json.dumps({
    "status": stats.get("status"),
    "phase1_go": stats["phase1_go"],
    "pipe_group_count": stats.get("pipe_group_count"),
    "topology_junction_count": stats.get("topology_junction_count"),
    "failed_geometry_guards": sum(
        strand["geometry_guard"]["status"] != "PASS"
        for strand in stats.get("cutter_strands", [])
    ),
}, ensure_ascii=False))