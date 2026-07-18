# -*- coding: utf-8 -*-
"""实验性 Sharp FeatureGraph → 多 Pipe → Boolean → Patch 实现。"""

import math

import bpy
import bmesh
from mathutils import Matrix
from mathutils import Vector
from mathutils import geometry
from mathutils.bvhtree import BVHTree


COLLECTION_NAME = "HST_Experimental_PipeChamfer"
CUTTER_COLLECTION_SUFFIX = "_PipeCutters_TEST"
OUTPUT_TAG = "hst_experimental_pipe_chamfer_output"
PIPE_ID_TAG = "hst_pipe_id"
DEBUG_STAGE_TAG = "hst_pipe_chamfer_stage"
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
        "junction_vertex_indices": [],
        "debug_object_names": [],
        "source_hidden": False,
        "warnings": [],
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
    for obj in list(bpy.data.objects):
        if obj.get(OUTPUT_TAG) == source_object.name:
            bpy.data.objects.remove(obj, do_unlink=True)
    cutter_collection = bpy.data.collections.get(f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}")
    if cutter_collection is not None:
        bpy.data.collections.remove(cutter_collection)


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
    bpy.ops.object.select_all(action="DESELECT")
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


# 从 Sharp Edge 建 FeatureGraph，并按 patch pair、convexity、degree 与 turn spike 分 Pipe Groups。
# source_object: 输入 Mesh；threshold/spike: tangent continuity 参数；stats: 机器统计。
def _build_feature_graph(
    source_object,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    stats,
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
    for edge in sharp_edges:
        patch_pair = tuple(sorted(face_patch[face] for face in edge.link_faces))
        metadata[edge] = {
            "patch_pair": patch_pair,
            "convexity": _edge_convexity(edge),
        }
        for vertex in edge.verts:
            vertex_edges.setdefault(vertex, []).append(edge)
    for edges in vertex_edges.values():
        edges.sort(key=lambda edge: edge.index)
    topology_junctions = sorted(vertex.index for vertex, edges in vertex_edges.items() if len(edges) != 2)
    turn_by_vertex = {
        vertex: _turn_angle_degrees(edges[0], edges[1], vertex)
        for vertex, edges in vertex_edges.items()
        if len(edges) == 2
    }
    nonzero_turns = sorted(value for value in turn_by_vertex.values() if value > 1.0e-5)
    median_turn = nonzero_turns[len(nonzero_turns) // 2] if nonzero_turns else 0.0

    def can_continue(vertex, edge_a, edge_b):
        if len(vertex_edges[vertex]) != 2:
            return False
        if metadata[edge_a] != metadata[edge_b]:
            return False
        turn = turn_by_vertex[vertex]
        spike = turn / max(median_turn, 1.0e-6) if median_turn > 0.0 else float("inf")
        return not (
            turn > chain_turn_threshold_degrees
            and spike > chain_turn_spike_ratio
        )

    groups = []
    remaining = set(sharp_edges)
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        component = {seed}
        stack = [seed]
        remaining.remove(seed)
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in vertex_edges[vertex]:
                    if neighbor in remaining and can_continue(vertex, edge, neighbor):
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        component_vertex_edges = {}
        for edge in component:
            for vertex in edge.verts:
                component_vertex_edges.setdefault(vertex, []).append(edge)
        endpoints = sorted(
            (vertex for vertex, edges in component_vertex_edges.items() if len(edges) == 1),
            key=lambda vertex: vertex.index,
        )
        cyclic = not endpoints and all(len(edges) == 2 for edges in component_vertex_edges.values())
        if not cyclic and len(endpoints) != 2:
            bm.free()
            _fail("feature_group_invalid", "Pipe Group is neither an open chain nor a closed loop", stats)
        start = endpoints[0] if endpoints else min(component_vertex_edges, key=lambda vertex: vertex.index)
        ordered_vertices = [start]
        ordered_edges = []
        current = start
        previous = None
        while len(ordered_edges) < len(component):
            candidates = sorted(
                (edge for edge in component_vertex_edges[current] if edge is not previous),
                key=lambda edge: edge.index,
            )
            next_edge = next((edge for edge in candidates if edge not in ordered_edges), None)
            if next_edge is None:
                break
            ordered_edges.append(next_edge)
            current = next_edge.other_vert(current)
            previous = next_edge
            if current is start:
                break
            ordered_vertices.append(current)
        if len(ordered_edges) != len(component):
            bm.free()
            _fail("feature_group_invalid", "Pipe Group traversal did not consume every Edge", stats)
        first_edge = ordered_edges[0]
        group = {
            "pipe_id": len(groups),
            "edge_indices": [edge.index for edge in ordered_edges],
            "vertex_indices": [vertex.index for vertex in ordered_vertices],
            "points": [vertex.co.copy() for vertex in ordered_vertices],
            "is_cyclic": cyclic,
            "patch_pair": metadata[first_edge]["patch_pair"],
            "convexity": metadata[first_edge]["convexity"],
            "start_feature_degree": len(vertex_edges[ordered_vertices[0]]),
            "end_feature_degree": len(vertex_edges[ordered_vertices[0]]) if cyclic else len(vertex_edges[ordered_vertices[-1]]),
        }
        groups.append(group)
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


# 判断 Pipe 端点是否存在近似垂直于轴线的 terminal face。
# bm: source BMesh；group: Pipe Group；endpoint: start/end；返回分类与候选 Face。
def _classify_pipe_endpoint(bm, group, endpoint):
    if group["is_cyclic"]:
        return "CYCLIC", None
    endpoint_index = 0 if endpoint == "start" else -1
    neighbor_index = 1 if endpoint == "start" else -2
    edge_index = group["edge_indices"][0 if endpoint == "start" else -1]
    vertex = bm.verts[group["vertex_indices"][endpoint_index]]
    outward = (group["points"][endpoint_index] - group["points"][neighbor_index]).normalized()
    pipe_side_faces = set(bm.edges[edge_index].link_faces)
    candidates = [
        face
        for face in vertex.link_faces
        if face not in pipe_side_faces and face.normal.dot(outward) >= math.cos(math.radians(15.0))
    ]
    if len(candidates) == 1:
        return "TERMINAL_FACE", candidates[0]
    if not candidates:
        return "SURFACE_CONTINUATION", None
    return "AMBIGUOUS", None


# 按 terminal face 分类返回 Pipe 两端延长量，并把分类写入 group 供诊断。
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
    start_class, start_face = _classify_pipe_endpoint(bm, group, "start")
    end_class, end_face = _classify_pipe_endpoint(bm, group, "end")
    group["start_endpoint_class"] = start_class
    group["end_endpoint_class"] = end_class
    group["start_terminal_face_index"] = start_face.index if start_face is not None else None
    group["end_terminal_face_index"] = end_face.index if end_face is not None else None
    bm.free()
    return (
        radius if start_class == "TERMINAL_FACE" else 0.0,
        radius if end_class == "TERMINAL_FACE" else 0.0,
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
            endpoint_results = (("CYCLIC", None), ("CYCLIC", None))
        else:
            endpoint_results = (
                _classify_pipe_endpoint(bm, group, "start"),
                _classify_pipe_endpoint(bm, group, "end"),
            )
        for endpoint, (endpoint_class, terminal_face) in zip(
            ("start", "end"), endpoint_results
        ):
            group[f"{endpoint}_endpoint_class"] = endpoint_class
            group[f"{endpoint}_terminal_face_index"] = (
                terminal_face.index if terminal_face is not None else None
            )
            group[f"{endpoint}_extension"] = (
                radius if endpoint_class == "TERMINAL_FACE" else 0.0
            )
    bm.free()


# 直接生成一根 closed manifold Pipe Mesh，不调用 Curve bevel、Mesh bevel 或 Bevel modifier。
# source_object: transform 来源；group: Pipe Group；radius/resolution: 截面参数；collection: 输出位置。
def _build_pipe_mesh(source_object, group, radius, pipe_resolution, collection):
    points = [point.copy() for point in group["points"]]
    cyclic = group["is_cyclic"]
    start_extension = group.get("start_extension", 0.0)
    end_extension = group.get("end_extension", 0.0)
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


# 创建独立 Pipe cutter set，并用 BVH overlap 为空间 Junction 提供初始统计。
# pipes: 独立 Pipe Objects；source_object/stats: 输出上下文。
def _build_cutter_set(pipes, source_object, stats):
    spatial_pairs = set()
    trees = [BVHTree.FromObject(pipe, bpy.context.evaluated_depsgraph_get()) for pipe in pipes]
    for index_a, tree_a in enumerate(trees):
        for index_b in range(index_a + 1, len(trees)):
            if tree_a.overlap(trees[index_b]):
                spatial_pairs.add((index_a, index_b))
    cutter_collection = bpy.data.collections.new(f"{source_object.name}{CUTTER_COLLECTION_SUFFIX}")
    bpy.context.scene.collection.children.link(cutter_collection)
    for pipe in pipes:
        for existing_collection in list(pipe.users_collection):
            existing_collection.objects.unlink(pipe)
        cutter_collection.objects.link(pipe)
    stats["spatial_junction_count"] = len(spatial_pairs)
    stats["pipe_overlap_pairs"] = [list(pair) for pair in sorted(spatial_pairs)]
    stats["cutter_set_object_count"] = len(pipes)
    stats["cutter_collection_name"] = cutter_collection.name
    return cutter_collection, trees


# 添加可手动调整的 Cutter Collection Boolean Modifier，不 Apply、不改写 Mesh data。
# output: source duplicate；cutter_collection: 独立 Pipe 集合；返回 Boolean Modifier。
def _add_difference_modifier(output, cutter_collection):
    modifier = output.modifiers.new("HST Pipe Exact Difference", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.operand_type = "COLLECTION"
    modifier.collection = cutter_collection
    return modifier


# 为后续自动开口/补面阶段应用 Difference，并用 material marker 保留 cutter Face 线索。
# output: source duplicate；cutter_collection: 独立 Pipe 集合；返回 marker slot index。
def _apply_difference(output, cutter_collection):
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
    _activate_object(output)
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


# 删除 cutter Faces 并把 BoundaryGraph 的连通边界环提取为有序 BMVert 序列。
# output: Difference 结果；cutter_face_indices: 待删除 Face 索引；stats: 机器统计。
def _open_boundary(output, cutter_face_indices, stats):
    bm = bmesh.new()
    bm.from_mesh(output.data)
    bm.faces.ensure_lookup_table()
    to_delete = [bm.faces[index] for index in cutter_face_indices]
    bmesh.ops.delete(bm, geom=to_delete, context="FACES_KEEP_BOUNDARY")
    boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    adjacency = {}
    for edge in boundary_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    if any(len(edges) != 2 for edges in adjacency.values()):
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
            raise ValueError("Regular Strip produced a zero-area Face")
        new_faces.append(face)
    return new_faces


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
            raise ValueError("Junction Patch produced a zero-area Face")
        new_faces.append(face)
    return new_faces


# 对 BoundaryGraph 做 Regular/Junction 分区并 patch；复杂 overlap 宁可稳定失败也不伪成功。
# bm/loops: open boundary；groups: Pipe Groups；junction_count: 拓扑+空间 junction 数；stats: 统计。
def _patch_boundaries(bm, loops, groups, junction_count, stats, debug_stage):
    if not loops:
        _fail("ambiguous_boundary", "Difference produced no open boundary loops", stats)
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


# 构建 Sharp FeatureGraph、多独立 Pipe、Collection Difference、Regular/Junction Patch。
# 参数与 Operator interface 一一对应；返回 handoff 规定的机器可读 dict。
def build_pipe_chamfer(
    source_object,
    radius,
    pipe_resolution,
    chain_turn_threshold_degrees,
    chain_turn_spike_ratio,
    junction_margin,
    debug_stage,
    keep_debug_objects,
):
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
    if source_object.modifiers:
        _fail("modifiers_not_supported", "Objects with modifiers are not supported", stats)
    if debug_stage not in SUPPORTED_STAGES:
        _fail("invalid_context", f"Unsupported debug stage: {debug_stage}", stats)
    source_risks = _mesh_risk_counts(source_object)
    if source_risks["non_manifold"]:
        _fail("source_not_closed_manifold", "Source Mesh must be closed manifold", stats)

    groups = _build_feature_graph(
        source_object,
        chain_turn_threshold_degrees,
        chain_turn_spike_ratio,
        stats,
    )
    _classify_pipe_endpoints(source_object, groups, radius)
    _remove_previous_result(source_object)
    collection = _get_collection()
    if debug_stage == "FEATURE_GRAPH":
        stats["status"] = "finished"
        return stats

    pipes = [
        _build_pipe_mesh(source_object, group, radius, pipe_resolution, collection)
        for group in groups
    ]
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
            _fail("pipe_not_manifold", f"Generated Pipe is invalid: {pipe.name}", stats)
        pipe.display_type = "WIRE"
    if debug_stage == "PIPES":
        _hide_source_object(source_object, stats)
        if not keep_debug_objects:
            stats["warnings"].append("PIPES stage forces debug Pipe objects to remain visible")
        stats["status"] = "finished"
        return stats

    cutter_collection, pipe_trees = _build_cutter_set(pipes, source_object, stats)
    if debug_stage == "CUTTER_UNION":
        _hide_source_object(source_object, stats)
        stats["status"] = "finished"
        return stats

    output = _duplicate_source(source_object, collection)
    _hide_source_object(source_object, stats)
    output[DEBUG_STAGE_TAG] = debug_stage
    stats["output_object_name"] = output.name
    if debug_stage == "BOOLEAN_CUT":
        _add_difference_modifier(output, cutter_collection)
        stats["warnings"].append(
            "Boolean Modifier is left unapplied so its settings can be adjusted manually"
        )
        stats["status"] = "finished"
        _activate_object(output)
        return stats

    marker_index = _apply_difference(output, cutter_collection)
    owner_sets, ambiguous_faces = _classify_cutter_faces(output, marker_index, pipe_trees, radius)
    cutter_face_indices = sorted(owner_sets)
    stats["cutter_face_count"] = len(cutter_face_indices)
    stats["ambiguous_face_count"] = len(ambiguous_faces)
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
    if debug_stage in {"OPEN_BOUNDARY", "REGULAR_PATCHED", "PATCHED"} and ambiguous_faces:
        _fail("ambiguous_provenance", f"Could not classify cutter Faces: {ambiguous_faces}", stats)
    bm, loops = _open_boundary(output, cutter_face_indices, stats)
    stats["boundary_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    if debug_stage == "OPEN_BOUNDARY":
        bm.free()
        stats["status"] = "finished"
    else:
        junction_count = stats["topology_junction_count"] + stats["spatial_junction_count"]
        _patch_boundaries(bm, loops, groups, junction_count, stats, debug_stage)
        stats["boundary_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
        stats["non_manifold_edge_count_after"] = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
        stats["zero_area_face_count"] = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)
        if debug_stage == "PATCHED" and (
            stats["boundary_edge_count_after"]
            or stats["non_manifold_edge_count_after"]
            or stats["zero_area_face_count"]
        ):
            bm.free()
            _fail("result_not_manifold", "PATCHED result failed topology validation", stats)
        bm.to_mesh(output.data)
        bm.free()
        output.data.update()
        _remove_marker_material(output, marker_index)
        stats["status"] = "finished"

    if not keep_debug_objects and debug_stage not in {"PIPES", "CUTTER_UNION"}:
        for debug_object in pipes:
            if debug_object.name in bpy.data.objects:
                bpy.data.objects.remove(debug_object, do_unlink=True)
        if cutter_collection.name in bpy.data.collections:
            bpy.data.collections.remove(cutter_collection)
        stats["debug_object_names"] = []
    _activate_object(output)
    return stats
