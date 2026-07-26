# -*- coding: utf-8 -*-
"""从已确认的 junction hole 诊断生成 Edge Visualizer 标准输入和源文件。"""

import json
import os
from pathlib import Path

import bpy


diagnostics_path = Path(os.environ["HST_HOLE_DIAGNOSTICS"])
source_blend_path = Path(os.environ["HST_HOLE_SOURCE_BLEND"])
visualizer_diagnostics_path = Path(os.environ["HST_HOLE_VISUALIZER_DIAGNOSTICS"])
diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
stats = diagnostics["repetitions"][0]["backend"]["stats"]
coordinates = stats["coordinates"]
output_object_name = diagnostics["repetitions"][0]["output"].get("object_name")
source_object = bpy.data.objects.get(output_object_name) if output_object_name else None
if source_object is None:
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.endswith("_FeatureChamfer")
    ]
    source_object = candidates[0] if len(candidates) == 1 else None
if source_object is None:
    raise RuntimeError("Feature Chamfer output missing or ambiguous")
edge_entries = []
edge_lengths = []
for index, start_index in enumerate((0, 4, 8), start=1):
    end_index = (start_index + 1) % len(coordinates)
    start = coordinates[start_index]
    end = coordinates[end_index]
    edge_id = f"hole_marker_{index}"
    edge_entries.append({"edge_id": edge_id, "endpoints": [start, end]})
    edge_lengths.append(
        sum((end[axis] - start[axis]) ** 2 for axis in range(3)) ** 0.5
    )
visualizer_diagnostics = {
    "object_name": source_object.name,
    "radius": diagnostics["radius"],
    "repetitions": [
        {
            "topology_diagnostics": {
                "edge_endpoints": edge_entries,
                "edge_ids": [entry["edge_id"] for entry in edge_entries],
                "edge_lengths": edge_lengths,
            }
        }
    ],
}
visualizer_diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
visualizer_diagnostics_path.write_text(
    json.dumps(visualizer_diagnostics, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
bpy.ops.wm.save_as_mainfile(
    filepath=str(source_blend_path),
    check_existing=False,
    compress=True,
)
