# -*- coding: utf-8 -*-
"""在真实 Feature Chamfer 一步入口中记录 Bridge/Fill 热点耗时。"""

import functools
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
OUTPUT_PATH = Path(os.environ["HST_BRIDGE_PROFILE_OUTPUT"])
DEFER_INTERSECTION_CHECKS = (
    os.environ.get("HST_BRIDGE_DEFER_INTERSECTION_CHECKS") == "1"
)


# module/name/records: 包装指定阶段并累计调用次数、耗时和输入规模；无返回值。
def _profile_function(module, name, records):
    original = getattr(module, name)

    @functools.wraps(original)
    def profiled(*args, **kwargs):
        started_at = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started_at
            record = records.setdefault(
                name,
                {"call_count": 0, "total_seconds": 0.0, "maximum_seconds": 0.0},
            )
            record["call_count"] += 1
            record["total_seconds"] += elapsed
            record["maximum_seconds"] = max(record["maximum_seconds"], elapsed)

    setattr(module, name, profiled)


# module/records: 记录自交检测调用是 Bridge、Fill 或最终全局检查；无返回值。
def _profile_intersections(module, records):
    original = module._self_intersection_records

    @functools.wraps(original)
    def profiled(mesh, target_faces=None):
        target_count = len(target_faces) if target_faces is not None else None
        started_at = time.perf_counter()
        try:
            return original(mesh, target_faces)
        finally:
            elapsed = time.perf_counter() - started_at
            if target_count is None:
                bucket = "all_faces"
            elif target_count <= 8:
                bucket = "fill_faces"
            else:
                bucket = "bridge_or_final_faces"
            record = records.setdefault(
                "_self_intersection_records",
                {"call_count": 0, "total_seconds": 0.0, "maximum_seconds": 0.0, "buckets": {}},
            )
            record["call_count"] += 1
            record["total_seconds"] += elapsed
            record["maximum_seconds"] = max(record["maximum_seconds"], elapsed)
            bucket_record = record["buckets"].setdefault(
                bucket,
                {"call_count": 0, "total_seconds": 0.0, "maximum_seconds": 0.0},
            )
            bucket_record["call_count"] += 1
            bucket_record["total_seconds"] += elapsed
            bucket_record["maximum_seconds"] = max(
                bucket_record["maximum_seconds"], elapsed
            )

    module._self_intersection_records = profiled


# output_object: 返回与产品矩阵一致的拓扑规范化摘要。
def _output_contract(output_object):
    mesh = output_object.data
    analysis = bmesh.new()
    analysis.from_mesh(mesh)
    boundary_count = sum(len(edge.link_faces) == 1 for edge in analysis.edges)
    non_manifold_count = sum(len(edge.link_faces) != 2 for edge in analysis.edges)
    zero_area_count = sum(face.calc_area() <= 1.0e-12 for face in analysis.faces)
    analysis.free()
    chamfer = mesh.attributes.get("hst_feature_chamfer_face")
    chamfer_values = [bool(item.value) for item in chamfer.data]
    coordinates = {
        vertex.index: tuple(round(component, 9) for component in vertex.co)
        for vertex in mesh.vertices
    }
    payload = {
        "vertices": sorted(list(coordinates[vertex.index]) for vertex in mesh.vertices),
        "edges": sorted(
            sorted(coordinates[index] for index in edge.vertices)
            for edge in mesh.edges
        ),
        "faces": sorted(
            sorted(coordinates[index] for index in polygon.vertices)
            for polygon in mesh.polygons
        ),
        "chamfer_face_count": sum(chamfer_values),
    }
    return {
        "fingerprint": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "chamfer_face_count": sum(chamfer_values),
        "boundary_count": boundary_count,
        "non_manifold_count": non_manifold_count,
        "zero_area_count": zero_area_count,
    }


# 无参数；从真实用户入口运行固定样本并输出结构化热点记录。
def main():
    package_name = "hst_feature_chamfer_bridge_profile_addon"
    spec = importlib.util.spec_from_file_location(
        package_name,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = addon
    spec.loader.exec_module(addon)
    addon.auto_load.init()
    addon.utils = sys.modules[package_name + ".utils"]
    addon.operators = sys.modules[package_name + ".operators"]
    operator_module = addon.operators.feature_chamfer_gn_ops
    bridge = addon.utils.feature_chamfer_direct_bridge_utils
    records = {}
    _profile_intersections(bridge, records)
    if DEFER_INTERSECTION_CHECKS:
        profiled_intersections = bridge._self_intersection_records

        def deferred_intersections(mesh, target_faces=None):
            if target_faces is not None:
                return []
            return profiled_intersections(mesh, target_faces)

        bridge._self_intersection_records = deferred_intersections
    for name in (
        "_clean_bridge_component",
        "_fill_junction_holes",
        "_split_junction_hole_components",
        "_weld_coincident_vertices",
        "_remove_zero_area_faces",
        "_weld_duplicate_edges",
        "_remove_wire_edges",
        "_direct_bridge_layers",
    ):
        _profile_function(bridge, name, records)
    source = bpy.data.objects["Extruded.002"]
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    source.hide_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    started_at = time.perf_counter()
    transaction = {
        "output": None,
        "cutter": None,
        "cutter_data": None,
    }
    stats = operator_module._build_preview_finalize_output(
        source,
        0.01,
        False,
        transaction,
    )
    output = transaction["output"]
    bpy.context.view_layer.objects.active = output
    output.select_set(True)
    stats["total_seconds"] = time.perf_counter() - started_at
    result = {"FINISHED"}
    total_seconds = time.perf_counter() - started_at
    payload = {
        "operator_result": sorted(result),
        "total_seconds": total_seconds,
        "reported_preview_seconds": stats.get("preview_seconds"),
        "reported_bridge_fill_seconds": stats.get("bridge_fill_seconds"),
        "records": records,
        "defer_intersection_checks": DEFER_INTERSECTION_CHECKS,
        "output_counts": [
            len(bpy.context.active_object.data.vertices),
            len(bpy.context.active_object.data.edges),
            len(bpy.context.active_object.data.polygons),
        ],
        "output_contract": _output_contract(bpy.context.active_object),
        "bridge_job_count": stats.get("bridge_job_count"),
        "fill_job_count": stats.get("junction_fill_count"),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("HST_BRIDGE_PROFILE=" + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
