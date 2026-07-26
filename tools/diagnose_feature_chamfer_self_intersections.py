# -*- coding: utf-8 -*-
"""统计 Feature Chamfer 最终 Mesh 的非邻接三角形相交。"""

import json
import os
from pathlib import Path

import bpy
import bmesh
from mathutils.bvhtree import BVHTree


output = bpy.data.objects.get(
    os.environ.get(
        "HST_PRODUCT_OBJECT_NAME",
        "Extruded.002_FeatureChamfer",
    )
)
if output is None or output.type != "MESH":
    raise RuntimeError("Feature Chamfer output missing")
bm = bmesh.new()
bm.from_mesh(output.data)
chamfer_layer = bm.faces.layers.bool.get("hst_feature_chamfer_face")
bmesh.ops.triangulate(
    bm,
    faces=list(bm.faces),
    quad_method="BEAUTY",
    ngon_method="BEAUTY",
)
bm.faces.ensure_lookup_table()
bm.faces.index_update()
tree = BVHTree.FromBMesh(bm, epsilon=1.0e-8)
overlaps = []
for first_index, second_index in tree.overlap(tree):
    if first_index >= second_index:
        continue
    first = bm.faces[first_index]
    second = bm.faces[second_index]
    if set(first.verts) & set(second.verts):
        continue
    overlaps.append(
        {
            "first": first_index,
            "second": second_index,
            "first_chamfer": bool(first[chamfer_layer]) if chamfer_layer else None,
            "second_chamfer": bool(second[chamfer_layer]) if chamfer_layer else None,
            "first_center": [float(value) for value in first.calc_center_median()],
            "second_center": [float(value) for value in second.calc_center_median()],
        }
    )
result = {
    "triangle_count": len(bm.faces),
    "non_adjacent_overlap_count": len(overlaps),
    "overlaps": overlaps[:2000],
}
Path(os.environ["HST_SELF_INTERSECTION_PATH"]).write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
bm.free()
