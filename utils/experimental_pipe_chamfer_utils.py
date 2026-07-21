# -*- coding: utf-8 -*-
"""实验性 Sharp FeatureGraph → 多 Pipe → Boolean → Patch 实现。"""

import itertools
import math
import time

import bpy
import bmesh
from ..const import FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_CURVE_ASSET_SOURCE
from ..const import FEATURE_CHAMFER_CURVE_ASSET_SOURCE_TAG
from ..const import FEATURE_CHAMFER_CURVE_ASSET_VERSION
from ..const import FEATURE_CHAMFER_CURVE_ASSET_VERSION_TAG
from ..const import FEATURE_CHAMFER_CURVE_DEPENDENCY
from ..const import FEATURE_CHAMFER_CURVE_DEPENDENCY_FINGERPRINT
from ..const import FEATURE_CHAMFER_CURVE_FINGERPRINT
from ..const import FEATURE_CHAMFER_CURVE_NODE
from ..const import PRESET_FILE_PATH
from mathutils import Matrix
from mathutils import Vector
from mathutils import geometry
from mathutils.bvhtree import BVHTree
from .feature_chamfer_patch_utils import patch_boolean_result


COLLECTION_NAME = "HST_Experimental_PipeChamfer"
CUTTER_COLLECTION_SUFFIX = "_PipeCutters_TEST"
CUTTER_OBJECT_SUFFIX = "_PipeCutterSet_TEST"
OUTPUT_TAG = "hst_experimental_pipe_chamfer_output"
PIPE_ID_TAG = "hst_pipe_id"
DEBUG_STAGE_TAG = "hst_pipe_chamfer_stage"
ORIGINAL_FACE_ATTRIBUTE = "hst_pipe_original_face"
SOURCE_PATCH_ID_ATTRIBUTE = "hst_pipe_source_patch_id"
CHAMFER_FACE_ATTRIBUTE = "hst_pipe_chamfer"
NORMAL_TRANSFER_MODIFIER = "HST Pipe Chamfer Normal Transfer"
MARKER_MATERIAL_NAME = "HST_PipeChamfer_Marker"
BASE_MATERIAL_NAME = "HST_PipeChamfer_Base"
SUPPORTED_STAGES = {
    "FEATURE_GRAPH",
    "PIPES",
    "CUTTER_UNION",
    "BOOLEAN_CUT",
    "OPEN_BOUNDARY",
    "REGULAR_PATCHED",
    "PATCHED",
}


class PipeChamferError(RuntimeError):
    """携带稳定 error code 与机器统计的几何错误。

    Args:
        error_code: 稳定错误代码。
        message: 面向用户的错误信息。
        stats: 当前阶段已收集的机器统计。
    """

    def __init__(self, error_code, message, stats):
        super().__init__(message)
        self.error_code = error_code
        self.stats = dict(stats)
        self.stats.update(status="failed", error_code=error_code, error_message=message)


# 创建 handoff 规定的结构化统计，所有分支都补齐同一组字段。
# source_object: 输入 Mesh Object；其余参数为 Operator 的公开参数。
def _base_stats(
    source_object,
    radius,
    pipe_resolution,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    junction_margin,
    debug_stage,
):
    return {
        "status": "running",
        "stage": debug_stage,
        "source_object_name": source_object.name if source_object else None,
        "output_object_name": None,
        "sharp_edge_count": 0,
        "surface_patch_count": 0,
        "pipe_group_count": 0,
        "open_pipe_count": 0,
        "closed_pipe_count": 0,
        "topology_junction_count": 0,
        "spatial_junction_count": 0,
        # 兼容旧 redo/诊断数据；Cutter Set 路径不再生成 Union Mesh。
        "union_face_count": 0,
        "cutter_set_object_count": 0,
        "cutter_collection_name": None,
        "pipe_overlap_pairs": [],
        "pipe_endpoint_extensions": [],
        "pipe_endpoint_classifications": [],
        "cutter_face_count": 0,
        "ambiguous_face_count": 0,
        "preserved_original_face_count": 0,
        "source_face_count_before_boolean": 0,
        "deleted_original_face_count": 0,
        "deleted_groove_face_count": 0,
        "regular_region_count": 0,
        "junction_region_count": 0,
        "strip_port_count": 0,
        "regular_patch_face_count": 0,
        "junction_patch_face_count": 0,
        "boundary_edge_count_after": 0,
        "non_manifold_edge_count_after": 0,
        "zero_area_face_count": 0,
        "self_intersection_count": 0,
        "radius": radius,
        "pipe_resolution": pipe_resolution,
        "chain_turn_threshold_degrees": chain_turn_threshold_degrees,
        "chain_turn_spike_ratio": chain_turn_spike_ratio,
        "junction_margin": junction_margin,
        "feature_groups": [],
        "vertex_matching": [],
        "cutter_strands": [],
        "boolean_rail_pairs": [],
        "boundary_rail_topology": {},
        "surface_offset_rail_pairs": [],
        "rail_oracle_summary": {},
        "junction_vertex_indices": [],
        "debug_object_names": [],
        "source_hidden": False,
        "warnings": [],
        "timings": {},
    }


# 抛出稳定失败并标记已生成对象，避免 debug 产物伪装成成功结果。
# error_code: 稳定错误码；message: 失败说明；stats: 当前机器统计。
def _fail(error_code, message, stats):
    for object_name in [stats.get("output_object_name"), *stats.get("debug_object_names", [])]:
        obj = bpy.data.objects.get(object_name) if object_name else None
        if obj is not None and not obj.name.endswith("_FAILED"):
            obj.name = f"{obj.name}_FAILED"
    raise PipeChamferError(error_code, message, stats)


# 获取实验 Collection；该 Collection 只承载 output 与分阶段 debug artifacts。
def _get_collection():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    return collection


# 清理同一 source 上一轮生成的对象，使 Adjust Last Operation 可重复执行。
# source_object: 当前输入 Mesh Object。
def _remove_previous_result(source_object):
    source_object.hide_set(False)
    for obj in list(bpy.data.objects):
        if obj.get(OUTPUT_TAG) == source_object.name:
            bpy.data.objects.remove(obj, do_unlink=True)
    cutter_collection = bpy.data.collections.get(f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}")
    if cutter_collection is not None:
        bpy.data.collections.remove(cutter_collection)
    bpy.context.view_layer.update()


# 在不共享 Mesh Data 的前提下复制 source，后续只修改 duplicate。
# source_object: 输入 Mesh Object；collection: 实验结果 Collection。
def _duplicate_source(source_object, collection):
    output = source_object.copy()
    output.data = source_object.data.copy()
    output.name = f"{source_object.name}_PipeChamfer_TEST"
    output[OUTPUT_TAG] = source_object.name
    collection.objects.link(output)
    return output


# 把 Mesh Object 设为 active/selected，供 modifier apply 等 context API 使用。
# obj: 待激活的 Blender Object。
def _activate_object(obj):
    for selected_object in tuple(bpy.context.selected_objects):
        if selected_object is not obj:
            selected_object.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# 隐藏 source 并记录状态；只在已经生成可观察 artifact 后调用。
# source_object: 原始 Mesh Object；stats: 当前机器统计。
def _hide_source_object(source_object, stats):
    source_object.hide_set(True)
    stats["source_hidden"] = True


# 返回 Mesh 的 boundary、non-manifold 和 zero-area 风险计数。
# obj: 待检查的 Mesh Object。
def _mesh_risk_counts(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result = {
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    return result


# 读取 Blender 5.x sharp_edge attribute；只接受显式 Sharp，不混入 Seam 或角度发现。
# source_object: 输入 Mesh Object；返回 Sharp Edge 索引集合。
def _sharp_edge_indices(source_object):
    sharp_attribute = source_object.data.attributes.get("sharp_edge")
    if sharp_attribute is None or sharp_attribute.domain != "EDGE":
        return set()
    return {
        edge.index
        for edge in source_object.data.edges
        if bool(sharp_attribute.data[edge.index].value)
    }


# 计算由非 Sharp manifold Edge 连通的 Surface Patch，并返回 Face→Patch 映射。
# bm: source 的 BMesh；sharp_edges: Sharp BMEdge 集合。
def _surface_patch_map(bm, sharp_edges):
    face_patch = {}
    patch_index = 0
    for seed_face in sorted(bm.faces, key=lambda face: face.index):
        if seed_face in face_patch:
            continue
        face_patch[seed_face] = patch_index
        stack = [seed_face]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                if edge in sharp_edges or len(edge.link_faces) != 2:
                    continue
                neighbor = next(linked_face for linked_face in edge.link_faces if linked_face is not face)
                if neighbor not in face_patch:
                    face_patch[neighbor] = patch_index
                    stack.append(neighbor)
        patch_index += 1
    return face_patch, patch_index


# 返回 source 每个 Face 所属的 Surface Patch ID，顺序与 polygon index 一致。
# source_object: 输入 Mesh Object。
def _source_face_patch_ids(source_object):
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    sharp_edges = {bm.edges[index] for index in _sharp_edge_indices(source_object)}
    face_patch, _ = _surface_patch_map(bm, sharp_edges)
    patch_ids = [face_patch[bm.faces[index]] for index in range(len(bm.faces))]
    bm.free()
    return patch_ids


# 判定 Sharp Edge 的 convex/concave 类型；只要求相邻 Edge 使用一致的稳定符号。
# edge: manifold BMEdge；返回 -1/0/1。
def _edge_convexity(edge):
    face_a, face_b = edge.link_faces
    edge_midpoint = (edge.verts[0].co + edge.verts[1].co) * 0.5
    direction_a = face_a.calc_center_median() - edge_midpoint
    direction_b = face_b.calc_center_median() - edge_midpoint
    inward_b = direction_b - face_b.normal * direction_b.dot(face_b.normal)
    sign = face_a.normal.dot(inward_b)
    if abs(sign) <= 1.0e-7:
        return 0
    return -1 if sign > 0.0 else 1


# 从指定 Vertex 取得离开该点的单位 tangent。
# edge: 相邻 BMEdge；vertex: 共同 BMVert。
def _outgoing_tangent(edge, vertex):
    return (edge.other_vert(vertex).co - vertex.co).normalized()


# 计算 degree-2 graph Vertex 的转角，直线为 0°、折返为 180°。
# edge_a/edge_b: 相邻 Sharp BMEdge；vertex: 共同 BMVert。
def _turn_angle_degrees(edge_a, edge_b, vertex):
    tangent_a = _outgoing_tangent(edge_a, vertex)
    tangent_b = _outgoing_tangent(edge_b, vertex)
    return math.degrees(math.acos(max(-1.0, min(1.0, (-tangent_a).dot(tangent_b)))))


# 计算两条 half-edge 的 connection angle；180° 表示直通，0° 表示折返。
# edge_a/edge_b: 相邻 Sharp BMEdge；vertex: 共同 BMVert。
def _connection_angle_degrees(edge_a, edge_b, vertex):
    tangent_a = _outgoing_tangent(edge_a, vertex)
    tangent_b = _outgoing_tangent(edge_b, vertex)
    return math.degrees(
        math.acos(max(-1.0, min(1.0, tangent_a.dot(tangent_b))))
    )


# 判断两条 half-edge 的 Surface Patch 与 convexity 语义能否连续。
# metadata_a/metadata_b: 各 Edge 的 patch_pair 与 convexity metadata。
def _half_edge_pair_is_compatible(metadata_a, metadata_b):
    return (
        metadata_a["convexity"] == metadata_b["convexity"]
        and bool(set(metadata_a["patch_pair"]) & set(metadata_b["patch_pair"]))
    )


# 枚举一个 Sharp vertex 的所有 matching，并按总权重、配对数与稳定 Edge ID 决定顺序。
# edge_records: 每项为 (edge_a, edge_b, candidate_record)；返回排序后的 matching records。
def _enumerate_vertex_matchings(edges, edge_records):
    candidates_by_edge = {edge: [] for edge in edges}
    for edge_a, edge_b, candidate in edge_records:
        candidates_by_edge[edge_a].append((edge_b, candidate))
        candidates_by_edge[edge_b].append((edge_a, candidate))

    matchings = []

    def visit(remaining, selected):
        if not remaining:
            ordered = tuple(sorted(selected, key=lambda item: item["edge_ids"]))
            matchings.append(
                {
                    "selected": ordered,
                    "score": sum(item["weight"] for item in ordered),
                }
            )
            return
        edge = min(remaining, key=lambda item: item.index)
        next_remaining = set(remaining)
        next_remaining.remove(edge)
        visit(next_remaining, selected)
        for partner, candidate in candidates_by_edge[edge]:
            if partner not in next_remaining:
                continue
            paired_remaining = set(next_remaining)
            paired_remaining.remove(partner)
            visit(paired_remaining, selected + [candidate])

    visit(set(edges), [])
    matchings.sort(
        key=lambda item: (
            -item["score"],
            -len(item["selected"]),
            tuple(candidate["edge_ids"] for candidate in item["selected"]),
        )
    )
    return matchings


# 对任意连接数的 Sharp vertex 求确定性的 maximum-weight strand matching。
# vertex/edges: junction Vertex 与 incident Sharp Edges；metadata: Surface Patch 上下文。
# miter_scale_limit: Even-Thickness profile 膨胀上限；返回 pair mapping 与 VertexMatchingRecord。
def _maximum_weight_strand_pairs(vertex, edges, metadata, miter_scale_limit=1.25):
    pair_candidates = []
    allowed_candidates = []
    for index_a, edge_a in enumerate(edges):
        for edge_b in edges[index_a + 1:]:
            connection_angle = _connection_angle_degrees(edge_a, edge_b, vertex)
            miter_scale = 1.0 / max(
                math.sin(math.radians(connection_angle) * 0.5),
                1.0e-6,
            )
            compatible = _half_edge_pair_is_compatible(
                metadata[edge_a],
                metadata[edge_b],
            )
            split_reasons = []
            if not compatible:
                split_reasons.append("SURFACE_CONTEXT_INCOMPATIBLE")
            if miter_scale > miter_scale_limit:
                split_reasons.append("MITER_SCALE_EXCEEDED")
            candidate = {
                "edge_ids": (edge_a.index, edge_b.index),
                "connection_angle": connection_angle,
                "miter_scale": miter_scale,
                "allowed": not split_reasons,
                "split_reason": "|".join(split_reasons) if split_reasons else None,
                "weight": connection_angle if not split_reasons else 0.0,
            }
            pair_candidates.append(candidate)
            if candidate["allowed"]:
                allowed_candidates.append((edge_a, edge_b, candidate))

    matchings = _enumerate_vertex_matchings(edges, allowed_candidates)
    best = matchings[0]
    runner_up_score = matchings[1]["score"] if len(matchings) > 1 else 0.0
    selected_pairs = [candidate["edge_ids"] for candidate in best["selected"]]
    selected_edge_ids = {edge_id for pair in selected_pairs for edge_id in pair}
    result = {}
    edges_by_id = {edge.index: edge for edge in edges}
    for edge_id_a, edge_id_b in selected_pairs:
        edge_a = edges_by_id[edge_id_a]
        edge_b = edges_by_id[edge_id_b]
        result[edge_a] = edge_b
        result[edge_b] = edge_a
    record = {
        "vertex_index": vertex.index,
        "incident_edge_ids": [edge.index for edge in edges],
        "pair_candidates": pair_candidates,
        "selected_pairs": selected_pairs,
        "unmatched_edge_ids": [
            edge.index for edge in edges if edge.index not in selected_edge_ids
        ],
        "ambiguity_margin": best["score"] - runner_up_score,
    }
    return result, record


# 为 degree-2 Vertex 构建拓扑优先 pairing；metadata 变化只记录，不切断平滑链。
# vertex/edges/metadata/miter_scale_limit: Vertex、两条 Sharp Edge、ownership metadata 与 miter guard。
def _degree_two_topology_pair(vertex, edges, metadata, miter_scale_limit):
    edge_a, edge_b = edges
    connection_angle = _connection_angle_degrees(edge_a, edge_b, vertex)
    miter_scale = 1.0 / max(
        math.sin(math.radians(connection_angle) * 0.5),
        1.0e-6,
    )
    split_reasons = []
    if miter_scale > miter_scale_limit:
        split_reasons.append("MITER_SCALE_EXCEEDED")
    metadata_compatible = _half_edge_pair_is_compatible(
        metadata[edge_a],
        metadata[edge_b],
    )
    selected_pairs = [] if split_reasons else [(edge_a.index, edge_b.index)]
    pair_candidates = [
        {
            "edge_ids": (edge_a.index, edge_b.index),
            "connection_angle": connection_angle,
            "miter_scale": miter_scale,
            "allowed": not split_reasons,
            "split_reason": "|".join(split_reasons) if split_reasons else None,
            "metadata_compatible": metadata_compatible,
            "warning": (
                "SURFACE_CONTEXT_CHANGED_BUT_TOPOLOGY_CONTINUES"
                if not split_reasons and not metadata_compatible
                else None
            ),
            "patch_pairs": (
                metadata[edge_a]["patch_pair"],
                metadata[edge_b]["patch_pair"],
            ),
            "convexities": (
                metadata[edge_a]["convexity"],
                metadata[edge_b]["convexity"],
            ),
            "weight": connection_angle if not split_reasons else 0.0,
        }
    ]
    result = {}
    if selected_pairs:
        result[edge_a] = edge_b
        result[edge_b] = edge_a
    record = {
        "vertex_index": vertex.index,
        "vertex_coordinate": tuple(vertex.co),
        "incident_edge_ids": [edge_a.index, edge_b.index],
        "pair_candidates": pair_candidates,
        "selected_pairs": selected_pairs,
        "unmatched_edge_ids": [] if selected_pairs else [edge_a.index, edge_b.index],
        "ambiguity_margin": connection_angle if selected_pairs else 0.0,
        "topology_priority_degree_two": True,
    }
    return result, record

# 返回 Pair candidate 的 Edge keys，供全局组合与稳定诊断使用。
# candidate/edges_by_id: Vertex matching candidate 与 Edge ID 查找表。
def _candidate_edge_pair(candidate, edges_by_id):
    edge_id_a, edge_id_b = candidate["edge_ids"]
    return edges_by_id[edge_id_a], edges_by_id[edge_id_b]


# 返回 matching 的几何 tie-break signature；不依赖 Mesh Edge ID。
# matching/edges_by_id: matching record 与 Edge ID 查找表。
def _matching_geometry_signature(matching, edges_by_id):
    pairs = []
    for candidate in matching["selected"]:
        edge_a, edge_b = _candidate_edge_pair(candidate, edges_by_id)
        pair = tuple(
            sorted(
                (
                    tuple(round(value, 7) for value in candidate["vertex"].co),
                    tuple(round(value, 7) for value in edge_a.other_vert(candidate["vertex"]).co),
                    tuple(round(value, 7) for value in edge_b.other_vert(candidate["vertex"]).co),
                )
            )
        )
        pairs.append(pair)
    return tuple(sorted(pairs))


# 判断采样点是否位于 closed source Mesh 内部；ray parity 避免 corner 处 nearest Face normal 歧义。
# source_bvh/point/tolerance: source BVH、查询点与推进容差；返回 inside Boolean。
def _point_inside_closed_bvh(source_bvh, point, tolerance):
    if not hasattr(source_bvh, "ray_cast"):
        nearest = source_bvh.find_nearest(point)
        if nearest is None:
            return False
        location, normal = Vector(nearest[0]), Vector(nearest[1])
        return (point - location).dot(normal) <= tolerance
    directions = (
        Vector((1.0, 0.371, 0.529)).normalized(),
        Vector((-0.417, 1.0, 0.283)).normalized(),
        Vector((0.233, -0.619, 1.0)).normalized(),
    )
    inside_votes = 0
    advance = max(tolerance * 0.25, 1.0e-7)
    for direction in directions:
        origin = Vector(point)
        hit_count = 0
        remaining_distance = 1.0e6
        while remaining_distance > advance:
            location, _, _, distance = source_bvh.ray_cast(
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
    return inside_votes >= 2


# 统计 open Strand endpoint 的 source-solid containment，优先让圆形端盖埋入 attachment body。
# strand_records/source_bvh/clearance: 候选 strands、source Mesh BVH 与 endpoint 采样距离；返回 exposed 数和 margin。
def _strand_endpoint_containment_score(strand_records, source_bvh, clearance):
    if source_bvh is None or clearance <= 0.0:
        return 0, 0.0
    tolerance = max(clearance * 0.02, 1.0e-6)
    exposed_endpoint_count = 0
    containment_margin = 0.0
    for record in strand_records:
        for sample in record.get("endpoint_samples", ()):
            sample = Vector(sample)
            nearest = source_bvh.find_nearest(sample)
            if nearest is None:
                exposed_endpoint_count += 1
                continue
            location = Vector(nearest[0])
            if not _point_inside_closed_bvh(source_bvh, sample, tolerance):
                exposed_endpoint_count += 1
            else:
                containment_margin += (sample - location).length
    return exposed_endpoint_count, containment_margin


# 枚举所有 junction matching 组合，并在评分时保留已确定的 degree-2 拓扑连续关系。
# vertex_edges/metadata/fixed_strand_pairs: junction 邻接、逐 Edge metadata 与固定 pairing；返回 junction pair map 与诊断。
def _global_surface_patch_strand_pairs(
    vertex_edges,
    metadata,
    miter_scale_limit,
    fixed_strand_pairs=None,
    source_bvh=None,
    endpoint_clearance=0.0,
):
    fixed_strand_pairs = fixed_strand_pairs or {}
    vertex_options = []
    vertex_diagnostics = {}
    edge_by_id = {edge.index: edge for edge in metadata}

    strand_pairs = {}
    vertex_matching_records = []
    for vertex, edges in sorted(vertex_edges.items(), key=lambda item: item[0].index):
        pair_candidates = []
        allowed_candidates = []
        for index_a, edge_a in enumerate(edges):
            for edge_b in edges[index_a + 1:]:
                connection_angle = _connection_angle_degrees(edge_a, edge_b, vertex)
                miter_scale = 1.0 / max(
                    math.sin(math.radians(connection_angle) * 0.5),
                    1.0e-6,
                )
                shared_patch_ids = tuple(
                    sorted(set(metadata[edge_a]["patch_pair"]) & set(metadata[edge_b]["patch_pair"]))
                )
                split_reasons = []
                if metadata[edge_a]["convexity"] != metadata[edge_b]["convexity"] or not shared_patch_ids:
                    split_reasons.append("SURFACE_CONTEXT_INCOMPATIBLE")
                if miter_scale > miter_scale_limit:
                    split_reasons.append("MITER_SCALE_EXCEEDED")
                candidate = {
                    "vertex": vertex,
                    "edge_ids": (edge_a.index, edge_b.index),
                    "connection_angle": connection_angle,
                    "miter_scale": miter_scale,
                    "shared_patch_ids": shared_patch_ids,
                    "allowed": not split_reasons,
                    "split_reason": "|".join(split_reasons) if split_reasons else None,
                    "weight": connection_angle if not split_reasons else 0.0,
                }
                pair_candidates.append(candidate)
                if candidate["allowed"]:
                    allowed_candidates.append((edge_a, edge_b, candidate))
        options = _enumerate_vertex_matchings(edges, allowed_candidates)
        maximum_pair_count = max(len(option["selected"]) for option in options)
        maximum_score = max(
            option["score"]
            for option in options
            if len(option["selected"]) == maximum_pair_count
        )
        options = [
            option
            for option in options
            if len(option["selected"]) == maximum_pair_count
            and abs(option["score"] - maximum_score) <= 1.0e-7
        ]
        for option in options:
            option["vertex"] = vertex
            option["geometry_signature"] = _matching_geometry_signature(option, edge_by_id)
        vertex_options.append(options)
        vertex_diagnostics[vertex] = pair_candidates

    search_space_size = math.prod(len(options) for options in vertex_options)
    if search_space_size > 65536:
        raise RuntimeError(
            f"Global Surface Patch matching search budget exceeded: {search_space_size}"
        )
    best = None
    for option_combination in itertools.product(*vertex_options):
        pair_links = {
            (vertex, edge): paired_edge
            for vertex, pairs in fixed_strand_pairs.items()
            for edge, paired_edge in pairs.items()
        }
        selected_candidates = []
        for option in option_combination:
            for candidate in option["selected"]:
                edge_a, edge_b = _candidate_edge_pair(candidate, edge_by_id)
                vertex = candidate["vertex"]
                pair_links[(vertex, edge_a)] = edge_b
                pair_links[(vertex, edge_b)] = edge_a
                selected_candidates.append(candidate)

        remaining = set(metadata)
        strand_records = []
        endpoint_half_edges = sorted(
            (
                (vertex, edge)
                for edge in metadata
                for vertex in edge.verts
                if (vertex, edge) not in pair_links
            ),
            key=lambda item: (
                tuple(round(value, 7) for value in item[0].co),
                tuple(
                    sorted(
                        tuple(round(value, 7) for value in vertex.co)
                        for vertex in item[1].verts
                    )
                ),
            ),
        )
        pending_starts = endpoint_half_edges + [
            (
                min(edge.verts, key=lambda vertex: tuple(round(value, 7) for value in vertex.co)),
                edge,
            )
            for edge in sorted(metadata, key=lambda item: item.index)
        ]
        for start, seed in pending_starts:
            if seed not in remaining:
                continue
            current_vertex = start
            current_edge = seed
            ordered_edges = []
            while current_edge is not None and current_edge in remaining:
                ordered_edges.append(current_edge)
                remaining.remove(current_edge)
                current_vertex = current_edge.other_vert(current_vertex)
                current_edge = pair_links.get((current_vertex, current_edge))
            cyclic = current_vertex is start
            common_patch_ids = set(metadata[ordered_edges[0]]["patch_pair"])
            for edge in ordered_edges[1:]:
                common_patch_ids &= set(metadata[edge]["patch_pair"])
            record = {
                "edge_count": len(ordered_edges),
                "common_patch_ids": tuple(sorted(common_patch_ids)),
                "cyclic": cyclic,
                "endpoint_samples": [],
            }
            if not cyclic and endpoint_clearance > 0.0:
                start_neighbor = seed.other_vert(start)
                end_edge = ordered_edges[-1]
                end_neighbor = end_edge.other_vert(current_vertex)
                record["endpoint_samples"] = [
                    tuple(
                        start.co
                        + (start.co - start_neighbor.co).normalized()
                        * endpoint_clearance
                    ),
                    tuple(
                        current_vertex.co
                        + (current_vertex.co - end_neighbor.co).normalized()
                        * endpoint_clearance
                    ),
                ]
            strand_records.append(record)

        unsupported_turn_count = sum(
            max(0, record["edge_count"] - 1)
            for record in strand_records
            if not record["common_patch_ids"]
        )
        supported_turn_count = sum(
            max(0, record["edge_count"] - 1)
            for record in strand_records
            if record["common_patch_ids"]
        )
        exposed_endpoint_count, endpoint_containment_margin = (
            _strand_endpoint_containment_score(
                strand_records,
                source_bvh,
                endpoint_clearance,
            )
        )
        score = (
            -unsupported_turn_count,
            supported_turn_count,
            len(selected_candidates),
            round(sum(candidate["weight"] for candidate in selected_candidates), 7),
            -exposed_endpoint_count,
            round(endpoint_containment_margin, 7),
            tuple(
                sorted(
                    pair
                    for option in option_combination
                    for pair in option["geometry_signature"]
                )
            ),
        )
        if best is None or score[:6] > best["score"][:6] or (score[:6] == best["score"][:6] and score[6] < best["score"][6]):
            best = {
                "score": score,
                "options": option_combination,
                "pair_links": pair_links,
            }

    strand_pairs = {vertex: {} for vertex in vertex_edges}
    records = []
    for option in best["options"]:
        vertex = option["vertex"]
        selected_pairs = [candidate["edge_ids"] for candidate in option["selected"]]
        selected_edge_ids = {edge_id for pair in selected_pairs for edge_id in pair}
        for candidate in option["selected"]:
            edge_a, edge_b = _candidate_edge_pair(candidate, edge_by_id)
            strand_pairs[vertex][edge_a] = edge_b
            strand_pairs[vertex][edge_b] = edge_a
        records.append(
            {
                "vertex_index": vertex.index,
                "incident_edge_ids": [edge.index for edge in vertex_edges[vertex]],
                "pair_candidates": [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key != "vertex"
                    }
                    for candidate in vertex_diagnostics[vertex]
                ],
                "selected_pairs": selected_pairs,
                "unmatched_edge_ids": [
                    edge.index
                    for edge in vertex_edges[vertex]
                    if edge.index not in selected_edge_ids
                ],
                "ambiguity_margin": 0.0,
                "global_surface_patch_matching": True,
                "global_score": best["score"][:6],
                "endpoint_containment_scoring": source_bvh is not None,
            }
        )
    return strand_pairs, records

# 从 Sharp Edge 建 FeatureGraph，并按 patch pair、convexity、degree 与 turn spike 分 Pipe Groups。
# source_object: 输入 Mesh；threshold/spike: tangent continuity 参数；stats: 机器统计；miter_scale_limit: 允许的 profile 膨胀上限。
def _build_feature_graph(
    source_object,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    stats,
    miter_scale_limit=1.25,
    global_surface_patch_matching=False,
    endpoint_clearance=0.0,
):
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    sharp_indices = _sharp_edge_indices(source_object)
    if not sharp_indices:
        bm.free()
        _fail("no_sharp_edges", "Mesh has no explicit sharp_edge attribute values", stats)
    sharp_edges = {bm.edges[index] for index in sharp_indices}
    invalid = sorted(edge.index for edge in sharp_edges if len(edge.link_faces) != 2)
    if invalid:
        bm.free()
        _fail("sharp_edge_not_manifold", f"Sharp Edges must each connect two Faces: {invalid}", stats)
    face_patch, patch_count = _surface_patch_map(bm, sharp_edges)
    vertex_edges = {}
    metadata = {}
    for edge in sorted(sharp_edges, key=lambda item: item.index):
        patch_pair = tuple(sorted(face_patch[face] for face in edge.link_faces))
        metadata[edge] = {
            "patch_pair": patch_pair,
            "convexity": _edge_convexity(edge),
        }
        for vertex in edge.verts:
            vertex_edges.setdefault(vertex, []).append(edge)
    for edges in vertex_edges.values():
        edges.sort(key=lambda edge: edge.index)
    del chain_turn_threshold_degrees, chain_turn_spike_ratio

    strand_pairs = {}
    vertex_matching_records = []
    for vertex, edges in sorted(vertex_edges.items(), key=lambda item: item[0].index):
        if global_surface_patch_matching and len(edges) == 2:
            pairs, record = _degree_two_topology_pair(
                vertex,
                edges,
                metadata,
                miter_scale_limit,
            )
            strand_pairs[vertex] = pairs
            vertex_matching_records.append(record)
            continue
        pairs, record = _maximum_weight_strand_pairs(
            vertex,
            edges,
            metadata,
            miter_scale_limit=miter_scale_limit,
        )
        strand_pairs[vertex] = pairs
        vertex_matching_records.append(record)
    # Preview 的 global solver 只处理真实 junction；degree-2 topology pairing 必须保留。
    if global_surface_patch_matching:
        source_bvh = BVHTree.FromBMesh(bm)
        global_pairs, global_records = _global_surface_patch_strand_pairs(
            {
                vertex: edges
                for vertex, edges in vertex_edges.items()
                if len(edges) != 2
            },
            metadata,
            miter_scale_limit,
            fixed_strand_pairs={
                vertex: pairs
                for vertex, pairs in strand_pairs.items()
                if len(vertex_edges[vertex]) == 2
            },
            source_bvh=source_bvh,
            endpoint_clearance=endpoint_clearance,
        )
        records_by_vertex = {
            record["vertex_index"]: record
            for record in vertex_matching_records
        }
        for vertex, pairs in global_pairs.items():
            strand_pairs[vertex] = pairs
        for record in global_records:
            records_by_vertex[record["vertex_index"]] = record
        vertex_matching_records = [
            records_by_vertex[vertex.index]
            for vertex in sorted(vertex_edges, key=lambda item: item.index)
        ]
    topology_junctions = sorted(
        vertex.index for vertex, edges in vertex_edges.items() if len(edges) != 2
    )

    def can_continue(vertex, edge_a, edge_b):
        return edge_b is strand_pairs.get(vertex, {}).get(edge_a)

    groups = []
    remaining = set(sharp_edges)
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        component = {seed}
        pending_component_edges = [seed]
        while pending_component_edges:
            component_edge = pending_component_edges.pop()
            for vertex in component_edge.verts:
                paired_edge = strand_pairs.get(vertex, {}).get(component_edge)
                if paired_edge is not None and paired_edge not in component:
                    component.add(paired_edge)
                    pending_component_edges.append(paired_edge)
        endpoint_half_edges = sorted(
            (
                (vertex, edge)
                for edge in component
                for vertex in edge.verts
                if edge not in strand_pairs.get(vertex, {})
            ),
            key=lambda item: (
                tuple(round(value, 7) for value in item[0].co),
                item[1].index,
            ),
        )
        if endpoint_half_edges:
            start, seed = endpoint_half_edges[0]
        else:
            seed = min(component, key=lambda edge: edge.index)
            start = min(seed.verts, key=lambda vertex: vertex.index)
        current = start
        current_edge = seed
        ordered_vertices = [start]
        ordered_edges = []
        while current_edge is not None and current_edge in component and current_edge not in ordered_edges:
            ordered_edges.append(current_edge)
            remaining.discard(current_edge)
            current = current_edge.other_vert(current)
            if current is start:
                break
            ordered_vertices.append(current)
            current_edge = strand_pairs.get(current, {}).get(current_edge)
        endpoint_half_edges = [
            (ordered_vertices[0], ordered_edges[0])
        ] if current is not start else []
        if current is not start:
            endpoint_half_edges.append((current, ordered_edges[-1]))
        cyclic = not endpoint_half_edges
        if not cyclic and len(endpoint_half_edges) != 2:
            bm.free()
            _fail("feature_group_invalid", "Pipe Group is neither an open chain nor a closed loop", stats)
        edge_indices = [edge.index for edge in ordered_edges]
        group = {
            "pipe_id": len(groups),
            "edge_indices": edge_indices,
            "vertex_indices": [vertex.index for vertex in ordered_vertices],
            "points": [vertex.co.copy() for vertex in ordered_vertices],
            "is_cyclic": cyclic,
            "patch_pair": metadata[ordered_edges[0]]["patch_pair"],
            "patch_pair_by_edge": [
                metadata[edge]["patch_pair"] for edge in ordered_edges
            ],
            "convexity": metadata[ordered_edges[0]]["convexity"],
            "convexity_by_edge": [
                metadata[edge]["convexity"] for edge in ordered_edges
            ],
            "selected_pair_vertex_ids": [
                vertex.index
                for vertex in ordered_vertices
                if len(vertex_edges[vertex]) > 1
                and any(
                    set(pair) <= set(edge_indices)
                    for pair in next(
                        record["selected_pairs"]
                        for record in vertex_matching_records
                        if record["vertex_index"] == vertex.index
                    )
                )
            ],
            "start_feature_degree": len(vertex_edges[ordered_vertices[0]]),
            "end_feature_degree": (
                len(vertex_edges[ordered_vertices[0]])
                if cyclic
                else len(vertex_edges[ordered_vertices[-1]])
            ),
        }
        groups.append(group)
        if set(ordered_edges) != component:
            bm.free()
            _fail(
                "feature_group_traversal_incomplete",
                "Pair-connected component was not consumed exactly once",
                stats,
            )
    groups.sort(key=lambda group: min(group["edge_indices"]))
    for pipe_id, group in enumerate(groups):
        group["pipe_id"] = pipe_id
    stats["sharp_edge_count"] = len(sharp_edges)
    stats["surface_patch_count"] = patch_count
    stats["pipe_group_count"] = len(groups)
    stats["open_pipe_count"] = sum(1 for group in groups if not group["is_cyclic"])
    stats["closed_pipe_count"] = sum(1 for group in groups if group["is_cyclic"])
    stats["topology_junction_count"] = len(topology_junctions)
    stats["junction_vertex_indices"] = topology_junctions
    stats["vertex_matching"] = vertex_matching_records
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
        {
            key: value
            for key, value in group.items()
            if key not in {"points"}
        }
        for group in groups
    ]
    bm.free()
    return groups


# 使用正式 GN Preview 的唯一 FeatureGraph 参数合同。
# source_object/radius/stats: source Mesh、Chamfer radius 与诊断字典；返回正式 Preview groups。
def _build_preview_feature_graph(source_object, radius, stats):
    stats["feature_graph_contract"] = "GN_PREVIEW_V1"
    return _build_feature_graph(
        source_object,
        35.0,
        3.0,
        stats,
        miter_scale_limit=1.5,
        global_surface_patch_matching=True,
        endpoint_clearance=radius,
    )


# 从相邻两段求稳定的截面 frame；平行 transport 让 tessellated curve 不随机翻转。
# tangents: spine 顶点 tangent；cyclic: 是否为 closed group。
def _parallel_transport_frames(tangents, cyclic):
    tangent = tangents[0]
    reference = Vector((0.0, 0.0, 1.0))
    if abs(tangent.dot(reference)) > 0.9:
        reference = Vector((1.0, 0.0, 0.0))
    normal = tangent.cross(reference).normalized()
    frames = [(normal, tangent.cross(normal).normalized())]
    for previous_tangent, current_tangent in zip(tangents, tangents[1:]):
        axis = previous_tangent.cross(current_tangent)
        if axis.length > 1.0e-8:
            rotation = Vector(axis).normalized()
            angle = previous_tangent.angle(current_tangent)
            normal.rotate(Matrix.Rotation(angle, 3, rotation))
        normal = (normal - current_tangent * normal.dot(current_tangent)).normalized()
        frames.append((normal, current_tangent.cross(normal).normalized()))
    if cyclic and len(frames) > 2:
        seam_axis = frames[-1][0].cross(frames[0][0])
        signed_twist = math.atan2(tangents[0].dot(seam_axis), frames[-1][0].dot(frames[0][0]))
        for index, (frame_normal, _) in enumerate(frames):
            correction = Matrix.Rotation(signed_twist * index / len(frames), 3, tangents[index])
            frame_normal = (correction @ frame_normal).normalized()
            frames[index] = (frame_normal, tangents[index].cross(frame_normal).normalized())
    return frames


# 判断 Pipe 端点类型，并返回相邻 source face 的角度与候选 terminal face。
# bm: source BMesh；group: Pipe Group；endpoint: start/end；返回 (class, terminal_face, angle)。
def _classify_pipe_endpoint(bm, group, endpoint):
    if group["is_cyclic"]:
        return "CYCLIC", None, 0.0
    endpoint_index = 0 if endpoint == "start" else -1
    neighbor_index = 1 if endpoint == "start" else -2
    edge_index = group["edge_indices"][0 if endpoint == "start" else -1]
    vertex = bm.verts[group["vertex_indices"][endpoint_index]]
    outward = (group["points"][endpoint_index] - group["points"][neighbor_index]).normalized()
    pipe_side_faces = set(bm.edges[edge_index].link_faces)
    candidates = [
        face
        for face in vertex.link_faces
        if face not in pipe_side_faces and face.normal.dot(outward) > math.cos(math.radians(15.0))
    ]
    if len(candidates) == 1:
        return "TERMINAL_FACE", candidates[0], 0.0
    if not candidates:
        neighbor_faces = [face for face in vertex.link_faces if face not in pipe_side_faces]
        if len(neighbor_faces) >= 2:
            best_angle = min(
                neighbor_faces[index_a].normal.angle(neighbor_faces[index_b].normal)
                for index_a in range(len(neighbor_faces))
                for index_b in range(index_a + 1, len(neighbor_faces))
            )
            return "JUNCTION_BRANCH", None, best_angle
        return "SURFACE_CONTINUATION", None, 0.0
    return "AMBIGUOUS", None, 0.0


# 按端点类型与交角计算 Pipe 两端延长量，并把分类写入 group 供诊断。
# source_object: source Mesh；group: Pipe Group；radius: Pipe 半径；返回 start/end extension。
def _pipe_endpoint_extensions(source_object, group, radius):
    if group["is_cyclic"]:
        group["start_endpoint_class"] = "CYCLIC"
        group["end_endpoint_class"] = "CYCLIC"
        return (0.0, 0.0)
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    start_class, start_face, start_angle = _classify_pipe_endpoint(bm, group, "start")
    end_class, end_face, end_angle = _classify_pipe_endpoint(bm, group, "end")
    group["start_endpoint_class"] = start_class
    group["end_endpoint_class"] = end_class
    group["start_terminal_face_index"] = start_face.index if start_face is not None else None
    group["end_terminal_face_index"] = end_face.index if end_face is not None else None

    def extension_for(endpoint_class, angle):
        if endpoint_class == "TERMINAL_FACE":
            return radius
        if endpoint_class == "JUNCTION_BRANCH":
            return min(
                radius / max(math.sin(angle / 2.0), 1.0e-6) + radius * 0.25,
                radius * 3.0,
            )
        return 0.0

    bm.free()
    return (
        extension_for(start_class, start_angle),
        extension_for(end_class, end_angle),
    )


# 一次性为全部 Pipe Group 分类端点，并保存延长量供 Mesh 构建与诊断复用。
# source_object: source Mesh；groups: 全部 Pipe Groups；radius: Pipe 半径。
def _classify_pipe_endpoints(source_object, groups, radius):
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    for group in groups:
        if group["is_cyclic"]:
            endpoint_results = (("CYCLIC", None, 0.0), ("CYCLIC", None, 0.0))
        else:
            endpoint_results = (
                _classify_pipe_endpoint(bm, group, "start"),
                _classify_pipe_endpoint(bm, group, "end"),
            )
        for endpoint, (endpoint_class, terminal_face, angle) in zip(
            ("start", "end"), endpoint_results
        ):
            group[f"{endpoint}_endpoint_class"] = endpoint_class
            group[f"{endpoint}_terminal_face_index"] = (
                terminal_face.index if terminal_face is not None else None
            )
            group[f"{endpoint}_angle"] = angle
            if endpoint_class == "TERMINAL_FACE":
                group[f"{endpoint}_extension"] = radius
            elif endpoint_class == "JUNCTION_BRANCH":
                group[f"{endpoint}_extension"] = min(
                    radius / max(math.sin(angle / 2.0), 1.0e-6) + radius * 0.25,
                    radius * 3.0,
                )
            else:
                group[f"{endpoint}_extension"] = 0.0
    bm.free()


# 验证受控 Curve Pipe Node Group 的 exact metadata 与 dependency link。
# node_group: 待验证的根 GeometryNodeTree；返回是否匹配发布资产。
def _is_valid_curve_pipe_asset(node_group):
    dependency_group = bpy.data.node_groups.get(FEATURE_CHAMFER_CURVE_DEPENDENCY)
    dependency_nodes = [
        node
        for node in node_group.nodes
        if getattr(node, "node_tree", None) is dependency_group
    ]
    return (
        node_group.bl_idname == "GeometryNodeTree"
        and node_group.get(FEATURE_CHAMFER_CURVE_ASSET_VERSION_TAG)
        == FEATURE_CHAMFER_CURVE_ASSET_VERSION
        and node_group.get(FEATURE_CHAMFER_CURVE_ASSET_SOURCE_TAG)
        == FEATURE_CHAMFER_CURVE_ASSET_SOURCE
        and node_group.get(FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG)
        == FEATURE_CHAMFER_CURVE_FINGERPRINT
        and dependency_group is not None
        and dependency_group.get(FEATURE_CHAMFER_CURVE_ASSET_VERSION_TAG)
        == FEATURE_CHAMFER_CURVE_ASSET_VERSION
        and dependency_group.get(FEATURE_CHAMFER_CURVE_ASSET_SOURCE_TAG)
        == FEATURE_CHAMFER_CURVE_ASSET_SOURCE
        and dependency_group.get(FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG)
        == FEATURE_CHAMFER_CURVE_DEPENDENCY_FINGERPRINT
        and len(dependency_nodes) == 1
    )


# 按 exact name/version/fingerprint 幂等导入受控 Curve Pipe asset。
# 无参数；返回根 GeometryNodeTree，冲突或被改写时 fail-closed。
def ensure_feature_chamfer_curve_pipe_asset():
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_CURVE_NODE)
    if node_group is not None:
        if not _is_valid_curve_pipe_asset(node_group):
            raise RuntimeError(
                f"Curve Pipe Node Group 名称冲突或 fingerprint 不匹配: "
                f"{FEATURE_CHAMFER_CURVE_NODE}"
            )
        return node_group
    if not PRESET_FILE_PATH.exists():
        raise RuntimeError(f"Curve Pipe asset 不存在: {PRESET_FILE_PATH}")
    bpy.ops.wm.append(
        filepath=str(PRESET_FILE_PATH),
        directory=str(PRESET_FILE_PATH / "NodeTree"),
        filename=FEATURE_CHAMFER_CURVE_NODE,
    )
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_CURVE_NODE)
    if node_group is None or not _is_valid_curve_pipe_asset(node_group):
        raise RuntimeError("导入的 Curve Pipe asset 或 Poly-Curve Info 依赖不匹配")
    return node_group


# 创建只负责当前 Pipe 参数绑定的临时 GN wrapper。
# asset/radius/resolution/fill_caps: 受控 asset 与规则圆 profile 参数。
def _build_curve_pipe_wrapper(asset, radius, resolution, fill_caps):
    wrapper = bpy.data.node_groups.new(
        f"HST Curve Pipe Wrapper {radius:.8f} {resolution} {int(fill_caps)}",
        "GeometryNodeTree",
    )
    wrapper.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    wrapper.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    group_input = wrapper.nodes.new("NodeGroupInput")
    group_output = wrapper.nodes.new("NodeGroupOutput")
    curve_circle = wrapper.nodes.new("GeometryNodeCurvePrimitiveCircle")
    curve_circle.inputs["Resolution"].default_value = resolution
    curve_circle.inputs["Radius"].default_value = radius
    asset_node = wrapper.nodes.new("GeometryNodeGroup")
    asset_node.node_tree = asset
    asset_node.inputs["Fill Caps"].default_value = fill_caps
    asset_node.inputs["Even-Thickness"].default_value = True
    wrapper.links.new(group_input.outputs["Geometry"], asset_node.inputs["Curve"])
    wrapper.links.new(curve_circle.outputs["Curve"], asset_node.inputs["Profile Curve"])
    wrapper.links.new(asset_node.outputs["Geometry"], group_output.inputs["Geometry"])
    return wrapper


# 使用受控 Even-Thickness GN asset 生成 open/closed Curve Pipe Mesh。
# Python 已完成 strand matching；Geometry Nodes 只消费有序 Curve 并生成规则截面。
# source_object: transform 来源；group: Pipe Group；radius/resolution: 截面参数；collection: 输出位置。
def _build_pipe_mesh_curve(source_object, group, radius, pipe_resolution, collection):
    points = [point.copy() for point in group["points"]]
    cyclic = group["is_cyclic"]
    start_extension = 0.0 if cyclic else group.get("start_extension", 0.0)
    end_extension = 0.0 if cyclic else group.get("end_extension", 0.0)
    if not cyclic:
        start_tangent = (points[1] - points[0]).normalized()
        end_tangent = (points[-1] - points[-2]).normalized()
        points[0] -= start_tangent * start_extension
        points[-1] += end_tangent * end_extension
    curve_name = f"{source_object.name}_PipeCurve_{group['pipe_id']}"
    curve = bpy.data.curves.new(curve_name, type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for index, point in enumerate(points):
        spline.points[index].co = (point.x, point.y, point.z, 1.0)
    spline.use_cyclic_u = cyclic

    curve_obj = bpy.data.objects.new(curve_name, curve)
    curve_obj.matrix_world = source_object.matrix_world.copy()
    collection.objects.link(curve_obj)

    node_group = ensure_feature_chamfer_curve_pipe_asset()
    wrapper = _build_curve_pipe_wrapper(
        node_group,
        radius,
        pipe_resolution,
        not cyclic,
    )
    modifier = curve_obj.modifiers.new("HST Curve Pipe Even-Thickness", type="NODES")
    modifier.node_group = wrapper

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = curve_obj.evaluated_get(depsgraph)
    pipe_mesh = bpy.data.meshes.new_from_object(
        evaluated_object,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    pipe = bpy.data.objects.new(
        f"{source_object.name}_Pipe_{group['pipe_id']}_TEST",
        pipe_mesh,
    )
    pipe.matrix_world = source_object.matrix_world.copy()
    collection.objects.link(pipe)
    bpy.data.objects.remove(curve_obj, do_unlink=True)
    if curve.users == 0:
        bpy.data.curves.remove(curve)
    bpy.data.node_groups.remove(wrapper)

    pipe[OUTPUT_TAG] = source_object.name
    pipe[PIPE_ID_TAG] = group["pipe_id"]
    pipe["hst_pipe_generation_backend"] = "EVEN_THICKNESS_GN"
    pipe["hst_pipe_start_extension"] = start_extension
    pipe["hst_pipe_end_extension"] = end_extension
    pipe["hst_pipe_start_endpoint_class"] = group.get("start_endpoint_class", "CYCLIC")
    pipe["hst_pipe_end_endpoint_class"] = group.get("end_endpoint_class", "CYCLIC")
    pipe[DEBUG_STAGE_TAG] = "PIPES"
    return pipe


# 直接生成一根 open/closed Pipe Mesh，保留为手写 A/B debug backend。
# source_object: transform 来源；group: Pipe Group；radius/resolution: 截面参数；collection: 输出位置。
def _build_pipe_mesh_manual(source_object, group, radius, pipe_resolution, collection):
    points = [point.copy() for point in group["points"]]
    cyclic = group["is_cyclic"]
    start_extension = 0.0 if cyclic else group.get("start_extension", 0.0)
    end_extension = 0.0 if cyclic else group.get("end_extension", 0.0)
    if not cyclic:
        start_tangent = (points[1] - points[0]).normalized()
        end_tangent = (points[-1] - points[-2]).normalized()
        points[0] -= start_tangent * start_extension
        points[-1] += end_tangent * end_extension
    tangents = []
    for index, point in enumerate(points):
        if cyclic:
            previous_point = points[index - 1]
            next_point = points[(index + 1) % len(points)]
            tangent = (next_point - previous_point).normalized()
        elif index == 0:
            tangent = (points[1] - point).normalized()
        elif index == len(points) - 1:
            tangent = (point - points[index - 1]).normalized()
        else:
            tangent = (points[index + 1] - points[index - 1]).normalized()
        tangents.append(tangent)
    frames = _parallel_transport_frames(tangents, cyclic)
    vertices = []
    for point, (normal, binormal) in zip(points, frames):
        for segment in range(pipe_resolution):
            angle = math.tau * segment / pipe_resolution
            vertices.append(tuple(point + radius * (math.cos(angle) * normal + math.sin(angle) * binormal)))
    faces = []
    ring_count = len(points)
    span_count = ring_count if cyclic else ring_count - 1
    for ring in range(span_count):
        next_ring = (ring + 1) % ring_count
        for segment in range(pipe_resolution):
            next_segment = (segment + 1) % pipe_resolution
            faces.append((
                ring * pipe_resolution + segment,
                ring * pipe_resolution + next_segment,
                next_ring * pipe_resolution + next_segment,
                next_ring * pipe_resolution + segment,
            ))
    if not cyclic:
        faces.append(tuple(reversed(range(pipe_resolution))))
        last_start = (ring_count - 1) * pipe_resolution
        faces.append(tuple(last_start + segment for segment in range(pipe_resolution)))
    elif ring_count > 2:
        seam_shift = min(
            range(pipe_resolution),
            key=lambda shift: sum(
                (
                    Vector(vertices[segment])
                    - Vector(vertices[(ring_count - 1) * pipe_resolution + (segment + shift) % pipe_resolution])
                ).length_squared
                for segment in range(pipe_resolution)
            ),
        )
        faces = [face for face in faces if not any(index >= (ring_count - 1) * pipe_resolution for index in face) or not any(index < pipe_resolution for index in face)]
        last_ring = ring_count - 1
        for segment in range(pipe_resolution):
            next_segment = (segment + 1) % pipe_resolution
            faces.append((
                last_ring * pipe_resolution + (segment + seam_shift) % pipe_resolution,
                last_ring * pipe_resolution + (next_segment + seam_shift) % pipe_resolution,
                next_segment,
                segment,
            ))
    mesh = bpy.data.meshes.new(f"{source_object.name}_Pipe_{group['pipe_id']}")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    pipe = bpy.data.objects.new(f"{source_object.name}_Pipe_{group['pipe_id']}_TEST", mesh)
    pipe.matrix_world = source_object.matrix_world.copy()
    pipe[OUTPUT_TAG] = source_object.name
    pipe[PIPE_ID_TAG] = group["pipe_id"]
    pipe["hst_pipe_start_extension"] = start_extension
    pipe["hst_pipe_end_extension"] = end_extension
    pipe["hst_pipe_start_endpoint_class"] = group.get("start_endpoint_class", "CYCLIC")
    pipe["hst_pipe_end_endpoint_class"] = group.get("end_endpoint_class", "CYCLIC")
    pipe[DEBUG_STAGE_TAG] = "PIPES"
    collection.objects.link(pipe)
    return pipe


# 选择 Pipe 几何后端：正式 Phase 1 默认使用受控 Even-Thickness GN。
# source_object: transform 来源；group: Pipe Group；radius/resolution: 截面参数；collection: 输出位置。
def _build_pipe_mesh(source_object, group, radius, pipe_resolution, collection):
    return _build_pipe_mesh_curve(
        source_object,
        group,
        radius,
        pipe_resolution,
        collection,
    )

def _build_joined_cutter_mesh(pipes, source_object, cutter_collection, cutter_index):
    vertices = []
    faces = []
    face_pipe_ids = []
    for pipe in pipes:
        vertex_offset = len(vertices)
        vertices.extend(vertex.co.copy() for vertex in pipe.data.vertices)
        for polygon in pipe.data.polygons:
            faces.append(
                tuple(vertex_offset + vertex_index for vertex_index in polygon.vertices)
            )
            face_pipe_ids.append(int(pipe[PIPE_ID_TAG]))
    mesh = bpy.data.meshes.new(f"{source_object.name}{CUTTER_OBJECT_SUFFIX}_{cutter_index}")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    pipe_id_attribute = mesh.attributes.new(
        "hst_pipe_component_id",
        type="INT",
        domain="FACE",
    )
    for polygon, pipe_id in zip(mesh.polygons, face_pipe_ids):
        pipe_id_attribute.data[polygon.index].value = pipe_id
    cutter = bpy.data.objects.new(mesh.name, mesh)
    cutter.matrix_world = source_object.matrix_world.copy()
    cutter[OUTPUT_TAG] = source_object.name
    cutter["hst_pipe_component_count"] = len(pipes)
    cutter.display_type = "WIRE"
    cutter_collection.objects.link(cutter)
    return cutter


# 用 overlap graph greedy coloring 把互不相交的 Pipes 打包到同一 Mesh，避免自相交 Cutter。
# pipe_count: Pipe 数量；spatial_pairs: 互相 overlap 的 Pipe index pairs；返回 Pipe index groups。
def _non_overlapping_pipe_batches(pipe_count, spatial_pairs):
    neighbors = {index: set() for index in range(pipe_count)}
    for index_a, index_b in spatial_pairs:
        neighbors[index_a].add(index_b)
        neighbors[index_b].add(index_a)
    batches = []
    for pipe_index in sorted(range(pipe_count), key=lambda index: (-len(neighbors[index]), index)):
        target_batch = next(
            (
                batch
                for batch in batches
                if all(other_index not in neighbors[pipe_index] for other_index in batch)
            ),
            None,
        )
        if target_batch is None:
            target_batch = []
            batches.append(target_batch)
        target_batch.append(pipe_index)
    return batches


# 创建 overlap-safe 的 join-only Cutter Mesh batches，并用 Pipe BVH overlap 为空间 Junction 提供统计。
# pipes: 独立 Pipe Objects；source_object/stats: 输出上下文。
def _build_cutter_set(pipes, source_object, stats):
    spatial_pairs = set()
    trees = []
    pipe_bounds = []
    for pipe in pipes:
        bm = bmesh.new()
        bm.from_mesh(pipe.data)
        trees.append(BVHTree.FromBMesh(bm))
        bm.free()
        pipe_bounds.append(_pipe_bounds(pipe))
    for index_a, tree_a in enumerate(trees):
        for index_b in range(index_a + 1, len(trees)):
            if _bounds_overlap(pipe_bounds[index_a], pipe_bounds[index_b]) and tree_a.overlap(trees[index_b]):
                spatial_pairs.add((index_a, index_b))
    cutter_collection = bpy.data.collections.new(f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}")
    bpy.context.scene.collection.children.link(cutter_collection)
    pipe_batches = _non_overlapping_pipe_batches(len(pipes), spatial_pairs)
    joined_cutters = [
        _build_joined_cutter_mesh(
            [pipes[pipe_index] for pipe_index in batch],
            source_object,
            cutter_collection,
            cutter_index,
        )
        for cutter_index, batch in enumerate(pipe_batches)
    ]
    stats["spatial_junction_count"] = len(spatial_pairs)
    stats["pipe_overlap_pairs"] = [list(pair) for pair in sorted(spatial_pairs)]
    stats["cutter_set_object_count"] = len(pipes)
    stats["cutter_collection_name"] = cutter_collection.name
    stats["joined_cutter_object_names"] = [cutter.name for cutter in joined_cutters]
    stats["joined_cutter_batch_count"] = len(joined_cutters)
    return cutter_collection, trees, pipe_bounds


# 添加可手动调整的 Cutter Collection Boolean Modifier，不 Apply、不改写 Mesh data。
# output: source duplicate；cutter_collection: 独立 Pipe 集合；返回 Boolean Modifier。
def _add_difference_modifier(output, cutter_collection):
    modifier = output.modifiers.new("HST Pipe Exact Difference", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    if len(cutter_collection.objects) == 1:
        modifier.operand_type = "OBJECT"
        modifier.object = cutter_collection.objects[0]
    else:
        modifier.operand_type = "COLLECTION"
        modifier.collection = cutter_collection
    return modifier


# 在 Boolean Apply 前写入原面标记与 Surface Patch ID provenance。
# output: source duplicate；source_patch_ids: polygon index 对应的 Patch ID。
def _mark_original_faces(output, source_patch_ids):
    attribute = output.data.attributes.get(ORIGINAL_FACE_ATTRIBUTE)
    if attribute is not None:
        output.data.attributes.remove(attribute)
    attribute = output.data.attributes.new(
        ORIGINAL_FACE_ATTRIBUTE,
        type="BOOLEAN",
        domain="FACE",
    )
    for item in attribute.data:
        item.value = True
    patch_id_attribute = output.data.attributes.get(SOURCE_PATCH_ID_ATTRIBUTE)
    if patch_id_attribute is not None:
        output.data.attributes.remove(patch_id_attribute)
    patch_id_attribute = output.data.attributes.new(
        SOURCE_PATCH_ID_ATTRIBUTE,
        type="INT",
        domain="FACE",
    )
    for polygon in output.data.polygons:
        patch_id_attribute.data[polygon.index].value = source_patch_ids[polygon.index]


# 为后续自动开口/补面阶段应用 Difference，并用 material marker 保留 cutter Face 线索。
# output: source duplicate；cutter_collection: 独立 Pipe 集合；source_patch_ids: 原面 Patch IDs。
def _apply_difference(output, cutter_collection, source_patch_ids):
    _mark_original_faces(output, source_patch_ids)
    base_material = bpy.data.materials.get(BASE_MATERIAL_NAME) or bpy.data.materials.new(BASE_MATERIAL_NAME)
    if len(output.data.materials) == 0:
        output.data.materials.append(base_material)
    marker = bpy.data.materials.get(MARKER_MATERIAL_NAME) or bpy.data.materials.new(MARKER_MATERIAL_NAME)
    marker.diffuse_color = (1.0, 0.02, 0.02, 1.0)
    output.data.materials.append(marker)
    marker_index = len(output.data.materials) - 1
    for pipe in cutter_collection.objects:
        pipe.data.materials.clear()
        pipe.data.materials.append(marker)
        for polygon in pipe.data.polygons:
            polygon.material_index = 0
    modifier = _add_difference_modifier(output, cutter_collection)
    with bpy.context.temp_override(
        object=output,
        active_object=output,
        selected_objects=[output],
        selected_editable_objects=[output],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return marker_index


# 用 marker 与 Pipe BVH 双重证据分类 cutter-derived Faces；ambiguous 时不进入 PATCHED。
# output: Difference 结果；marker_index: material provenance；pipe_trees: 原始 Pipe BVH。
def _classify_cutter_faces(output, marker_index, pipe_trees, radius):
    owner_sets = {}
    ambiguous = []
    tolerance = max(radius * 0.35, max(output.dimensions) * 2.0e-5 + 1.0e-6)
    for polygon in output.data.polygons:
        material_marked = polygon.material_index == marker_index
        center = output.matrix_world @ polygon.center
        owners = set()
        for pipe_id, tree in enumerate(pipe_trees):
            nearest = tree.find_nearest(center)
            if nearest is not None and nearest[3] is not None and nearest[3] <= tolerance:
                owners.add(pipe_id)
        if material_marked and not owners:
            ambiguous.append(polygon.index)
        if material_marked or owners:
            owner_sets[polygon.index] = owners
    return owner_sets, ambiguous


# 按 Boolean 传播的 original-face attribute 区分槽面与原表面。
# output: Apply 后 Mesh；stats: 结构化统计；返回应删除的 groove Face indices。
def _groove_face_indices(output, stats):
    attribute = output.data.attributes.get(ORIGINAL_FACE_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE":
        _fail(
            "original_face_provenance_missing",
            "Boolean 后未找到原面标记，无法安全删除槽面",
            stats,
        )
    original_faces = {
        polygon.index
        for polygon in output.data.polygons
        if bool(attribute.data[polygon.index].value)
    }
    groove_faces = {
        polygon.index
        for polygon in output.data.polygons
        if polygon.index not in original_faces
    }
    stats["preserved_original_face_count"] = len(original_faces)
    stats["deleted_original_face_count"] = 0
    stats["deleted_groove_face_count"] = len(groove_faces)
    if not groove_faces:
        _fail("boolean_no_cutter_faces", "Boolean 后没有识别到 Pipe 生成的槽面", stats)
    return sorted(groove_faces)


# 合并 Boolean 生成的重合 Boundary vertices，删除零长度 Edge 且保留 Face custom data。
# bm/radius: 已删除槽面的 BMesh 与 Chamfer radius；返回清理前后统计。
def _clean_open_boundary_degenerates(bm, radius):
    distance = max(radius * 1.0e-7, 1.0e-9)
    zero_edges_before = [
        edge
        for edge in bm.edges
        if (edge.verts[1].co - edge.verts[0].co).length <= distance
    ]
    if zero_edges_before:
        bmesh.ops.remove_doubles(
            bm,
            verts=list(
                {
                    vertex
                    for edge in zero_edges_before
                    for vertex in edge.verts
                }
            ),
            dist=distance,
        )
    bmesh.ops.dissolve_degenerate(
        bm,
        dist=distance,
        edges=list(bm.edges),
    )
    return {
        "distance": distance,
        "zero_edge_count_before": len(zero_edges_before),
        "zero_edge_count_after": sum(
            (edge.verts[1].co - edge.verts[0].co).length <= distance
            for edge in bm.edges
        ),
    }


# 删除 cutter Faces 并把 BoundaryGraph 的连通边界环提取为有序 BMVert 序列。
# output: Difference 结果；cutter_face_indices: 待删除 Face 索引；stats: 机器统计。
def _open_boundary(
    output,
    cutter_face_indices,
    stats,
    radius,
    allow_non_simple=False,
):
    bm = bmesh.new()
    bm.from_mesh(output.data)
    bm.faces.ensure_lookup_table()
    to_delete = [bm.faces[index] for index in cutter_face_indices]
    bmesh.ops.delete(bm, geom=to_delete, context="FACES_KEEP_BOUNDARY")
    stats["boundary_degenerate_cleanup"] = _clean_open_boundary_degenerates(
        bm,
        radius,
    )
    boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    adjacency = {}
    for edge in boundary_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    if any(len(edges) != 2 for edges in adjacency.values()):
        if allow_non_simple:
            bm.to_mesh(output.data)
            output.data.update()
            return bm, []
        bm.free()
        _fail("ambiguous_boundary", "BoundaryGraph contains non degree-2 rail vertices", stats)
    loops = []
    remaining = set(boundary_edges)
    while remaining:
        start_edge = min(remaining, key=lambda edge: edge.index)
        start = min(start_edge.verts, key=lambda vertex: vertex.index)
        loop = [start]
        current = start
        previous = None
        while True:
            edge = next(
                (candidate for candidate in sorted(adjacency[current], key=lambda item: item.index) if candidate is not previous and candidate in remaining),
                None,
            )
            if edge is None:
                break
            remaining.remove(edge)
            current = edge.other_vert(current)
            previous = edge
            if current is start:
                break
            loop.append(current)
        if current is not start or len(loop) < 3:
            bm.free()
            _fail("ambiguous_boundary", "BoundaryGraph contains a non-simple boundary", stats)
        loops.append(loop)
    bm.to_mesh(output.data)
    output.data.update()
    return bm, loops


# 计算 closed boundary loop 的 normalized arc-length 参数。
# loop: 有序 BMVert 序列。
def _normalized_loop_parameters(loop):
    lengths = [(loop[(index + 1) % len(loop)].co - vertex.co).length for index, vertex in enumerate(loop)]
    total = sum(lengths)
    if total <= 1.0e-10:
        return [0.0 for _ in loop]
    parameters = []
    cumulative = 0.0
    for length in lengths:
        parameters.append(cumulative / total)
        cumulative += length
    return parameters


# 选择 loop B 的方向和 cyclic offset，使两 rail 的距离与 tangent twist 最小。
# loop_a/loop_b: 待配对的两个 closed boundary loops。
def _align_loops(loop_a, loop_b):
    parameters_a = _normalized_loop_parameters(loop_a)
    best = None
    for candidate in (list(loop_b), list(reversed(loop_b))):
        for offset in range(len(candidate)):
            rotated = candidate[offset:] + candidate[:offset]
            parameters_b = _normalized_loop_parameters(rotated)
            cost = 0.0
            for index_a, parameter in enumerate(parameters_a):
                index_b = min(range(len(rotated)), key=lambda index: abs(parameters_b[index] - parameter))
                cost += (loop_a[index_a].co - rotated[index_b].co).length_squared
            if best is None or cost < best[0]:
                best = (cost, rotated)
    return best[1]


# 以 normalized arc-length zipper 在两条 rail 间生成单 span Regular Strip。
# bm: 目标 BMesh；loop_a/loop_b: rail loops；返回新 Face 列表。
def _zipper_bridge(bm, loop_a, loop_b):
    loop_b = _align_loops(loop_a, loop_b)
    count_a = len(loop_a)
    count_b = len(loop_b)
    parameters_a = _normalized_loop_parameters(loop_a) + [1.0]
    parameters_b = _normalized_loop_parameters(loop_b) + [1.0]
    index_a = 0
    index_b = 0
    new_faces = []
    skipped_zero_area_faces = 0
    while index_a < count_a or index_b < count_b:
        next_a = parameters_a[index_a + 1]
        next_b = parameters_b[index_b + 1]
        current_a = loop_a[index_a % count_a]
        current_b = loop_b[index_b % count_b]
        if abs(next_a - next_b) <= 1.0e-9:
            vertices = (current_a, loop_a[(index_a + 1) % count_a], loop_b[(index_b + 1) % count_b], current_b)
            index_a += 1
            index_b += 1
        elif next_a < next_b:
            vertices = (current_a, loop_a[(index_a + 1) % count_a], current_b)
            index_a += 1
        else:
            vertices = (current_a, loop_b[(index_b + 1) % count_b], current_b)
            index_b += 1
        if len(set(vertices)) != len(vertices):
            raise ValueError("Regular Strip produced a repeated-vertex Face")
        face = bm.faces.new(vertices)
        if face.calc_area() <= 1.0e-12:
            bm.faces.remove(face)
            skipped_zero_area_faces += 1
            continue
        new_faces.append(face)
    if not new_faces or skipped_zero_area_faces > max(2, len(new_faces) // 10):
        raise ValueError(
            f"Regular Strip degenerate correspondence: faces={len(new_faces)}, skipped={skipped_zero_area_faces}"
        )
    return new_faces


# 在两条 open Rail 上求单调 correspondence，并返回与 BMesh 无关的 Strip topology。
# rail_a/rail_b: 已验收且有序的 Rail 坐标；terminal_constraints: 可选 endpoint 与 signed width 约束。
def build_chamfer_strip(
    rail_a,
    rail_b,
    terminal_constraints=None,
):
    if len(rail_a) < 2 or len(rail_b) < 2:
        raise ValueError("Open Rail pair requires at least two vertices per side")
    coordinates_a = [vertex.co.copy() if hasattr(vertex, "co") else Vector(vertex) for vertex in rail_a]
    coordinates_b = [vertex.co.copy() if hasattr(vertex, "co") else Vector(vertex) for vertex in rail_b]
    parameters_a = _coordinate_parameters(coordinates_a, False)
    parameters_b = _coordinate_parameters(coordinates_b, False)
    constraints = terminal_constraints or {}
    expected_width = constraints.get("expected_width")
    maximum_width_error = constraints.get("maximum_width_error")
    endpoint_width = (
        (coordinates_a[0] - coordinates_b[0]).length
        + (coordinates_a[-1] - coordinates_b[-1]).length
    ) * 0.5
    width_scale = max(float(expected_width or endpoint_width), 1.0e-12)
    required_start = tuple(constraints.get("start_pairs", [(0, 0)])[0])
    required_end = tuple(
        constraints.get(
            "end_pairs",
            [(len(coordinates_a) - 1, len(coordinates_b) - 1)],
        )[-1]
    )
    if required_start != (0, 0) or required_end != (
        len(coordinates_a) - 1,
        len(coordinates_b) - 1,
    ):
        raise ValueError("Terminal constraint must bind both open Rail endpoints")

    costs = {(0, 0): 0.0}
    predecessors = {}
    for index_a in range(len(coordinates_a)):
        for index_b in range(len(coordinates_b)):
            if (index_a, index_b) == (0, 0):
                continue
            best = None
            for delta_a, delta_b in ((1, 0), (0, 1), (1, 1)):
                previous = (index_a - delta_a, index_b - delta_b)
                if previous not in costs:
                    continue
                width = (coordinates_a[index_a] - coordinates_b[index_b]).length
                width_error = (
                    abs(width - expected_width)
                    if expected_width is not None
                    else width
                )
                width_cost = width_error / width_scale
                parameter_error = abs(parameters_a[index_a] - parameters_b[index_b])
                if delta_a and delta_b:
                    tangent_a = coordinates_a[index_a] - coordinates_a[index_a - 1]
                    tangent_b = coordinates_b[index_b] - coordinates_b[index_b - 1]
                    tangent_cost = 0.0
                    if tangent_a.length > 1.0e-12 and tangent_b.length > 1.0e-12:
                        tangent_cost = 1.0 - abs(tangent_a.normalized().dot(tangent_b.normalized()))
                else:
                    tangent_cost = 0.25
                step_cost = width_cost + parameter_error + tangent_cost
                candidate = (costs[previous] + step_cost, previous)
                if best is None or candidate < best:
                    best = candidate
            if best is None:
                raise ValueError("Regular Strip has no monotonic correspondence path")
            costs[(index_a, index_b)] = best[0]
            predecessors[(index_a, index_b)] = best[1]

    path = [required_end]
    while path[-1] != required_start:
        path.append(predecessors[path[-1]])
    path.reverse()
    faces = []
    for current, following in zip(path, path[1:]):
        index_a, index_b = current
        next_a, next_b = following
        if next_a > index_a and next_b > index_b:
            faces.append((("A", index_a), ("A", next_a), ("B", next_b), ("B", index_b)))
        elif next_a > index_a:
            faces.append((("A", index_a), ("A", next_a), ("B", index_b)))
        else:
            faces.append((("A", index_a), ("B", next_b), ("B", index_b)))
    widths = []
    width_errors = []
    relative_advances = []
    for path_index, (index_a, index_b) in enumerate(path):
        width = (coordinates_a[index_a] - coordinates_b[index_b]).length
        widths.append(width)
        if expected_width is None:
            continue
        if path_index == 0:
            allowed_longitudinal_advance = 0.0
            relative_advance = 0.0
        else:
            previous_a, previous_b = path[path_index - 1]
            advance_a = (coordinates_a[index_a] - coordinates_a[previous_a]).length
            advance_b = (coordinates_b[index_b] - coordinates_b[previous_b]).length
            allowed_longitudinal_advance = max(advance_a, advance_b)
            relative_advance = abs(advance_a - advance_b)
        relative_advances.append(relative_advance)
        width_errors.append(
            max(
                0.0,
                expected_width - width,
                width - expected_width - allowed_longitudinal_advance,
            )
        )
    reasons = []
    width_error_inlier_ratio = (
        sum(error <= maximum_width_error for error in width_errors) / len(width_errors)
        if maximum_width_error is not None and width_errors
        else 1.0
    )
    maximum_relative_advance = max(relative_advances, default=0.0)
    maximum_relative_advance_limit = (
        expected_width * 8.0
        if expected_width is not None
        else float("inf")
    )
    if (
        maximum_width_error is not None
        and (
            width_error_inlier_ratio < 0.95
            or maximum_relative_advance > maximum_relative_advance_limit
        )
    ):
        reasons.append("SIGNED_STRIP_WIDTH_EXCEEDED")
    return {
        "faces": faces,
        "path": path,
        "diagnostics": {
            "status": "PASS" if not reasons else "FAIL",
            "reasons": reasons,
            "monotonic": all(
                next_a >= index_a
                and next_b >= index_b
                and (next_a > index_a or next_b > index_b)
                for (index_a, index_b), (next_a, next_b) in zip(path, path[1:])
            ),
            "cost": costs[required_end],
            "expected_width": expected_width,
            "maximum_width_error": max(width_errors, default=0.0),
            "width_error_inlier_ratio": width_error_inlier_ratio,
            "maximum_raw_width_error": max(
                (abs(width - expected_width) for width in widths),
                default=0.0,
            ) if expected_width is not None else 0.0,
            "maximum_relative_advance": maximum_relative_advance,
            "maximum_relative_advance_limit": maximum_relative_advance_limit,
            "one_sided_step_count": sum(
                (next_a == index_a) != (next_b == index_b)
                for (index_a, index_b), (next_a, next_b) in zip(path, path[1:])
            ),
        },
    }


# 按 arc-length zipper 连接两条 open Rail，并保留末端作为 Junction/terminal port。
# bm/vertices_a/vertices_b: 当前 BMesh 与两侧有序 Boundary vertices；返回新 Faces。
def _zipper_bridge_open(
    bm,
    vertices_a,
    vertices_b,
    expected_width=None,
    maximum_width_error=None,
):
    strip = build_chamfer_strip(
        vertices_a,
        vertices_b,
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(len(vertices_a) - 1, len(vertices_b) - 1)],
            "expected_width": expected_width,
            "maximum_width_error": maximum_width_error,
        },
    )
    if strip["diagnostics"]["status"] != "PASS":
        raise ValueError(
            "Open Rail correspondence guard failed: "
            + ", ".join(strip["diagnostics"]["reasons"])
        )
    new_faces = []
    for face_indices in strip["faces"]:
        vertices = tuple(
            vertices_a[index] if side == "A" else vertices_b[index]
            for side, index in face_indices
        )
        unique_vertices = []
        for vertex in vertices:
            if not unique_vertices or vertex is not unique_vertices[-1]:
                unique_vertices.append(vertex)
        if len(unique_vertices) > 2 and unique_vertices[0] is unique_vertices[-1]:
            unique_vertices.pop()
        vertices = tuple(unique_vertices)
        if len(vertices) < 3:
            continue
        if len(set(vertices)) != len(vertices):
            raise ValueError("Open Rail zipper produced a repeated-vertex Face")
        face = bm.faces.new(vertices)
        if face.calc_area() <= 1.0e-12:
            bm.faces.remove(face)
            continue
        new_faces.append(face)
    _validate_chamfer_strip_faces(new_faces)
    return new_faces


# 验证新建 Strip Faces 不含 zero-length Edge。
# faces: 同一 open Rail pair 新建的有序 Faces；校验失败时抛出 ValueError。
def _validate_chamfer_strip_faces(faces):
    for face in faces:
        face.normal_update()
        edge_lengths = [edge.calc_length() for edge in face.edges]
        minimum_edge = min(edge_lengths, default=0.0)
        if minimum_edge <= 1.0e-12:
            raise ValueError("Open Rail zipper produced a zero-length Face edge")


# 用 constrained Delaunay triangulation 补单个 Junction boundary；复用所有 boundary 3D 点。
# bm: 目标 BMesh；loop: Junction boundary；返回新 Triangle Face 列表。
def _triangulate_junction_loop(bm, loop):
    center = sum((vertex.co for vertex in loop), Vector()) / len(loop)
    normal = Vector()
    for index, vertex in enumerate(loop):
        normal += (vertex.co - center).cross(loop[(index + 1) % len(loop)].co - center)
    if normal.length <= 1.0e-8:
        raise ValueError("Junction boundary has no stable best-fit plane")
    normal.normalize()
    axis_x = (loop[0].co - center).normalized()
    axis_y = normal.cross(axis_x).normalized()
    points_2d = [Vector(((vertex.co - center).dot(axis_x), (vertex.co - center).dot(axis_y))) for vertex in loop]
    constraint_edges = [(index, (index + 1) % len(loop)) for index in range(len(loop))]
    _, _, triangles, _, _, _ = geometry.delaunay_2d_cdt(
        points_2d,
        constraint_edges,
        [list(range(len(loop)))],
        1,
        1.0e-7,
        True,
    )
    if not triangles:
        raise ValueError("Constrained triangulation returned no Junction Faces")
    new_faces = []
    for triangle in triangles:
        if len(triangle) != 3 or any(index >= len(loop) for index in triangle):
            raise ValueError("Constrained triangulation inserted unsupported interior vertices")
        vertices = tuple(loop[index] for index in triangle)
        face = bm.faces.new(vertices)
        if face.calc_area() <= 1.0e-12:
            bm.faces.remove(face)
            continue
        new_faces.append(face)
    if not new_faces:
        raise ValueError("Junction Patch produced no non-zero-area Faces")
    return new_faces


# 把一组 degree-2/degree-1 Boundary Edges 拆成有序的 open/cyclic edge chains。
# edges: 同一 Pipe、同一 source Surface Patch 上的 Boundary Edges；返回 chain records。
def _ordered_edge_chains(edges):
    remaining = set(edges)
    chains = []
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        component = {seed}
        stack = [seed]
        remaining.remove(seed)
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in vertex.link_edges:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        adjacency = {}
        for edge in component:
            for vertex in edge.verts:
                adjacency.setdefault(vertex, []).append(edge)
        endpoints = sorted(
            (vertex for vertex, linked in adjacency.items() if len(linked) == 1),
            key=lambda vertex: vertex.index,
        )
        cyclic = not endpoints and all(len(linked) == 2 for linked in adjacency.values())
        if not cyclic and len(endpoints) != 2:
            continue
        start = endpoints[0] if endpoints else min(adjacency, key=lambda vertex: vertex.index)
        ordered_edges = []
        ordered_vertices = [start]
        current = start
        previous = None
        while len(ordered_edges) < len(component):
            next_edge = next(
                (
                    edge
                    for edge in sorted(adjacency[current], key=lambda item: item.index)
                    if edge is not previous and edge not in ordered_edges
                ),
                None,
            )
            if next_edge is None:
                break
            ordered_edges.append(next_edge)
            current = next_edge.other_vert(current)
            previous = next_edge
            if current is start:
                break
            ordered_vertices.append(current)
        if len(ordered_edges) == len(component):
            chains.append(
                {
                    "edges": ordered_edges,
                    "vertices": ordered_vertices,
                    "is_cyclic": cyclic,
                }
            )
    return chains


# 返回 Pipe Mesh 的 local-space axis-aligned bounds，供空间查询 broad phase 使用。
# pipe: Pipe Mesh Object；返回 (minimum, maximum)。
def _pipe_bounds(pipe):
    points = [vertex.co for vertex in pipe.data.vertices]
    return (
        Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points))),
        Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points))),
    )


# 判断两个扩张后的 axis-aligned bounds 是否可能 overlap。
# bounds_a/b: (minimum, maximum)；margin: 扩张距离。
def _bounds_overlap(bounds_a, bounds_b, margin=0.0):
    minimum_a, maximum_a = bounds_a
    minimum_b, maximum_b = bounds_b
    return all(
        maximum_a[axis] + margin >= minimum_b[axis]
        and maximum_b[axis] + margin >= minimum_a[axis]
        for axis in range(3)
    )


# 返回 Boundary Edge 落在 Pipe surface tolerance 内的候选 owner，按最近距离排序。
# edge/pipe_trees/bounds/radius: 洞口边、Pipe BVH/bounds 与 Chamfer radius；返回 (distance, pipe_id)。
def _boundary_edge_pipe_candidates(edge, pipe_trees, pipe_bounds, radius):
    center = (edge.verts[0].co + edge.verts[1].co) * 0.5
    distances = []
    surface_tolerance = max(radius * 0.12, 1.0e-6)
    for pipe_id, (tree, bounds) in enumerate(zip(pipe_trees, pipe_bounds)):
        minimum, maximum = bounds
        if any(
            center[axis] < minimum[axis] - surface_tolerance
            or center[axis] > maximum[axis] + surface_tolerance
            for axis in range(3)
        ):
            continue
        nearest = tree.find_nearest(center)
        if nearest is not None and nearest[3] is not None:
            distances.append((nearest[3], pipe_id))
    if not distances:
        return []
    distances.sort()
    minimum_distance = distances[0][0]
    if minimum_distance > surface_tolerance:
        return []
    owner_tolerance = max(radius * 0.025, 1.0e-7)
    return [
        (distance, pipe_id)
        for distance, pipe_id in distances
        if distance <= minimum_distance + owner_tolerance
    ]


# 以 Pipe BVH 最近距离给 Boundary Edge 分配唯一 Pipe；Pipe overlap 区域保持未分配。
# edge: open Boundary Edge；pipe_trees/bounds: Pipe spatial index；radius: Pipe 半径。
def _boundary_edge_pipe_owner(edge, pipe_trees, pipe_bounds, radius):
    candidates = _boundary_edge_pipe_candidates(
        edge,
        pipe_trees,
        pipe_bounds,
        radius,
    )
    return candidates[0][1] if len(candidates) == 1 else None


# 为同一 Pipe 的两个 source Surface Patch 收集连续 Boundary rail chains。
# bm/groups/pipe_trees/radius: 当前补面上下文；返回 pipe_id -> patch_id -> chains。
def _pipe_boundary_rails(bm, groups, pipe_trees, pipe_bounds, radius):
    rails, _ = _final_boolean_boundary_rails(
        bm,
        groups,
        pipe_trees,
        pipe_bounds,
        radius,
    )
    return rails


# 序列化一条完全由最终 Boolean Boundary Edges 组成的 Rail chain。
# chain/pipe_id/patch_id: 原始 BMesh chain、Cutter Pipe owner 与 source Surface Patch owner。
def _serialize_boundary_rail_chain(chain, pipe_id, patch_id):
    return {
        "pipe_id": pipe_id,
        "patch_id": patch_id,
        "coordinates": [tuple(vertex.co) for vertex in chain["vertices"]],
        "vertex_indices": [vertex.index for vertex in chain["vertices"]],
        "edge_indices": [edge.index for edge in chain["edges"]],
        "is_cyclic": bool(chain["is_cyclic"]),
    }


# 只沿最终 Boolean 洞口的原始 Boundary Edge adjacency 提取 Rail，不排序或插值坐标。
# bm/groups/pipe_trees/bounds/radius: OPEN_BOUNDARY BMesh、Feature groups 与 Cutter Pipe spatial index。
def _final_boolean_boundary_rails(bm, groups, pipe_trees, pipe_bounds, radius):
    patch_layer = bm.faces.layers.int.get(SOURCE_PATCH_ID_ATTRIBUTE)
    group_by_pipe = {group["pipe_id"]: group for group in groups}
    allowed_patches = {
        group["pipe_id"]: {
            patch_id
            for patch_pair in group["patch_pair_by_edge"]
            for patch_id in patch_pair
        }
        for group in groups
    }
    boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    boundary_edge_set = set(boundary_edges)
    edges_by_key = {}
    edge_owners = {}
    unowned_edges = {}
    if patch_layer is None:
        unowned_edges = {
            edge: "SOURCE_PATCH_LAYER_MISSING"
            for edge in boundary_edges
        }
    else:
        for edge in boundary_edges:
            patch_id = int(edge.link_faces[0][patch_layer])
            candidates = _boundary_edge_pipe_candidates(
                edge,
                pipe_trees,
                pipe_bounds,
                radius,
            )
            compatible_candidates = [
                (distance, pipe_id)
                for distance, pipe_id in candidates
                if (
                    pipe_id in group_by_pipe
                    and patch_id in allowed_patches[pipe_id]
                )
            ]
            if len(compatible_candidates) == 1:
                pipe_id = compatible_candidates[0][1]
                edge_owners[edge] = (pipe_id, patch_id)
                edges_by_key.setdefault((pipe_id, patch_id), []).append(edge)
                continue
            if not candidates:
                unowned_edges[edge] = "PIPE_OWNER_UNKNOWN"
            elif not compatible_candidates:
                unowned_edges[edge] = "PATCH_OWNER_MISMATCH"
            else:
                unowned_edges[edge] = "PIPE_OWNER_AMBIGUOUS"

        # 仅沿同一 Surface Patch 的 Boundary adjacency 传播唯一 Pipe owner。
        # 模糊 edge 两端若只接触同一已知 owner，继承该 owner；junction 多 owner 保持未解决。
        pending_edges = set(unowned_edges)
        propagated_edge_count = 0
        while pending_edges:
            resolved_edges = []
            for edge in pending_edges:
                patch_id = int(edge.link_faces[0][patch_layer])
                adjacent_owners = {
                    owner
                    for vertex in edge.verts
                    for neighbor in vertex.link_edges
                    if neighbor in boundary_edge_set
                    for owner in [edge_owners.get(neighbor)]
                    if owner is not None and owner[1] == patch_id
                }
                adjacent_pipe_ids = {
                    pipe_id
                    for pipe_id, _ in adjacent_owners
                    if patch_id in allowed_patches[pipe_id]
                }
                if len(adjacent_pipe_ids) != 1:
                    continue
                pipe_id = next(iter(adjacent_pipe_ids))
                edge_owners[edge] = (pipe_id, patch_id)
                edges_by_key.setdefault((pipe_id, patch_id), []).append(edge)
                resolved_edges.append(edge)
            if not resolved_edges:
                break
            propagated_edge_count += len(resolved_edges)
            pending_edges.difference_update(resolved_edges)
            for edge in resolved_edges:
                unowned_edges.pop(edge, None)

        # 同一 Surface Patch 上的剩余连通 component 若邻接唯一 owner，则整体继承。
        # component 若接触多个 owner，视为真实 junction，继续保持未解决。
        remaining = set(unowned_edges)
        while remaining:
            seed = remaining.pop()
            component = {seed}
            stack = [seed]
            while stack:
                current = stack.pop()
                patch_id = int(current.link_faces[0][patch_layer])
                for vertex in current.verts:
                    for neighbor in vertex.link_edges:
                        if neighbor not in remaining:
                            continue
                        if int(neighbor.link_faces[0][patch_layer]) != patch_id:
                            continue
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
            patch_id = int(seed.link_faces[0][patch_layer])
            adjacent_pipe_ids = {
                owner[0]
                for edge in component
                for vertex in edge.verts
                for neighbor in vertex.link_edges
                if neighbor in boundary_edge_set and neighbor not in component
                for owner in [edge_owners.get(neighbor)]
                if owner is not None and owner[1] == patch_id
            }
            if len(adjacent_pipe_ids) != 1:
                continue
            pipe_id = next(iter(adjacent_pipe_ids))
            for edge in component:
                edge_owners[edge] = (pipe_id, patch_id)
                edges_by_key.setdefault((pipe_id, patch_id), []).append(edge)
                unowned_edges.pop(edge, None)
            propagated_edge_count += len(component)

    # Junction overlap 上的 Boundary Edge 允许保留多个明确 owner，不强行猜成单一 Pipe。
    # 共享 edge 仍只引用最终 Boolean 原始拓扑，并分别进入兼容 Pipe/Patch 的 Rail adjacency。
    shared_edge_owners = {}
    if patch_layer is not None:
        for edge in list(unowned_edges):
            patch_id = int(edge.link_faces[0][patch_layer])
            candidate_pipe_ids = {
                pipe_id
                for _, pipe_id in _boundary_edge_pipe_candidates(
                    edge,
                    pipe_trees,
                    pipe_bounds,
                    radius,
                )
            }
            adjacent_pipe_ids = {
                owner[0]
                for vertex in edge.verts
                for neighbor in vertex.link_edges
                if neighbor in boundary_edge_set
                for owner in [edge_owners.get(neighbor)]
                if owner is not None
            }
            compatible_pipe_ids = sorted(
                pipe_id
                for pipe_id in candidate_pipe_ids | adjacent_pipe_ids
                if (
                    pipe_id in allowed_patches
                    and patch_id in allowed_patches[pipe_id]
                )
            )
            if len(compatible_pipe_ids) < 2:
                continue
            shared_edge_owners[edge] = [
                (pipe_id, patch_id)
                for pipe_id in compatible_pipe_ids
            ]
            for pipe_id in compatible_pipe_ids:
                edges_by_key.setdefault((pipe_id, patch_id), []).append(edge)
            unowned_edges.pop(edge, None)

    rails = {}
    owned_chains = []
    owned_edges = set()
    for (pipe_id, patch_id), edges in sorted(edges_by_key.items()):
        chains = _ordered_edge_chains(edges)
        rails.setdefault(pipe_id, {})[patch_id] = chains
        chained_edges = set()
        for chain in chains:
            chained_edges.update(chain["edges"])
            owned_edges.update(chain["edges"])
            owned_chains.append(
                _serialize_boundary_rail_chain(chain, pipe_id, patch_id)
            )
        for edge in set(edges) - chained_edges:
            unowned_edges[edge] = "NON_CHAIN_BOUNDARY_COMPONENT"

    shared_owner_rails = [
        {
            "edge_index": edge.index,
            "vertex_indices": [vertex.index for vertex in edge.verts],
            "coordinates": [tuple(vertex.co) for vertex in edge.verts],
            "owner_pairs": [list(owner) for owner in owners],
            "region_class": "MULTI_OWNER_RAIL",
        }
        for edge, owners in sorted(
            shared_edge_owners.items(),
            key=lambda item: item[0].index,
        )
    ]
    owned_edges.update(shared_edge_owners)
    deferred_segments = []
    regular_unowned_segments = []
    for edge, reason in sorted(
        unowned_edges.items(),
        key=lambda item: item[0].index,
    ):
        candidate_pipe_ids = {
            pipe_id
            for _, pipe_id in _boundary_edge_pipe_candidates(
                edge,
                pipe_trees,
                pipe_bounds,
                radius,
            )
        }
        adjacent_pipe_ids = {
            owner[0]
            for vertex in edge.verts
            for neighbor in vertex.link_edges
            if neighbor in boundary_edge_set
            for owner in [edge_owners.get(neighbor)]
            if owner is not None
        }
        related_pipe_ids = candidate_pipe_ids | adjacent_pipe_ids
        is_deferred = (
            len(related_pipe_ids) != 1
            or reason in {"PIPE_OWNER_AMBIGUOUS", "PATCH_OWNER_MISMATCH"}
        )
        segment = {
            "edge_index": edge.index,
            "coordinates": [tuple(vertex.co) for vertex in edge.verts],
            "reason": reason,
            "related_pipe_ids": sorted(related_pipe_ids),
        }
        if is_deferred:
            segment["region_class"] = "JUNCTION_OR_TERMINAL_DEFERRED"
            deferred_segments.append(segment)
        else:
            segment["region_class"] = "REGULAR_UNOWNED"
            regular_unowned_segments.append(segment)
    unowned_segments = regular_unowned_segments + deferred_segments
    serialized_edge_count = len(owned_edges) + len(unowned_segments)
    shared_owner_segments = shared_owner_rails
    zero_length_edge_indices = sorted(
        edge.index
        for edge in boundary_edges
        if (edge.verts[1].co - edge.verts[0].co).length <= 1.0e-9
    )
    boundary_edge_count = len(boundary_edges)
    topology = {
        "backend": "FINAL_BOOLEAN_BOUNDARY_ADJACENCY",
        "ownership_backend": "CUTTER_PIPE_SURFACE_BVH",
        "boundary_edge_count": boundary_edge_count,
        "owned_edge_count": len(owned_edges),
        "single_owner_edge_count": len(owned_edges - set(shared_edge_owners)),
        "shared_owner_edge_count": len(shared_owner_segments),
        "unowned_edge_count": len(regular_unowned_segments),
        "deferred_edge_count": len(deferred_segments),
        "adjacency_propagated_edge_count": (
            propagated_edge_count if patch_layer is not None else 0
        ),
        "ownership_coverage": (
            len(owned_edges) / boundary_edge_count
            if boundary_edge_count
            else 0.0
        ),
        "owned_chains": owned_chains,
        "shared_owner_rails": shared_owner_rails,
        "shared_owner_segments": shared_owner_segments,
        "zero_length_edge_indices": zero_length_edge_indices,
        "unowned_segments": regular_unowned_segments,
        "deferred_segments": deferred_segments,
        "adjacency_guard": {
            "status": (
                "PASS"
                if serialized_edge_count == boundary_edge_count
                else "FAIL"
            ),
            "serialized_edge_count": serialized_edge_count,
            "zero_length_edge_count": len(zero_length_edge_indices),
            "zero_length_edge_indices": zero_length_edge_indices,
            "consumable_rail_guard": (
                "PASS" if not zero_length_edge_indices else "FAIL"
            ),
            "coordinate_reconstruction": False,
            "centerline_sorting": False,
        },
    }
    return rails, topology


# 为每根正式 Cutter Pipe 单独执行 Difference，并以 Boolean 生成槽面邻接关系提取真实交线。
# source_object/groups/pipes/radius: 原 Mesh、Feature groups、正式四边 Cutter Pipes 与 radius；返回 Pipe/Patch rails。
def _cutter_intersection_rails(source_object, groups, pipes, radius):
    del radius
    source_patch_ids = _source_face_patch_ids(source_object)
    group_by_pipe = {group["pipe_id"]: group for group in groups}
    rails = {}
    diagnostics = []
    for pipe in pipes:
        pipe_id = int(pipe[PIPE_ID_TAG])
        group = group_by_pipe[pipe_id]
        probe_mesh = source_object.data.copy()
        probe = bpy.data.objects.new(
            f"{source_object.name}_RailIntersectionProbe_{pipe_id}",
            probe_mesh,
        )
        probe.matrix_world = source_object.matrix_world.copy()
        bpy.context.scene.collection.objects.link(probe)
        try:
            _mark_original_faces(probe, source_patch_ids)
            modifier = probe.modifiers.new("HST Rail Intersection Difference", type="BOOLEAN")
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.operand_type = "OBJECT"
            modifier.object = pipe
            with bpy.context.temp_override(
                object=probe,
                active_object=probe,
                selected_objects=[probe],
                selected_editable_objects=[probe],
            ):
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            probe_bmesh = bmesh.new()
            probe_bmesh.from_mesh(probe.data)
            probe_bmesh.edges.ensure_lookup_table()
            probe_bmesh.faces.ensure_lookup_table()
            original_layer = probe_bmesh.faces.layers.int.get(ORIGINAL_FACE_ATTRIBUTE)
            if original_layer is None:
                original_layer = probe_bmesh.faces.layers.bool.get(ORIGINAL_FACE_ATTRIBUTE)
            patch_layer = probe_bmesh.faces.layers.int.get(SOURCE_PATCH_ID_ATTRIBUTE)
            if original_layer is None or patch_layer is None:
                probe_bmesh.free()
                continue
            edges_by_patch = {}
            for edge in probe_bmesh.edges:
                original_faces = [face for face in edge.link_faces if bool(face[original_layer])]
                cutter_faces = [face for face in edge.link_faces if not bool(face[original_layer])]
                if len(original_faces) != 1 or not cutter_faces:
                    continue
                patch_id = original_faces[0][patch_layer]
                if patch_id not in group["patch_pair"]:
                    continue
                edges_by_patch.setdefault(patch_id, []).append(edge)
            for patch_id, edges in edges_by_patch.items():
                rails.setdefault(pipe_id, {})[patch_id] = [
                    {
                        "coordinates": [vertex.co.copy() for vertex in chain["vertices"]],
                        "is_cyclic": chain["is_cyclic"],
                    }
                    for chain in _ordered_edge_chains(edges)
                ]
            diagnostics.append(
                {
                    "pipe_id": pipe_id,
                    "patch_edge_counts": {
                        patch_id: len(edges)
                        for patch_id, edges in edges_by_patch.items()
                    },
                }
            )
            probe_bmesh.free()
        finally:
            bpy.data.objects.remove(probe, do_unlink=True)
            if probe_mesh.users == 0:
                bpy.data.meshes.remove(probe_mesh)
    return rails, diagnostics


# 计算两个 open/cyclic rail chains 的配对成本；成本主要取端点距离和中心距离。
# chain_a/chain_b: 同一 Pipe 两侧的候选 rail chain；返回可排序 score。
def _rail_pair_score(chain_a, chain_b):
    coordinates_a = chain_a.get("coordinates") or [vertex.co for vertex in chain_a["vertices"]]
    coordinates_b = chain_b.get("coordinates") or [vertex.co for vertex in chain_b["vertices"]]
    center_a = sum(coordinates_a, Vector()) / len(coordinates_a)
    center_b = sum(coordinates_b, Vector()) / len(coordinates_b)
    count_ratio = max(len(coordinates_a), len(coordinates_b)) / min(len(coordinates_a), len(coordinates_b))
    if chain_a["is_cyclic"] or chain_b["is_cyclic"]:
        endpoint_cost = (center_a - center_b).length
    else:
        direct = (
            (coordinates_a[0] - coordinates_b[0]).length
            + (coordinates_a[-1] - coordinates_b[-1]).length
        ) * 0.5
        reversed_cost = (
            (coordinates_a[0] - coordinates_b[-1]).length
            + (coordinates_a[-1] - coordinates_b[0]).length
        ) * 0.5
        endpoint_cost = min(direct, reversed_cost)
    return endpoint_cost + (center_a - center_b).length * 0.25 + abs(math.log(count_ratio))


# 返回 open/cyclic coordinates 的 normalized arc-length u。
# coordinates/cyclic: 有序坐标与闭环标记；返回与 coordinates 等长的参数。
def _coordinate_parameters(coordinates, cyclic):
    segment_count = len(coordinates) if cyclic else len(coordinates) - 1
    lengths = [
        (
            coordinates[(index + 1) % len(coordinates)]
            - coordinates[index]
        ).length
        for index in range(segment_count)
    ]
    total = sum(lengths)
    cumulative = 0.0
    parameters = []
    for index in range(len(coordinates)):
        parameters.append(cumulative / total if total > 1.0e-10 else 0.0)
        if index < len(lengths):
            cumulative += lengths[index]
    return parameters


# 返回 open/cyclic rail 的 normalized arc-length u。
# vertices/cyclic: 有序 rail vertices 与闭环标记；返回与 vertices 等长的参数。
def _rail_parameters(vertices, cyclic):
    return _coordinate_parameters(
        [vertex.co if hasattr(vertex, "co") else vertex for vertex in vertices],
        cyclic,
    )


# 返回点到 CutterStrand polyline 的最短距离。
# point/group: 查询点与含 ordered points/cyclic 的 Feature group。
def _point_to_feature_group_distance(point, group):
    points = group["points"]
    segment_count = len(points) if group["is_cyclic"] else len(points) - 1
    distances = []
    for index in range(segment_count):
        start = points[index]
        end = points[(index + 1) % len(points)]
        closest, factor = geometry.intersect_point_line(point, start, end)
        if factor < 0.0:
            closest = start
        elif factor > 1.0:
            closest = end
        distances.append((point - closest).length)
    return min(distances)


# 统计 3D polyline 的非相邻 segment 自交数量。
# coordinates/cyclic/tolerance: 有序点、闭环标记与几何距离容差。
def _polyline_self_intersection_count(coordinates, cyclic, tolerance):
    if len(coordinates) < 4:
        return 0
    segment_count = len(coordinates) if cyclic else len(coordinates) - 1
    intersection_count = 0
    for first_index in range(segment_count):
        first_start = coordinates[first_index]
        first_end = coordinates[(first_index + 1) % len(coordinates)]
        for second_index in range(first_index + 1, segment_count):
            if second_index == first_index + 1:
                continue
            if cyclic and first_index == 0 and second_index == segment_count - 1:
                continue
            second_start = coordinates[second_index]
            second_end = coordinates[(second_index + 1) % len(coordinates)]
            closest = geometry.intersect_line_line(
                first_start,
                first_end,
                second_start,
                second_end,
            )
            if closest is None or (closest[0] - closest[1]).length > tolerance:
                continue
            midpoint = (closest[0] + closest[1]) * 0.5
            _, first_factor = geometry.intersect_point_line(
                midpoint,
                first_start,
                first_end,
            )
            _, second_factor = geometry.intersect_point_line(
                midpoint,
                second_start,
                second_end,
            )
            if (
                -1.0e-6 <= first_factor <= 1.0 + 1.0e-6
                and -1.0e-6 <= second_factor <= 1.0 + 1.0e-6
            ):
                intersection_count += 1
    return intersection_count


# 为 RailPairRecord 计算 Phase 2 的距离、顺序、自交和采样密度 guard。
# record/group/span/radius: rail record、owner Feature、ownership span 与 Chamfer radius。
def _rail_pair_geometry_guard(record, group, span, radius):
    left = [Vector(point) for point in record["rail_left"]]
    right = [Vector(point) for point in record["rail_right"]]
    cyclic = record["cyclic"]
    tolerance = max(radius * 0.05, 1.0e-5)
    intersection_tolerance = max(radius * 1.0e-4, 1.0e-7)
    left_lengths = [
        (left[(index + 1) % len(left)] - left[index]).length
        for index in range(len(left) if cyclic else len(left) - 1)
    ]
    right_lengths = [
        (right[(index + 1) % len(right)] - right[index]).length
        for index in range(len(right) if cyclic else len(right) - 1)
    ]
    u = record["u"]
    u_monotonic = len(u) == len(left) and all(
        right_parameter - left_parameter > 1.0e-10
        for left_parameter, right_parameter in zip(u, u[1:])
    )
    if record.get("backend") == "BOOLEAN_INTERSECTION_ORACLE":
        u_monotonic = True
    left_cyclic = bool(record.get("left_cyclic", cyclic))
    right_cyclic = bool(record.get("right_cyclic", cyclic))
    self_intersection_count = (
        _polyline_self_intersection_count(
            left,
            left_cyclic,
            intersection_tolerance,
        )
        + _polyline_self_intersection_count(
            right,
            right_cyclic,
            intersection_tolerance,
        )
    )
    max_width_error = max(record["width_error"], default=float("inf"))
    correspondence_widths = record.get("correspondence_width", [])
    expected_correspondence_width = radius * math.sqrt(2.0)
    correspondence_tolerance = max(radius * 0.60, 1.0e-5)
    correspondence_errors = sorted(
        abs(
            _point_to_rail_distance(
                left_coordinate,
                right,
                right_cyclic,
            )
            - expected_correspondence_width
        )
        for left_coordinate in left
    )
    correspondence_percentile_index = max(
        0,
        math.ceil(len(correspondence_errors) * 0.95) - 1,
    )
    max_correspondence_error = (
        correspondence_errors[correspondence_percentile_index]
        if correspondence_errors
        else float("inf")
    )
    correspondence_inlier_count = sum(
        error <= correspondence_tolerance
        for error in correspondence_errors
    )
    correspondence_inlier_ratio = (
        correspondence_inlier_count / len(correspondence_errors)
        if correspondence_errors
        else 0.0
    )
    max_projection_distance = max(record.get("projection_distance", []), default=0.0)
    max_projection_continuity_error = max(
        record.get("projection_continuity_error", []),
        default=0.0,
    )
    max_edge_length = max(left_lengths + right_lengths, default=0.0)
    reasons = []
    if record["ownership_confidence"] < 1.0:
        reasons.append("AMBIGUOUS_OWNER")
    if not u_monotonic:
        reasons.append("NON_MONOTONIC_U")
    if (
        self_intersection_count
        and not cyclic
        and record.get("backend") != "BOOLEAN_INTERSECTION_ORACLE"
    ):
        reasons.append("SELF_INTERSECTION")
    if record.get("backend") == "BOOLEAN_INTERSECTION_ORACLE":
        if correspondence_inlier_ratio < 0.90:
            reasons.append("RAIL_PAIR_WIDTH_EXCEEDED")
    elif max_width_error > tolerance:
        reasons.append("RADIUS_TOLERANCE_EXCEEDED")
    if max_projection_distance > record.get("projection_limit", float("inf")):
        reasons.append("OWNER_PATCH_PROJECTION_EXCEEDED")
    if max_projection_continuity_error > record.get(
        "projection_continuity_limit",
        float("inf"),
    ):
        reasons.append("OWNER_PATCH_CONTINUITY_EXCEEDED")
    return {
        "status": "PASS" if not reasons else "FAIL",
        "reasons": reasons,
        "radius_tolerance": tolerance,
        "max_width_error": max_width_error,
        "expected_correspondence_width": expected_correspondence_width,
        "max_correspondence_error": max_correspondence_error,
        "correspondence_error_percentile": 0.95,
        "correspondence_inlier_count": correspondence_inlier_count,
        "correspondence_inlier_ratio": correspondence_inlier_ratio,
        "correspondence_inlier_ratio_limit": 0.90,
        "correspondence_tolerance": correspondence_tolerance,
        "max_projection_distance": max_projection_distance,
        "max_projection_continuity_error": max_projection_continuity_error,
        "u_monotonic": u_monotonic,
        "self_intersection_count": self_intersection_count,
        "max_edge_length": max_edge_length,
        "sampling_backend": "FINAL_BOOLEAN_BOUNDARY_EDGES",
        "owner_group_id": group["pipe_id"],
        "owner_patch_pair": span["patch_pair"],
    }

# 按 normalized u 返回目标 rail 上与 parameter 对应的 Vertex。
# vertices/parameters/parameter: rail points、u 数组与查询参数。
def _rail_vertex_at_parameter(vertices, parameters, parameter):
    return vertices[
        min(
            range(len(parameters)),
            key=lambda index: abs(parameters[index] - parameter),
        )
    ]


# 返回 point 到 polyline 的最短距离，完全基于现有 vertices，不创建新坐标。
# point/vertices/cyclic: 查询点、目标 Rail vertices 与闭环标记。
def _point_to_rail_distance(point, vertices, cyclic):
    coordinates = [
        vertex.co if hasattr(vertex, "co") else vertex
        for vertex in vertices
    ]
    segment_count = len(coordinates) if cyclic else len(coordinates) - 1
    if segment_count <= 0:
        return float("inf")
    distances = []
    for index in range(segment_count):
        start = coordinates[index]
        end = coordinates[(index + 1) % len(coordinates)]
        closest, factor = geometry.intersect_point_line(point, start, end)
        if factor < 0.0:
            closest = start
        elif factor > 1.0:
            closest = end
        distances.append((point - closest).length)
    return min(distances)


# 对齐 open/cyclic rail B 的方向和 cyclic offset，避免端点或 seam 错配。
# chain_left/right: 待配对 Boundary chains；返回 aligned right vertices 与独立 correspondence u。
def _aligned_rail_correspondence(chain_left, chain_right):
    left_vertices = chain_left.get("coordinates") or chain_left["vertices"]
    right_vertices = chain_right.get("coordinates") or chain_right["vertices"]
    candidates = []
    if chain_left["is_cyclic"] and chain_right["is_cyclic"]:
        for candidate in (list(right_vertices), list(reversed(right_vertices))):
            for offset in range(len(candidate)):
                candidates.append(candidate[offset:] + candidate[:offset])
    else:
        candidates = [list(right_vertices), list(reversed(right_vertices))]
    left_u = _rail_parameters(left_vertices, chain_left["is_cyclic"])
    best = None
    for candidate in candidates:
        candidate_u = _rail_parameters(candidate, chain_right["is_cyclic"])
        cost = sum(
            (
                (left_vertex.co if hasattr(left_vertex, "co") else left_vertex)
                - (
                    _rail_vertex_at_parameter(candidate, candidate_u, parameter).co
                    if hasattr(_rail_vertex_at_parameter(candidate, candidate_u, parameter), "co")
                    else _rail_vertex_at_parameter(candidate, candidate_u, parameter)
                )
            ).length_squared
            for left_vertex, parameter in zip(left_vertices, left_u)
        )
        if best is None or cost < best[0]:
            best = (cost, candidate, candidate_u)
    return best[1], best[2]


# 保留旧调用 seam，仅返回对齐后的 Rail B vertices。
# chain_left/right: 待配对 Boundary chains。
def _aligned_rail_vertices(chain_left, chain_right):
    return _aligned_rail_correspondence(chain_left, chain_right)[0]


# 把两条 Boundary chains 序列化为 RailPairRecord，并计算横向宽度误差。
# group/span/chain_left/right/radius: owner strand/span、两侧 rails 与目标 Pipe radius。
def _boolean_rail_pair_record(
    group,
    span,
    chain_left,
    chain_right,
    radius,
):
    left_vertices = chain_left.get("coordinates") or chain_left["vertices"]
    right_vertices, right_u = _aligned_rail_correspondence(
        chain_left,
        chain_right,
    )
    left_u = _rail_parameters(left_vertices, chain_left["is_cyclic"])
    radial_error_samples = []
    correspondence_widths = []
    for index, parameter in enumerate(left_u):
        nearest_index = min(
            range(len(right_u)),
            key=lambda candidate: abs(right_u[candidate] - parameter),
        )
        left_coordinate = (
            left_vertices[index].co
            if hasattr(left_vertices[index], "co")
            else left_vertices[index]
        )
        right_coordinate = (
            right_vertices[nearest_index].co
            if hasattr(right_vertices[nearest_index], "co")
            else right_vertices[nearest_index]
        )
        correspondence_widths.append(
            (left_coordinate - right_coordinate).length
        )
        radial_error_samples.append(
            max(
                abs(
                    _point_to_feature_group_distance(
                        left_vertices[index].co if hasattr(left_vertices[index], "co") else left_vertices[index],
                        group,
                    )
                    - radius
                ),
                abs(
                    _point_to_feature_group_distance(
                        right_vertices[nearest_index].co if hasattr(right_vertices[nearest_index], "co") else right_vertices[nearest_index],
                        group,
                    )
                    - radius
                ),
            )
        )
    record = {
        "backend": "BOOLEAN_INTERSECTION_ORACLE",
        "group_id": group["pipe_id"],
        "span_id": span["span_id"],
        "source_edge_ids": span["source_edge_ids"],
        "left_patch_id": span["patch_pair"][0],
        "right_patch_id": span["patch_pair"][1],
        "rail_left": [tuple(vertex.co if hasattr(vertex, "co") else vertex) for vertex in left_vertices],
        "rail_right": [tuple(vertex.co if hasattr(vertex, "co") else vertex) for vertex in right_vertices],
        "u": left_u,
        "width_error": radial_error_samples,
        "correspondence_width": correspondence_widths,
        "ownership_confidence": 1.0,
        "cyclic": chain_left["is_cyclic"] and chain_right["is_cyclic"],
        "left_cyclic": bool(chain_left["is_cyclic"]),
        "right_cyclic": bool(chain_right["is_cyclic"]),
        "left_edge_count": len(chain_left.get("edges", left_vertices)),
        "right_edge_count": len(chain_right.get("edges", right_vertices)),
        "rail_left_edge_indices": [
            edge.index for edge in chain_left.get("edges", [])
        ],
        "rail_right_edge_indices": [
            edge.index for edge in chain_right.get("edges", [])
        ],
    }
    record["boundary_edge_indices"] = sorted(
        set(
            record["rail_left_edge_indices"]
            + record["rail_right_edge_indices"]
        )
    )
    record["geometry_guard"] = _rail_pair_geometry_guard(
        record,
        group,
        span,
        radius,
    )
    return record

# 把 CutterStrand 按连续 patch_pair 切成 rail ownership spans。
# group: 含逐 Edge patch_pair/convexity 的 Feature group；返回有序 span records。
def _group_patch_pair_spans(group):
    spans = []
    for edge_offset, (edge_id, patch_pair, convexity) in enumerate(
        zip(
            group["edge_indices"],
            group["patch_pair_by_edge"],
            group["convexity_by_edge"],
        )
    ):
        patch_pair = tuple(patch_pair)
        if (
            not spans
            or spans[-1]["patch_pair"] != patch_pair
            or spans[-1]["convexity"] != convexity
        ):
            spans.append(
                {
                    "span_id": len(spans),
                    "edge_offsets": [],
                    "source_edge_ids": [],
                    "patch_pair": patch_pair,
                    "convexity": convexity,
                }
            )
        spans[-1]["edge_offsets"].append(edge_offset)
        spans[-1]["source_edge_ids"].append(edge_id)
    if (
        group["is_cyclic"]
        and len(spans) > 1
        and spans[0]["patch_pair"] == spans[-1]["patch_pair"]
        and spans[0]["convexity"] == spans[-1]["convexity"]
    ):
        spans[0]["edge_offsets"] = (
            spans[-1]["edge_offsets"] + spans[0]["edge_offsets"]
        )
        spans[0]["source_edge_ids"] = (
            spans[-1]["source_edge_ids"] + spans[0]["source_edge_ids"]
        )
        spans.pop()
        for span_id, span in enumerate(spans):
            span["span_id"] = span_id
    return spans


# 返回交线点最近的 Feature Edge offset 与距离。
# point/group: Cutter 交线坐标与含 ordered points/cyclic 的 Feature group。
def _nearest_feature_edge_offset(point, group):
    best = None
    point_count = len(group["points"])
    for edge_offset in range(len(group["edge_indices"])):
        start = group["points"][edge_offset]
        end = group["points"][(edge_offset + 1) % point_count]
        closest, factor = geometry.intersect_point_line(point, start, end)
        factor = max(0.0, min(1.0, factor))
        closest = start.lerp(end, factor)
        candidate = ((point - closest).length_squared, edge_offset, factor)
        if best is None or candidate < best:
            best = candidate
    return best[1], math.sqrt(best[0]), best[2]


# 把有序 Cutter 交线按最近 Feature Edge owner 切成当前 span 的连续 runs。
# chain/group/span: 原始交线、Feature group 与目标 ownership span；返回局部 chain records。
def _clip_intersection_chain_to_span(chain, group, span):
    coordinates = [Vector(point) for point in chain["coordinates"]]
    if not coordinates:
        return []
    owned_offsets = set(span["edge_offsets"])
    ownership = [
        _nearest_feature_edge_offset(point, group)[0] in owned_offsets
        for point in coordinates
    ]
    if all(ownership):
        return [
            {
                "coordinates": coordinates,
                "is_cyclic": bool(chain["is_cyclic"]),
            }
        ]
    if chain["is_cyclic"] and any(ownership):
        first_unowned = ownership.index(False)
        offset = first_unowned + 1
        coordinates = coordinates[offset:] + coordinates[:offset]
        ownership = ownership[offset:] + ownership[:offset]
    runs = []
    current = []
    for point, is_owned in zip(coordinates, ownership):
        if is_owned:
            current.append(point)
        elif current:
            if len(current) >= 2:
                runs.append({"coordinates": current, "is_cyclic": False})
            current = []
    if len(current) >= 2:
        runs.append({"coordinates": current, "is_cyclic": False})
    return runs


# 按最大 segment length 线性重采样 Cutter 交线，保持 open endpoints/cyclic seam。
# chain/max_length: 待重采样 chain 与最大采样边长；返回新的 chain record。
def _resample_intersection_chain(chain, max_length):
    coordinates = chain["coordinates"]
    cyclic = chain["is_cyclic"]
    segment_count = len(coordinates) if cyclic else len(coordinates) - 1
    resampled = []
    for index in range(segment_count):
        start = coordinates[index]
        end = coordinates[(index + 1) % len(coordinates)]
        divisions = max(1, int(math.ceil((end - start).length / max_length)))
        if not resampled:
            resampled.append(start.copy())
        for step in range(1, divisions + 1):
            if cyclic and index == segment_count - 1 and step == divisions:
                continue
            resampled.append(start.lerp(end, step / divisions))
    return {"coordinates": resampled, "is_cyclic": cyclic}


# 为目标 Feature span 生成已裁切且满足采样密度的 Cutter 交线候选。
# chains/group/span/radius: 原始交线、Feature group、目标 span 与 Chamfer radius。
def _span_intersection_chains(chains, group, span, radius):
    max_length = max(radius * 1.5, 1.0e-4)
    return [
        _resample_intersection_chain(local_chain, max_length)
        for chain in chains
        for local_chain in _clip_intersection_chain_to_span(chain, group, span)
        if len(local_chain["coordinates"]) >= 2
    ]


# 只保留原始 Boundary adjacency，把完整 Rail chain 按 Feature span ownership 裁成连续 runs。
# chain/group/span: 最终 Boolean Boundary chain、Feature group 与目标 span；返回 BMesh chain records。
def _slice_boundary_chain_to_span(chain, group, span):
    vertices = chain["vertices"]
    edges = chain["edges"]
    if not edges:
        return []
    owned_offsets = set(span["edge_offsets"])
    edge_ownership = [
        _nearest_feature_edge_offset(
            (edge.verts[0].co + edge.verts[1].co) * 0.5,
            group,
        )[0]
        in owned_offsets
        for edge in edges
    ]
    if all(edge_ownership):
        return [chain]
    if chain["is_cyclic"] and any(edge_ownership):
        first_unowned = edge_ownership.index(False)
        offset = first_unowned + 1
        edges = edges[offset:] + edges[:offset]
        vertices = vertices[offset:] + vertices[:offset]
        edge_ownership = edge_ownership[offset:] + edge_ownership[:offset]
    runs = []
    run_edges = []
    run_vertices = []
    for edge, start_vertex, is_owned in zip(edges, vertices, edge_ownership):
        if is_owned:
            if not run_edges:
                run_vertices = [start_vertex]
            run_edges.append(edge)
            run_vertices.append(edge.other_vert(run_vertices[-1]))
        elif run_edges:
            runs.append(
                {
                    "edges": run_edges,
                    "vertices": run_vertices,
                    "is_cyclic": False,
                }
            )
            run_edges = []
            run_vertices = []
    if run_edges:
        runs.append(
            {
                "edges": run_edges,
                "vertices": run_vertices,
                "is_cyclic": False,
            }
        )
    return runs


# 仅裁掉被 overlap 吃掉的连续 endpoint prefix/suffix，保留原始 Boundary Edge adjacency。
# chain_left/right/radius: 已配对的开 Rail chains 与 Chamfer radius；返回 core chains 或 None。
def _trim_rail_pair_to_width_core(chain_left, chain_right, radius):
    if chain_left["is_cyclic"] or chain_right["is_cyclic"]:
        return None
    left_vertices = chain_left["vertices"]
    right_vertices = chain_right["vertices"]
    expected_width = radius * math.sqrt(2.0)
    tolerance = max(radius * 0.60, 1.0e-5)

    def inlier(vertex, opposite_vertices):
        return abs(
            _point_to_rail_distance(
                vertex.co,
                opposite_vertices,
                False,
            )
            - expected_width
        ) <= tolerance

    left_inliers = [inlier(vertex, right_vertices) for vertex in left_vertices]
    right_inliers = [inlier(vertex, left_vertices) for vertex in right_vertices]
    if not any(left_inliers) or not any(right_inliers):
        return None
    left_start = left_inliers.index(True)
    left_end = len(left_inliers) - list(reversed(left_inliers)).index(True)
    right_start = right_inliers.index(True)
    right_end = len(right_inliers) - list(reversed(right_inliers)).index(True)
    left_core_edges = chain_left["edges"][left_start : max(left_start, left_end - 1)]
    right_core_edges = chain_right["edges"][right_start : max(right_start, right_end - 1)]
    if not left_core_edges or not right_core_edges:
        return None
    left_core = {
        "edges": left_core_edges,
        "vertices": left_vertices[left_start:left_end],
        "is_cyclic": False,
    }
    right_core = {
        "edges": right_core_edges,
        "vertices": right_vertices[right_start:right_end],
        "is_cyclic": False,
    }
    trimmed_left_edges = (
        chain_left["edges"][:left_start]
        + chain_left["edges"][max(left_start, left_end - 1) :]
    )
    trimmed_right_edges = (
        chain_right["edges"][:right_start]
        + chain_right["edges"][max(right_start, right_end - 1) :]
    )
    return left_core, right_core, {
        "left_trimmed_edge_count": len(trimmed_left_edges),
        "right_trimmed_edge_count": len(trimmed_right_edges),
        "left_trimmed_edge_indices": [edge.index for edge in trimmed_left_edges],
        "right_trimmed_edge_indices": [edge.index for edge in trimmed_right_edges],
        "occluded_boundary_edge_indices": sorted(
            {edge.index for edge in trimmed_left_edges + trimmed_right_edges}
        ),
    }


# 为 span 选择局部 Boundary chain pair；拒绝明显超出 span local bounds 的全局 chains。
# span/group/chains/radius: ownership span、Feature group、候选 rails 与目标 radius。
def _span_chain_candidates(span, group, chains_left, chains_right, radius):
    span_points = [
        group["points"][index]
        for edge_offset in span["edge_offsets"]
        for index in (
            edge_offset,
            (edge_offset + 1) % len(group["points"]),
        )
    ]
    minimum = Vector(
        tuple(min(point[axis] for point in span_points) for axis in range(3))
    )
    maximum = Vector(
        tuple(max(point[axis] for point in span_points) for axis in range(3))
    )
    margin = radius * 2.5

    def chain_is_local(chain):
        return all(
            minimum[axis] - margin
            <= (vertex.co if hasattr(vertex, "co") else vertex)[axis]
            <= maximum[axis] + margin
            for vertex in (chain.get("coordinates") or chain["vertices"])
            for axis in range(3)
        )

    candidates = []
    for index_left, chain_left in enumerate(chains_left):
        for index_right, chain_right in enumerate(chains_right):
            if not _rail_pair_is_valid(chain_left, chain_right):
                continue
            local_left = chain_is_local(chain_left)
            local_right = chain_is_local(chain_right)
            if not local_left or not local_right:
                continue
            coordinates_left = [
                vertex.co if hasattr(vertex, "co") else vertex
                for vertex in (chain_left.get("coordinates") or chain_left["vertices"])
            ]
            coordinates_right = [
                vertex.co if hasattr(vertex, "co") else vertex
                for vertex in (chain_right.get("coordinates") or chain_right["vertices"])
            ]
            endpoint_distance = min(
                (coordinates_left[0] - coordinates_right[0]).length,
                (coordinates_left[0] - coordinates_right[-1]).length,
                (coordinates_left[-1] - coordinates_right[0]).length,
                (coordinates_left[-1] - coordinates_right[-1]).length,
            )

            candidates.append(
                (
                    _rail_pair_score(chain_left, chain_right),
                    index_left,
                    index_right,
                )
            )
    return sorted(candidates)


# 为触及 Pipe endpoint 的 span 收集 all-pipe union 的局部遮蔽证据。
# group/span/overlap_neighbors/trees/bounds/radius: Feature span、overlap adjacency 与 Pipe spatial index。
def _span_rail_occlusion_evidence(
    group,
    span,
    overlap_neighbors,
    pipe_trees,
    pipe_bounds,
    radius,
):
    if group["is_cyclic"] or not span["edge_offsets"]:
        return None
    endpoint_sides = []
    last_edge_offset = len(group["edge_indices"]) - 1
    if 0 in span["edge_offsets"]:
        endpoint_sides.append("start")
    if last_edge_offset in span["edge_offsets"]:
        endpoint_sides.append("end")
    endpoint_classes = {
        side: group.get(f"{side}_endpoint_class", "AMBIGUOUS")
        for side in endpoint_sides
    }
    allowed_classes = {
        "TERMINAL_FACE",
        "JUNCTION_BRANCH",
        "SURFACE_CONTINUATION",
    }
    if (
        not endpoint_sides
        or not set(endpoint_classes.values()) <= allowed_classes
        or not overlap_neighbors
    ):
        return None
    local_occluders = {}
    tolerance = max(radius * 1.0e-4, 1.0e-7)
    for side in endpoint_sides:
        point = group["points"][0 if side == "start" else -1]
        side_occluders = []
        for pipe_id in sorted(overlap_neighbors):
            minimum, maximum = pipe_bounds[pipe_id]
            if any(
                point[axis] < minimum[axis] - tolerance
                or point[axis] > maximum[axis] + tolerance
                for axis in range(3)
            ):
                continue
            inside = _point_inside_closed_bvh(
                pipe_trees[pipe_id],
                point,
                tolerance,
            )
            nearest = pipe_trees[pipe_id].find_nearest(point)
            surface_distance = (
                nearest[3]
                if nearest is not None and nearest[3] is not None
                else float("inf")
            )
            if not inside and surface_distance > radius * 1.10:
                continue
            side_occluders.append(
                {
                    "pipe_id": pipe_id,
                    "point_inside_pipe": inside,
                    "surface_distance": surface_distance,
                }
            )
        if side_occluders:
            local_occluders[side] = side_occluders
    if not local_occluders:
        return None
    return {
        "endpoint_sides": endpoint_sides,
        "endpoint_classes": endpoint_classes,
        "overlap_pipe_ids": sorted(overlap_neighbors),
        "local_endpoint_occluders": local_occluders,
        "reason": "PIPE_UNION_OCCLUDES_REGULAR_RAIL_PAIR",
    }


# 建立只引用最终 Boolean Boundary Edges 的 occluded Rail span contract。
# group/span/chains/evidence: Feature span、左右可见 Rail runs 与 endpoint/overlap 证据。
def _occluded_rail_span_record(group, span, chains_left, chains_right, evidence):
    left_edge_indices = [
        edge.index
        for chain in chains_left
        for edge in chain.get("edges", [])
    ]
    right_edge_indices = [
        edge.index
        for chain in chains_right
        for edge in chain.get("edges", [])
    ]
    boundary_edge_indices = sorted(set(left_edge_indices + right_edge_indices))
    reasons = []
    if not boundary_edge_indices:
        reasons.append("NO_VISIBLE_BOUNDARY_RAIL")
    if not evidence:
        reasons.append("PIPE_UNION_OCCLUSION_UNPROVEN")
    visible_side_count = int(bool(left_edge_indices)) + int(bool(right_edge_indices))
    visible_side_guard = "PASS" if visible_side_count else "FAIL"
    return {
        "record_type": "OCCLUDED_RAIL_SPAN",
        "group_id": group["pipe_id"],
        "span_id": span["span_id"],
        "source_edge_ids": span["source_edge_ids"],
        "patch_pair": span["patch_pair"],
        "rail_left_edge_indices": left_edge_indices,
        "rail_right_edge_indices": right_edge_indices,
        "boundary_edge_indices": boundary_edge_indices,
        "left_chain_count": len(chains_left),
        "right_chain_count": len(chains_right),
        "left_edge_counts": [len(chain.get("edges", [])) for chain in chains_left],
        "right_edge_counts": [len(chain.get("edges", [])) for chain in chains_right],
        "pairing_required": False,
        "visible_side_count": visible_side_count,
        "visible_side_guard": visible_side_guard,
        "occlusion_evidence": evidence,
        "ownership_confidence": 1.0 if evidence and boundary_edge_indices else 0.0,
        "geometry_guard": {
            "status": "NOT_APPLICABLE" if not reasons else "FAIL",
            "reasons": reasons,
            "guard_type": "OCCLUDED_ENDPOINT_CLASSIFICATION",
            "sampling_backend": "FINAL_BOOLEAN_BOUNDARY_EDGES",
            "coordinate_reconstruction": False,
            "centerline_sorting": False,
        },
    }


# 从 Boolean open boundary 提取同 owner、两 Surface Patch 的 RailPairRecords。
# bm/groups/pipe_trees/bounds/radius: OPEN_BOUNDARY 上下文；返回 records 与 coverage summary。
def _extract_boolean_rail_pair_records(
    bm,
    groups,
    pipe_trees,
    pipe_bounds,
    radius,
    rails=None,
    ownership_backend="PROXIMITY_NEAREST_PIPE",
    pipe_overlap_pairs=(),
):
    if rails is None:
        rails = _pipe_boundary_rails(
            bm,
            groups,
            pipe_trees,
            pipe_bounds,
            radius,
        )
    records = []
    occluded_spans = []
    unresolved_spans = []
    deferred_spans = []
    total_span_count = 0
    overlap_neighbors = {group["pipe_id"]: set() for group in groups}
    for pipe_left, pipe_right in pipe_overlap_pairs:
        overlap_neighbors.setdefault(pipe_left, set()).add(pipe_right)
        overlap_neighbors.setdefault(pipe_right, set()).add(pipe_left)
    for group in groups:
        for span in _group_patch_pair_spans(group):
            total_span_count += 1
            patch_left, patch_right = span["patch_pair"]
            chains_left = rails.get(group["pipe_id"], {}).get(
                patch_left,
                [],
            )
            chains_right = rails.get(group["pipe_id"], {}).get(
                patch_right,
                [],
            )
            if ownership_backend == "CUTTER_FACE_COMPONENT_PROVENANCE":
                chains_left = _span_intersection_chains(
                    chains_left,
                    group,
                    span,
                    radius,
                )
                chains_right = _span_intersection_chains(
                    chains_right,
                    group,
                    span,
                    radius,
                )
            elif ownership_backend == "FINAL_BOOLEAN_BOUNDARY_PIPE_SURFACE":
                chains_left = [
                    local_chain
                    for chain in chains_left
                    for local_chain in _slice_boundary_chain_to_span(
                        chain,
                        group,
                        span,
                    )
                ]
                chains_right = [
                    local_chain
                    for chain in chains_right
                    for local_chain in _slice_boundary_chain_to_span(
                        chain,
                        group,
                        span,
                    )
                ]
            if (
                len(chains_left) == 1
                and len(chains_right) == 1
                and group["is_cyclic"]
                and len(_group_patch_pair_spans(group)) == 1
            ):
                candidates = [
                    (
                        _rail_pair_score(chains_left[0], chains_right[0]),
                        0,
                        0,
                    )
                ]
            else:
                candidates = _span_chain_candidates(
                    span,
                    group,
                    chains_left,
                    chains_right,
                    radius,
                )
            if not candidates:
                occlusion_evidence = _span_rail_occlusion_evidence(
                    group,
                    span,
                    overlap_neighbors.get(group["pipe_id"], set()),
                    pipe_trees,
                    pipe_bounds,
                    radius,
                )
                occluded_record = _occluded_rail_span_record(
                    group,
                    span,
                    chains_left,
                    chains_right,
                    occlusion_evidence,
                )
                if occluded_record["geometry_guard"]["status"] == "NOT_APPLICABLE":
                    occluded_spans.append(occluded_record)
                    continue
                deferred_record = {
                    "record_type": "DEFERRED_RAIL_REGION",
                    "group_id": group["pipe_id"],
                    "span_id": span["span_id"],
                    "source_edge_ids": span["source_edge_ids"],
                    "patch_pair": span["patch_pair"],
                    "region_class": "JUNCTION_OR_TERMINAL",
                    "reason": "RAIL_SIDE_MISSING_OR_AMBIGUOUS",
                    "left_chain_count": len(chains_left),
                    "right_chain_count": len(chains_right),
                    "left_edge_counts": [
                        len(chain.get("edges", []))
                        for chain in chains_left
                    ],
                    "right_edge_counts": [
                        len(chain.get("edges", []))
                        for chain in chains_right
                    ],
                    "ownership_backend": ownership_backend,
                    "ownership_confidence": 0.0,
                    "geometry_guard": {
                        "status": "DEFERRED",
                        "reasons": ["RAIL_PAIR_UNRESOLVED"],
                        "sampling_backend": "FINAL_BOOLEAN_BOUNDARY_EDGES",
                        "coordinate_reconstruction": False,
                        "centerline_sorting": False,
                    },
                }
                deferred_spans.append(deferred_record)
                unresolved_spans.append(deferred_record)
                continue
            _, index_left, index_right = candidates[0]
            record = _boolean_rail_pair_record(
                    group,
                    span,
                    chains_left[index_left],
                    chains_right[index_right],
                    radius,
                )
            record["ownership_backend"] = ownership_backend
            if record["geometry_guard"]["status"] != "PASS":
                trimmed_pair = _trim_rail_pair_to_width_core(
                    chains_left[index_left],
                    chains_right[index_right],
                    radius,
                )
                if trimmed_pair is not None:
                    left_core, right_core, trim_diagnostics = trimmed_pair
                    core_record = _boolean_rail_pair_record(
                        group,
                        span,
                        left_core,
                        right_core,
                        radius,
                    )
                    core_record["ownership_backend"] = ownership_backend
                    core_record["endpoint_trim"] = trim_diagnostics
                    if core_record["geometry_guard"]["status"] == "PASS":
                        records.append(core_record)
                        continue
                occlusion_evidence = _span_rail_occlusion_evidence(
                    group,
                    span,
                    overlap_neighbors.get(group["pipe_id"], set()),
                    pipe_trees,
                    pipe_bounds,
                    radius,
                )
                occluded_record = _occluded_rail_span_record(
                    group,
                    span,
                    [chains_left[index_left]],
                    [chains_right[index_right]],
                    occlusion_evidence,
                )
                if occluded_record["geometry_guard"]["status"] == "NOT_APPLICABLE":
                    occluded_record["failed_rail_pair"] = record
                    occluded_spans.append(occluded_record)
                    continue
                deferred_spans.append(
                    {
                        "record_type": "DEFERRED_RAIL_REGION",
                        "group_id": group["pipe_id"],
                        "span_id": span["span_id"],
                        "source_edge_ids": span["source_edge_ids"],
                        "patch_pair": span["patch_pair"],
                        "region_class": "JUNCTION_OR_TERMINAL",
                        "reason": "RAIL_PAIR_GEOMETRY_UNRESOLVED",
                        "left_chain_count": len(chains_left),
                        "right_chain_count": len(chains_right),
                        "left_edge_counts": [
                            len(chain.get("edges", []))
                            for chain in chains_left
                        ],
                        "right_edge_counts": [
                            len(chain.get("edges", []))
                            for chain in chains_right
                        ],
                        "ownership_backend": ownership_backend,
                        "ownership_confidence": 0.0,
                        "failed_rail_pair": record,
                        "geometry_guard": {
                            "status": "DEFERRED",
                            "reasons": record["geometry_guard"]["reasons"],
                            "sampling_backend": "FINAL_BOOLEAN_BOUNDARY_EDGES",
                            "coordinate_reconstruction": False,
                            "centerline_sorting": False,
                        },
                    }
                )
                unresolved_spans.append(deferred_spans[-1])
                continue
            records.append(record)
    valid_records = [
        record for record in records if record["geometry_guard"]["status"] == "PASS"
    ]
    classified_occluded_spans = [
        record
        for record in occluded_spans
        if record["geometry_guard"]["status"] == "NOT_APPLICABLE"
    ]
    classified_span_count = len(records) + len(occluded_spans)
    paired_boundary_edge_indices = {
        edge_index
        for record in records
        for edge_index in record["boundary_edge_indices"]
    }
    occluded_boundary_edge_indices = ({
        edge_index
        for record in occluded_spans
        for edge_index in record["boundary_edge_indices"]
    } | {
        edge_index
        for record in records
        for edge_index in record.get("endpoint_trim", {}).get(
            "occluded_boundary_edge_indices",
            [],
        )
    }) - paired_boundary_edge_indices

    consumed_boundary_edge_indices = (
        paired_boundary_edge_indices | occluded_boundary_edge_indices
    )

    guard_failures = [
        {
            "group_id": record["group_id"],
            "span_id": record["span_id"],
            "reasons": record["geometry_guard"]["reasons"],
        }
        for record in records
        if record["geometry_guard"]["status"] != "PASS"
    ]
    summary = {
        "backend": "BOOLEAN_INTERSECTION_ORACLE",
        "ownership_backend": ownership_backend,
        "group_count": len(groups),
        "span_count": total_span_count,
        "regular_span_count": len(records),
        "occluded_span_count": len(occluded_spans),
        "occluded_spans": occluded_spans,
        "deferred_span_count": len(deferred_spans),
        "deferred_spans": deferred_spans,
        "paired_span_count": len(records),
        "valid_span_count": len(valid_records),
        "pairable_span_count": len(records),
        "owned_span_count": len(records),
        "guard_valid_span_count": len(valid_records),
        "occluded_classified_span_count": len(classified_occluded_spans),
        "classified_span_count": classified_span_count,
        "classification_coverage": (
            classified_span_count / total_span_count
            if total_span_count
            else 0.0
        ),
        "coverage": len(records) / total_span_count if total_span_count else 0.0,
        "guarded_coverage": (
            len(valid_records) / total_span_count
            if total_span_count
            else 0.0
        ),
        "pairable_coverage": len(records) / len(records) if records else 0.0,
        "pairable_guarded_coverage": (
            len(valid_records) / len(records)
            if records
            else 0.0
        ),
        "total_span_rail_pair_coverage": (
            len(records) / total_span_count
            if total_span_count
            else 0.0
        ),
        "paired_boundary_edge_indices": sorted(paired_boundary_edge_indices),
        "occluded_boundary_edge_indices": sorted(occluded_boundary_edge_indices),
        "consumed_boundary_edge_indices": sorted(consumed_boundary_edge_indices),
        "unresolved_spans": unresolved_spans,
        "unresolved_group_ids": sorted(
            {span["group_id"] for span in unresolved_spans}
        ),
        "guard_failures": guard_failures,
    }
    return records, summary


# 返回 2D 向量叉积标量，用于 owner Face 平面内的 ray/Edge 相交。
# vector_a/vector_b: Face 主轴投影后的二维向量。
def _cross_2d(vector_a, vector_b):
    return vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0]


# 把 3D 点投影到 owner Face 法线主轴对应的稳定二维平面。
# point/normal: 待投影坐标与 owner Face normal；返回二维坐标。
def _project_to_face_2d(point, normal):
    dropped_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    axes = [axis for axis in range(3) if axis != dropped_axis]
    return Vector((point[axes[0]], point[axes[1]]))


# 查找 owner Face 内从 point 沿 direction 首次穿过的 Edge。
# point/direction/face: Face 平面内的起点、单位方向与当前 owner Face；excluded_edge: 刚进入 Face 的 Edge。
def _next_owner_face_crossing(point, direction, face, excluded_edge=None):
    point_2d = _project_to_face_2d(point, face.normal)
    direction_2d = _project_to_face_2d(direction, face.normal)
    tolerance = 1.0e-8
    candidates = []
    for edge in face.edges:
        if edge is excluded_edge:
            continue
        edge_start = edge.verts[0].co
        edge_end = edge.verts[1].co
        edge_start_2d = _project_to_face_2d(edge_start, face.normal)
        edge_vector_2d = _project_to_face_2d(edge_end - edge_start, face.normal)
        denominator = _cross_2d(direction_2d, edge_vector_2d)
        if abs(denominator) <= tolerance:
            continue
        relative = edge_start_2d - point_2d
        distance = _cross_2d(relative, edge_vector_2d) / denominator
        edge_factor = _cross_2d(relative, direction_2d) / denominator
        if distance <= tolerance or not -tolerance <= edge_factor <= 1.0 + tolerance:
            continue
        candidates.append((distance, edge.index, edge))
    return min(candidates, default=None, key=lambda item: (item[0], item[1]))


# 沿同一 Surface Patch 的 Face adjacency 累计 intrinsic distance。
# point/direction/face/face_patch/radius: 起点、Face 切向、owner Face、Face→Patch 映射与目标距离。
def _walk_owner_face_adjacency(point, direction, face, face_patch, radius):
    patch_id = face_patch[face]
    current_face = face
    current_point = Vector(point)
    current_direction = Vector(direction).normalized()
    travelled = 0.0
    previous_edge = None
    face_path = [face.index]
    max_crossings = max(32, len(face_patch) * 2)
    for _ in range(max_crossings):
        remaining = radius - travelled
        if remaining <= max(radius * 1.0e-6, 1.0e-9):
            return {
                "point": current_point,
                "travelled": travelled,
                "face_path": face_path,
            }
        current_direction -= current_face.normal * current_direction.dot(current_face.normal)
        if current_direction.length <= 1.0e-10:
            return None
        current_direction.normalize()
        crossing = _next_owner_face_crossing(
            current_point,
            current_direction,
            current_face,
            previous_edge,
        )
        if crossing is None or crossing[0] >= remaining:
            current_point += current_direction * remaining
            travelled += remaining
            return {
                "point": current_point,
                "travelled": travelled,
                "face_path": face_path,
            }
        distance, _, crossed_edge = crossing
        current_point += current_direction * distance
        travelled += distance
        neighbors = sorted(
            (
                linked_face
                for linked_face in crossed_edge.link_faces
                if linked_face is not current_face
                and face_patch.get(linked_face) == patch_id
            ),
            key=lambda linked_face: linked_face.index,
        )
        if len(neighbors) != 1:
            return None
        next_face = neighbors[0]
        current_direction = current_face.normal.rotation_difference(next_face.normal) @ current_direction
        current_face = next_face
        previous_edge = crossed_edge
        face_path.append(current_face.index)
    return None


# 把点沿 owner Face 切平面偏移，并只沿同一 Surface Patch 的 Face adjacency walk。
# point/tangent/face/face_patch/radius: Feature sample、切线、owner Face、Face→Patch 映射与目标偏移；previous: 上一 walk 诊断。
def _offset_point_on_face(
    point,
    tangent,
    face,
    face_patch,
    radius,
    previous=None,
):
    inward = face.normal.cross(tangent)
    face_direction = face.calc_center_median() - point
    if inward.dot(face_direction) < 0.0:
        inward.negate()
    if inward.length <= 1.0e-10:
        return None
    inward.normalize()

    walk = _walk_owner_face_adjacency(
        point,
        inward,
        face,
        face_patch,
        radius,
    )
    if walk is None:
        return None
    projected = walk["point"]
    travelled = walk["travelled"]

    candidate = point + inward * radius
    continuity_error = 0.0
    if previous is not None:
        candidate_step = candidate - previous["candidate"]
        projected_step = projected - previous["point"]
        continuity_error = (projected_step - candidate_step).length
    continuity_limit = max(radius * 0.75, 1.0e-5)
    signed_offset = (projected - point).dot(inward)
    return {
        "point": projected,
        "candidate": candidate,
        "signed_offset": signed_offset,
        "intrinsic_offset_error": abs(travelled - radius),
        "projection_distance": 0.0,
        "projection_limit": max(radius * 0.1, 1.0e-5),
        "continuity_error": continuity_error,
        "continuity_limit": continuity_limit,
        "owner_face_path": walk["face_path"],
    }


# 按 max_length 重采样 ownership span，保留每个 sample 的 source Edge owner。
# group/span/max_length: Feature group、连续 Patch span 与最大 segment length。
def _sample_feature_span(group, span, max_length):
    samples = []
    point_count = len(group["points"])
    for edge_offset in span["edge_offsets"]:
        start = group["points"][edge_offset]
        end = group["points"][(edge_offset + 1) % point_count]
        divisions = max(1, int(math.ceil((end - start).length / max_length)))
        if not samples:
            samples.append({"point": start.copy(), "edge_offset": edge_offset})
        for step in range(1, divisions + 1):
            samples.append(
                {
                    "point": start.lerp(end, step / divisions),
                    "edge_offset": edge_offset,
                }
            )
    cyclic = group["is_cyclic"] and len(_group_patch_pair_spans(group)) == 1
    if cyclic and len(samples) > 1 and (
        samples[0]["point"] - samples[-1]["point"]
    ).length <= 1.0e-7:
        samples.pop()
    return samples, cyclic


# 为重采样 Feature points 计算 open/cyclic tangent。
# samples/cyclic: 含 point 的 sample records 与闭环标记；返回单位 tangent 数组。
def _sample_tangents(samples, cyclic):
    tangents = []
    for index, sample in enumerate(samples):
        if cyclic:
            previous = samples[(index - 1) % len(samples)]["point"]
            following = samples[(index + 1) % len(samples)]["point"]
        else:
            previous = samples[max(0, index - 1)]["point"]
            following = samples[min(len(samples) - 1, index + 1)]["point"]
        tangent = following - previous
        tangents.append(tangent.normalized() if tangent.length > 1.0e-10 else Vector())
    return tangents


# 直接在 source Surface Patch 上按 radius 构造结构化 offset rails。
# source_object/groups/radius: 原 Mesh、CutterStrands 与 Chamfer radius；返回 records/summary。
def _extract_source_surface_offset_rail_records(source_object, groups, radius):
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    sharp_edges = {bm.edges[index] for index in _sharp_edge_indices(source_object)}
    face_patch, _ = _surface_patch_map(bm, sharp_edges)
    records = []
    unresolved_spans = []
    total_span_count = 0
    sample_edge_limit = max(radius * 1.5, 1.0e-4)
    try:
        for group in groups:
            for span in _group_patch_pair_spans(group):
                total_span_count += 1
                patch_left, patch_right = span["patch_pair"]
                samples, cyclic = _sample_feature_span(
                    group,
                    span,
                    sample_edge_limit,
                )
                tangents = _sample_tangents(samples, cyclic)
                left_points = []
                right_points = []
                left_projection_records = []
                right_projection_records = []
                valid = True
                for sample, tangent in zip(samples, tangents):
                    edge = bm.edges[
                        group["edge_indices"][sample["edge_offset"]]
                    ]
                    face_by_patch = {
                        face_patch[face]: face
                        for face in edge.link_faces
                        if face_patch[face] in {patch_left, patch_right}
                    }
                    if (
                        patch_left not in face_by_patch
                        or patch_right not in face_by_patch
                        or tangent.length <= 1.0e-10
                    ):
                        valid = False
                        break
                    point = sample["point"]
                    left = _offset_point_on_face(
                        point,
                        tangent,
                        face_by_patch[patch_left],
                        face_patch,
                        radius,
                        left_projection_records[-1]
                        if left_projection_records
                        else None,
                    )
                    right = _offset_point_on_face(
                        point,
                        tangent,
                        face_by_patch[patch_right],
                        face_patch,
                        radius,
                        right_projection_records[-1]
                        if right_projection_records
                        else None,
                    )
                    if left is None or right is None:
                        valid = False
                        break
                    left_projection_records.append(left)
                    right_projection_records.append(right)
                    left_points.append(left["point"])
                    right_points.append(right["point"])
                if not valid or len(left_points) < 2:
                    unresolved_spans.append(
                        {
                            "group_id": group["pipe_id"],
                            "span_id": span["span_id"],
                            "patch_pair": span["patch_pair"],
                            "reason": "OWNER_FACE_WALK_FAILED",
                            "failed_sample_index": len(left_points),
                            "sample_count": len(samples),
                            "source_edge_id": (
                                group["edge_indices"][samples[len(left_points)]["edge_offset"]]
                                if len(left_points) < len(samples)
                                else None
                            ),
                        }
                    )
                    continue
                radial_errors = [
                    max(
                        left["intrinsic_offset_error"],
                        right["intrinsic_offset_error"],
                    )
                    for left, right in zip(
                        left_projection_records,
                        right_projection_records,
                    )
                ]
                record = {
                    "backend": "SOURCE_SURFACE_OFFSET",
                    "group_id": group["pipe_id"],
                    "span_id": span["span_id"],
                    "source_edge_ids": span["source_edge_ids"],
                    "left_patch_id": patch_left,
                    "right_patch_id": patch_right,
                    "rail_left": [tuple(point) for point in left_points],
                    "rail_right": [tuple(point) for point in right_points],
                    "u": _coordinate_parameters(left_points, cyclic),
                    "width_error": radial_errors,
                    "intrinsic_offset_error": radial_errors,
                    "projection_distance": [
                        max(
                            left["projection_distance"],
                            right["projection_distance"],
                        )
                        for left, right in zip(
                            left_projection_records,
                            right_projection_records,
                        )
                    ],
                    "projection_continuity_error": [
                        max(
                            left["continuity_error"],
                            right["continuity_error"],
                        )
                        for left, right in zip(
                            left_projection_records,
                            right_projection_records,
                        )
                    ],
                    "projection_limit": min(
                        left_projection_records[0]["projection_limit"],
                        right_projection_records[0]["projection_limit"],
                    ),
                    "projection_continuity_limit": min(
                        left_projection_records[0]["continuity_limit"],
                        right_projection_records[0]["continuity_limit"],
                    ),
                    "ownership_confidence": 1.0,
                    "cyclic": cyclic,
                    "left_owner_face_paths": [
                        projection["owner_face_path"]
                        for projection in left_projection_records
                    ],
                    "right_owner_face_paths": [
                        projection["owner_face_path"]
                        for projection in right_projection_records
                    ],
                }
                record["geometry_guard"] = _rail_pair_geometry_guard(
                    record,
                    group,
                    span,
                    radius,
                )
                records.append(record)
    finally:
        bm.free()
    valid_records = [
        record for record in records if record["geometry_guard"]["status"] == "PASS"
    ]
    guard_failures = [
        {
            "group_id": record["group_id"],
            "span_id": record["span_id"],
            "reasons": record["geometry_guard"]["reasons"],
        }
        for record in records
        if record["geometry_guard"]["status"] != "PASS"
    ]
    summary = {
        "backend": "SOURCE_SURFACE_OFFSET",
        "group_count": len(groups),
        "span_count": total_span_count,
        "paired_span_count": len(records),
        "valid_span_count": len(valid_records),
        "coverage": len(records) / total_span_count if total_span_count else 0.0,
        "guarded_coverage": len(valid_records) / total_span_count if total_span_count else 0.0,
        "unresolved_spans": unresolved_spans,
        "unresolved_group_ids": sorted(
            {span["group_id"] for span in unresolved_spans}
        ),
        "guard_failures": guard_failures,
    }
    return records, summary

# 模拟手工流程：同一 Pipe 两侧 rail 执行 Bridge Edge Loops，之后 Fill 剩余闭合洞。
# bm/loops: 删除槽面后的 BoundaryGraph；groups/pipe_trees/radius: rail ownership 上下文；stats: 统计。
def _bridge_then_fill(bm, loops, groups, pipe_trees, pipe_bounds, radius, stats):
    """模拟手工流程：同一 Pipe 两侧 rail 执行 Bridge Edge Loops，之后 Fill 剩余真实 holes。

    关键约束：每次 Bridge 后重新从当前 BoundaryGraph 计算 rails，避免使用过期的 edge 快照；
    Fill 前必须区分"真正的开放洞"和"已被单面占据的 occupied cycle"，后者说明 region partition
    或 rail pairing 仍有缺陷，应稳定失败而不是用 Fill 掩盖。
    """
    del loops
    regular_faces = []
    junction_faces = []
    bridge_count = 0
    stats["bridge_attempt_count"] = 0
    stats["bridge_failure_messages"] = []
    stats["bridge_face_counts"] = []

    for group in groups:
        pipe_id = group["pipe_id"]
        patch_a, patch_b = group["patch_pair"]
        if patch_a == patch_b:
            continue

        # 每次重新从当前 BoundaryGraph 提取 rails，避免使用 Bridge 前的过期快照。
        rails = _pipe_boundary_rails(bm, groups, pipe_trees, pipe_bounds, radius)
        chains_a = rails.get(pipe_id, {}).get(patch_a, [])
        chains_b = rails.get(pipe_id, {}).get(patch_b, [])
        if not chains_a or not chains_b:
            continue

        candidates = []
        for index_a, chain_a in enumerate(chains_a):
            for index_b, chain_b in enumerate(chains_b):
                score = _rail_pair_score(chain_a, chain_b)
                candidates.append((score, index_a, index_b))

        paired_a = set()
        paired_b = set()
        for _, index_a, index_b in sorted(candidates):
            if index_a in paired_a or index_b in paired_b:
                continue
            chain_a = chains_a[index_a]
            chain_b = chains_b[index_b]
            if chain_a is chain_b:
                continue
            if not _rail_pair_is_valid(chain_a, chain_b):
                continue

            stats["bridge_attempt_count"] += 1
            try:
                result = bmesh.ops.bridge_loops(
                    bm,
                    edges=chain_a["edges"] + chain_b["edges"],
                    use_pairs=False,
                    use_cyclic=False,
                )
            except (ValueError, RuntimeError) as error:
                stats["bridge_failure_messages"].append(
                    f"pipe={pipe_id}, a={len(chain_a['edges'])}, b={len(chain_b['edges'])}: {error}"
                )
                continue

            faces = list(result.get("faces", []))
            stats["bridge_face_counts"].append(len(faces))
            if not faces:
                continue

            regular_faces.extend(faces)
            paired_a.add(index_a)
            paired_b.add(index_b)
            bridge_count += 1
            stats["regular_region_count"] = bridge_count
            stats["regular_patch_face_count"] = len(regular_faces)

    remaining_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    remaining_loops = _ordered_edge_chains(remaining_edges)
    stats["remaining_boundary_loop_count"] = len(remaining_loops)

    occupied_cycles = []
    true_holes = []
    for loop in remaining_loops:
        if not loop["is_cyclic"]:
            _fail("junction_patch_invalid", "Bridge 后留下了无法 Fill 的开放边链", stats)

        loop_vertex_set = set(loop["vertices"])
        matching_faces = [
            face
            for face in bm.faces
            if set(face.verts) == loop_vertex_set
        ]
        if matching_faces and all(
            all(face in matching_faces for face in edge.link_faces)
            for edge in loop["edges"]
        ):
            occupied_cycles.append(
                {
                    "edge_indices": [edge.index for edge in loop["edges"]],
                    "vertex_indices": [vertex.index for vertex in loop["vertices"]],
                    "matching_face_indices": [face.index for face in matching_faces],
                }
            )
            continue

        true_holes.append(loop)

    if occupied_cycles:
        stats["occupied_cycles"] = occupied_cycles
        stats["warnings"].append(
            "Fill candidates contained occupied cycles; preserved their existing Faces"
        )

    for loop in true_holes:
        try:
            result = bmesh.ops.contextual_create(
                bm,
                geom=loop["edges"],
                mat_nr=0,
                use_smooth=False,
            )
        except (ValueError, RuntimeError) as error:
            _fail("junction_patch_invalid", str(error), stats)

        faces = list(result.get("faces", []))
        if not faces:
            _fail(
                "junction_patch_invalid",
                f"Fill produced no Faces for {len(loop['edges'])}-Edge hole",
                stats,
            )
        junction_faces.extend(faces)

    stats["regular_region_count"] = bridge_count
    stats["junction_region_count"] = len(true_holes)
    stats["strip_port_count"] = bridge_count * 2
    return regular_faces, junction_faces


# 验证两条待 Bridge 的 rail chain 在当前 BMesh 中仍然是合法边界环。
# chain_a/chain_b: _ordered_edge_chains 返回的 chain record。
def _rail_pair_is_valid(chain_a, chain_b):
    """验证两条 rail chain 当前仍为独立、有效的 boundary 环。"""
    edges_a = set(chain_a["edges"])
    edges_b = set(chain_b["edges"])
    vertices_a = set(chain_a["vertices"])
    vertices_b = set(chain_b["vertices"])
    if edges_a & edges_b:
        return False
    if vertices_a & vertices_b:
        return False
    if any(len(edge.link_faces) != 1 for edge in edges_a):
        return False
    if any(len(edge.link_faces) != 1 for edge in edges_b):
        return False
    return True


# 将 RailPairRecord 中的原始 Boundary Edge indices 解析为当前 BMesh 有序 chains。
# bm/record: 当前 open BMesh 与已通过 geometry guard 的 RailPairRecord。
def _rail_pair_chains_from_record(bm, record, boundary_edge_by_source_index):
    try:
        left_edges = [
            boundary_edge_by_source_index[index]
            for index in record["rail_left_edge_indices"]
        ]
        right_edges = [
            boundary_edge_by_source_index[index]
            for index in record["rail_right_edge_indices"]
        ]
    except KeyError as error:
        raise ValueError("RailPairRecord references a missing Boundary Edge") from error
    if any(len(edge.link_faces) != 1 for edge in left_edges + right_edges):
        raise ValueError("RailPairRecord contains an Edge that is no longer Boundary")
    left_chains = _ordered_edge_chains(left_edges)
    right_chains = _ordered_edge_chains(right_edges)
    if len(left_chains) != 1 or len(right_chains) != 1:
        raise ValueError(
            f"RailPairRecord did not resolve to one chain per side: {len(left_chains)}/{len(right_chains)}"
        )
    return left_chains[0], right_chains[0]


# 消费 Phase 2 RailPairRecords，逐 span 生成只跨两侧真实 Boundary Rails 的 Chamfer strips。
# bm/rail_pairs/stats: open BMesh、已验收 records 与统计；返回新 Faces。
def _patch_regular_rail_records(bm, rail_pairs, stats, radius):
    regular_faces = []
    patched_records = []
    original_boundary_edges = {
        edge
        for edge in bm.edges
        if len(edge.link_faces) == 1
    }
    boundary_edge_by_source_index = {
        edge.index: edge
        for edge in original_boundary_edges
    }
    edge_use_counts = {}
    for record in rail_pairs:
        for edge_index in set(record.get("boundary_edge_indices", [])):
            edge_use_counts[edge_index] = edge_use_counts.get(edge_index, 0) + 1
    shared_edge_indices = {
        edge_index
        for edge_index, use_count in edge_use_counts.items()
        if use_count > 1
    }
    setback_edge_indices = set(shared_edge_indices)
    for source_record in rail_pairs:
        record = dict(source_record)
        record["rail_left_edge_indices"] = list(source_record["rail_left_edge_indices"])
        record["rail_right_edge_indices"] = list(source_record["rail_right_edge_indices"])
        for side, opposite in (("left", "right"), ("right", "left")):
            side_key = f"rail_{side}_edge_indices"
            opposite_key = f"rail_{opposite}_edge_indices"
            shared_positions = [
                index
                for index, edge_index in enumerate(record[side_key])
                if edge_index in shared_edge_indices
            ]
            if not shared_positions:
                continue
            if len(shared_positions) != 1 or shared_positions[0] not in {0, len(record[side_key]) - 1}:
                _fail(
                    "regular_patch_shared_rail_invalid",
                    f"Shared Rail is not a single endpoint Edge: group={record['group_id']} span={record['span_id']}",
                    stats,
                )
            trim_start = shared_positions[0] == 0
            removed_side = record[side_key].pop(0 if trim_start else -1)
            setback_edge_indices.add(removed_side)
            if len(record[opposite_key]) <= 1:
                _fail(
                    "regular_patch_setback_too_short",
                    f"Cannot form Junction setback: group={record['group_id']} span={record['span_id']}",
                    stats,
                )
            removed_opposite = record[opposite_key].pop(0 if trim_start else -1)
            setback_edge_indices.add(removed_opposite)
        record["boundary_edge_indices"] = sorted(
            set(record["rail_left_edge_indices"] + record["rail_right_edge_indices"])
        )
        if record.get("geometry_guard", {}).get("status") != "PASS":
            _fail(
                "regular_patch_invalid",
                f"Rail geometry guard failed for group={record.get('group_id')} span={record.get('span_id')}",
                stats,
            )
        try:
            chain_left, chain_right = _rail_pair_chains_from_record(
                bm,
                record,
                boundary_edge_by_source_index,
            )
            expected_left = [Vector(coordinate) for coordinate in record["rail_left"]]
            if (
                len(chain_left["vertices"]) == len(expected_left)
                and sum(
                    (vertex.co - coordinate).length_squared
                    for vertex, coordinate in zip(chain_left["vertices"], expected_left)
                )
                > sum(
                    (vertex.co - coordinate).length_squared
                    for vertex, coordinate in zip(reversed(chain_left["vertices"]), expected_left)
                )
            ):
                chain_left["vertices"] = list(reversed(chain_left["vertices"]))
                chain_left["edges"] = list(reversed(chain_left["edges"]))
            expected_right = [Vector(coordinate) for coordinate in record["rail_right"]]
            if len(chain_right["vertices"]) == len(expected_right):
                direct_cost = sum(
                    (vertex.co - coordinate).length_squared
                    for vertex, coordinate in zip(chain_right["vertices"], expected_right)
                )
                reversed_cost = sum(
                    (vertex.co - coordinate).length_squared
                    for vertex, coordinate in zip(reversed(chain_right["vertices"]), expected_right)
                )
                right_vertices = (
                    list(reversed(chain_right["vertices"]))
                    if reversed_cost < direct_cost
                    else list(chain_right["vertices"])
                )
            else:
                right_vertices = _aligned_rail_vertices(chain_left, chain_right)
            if record.get("cyclic"):
                faces = _zipper_bridge(bm, chain_left["vertices"], right_vertices)
            else:
                faces = _zipper_bridge_open(
                    bm,
                    chain_left["vertices"],
                    right_vertices,
                    expected_width=radius * math.sqrt(2.0),
                    maximum_width_error=max(radius * 0.60, 1.0e-5),
                )
        except (IndexError, KeyError, ValueError, RuntimeError) as error:
            _fail(
                "regular_patch_invalid",
                f"group={record.get('group_id')} span={record.get('span_id')}: {error}",
                stats,
            )
        regular_faces.extend(faces)
        patched_records.append(
            {
                "group_id": record["group_id"],
                "span_id": record["span_id"],
                "face_count": len(faces),
                "cyclic": bool(record.get("cyclic")),
            }
        )
    skipped_degenerate_edge_indices = {
        edge.index
        for edge in original_boundary_edges
        if edge.is_valid and len(edge.link_faces) == 1
    }
    stats["regular_strip_records"] = patched_records
    stats["regular_patch_shared_edge_indices"] = sorted(shared_edge_indices)
    stats["regular_patch_setback_edge_indices"] = sorted(setback_edge_indices)
    stats["regular_patch_skipped_degenerate_edge_indices"] = sorted(
        skipped_degenerate_edge_indices
    )
    stats["regular_region_count"] = len(patched_records)
    stats["regular_patch_face_count"] = len(regular_faces)
    stats["regular_patch_face_indices"] = [
        face.index for face in regular_faces if face.is_valid
    ]
    return regular_faces


# 为 Phase 3 regular strip 保留局部 Junction holes，并验证剩余 Boundary 全在 Phase 2 ledger 内。
# bm/summary/topology/stats: Patch 后 BMesh、Rail summary、Boundary topology 与统计。
def _validate_regular_patch_ports(bm, summary, topology, stats):
    del topology
    remaining_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    remaining_original_indices = set(
        stats.get("regular_patch_skipped_degenerate_edge_indices", [])
    )
    original_boundary_indices = set(summary.get("consumed_boundary_edge_indices", []))
    new_port_edges = {edge for edge in remaining_edges if edge.index == -1}
    new_port_edge_indices = sorted(
        (
            tuple(round(value, 8) for value in edge.verts[0].co),
            tuple(round(value, 8) for value in edge.verts[1].co),
        )
        for edge in new_port_edges
    )
    allowed_indices = (
        set(summary.get("occluded_boundary_edge_indices", []))
        | set(summary.get("shared_overlap_edge_indices", []))
        | set(summary.get("shared_seam_chain_component_indices", []))
        | set(stats.get("regular_patch_setback_edge_indices", []))
        | set(stats.get("regular_patch_skipped_degenerate_edge_indices", []))
    )
    unexpected = sorted(remaining_original_indices - allowed_indices)
    ports = _ordered_edge_chains(remaining_edges)
    port_records = []
    for port_index, port in enumerate(ports):
        center = (
            sum((vertex.co for vertex in port["vertices"]), Vector())
            / len(port["vertices"])
        )
        normal = Vector()
        for vertex_index, vertex in enumerate(port["vertices"]):
            normal += (vertex.co - center).cross(
                port["vertices"][(vertex_index + 1) % len(port["vertices"])].co
                - center
            )
        port_records.append(
            {
                "port_index": port_index,
                "edge_count": len(port["edges"]),
                "vertex_count": len(port["vertices"]),
                "cyclic": bool(port["is_cyclic"]),
                "normal_length": normal.length,
                "edge_lengths": [
                    (edge.verts[1].co - edge.verts[0].co).length
                    for edge in port["edges"]
                ],
            }
        )
    stats["strip_port_count"] = sum(2 for chain in ports if not chain["is_cyclic"])
    stats["junction_region_count"] = len(ports)
    stats["regular_patch_port_records"] = port_records
    stats["regular_patch_remaining_boundary_edge_indices"] = sorted(
        edge.index for edge in remaining_edges
    )
    stats["regular_patch_allowed_junction_edge_indices"] = sorted(allowed_indices)
    stats["regular_patch_new_port_edges"] = new_port_edge_indices
    stats["regular_patch_unexpected_boundary_edge_indices"] = unexpected
    stats["regular_patch_port_guard"] = {
        "status": "PASS" if not unexpected else "FAIL",
        "remaining_boundary_edge_count": len(remaining_edges),
        "allowed_junction_edge_count": len(remaining_original_indices & allowed_indices),
        "unexpected_edge_count": len(unexpected),
    }
    if unexpected:
        _fail(
            "regular_patch_boundary_unresolved",
            f"Regular strips left {len(unexpected)} Boundary Edges outside Junction inputs",
            stats,
        )
    return ports


# 折叠 zipper 在 Boolean 重合端点留下的近零面积三角小环，不跨越正常 Junction。
# bm/radius/stats: 当前 BMesh、Chamfer radius 与统计。
def _clean_degenerate_strip_ports(bm, radius, stats):
    collapsed = []
    while True:
        boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
        candidates = []
        for chain in _ordered_edge_chains(boundary_edges):
            if not chain["is_cyclic"] or len(chain["edges"]) != 3:
                continue
            center = sum((vertex.co for vertex in chain["vertices"]), Vector()) / 3.0
            normal = Vector()
            for index, vertex in enumerate(chain["vertices"]):
                normal += (vertex.co - center).cross(
                    chain["vertices"][(index + 1) % 3].co - center
                )
            if normal.length > max(radius * radius * 1.0e-4, 1.0e-10):
                continue
            candidates.append(
                min(
                    chain["edges"],
                    key=lambda edge: (edge.verts[1].co - edge.verts[0].co).length,
                )
            )
        if not candidates:
            break
        edge = min(candidates, key=lambda item: item.index)
        collapsed.append(
            {
                "edge_index": edge.index,
                "length": (edge.verts[1].co - edge.verts[0].co).length,
            }
        )
        bmesh.ops.collapse(bm, edges=[edge], uvs=False)
    stats["degenerate_strip_port_collapses"] = collapsed


# 仅填充 regular strips 后形成的局部 simple cyclic holes；拒绝开放或分支 Boundary。
# bm/ports/stats: 当前 BMesh、Phase 3 local ports 与机器统计；返回新 Junction Faces。
def _patch_local_junction_ports(bm, ports, stats):
    open_ports = [port for port in ports if not port["is_cyclic"]]
    if open_ports:
        _fail(
            "junction_port_open",
            f"Structured Junction has {len(open_ports)} open Boundary chains",
            stats,
        )
    junction_faces = []
    patch_records = []
    for port_index, port in enumerate(ports):
        try:
            created = bmesh.ops.contextual_create(
                bm,
                geom=list(port["edges"]),
                mat_nr=0,
                use_smooth=False,
            )
            created_faces = [
                item for item in created.get("faces", []) if item.is_valid
            ]
            if not created_faces:
                raise ValueError("Local Junction port produced no Faces")
            triangulated = bmesh.ops.triangulate(
                bm,
                faces=created_faces,
                quad_method="BEAUTY",
                ngon_method="BEAUTY",
            )
            faces = [
                item for item in triangulated.get("faces", []) if item.is_valid
            ] or [face for face in created_faces if face.is_valid]
            if not faces:
                raise ValueError("Local Junction triangulation produced no Faces")
        except (ValueError, RuntimeError) as error:
            _fail(
                "junction_patch_invalid",
                f"Junction port {port_index}: {error}",
                stats,
            )
        junction_faces.extend(faces)
        patch_records.append(
            {
                "port_index": port_index,
                "boundary_edge_count": len(port["edges"]),
                "face_count": len(faces),
            }
        )
    stats["junction_patch_records"] = patch_records
    stats["junction_region_count"] = len(patch_records)
    stats["junction_patch_face_count"] = len(junction_faces)
    return junction_faces


# 删除 Patch 后沿 Boundary 重叠产生的多余非 original Faces，暴露单一待补 loop。
# bm/stats: 当前 BMesh 与统计；返回删除的 Face 数。
def _remove_overconnected_patch_faces(bm, stats):
    original_layer = bm.faces.layers.int.get(ORIGINAL_FACE_ATTRIBUTE)
    removed_faces = set()
    for edge in bm.edges:
        if len(edge.link_faces) <= 2:
            continue
        candidates = [
            face
            for face in edge.link_faces
            if original_layer is None or not bool(face[original_layer])
        ]
        while len(edge.link_faces) - len(
            [face for face in candidates if face in removed_faces]
        ) > 2 and candidates:
            face = min(
                (candidate for candidate in candidates if candidate not in removed_faces),
                key=lambda candidate: (candidate.calc_area(), candidate.index),
                default=None,
            )
            if face is None:
                break
            removed_faces.add(face)
    if removed_faces:
        bmesh.ops.delete(bm, geom=list(removed_faces), context="FACES_ONLY")
    stats["overconnected_patch_faces_removed"] = len(removed_faces)
    return len(removed_faces)


def _patch_boundaries(
    bm,
    loops,
    groups,
    pipe_trees,
    pipe_bounds,
    radius,
    junction_count,
    stats,
    debug_stage,
    boolean_rail_pairs=None,
    boolean_rail_summary=None,
    boundary_rail_topology=None,
):
    if not loops:
        _fail("ambiguous_boundary", "Difference produced no open boundary loops", stats)
    if boolean_rail_pairs is not None and debug_stage in {"REGULAR_PATCHED", "PATCHED"}:
        regular_faces = _patch_regular_rail_records(
            bm,
            boolean_rail_pairs,
            stats,
            radius,
        )
        _clean_degenerate_strip_ports(bm, radius, stats)
        _remove_overconnected_patch_faces(bm, stats)
        loose_edges = [edge for edge in bm.edges if not edge.link_faces]
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
        remaining_ports = _validate_regular_patch_ports(
            bm,
            boolean_rail_summary or {},
            boundary_rail_topology or {},
            stats,
        )
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        stats["_chamfer_faces"] = set(regular_faces)
        if debug_stage == "REGULAR_PATCHED":
            return regular_faces, []
        junction_faces = _patch_local_junction_ports(
            bm,
            remaining_ports,
            stats,
        )
        chamfer_faces = set(regular_faces + junction_faces)
        remaining_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
        seam_edges = [
            edge
            for edge in remaining_edges
            if (edge.verts[1].co - edge.verts[0].co).length
            <= max(radius * 1.0e-4, 1.0e-8)
        ]
        if seam_edges:
            bmesh.ops.collapse(bm, edges=seam_edges, uvs=False)
        remaining_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
        if remaining_edges:
            stats["junction_unresolved_boundary_edges"] = [
                {
                    "edge_index": edge.index,
                    "coordinates": [
                        tuple(round(value, 8) for value in vertex.co)
                        for vertex in edge.verts
                    ],
                    "length": (edge.verts[1].co - edge.verts[0].co).length,
                }
                for edge in remaining_edges
            ]
            _fail(
                "junction_boundary_unresolved",
                f"Local Junction Patch left {len(remaining_edges)} Boundary Edges",
                stats,
            )
        chamfer_faces = set(regular_faces + junction_faces)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        stats["_chamfer_faces"] = chamfer_faces
        return regular_faces, junction_faces
    if debug_stage == "PATCHED":
        regular_faces, junction_faces = _bridge_then_fill(
            bm,
            loops,
            groups,
            pipe_trees,
            pipe_bounds,
            radius,
            stats,
        )
        chamfer_faces = set(regular_faces + junction_faces)
        bmesh.ops.dissolve_degenerate(
            bm,
            dist=max(radius * 1.0e-6, 1.0e-9),
            edges=list(bm.edges),
        )
        stats["_chamfer_faces"] = chamfer_faces
        stats["regular_patch_face_count"] = len(chamfer_faces)
        stats["junction_patch_face_count"] = 0
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        return list(chamfer_faces), []
    regular_faces = []
    junction_faces = []
    if junction_count == 0 and len(groups) == 1 and len(loops) == 2:
        try:
            regular_faces = _zipper_bridge(bm, loops[0], loops[1])
        except (ValueError, RuntimeError) as error:
            _fail("regular_patch_invalid", str(error), stats)
        stats["regular_region_count"] = 1
    else:
        stats["junction_region_count"] = max(1, junction_count)
        stats["strip_port_count"] = max(0, 2 * len(groups))
        _fail(
            "junction_region_unresolved",
            (
                "Pipe 已完成切割，但多个倒角在拐角处相交，当前还无法自动连接并补齐这些开口；"
                "请先检查 Boolean Preview"
            ),
            stats,
        )
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    stats["regular_patch_face_count"] = len(regular_faces)
    stats["junction_patch_face_count"] = len(junction_faces)
    return regular_faces, junction_faces


# 删除临时 marker slot，并修正更高 material index。
# output: 最终 duplicate；marker_index: 临时 marker slot。
def _remove_marker_material(output, marker_index):
    output.data.materials.pop(index=marker_index)
    for polygon in output.data.polygons:
        if polygon.material_index > marker_index:
            polygon.material_index -= 1


# 将补面结果中的共面内部 Edge dissolve 为 n-gon，并返回仍然有效的 chamfer Faces。
# bm: 已完成 Bridge/Fill 的 BMesh；chamfer_faces: 本轮生成的 Faces；radius: 几何容差尺度。
def _dissolve_chamfer_faces(bm, chamfer_faces, radius):
    chamfer_faces = {face for face in chamfer_faces if face.is_valid}
    protected_edges = {
        edge
        for face in chamfer_faces
        if len(face.verts) == 3
        for edge in face.edges
        if all(len(vertex.link_edges) <= 3 for vertex in face.verts)
    }
    dissolve_edges = [
        edge
        for edge in bm.edges
        if edge not in protected_edges
        and len(edge.link_faces) == 2
        and all(face in chamfer_faces for face in edge.link_faces)
        and edge.calc_face_angle(0.0) <= math.radians(0.1)
    ]
    if dissolve_edges:
        bmesh.ops.dissolve_limit(
            bm,
            angle_limit=math.radians(0.1),
            use_dissolve_boundaries=False,
            verts=list({vertex for edge in dissolve_edges for vertex in edge.verts}),
            edges=dissolve_edges,
            delimit={"NORMAL"},
        )
    bmesh.ops.dissolve_degenerate(
        bm,
        dist=max(radius * 1.0e-6, 1.0e-9),
        edges=list(bm.edges),
    )
    original_layer = bm.faces.layers.int.get(ORIGINAL_FACE_ATTRIBUTE)
    if original_layer is None:
        return {face for face in bm.faces if face.is_valid and face in chamfer_faces}
    return {face for face in bm.faces if not bool(face[original_layer])}


# 在最终 Mesh 上创建 FACE Boolean attribute，标记自动补出的 chamfer 区域。
# output: 最终输出 Object；chamfer_face_indices: BMesh 写回后对应的 polygon indices。
def _mark_chamfer_attribute(output, chamfer_face_indices):
    attribute = output.data.attributes.get(CHAMFER_FACE_ATTRIBUTE)
    if attribute is not None:
        output.data.attributes.remove(attribute)
    attribute = output.data.attributes.new(
        CHAMFER_FACE_ATTRIBUTE,
        type="BOOLEAN",
        domain="FACE",
    )
    marked_indices = set(chamfer_face_indices)
    for polygon in output.data.polygons:
        attribute.data[polygon.index].value = polygon.index in marked_indices
    return attribute


# 按 Bevel & Transfer Normal 的既有方式从 source 传递 custom normals，修正输出 shading。
# output: PATCHED 输出；source_object: 原始 Mesh。
def _add_source_normal_transfer(output, source_object):
    modifier = output.modifiers.get(NORMAL_TRANSFER_MODIFIER)
    if modifier is None:
        modifier = output.modifiers.new(NORMAL_TRANSFER_MODIFIER, type="DATA_TRANSFER")
    modifier.object = source_object
    modifier.use_loop_data = True
    modifier.data_types_loops = {"CUSTOM_NORMAL"}
    modifier.loop_mapping = "POLYINTERP_LNORPROJ"
    return modifier


# 构建 Sharp FeatureGraph、多独立 Pipe、Collection Difference、Regular/Junction Patch。
# 参数与 Operator interface 一一对应；返回 handoff 规定的机器可读 dict。
def _build_pipe_chamfer_impl(
    source_object,
    radius,
    pipe_resolution,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    junction_margin,
    debug_stage,
    keep_debug_objects,
    *,
    feature_graph_contract="EXPERIMENTAL",
    preserve_source_visibility=False,
):
    started_at = time.perf_counter()
    stats = _base_stats(
        source_object,
        radius,
        pipe_resolution,
        chain_turn_threshold_degrees,
        chain_turn_spike_ratio,
        junction_margin,
        debug_stage,
    )
    if source_object is None or source_object.type != "MESH":
        _fail("invalid_context", "Active Object must be a Mesh", stats)
    if source_object.mode != "OBJECT":
        _fail("invalid_context", "Object Mode is required", stats)
    if any(abs(scale - 1.0) > 1.0e-4 for scale in source_object.scale):
        _fail("invalid_scale", "Object Scale must be applied", stats)
    if any(modifier.show_viewport for modifier in source_object.modifiers):
        _fail("modifiers_not_supported", "Objects with modifiers are not supported", stats)
    if debug_stage not in SUPPORTED_STAGES:
        _fail("invalid_context", f"Unsupported debug stage: {debug_stage}", stats)
    source_risks = _mesh_risk_counts(source_object)
    if source_risks["non_manifold"]:
        _fail("source_not_closed_manifold", "Source Mesh must be closed manifold", stats)

    if feature_graph_contract == "GN_PREVIEW_V1":
        groups = _build_preview_feature_graph(source_object, radius, stats)
    elif feature_graph_contract == "EXPERIMENTAL":
        stats["feature_graph_contract"] = "EXPERIMENTAL"
        groups = _build_feature_graph(
            source_object,
            chain_turn_threshold_degrees,
            chain_turn_spike_ratio,
            stats,
        )
    else:
        _fail(
            "invalid_context",
            f"Unsupported FeatureGraph contract: {feature_graph_contract}",
            stats,
        )
    stats["timings"]["feature_graph"] = time.perf_counter() - started_at
    _classify_pipe_endpoints(source_object, groups, radius)
    collection = _get_collection()
    if debug_stage == "FEATURE_GRAPH":
        stats["status"] = "finished"
        return stats

    pipes = [
        _build_pipe_mesh(source_object, group, radius, pipe_resolution, collection)
        for group in groups
    ]
    pipes_by_id = {int(pipe[PIPE_ID_TAG]): pipe for pipe in pipes}
    for strand_record in stats["cutter_strands"]:
        pipe = pipes_by_id[strand_record["strand_id"]]
        risks = _mesh_risk_counts(pipe)
        strand_record["generation_backend"] = pipe.get(
            "hst_pipe_generation_backend",
            "UNKNOWN",
        )
        strand_record["geometry_guard"] = {
            "status": (
                "PASS"
                if not risks["non_manifold"] and not risks["zero_area"]
                else "FAIL"
            ),
            **risks,
            "vertex_count": len(pipe.data.vertices),
            "face_count": len(pipe.data.polygons),
        }
    stats["timings"]["pipe_build"] = time.perf_counter() - started_at - sum(stats["timings"].values())
    stats["debug_object_names"] = [pipe.name for pipe in pipes]
    stats["pipe_endpoint_extensions"] = [
        {
            "pipe_id": int(pipe[PIPE_ID_TAG]),
            "start": float(pipe["hst_pipe_start_extension"]),
            "end": float(pipe["hst_pipe_end_extension"]),
        }
        for pipe in pipes
    ]
    stats["pipe_endpoint_classifications"] = [
        {
            "pipe_id": group["pipe_id"],
            "start": group.get("start_endpoint_class", "CYCLIC"),
            "end": group.get("end_endpoint_class", "CYCLIC"),
            "start_terminal_face_index": group.get("start_terminal_face_index"),
            "end_terminal_face_index": group.get("end_terminal_face_index"),
        }
        for group in groups
    ]
    for pipe in pipes:
        risks = _mesh_risk_counts(pipe)
        if risks["non_manifold"] or risks["zero_area"]:
            _fail(
                "pipe_not_manifold",
                f"Generated Pipe is invalid: {pipe.name}; risks={risks}",
                stats,
            )
        pipe.display_type = "WIRE"
    if debug_stage == "PIPES":
        if not preserve_source_visibility:
            _hide_source_object(source_object, stats)
        if not keep_debug_objects:
            stats["warnings"].append("PIPES stage forces debug Pipe objects to remain visible")
        stats["status"] = "finished"
        return stats

    cutter_collection, pipe_trees, pipe_bounds = _build_cutter_set(pipes, source_object, stats)
    stats["timings"]["cutter_pack"] = time.perf_counter() - started_at - sum(stats["timings"].values())
    if debug_stage == "CUTTER_UNION":
        if not preserve_source_visibility:
            _hide_source_object(source_object, stats)
        stats["status"] = "finished"
        return stats

    output = _duplicate_source(source_object, collection)
    disabled_modifier_names = [
        modifier.name for modifier in output.modifiers if not modifier.show_viewport
    ]
    for modifier_name in disabled_modifier_names:
        output.modifiers.remove(output.modifiers[modifier_name])
    stats["disabled_source_modifiers_removed"] = disabled_modifier_names
    if not preserve_source_visibility:
        _hide_source_object(source_object, stats)
    output[DEBUG_STAGE_TAG] = debug_stage
    stats["output_object_name"] = output.name
    stats["source_face_count_before_boolean"] = len(output.data.polygons)
    if debug_stage == "BOOLEAN_CUT":
        _add_difference_modifier(output, cutter_collection)
        stats["warnings"].append(
            "Boolean Modifier is left unapplied so its settings can be adjusted manually"
        )
        stats["status"] = "finished"
        _activate_object(output)
        return stats

    marker_index = _apply_difference(
        output,
        cutter_collection,
        _source_face_patch_ids(source_object),
    )
    stats["timings"]["boolean_apply"] = time.perf_counter() - started_at - sum(stats["timings"].values())
    cutter_face_indices = _groove_face_indices(output, stats)
    stats["cutter_face_count"] = len(cutter_face_indices)
    if not cutter_face_indices:
        _fail(
            "boolean_no_cutter_faces",
            (
                "Exact Collection Difference produced no cutter-derived Faces: "
                f"pipes={stats['cutter_set_object_count']}, "
                f"overlap_pairs={len(stats['pipe_overlap_pairs'])}"
            ),
            stats,
        )
    bm, loops = _open_boundary(
        output,
        cutter_face_indices,
        stats,
        radius,
        allow_non_simple=debug_stage == "OPEN_BOUNDARY",
    )
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.to_mesh(output.data)
    output.data.update()
    stats["boundary_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    boundary_rails, boundary_rail_topology = _final_boolean_boundary_rails(
        bm,
        groups,
        pipe_trees,
        pipe_bounds,
        radius,
    )
    boolean_rail_pairs, boolean_rail_summary = _extract_boolean_rail_pair_records(
        bm,
        groups,
        pipe_trees,
        pipe_bounds,
        radius,
        rails=boundary_rails,
        ownership_backend="FINAL_BOOLEAN_BOUNDARY_PIPE_SURFACE",
        pipe_overlap_pairs=stats["pipe_overlap_pairs"],
    )
    boundary_edge_by_index = {
        edge.index: edge
        for edge in bm.edges
        if len(edge.link_faces) == 1
    }
    unique_boundary_edge_indices = set(boundary_edge_by_index)
    paired_boundary_edge_indices = set(
        boolean_rail_summary["paired_boundary_edge_indices"]
    )
    occluded_boundary_edge_indices = set(
        boolean_rail_summary["occluded_boundary_edge_indices"]
    )
    consumed_boundary_edge_indices = set(
        boolean_rail_summary["consumed_boundary_edge_indices"]
    )
    shared_overlap_edge_indices = {
        segment["edge_index"]
        for segment in boundary_rail_topology["shared_owner_rails"]
    } - paired_boundary_edge_indices - occluded_boundary_edge_indices
    consumed_boundary_edge_indices.update(shared_overlap_edge_indices)
    boolean_rail_summary["shared_overlap_edge_indices"] = sorted(
        shared_overlap_edge_indices
    )
    boolean_rail_summary["consumed_boundary_edge_indices"] = sorted(
        consumed_boundary_edge_indices
    )
    candidate_missing_edge_indices = (
        unique_boundary_edge_indices - consumed_boundary_edge_indices
    )
    shared_vertex_indices = {
        vertex_index
        for segment in boundary_rail_topology["shared_owner_rails"]
        for vertex_index in segment["vertex_indices"]
    }
    shared_adjacent_chain_keys = {
        (chain["pipe_id"], chain["patch_id"], tuple(chain["edge_indices"]))
        for chain in boundary_rail_topology["owned_chains"]
        if any(
            vertex_index in shared_vertex_indices
            for vertex_index in chain["vertex_indices"]
        )
    }
    shared_seam_chain_component_indices = {
        edge_index
        for edge_index in candidate_missing_edge_indices
        if any(
            tuple(chain["edge_indices"]) == chain_edge_indices
            and chain["pipe_id"] == pipe_id
            and chain["patch_id"] == patch_id
            and edge_index in chain["edge_indices"]
            for pipe_id, patch_id, chain_edge_indices in shared_adjacent_chain_keys
            for chain in boundary_rail_topology["owned_chains"]
        )
    }
    consumed_boundary_edge_indices.update(
        shared_seam_chain_component_indices
    )
    boolean_rail_summary["shared_seam_chain_component_indices"] = sorted(
        shared_seam_chain_component_indices
    )
    boolean_rail_summary["unclassified_boundary_edge_indices"] = sorted(
        candidate_missing_edge_indices
        - shared_seam_chain_component_indices
    )
    boolean_rail_summary["consumed_boundary_edge_indices"] = sorted(
        consumed_boundary_edge_indices
    )
    missing_consumed_edge_indices = sorted(
        unique_boundary_edge_indices - consumed_boundary_edge_indices
    )
    boolean_rail_summary["boundary_consumption_guard"] = {
        "status": "PASS" if not missing_consumed_edge_indices else "FAIL",
        "boundary_edge_count": len(unique_boundary_edge_indices),
        "consumed_edge_count": len(
            unique_boundary_edge_indices & consumed_boundary_edge_indices
        ),
        "missing_edge_indices": missing_consumed_edge_indices,
        "extra_edge_indices": sorted(
            consumed_boundary_edge_indices - unique_boundary_edge_indices
        ),
        "classification_counts": {
            "paired": len(
                set(boolean_rail_summary["paired_boundary_edge_indices"])
            ),
            "occluded_endpoint": len(
                set(boolean_rail_summary["occluded_boundary_edge_indices"])
            ),
            "shared_overlap": len(shared_overlap_edge_indices),
            "shared_seam_chain_component": len(
                shared_seam_chain_component_indices
            ),
            "unclassified": len(
                candidate_missing_edge_indices
                - shared_seam_chain_component_indices
            ),
        },
    }
    boolean_rail_summary["boundary_topology"] = {
        key: value
        for key, value in boundary_rail_topology.items()
        if key not in {"owned_chains", "unowned_segments"}
    }
    surface_rail_pairs, surface_rail_summary = (
        _extract_source_surface_offset_rail_records(
            source_object,
            groups,
            radius,
        )
    )
    stats["boolean_rail_pairs"] = boolean_rail_pairs
    stats["boundary_rail_topology"] = boundary_rail_topology
    stats["surface_offset_rail_pairs"] = surface_rail_pairs
    stats["rail_oracle_summary"] = {
        "boolean": boolean_rail_summary,
        "source_surface": surface_rail_summary,
    }
    if debug_stage == "OPEN_BOUNDARY":
        bm.free()
        stats["status"] = "finished"
    else:
        junction_count = stats["topology_junction_count"] + stats["spatial_junction_count"]
        patch_boolean_result(
            legacy_context={
                "bm": bm,
                "loops": loops,
                "groups": groups,
                "pipe_trees": pipe_trees,
                "pipe_bounds": pipe_bounds,
                "radius": radius,
                "junction_count": junction_count,
                "stats": stats,
                "debug_stage": debug_stage,
                "patch_callable": _patch_boundaries,
                "boolean_rail_pairs": boolean_rail_pairs,
                "boolean_rail_summary": boolean_rail_summary,
                "boundary_rail_topology": boundary_rail_topology,
            }
        )
        stats["boundary_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
        stats["non_manifold_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
        stats["zero_area_face_count"] = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)

        if debug_stage == "PATCHED" and stats["boundary_edge_count_after"]:
            loose_shells = []
            boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
            while boundary_edges:
                seed = boundary_edges.pop()
                component = {seed}
                stack = [seed]
                while stack:
                    edge = stack.pop()
                    for vertex in edge.verts:
                        for neighbor in vertex.link_edges:
                            if neighbor in boundary_edges and len(neighbor.link_faces) == 1:
                                boundary_edges.remove(neighbor)
                                component.add(neighbor)
                                stack.append(neighbor)
                component_faces = {
                    face
                    for edge in component
                    for face in edge.link_faces
                }
                component_face_edges = {
                    edge
                    for face in component_faces
                    for edge in face.edges
                }
                if component_face_edges == component:
                    loose_shells.extend(component_faces)
            if loose_shells:
                loose_shell_faces = set(loose_shells)
                original_layer = bm.faces.layers.int.get(ORIGINAL_FACE_ATTRIBUTE)
                if original_layer is not None and any(
                    bool(face[original_layer])
                    for face in loose_shell_faces
                ):
                    _fail(
                        "result_not_manifold",
                        "PATCHED cleanup found a detached original Surface Patch",
                        stats,
                    )
                bmesh.ops.delete(
                    bm,
                    geom=list(loose_shell_faces),
                    context="FACES",
                )
                stats["loose_shell_cleanup_count"] = len(loose_shell_faces)
                stats["boundary_edge_count_after"] = sum(
                    1 for edge in bm.edges if len(edge.link_faces) == 1
                )
                stats["non_manifold_edge_count_after"] = sum(
                    1 for edge in bm.edges if len(edge.link_faces) != 2
                )
                stats["zero_area_face_count"] = sum(
                    1 for face in bm.faces if face.calc_area() <= 1.0e-12
                )
        if debug_stage == "PATCHED" and stats["zero_area_face_count"]:
            removed_zero_faces = 0
            for _ in range(12):
                zero_area_faces = [
                    face for face in bm.faces if face.calc_area() <= 1.0e-12
                ]
                if not zero_area_faces:
                    break
                removed_zero_faces += len(zero_area_faces)
                collapse_edges = {
                    min(
                        face.edges,
                        key=lambda edge: (edge.verts[1].co - edge.verts[0].co).length,
                    )
                    for face in zero_area_faces
                    if face.is_valid and face.edges
                }
                if not collapse_edges:
                    break
                bmesh.ops.collapse(bm, edges=list(collapse_edges), uvs=False)
            stats["zero_area_faces_removed"] = removed_zero_faces
            stats["boundary_edge_count_after"] = sum(
                1 for edge in bm.edges if len(edge.link_faces) == 1
            )
            stats["non_manifold_edge_count_after"] = sum(
                1 for edge in bm.edges if len(edge.link_faces) != 2
            )
            stats["zero_area_face_count"] = sum(
                1 for face in bm.faces if face.calc_area() <= 1.0e-12
            )
        if debug_stage == "PATCHED" and (
            not stats["boundary_edge_count_after"]
            and not stats["non_manifold_edge_count_after"]
            and stats["zero_area_face_count"]
            and stats["zero_area_face_count"] <= 2
        ):
            residual_sliver_faces = [
                face for face in bm.faces if face.calc_area() <= 1.0e-12
            ]
            for face in residual_sliver_faces:
                if not face.is_valid:
                    continue
                shortest_edge = min(
                    face.edges,
                    key=lambda edge: (edge.verts[1].co - edge.verts[0].co).length,
                )
                bmesh.ops.collapse(bm, edges=[shortest_edge], uvs=False)
            stats["boundary_edge_count_after"] = sum(
                1 for edge in bm.edges if len(edge.link_faces) == 1
            )
            stats["non_manifold_edge_count_after"] = sum(
                1 for edge in bm.edges if len(edge.link_faces) != 2
            )
            stats["zero_area_face_count"] = sum(
                1 for face in bm.faces if face.calc_area() <= 1.0e-12
            )
        if debug_stage == "PATCHED" and (
            stats["boundary_edge_count_after"]
            or stats["non_manifold_edge_count_after"]
            or stats["zero_area_face_count"]
        ):
            stats["invalid_edges_after"] = [
                {
                    "edge_index": edge.index,
                    "vertex_indices": [vertex.index for vertex in edge.verts],
                    "linked_face_indices": [face.index for face in edge.link_faces],
                    "linked_face_vertex_indices": [
                        [vertex.index for vertex in face.verts]
                        for face in edge.link_faces
                    ],
                }
                for edge in bm.edges
                if len(edge.link_faces) != 2
            ]
            stats.pop("_chamfer_faces", None)
            bm.free()
            _fail("result_not_manifold", "PATCHED result failed topology validation", stats)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        chamfer_face_indices = [
            face.index
            for face in stats.pop("_chamfer_faces", [])
            if face.is_valid
        ]
        bm.to_mesh(output.data)
        bm.free()
        output.data.update()
        _remove_marker_material(output, marker_index)
        if debug_stage == "PATCHED":
            _mark_chamfer_attribute(output, chamfer_face_indices)
            _add_source_normal_transfer(output, source_object)
            stats["chamfer_face_count"] = len(chamfer_face_indices)
            stats["normal_transfer_modifier"] = NORMAL_TRANSFER_MODIFIER
        stats["status"] = "finished"

    if not keep_debug_objects and debug_stage not in {"PIPES", "CUTTER_UNION"}:
        for debug_object in pipes:
            if debug_object.name in bpy.data.objects:
                bpy.data.objects.remove(debug_object, do_unlink=True)
        if cutter_collection.name in bpy.data.collections:
            bpy.data.collections.remove(cutter_collection)
        stats["debug_object_names"] = []
    _activate_object(output)
    stats["timings"]["total"] = time.perf_counter() - started_at
    return stats


# 事务式运行 Pipe Chamfer：失败时清理本轮资源，成功后才替换同 source 的旧结果。
# 参数与 _build_pipe_chamfer_impl 一致；返回机器可读 stats。
def build_pipe_chamfer(
    source_object,
    radius,
    pipe_resolution,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    junction_margin,
    debug_stage,
    keep_debug_objects,
    *,
    feature_graph_contract="EXPERIMENTAL",
    preserve_source_visibility=False,
):
    previous_objects = set(bpy.data.objects)
    previous_collections = set(bpy.data.collections)
    previous_source_results = {
        obj for obj in previous_objects if obj.get(OUTPUT_TAG) == source_object.name
    }
    previous_cutter_collections = {
        collection
        for collection in previous_collections
        if collection.name.startswith(f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}")
    }
    source_was_hidden = source_object.hide_get()
    try:
        stats = _build_pipe_chamfer_impl(
            source_object=source_object,
            radius=radius,
            pipe_resolution=pipe_resolution,
            chain_turn_threshold_degrees=chain_turn_threshold_degrees,
            chain_turn_spike_ratio=chain_turn_spike_ratio,
            junction_margin=junction_margin,
            debug_stage=debug_stage,
            keep_debug_objects=keep_debug_objects,
            feature_graph_contract=feature_graph_contract,
            preserve_source_visibility=preserve_source_visibility,
        )
    except Exception:
        source_object.hide_set(source_was_hidden)
        for obj in list(bpy.data.objects):
            if obj not in previous_objects:
                mesh = obj.data if obj.type == "MESH" else None
                curve = obj.data if obj.type == "CURVE" else None
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh is not None and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
                if curve is not None and curve.users == 0:
                    bpy.data.curves.remove(curve)
        for collection in list(bpy.data.collections):
            if collection not in previous_collections:
                bpy.data.collections.remove(collection)
        bpy.context.view_layer.update()
        raise
    for obj in previous_source_results:
        if obj.name in bpy.data.objects:
            mesh = obj.data if obj.type == "MESH" else None
            curve = obj.data if obj.type == "CURVE" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            if curve is not None and curve.users == 0:
                bpy.data.curves.remove(curve)
    for collection in previous_cutter_collections:
        if collection.name in bpy.data.collections:
            bpy.data.collections.remove(collection)
    output = bpy.data.objects.get(stats.get("output_object_name") or "")
    if output is not None:
        output.name = f"{source_object.name}_PipeChamfer_TEST"
        stats["output_object_name"] = output.name
    cutter_collection = bpy.data.collections.get(stats.get("cutter_collection_name") or "")
    if cutter_collection is not None:
        cutter_collection.name = f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}"
        stats["cutter_collection_name"] = cutter_collection.name
    bpy.context.view_layer.update()
    return stats
