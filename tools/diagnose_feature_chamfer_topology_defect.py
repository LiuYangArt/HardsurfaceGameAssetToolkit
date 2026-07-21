# -*- coding: utf-8 -*-
"""分析 Feature Chamfer 最终 Mesh 的局部 topology 质量。"""

import json
import math
import os
from pathlib import Path

import bpy
import bmesh


OUTPUT_OBJECT_NAME = os.environ.get(
    "HST_TOPOLOGY_DIAGNOSTIC_OBJECT",
    "Extruded.002_FeatureChamfer",
)
OUTPUT_PATH = Path(os.environ["HST_TOPOLOGY_DIAGNOSTIC_PATH"])
CHAMFER_ATTRIBUTE_NAME = "hst_feature_chamfer_face"


# 计算 Polygon 的几何质量；face: 待分析 BMesh Face。
# 返回面积、边长比、compactness、planarity 与相邻 Face indices。
def _face_record(face):
    edge_lengths = sorted(
        (edge.verts[1].co - edge.verts[0].co).length
        for edge in face.edges
    )
    area = face.calc_area()
    perimeter = sum(edge_lengths)
    center = face.calc_center_median()
    planarity = 0.0
    if len(face.verts) > 3:
        base = face.verts[0].co
        normal = (face.verts[1].co - base).cross(face.verts[2].co - base)
        if normal.length > 1.0e-12:
            normal.normalize()
            planarity = max(abs((vertex.co - base).dot(normal)) for vertex in face.verts)
    compactness = perimeter * perimeter / max(4.0 * math.pi * area, 1.0e-20)
    neighbors = sorted(
        neighbor.index
        for edge in face.edges
        for neighbor in edge.link_faces
        if neighbor is not face
    )
    return {
        "face_index": face.index,
        "vertex_indices": [vertex.index for vertex in face.verts],
        "coordinates": [
            [round(value, 9) for value in vertex.co]
            for vertex in face.verts
        ],
        "center": [round(value, 9) for value in center],
        "normal": [round(value, 9) for value in face.normal],
        "area": area,
        "edge_lengths": edge_lengths,
        "edge_ratio": edge_lengths[-1] / max(edge_lengths[0], 1.0e-20),
        "compactness": compactness,
        "planarity_error": planarity,
        "neighbor_face_indices": neighbors,
    }


# 汇总 marked chamfer Faces 并输出最可疑的长边、sliver 和非平面 Faces。
# obj: Feature Chamfer output Object；返回 JSON 可序列化诊断。
def _diagnose_object(obj):
    chamfer_attribute = obj.data.attributes.get(CHAMFER_ATTRIBUTE_NAME)
    if chamfer_attribute is None:
        chamfer_attribute = obj.data.attributes.get("hst_pipe_chamfer")
    original_attribute = obj.data.attributes.get("hst_pipe_original_face")
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    if chamfer_attribute is not None:
        marked_indices = {
            index
            for index, item in enumerate(chamfer_attribute.data)
            if item.value
        }
        provenance_mode = chamfer_attribute.name
    elif original_attribute is not None:
        marked_indices = {
            index
            for index, item in enumerate(original_attribute.data)
            if not item.value
        }
        provenance_mode = "not hst_pipe_original_face"
    else:
        raise RuntimeError(f"Chamfer provenance missing on {obj.name}")
    records = [
        _face_record(face)
        for face in bm.faces
        if face.index in marked_indices
    ]
    bounds_min = [min(vertex.co[axis] for vertex in bm.verts) for axis in range(3)]
    bounds_max = [max(vertex.co[axis] for vertex in bm.verts) for axis in range(3)]
    result = {
        "object_name": obj.name,
        "vertex_count": len(bm.verts),
        "edge_count": len(bm.edges),
        "face_count": len(bm.faces),
        "chamfer_face_count": len(records),
        "provenance_mode": provenance_mode,
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
        "boundary_edge_count": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold_edge_count": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area_face_count": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
        "top_by_compactness": sorted(
            records,
            key=lambda record: (record["compactness"], record["edge_ratio"]),
            reverse=True,
        )[:160],
        "top_by_longest_edge": sorted(
            records,
            key=lambda record: record["edge_lengths"][-1],
            reverse=True,
        )[:160],
        "top_by_planarity_error": sorted(
            records,
            key=lambda record: record["planarity_error"],
            reverse=True,
        )[:80],
    }
    bm.free()
    return result


output = bpy.data.objects.get(OUTPUT_OBJECT_NAME)
if output is None or output.type != "MESH":
    raise RuntimeError(f"Mesh Object missing: {OUTPUT_OBJECT_NAME}")
for modifier in output.modifiers:
    if modifier.type == "DATA_TRANSFER":
        modifier.show_viewport = False
        modifier.show_render = False
diagnostic = _diagnose_object(output)
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(
    json.dumps(diagnostic, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
blend_path = OUTPUT_PATH.with_suffix(".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
print(
    "HST_TOPOLOGY_DEFECT_DIAGNOSTIC="
    + json.dumps(
        {
            "object_name": output.name,
            "chamfer_face_count": diagnostic["chamfer_face_count"],
            "bounds_min": diagnostic["bounds_min"],
            "bounds_max": diagnostic["bounds_max"],
            "json": str(OUTPUT_PATH),
            "blend": str(blend_path),
        },
        ensure_ascii=False,
    )
)
