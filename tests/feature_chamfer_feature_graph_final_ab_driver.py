# -*- coding: utf-8 -*-
"""从正式 Feature Chamfer Operator 采集 Python/native A/B 合同。"""

import hashlib
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
BACKEND = os.environ["HST_FEATURE_GRAPH_AB_BACKEND"]
FIXTURE_PATH = Path(os.environ["HST_FEATURE_GRAPH_AB_FIXTURE"])
OUTPUT_JSON = Path(os.environ["HST_FEATURE_GRAPH_AB_OUTPUT_JSON"])
REPETITIONS = int(os.environ.get("HST_FEATURE_GRAPH_AB_REPETITIONS", "3"))
PACKAGE_NAME = "hst_feature_graph_final_ab_addon"
SOURCE_OBJECT_NAME = os.environ.get("HST_FEATURE_GRAPH_AB_OBJECT", "Extruded.002")
RADIUS = float(os.environ.get("HST_FEATURE_GRAPH_AB_RADIUS", "0.01"))


# 无参数；通过当前 worktree 的正式注册入口载入插件，返回插件 package。
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


# value: 任意 Blender/Python 诊断值；返回可稳定写入 JSON 的值。
def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=repr)
    if hasattr(value, "to_tuple"):
        return _json_value(value.to_tuple())
    try:
        return [_json_value(item) for item in value]
    except TypeError:
        return str(value)


# value: 已转为 JSON 的语义值；返回稳定 SHA-256。
def _stable_fingerprint(value):
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# output_object: 正式结果 Mesh Object；返回计数、健康性和顺序无关 fingerprint。
def _mesh_contract(output_object):
    mesh = output_object.data
    analysis = bmesh.new()
    analysis.from_mesh(mesh)
    boundary_edge_count = sum(len(edge.link_faces) == 1 for edge in analysis.edges)
    non_manifold_edge_count = sum(len(edge.link_faces) != 2 for edge in analysis.edges)
    zero_area_face_count = sum(face.calc_area() <= 1.0e-12 for face in analysis.faces)
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
        "fingerprint": _stable_fingerprint(payload),
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "chamfer_face_count": sum(chamfer_values),
        "boundary_edge_count": boundary_edge_count,
        "non_manifold_edge_count": non_manifold_edge_count,
        "zero_area_face_count": zero_area_face_count,
    }


# addon: 已注册插件；安装只观测正式 FeatureGraph 返回值的包装，返回捕获容器与原函数。
def _install_feature_graph_capture(addon):
    preview_utils = addon.utils.feature_chamfer_gn_utils
    original = preview_utils._preview_feature_graph_with_cache
    capture = {}

    def captured_build(source_object, radius, stats):
        groups = original(source_object, radius, stats)
        if isinstance(groups, tuple):
            groups, cache_hit = groups
        else:
            cache_hit = False
        group_value = _json_value(groups)
        matching_value = _json_value(stats.get("vertex_matching", ()))
        capture.clear()
        capture.update(
            groups=group_value,
            groups_fingerprint=_stable_fingerprint(group_value),
            matching=matching_value,
            matching_fingerprint=_stable_fingerprint(matching_value),
            stats=_json_value(stats),
        )
        return groups, cache_hit

    preview_utils._preview_feature_graph_with_cache = captured_build
    return capture, original


# addon/original: 插件与被包装原函数；恢复正式 FeatureGraph 函数，无返回值。
def _restore_feature_graph_capture(addon, original):
    addon.utils.feature_chamfer_gn_utils._preview_feature_graph_with_cache = original


# addon/backend: 插件与 python/native 后端名；设置单次测试后端，无返回值。
def _set_backend(addon, backend):
    loader = addon.utils.feature_chamfer_feature_graph_native_utils
    loader.set_backend_override_for_tests(backend)


# addon: 插件；清除测试后端覆盖，无返回值。
def _clear_backend(addon):
    addon.utils.feature_chamfer_feature_graph_native_utils.clear_backend_override_for_tests()


# addon/repetition: 插件与轮次；从正式 Operator 运行固定 Mixed 样本并返回完整合同。
def _run_once(addon, repetition):
    open_result = bpy.ops.wm.open_mainfile(
        filepath=str(FIXTURE_PATH),
        load_ui=False,
        use_scripts=False,
    )
    if open_result != {"FINISHED"}:
        raise RuntimeError(f"could not open fixture: {open_result}")
    addon.utils.feature_chamfer_gn_utils.clear_feature_chamfer_runtime_caches()
    capture, original = _install_feature_graph_capture(addon)
    try:
        source = bpy.data.objects.get(SOURCE_OBJECT_NAME)
        if source is None or source.type != "MESH":
            raise RuntimeError(f"fixture object {SOURCE_OBJECT_NAME} is missing")
        for selected_object in tuple(bpy.context.selected_objects):
            selected_object.select_set(False)
        source.hide_set(False)
        source.hide_viewport = False
        source.select_set(True)
        bpy.context.view_layer.objects.active = source
        wall_started_at = time.perf_counter()
        operation_result = bpy.ops.hst.feature_chamfer_gn(
            "INVOKE_DEFAULT",
            radius=RADIUS,
            show_cutter=False,
            dissolve_chamfer=True,
        )
        operator_wall_seconds = time.perf_counter() - wall_started_at
    finally:
        _restore_feature_graph_capture(addon, original)
    if operation_result != {"FINISHED"}:
        raise RuntimeError(f"formal operator failed: {operation_result}")
    if not capture:
        raise RuntimeError("formal operator did not execute the FeatureGraph builder")
    stats = json.loads(bpy.context.scene["hst_pipe_chamfer_last_result"])
    output_object = bpy.context.active_object
    if output_object is None or output_object.type != "MESH":
        raise RuntimeError("formal operator did not publish a Mesh output")
    plan = addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        source if addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(source) is not None else output_object
    )
    plan_payload = None
    plan_fingerprint = None
    if plan is not None:
        plan_payload = json.loads(
            addon.utils.feature_chamfer_plan_utils.chamfer_plan_json(plan)
        )
        plan_fingerprint = plan.plan_id
    feature_graph_stats = capture["stats"]
    backend_actual = (
        feature_graph_stats.get("backend_actual")
        or feature_graph_stats.get("feature_graph_backend")
        or stats.get("feature_graph_backend")
        or BACKEND
    )
    return {
        "repetition": repetition,
        "operation_result": sorted(operation_result),
        "backend_requested": BACKEND,
        "backend_actual": backend_actual,
        "mesh": _mesh_contract(output_object),
        "feature_groups": capture["groups"],
        "feature_groups_fingerprint": capture["groups_fingerprint"],
        "vertex_matching": capture["matching"],
        "vertex_matching_fingerprint": capture["matching_fingerprint"],
        "chamfer_plan": plan_payload,
        "chamfer_plan_fingerprint": plan_fingerprint,
        "feature_graph": feature_graph_stats,
        "timings": {
            "feature_graph_seconds": float(
                stats.get("feature_graph_seconds", feature_graph_stats.get("feature_graph_seconds", -1.0))
            ),
            "operator_seconds": float(stats["total_seconds"]),
            "operator_wall_seconds": operator_wall_seconds,
        },
    }


# runs: 同一后端多轮结果；返回排除计时和轮次后的稳定合同 fingerprint。
def _contract_fingerprint(runs):
    contracts = []
    for run in runs:
        contracts.append(
            {
                key: value
                for key, value in run.items()
                if key not in {"repetition", "timings", "feature_graph"}
            }
        )
    return _stable_fingerprint(contracts)


# runs: 同一后端多轮结果；返回关键阶段耗时中位数。
def _timing_medians(runs):
    return {
        key: statistics.median(run["timings"][key] for run in runs)
        for key in (
            "feature_graph_seconds",
            "operator_seconds",
            "operator_wall_seconds",
        )
    }


# 无参数；执行固定后端多轮正式 Operator 验证并写入 JSON。
def main():
    if BACKEND not in {"auto", "python", "native"}:
        raise ValueError(f"unsupported backend: {BACKEND}")
    if REPETITIONS < 1:
        raise ValueError("repetitions must be positive")
    addon = _load_addon()
    _set_backend(addon, BACKEND)
    try:
        runs = [_run_once(addon, repetition) for repetition in range(1, REPETITIONS + 1)]
    finally:
        _clear_backend(addon)
    semantic_fingerprints = {
        _stable_fingerprint(
            {
                key: value
                for key, value in run.items()
                if key not in {"repetition", "timings", "feature_graph"}
            }
        )
        for run in runs
    }
    payload = {
        "status": "PASS" if len(semantic_fingerprints) == 1 else "STOP",
        "backend": BACKEND,
        "repetitions": REPETITIONS,
        "runs": runs,
        "stable": len(semantic_fingerprints) == 1,
        "contract_fingerprint": _contract_fingerprint(runs),
        "medians": _timing_medians(runs),
        "environment": {
            "blender": bpy.app.version_string,
            "python": sys.version,
            "fixture": str(FIXTURE_PATH),
            "object": SOURCE_OBJECT_NAME,
            "radius": RADIUS,
        },
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("HST_FEATURE_GRAPH_FINAL_AB=" + json.dumps(payload, ensure_ascii=False))


main()
