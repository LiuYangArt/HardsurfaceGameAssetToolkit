# -*- coding: utf-8 -*-
"""从正式 Operator 采集 Feature Chamfer Bridge 清理证据。"""

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
MODE = os.environ["HST_CLEANUP_VALIDATION_MODE"]
FIXTURE_PATH = Path(os.environ["HST_CLEANUP_VALIDATION_FIXTURE"])
OUTPUT_JSON = Path(os.environ["HST_CLEANUP_VALIDATION_OUTPUT_JSON"])
OUTPUT_BLEND = Path(os.environ["HST_CLEANUP_VALIDATION_OUTPUT_BLEND"])
PACKAGE_NAME = "hst_feature_chamfer_python_cleanup_validation_addon"


# 无参数；载入并注册当前 worktree 插件，确保使用正式 Operator 注册路径。
def _load_addon():
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    module.register()
    return module


# value: Blender/Python 诊断值；递归转换为稳定 JSON 数据。
def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    try:
        return [_json_value(item) for item in value]
    except TypeError:
        return str(value)


# coordinates: mathutils.Vector 序列；返回可重放的 float64 XYZ 列表。
def _coordinate_values(coordinates):
    return [
        [float(coordinate[0]), float(coordinate[1]), float(coordinate[2])]
        for coordinate in coordinates
    ]


# output_object: 正式结果 Mesh；返回拓扑、健康性和几何 fingerprint。
def _result_contract(output_object):
    mesh = output_object.data
    analysis = bmesh.new()
    analysis.from_mesh(mesh)
    boundary_count = sum(len(edge.link_faces) == 1 for edge in analysis.edges)
    non_manifold_count = sum(len(edge.link_faces) != 2 for edge in analysis.edges)
    zero_area_count = sum(face.calc_area() <= 1.0e-12 for face in analysis.faces)
    analysis.free()
    coordinates = {
        vertex.index: tuple(round(float(value), 9) for value in vertex.co)
        for vertex in mesh.vertices
    }
    chamfer_attribute = mesh.attributes.get("hst_feature_chamfer_face")
    chamfer_values = (
        [bool(item.value) for item in chamfer_attribute.data]
        if chamfer_attribute is not None
        else []
    )
    payload = {
        "vertices": sorted(coordinates.values()),
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
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "chamfer_face_count": sum(chamfer_values),
        "boundary_edge_count": boundary_count,
        "non_manifold_edge_count": non_manifold_count,
        "zero_area_face_count": zero_area_count,
    }


# bridge: 正式 Bridge 模块；安装只观测不替代算法的细分计时包装。
def _install_instrumentation(bridge):
    deviation_calls = []
    cleanup_calls = []
    original_deviation = bridge._polyline_maximum_deviation
    original_cleanup = bridge._clean_bridge_component

    @functools.wraps(original_deviation)
    def profiled_deviation(source, cleaned, cyclic):
        started_at = time.perf_counter()
        result = original_deviation(source, cleaned, cyclic)
        elapsed = time.perf_counter() - started_at
        deviation_calls.append((source, cleaned, bool(cyclic), float(result), elapsed))
        return result

    @functools.wraps(original_cleanup)
    def profiled_cleanup(bm, component, boundary_layer):
        started_at = time.perf_counter()
        result = original_cleanup(bm, component, boundary_layer)
        elapsed = time.perf_counter() - started_at
        cleanup_calls.append((result[1], elapsed))
        return result

    bridge._polyline_maximum_deviation = profiled_deviation
    bridge._clean_bridge_component = profiled_cleanup
    return deviation_calls, cleanup_calls


# deviation_calls: 偏差输入引用；返回逐 chain 可重放数据与精确派生的点到线段求值次数。
def _replay_records(deviation_calls):
    records = []
    for chain_index, (source, cleaned, cyclic, result, elapsed) in enumerate(
        deviation_calls
    ):
        source_values = _coordinate_values(source)
        cleaned_values = _coordinate_values(cleaned)
        source_segment_count = len(source_values) if cyclic else len(source_values) - 1
        cleaned_segment_count = len(cleaned_values) if cyclic else len(cleaned_values) - 1
        records.append(
            {
                "chain_index": chain_index,
                "source_coordinates": source_values,
                "cleaned_coordinates": cleaned_values,
                "cyclic": cyclic,
                "maximum_deviation": result,
                "kernel_seconds": elapsed,
                "point_to_segment_evaluation_count": (
                    len(source_values) * cleaned_segment_count
                    + len(cleaned_values) * source_segment_count
                ),
            }
        )
    return records


# 无参数；运行 Mixed/Extruded.002/0.01 正式 Operator 并保存完整证据。
def main():
    addon = _load_addon()
    open_result = bpy.ops.wm.open_mainfile(
        filepath=str(FIXTURE_PATH),
        load_ui=False,
        use_scripts=False,
    )
    if open_result != {"FINISHED"}:
        raise RuntimeError(f"could not open fixture: {open_result}")
    bridge = addon.utils.feature_chamfer_direct_bridge_utils
    deviation_calls, cleanup_calls = _install_instrumentation(bridge)
    source = bpy.data.objects.get("Extruded.002")
    if source is None or source.type != "MESH":
        raise RuntimeError("fixture object Extruded.002 is missing")
    for selected_object in tuple(bpy.context.selected_objects):
        selected_object.select_set(False)
    source.hide_set(False)
    source.hide_viewport = False
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    wall_started_at = time.perf_counter()
    operator_result = bpy.ops.hst.feature_chamfer_gn(
        "INVOKE_DEFAULT",
        radius=0.01,
        show_cutter=False,
        dissolve_chamfer=True,
    )
    wall_seconds = time.perf_counter() - wall_started_at
    if operator_result != {"FINISHED"}:
        raise RuntimeError(f"formal operator failed: {operator_result}")
    stats = json.loads(bpy.context.scene["hst_pipe_chamfer_last_result"])
    output = bpy.context.active_object
    replay_records = _replay_records(deviation_calls)
    cleanup_records = [
        {**_json_value(record), "cleanup_seconds": elapsed}
        for record, elapsed in cleanup_calls
    ]
    no_modification_count = sum(
        record.get("merged_vertex_count", 0) == 0
        and record.get("dissolved_vertex_count", 0) == 0
        for record in cleanup_records
    )
    decision_payload = [
        {
            key: record.get(key)
            for key in (
                "cleanup_status",
                "source_edge_count",
                "cleaned_edge_count",
                "source_vertex_count",
                "cleaned_vertex_count",
                "merged_vertex_count",
                "dissolved_vertex_count",
                "zero_edge_count_before",
                "zero_edge_count_after",
                "length_delta",
                "length_tolerance",
                "geometric_tolerance",
            )
        }
        for record in cleanup_records
    ]
    payload = {
        "mode": MODE,
        "mechanism": {
            "ui_entry": "Feature Chamfer",
            "operator": "hst.feature_chamfer_gn",
            "invocation": "INVOKE_DEFAULT",
            "instrumentation": (
                "in-memory timing wrappers call the original production cleanup "
                "and deviation functions; the formal Operator remains the runtime boundary"
            ),
        },
        "environment": {
            "blender_version": bpy.app.version_string,
            "python_version": sys.version,
            "fixture": str(FIXTURE_PATH),
            "object": "Extruded.002",
            "radius": 0.01,
        },
        "operator_result": sorted(operator_result),
        "counts": {
            "total_chain_count": len(cleanup_records),
            "no_modification_chain_count": no_modification_count,
            "modified_chain_count": len(cleanup_records) - no_modification_count,
            "fast_path_hit_count": sum(
                bool(record.get("deviation_fast_path"))
                for record in cleanup_records
            ),
            "deviation_kernel_call_count": len(deviation_calls),
            "point_to_segment_evaluation_count": sum(
                record["point_to_segment_evaluation_count"]
                for record in replay_records
            ),
            "source_coordinate_count": sum(
                len(record["source_coordinates"]) for record in replay_records
            ),
            "cleaned_coordinate_count": sum(
                len(record["cleaned_coordinates"]) for record in replay_records
            ),
        },
        "timings": {
            "operator_seconds": float(stats["total_seconds"]),
            "operator_wall_seconds": wall_seconds,
            "bridge_fill_seconds": float(stats["bridge_fill_seconds"]),
            "bridge_cleanup_seconds": sum(elapsed for _, elapsed in cleanup_calls),
            "deviation_kernel_seconds": sum(
                elapsed for *_, elapsed in deviation_calls
            ),
        },
        "result_contract": _result_contract(output),
        "decision_fingerprint": hashlib.sha256(
            json.dumps(decision_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "cleanup_records": cleanup_records,
        "deviation_replay": replay_records,
        "formal_operator_stats": _json_value(stats),
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND), check_existing=False)
    print("HST_CLEANUP_VALIDATION=" + json.dumps(payload["counts"]))


if __name__ == "__main__":
    main()
