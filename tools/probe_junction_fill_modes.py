# -*- coding: utf-8 -*-
"""在固定 junction 轮廓上比较 Blender 原生 Fill 模式。"""

import json
import os
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree


coordinates = json.loads(os.environ["HST_JUNCTION_COORDINATES"])


# 统计当前 BMesh 的非邻接自交 pair。
# bm: 待检查 Mesh；返回相交数量。
def intersection_count(bm):
    tree = BVHTree.FromBMesh(bm, epsilon=1.0e-8)
    return sum(
        1
        for first_index, second_index in tree.overlap(tree)
        if first_index < second_index
        and not (
            set(bm.faces[first_index].verts)
            & set(bm.faces[second_index].verts)
        )
    )


results = []
for mode in ("EDGeloop", "CONTEXTUAL", "TRIANGLE"):
    bm = bmesh.new()
    vertices = [bm.verts.new(Vector(coordinate)) for coordinate in coordinates]
    edges = [
        bm.edges.new((vertices[index], vertices[(index + 1) % len(vertices)]))
        for index in range(len(vertices))
    ]
    if mode == "EDGeloop":
        result = bmesh.ops.edgeloop_fill(bm, edges=edges)
        created = list(result.get("faces", ()))
        triangulated = bmesh.ops.triangulate(
            bm,
            faces=created,
            quad_method="BEAUTY",
            ngon_method="BEAUTY",
        )
        created = list(triangulated.get("faces", ())) or created
    elif mode == "CONTEXTUAL":
        result = bmesh.ops.contextual_create(bm, geom=edges)
        created = list(result.get("faces", ()))
        triangulated = bmesh.ops.triangulate(
            bm,
            faces=created,
            quad_method="BEAUTY",
            ngon_method="BEAUTY",
        )
        created = list(triangulated.get("faces", ())) or created
    else:
        result = bmesh.ops.triangle_fill(
            bm,
            edges=edges,
            use_beauty=True,
            use_dissolve=False,
        )
        created = list(result.get("faces", ()))
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    results.append(
        {
            "mode": mode,
            "face_count": len(created),
            "intersection_count": intersection_count(bm) if bm.faces else None,
            "boundary_count": sum(len(edge.link_faces) == 1 for edge in bm.edges),
        }
    )
    bm.free()
Path(os.environ["HST_JUNCTION_PROBE_PATH"]).write_text(
    json.dumps(results, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
