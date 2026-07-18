# -*- coding: utf-8 -*-
"""实验性 Pipe Chamfer 的几何实现。"""

import bpy
import bmesh
from mathutils import geometry


COLLECTION_NAME = "HST_Experimental_PipeChamfer"
MARKER_MATERIAL_NAME = "HST_PipeChamfer_Marker"
OUTPUT_TAG = "hst_experimental_pipe_chamfer_output"


def collect_feature_chains(source_object, edge_source="AUTO_SHARP", selected_edge_indices=None):
    """按 surface patch pair 把候选 Edge 拆成 maximal feature chains。

    Args:
        source_object: 输入 Mesh Object。
        edge_source: AUTO_SHARP 或 SELECTED。
        selected_edge_indices: SELECTED 模式缓存的 Edge 索引。
    """
    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    selected_edge_indices = set(selected_edge_indices or [])
    if edge_source == "SELECTED":
        candidate_edges = {edge for edge in bm.edges if edge.index in selected_edge_indices}
    else:
        sharp_attribute = source_object.data.attributes.get("sharp_edge")
        candidate_edges = {
            edge
            for edge in bm.edges
            if edge.seam
            or source_object.data.edges[edge.index].use_edge_sharp
            or (
                sharp_attribute is not None
                and bool(sharp_attribute.data[edge.index].value)
            )
        }
    manifold_edges = {edge for edge in candidate_edges if len(edge.link_faces) == 2}

    non_feature_adjacency = {}
    for edge in bm.edges:
        if edge in manifold_edges or len(edge.link_faces) != 2:
            continue
        face_a, face_b = edge.link_faces
        non_feature_adjacency.setdefault(face_a, set()).add(face_b)
        non_feature_adjacency.setdefault(face_b, set()).add(face_a)
    face_patch = {}
    patch_index = 0
    for face in bm.faces:
        if face in face_patch:
            continue
        stack = [face]
        face_patch[face] = patch_index
        while stack:
            current_face = stack.pop()
            for neighbor in non_feature_adjacency.get(current_face, ()):
                if neighbor not in face_patch:
                    face_patch[neighbor] = patch_index
                    stack.append(neighbor)
        patch_index += 1

    grouped_edges = {}
    for edge in manifold_edges:
        patch_pair = tuple(sorted(face_patch[face] for face in edge.link_faces))
        grouped_edges.setdefault(patch_pair, set()).add(edge)

    chain_results = []
    for patch_pair, group_edges in sorted(grouped_edges.items()):
        vertex_edges = {}
        for edge in group_edges:
            for vert in edge.verts:
                vertex_edges.setdefault(vert, set()).add(edge)
        remaining = set(group_edges)
        starts = sorted(
            (vert for vert, edges in vertex_edges.items() if len(edges) != 2),
            key=lambda vert: vert.index,
        )
        for start_vert in starts:
            for start_edge in sorted(vertex_edges[start_vert], key=lambda edge: edge.index):
                if start_edge not in remaining:
                    continue
                chain_results.append(_walk_feature_chain(start_vert, start_edge, vertex_edges, remaining, patch_pair))
        while remaining:
            start_edge = min(remaining, key=lambda edge: edge.index)
            start_vert = min(start_edge.verts, key=lambda vert: vert.index)
            chain_results.append(_walk_feature_chain(start_vert, start_edge, vertex_edges, remaining, patch_pair))
    bm.free()
    chain_results.sort(key=lambda chain: min(chain["edge_indices"]))
    return chain_results


def _walk_feature_chain(start_vert, start_edge, vertex_edges, remaining, patch_pair):
    """从指定 Vertex/Edge 确定性遍历一条 maximal feature chain。

    Args:
        start_vert: 起始 BMesh Vertex。
        start_edge: 起始 BMesh Edge。
        vertex_edges: 同 patch pair 的 Vertex-Edge adjacency。
        remaining: 尚未消费的 Edge 集合。
        patch_pair: chain 两侧的 surface patch pair。
    """
    vertex_indices = [start_vert.index]
    edge_indices = []
    current_vert = start_vert
    current_edge = start_edge
    while current_edge in remaining:
        remaining.remove(current_edge)
        edge_indices.append(current_edge.index)
        current_vert = current_edge.other_vert(current_vert)
        vertex_indices.append(current_vert.index)
        if current_vert is start_vert:
            break
        if len(vertex_edges[current_vert]) != 2:
            break
        current_edge = next(edge for edge in vertex_edges[current_vert] if edge.index != current_edge.index)
    return {
        "patch_pair": patch_pair,
        "edge_indices": edge_indices,
        "vertex_indices": vertex_indices[:-1] if current_vert is start_vert else vertex_indices,
        "is_cyclic": current_vert is start_vert,
    }


class PipeChamferError(RuntimeError):
    """携带稳定 error code 与机器统计的已知几何错误。

    Args:
        error_code: 稳定错误代码。
        message: 面向用户的错误信息。
        stats: 当前阶段已收集的统计。
    """

    def __init__(self, error_code, message, stats):
        super().__init__(message)
        self.error_code = error_code
        self.stats = dict(stats)
        self.stats.update(status="failed", error_code=error_code, error_message=message)


def _base_stats(source_object, selected_edge_indices, radius, pipe_resolution, debug_stage):
    """创建所有阶段共用的统计字典。

    Args:
        source_object: 输入 Mesh Object。
        selected_edge_indices: 用户缓存的 Edge 索引。
        radius: Pipe 半径。
        pipe_resolution: Pipe 截面分辨率。
        debug_stage: 当前调试阶段。
    """
    return {
        "status": "running",
        "source_object_name": source_object.name if source_object else None,
        "output_object_name": None,
        "cutter_object_name": None,
        "stage": debug_stage,
        "radius": radius,
        "pipe_resolution": pipe_resolution,
        "selected_edge_count": len(selected_edge_indices),
        "selected_vertex_count": 0,
        "source_boundary_edge_count": 0,
        "source_non_manifold_edge_count": 0,
        "pipe_face_count": 0,
        "cutter_face_count": 0,
        "marker_face_count": 0,
        "trim_loop_count": 0,
        "trim_loop_vertex_counts": [],
        "chamfer_face_count": 0,
        "boundary_edge_count_after": 0,
        "non_manifold_edge_count_after": 0,
        "zero_area_face_count_after": 0,
        "warnings": [],
    }


def _fail(error_code, message, stats):
    """抛出带上下文的已知失败。

    Args:
        error_code: 稳定错误代码。
        message: 失败说明。
        stats: 已收集的统计。
    """
    _mark_failed_outputs(stats)
    raise PipeChamferError(error_code, message, stats)


def _mark_failed_outputs(stats):
    """把后置几何失败产生的 debug 对象明确标记为 FAILED。

    Args:
        stats: 含 output/cutter 对象名的统计字典。
    """
    for key in ("output_object_name", "cutter_object_name"):
        object_name = stats.get(key)
        obj = bpy.data.objects.get(object_name) if object_name else None
        if obj is not None and not obj.name.endswith("_FAILED"):
            obj.name = f"{obj.name}_FAILED"
            stats[key] = obj.name


def _validate_and_order_path(source_object, selected_edge_indices, radius, stats):
    """验证输入并确定性提取闭合 selected edge path。

    Args:
        source_object: 输入 Mesh Object。
        selected_edge_indices: 缓存的 Edge 索引。
        radius: Pipe 半径。
        stats: 可变统计字典。
    """
    if source_object.type != "MESH":
        _fail("invalid_context", "Active Object must be a Mesh", stats)
    if any(abs(scale - 1.0) > 1.0e-4 for scale in source_object.scale):
        _fail("invalid_scale", "Object Scale must be applied", stats)
    if source_object.modifiers:
        _fail("modifiers_not_supported", "Objects with modifiers are not supported", stats)

    bm = bmesh.new()
    bm.from_mesh(source_object.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    invalid_indices = [index for index in selected_edge_indices if index < 0 or index >= len(bm.edges)]
    if invalid_indices or not selected_edge_indices:
        bm.free()
        _fail("stale_edge_indices", f"Invalid or empty Edge indices: {invalid_indices}", stats)

    source_boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    source_non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    stats["source_boundary_edge_count"] = source_boundary
    stats["source_non_manifold_edge_count"] = source_non_manifold
    if source_non_manifold:
        bm.free()
        _fail("source_not_closed_manifold", "Source Mesh must be closed manifold", stats)

    selected_edges = [bm.edges[index] for index in sorted(selected_edge_indices)]
    for edge in selected_edges:
        if len(edge.link_faces) != 2:
            bm.free()
            _fail("selected_edge_not_manifold", f"Selected Edge {edge.index} is not manifold", stats)

    adjacency = {}
    for edge in selected_edges:
        for vert in edge.verts:
            adjacency.setdefault(vert.index, []).append(edge)
    stats["selected_vertex_count"] = len(adjacency)
    if any(len(edges) != 2 for edges in adjacency.values()):
        bm.free()
        _fail("selection_not_closed_loop", "Selection must be one closed degree-2 Edge loop", stats)

    start_vertex_index = min(adjacency)
    ordered_vertex_indices = [start_vertex_index]
    visited_edges = set()
    current_vertex_index = start_vertex_index
    previous_edge_index = None
    while True:
        candidates = sorted(
            (edge for edge in adjacency[current_vertex_index] if edge.index != previous_edge_index),
            key=lambda edge: edge.index,
        )
        next_edge = next((edge for edge in candidates if edge.index not in visited_edges), None)
        if next_edge is None:
            break
        visited_edges.add(next_edge.index)
        next_vertex = next(vert for vert in next_edge.verts if vert.index != current_vertex_index)
        previous_edge_index = next_edge.index
        current_vertex_index = next_vertex.index
        if current_vertex_index == start_vertex_index:
            break
        ordered_vertex_indices.append(current_vertex_index)

    if len(visited_edges) != len(selected_edges) or current_vertex_index != start_vertex_index:
        bm.free()
        _fail("selection_disconnected", "Selected edges do not form one connected closed loop", stats)

    points = [bm.verts[index].co.copy() for index in ordered_vertex_indices]
    segment_lengths = [(points[(index + 1) % len(points)] - point).length for index, point in enumerate(points)]
    min_segment_length = min(segment_lengths)
    stats["path_length"] = sum(segment_lengths)
    stats["min_segment_length"] = min_segment_length
    min_non_adjacent_distance = float("inf")
    segment_count = len(points)
    for index_a in range(segment_count):
        for index_b in range(index_a + 1, segment_count):
            if index_b in {index_a, (index_a + 1) % segment_count} or index_a == (index_b + 1) % segment_count:
                continue
            closest = geometry.intersect_line_line(
                points[index_a], points[(index_a + 1) % segment_count],
                points[index_b], points[(index_b + 1) % segment_count],
            )
            if closest is not None:
                _, factor_a = geometry.intersect_point_line(
                    closest[0], points[index_a], points[(index_a + 1) % segment_count]
                )
                _, factor_b = geometry.intersect_point_line(
                    closest[1], points[index_b], points[(index_b + 1) % segment_count]
                )
                if 0.0 <= factor_a <= 1.0 and 0.0 <= factor_b <= 1.0:
                    min_non_adjacent_distance = min(min_non_adjacent_distance, (closest[0] - closest[1]).length)
            for point, segment_start, segment_end in (
                (points[index_a], points[index_b], points[(index_b + 1) % segment_count]),
                (points[(index_a + 1) % segment_count], points[index_b], points[(index_b + 1) % segment_count]),
                (points[index_b], points[index_a], points[(index_a + 1) % segment_count]),
                (points[(index_b + 1) % segment_count], points[index_a], points[(index_a + 1) % segment_count]),
            ):
                projected, factor = geometry.intersect_point_line(point, segment_start, segment_end)
                factor = max(0.0, min(1.0, factor))
                clamped = segment_start.lerp(segment_end, factor)
                min_non_adjacent_distance = min(min_non_adjacent_distance, (point - clamped).length)
    stats["min_non_adjacent_distance"] = (
        None if min_non_adjacent_distance == float("inf") else min_non_adjacent_distance
    )
    bm.free()
    if radius * 2.0 >= min_segment_length:
        _fail("radius_exceeds_clearance", "Pipe diameter must be smaller than every path segment", stats)
    if min_non_adjacent_distance != float("inf") and radius * 2.0 >= min_non_adjacent_distance:
        _fail("radius_exceeds_clearance", "Pipe diameter exceeds non-adjacent path clearance", stats)
    return points


def _get_collection():
    """获取或创建实验结果 Collection。"""
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _remove_previous_result(source_object):
    """仅清理同一 source 由本 operator 创建的上次结果，支持 redo。

    Args:
        source_object: 当前输入 Mesh Object。
    """
    for obj in list(bpy.data.objects):
        if obj.get(OUTPUT_TAG) == source_object.name:
            bpy.data.objects.remove(obj, do_unlink=True)


def _duplicate_source(source_object, collection):
    """复制 source Object 与 Mesh Data 到实验 Collection。

    Args:
        source_object: 输入 Mesh Object。
        collection: 目标 Collection。
    """
    output = source_object.copy()
    output.data = source_object.data.copy()
    output.name = f"{source_object.name}_PipeChamfer_TEST"
    output[OUTPUT_TAG] = source_object.name
    collection.objects.link(output)
    return output


def _build_feature_chamfer_bevel(source_object, feature_edge_indices, radius, pipe_resolution, collection):
    """在 source duplicate 上对全部 feature Edge 一次执行 Mesh bevel。

    Args:
        source_object: 输入 Mesh Object。
        feature_edge_indices: 自动收集的全部 feature Edge 索引。
        radius: Chamfer 宽度。
        pipe_resolution: 输出横向分段数；0 代表单 span chamfer。
        collection: 目标 Collection。
    """
    output = _duplicate_source(source_object, collection)
    output.name = f"{source_object.name}_FeatureChamfer_TEST"
    bevel_attribute_name = "hst_feature_chamfer_weight"
    bevel_attribute = output.data.attributes.new(bevel_attribute_name, type="FLOAT", domain="EDGE")
    feature_edge_indices = set(feature_edge_indices)
    for edge in output.data.edges:
        bevel_attribute.data[edge.index].value = 1.0 if edge.index in feature_edge_indices else 0.0
    modifier = output.modifiers.new("HST Feature Chamfer", type="BEVEL")
    modifier.limit_method = "WEIGHT"
    modifier.edge_weight = bevel_attribute_name
    modifier.width = radius
    modifier.segments = max(1, pipe_resolution + 1)
    modifier.affect = "EDGES"
    modifier.harden_normals = False
    modifier.loop_slide = True
    if hasattr(modifier, "clamp_overlap"):
        modifier.clamp_overlap = False
    bpy.ops.object.select_all(action="DESELECT")
    output.select_set(True)
    bpy.context.view_layer.objects.active = output
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    output.data.attributes.remove(output.data.attributes[bevel_attribute_name])
    return output


def build_feature_chamfer(
    source_object,
    radius,
    pipe_resolution,
    edge_source="AUTO_SHARP",
    selected_edge_indices=None,
):
    """一次处理整个对象的 Sharp/Seam feature graph。

    Args:
        source_object: Active Mesh Object。
        radius: Chamfer 宽度。
        pipe_resolution: 横向额外分段控制。
        edge_source: AUTO_SHARP 或 SELECTED。
        selected_edge_indices: SELECTED 模式缓存的 Edge 索引。
    """
    stats = _base_stats(source_object, selected_edge_indices or [], radius, pipe_resolution, "RECONSTRUCT")
    stats["edge_source"] = edge_source
    if source_object.type != "MESH":
        _fail("invalid_context", "Active Object must be a Mesh", stats)
    if any(abs(scale - 1.0) > 1.0e-4 for scale in source_object.scale):
        _fail("invalid_scale", "Object Scale must be applied", stats)
    if source_object.modifiers:
        _fail("modifiers_not_supported", "Objects with modifiers are not supported", stats)
    chains = collect_feature_chains(source_object, edge_source, selected_edge_indices)
    if not chains:
        _fail("no_feature_edges", "No manifold Sharp/Seam feature Edges found", stats)
    feature_edge_indices = sorted({edge_index for chain in chains for edge_index in chain["edge_indices"]})
    stats["selected_edge_count"] = len(feature_edge_indices)
    stats["feature_chain_count"] = len(chains)
    stats["closed_chain_count"] = sum(1 for chain in chains if chain["is_cyclic"])
    stats["open_chain_count"] = sum(1 for chain in chains if not chain["is_cyclic"])
    stats["feature_chains"] = chains
    candidate_vertex_degree = {}
    for edge_index in feature_edge_indices:
        edge = source_object.data.edges[edge_index]
        for vertex_index in edge.vertices:
            candidate_vertex_degree[vertex_index] = candidate_vertex_degree.get(vertex_index, 0) + 1
    junction_vertex_indices = sorted(
        vertex_index for vertex_index, degree in candidate_vertex_degree.items() if degree > 2
    )
    boundary_candidate_edge_indices = sorted(
        edge.index
        for edge in source_object.data.edges
        if (edge.use_edge_sharp or edge.use_seam)
        and edge.index not in feature_edge_indices
    )
    stats["junction_vertex_count"] = len(junction_vertex_indices)
    stats["junction_vertex_indices"] = junction_vertex_indices
    stats["skipped_edge_count"] = len(boundary_candidate_edge_indices)
    stats["skipped_edge_indices"] = boundary_candidate_edge_indices
    stats["warnings"] = []
    if junction_vertex_indices:
        stats["warnings"].append("junction corners are resolved by Blender Bevel")
    if boundary_candidate_edge_indices:
        stats["warnings"].append("boundary/non-manifold Sharp or Seam edges were skipped")
    _remove_previous_result(source_object)
    collection = _get_collection()
    output = _build_feature_chamfer_bevel(
        source_object, feature_edge_indices, radius, pipe_resolution, collection
    )
    risks = _mesh_risk_counts(output)
    stats["output_object_name"] = output.name
    stats["boundary_edge_count_after"] = risks["boundary"]
    stats["non_manifold_edge_count_after"] = risks["non_manifold"]
    stats["zero_area_face_count_after"] = risks["zero_area"]
    stats["chamfer_face_count"] = max(0, len(output.data.polygons) - len(source_object.data.polygons))
    if risks["non_manifold"] or risks["zero_area"]:
        _fail("result_not_manifold", "Feature Chamfer result is not closed manifold", stats)
    bpy.ops.object.select_all(action="DESELECT")
    output.select_set(True)
    bpy.context.view_layer.objects.active = output
    stats["status"] = "finished"
    return stats


def _build_pipe(source_object, points, radius, pipe_resolution, collection):
    """用 cyclic POLY Curve 构造并转换闭合 Pipe Mesh。

    Args:
        source_object: 输入 Mesh Object，用于继承 transform。
        points: 有序闭合路径点。
        radius: Pipe 半径。
        pipe_resolution: Curve bevel 分辨率。
        collection: 目标 Collection。
    """
    curve_data = bpy.data.curves.new(f"{source_object.name}_PipeCutterCurve_TEST", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 1
    curve_data.bevel_depth = radius
    curve_data.bevel_resolution = pipe_resolution
    curve_data.use_fill_caps = True
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for spline_point, coordinate in zip(spline.points, points):
        spline_point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = True

    cutter = bpy.data.objects.new(f"{source_object.name}_PipeCutter_TEST", curve_data)
    cutter.matrix_world = source_object.matrix_world.copy()
    cutter[OUTPUT_TAG] = source_object.name
    collection.objects.link(cutter)
    bpy.ops.object.select_all(action="DESELECT")
    cutter.select_set(True)
    bpy.context.view_layer.objects.active = cutter
    bpy.ops.object.convert(target="MESH")
    cutter = bpy.context.active_object
    cutter.name = f"{source_object.name}_PipeCutter_TEST"
    return cutter


def _mesh_risk_counts(obj):
    """统计 Mesh 的 boundary、non-manifold 与 zero-area 风险。

    Args:
        obj: 待统计的 Mesh Object。
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result = {
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    return result


def _apply_boolean(output, cutter, marker_material):
    """执行 Exact Boolean Difference 并返回 marker material index。

    Args:
        output: source duplicate。
        cutter: Pipe cutter Mesh Object。
        marker_material: 唯一来源标记 Material。
    """
    if len(output.data.materials) == 0:
        base_material = bpy.data.materials.get("HST_PipeChamfer_Base") or bpy.data.materials.new(
            "HST_PipeChamfer_Base"
        )
        output.data.materials.append(base_material)
    output.data.materials.append(marker_material)
    marker_index = len(output.data.materials) - 1
    cutter.data.materials.append(marker_material)
    for polygon in cutter.data.polygons:
        polygon.material_index = 0
    modifier = output.modifiers.new("HST Experimental Pipe Exact", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.material_mode = "TRANSFER"
    modifier.object = cutter
    bpy.ops.object.select_all(action="DESELECT")
    output.select_set(True)
    bpy.context.view_layer.objects.active = output
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return marker_index


def _extract_boundary_loops(boundary_edges, stats):
    """从 marker 删除后的 boundary edges 提取确定性闭环。

    Args:
        boundary_edges: BMesh boundary Edge 集合。
        stats: 可变统计字典。
    """
    adjacency = {}
    for edge in boundary_edges:
        for vert in edge.verts:
            adjacency.setdefault(vert, []).append(edge)
    if any(len(edges) != 2 for edges in adjacency.values()):
        _fail("invalid_trim_loop", "Trim boundary is not degree-2", stats)

    remaining = set(boundary_edges)
    loops = []
    while remaining:
        start_edge = min(remaining, key=lambda edge: edge.index)
        start_vert = min(start_edge.verts, key=lambda vert: vert.index)
        loop = [start_vert]
        current_vert = start_vert
        previous_edge = None
        while True:
            candidate_edges = sorted(adjacency[current_vert], key=lambda edge: edge.index)
            edge = next((item for item in candidate_edges if item is not previous_edge and item in remaining), None)
            if edge is None:
                break
            remaining.remove(edge)
            current_vert = edge.other_vert(current_vert)
            previous_edge = edge
            if current_vert is start_vert:
                break
            loop.append(current_vert)
        if current_vert is not start_vert or len(loop) < 3:
            _fail("invalid_trim_loop", "Trim boundary is not a simple closed loop", stats)
        loops.append(loop)
    return loops


def _align_loops(loop_a, loop_b):
    """按最小配对距离选择 loop B 的方向和 cyclic offset。

    Args:
        loop_a: 第一条 trim loop Vertex 序列。
        loop_b: 第二条 trim loop Vertex 序列。
    """
    parameters_a = _normalized_loop_parameters(loop_a)
    best = None
    for candidate in (list(loop_b), list(reversed(loop_b))):
        for offset in range(len(candidate)):
            rotated = candidate[offset:] + candidate[:offset]
            parameters_b = _normalized_loop_parameters(rotated)
            cost = 0.0
            for index_a, parameter_a in enumerate(parameters_a):
                index_b = min(range(len(rotated)), key=lambda index: abs(parameters_b[index] - parameter_a))
                distance_cost = (loop_a[index_a].co - rotated[index_b].co).length_squared
                tangent_a = loop_a[(index_a + 1) % len(loop_a)].co - loop_a[index_a].co
                tangent_b = rotated[(index_b + 1) % len(rotated)].co - rotated[index_b].co
                twist_cost = 1.0 - abs(tangent_a.normalized().dot(tangent_b.normalized()))
                cost += distance_cost + twist_cost * 0.01
            if best is None or cost < best[0]:
                best = (cost, rotated)
    return best[1]


def _normalized_loop_parameters(loop):
    """计算 closed loop 每个 Vertex 的 normalized cumulative arc-length 参数。

    Args:
        loop: 有序闭合 BMesh Vertex 序列。
    """
    lengths = [(loop[(index + 1) % len(loop)].co - vert.co).length for index, vert in enumerate(loop)]
    total_length = sum(lengths)
    parameters = []
    cumulative = 0.0
    for length in lengths:
        parameters.append(cumulative / total_length)
        cumulative += length
    return parameters


def _zipper_bridge(bm, loop_a, loop_b, stats):
    """以 normalized event zipper 在两条 loop 间生成单 span strip。

    Args:
        bm: 目标 BMesh。
        loop_a: 第一条 trim loop。
        loop_b: 第二条 trim loop。
        stats: 可变统计字典。
    """
    loop_b = _align_loops(loop_a, loop_b)
    count_a = len(loop_a)
    count_b = len(loop_b)
    parameters_a = _normalized_loop_parameters(loop_a) + [1.0]
    parameters_b = _normalized_loop_parameters(loop_b) + [1.0]
    index_a = 0
    index_b = 0
    new_faces = []
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
            _fail("bridge_self_intersection", "Bridge generated a repeated-vertex Face", stats)
        try:
            face = bm.faces.new(vertices)
        except ValueError as error:
            _fail("bridge_self_intersection", f"Bridge Face creation failed: {error}", stats)
        if face.calc_area() <= 1.0e-12:
            _fail("bridge_self_intersection", "Bridge generated a zero-area Face", stats)
        new_faces.append(face)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return new_faces


def _reconstruct(output, marker_index, stats):
    """删除 marker faces、提取两条 trim loop 并 zipper bridge。

    Args:
        output: Boolean 后的输出 Mesh Object。
        marker_index: marker material slot index。
        stats: 可变统计字典。
    """
    bm = bmesh.new()
    bm.from_mesh(output.data)
    bm.edges.ensure_lookup_table()
    marker_faces = {face for face in bm.faces if face.material_index == marker_index}
    boundary_edges = {
        edge
        for edge in bm.edges
        if any(face in marker_faces for face in edge.link_faces)
        and any(face not in marker_faces for face in edge.link_faces)
    }
    bmesh.ops.delete(bm, geom=list(marker_faces), context="FACES_KEEP_BOUNDARY")
    live_boundary_edges = [edge for edge in boundary_edges if edge.is_valid and len(edge.link_faces) == 1]
    loops = _extract_boundary_loops(live_boundary_edges, stats)
    stats["trim_loop_count"] = len(loops)
    stats["trim_loop_vertex_counts"] = [len(loop) for loop in loops]
    if len(loops) != 2:
        bm.free()
        _fail("unexpected_trim_loop_count", f"Expected 2 trim loops, found {len(loops)}", stats)
    new_faces = _zipper_bridge(bm, loops[0], loops[1], stats)
    stats["chamfer_face_count"] = len(new_faces)
    stats["boundary_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    stats["non_manifold_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    stats["zero_area_face_count_after"] = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)
    if stats["non_manifold_edge_count_after"] or stats["zero_area_face_count_after"]:
        bm.free()
        _fail("result_not_manifold", "Reconstructed result is not closed manifold", stats)
    bm.to_mesh(output.data)
    bm.free()
    output.data.materials.pop(index=marker_index)
    for polygon in output.data.polygons:
        if polygon.material_index > marker_index:
            polygon.material_index -= 1


def build_experimental_pipe_chamfer(
    source_object,
    selected_edge_indices,
    radius,
    pipe_resolution,
    debug_stage,
    keep_cutter,
):
    """构建实验性 Pipe Chamfer 并返回机器可读统计。

    Args:
        source_object: Active Mesh Object。
        selected_edge_indices: Edit Mode 中缓存的 Edge 索引。
        radius: Pipe 半径，使用对象局部单位。
        pipe_resolution: Curve bevel 分辨率。
        debug_stage: PIPE_ONLY、BOOLEAN_CUT 或 RECONSTRUCT。
        keep_cutter: 完成后是否保留 debug cutter。
    """
    stats = _base_stats(source_object, selected_edge_indices, radius, pipe_resolution, debug_stage)
    points = _validate_and_order_path(source_object, selected_edge_indices, radius, stats)
    if debug_stage not in {"PIPE_ONLY", "BOOLEAN_CUT", "RECONSTRUCT"}:
        _fail("invalid_context", f"Unsupported debug stage: {debug_stage}", stats)
    _remove_previous_result(source_object)
    collection = _get_collection()
    output = _duplicate_source(source_object, collection)
    cutter = _build_pipe(source_object, points, radius, pipe_resolution, collection)
    stats["output_object_name"] = output.name
    stats["cutter_object_name"] = cutter.name
    stats["pipe_face_count"] = len(cutter.data.polygons)
    pipe_risks = _mesh_risk_counts(cutter)
    if pipe_risks["non_manifold"] or pipe_risks["zero_area"]:
        _fail("pipe_not_manifold", "Generated Pipe is not closed manifold", stats)

    if debug_stage != "PIPE_ONLY":
        marker_material = bpy.data.materials.get(MARKER_MATERIAL_NAME) or bpy.data.materials.new(MARKER_MATERIAL_NAME)
        marker_material.diffuse_color = (1.0, 0.03, 0.03, 1.0)
        marker_index = _apply_boolean(output, cutter, marker_material)
        stats["cutter_face_count"] = len(cutter.data.polygons)
        marker_face_count = sum(1 for polygon in output.data.polygons if polygon.material_index == marker_index)
        stats["marker_face_count"] = marker_face_count
        if marker_face_count == 0:
            _fail("boolean_no_marker_faces", "Exact Boolean produced no marker faces", stats)
        if debug_stage == "RECONSTRUCT":
            _reconstruct(output, marker_index, stats)

    if keep_cutter:
        cutter.display_type = "WIRE"
    else:
        bpy.data.objects.remove(cutter, do_unlink=True)
        stats["cutter_object_name"] = None
    bpy.ops.object.select_all(action="DESELECT")
    output.select_set(True)
    bpy.context.view_layer.objects.active = output
    stats["status"] = "finished"
    return stats
