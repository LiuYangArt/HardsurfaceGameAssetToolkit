# -*- coding: utf-8 -*-
"""比较 REGULAR_PATCHED 与 PATCHED 中指定 geometry face 的保留情况。"""

import json
import os
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


OUTPUT_OBJECT_NAME = os.environ.get(
    "HST_TOPOLOGY_DIAGNOSTIC_OBJECT",
    "Extruded.002_PipeChamfer_TEST",
)
OUTPUT_PATH = Path(os.environ["HST_TOPOLOGY_STAGE_RECORD_PATH"])
OUTPUT_STAGE = os.environ.get("HST_TOPOLOGY_STAGE", "UNKNOWN")
FOCUS_GROUP_ID = int(os.environ.get("HST_TOPOLOGY_FOCUS_GROUP", "3"))
FOCUS_SPAN_ID = int(os.environ.get("HST_TOPOLOGY_FOCUS_SPAN", "3"))
FOCUS_CENTER = Vector(
    tuple(
        float(value)
        for value in os.environ.get(
            "HST_TOPOLOGY_FOCUS_CENTER",
            "0.616425574,0.199089348,-0.633726716",
        ).split(",")
    )
)


# 在 focus center 附近查找最长边最大的 Face；bm: artifact BMesh。
# 返回稳定的几何记录，避免把 polygon index 当生产合同。
def _focus_face_record(bm):
    candidates = sorted(
        bm.faces,
        key=lambda face: (
            (face.calc_center_median() - FOCUS_CENTER).length,
            -max((edge.verts[1].co - edge.verts[0].co).length for edge in face.edges),
        ),
    )
    face = candidates[0]
    edge_lengths = sorted(
        (edge.verts[1].co - edge.verts[0].co).length
        for edge in face.edges
    )
    original_attribute = bm.faces.layers.int.get("hst_pipe_original_face")
    chamfer_attribute = bm.faces.layers.int.get("hst_pipe_chamfer")
    return {
        "face_index": face.index,
        "vertex_indices": [vertex.index for vertex in face.verts],
        "coordinates": [
            [round(value, 9) for value in vertex.co]
            for vertex in face.verts
        ],
        "center": [round(value, 9) for value in face.calc_center_median()],
        "area": face.calc_area(),
        "edge_lengths": edge_lengths,
        "original_face": bool(face[original_attribute]) if original_attribute else None,
        "chamfer_face": bool(face[chamfer_attribute]) if chamfer_attribute else None,
        "neighbor_face_indices": sorted(
            neighbor.index
            for edge in face.edges
            for neighbor in edge.link_faces
            if neighbor is not face
        ),
    }


output = bpy.data.objects.get(OUTPUT_OBJECT_NAME)
if output is None or output.type != "MESH":
    raise RuntimeError(f"Mesh Object missing: {OUTPUT_OBJECT_NAME}")
bm = bmesh.new()
bm.from_mesh(output.data)
bm.verts.ensure_lookup_table()
bm.edges.ensure_lookup_table()
bm.faces.ensure_lookup_table()
bm.verts.index_update()
bm.edges.index_update()
bm.faces.index_update()
record = {
    "stage": OUTPUT_STAGE,
    "object_name": output.name,
    "face_count": len(bm.faces),
    "focus_provenance": {
        "region": "REGULAR",
        "group_id": FOCUS_GROUP_ID,
        "span_id": FOCUS_SPAN_ID,
    },
    "focus_face": _focus_face_record(bm),
}
bm.free()
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("HST_TOPOLOGY_STAGE_RECORD=" + json.dumps(record, ensure_ascii=False))
