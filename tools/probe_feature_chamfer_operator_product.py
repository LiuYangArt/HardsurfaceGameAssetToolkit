# -*- coding: utf-8 -*-
"""从目标 Feature Chamfer Operator 运行真实 mixed fixture。"""

import json
import os
import sys
from pathlib import Path

import bpy
import bmesh

REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
sys.path.insert(0, str(REPO_ROOT.parent))
ADDON = __import__(REPO_ROOT.name)
ADDON.register()
source = bpy.data.objects.get("Extruded.002")
if source is None:
    raise RuntimeError("Extruded.002 missing")
for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
source.hide_set(False)
source.select_set(True)
bpy.context.view_layer.objects.active = source
source_vertex_coordinates_before = [tuple(vertex.co) for vertex in source.data.vertices]
preview_result = bpy.ops.hst.feature_chamfer_gn(
    "EXEC_DEFAULT",
    action="PREVIEW",
    source_object_name=source.name,
    radius=float(os.environ.get("HST_OPERATOR_RADIUS", "0.01")),
)
finalize_result = bpy.ops.hst.feature_chamfer_gn(
    "EXEC_DEFAULT",
    action="FINALIZE",
    source_object_name=source.name,
)
output = bpy.context.active_object
chamfer_attribute = output.data.attributes.get("hst_feature_chamfer_face")
bm = bmesh.new()
bm.from_mesh(output.data)
boundary_count = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
non_manifold_count = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
zero_area_count = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)
bm.free()
summary = {
    "preview_result": sorted(preview_result),
    "finalize_result": sorted(finalize_result),
    "source_object": source.name,
    "output_object": output.name,
    "output_is_separate": output is not source and output.data is not source.data,
    "source_mesh_unchanged": source_vertex_coordinates_before
    == [tuple(vertex.co) for vertex in source.data.vertices],
    "source_visible": not source.hide_get(),
    "boundary_edge_count": boundary_count,
    "non_manifold_edge_count": non_manifold_count,
    "zero_area_face_count": zero_area_count,
    "chamfer_attribute": chamfer_attribute is not None,
    "chamfer_face_count": sum(
        1 for item in chamfer_attribute.data if item.value
    ) if chamfer_attribute is not None else 0,
}
output_path = Path(os.environ["HST_OPERATOR_PROBE_PATH"])
blend_path = output_path.with_suffix(".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
summary["visual_artifact"] = str(blend_path)
output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

failures = []
if preview_result != {"FINISHED"}:
    failures.append(f"Preview result is {sorted(preview_result)}")
if finalize_result != {"FINISHED"}:
    failures.append(f"Finalize result is {sorted(finalize_result)}")
if not summary["output_is_separate"]:
    failures.append("Finalize did not create a separate output Object and Mesh")
if not summary["source_mesh_unchanged"]:
    failures.append("Finalize changed the source Mesh")
if boundary_count != 0:
    failures.append(f"Output has {boundary_count} boundary edges")
if non_manifold_count != 0:
    failures.append(f"Output has {non_manifold_count} non-manifold edges")
if zero_area_count != 0:
    failures.append(f"Output has {zero_area_count} zero-area faces")
if summary["chamfer_face_count"] <= 0:
    failures.append("Output has no marked chamfer faces")
if failures:
    raise RuntimeError("Feature Chamfer product probe failed: " + "; ".join(failures))
print("HST_OPERATOR_PRODUCT_PROBE=" + json.dumps(summary, ensure_ascii=False))
