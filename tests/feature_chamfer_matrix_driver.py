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
CASE_FILTER = set(
    json.loads(os.environ.get("HST_FEATURE_CHAMFER_MATRIX_CASES", "[]"))
)
RESULTS_PATH = ARTIFACT_DIRECTORY / "results.json"
PACKAGE_NAME = "hst_feature_chamfer_matrix_addon"
FIXTURE_DIRECTORY = REPO_ROOT / "tests" / "fixtures"
CLASSIFICATIONS = {
    "PRODUCT_SUCCESS",
    "RADIUS_LIMIT_DIAGNOSTIC",
    "PRODUCT_SUCCESS_WITH_RADIUS_RETRY",
    "EXPECTED_UNSUPPORTED",
    "REGRESSION_FAILURE",
    "SAFETY_PASS",
}
FIRST_STAGE_LABELS = {"simple", "tricky_b", "mixed"}
DEFERRED_LABELS = {"tricky"}
CYCLIC_FIX_TARGET_SCOPE = {("tricky_b", "Extruded.002", 0.01)}
MIXED_CYCLIC_FIX_TARGET_SCOPE = {
    ("mixed", "Extruded.002", 0.01),
    ("mixed", "Extruded.002", 0.03),
}
CYCLIC_FIX_REGRESSION_SCOPE = {
    ("simple", "Extruded.002", 0.01),
    ("simple", "Extruded.002", 0.03),
    ("simple", "Solid 44", 0.01),
    ("simple", "Solid 44", 0.03),
    ("tricky_b", "Extruded.003", 0.01),
    ("tricky_b", "Extruded.003", 0.03),
    ("mixed", "Extruded.002", 0.01),
    ("mixed", "Extruded.002", 0.03),
}
# 锁定未执行补面 dissolve 时的 Preview→Finalize 输出拓扑。
# 默认 dissolve 路径另由显式执行记录、健康性与同配置重复语义一致性守住，避免把预期简化误报为回归。
# key: matrix cell；value: 未清理 Mesh 与 Chamfer Face 数量。
UNDISSOLVED_TOPOLOGY_BASELINES = {
    ("simple", "Extruded.002", 0.01): {
        "fingerprint": "60666add88c6d5f428fbad0b8ba0a759a9250c139426cce032acf964f1f4a402",
        "vertex_count": 533,
        "edge_count": 1102,
        "face_count": 571,
        "chamfer_face_count": 509,
    },
    ("simple", "Extruded.002", 0.03): {
        "fingerprint": "6a7a0df17e7b81c7c81a79e9f91f5ac3cbcfc1ba10d43baa26c245064ffec130",
        "vertex_count": 531,
        "edge_count": 1067,
        "face_count": 538,
        "chamfer_face_count": 476,
    },
    ("simple", "Solid 44", 0.01): {
        "fingerprint": "633dd72a20044b71760a8bb757992e988155815cdcf65b61c48b7ae7ffb8fd85",
        "vertex_count": 271,
        "edge_count": 562,
        "face_count": 293,
        "chamfer_face_count": 239,
    },
    ("simple", "Solid 44", 0.03): {
        "fingerprint": "15e0e7323b50cad154b7bcc25cd87ca61ba81eb804d8016a099b49192733629f",
        "vertex_count": 267,
        "edge_count": 562,
        "face_count": 297,
        "chamfer_face_count": 243,
    },
    ("tricky_b", "Extruded.003", 0.01): {
        "fingerprint": "a739066c549873af66baf2b650960cb2f8253750f217c0fa9178ef0c337b7aac",
        "vertex_count": 428,
        "edge_count": 896,
        "face_count": 470,
        "chamfer_face_count": 426,
    },
    ("tricky_b", "Extruded.003", 0.03): {
        "fingerprint": "50465630bb8bffe89108b4ac29d83fb65f71b3bbeebf8c4fbb9e4157423941c5",
        "vertex_count": 400,
        "edge_count": 837,
        "face_count": 439,
        "chamfer_face_count": 399,
    },
    ("tricky_b", "Extruded.002", 0.01): {
        "fingerprint": "d52ca6645f51cbe10047cd128295d5477f278a508e657cdbfa429fd3218709f8",
        "vertex_count": 1162,
        "edge_count": 2386,
        "face_count": 1226,
        "chamfer_face_count": 1043,
    },
    ("tricky_b", "Extruded.002", 0.03): {
        "fingerprint": "54c0fcc616c5f167913eab9ad5bd12d380167daa6596a238bdd546437d696a1b",
        "vertex_count": 1128,
        "edge_count": 2316,
        "face_count": 1190,
        "chamfer_face_count": 1009,
    },
    ("mixed", "Extruded.002", 0.01): {
        "fingerprint": "f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107",
        "vertex_count": 3922,
        "edge_count": 8054,
        "face_count": 4134,
        "chamfer_face_count": 3454,
    },
    ("mixed", "Extruded.002", 0.03): {
        "fingerprint": "c0ae987df1bdcb603113533944397213a44fd5368d68a5f72cc1a5c94af5d525",
        "vertex_count": 3885,
        "edge_count": 8058,
        "face_count": 4175,
        "chamfer_face_count": 3502,
    },
}
# Blender 5.2 的 Manifold Boolean 会稳定产生不同的等价闭合拓扑，冻结该版本的正式结果。
if bpy.app.version >= (5, 2, 0):
    UNDISSOLVED_TOPOLOGY_BASELINES.update({
        ("simple", "Solid 44", 0.01): {
            "fingerprint": "a46cb0484784f4ca45fe3d2957c869ad4c8d46dbe5c797c16450bd520ef8dd82",
            "vertex_count": 270,
            "edge_count": 559,
            "face_count": 291,
            "chamfer_face_count": 237,
        },
        ("simple", "Solid 44", 0.03): {
            "fingerprint": "5e8eba40d13c0a9ebc60afb3d4760a3f08d526b4ad078c6526ac6d5ca18bb3bf",
            "vertex_count": 265,
            "edge_count": 550,
            "face_count": 287,
            "chamfer_face_count": 233,
        },
        ("tricky_b", "Extruded.003", 0.01): {
            "fingerprint": "445f4e0fc25f21f63d7d6ccff95c737e1341ca809fe031026eb9d3718194dde0",
            "vertex_count": 425,
            "edge_count": 890,
            "face_count": 467,
            "chamfer_face_count": 423,
        },
        ("tricky_b", "Extruded.003", 0.03): {
            "fingerprint": "5df8f942606f040065d50152bb74ef57cad55438f43211d1556098096147748a",
            "vertex_count": 397,
            "edge_count": 830,
            "face_count": 435,
            "chamfer_face_count": 395,
        },
        ("tricky_b", "Extruded.002", 0.01): {
            "fingerprint": "d96b8b6fef236e9bb54aa23ba4c1d97b8359b7aba2849456b161268cdd72de0b",
            "vertex_count": 1155,
            "edge_count": 2364,
            "face_count": 1211,
            "chamfer_face_count": 1028,
        },
        ("tricky_b", "Extruded.002", 0.03): {
            "fingerprint": "01ccda3a1209c9c6ac225eac798d47c4163e4a9739407b635bc659ad5225691f",
            "vertex_count": 1133,
            "edge_count": 2314,
            "face_count": 1183,
            "chamfer_face_count": 1002,
        },
        ("mixed", "Extruded.002", 0.01): {
            "fingerprint": "058161226104472961189debc132c72d3fdf220fb9f424e2b5decd82f692da2c",
            "vertex_count": 3917,
            "edge_count": 8044,
            "face_count": 4129,
            "chamfer_face_count": 3449,
        },
        ("mixed", "Extruded.002", 0.03): {
            "fingerprint": "085eb96cb450610c1edd599d76028429a17939930b64571bab8852fe86b465e4",
            "vertex_count": 3889,
            "edge_count": 8055,
            "face_count": 4168,
            "chamfer_face_count": 3495,
        },
    })
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
MATRIX_RADII = tuple(
    float(radius)
    for radius in json.loads(
        os.environ.get("HST_FEATURE_CHAMFER_MATRIX_RADII", "[0.01, 0.03]")
    )
)
# 产品矩阵已知 U 形拓扑身份；只用于断言通用几何规则的结果，生产实现不读取这些值。
TURN_SPLIT_REGRESSION_CONTRACTS = {
    ("mixed", "Extruded.002"): {
        "segment_id": 25,
        "pipe_id": 4,
        "owner_surface_pair": [5, 15],
        "job_count": 7,
        "turn_count": 6,
    },
    ("tricky_b", "Extruded.002"): {
        "segment_id": 18,
        "pipe_id": 10,
        "owner_surface_pair": [8, 9],
        "job_count": 3,
        "turn_count": 2,
    },
}
# 产品矩阵已知 cyclic 目标身份；只断言正式通用规则的结果，生产实现不读取这些值。
CYCLIC_SPLIT_REGRESSION_CONTRACTS = {
    ("simple", "Extruded.002", 0.01): (
        {
            "segment_id": 0,
            "pipe_id": 2,
            "owner_surface_pair": [2, 4],
            "source_side_edge_counts": [27, 67],
            "maximum_side_length_ratio": 1.04,
        },
        {
            "segment_id": 1,
            "pipe_id": 3,
            "owner_surface_pair": [2, 3],
            "source_side_edge_counts": [27, 67],
            "maximum_side_length_ratio": 1.04,
        },
    ),
    ("simple", "Extruded.002", 0.03): (
        {
            "segment_id": 0,
            "pipe_id": 2,
            "owner_surface_pair": [2, 4],
            "source_side_edge_counts": [27, 65],
            "maximum_side_length_ratio": 1.04,
        },
        {
            "segment_id": 1,
            "pipe_id": 3,
            "owner_surface_pair": [2, 3],
            "source_side_edge_counts": [27, 65],
            "maximum_side_length_ratio": 1.04,
        },
    ),
    ("tricky_b", "Extruded.002", 0.01): (
        {
            "segment_id": 16,
            "pipe_id": 8,
            "owner_surface_pair": [5, 6],
            "source_side_edge_counts": [27, 86],
        },
        {
            "segment_id": 19,
            "pipe_id": 2,
            "owner_surface_pair": [2, 3],
            "source_side_edge_counts": [31, 122],
        },
    ),
    ("mixed", "Extruded.002", 0.01): (
        {
            "segment_id": 30,
            "pipe_id": 15,
            "owner_surface_pair": [13, 14],
            "source_side_edge_counts": [42, 97],
            "maximum_side_length_ratio": 1.26,
            "maximum_contract_station_distance": 0.025,
        },
    ),
    ("mixed", "Extruded.002", 0.03): (
        {
            "segment_id": 30,
            "pipe_id": 15,
            "owner_surface_pair": [13, 14],
            "source_side_edge_counts": [42, 97],
            "maximum_side_length_ratio": 1.26,
            "maximum_contract_station_distance": 0.025,
        },
    ),
}
if bpy.app.version >= (5, 2, 0):
    CYCLIC_SPLIT_REGRESSION_CONTRACTS[
        ("tricky_b", "Extruded.002", 0.01)
    ] = (
        {
            "segment_id": 16,
            "pipe_id": 8,
            "owner_surface_pair": [5, 6],
            "source_side_edge_counts": [27, 86],
        },
        {
            "segment_id": 19,
            "pipe_id": 2,
            "owner_surface_pair": [2, 3],
            "source_side_edge_counts": [31, 121],
        },
    )
RETRY_RADII = tuple(
    float(radius)
    for radius in json.loads(
        os.environ.get("HST_FEATURE_CHAMFER_RETRY_RADII", "[0.005, 0.015]")
    )
)
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


# 返回 source Object 自身属性、Collection 归属与 Modifier runtime 的稳定快照。
# source_object: 正式输入 Mesh Object；用于证明一步式成功路径没有改写输入 Object 状态。
def source_object_state(source_object):
    modifier_states = []
    for modifier in source_object.modifiers:
        modifier_states.append(
            {
                "name": modifier.name,
                "type": modifier.type,
                "id_properties": json_value(dict(modifier.items())),
                "show_viewport": modifier.show_viewport,
                "show_render": modifier.show_render,
                "show_in_editmode": modifier.show_in_editmode,
                "show_on_cage": modifier.show_on_cage,
                "object": getattr(getattr(modifier, "object", None), "name", None),
                "node_group": getattr(getattr(modifier, "node_group", None), "name", None),
            }
        )
    return {
        "id_properties": json_value(dict(source_object.items())),
        "mesh_id_properties": json_value(dict(source_object.data.items())),
        "modifiers": modifier_states,
        "collections": sorted(collection.name for collection in source_object.users_collection),
        "hide_viewport": source_object.hide_viewport,
        "hide_render": source_object.hide_render,
        "hide_set": source_object.hide_get(),
        "display_type": source_object.display_type,
        "show_in_front": source_object.show_in_front,
    }


# 返回排除产品要求可见性变化后的 source 数据与 runtime 状态。
# state: source_object_state 的结果；返回用于几何与配置不变性比较的字典。
def source_content_state(state):
    return {
        key: value
        for key, value in state.items()
        if key not in {"hide_viewport", "hide_render", "hide_set"}
    }


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


# 返回一步式 output 的拓扑、Chamfer attribute 与稳定 fingerprint。
# output_object/source_object: 目标 Operator 创建的独立 Mesh Object 与对应原输入；output 为 None 时返回缺失状态。
def output_diagnostics(output_object, source_object):
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
    normal_transfer_modifiers = [
        modifier
        for modifier in output_object.modifiers
        if modifier.type == "DATA_TRANSFER"
        and modifier.data_types_loops == {"CUSTOM_NORMAL"}
    ]
    vertex_coordinates = {
        vertex.index: tuple(round(component, 9) for component in vertex.co)
        for vertex in mesh.vertices
    }
    fingerprint_payload = {
        "vertices": sorted(
            list(vertex_coordinates[vertex.index])
            for vertex in mesh.vertices
        ),
        "edges": sorted(
            sorted(vertex_coordinates[index] for index in edge.vertices)
            for edge in mesh.edges
        ),
        "faces": sorted(
            sorted(vertex_coordinates[index] for index in polygon.vertices)
            for polygon in mesh.polygons
        ),
        "chamfer_face_count": sum(chamfer_values),
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
        "custom_normal_transfer": (
            len(normal_transfer_modifiers) == 1
            and normal_transfer_modifiers[0].object is source_object
            and normal_transfer_modifiers[0].loop_mapping == "POLYINTERP_LNORPROJ"
            and normal_transfer_modifiers[0].show_viewport
            and normal_transfer_modifiers[0].show_render
        ),
    }


# 读取正式 Operator 留下的红色失败边界，验证它可见且准确关联当前 source。
# addon_module/source_object: 已注册插件与当前 source；返回诊断 Object 摘要。
def failure_diagnostic(addon_module, source_object):
    diagnostic_objects = (
        addon_module.utils.feature_chamfer_diagnostic_utils
        .owned_feature_chamfer_diagnostics(source_object)
    )
    objects = []
    for diagnostic_object in diagnostic_objects:
        curve_data = diagnostic_object.data
        spline_point_count = sum(
            len(spline.points)
            for spline in curve_data.splines
        )
        cyclic = bool(curve_data.splines) and all(
            spline.use_cyclic_u
            for spline in curve_data.splines
        )
        material = curve_data.materials[0] if curve_data.materials else None
        color = list(material.diffuse_color) if material is not None else None
        objects.append(
            {
                "object_name": diagnostic_object.name,
                "error_code": diagnostic_object.get(
                    addon_module.const.FEATURE_CHAMFER_DIAGNOSTIC_ERROR_TAG
                ),
                "radius": diagnostic_object.get(
                    addon_module.const.FEATURE_CHAMFER_DIAGNOSTIC_RADIUS_TAG
                ),
                "point_count": spline_point_count,
                "cyclic": cyclic,
                "show_in_front": diagnostic_object.show_in_front,
                "visible": not diagnostic_object.hide_get(),
                "color": color,
            }
        )
    radius_limit_visible = (
        len(objects) == 1
        and objects[0]["error_code"]
        in addon_module.utils.feature_chamfer_diagnostic_utils.RADIUS_LIMIT_ERROR_CODES
        and objects[0]["point_count"] >= 2
        and objects[0]["show_in_front"]
        and objects[0]["visible"]
        and objects[0]["color"] is not None
        and objects[0]["color"][0] >= 0.9
        and objects[0]["color"][1] <= 0.15
        and objects[0]["color"][2] <= 0.15
    )
    return {
        "exists": bool(objects),
        "object_count": len(objects),
        "radius_limit_visible": radius_limit_visible,
        "objects": objects,
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


# 从一步式 operator runtime 捕获 backend stats，仍由正式入口调用真实 builder。
# addon_module: 已注册插件；capture: 写入 backend 调用证据的 dict。
def install_backend_capture(addon_module, capture):
    operator_module = addon_module.operators.feature_chamfer_gn_ops
    original_builder = operator_module.build_direct_edge_loop_chamfer

    def captured_builder(*args, **kwargs):
        capture["called"] = True
        capture["feature_graph_contract"] = "GN_PREVIEW_V1"
        capture["debug_stage"] = "DIRECT_EDGE_LOOP_BRIDGE"
        expected_plan = (
            args[1]
            if len(args) > 1
            else kwargs.get("expected_chamfer_plan")
        )
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
        except addon_module.utils.feature_chamfer_direct_bridge_utils.FeatureChamferDirectBridgeError as error:
            capture["status"] = "failed"
            capture["error_code"] = error.error_code
            capture["error_message"] = str(error)
            capture["stats"] = json_value(error.stats)
            raise
        capture["status"] = "finished"
        capture["stats"] = json_value(stats)
        return stats

    operator_module.build_direct_edge_loop_chamfer = captured_builder
    return operator_module, original_builder


# 根据第一阶段产品合同与目标 Operator 结果生成四类产品语义。
# source_before/result/output/backend/source_unchanged: 当前 cell 的直接证据；allow_safe_failure 仅供延期 tricky 使用。
def classify_result(
    source_before,
    operation_result,
    output,
    preview_residue,
    backend_capture,
    source_unchanged,
    pseudo_output_count,
    final_state,
    diagnostic,
    allow_safe_failure,
    required_turn_split_contract,
    required_cyclic_split_contracts,
    topology_baseline,
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
        and output.get("custom_normal_transfer")
        and not preview_residue.get("owned_curve_tag")
        and not preview_residue.get("preview_modifier")
        and not preview_residue.get("owned_curve_objects")
    )
    backend_stats = backend_capture.get("stats", {})
    dissolve_chamfer_requested = bool(
        backend_stats.get("dissolve_chamfer_requested")
    )
    topology_baseline_matches = (
        topology_baseline is None
        or (
            dissolve_chamfer_requested
            and backend_stats.get("dissolved_chamfer_face_count", 0) > 0
        )
        or (
            not dissolve_chamfer_requested
            and all(
                output.get(key) == value
                for key, value in topology_baseline.items()
            )
        )
    )
    bridge_shape_records = backend_stats.get("bridge_records", ())
    bridge_shape_contract = (
        backend_stats.get("bridge_shape_contract")
        == "SEGMENT_OWNER_INTERVAL_OVERLAP_V1"
        and bool(bridge_shape_records)
        and all(
            record.get("station_interval_overlap_valid")
            and record.get("foreign_existing_edge_count") == 0
            and record.get("owner_surface_pair")
            in record.get("contract_owner_surface_pairs", ())
            for record in bridge_shape_records
        )
    )
    turn_split_contract = True
    if required_turn_split_contract is not None:
        target_records = [
            record
            for record in bridge_shape_records
            if record.get("segment_id")
            == required_turn_split_contract["segment_id"]
            and record.get("pipe_id") == required_turn_split_contract["pipe_id"]
            and record.get("owner_surface_pair")
            == required_turn_split_contract["owner_surface_pair"]
        ]
        expected_job_count = required_turn_split_contract["job_count"]
        expected_turn_count = required_turn_split_contract["turn_count"]
        turn_split_contract = (
            len(target_records) == expected_job_count
            and sorted(
                record.get("turn_split_job_index")
                for record in target_records
            )
            == list(range(expected_job_count))
            and all(
                record.get("common_turn_split_applied")
                and record.get("turn_split_job_count") == expected_job_count
                and record.get("native_operator") == "Blender Bridge Edge Loops"
                and len(record.get("common_turns", ())) == expected_turn_count
                for record in target_records
            )
        )
    cyclic_split_contract = True
    for cyclic_contract in required_cyclic_split_contracts:
        target_records = [
            record
            for record in bridge_shape_records
            if record.get("segment_id") == cyclic_contract["segment_id"]
            and record.get("pipe_id") == cyclic_contract["pipe_id"]
            and record.get("owner_surface_pair")
            == cyclic_contract["owner_surface_pair"]
        ]
        maximum_side_length_ratio = cyclic_contract.get(
            "maximum_side_length_ratio"
        )
        station_interval_tolerance = cyclic_contract.get(
            "station_interval_tolerance"
        )
        maximum_contract_station_distance = cyclic_contract.get(
            "maximum_contract_station_distance"
        )
        cyclic_split_contract = cyclic_split_contract and (
            len(target_records) == 4
            and sorted(
                record.get("cyclic_split_job_index")
                for record in target_records
            ) == [0, 1, 2, 3]
            and all(
                record.get("cyclic_split_applied")
                and record.get("cyclic_split_job_count") == 4
                and record.get("native_operator") == "Blender Bridge Edge Loops"
                for record in target_records
            )
            and sorted(
                target_records[0].get("cyclic_source_side_edge_counts", ())
            )
            == cyclic_contract["source_side_edge_counts"]
            and all(
                (
                    consumed_edges := [
                        edge_token
                        for record in target_records
                        for edge_token in record.get(
                            "cyclic_job_side_edge_identity_tokens", ((), ())
                        )[side_index]
                    ]
                )
                and len(consumed_edges) == len(set(consumed_edges))
                and set(consumed_edges)
                == set(
                    target_records[0].get(
                        "cyclic_source_side_edge_identity_tokens", ((), ())
                    )[side_index]
                )
                for side_index in range(2)
            )
            and (
                maximum_side_length_ratio is None
                or all(
                    min(record.get("side_lengths", (0.0,))) > 0.0
                    and max(record["side_lengths"]) / min(record["side_lengths"])
                    <= maximum_side_length_ratio
                    for record in target_records
                )
            )
            and (
                station_interval_tolerance is None
                or all(
                    len(record.get("side_station_intervals", ())) == 2
                    and all(
                        abs(first - second) <= station_interval_tolerance
                        for first, second in zip(
                            *record["side_station_intervals"]
                        )
                    )
                    for record in target_records
                )
            )
            and (
                maximum_contract_station_distance is None
                or all(
                    all(
                        min(
                            abs(side_station - cut["contract_station"])
                            % 1.0,
                            (-abs(side_station - cut["contract_station"]))
                            % 1.0,
                        )
                        <= maximum_contract_station_distance
                        for side_station in cut.get("side_cut_stations", ())
                    )
                    for cut in target_records[0].get(
                        "common_cyclic_stations",
                        (),
                    )
                )
            )
        )
    direct_bridge_product = (
        backend_capture.get("called")
        and backend_capture.get("status") == "finished"
        and backend_capture.get("feature_graph_contract") == "GN_PREVIEW_V1"
        and backend_capture.get("expected_chamfer_plan", {}).get("input_contract")
        == "GN_PREVIEW_V1"
        and backend_stats.get("backend") == "DIRECT_EDGE_LOOP_BRIDGE"
        and "Fixed Boolean Boundary Edges" in backend_stats.get("runtime_path", "")
        and backend_stats.get("bridge_job_count", 0) > 0
        and backend_stats.get("bridge_face_count", 0) > 0
        and backend_stats.get("deferred_segment_count") == 0
        and backend_stats.get("boundary_edge_count") == 0
        and backend_stats.get("non_manifold_edge_count") == 0
        and backend_stats.get("zero_area_face_count") == 0
        and backend_stats.get("self_intersection_count") == 0
        and backend_stats.get("self_intersection_validation_strategy")
        == "BATCHED_BRIDGE_FILL_FINAL"
        and 1
        <= backend_stats.get("self_intersection_validation_pass_count", 0)
        <= 3
        and bridge_shape_contract
        and turn_split_contract
        and cyclic_split_contract
    )
    safety_failure = (
        operation_result in (["FINISHED"], ["CANCELLED"])
        and backend_capture.get("error_code")
        and source_unchanged
        and pseudo_output_count == 0
    )
    radius_limit_failure = (
        safety_failure
        and backend_capture.get("error_code")
        in {
            "bridge_faces_self_intersect",
            "final_geometry_self_intersects",
            "junction_fill_self_intersects",
        }
        and final_state == "NO_OUTPUT"
        and diagnostic.get("radius_limit_visible")
    )
    if contract_violations:
        classification = "EXPECTED_UNSUPPORTED"
        reason = ",".join(contract_violations)
    elif (
        operation_result == ["FINISHED"]
        and clean_product_output
        and direct_bridge_product
        and topology_baseline_matches
        and source_unchanged
    ):
        classification = "PRODUCT_SUCCESS"
        reason = "OPERATOR_CREATED_CLEAN_SEPARATE_CHAMFER_OUTPUT"
    elif (
        radius_limit_failure
    ):
        classification = "RADIUS_LIMIT_DIAGNOSTIC"
        reason = backend_capture["error_code"]
    elif (
        safety_failure
        and allow_safe_failure
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


# 返回用于跨 repetition 比较的产品 fingerprint，排除计时、Object 显示名及 dissolve 造成的内部拓扑差异。
# repetition: 单次运行的完整诊断。
def repetition_signature(repetition):
    stable_payload = {
        "classification": repetition["classification"],
        "classification_reason": repetition["classification_reason"],
        "contract_violations": repetition["contract_violations"],
        "operation_result": repetition["operator"]["result"],
        "runtime_proven": repetition["operator"]["runtime_proven"],
        "backend_status": repetition["backend"].get("status"),
        "backend_error_code": repetition["backend"].get("error_code"),
        "backend_error_message": repetition["backend"].get("error_message"),
        "result_plan_id": repetition.get("result_plan", {}).get("plan_id"),
        "source_before": repetition["source_before"]["fingerprint"],
        "source_after_operation": repetition["source_after_operation"],
        "output_contract": {
            key: repetition["output"].get(key)
            for key in (
                "boundary_edge_count",
                "non_manifold_edge_count",
                "zero_area_face_count",
            )
        },
        "final_state": repetition["final_state"],
        "failure_diagnostic": repetition.get("failure_diagnostic"),
        "custom_normal_transfer": repetition["output"].get(
            "custom_normal_transfer"
        ),
        "output_topology": {
            key: repetition["output"].get(key)
            for key in (
                "boundary_edge_count",
                "non_manifold_edge_count",
                "zero_area_face_count",
            )
        },
        "preview_residue": repetition.get("preview_residue"),
        "direct_bridge": {
            key: repetition.get("backend", {}).get("stats", {}).get(key)
            for key in (
                "runtime_path",
                "bridge_shape_contract",
                "bridge_job_count",
                "deferred_segment_count",
                "junction_fill_count",
                "boundary_edge_count",
                "non_manifold_edge_count",
                "zero_area_face_count",
                "dissolve_chamfer_requested",
            )
        },
    }
    return hashlib.sha256(
        json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# 保存一步式结果为 copy，确保 fixture 路径与主文件状态不变。
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
    fixture_label,
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
    source_state_before = source_object_state(source_object)
    source_fingerprint_before = source_before["fingerprint"]
    activate_source(source_object)
    backend_capture = {"called": False}
    operator_module, original_builder = install_backend_capture(
        addon_module,
        backend_capture,
    )
    operation_started = time.perf_counter()
    try:
        operation_result = sorted(
            bpy.ops.hst.feature_chamfer_gn(
                "INVOKE_DEFAULT",
                radius=radius,
            )
        )
    except RuntimeError as error:
        operation_result = ["CANCELLED"]
        operation_error = str(error)
    else:
        operation_error = None
    finally:
        operator_module.build_direct_edge_loop_chamfer = original_builder
    operation_seconds = time.perf_counter() - operation_started
    try:
        one_step_stats = json.loads(
            bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}")
        )
    except json.JSONDecodeError:
        one_step_stats = {}
    backend_capture["one_step_stats"] = json_value(one_step_stats)
    source_fingerprint_after_operation = source_fingerprint(source_object)
    output_object = (
        bpy.context.active_object
        if operation_result == ["FINISHED"] and bpy.context.active_object is not source_object
        else None
    )
    result_plan = phase_2_plan_summary(addon_module, output_object)
    runtime_proven = output_object is not None
    if repetition_index == 0:
        save_artifact_copy(case_directory / "result.blend")

    if operation_error:
        backend_capture.update(
            status="failed",
            error_code="operation_failed_safe",
            error_message=operation_error,
        )

    source_state_after = source_object_state(source_object)
    source_hidden_after_success = all(
        source_state_after[key]
        for key in ("hide_viewport", "hide_render", "hide_set")
    )
    source_content_unchanged = (
        source_fingerprint_before == source_fingerprint_after_operation
        and source_content_state(source_state_before)
        == source_content_state(source_state_after)
    )
    product_output_created = bool(
        output_object is not None
        and output_object.get(addon_module.const.FEATURE_CHAMFER_SOURCE_OBJECT_TAG)
        == source_object.name
    )
    source_unchanged = (
        source_content_unchanged
        and (
            source_hidden_after_success
            if product_output_created
            else source_state_before == source_state_after
        )
    )
    output = output_diagnostics(output_object, source_object)
    preview_residue = {
        "owned_curve_tag": bool(
            source_object.get(addon_module.const.FEATURE_CHAMFER_CURVE_OBJECT_TAG)
        ),
        "preview_modifier": bool(
            source_object.modifiers.get(addon_module.const.FEATURE_CHAMFER_GN_MODIFIER)
        ),
        "owned_curve_objects": [
            obj.name
            for obj in bpy.data.objects
            if obj.get(addon_module.const.FEATURE_CHAMFER_CURVE_OWNER_TAG)
            == source_object.name
        ],
    }
    final_state = (
        "PRODUCT_OUTPUT"
        if output_object is not None
        else "NO_OUTPUT"
    )
    diagnostic = failure_diagnostic(addon_module, source_object)
    pseudo_outputs = [
        obj.name
        for obj in bpy.data.objects
        if obj is not source_object
        and obj.get(addon_module.const.FEATURE_CHAMFER_SOURCE_OBJECT_TAG)
        == source_object.name
    ]
    if output_object is not None and output_object.name in pseudo_outputs:
        pseudo_outputs.remove(output_object.name)
    backend_runtime_proven = (
        backend_capture.get("called")
        and backend_capture.get("feature_graph_contract") == "GN_PREVIEW_V1"
    )
    required_turn_split_contract = TURN_SPLIT_REGRESSION_CONTRACTS.get(
        (fixture_label, object_name)
    )
    required_cyclic_split_contracts = CYCLIC_SPLIT_REGRESSION_CONTRACTS.get(
        (fixture_label, object_name, round(float(radius), 6)),
        (),
    )
    classification, classification_reason, contract_violations = classify_result(
        source_before,
        operation_result,
        output,
        preview_residue,
        backend_capture,
        source_unchanged,
        len(pseudo_outputs),
        final_state,
        diagnostic,
        fixture_label in DEFERRED_LABELS,
        required_turn_split_contract,
        required_cyclic_split_contracts,
        UNDISSOLVED_TOPOLOGY_BASELINES.get(
            (fixture_label, object_name, round(float(radius), 6))
        ),
    )
    return {
        "repetition": repetition_index + 1,
        "classification": classification,
        "classification_reason": classification_reason,
        "contract_violations": contract_violations,
        "source_before": source_before,
        "source_after_operation": source_fingerprint_after_operation,
        "source_object_state_before": source_state_before,
        "source_object_state_after": source_state_after,
        "source_content_unchanged": source_content_unchanged,
        "source_hidden_after_success": source_hidden_after_success,
        "source_unchanged": source_unchanged,
        "operator": {
            "ui_entry": "Feature Chamfer",
            "bl_idname": "hst.feature_chamfer_gn",
            "invocation": "INVOKE_DEFAULT",
            "result": operation_result,
            "runtime_proven": runtime_proven and backend_runtime_proven,
        },
        "backend": json_value(backend_capture),
        "result_plan": result_plan,
        "output": output,
        "preview_residue": preview_residue,
        "final_state": final_state,
        "failure_diagnostic": diagnostic,
        "unexpected_pseudo_outputs": pseudo_outputs,
        "timings_seconds": {
            "one_step_operation": operation_seconds,
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


# 执行正式产品 matrix，验证第一阶段 10 cells 与延期 tricky 的安全结果。
# 无参数；配置通过环境变量由 host runner 注入。
def main():
    if REPETITIONS < 3:
        raise RuntimeError("Feature Chamfer product gate requires at least three repetitions")
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
            "delivery_role": (
                "FIRST_STAGE_REQUIRED"
                if fixture_label in FIRST_STAGE_LABELS
                else "DEFERRED_SAFE_RESULT"
            ),
            "repetitions": [],
        }
        for fixture_label, fixture_name, object_name in MATRIX_SOURCES
        for radius in MATRIX_RADII
    ]
    retry_cases = [
        {
            "case_id": case_id(fixture_label, object_name, radius),
            "fixture_label": fixture_label,
            "fixture": fixture_name,
            "object_name": object_name,
            "radius": radius,
            "delivery_role": "RADIUS_RETRY_EVIDENCE",
            "repetitions": [],
        }
        for fixture_label, fixture_name, object_name in MATRIX_SOURCES
        if fixture_label in FIRST_STAGE_LABELS
        for radius in RETRY_RADII
        if radius not in MATRIX_RADII
    ]
    matrix_cases.extend(retry_cases)
    if CASE_FILTER:
        matrix_cases = [
            case
            for case in matrix_cases
            if case["case_id"] in CASE_FILTER
        ]
        missing_case_ids = CASE_FILTER - {
            case["case_id"]
            for case in matrix_cases
        }
        if missing_case_ids:
            raise RuntimeError(
                f"Unknown Feature Chamfer matrix cases: {sorted(missing_case_ids)}"
            )
    summary = {
        "status": "running",
        "phase": "C_FIRST_STAGE",
        "blender_version": bpy.app.version_string,
        "blender_version_tuple": list(bpy.app.version),
        "repository_root": str(REPO_ROOT),
        "runtime_contract": (
            "UI Feature Chamfer -> hst.feature_chamfer_gn -> INVOKE -> "
            "ONE_STEP TRANSACTION -> accepted Preview Curve Pipe -> Boolean Pro -> "
            "segment Edge Loop groups -> Blender Bridge -> Blender Fill -> final Mesh"
        ),
        "fixture_hashes_expected": FIXTURE_HASHES,
        "fixture_hashes_actual": actual_fixture_hashes,
        "fixture_hashes_valid": fixture_hashes_valid,
        "requested_repetitions": REPETITIONS,
        "case_count": len(matrix_cases),
        "required_matrix_radii": list(MATRIX_RADII),
        "retry_evidence_radii": list(RETRY_RADII),
        "run_scope": (
            "FIRST_STAGE_REQUIRED"
            if CASE_FILTER
            and len(matrix_cases) == 10
            and all(
                case["delivery_role"] == "FIRST_STAGE_REQUIRED"
                for case in matrix_cases
            )
            else (
                "DEFERRED_TRICKY"
                if CASE_FILTER
                and len(matrix_cases) == 4
                and all(
                    case["delivery_role"] == "DEFERRED_SAFE_RESULT"
                    for case in matrix_cases
                )
                else "DIAGNOSTIC_PARTIAL" if CASE_FILTER else "FULL_MATRIX"
            )
        ),
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
                    case["fixture_label"],
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
            item.get("operator", {}).get("runtime_proven", False)
            for item in case["repetitions"]
        )
        result_plan_ids = [
            item.get("result_plan", {}).get("plan_id")
            for item in case["repetitions"]
        ]
        case["result_plan_ids_stable"] = (
            all(result_plan_ids) and len(set(result_plan_ids)) == 1
        )
        (case_directory / "diagnostics.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_summary(summary)

    cases_by_source = {}
    for case in matrix_cases:
        source_key = (
            case["fixture_label"],
            case["fixture"],
            case["object_name"],
        )
        cases_by_source.setdefault(source_key, []).append(case)
    for source_cases in cases_by_source.values():
        successful_cases = sorted(
            (
                case
                for case in source_cases
                if case["classification"] == "PRODUCT_SUCCESS"
            ),
            key=lambda case: case["radius"],
            reverse=True,
        )
        for case in source_cases:
            if case["classification"] != "RADIUS_LIMIT_DIAGNOSTIC":
                continue
            retry_case = next(
                (
                    successful_case
                    for successful_case in successful_cases
                    if successful_case["radius"] < case["radius"]
                ),
                None,
            )
            if retry_case is None:
                continue
            case["requested_radius_classification"] = "RADIUS_LIMIT_DIAGNOSTIC"
            case["classification"] = "PRODUCT_SUCCESS_WITH_RADIUS_RETRY"
            case["retry_evidence"] = {
                "requested_radius": case["radius"],
                "successful_radius": retry_case["radius"],
                "successful_case_id": retry_case["case_id"],
                "operator_changed_radius_automatically": False,
            }
    write_summary(summary)

    classification_counts = {
        classification: sum(
            case["classification"] == classification for case in matrix_cases
        )
        for classification in sorted(CLASSIFICATIONS)
    }
    common_go_conditions = {
        "all_cells_repeated": all(
            len(case["repetitions"]) == REPETITIONS for case in matrix_cases
        ),
        "all_cells_stable": all(case["stable"] for case in matrix_cases),
        "all_sources_unchanged": all(case["source_unchanged"] for case in matrix_cases),
        "all_success_sources_hidden": all(
            all(
                repetition.get("source_hidden_after_success", False)
                for repetition in case["repetitions"]
            )
            for case in matrix_cases
            if case["classification"]
            in {"PRODUCT_SUCCESS", "PRODUCT_SUCCESS_WITH_RADIUS_RETRY"}
        ),
        "all_required_runtime_paths_proven": all(
            case["runtime_path_proven"]
            for case in matrix_cases
            if case["delivery_role"] == "FIRST_STAGE_REQUIRED"
        ),
        "all_cells_classified": all(
            case["classification"] in CLASSIFICATIONS for case in matrix_cases
        ),
        "all_radius_limit_cells_have_retry": all(
            case["classification"] != "RADIUS_LIMIT_DIAGNOSTIC"
            for case in matrix_cases
            if case["delivery_role"] == "FIRST_STAGE_REQUIRED"
        ),
        "fixture_hashes_valid": fixture_hashes_valid,
    }
    runtime_go_conditions = {
        "three_repetitions": REPETITIONS >= 3,
        "legacy_geometry_backend_proven": all(
            repetition.get("classification") != "PRODUCT_SUCCESS"
            or (
                repetition.get("backend", {}).get("feature_graph_contract")
                == "GN_PREVIEW_V1"
                and repetition.get("backend", {}).get("stats", {}).get("backend")
                == "DIRECT_EDGE_LOOP_BRIDGE"
                and repetition.get("backend", {}).get("stats", {}).get(
                    "bridge_job_count",
                    0,
                )
                > 0
                and repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "backend"
                )
                == "FIXED_BOOLEAN_PYTHON_IDENTITY_DIRECT_EDGE_LOOP_BRIDGE"
                and repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "solver"
                )
                == "FIXED_MANIFOLD_BOOLEAN"
                and repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "post_boolean_backend"
                )
                == "PYTHON_NUMPY_FIELD_ADAPTATION_V1"
                and repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "post_boolean_dynamic_node_count"
                )
                == 0
            )
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
        "preview_runtime_cleanup_proven": all(
            repetition.get("classification") != "PRODUCT_SUCCESS"
            or (
                repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "one_step_transaction"
                )
                is True
                and repetition.get("backend", {}).get("one_step_stats", {}).get(
                    "temporary_preview_removed"
                )
                is True
            )
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
        "no_preview_runtime_residue": all(
            not any(
                (
                    repetition.get("preview_residue", {}).get("owned_curve_tag"),
                    repetition.get("preview_residue", {}).get("preview_modifier"),
                    repetition.get("preview_residue", {}).get("owned_curve_objects"),
                )
            )
            for case in matrix_cases
            for repetition in case["repetitions"]
            if repetition.get("classification") == "PRODUCT_SUCCESS"
        ),
        "one_step_runtime_recorded": all(
            repetition.get("classification") != "PRODUCT_SUCCESS"
            or repetition.get("timings_seconds", {}).get("one_step_operation", 0.0)
            > 0.0
            for case in matrix_cases
            for repetition in case["repetitions"]
        ),
    }
    first_stage_cases = [
        case
        for case in matrix_cases
        if case["fixture_label"] in FIRST_STAGE_LABELS
        and case["delivery_role"] == "FIRST_STAGE_REQUIRED"
    ]
    deferred_cases = [
        case for case in matrix_cases if case["fixture_label"] in DEFERRED_LABELS
    ]
    selected_first_stage_scope = {
        (
            case["fixture_label"],
            case["object_name"],
            round(float(case["radius"]), 6),
        )
        for case in first_stage_cases
    }
    target_cyclic_scope = selected_first_stage_scope == CYCLIC_FIX_TARGET_SCOPE
    mixed_cyclic_target_scope = (
        selected_first_stage_scope == MIXED_CYCLIC_FIX_TARGET_SCOPE
    )
    cyclic_fix_regression_scope = (
        selected_first_stage_scope == CYCLIC_FIX_REGRESSION_SCOPE
    )
    cyclic_fix_temporary_gate_scope = selected_first_stage_scope == (
        CYCLIC_FIX_TARGET_SCOPE | CYCLIC_FIX_REGRESSION_SCOPE
    )
    selected_first_stage_complete = len(first_stage_cases) == 10
    first_stage_go_conditions = {
        "required_scope_selected": (
            selected_first_stage_complete
            or target_cyclic_scope
            or mixed_cyclic_target_scope
            or cyclic_fix_regression_scope
            or cyclic_fix_temporary_gate_scope
        ),
        "required_cells_product_success": all(
            case["classification"]
            in {"PRODUCT_SUCCESS", "PRODUCT_SUCCESS_WITH_RADIUS_RETRY"}
            for case in first_stage_cases
        ),
    }
    deferred_go_conditions = {
        "deferred_scope_recorded": len(deferred_cases) == 4,
        "deferred_cells_product_or_safe": all(
            case["classification"] in {"PRODUCT_SUCCESS", "SAFETY_PASS"}
            for case in deferred_cases
        ),
    }
    go_conditions = {
        **common_go_conditions,
        **runtime_go_conditions,
        **first_stage_go_conditions,
    }
    run_go = all(go_conditions.values())
    if not CASE_FILTER:
        go_conditions.update(deferred_go_conditions)
        run_go = all(go_conditions.values())
    summary.update(
        status="finished",
        phase="C_FIRST_STAGE",
        classification_counts=classification_counts,
        go_conditions=go_conditions,
        first_stage_go=(
            all(common_go_conditions.values())
            and all(runtime_go_conditions.values())
            and all(first_stage_go_conditions.values())
        ),
        deferred_tricky_go=(
            len(deferred_cases) == 4
            and all(deferred_go_conditions.values())
        ),
        run_go=run_go,
    )
    write_summary(summary)
    print("[HST_FEATURE_CHAMFER_MATRIX_SUMMARY] " + json.dumps({
        "first_stage_go": summary["first_stage_go"],
        "deferred_tricky_go": summary["deferred_tricky_go"],
        "run_go": summary["run_go"],
        "classification_counts": classification_counts,
        "go_conditions": go_conditions,
    }, ensure_ascii=False))

    try:
        addon_module.unregister()
    except Exception:
        traceback.print_exc()
    if not summary["run_go"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
