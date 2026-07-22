# -*- coding: utf-8 -*-
"""Blender-side Feature Chamfer product matrix driver。"""

import hashlib
import importlib.util
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
ARTIFACT_DIRECTORY = Path(os.environ["HST_FEATURE_CHAMFER_MATRIX_ARTIFACT_DIR"])
REPETITIONS = int(os.environ["HST_FEATURE_CHAMFER_MATRIX_REPETITIONS"])
RESULTS_PATH = ARTIFACT_DIRECTORY / "results.json"
PACKAGE_NAME = "hst_feature_chamfer_matrix_addon"
FIXTURE_DIRECTORY = REPO_ROOT / "tests" / "fixtures"
CLASSIFICATIONS = {
    "PRODUCT_SUCCESS",
    "EXPECTED_UNSUPPORTED",
    "REGRESSION_FAILURE",
    "SAFETY_PASS",
}
PHASE_1_FAMILIES = {
    "AMBIGUOUS_BOUNDARY_GRAPH",
    "SHARED_RAIL_PORT_RANGE",
    "SIGNED_STRIP_WIDTH_EXCEEDED",
}
PHASE_1_PIPELINE_TIMER_KEYS = {
    "feature_graph",
    "pipe_build",
    "cutter_pack",
    "boolean_apply",
    "boundary_classify",
    "binding",
    "regular_strips",
    "junction",
    "validation",
    "cleanup",
    "total",
}
PHASE_0_CLASSIFICATION_COUNTS = {
    "EXPECTED_UNSUPPORTED": 0,
    "PRODUCT_SUCCESS": 2,
    "REGRESSION_FAILURE": 1,
    "SAFETY_PASS": 11,
}
FIXTURE_HASHES = {
    "feature-chamfer-product-simple.blend": (
        "1cbab4c83c4d9f77bd2b0799257953aaec32aa416994a1d8810425f3c2b94d8c"
    ),
    "feature-chamfer-product-tricky.blend": (
        "c7f57a54837a04f7e52b535bb47af0abeb05fca4193dac714fb3667efb426f02"
    ),
    "feature-chamfer-product-tricky-b.blend": (
        "a4c121b6bbbfff58b94c3b7ed11bd82fe59c88a92569389fd27593ed65be9a35"
    ),
    "feature-chamfer-topology-defect-mixed.blend": (
        "80da3ee4144ba83cab4e9bed980c8829d846369f22a694abfe1aa513c3a3d1b8"
    ),
}
MATRIX_SOURCES = (
    ("simple", "feature-chamfer-product-simple.blend", "Extruded.002"),
    ("simple", "feature-chamfer-product-simple.blend", "Solid 44"),
    ("tricky", "feature-chamfer-product-tricky.blend", "Solid.004"),
    ("tricky", "feature-chamfer-product-tricky.blend", "Solid.016"),
    ("tricky_b", "feature-chamfer-product-tricky-b.blend", "Extruded.003"),
    ("tricky_b", "feature-chamfer-product-tricky-b.blend", "Extruded.002"),
    ("mixed", "feature-chamfer-topology-defect-mixed.blend", "Extruded.002"),
)
MATRIX_RADII = (0.01, 0.03)
KNOWN_SAFETY_FAILURES = {
    ("feature-chamfer-product-simple.blend", "Solid 44", 0.01): (
        "ambiguous_boundary",
        "BoundaryGraph contains non degree-2 rail vertices",
    ),
    ("feature-chamfer-product-simple.blend", "Solid 44", 0.03): (
        "ambiguous_boundary",
        "BoundaryGraph contains non degree-2 rail vertices",
    ),
    ("feature-chamfer-product-tricky.blend", "Solid.004", 0.01): (
        "ambiguous_boundary",
        "BoundaryGraph contains non degree-2 rail vertices",
    ),
    ("feature-chamfer-product-tricky.blend", "Solid.004", 0.03): (
        "ambiguous_boundary",
        "BoundaryGraph contains non degree-2 rail vertices",
    ),
    ("feature-chamfer-product-tricky.blend", "Solid.016", 0.01): (
        "regular_patch_invalid",
        "SIGNED_STRIP_WIDTH_EXCEEDED",
    ),
    ("feature-chamfer-product-tricky.blend", "Solid.016", 0.03): (
        "regular_patch_invalid",
        "SIGNED_STRIP_WIDTH_EXCEEDED",
    ),
    ("feature-chamfer-product-tricky-b.blend", "Extruded.003", 0.01): (
        "regular_patch_invalid",
        "SIGNED_STRIP_WIDTH_EXCEEDED",
    ),
    ("feature-chamfer-product-tricky-b.blend", "Extruded.003", 0.03): (
        "regular_patch_shared_rail_invalid",
        "Shared Rail is not a single endpoint Edge",
    ),
    ("feature-chamfer-product-tricky-b.blend", "Extruded.002", 0.01): (
        "regular_patch_invalid",
        "SIGNED_STRIP_WIDTH_EXCEEDED",
    ),
    ("feature-chamfer-product-tricky-b.blend", "Extruded.002", 0.03): (
        "regular_patch_invalid",
        "SIGNED_STRIP_WIDTH_EXCEEDED",
    ),
    ("feature-chamfer-topology-defect-mixed.blend", "Extruded.002", 0.03): (
        "regular_patch_shared_rail_invalid",
        "Shared Rail is not a single endpoint Edge",
    ),
}


# 从 __init__.py 载入插件模块，使 matrix 使用与正式注册一致的 package。
# 返回值: 已载入但尚未 register 的插件模块。
def load_addon_module():
    init_path = REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        init_path,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


# 返回文件 SHA-256，用来证明 fixture 没有被静默替换。
# path: 待校验的 repository fixture 路径。
def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# 把 Blender/Python 诊断对象递归转换为稳定 JSON 值。
# value: stats、Vector、集合或普通标量。
def json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(json_value(item) for item in value)
    try:
        return [json_value(item) for item in value]
    except TypeError:
        return str(value)


# 从 backend stats 取出 Phase 1 诊断，保持缺失状态可被门禁显式发现。
# backend_capture: Operator runtime 捕获的 backend 调用证据。
def phase_1_diagnostics(backend_capture):
    stats = backend_capture.get("stats", {})
    diagnostics = stats.get("phase_1_diagnostics", {})
    return json_value(diagnostics) if isinstance(diagnostics, dict) else {}


# 返回 repetition 的主失败家族和 stable diagnostic IDs。
# repetition: 单次 Operator 运行的完整诊断。
def phase_1_family_identity(repetition):
    families = repetition.get("phase_1_diagnostics", {}).get("families", [])
    primary_families = [
        item.get("family")
        for item in families
        if isinstance(item, dict) and item.get("family") in PHASE_1_FAMILIES
    ]
    diagnostic_ids = sorted(
        item.get("diagnostic_id")
        for item in families
        if isinstance(item, dict) and item.get("diagnostic_id")
    )
    return primary_families, diagnostic_ids


# 校验 Phase 1 pipeline timer contract，计时值不参与稳定 signature。
# repetition: 单次 Operator 运行的完整诊断。
def phase_1_pipeline_timers_valid(repetition):
    pipeline = repetition.get("phase_1_diagnostics", {}).get("pipeline", {})
    if not PHASE_1_PIPELINE_TIMER_KEYS.issubset(pipeline) or not all(
        isinstance(pipeline[key], (int, float)) and pipeline[key] >= 0.0
        for key in PHASE_1_PIPELINE_TIMER_KEYS
    ):
        return False
    if pipeline["total"] <= 0.0:
        return False
    if repetition.get("classification") == "PRODUCT_SUCCESS":
        return all(
            pipeline[key] > 0.0
            for key in PHASE_1_PIPELINE_TIMER_KEYS
            if key not in {"junction"}
        )
    family_names, _ = phase_1_family_identity(repetition)
    required_positive = {
        "AMBIGUOUS_BOUNDARY_GRAPH": {"boundary_classify", "cleanup"},
        "SHARED_RAIL_PORT_RANGE": {"binding", "regular_strips", "cleanup"},
        "SIGNED_STRIP_WIDTH_EXCEEDED": {"binding", "regular_strips", "cleanup"},
    }
    return len(family_names) == 1 and all(
        pipeline[key] > 0.0 for key in required_positive[family_names[0]]
    )


# 读取 Blender ID Property 中由目标 Operator 保存的 Phase 2 shadow plan 摘要。
# addon_module/id_block: 已注册插件与 Object/Modifier；返回可序列化摘要或缺失状态。
def phase_2_plan_summary(addon_module, id_block):
    if id_block is None:
        return {"exists": False}
    plan = addon_module.utils.feature_chamfer_plan_utils.read_chamfer_plan(id_block)
    if plan is None:
        return {"exists": False}
    return {
        "exists": True,
        "mode": plan.mode,
        "plan_id": plan.plan_id,
        "source_fingerprint": plan.source_fingerprint,
        "input_contract": plan.input_contract,
        "provenance": list(plan.provenance),
        "is_complete": plan.is_complete,
        "feature_strand_count": len(plan.feature_strands),
        "junction_port_count": len(plan.junction_ports),
        "rail_chain_count": len(plan.rail_chains),
        "strip_correspondence_count": len(plan.strip_correspondences),
        "unsupported_region_count": len(plan.unsupported_regions),
        "unsupported_regions": [
            {
                "region_id": region.region_id,
                "reason_code": region.reason_code,
                "owner_strand_ids": list(region.owner_strand_ids),
                "evidence_ids": list(region.evidence_ids),
            }
            for region in plan.unsupported_regions
        ],
    }


# 返回从坐标、拓扑、Sharp 标记与 transform 构造的 source fingerprint。
# source_object: 产品矩阵中的原始 Mesh Object。
def source_fingerprint(source_object):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    payload = {
        "vertices": [
            [round(component, 9) for component in vertex.co]
            for vertex in mesh.vertices
        ],
        "edges": [list(edge.vertices) for edge in mesh.edges],
        "faces": [list(polygon.vertices) for polygon in mesh.polygons],
        "sharp": [
            bool(sharp_attribute and sharp_attribute.data[edge.index].value)
            for edge in mesh.edges
        ],
        "matrix_world": [
            [round(component, 9) for component in row]
            for row in source_object.matrix_world
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# 返回有序数值列表的线性 percentile，不依赖 NumPy。
# values: 数值序列；fraction: 0..1 百分位位置。
def percentile(values, fraction):
    ordered_values = sorted(values)
    if not ordered_values:
        return None
    position = (len(ordered_values) - 1) * fraction
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered_values[lower_index]
    blend = position - lower_index
    return (
        ordered_values[lower_index] * (1.0 - blend)
        + ordered_values[upper_index] * blend
    )


# 记录 source 合同事实、manifold 风险与局部 feature-size 指标。
# source_object: matrix cell 指定的原始 Mesh Object；radius: 当前 Chamfer 半径。
def source_diagnostics(source_object, radius):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    sharp_edge_indices = [
        edge.index
        for edge in mesh.edges
        if sharp_attribute is not None and sharp_attribute.data[edge.index].value
    ]
    sharp_vertices = {
        vertex_index
        for edge_index in sharp_edge_indices
        for vertex_index in mesh.edges[edge_index].vertices
    }
    edge_lengths = [
        (mesh.vertices[edge.vertices[1]].co - mesh.vertices[edge.vertices[0]].co).length
        for edge in mesh.edges
    ]
    local_edge_lengths = [
        edge_lengths[edge.index]
        for edge in mesh.edges
        if any(vertex_index in sharp_vertices for vertex_index in edge.vertices)
    ]
    mesh_analysis = bmesh.new()
    mesh_analysis.from_mesh(mesh)
    non_manifold_edge_count = sum(
        1 for edge in mesh_analysis.edges if len(edge.link_faces) != 2
    )
    degenerate_face_count = sum(
        1 for face in mesh_analysis.faces if face.calc_area() <= 1.0e-12
    )
    zero_length_edge_count = sum(
        1 for edge in mesh_analysis.edges if edge.calc_length() <= 1.0e-12
    )
    mesh_analysis.free()
    minimum_local_edge_length = min(local_edge_lengths, default=None)
    scale_applied = all(abs(component - 1.0) <= 1.0e-6 for component in source_object.scale)
    return {
        "object_name": source_object.name,
        "mesh_name": mesh.name,
        "fingerprint": source_fingerprint(source_object),
        "transform": {
            "location": list(source_object.location),
            "rotation_euler": list(source_object.rotation_euler),
            "scale": list(source_object.scale),
            "scale_applied": scale_applied,
        },
        "mesh": {
            "vertex_count": len(mesh.vertices),
            "edge_count": len(mesh.edges),
            "face_count": len(mesh.polygons),
            "sharp_edge_count": len(sharp_edge_indices),
            "non_manifold_edge_count": non_manifold_edge_count,
            "degenerate_face_count": degenerate_face_count,
            "zero_length_edge_count": zero_length_edge_count,
            "closed_manifold": non_manifold_edge_count == 0,
        },
        "local_feature_size": {
            "definition": "lengths of Mesh Edges incident to a Sharp Edge vertex",
            "minimum": minimum_local_edge_length,
            "p10": percentile(local_edge_lengths, 0.1),
            "median": percentile(local_edge_lengths, 0.5),
            "radius_to_minimum": (
                radius / minimum_local_edge_length
                if minimum_local_edge_length and minimum_local_edge_length > 0.0
                else None
            ),
        },
    }


# 返回 Finalize output 的拓扑、Chamfer attribute 与稳定 fingerprint。
# output_object: 目标 Operator 创建的独立 Mesh Object；为 None 时返回缺失状态。
def output_diagnostics(output_object):
    if output_object is None or output_object.type != "MESH":
        return {"exists": False}
    mesh = output_object.data
    mesh_analysis = bmesh.new()
    mesh_analysis.from_mesh(mesh)
    boundary_edge_count = sum(
        1 for edge in mesh_analysis.edges if len(edge.link_faces) == 1
    )
    non_manifold_edge_count = sum(
        1 for edge in mesh_analysis.edges if len(edge.link_faces) != 2
    )
    zero_area_face_count = sum(
        1 for face in mesh_analysis.faces if face.calc_area() <= 1.0e-12
    )
    mesh_analysis.free()
    chamfer_attribute = mesh.attributes.get("hst_feature_chamfer_face")
    chamfer_values = [
        bool(item.value) for item in chamfer_attribute.data
    ] if chamfer_attribute is not None else []
    fingerprint_payload = {
        "vertices": [
            [round(component, 9) for component in vertex.co]
            for vertex in mesh.vertices
        ],
        "edges": [list(edge.vertices) for edge in mesh.edges],
        "faces": [list(polygon.vertices) for polygon in mesh.polygons],
        "chamfer_faces": chamfer_values,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "exists": True,
        "object_name": output_object.name,
        "fingerprint": fingerprint,
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "boundary_edge_count": boundary_edge_count,
        "non_manifold_edge_count": non_manifold_edge_count,
        "zero_area_face_count": zero_area_face_count,
        "chamfer_attribute_exists": chamfer_attribute is not None,
        "chamfer_face_count": sum(chamfer_values),
    }


# 将 source 设为唯一选择和 active Object，使 INVOKE 路径执行正式上下文校验。
# source_object: 当前 matrix cell 的输入 Object。
def activate_source(source_object):
    for selected_object in tuple(bpy.context.selected_objects):
        selected_object.select_set(False)
    source_object.hide_set(False)
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.context.view_layer.update()


# 从 operator runtime 捕获 backend stats，仍由 hst.feature_chamfer_gn 调用真实 builder。
# addon_module: 已注册插件；capture: 写入 backend 调用证据的 dict。
def install_finalize_capture(addon_module, capture):
    operator_module = addon_module.operators.feature_chamfer_gn_ops
    original_builder = operator_module.build_pipe_chamfer

    def captured_builder(*args, **kwargs):
        capture["called"] = True
        capture["feature_graph_contract"] = kwargs.get("feature_graph_contract")
        capture["debug_stage"] = kwargs.get("debug_stage")
        expected_plan = kwargs.get("expected_chamfer_plan")
        if expected_plan is not None:
            capture["expected_chamfer_plan"] = {
                "mode": expected_plan.mode,
                "plan_id": expected_plan.plan_id,
                "source_fingerprint": expected_plan.source_fingerprint,
                "input_contract": expected_plan.input_contract,
                "provenance": list(expected_plan.provenance),
                "is_complete": expected_plan.is_complete,
                "unsupported_region_count": len(expected_plan.unsupported_regions),
            }
        try:
            stats = original_builder(*args, **kwargs)
        except addon_module.utils.experimental_pipe_chamfer_utils.PipeChamferError as error:
            capture["status"] = "failed"
            capture["error_code"] = error.error_code
            capture["error_message"] = str(error)
            capture["stats"] = json_value(error.stats)
            raise
        capture["status"] = "finished"
        capture["stats"] = json_value(stats)
        return stats

    operator_module.build_pipe_chamfer = captured_builder
    return operator_module, original_builder


# 根据预先写明的 input contract 与目标 Operator 结果生成四类产品语义。
# source_before/result/output/backend/source_unchanged: 当前 cell 的直接证据。
def classify_result(
    source_before,
    preview_result,
    finalize_result,
    output,
    backend_capture,
    source_unchanged,
    pseudo_output_count,
    expected_safety_failure,
):
    contract_violations = []
    if not source_before["mesh"]["closed_manifold"]:
        contract_violations.append("SOURCE_NOT_CLOSED_MANIFOLD")
    if source_before["mesh"]["sharp_edge_count"] == 0:
        contract_violations.append("NO_EXPLICIT_SHARP_EDGE")
    if not source_before["transform"]["scale_applied"]:
        contract_violations.append("OBJECT_SCALE_NOT_APPLIED")

    clean_product_output = (
        output.get("exists")
        and output.get("boundary_edge_count") == 0
        and output.get("non_manifold_edge_count") == 0
        and output.get("zero_area_face_count") == 0
        and output.get("chamfer_attribute_exists")
        and output.get("chamfer_face_count", 0) > 0
    )
    safety_failure = (
        preview_result == ["FINISHED"]
        and finalize_result == ["CANCELLED"]
        and backend_capture.get("error_code")
        and source_unchanged
        and pseudo_output_count == 0
    )
    if contract_violations:
        classification = "EXPECTED_UNSUPPORTED"
        reason = ",".join(contract_violations)
    elif (
        preview_result == ["FINISHED"]
        and finalize_result == ["FINISHED"]
        and clean_product_output
        and source_unchanged
    ):
        classification = "PRODUCT_SUCCESS"
        reason = "OPERATOR_CREATED_CLEAN_SEPARATE_CHAMFER_OUTPUT"
    elif (
        safety_failure
        and expected_safety_failure is not None
        and backend_capture.get("error_code") == expected_safety_failure[0]
        and expected_safety_failure[1] in backend_capture.get("error_message", "")
    ):
        classification = "SAFETY_PASS"
        reason = backend_capture["error_code"]
    else:
        classification = "REGRESSION_FAILURE"
        reason = (
            backend_capture.get("error_code")
            or "OPERATOR_OR_OUTPUT_CONTRACT_FAILED"
        )
    return classification, reason, contract_violations


# 返回用于跨 repetition 比较的语义 fingerprint，排除计时和 Object 显示名。
# repetition: 单次运行的完整诊断。
def repetition_signature(repetition):
    primary_families, diagnostic_ids = phase_1_family_identity(repetition)
    stable_payload = {
        "classification": repetition["classification"],
        "classification_reason": repetition["classification_reason"],
        "contract_violations": repetition["contract_violations"],
        "preview_result": repetition["operator"]["preview_result"],
        "finalize_result": repetition["operator"]["finalize_result"],
        "preview_runtime_proven": repetition["operator"]["preview_runtime_proven"],
        "finalize_runtime_proven": repetition["operator"]["finalize_runtime_proven"],
        "backend_status": repetition["backend"].get("status"),
        "backend_error_code": repetition["backend"].get("error_code"),
        "backend_error_message": repetition["backend"].get("error_message"),
        "phase_1_primary_families": primary_families,
        "phase_1_diagnostic_ids": diagnostic_ids,
        "phase_2_preview_plan_id": repetition.get("phase_2_plan", {})
        .get("preview", {})
        .get("plan_id"),
        "phase_2_finalize_plan_id": repetition.get("phase_2_plan", {})
        .get("finalize", {})
        .get("plan_id"),
        "source_before": repetition["source_before"]["fingerprint"],
        "source_after_preview": repetition["source_after_preview"],
        "source_after_finalize": repetition["source_after_finalize"],
        "output_fingerprint": repetition["output"].get("fingerprint"),
        "final_state": repetition["final_state"],
        "output_topology": {
            key: repetition["output"].get(key)
            for key in (
                "vertex_count",
                "edge_count",
                "face_count",
                "boundary_edge_count",
                "non_manifold_edge_count",
                "zero_area_face_count",
                "chamfer_face_count",
            )
        },
    }
    return hashlib.sha256(
        json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# 保存 Preview 或 Finalize 当前状态为 copy，确保 fixture 路径与主文件状态不变。
# artifact_path: 目标 .blend 路径。
def save_artifact_copy(artifact_path):
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.wm.save_as_mainfile(
        filepath=str(artifact_path),
        check_existing=False,
        compress=True,
        copy=True,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"Failed to save artifact copy: {artifact_path}")


# 执行一个 fixture/object/radius cell，并保存目标 Operator 的完整证据。
# addon_module: 已注册插件；其余参数定义 matrix cell 与 artifact 位置。
def run_repetition(
    addon_module,
    fixture_path,
    object_name,
    radius,
    case_directory,
    repetition_index,
):
    open_result = bpy.ops.wm.open_mainfile(
        filepath=str(fixture_path),
        load_ui=False,
        use_scripts=False,
    )
    if open_result != {"FINISHED"}:
        raise RuntimeError(f"Failed to open fixture: {fixture_path}")
    source_object = bpy.data.objects.get(object_name)
    if source_object is None or source_object.type != "MESH":
        raise RuntimeError(f"Fixture Object missing or not Mesh: {object_name}")

    source_before = source_diagnostics(source_object, radius)
    source_fingerprint_before = source_before["fingerprint"]
    activate_source(source_object)
    preview_started = time.perf_counter()
    preview_result = sorted(
        bpy.ops.hst.feature_chamfer_gn(
            "INVOKE_DEFAULT",
            action="PREVIEW",
            radius=radius,
        )
    )
    preview_seconds = time.perf_counter() - preview_started
    source_fingerprint_after_preview = source_fingerprint(source_object)
    preview_modifier = source_object.modifiers.get("HST Feature Chamfer GN Preview")
    preview_plan = phase_2_plan_summary(addon_module, preview_modifier)
    preview_runtime_proven = (
        source_object.get(addon_module.const.FEATURE_CHAMFER_GN_LAST_ACTION_TAG)
        == "PREVIEW"
        and preview_modifier is not None
        and preview_modifier.get(addon_module.const.FEATURE_CHAMFER_GN_LAST_ACTION_TAG)
        == "PREVIEW"
    )
    if repetition_index == 0:
        save_artifact_copy(case_directory / "preview.blend")

    backend_capture = {"called": False}
    finalize_result = ["SKIPPED"]
    finalize_seconds = 0.0
    if preview_result == ["FINISHED"]:
        activate_source(source_object)
        operator_module, original_builder = install_finalize_capture(
            addon_module,
            backend_capture,
        )
        finalize_started = time.perf_counter()
        try:
            finalize_result = sorted(
                bpy.ops.hst.feature_chamfer_gn(
                    "INVOKE_DEFAULT",
                    action="FINALIZE",
                )
            )
        finally:
            finalize_seconds = time.perf_counter() - finalize_started
            operator_module.build_pipe_chamfer = original_builder

    source_fingerprint_after_finalize = source_fingerprint(source_object)
    source_unchanged = (
        source_fingerprint_before
        == source_fingerprint_after_preview
        == source_fingerprint_after_finalize
    )
    output_object = (
        bpy.context.active_object
        if finalize_result == ["FINISHED"] and bpy.context.active_object is not source_object
        else None
    )
    output = output_diagnostics(output_object)
    finalize_plan = phase_2_plan_summary(
        addon_module,
        output_object if output_object is not None else preview_modifier,
    )
    final_state = (
        "PRODUCT_OUTPUT"
        if output_object is not None
        else (
            "PREVIEW_RETAINED"
            if addon_module.utils.feature_chamfer_gn_utils.preview_state(source_object)
            == addon_module.utils.feature_chamfer_gn_utils.PREVIEW_VALID
            else "NO_OUTPUT"
        )
    )
    pseudo_outputs = [
        obj.name
        for obj in bpy.data.objects
        if obj is not source_object
        and obj.get(addon_module.const.FEATURE_CHAMFER_SOURCE_OBJECT_TAG)
        == source_object.name
    ]
    if output_object is not None and output_object.name in pseudo_outputs:
        pseudo_outputs.remove(output_object.name)
    finalize_runtime_proven = (
        source_object.get(addon_module.const.FEATURE_CHAMFER_GN_LAST_ACTION_TAG)
        == "FINALIZE"
        and backend_capture.get("called")
        and backend_capture.get("feature_graph_contract") == "GN_PREVIEW_V1"
    )
    classification, classification_reason, contract_violations = classify_result(
        source_before,
        preview_result,
        finalize_result,
        output,
        backend_capture,
        source_unchanged,
        len(pseudo_outputs),
        KNOWN_SAFETY_FAILURES.get((fixture_path.name, object_name, radius)),
    )
    if repetition_index == 0:
        save_artifact_copy(case_directory / "final.blend")
    return {
        "repetition": repetition_index + 1,
        "classification": classification,
        "classification_reason": classification_reason,
        "contract_violations": contract_violations,
        "source_before": source_before,
        "source_after_preview": source_fingerprint_after_preview,
        "source_after_finalize": source_fingerprint_after_finalize,
        "source_unchanged": source_unchanged,
        "operator": {
            "ui_entry": "Feature Chamfer GN",
            "bl_idname": "hst.feature_chamfer_gn",
            "invocation": "INVOKE_DEFAULT",
            "preview_result": preview_result,
            "finalize_result": finalize_result,
            "preview_runtime_proven": preview_runtime_proven,
            "finalize_runtime_proven": finalize_runtime_proven,
        },
        "backend": json_value(backend_capture),
        "phase_1_diagnostics": phase_1_diagnostics(backend_capture),
        "phase_2_plan": {
            "preview": preview_plan,
            "finalize": finalize_plan,
            "shared_semantics": (
                preview_plan.get("exists", False)
                and bool(finalize_plan)
                and preview_plan.get("plan_id") == finalize_plan.get("plan_id")
                and preview_plan.get("provenance") == finalize_plan.get("provenance")
            ),
        },
        "phase_2_boundary_binding": json_value(
            backend_capture.get("stats", {}).get(
                "chamfer_plan_boundary_binding",
                {},
            )
        ),
        "output": output,
        "final_state": final_state,
        "unexpected_pseudo_outputs": pseudo_outputs,
        "timings_seconds": {
            "preview": preview_seconds,
            "finalize": finalize_seconds,
        },
    }


# 生成稳定的 case ID，供目录、汇总和后续 Phase 诊断引用。
# fixture_label/object_name/radius: matrix cell 三个维度。
def case_id(fixture_label, object_name, radius):
    safe_object_name = object_name.lower().replace(" ", "_").replace(".", "_")
    radius_token = f"{radius:.3f}".replace(".", "p")
    return f"{fixture_label}__{safe_object_name}__r{radius_token}"


# 写入可在 Blender crash 前保留的阶段性汇总。
# summary: 当前 matrix 执行状态。
def write_summary(summary):
    ARTIFACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 执行 14-cell matrix 两次，验证稳定性、source 不变与正式 runtime path。
# 无参数；配置通过环境变量由 host runner 注入。
def main():
    if REPETITIONS < 3:
        raise RuntimeError("Phase 2 requires at least three repetitions")
    actual_fixture_hashes = {
        fixture_name: file_sha256(FIXTURE_DIRECTORY / fixture_name)
        for fixture_name in FIXTURE_HASHES
    }
    fixture_hashes_valid = actual_fixture_hashes == FIXTURE_HASHES
    if not fixture_hashes_valid:
        raise RuntimeError(
            "Feature Chamfer fixture SHA-256 mismatch: "
            f"expected={FIXTURE_HASHES}, actual={actual_fixture_hashes}"
        )

    addon_module = load_addon_module()
    addon_module.register()
    matrix_cases = [
        {
            "case_id": case_id(fixture_label, object_name, radius),
            "fixture_label": fixture_label,
            "fixture": fixture_name,
            "object_name": object_name,
            "radius": radius,
            "expected_safety_failure": list(
                KNOWN_SAFETY_FAILURES[(fixture_name, object_name, radius)]
            ) if (fixture_name, object_name, radius) in KNOWN_SAFETY_FAILURES else None,
            "repetitions": [],
        }
        for fixture_label, fixture_name, object_name in MATRIX_SOURCES
        for radius in MATRIX_RADII
    ]
    summary = {
        "status": "running",
        "phase": 2,
        "blender_version": bpy.app.version_string,
        "blender_version_tuple": list(bpy.app.version),
        "repository_root": str(REPO_ROOT),
        "runtime_contract": (
            "UI Feature Chamfer GN -> hst.feature_chamfer_gn -> INVOKE -> "
            "PREVIEW/FINALIZE -> GN_PREVIEW_V1"
        ),
        "fixture_hashes_expected": FIXTURE_HASHES,
        "fixture_hashes_actual": actual_fixture_hashes,
        "fixture_hashes_valid": fixture_hashes_valid,
        "requested_repetitions": REPETITIONS,
        "case_count": len(matrix_cases),
        "cases": matrix_cases,
    }
    write_summary(summary)

    for case in matrix_cases:
        case_directory = ARTIFACT_DIRECTORY / case["case_id"]
        case_directory.mkdir(parents=True, exist_ok=True)
        fixture_path = FIXTURE_DIRECTORY / case["fixture"]
        print(
            "[HST_FEATURE_CHAMFER_MATRIX] "
            f"case={case['case_id']} repetitions={REPETITIONS}"
        )
        for repetition_index in range(REPETITIONS):
            try:
                repetition = run_repetition(
                    addon_module,
                    fixture_path,
                    case["object_name"],
                    case["radius"],
                    case_directory,
                    repetition_index,
                )
            except Exception as error:
                repetition = {
                    "repetition": repetition_index + 1,
                    "classification": "REGRESSION_FAILURE",
                    "classification_reason": "UNEXPECTED_EXCEPTION",
                    "error": "".join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    ),
                }
            repetition["signature"] = repetition_signature(repetition) if "operator" in repetition else None
            case["repetitions"].append(repetition)
            (case_directory / "diagnostics.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            write_summary(summary)

        signatures = [item.get("signature") for item in case["repetitions"]]
        case["stable"] = None not in signatures and len(set(signatures)) == 1
        case["classification"] = (
            case["repetitions"][0]["classification"]
            if case["stable"]
            else "REGRESSION_FAILURE"
        )
        case["source_unchanged"] = all(
            item.get("source_unchanged", False) for item in case["repetitions"]
        )
        case["runtime_path_proven"] = all(
            item.get("operator", {}).get("preview_runtime_proven", False)
            and item.get("operator", {}).get("finalize_runtime_proven", False)
            for item in case["repetitions"]
        )
        family_identities = [
            phase_1_family_identity(item) for item in case["repetitions"]
        ]
        case["phase_1_primary_family"] = (
            family_identities[0][0][0]
            if family_identities
            and len(family_identities[0][0]) == 1
            and all(
                identity[0] == family_identities[0][0]
                for identity in family_identities
            )
            else None
        )
        case["phase_1_diagnostic_ids_stable"] = (
            bool(family_identities)
            and all(identity[1] for identity in family_identities)
            and all(
                identity[1] == family_identities[0][1]
                for identity in family_identities
            )
        )
        case["phase_1_pipeline_timers_valid"] = all(
            phase_1_pipeline_timers_valid(item) for item in case["repetitions"]
        )
        phase_2_plan_ids = [
            item.get("phase_2_plan", {}).get("preview", {}).get("plan_id")
            for item in case["repetitions"]
        ]
        case["phase_2_plan_ids_stable"] = (
            all(phase_2_plan_ids) and len(set(phase_2_plan_ids)) == 1
        )
        case["phase_2_shared_plan_semantics"] = all(
            item.get("phase_2_plan", {}).get("shared_semantics", False)
            for item in case["repetitions"]
        )
        (case_directory / "diagnostics.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_summary(summary)

    classification_counts = {
        classification: sum(
            case["classification"] == classification for case in matrix_cases
        )
        for classification in sorted(CLASSIFICATIONS)
    }
    non_product_cases = [
        case for case in matrix_cases if case["classification"] != "PRODUCT_SUCCESS"
    ]
    family_objects = {
        family: {
            (case["fixture"], case["object_name"])
            for case in non_product_cases
            if case["phase_1_primary_family"] == family
        }
        for family in PHASE_1_FAMILIES
    }
    phase_0_go_conditions = {
        "fourteen_cells_recorded": len(matrix_cases) == 14,
        "all_cells_repeated": all(
            len(case["repetitions"]) == REPETITIONS for case in matrix_cases
        ),
        "all_cells_stable": all(case["stable"] for case in matrix_cases),
        "all_sources_unchanged": all(case["source_unchanged"] for case in matrix_cases),
        "all_runtime_paths_proven": all(case["runtime_path_proven"] for case in matrix_cases),
        "all_cells_classified": all(
            case["classification"] in CLASSIFICATIONS for case in matrix_cases
        ),
        "all_expected_safety_failures_match": all(
            case["expected_safety_failure"] is None
            or all(
                repetition.get("classification") == "SAFETY_PASS"
                and repetition.get("backend", {}).get("error_code")
                == case["expected_safety_failure"][0]
                and case["expected_safety_failure"][1]
                in repetition.get("backend", {}).get("error_message", "")
                for repetition in case["repetitions"]
            )
            for case in matrix_cases
        ),
        "fixture_hashes_valid": fixture_hashes_valid,
    }
    phase_1_go_conditions = {
        "phase_0_classification_semantics_unchanged": (
            classification_counts == PHASE_0_CLASSIFICATION_COUNTS
        ),
        "phase_1_each_non_product_has_one_primary_family": all(
            all(
                len(phase_1_family_identity(repetition)[0]) == 1
                for repetition in case["repetitions"]
            )
            and case["phase_1_primary_family"] in PHASE_1_FAMILIES
            for case in non_product_cases
        ),
        "phase_1_diagnostic_ids_stable": all(
            case["phase_1_diagnostic_ids_stable"] for case in non_product_cases
        ),
        "phase_1_each_family_has_two_objects": all(
            len(objects) >= 2 for objects in family_objects.values()
        ),
        "phase_1_pipeline_timers_valid": all(
            case["phase_1_pipeline_timers_valid"] for case in matrix_cases
        ),
    }
    phase_2_go_conditions = {
        "phase_2_three_repetitions": REPETITIONS >= 3,
        "phase_2_classification_semantics_unchanged": (
            classification_counts == PHASE_0_CLASSIFICATION_COUNTS
        ),
        "phase_2_plan_ids_stable": all(
            case["phase_2_plan_ids_stable"] for case in matrix_cases
        ),
        "phase_2_preview_finalize_share_plan_semantics": all(
            case["phase_2_shared_plan_semantics"] for case in matrix_cases
        ),
        "phase_2_shadow_mode_only": all(
            repetition.get("phase_2_plan", {}).get("preview", {}).get("mode")
            == "SHADOW"
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
        "phase_2_failed_fixtures_have_unsupported_plan": all(
            repetition.get("classification") == "PRODUCT_SUCCESS"
            or (
                repetition.get("phase_2_plan", {})
                .get("finalize", {})
                .get("is_complete")
                is False
                and repetition.get("phase_2_plan", {})
                .get("finalize", {})
                .get("unsupported_region_count", 0)
                > 0
            )
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
        "phase_2_success_boundary_binding_complete": all(
            repetition.get("classification") != "PRODUCT_SUCCESS"
            or (
                repetition.get("phase_2_boundary_binding", {}).get("status")
                == "PASS"
                and repetition.get("phase_2_boundary_binding", {}).get(
                    "bound_rail_count",
                    0,
                )
                > 0
                and not repetition.get("phase_2_boundary_binding", {}).get(
                    "missing_from_plan_binding"
                )
                and not repetition.get("phase_2_boundary_binding", {}).get(
                    "extra_in_plan_binding"
                )
                and not repetition.get("phase_2_boundary_binding", {}).get(
                    "missing_expected_rail_ids"
                )
                and not repetition.get("phase_2_boundary_binding", {}).get(
                    "missing_correspondence_rail_ids"
                )
            )
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
    }
    go_conditions = {
        **phase_0_go_conditions,
        **phase_1_go_conditions,
        **phase_2_go_conditions,
    }
    summary.update(
        status="finished",
        phase=2,
        classification_counts=classification_counts,
        phase_1_family_objects={
            family: sorted(f"{fixture}:{object_name}" for fixture, object_name in objects)
            for family, objects in sorted(family_objects.items())
        },
        go_conditions=go_conditions,
        phase_0_go=all(phase_0_go_conditions.values()),
        phase_1_go=(
            all(phase_0_go_conditions.values())
            and all(phase_1_go_conditions.values())
        ),
        phase_2_go=(
            all(phase_0_go_conditions.values())
            and all(phase_1_go_conditions.values())
            and all(phase_2_go_conditions.values())
        ),
    )
    write_summary(summary)
    print("[HST_FEATURE_CHAMFER_MATRIX_SUMMARY] " + json.dumps({
        "phase_0_go": summary["phase_0_go"],
        "phase_1_go": summary["phase_1_go"],
        "phase_2_go": summary["phase_2_go"],
        "classification_counts": classification_counts,
        "go_conditions": go_conditions,
    }, ensure_ascii=False))

    try:
        addon_module.unregister()
    except Exception:
        traceback.print_exc()
    if not summary["phase_2_go"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
