# -*- coding: utf-8 -*-
"""Probe Blender Curve、Boolean material transfer 与 BMesh 删除行为。"""

import json
import os
from pathlib import Path

import bpy
import bmesh


def mesh_counts(obj):
    """统计 Mesh 的拓扑风险。

    Args:
        obj: 待统计的 Blender Mesh Object。
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result = {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "boundary_edges": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold_edges": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area_faces": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    return result


def run_probe():
    """运行 Curve、Boolean material transfer 与 BMesh 删除 probe。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    output = bpy.context.active_object
    output.name = "ProbeOutput"

    base_material = bpy.data.materials.new("HST_PROBE_BASE")
    marker = bpy.data.materials.new("HST_PROBE_MARKER")
    output.data.materials.append(base_material)
    output.data.materials.append(marker)
    marker_index = len(output.data.materials) - 1

    curve_data = bpy.data.curves.new("ProbePipe", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 1
    curve_data.bevel_depth = 0.15
    curve_data.bevel_resolution = 2
    curve_data.resolution_u = 1
    curve_data.use_fill_caps = True
    spline = curve_data.splines.new("POLY")
    points = [(-1.0, -1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0)]
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = True
    cutter = bpy.data.objects.new("ProbeCutter", curve_data)
    bpy.context.scene.collection.objects.link(cutter)
    cutter.data.materials.append(marker)

    bpy.context.view_layer.objects.active = cutter
    cutter.select_set(True)
    output.select_set(False)
    bpy.ops.object.convert(target="MESH")
    cutter = bpy.context.active_object
    for polygon in cutter.data.polygons:
        polygon.material_index = 0

    modifier = output.modifiers.new("ProbeExact", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    modifier.material_mode = "TRANSFER"
    bpy.context.view_layer.objects.active = output
    output.select_set(True)
    cutter.select_set(False)
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    marker_faces = [polygon.index for polygon in output.data.polygons if polygon.material_index == marker_index]
    bm = bmesh.new()
    bm.from_mesh(output.data)
    marker_bm_faces = [face for face in bm.faces if face.material_index == marker_index]
    boundary_before_delete = sum(
        1
        for edge in bm.edges
        if any(face in marker_bm_faces for face in edge.link_faces)
        and any(face not in marker_bm_faces for face in edge.link_faces)
    )
    bmesh.ops.delete(bm, geom=marker_bm_faces, context="FACES_KEEP_BOUNDARY")
    boundary_after_delete = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    bm.free()

    return {
        "blender_version": bpy.app.version_string,
        "curve": mesh_counts(cutter),
        "boolean": mesh_counts(output),
        "boolean_solver": modifier.bl_rna.properties["solver"].enum_items.keys(),
        "material_mode": modifier.bl_rna.properties["material_mode"].enum_items.keys(),
        "marker_index": marker_index,
        "marker_face_count": len(marker_faces),
        "boundary_before_delete": boundary_before_delete,
        "boundary_after_delete": boundary_after_delete,
    }


result = run_probe()
artifact_dir = Path(os.environ.get("HST_TEST_ARTIFACT_DIR", Path(__file__).parent / "artifacts"))
artifact_dir.mkdir(parents=True, exist_ok=True)
(artifact_dir / "experimental_pipe_chamfer_probe.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("[HST_PIPE_CHAMFER_PROBE]" + json.dumps(result, ensure_ascii=False))
