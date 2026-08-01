# -*- coding: utf-8 -*-
"""FeatureGraph 的 Blender Mesh 与 Rust primitive 数据适配。"""

from __future__ import annotations

import bpy
import bmesh
import math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .experimental_pipe_chamfer_utils import _edge_convexity


_REQUIRED_GROUP_FIELDS = (
    "edge_indices",
    "vertex_indices",
    "is_cyclic",
    "patch_pair",
    "patch_pair_by_edge",
    "convexity",
    "convexity_by_edge",
    "selected_pair_vertex_ids",
    "start_feature_degree",
    "end_feature_degree",
)


# 从 Blender Mesh 构造稳定、无 bpy 引用的 Rust 输入。
# source_object: 输入 Mesh Object；radius: 当前 Chamfer 半径；返回只含基础数值与数组的 primitive 字典。
def build_feature_graph_native_primitives(
    source_object,
    radius,
    miter_scale_limit=1.5,
):
    mesh = source_object.data
    analysis = bmesh.new()
    analysis.from_mesh(mesh)
    analysis.verts.ensure_lookup_table()
    analysis.edges.ensure_lookup_table()
    analysis.faces.ensure_lookup_table()
    sharp_attribute = mesh.attributes.get("sharp_edge")
    sharp_edge_indices = []
    if sharp_attribute is not None:
        sharp_edge_indices = [
            edge.index
            for edge in mesh.edges
            if bool(sharp_attribute.data[edge.index].value)
        ]
    edge_convexities = [
        _edge_convexity(edge) if len(edge.link_faces) == 2 else 0
        for edge in analysis.edges
    ]
    feature_edges_by_vertex = {}
    for edge_index in sharp_edge_indices:
        for vertex in analysis.edges[edge_index].verts:
            feature_edges_by_vertex.setdefault(vertex.index, []).append(edge_index)
    candidate_metrics = []
    for vertex_index, incident_edge_indices in feature_edges_by_vertex.items():
        vertex = analysis.verts[vertex_index]
        for left_index, edge_a_index in enumerate(incident_edge_indices):
            for edge_b_index in incident_edge_indices[left_index + 1:]:
                tangent_a = (
                    analysis.edges[edge_a_index].other_vert(vertex).co - vertex.co
                ).normalized()
                tangent_b = (
                    analysis.edges[edge_b_index].other_vert(vertex).co - vertex.co
                ).normalized()
                connection_angle = math.degrees(
                    math.acos(max(-1.0, min(1.0, tangent_a.dot(tangent_b))))
                )
                candidate_metrics.append(
                    (
                        int(vertex_index),
                        int(edge_a_index),
                        int(edge_b_index),
                        float(connection_angle),
                        float(
                            1.0
                            / max(
                                math.sin(math.radians(connection_angle) * 0.5),
                                1.0e-6,
                            )
                        ),
                    )
                )
    loop_triangles = [
        tuple(loop.vert.index for loop in triangle)
        for triangle in analysis.calc_loop_triangles()
    ]
    edge_face_ids = [[] for _edge in mesh.edges]
    edge_index_by_key = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge.index
        for edge in mesh.edges
    }
    for polygon in mesh.polygons:
        polygon_index = int(polygon.index)
        for edge_key in polygon.edge_keys:
            edge_index = edge_index_by_key[tuple(sorted(edge_key))]
            edge_face_ids[edge_index].append(polygon_index)

    primitive = {
        "vertices": [
            (float(vertex.co.x), float(vertex.co.y), float(vertex.co.z))
            for vertex in mesh.vertices
        ],
        "edges": [
            (
                int(edge.index),
                int(edge.vertices[0]),
                int(edge.vertices[1]),
                tuple(edge_face_ids[edge.index]),
            )
            for edge in mesh.edges
        ],
        "faces": [
            tuple(int(vertex_index) for vertex_index in polygon.vertices)
            for polygon in mesh.polygons
        ],
        "face_records": [
            {
                "index": int(polygon.index),
                "vertex_indices": tuple(
                    int(vertex_index) for vertex_index in polygon.vertices
                ),
                "edge_indices": tuple(
                    edge_index_by_key[tuple(sorted(edge_key))]
                    for edge_key in polygon.edge_keys
                ),
                "normal": (
                    float(analysis.faces[polygon.index].normal.x),
                    float(analysis.faces[polygon.index].normal.y),
                    float(analysis.faces[polygon.index].normal.z),
                ),
                "center_median": (
                    float(analysis.faces[polygon.index].calc_center_median().x),
                    float(analysis.faces[polygon.index].calc_center_median().y),
                    float(analysis.faces[polygon.index].calc_center_median().z),
                ),
            }
            for polygon in mesh.polygons
        ],
        "sharp_edge_indices": sharp_edge_indices,
        "edge_convexities": edge_convexities,
        "candidate_metrics": candidate_metrics,
        "triangles": loop_triangles,
        "radius": float(radius),
        "miter_scale_limit": float(miter_scale_limit),
    }
    source_bvh = BVHTree.FromBMesh(analysis)
    endpoint_clearance = float(radius)
    tolerance = max(endpoint_clearance * 0.02, 1.0e-6)
    ray_directions = (
        Vector((1.0, 0.371, 0.529)).normalized(),
        Vector((-0.417, 1.0, 0.283)).normalized(),
        Vector((0.233, -0.619, 1.0)).normalized(),
    )
    advance = max(tolerance * 0.25, 1.0e-7)

    # Rust 的 global solver 生成的 endpoint samples 只依赖半边与 radius；在 Blender
    # 边界一次性冻结 BVH 查询结果，避免 729 个组合反复跨 Python 调用且精确保持 BVHTree 语义。
    containment_samples = []
    feature_degrees = {}
    for edge_index in sharp_edge_indices:
        for vertex in analysis.edges[edge_index].verts:
            feature_degrees[vertex.index] = feature_degrees.get(vertex.index, 0) + 1
    acute_split_vertices = set()
    for vertex_index, incident_edge_indices in feature_edges_by_vertex.items():
        if len(incident_edge_indices) != 2:
            continue
        vertex = analysis.verts[vertex_index]
        tangents = [
            (analysis.edges[edge_index].other_vert(vertex).co - vertex.co).normalized()
            for edge_index in incident_edge_indices
        ]
        connection_angle = math.acos(max(-1.0, min(1.0, tangents[0].dot(tangents[1]))))
        miter_scale = 1.0 / max(math.sin(connection_angle * 0.5), 1.0e-6)
        if miter_scale > float(miter_scale_limit):
            acute_split_vertices.add(vertex_index)
    containment_half_edges = {
        (vertex.index, edge_index)
        for edge_index in sharp_edge_indices
        for vertex in analysis.edges[edge_index].verts
        if feature_degrees[vertex.index] != 2
        or vertex.index in acute_split_vertices
    }
    for vertex_index, edge_index in containment_half_edges:
        edge = analysis.edges[edge_index]
        for vertex in edge.verts:
            if vertex.index != vertex_index:
                continue
            neighbor = edge.other_vert(vertex)
            sample = vertex.co + (vertex.co - neighbor.co).normalized() * endpoint_clearance
            nearest = source_bvh.find_nearest(sample)
            nearest_distance = float(nearest[3]) if nearest is not None else 0.0
            inside_votes = 0
            for direction in ray_directions:
                origin = sample.copy()
                hit_count = 0
                remaining_distance = 1.0e6
                while remaining_distance > advance:
                    location, _normal, _face_index, distance = source_bvh.ray_cast(
                        origin,
                        direction,
                        remaining_distance,
                    )
                    if location is None:
                        break
                    hit_count += 1
                    step = max(float(distance), 0.0) + advance
                    origin = Vector(location) + direction * advance
                    remaining_distance -= step
                inside_votes += hit_count % 2
            containment_samples.append(
                (
                    int(vertex.index),
                    int(edge_index),
                    inside_votes >= 2,
                    nearest_distance,
                )
            )
    primitive["containment_samples"] = containment_samples
    analysis.free()
    return primitive


# 将 Rust 返回的纯数据转回现有 FeatureGraph group 与统计合同。
# native_result: 包含 groups 和 stats 的 Rust 结果；stats: 正式流程使用的诊断字典；返回 points 已恢复为 Vector 的 groups。
def restore_feature_graph_native_result(native_result, stats):
    if not isinstance(native_result, dict):
        raise TypeError("Rust FeatureGraph result must be a dict")
    native_groups = native_result.get("groups")
    native_stats = native_result.get("stats")
    if not isinstance(native_groups, (list, tuple)):
        raise TypeError("Rust FeatureGraph result.groups must be a sequence")
    if not isinstance(native_stats, dict):
        raise TypeError("Rust FeatureGraph result.stats must be a dict")

    groups = []
    for pipe_id, native_group in enumerate(native_groups):
        if not isinstance(native_group, dict):
            raise TypeError("Rust FeatureGraph group must be a dict")
        missing_fields = [
            field for field in _REQUIRED_GROUP_FIELDS if field not in native_group
        ]
        if missing_fields:
            raise ValueError(
                "Rust FeatureGraph group is missing fields: "
                + ", ".join(missing_fields)
            )
        points = native_group.get("points")
        if not isinstance(points, (list, tuple)):
            raise TypeError("Rust FeatureGraph group.points must be a sequence")
        groups.append(
            {
                "pipe_id": pipe_id,
                "edge_indices": [int(value) for value in native_group["edge_indices"]],
                "vertex_indices": [
                    int(value) for value in native_group["vertex_indices"]
                ],
                "points": [Vector(point) for point in points],
                "is_cyclic": bool(native_group["is_cyclic"]),
                "patch_pair": tuple(int(value) for value in native_group["patch_pair"]),
                "patch_pair_by_edge": [
                    tuple(int(value) for value in pair)
                    for pair in native_group["patch_pair_by_edge"]
                ],
                "convexity": int(native_group["convexity"]),
                "convexity_by_edge": [
                    int(value) for value in native_group["convexity_by_edge"]
                ],
                "selected_pair_vertex_ids": [
                    int(value)
                    for value in native_group["selected_pair_vertex_ids"]
                ],
                "start_feature_degree": int(
                    native_group["start_feature_degree"]
                ),
                "end_feature_degree": int(native_group["end_feature_degree"]),
            }
        )

    groups.sort(key=lambda group: min(group["edge_indices"]))
    for pipe_id, group in enumerate(groups):
        group["pipe_id"] = pipe_id

    stats.update(native_stats)
    vertex_matching_records = stats.get("vertex_matching", [])
    stats["cutter_strands"] = [
        {
            "strand_id": group["pipe_id"],
            "ordered_edge_ids": group["edge_indices"],
            "cyclic": group["is_cyclic"],
            "selected_pair_vertex_ids": group["selected_pair_vertex_ids"],
            "unmatched_endpoints": [
                vertex_index
                for vertex_index in (
                    group["vertex_indices"][:1]
                    if group["is_cyclic"]
                    else (
                        group["vertex_indices"][0],
                        group["vertex_indices"][-1],
                    )
                )
                if any(
                    record["vertex_index"] == vertex_index
                    and record["unmatched_edge_ids"]
                    for record in vertex_matching_records
                )
            ],
            "generation_backend": "PENDING",
            "geometry_guard": {"status": "PENDING"},
        }
        for group in groups
    ]
    stats["feature_groups"] = [
        {key: value for key, value in group.items() if key != "points"}
        for group in groups
    ]
    return groups
