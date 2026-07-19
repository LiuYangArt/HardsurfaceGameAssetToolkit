# -*- coding: utf-8 -*-
"""Feature Chamfer GN Finalize 的 cutter 提取与端点上下文。"""

import json
import math

import bpy
import bmesh
from mathutils import Vector

from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION
from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION_TAG
from ..const import FEATURE_CHAMFER_GN_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_GN_PARAMETERS_TAG
from ..const import FEATURE_CHAMFER_ORIGINAL_FACE_ATTRIBUTE
from ..const import FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE
from .experimental_pipe_chamfer_utils import _base_stats
from .experimental_pipe_chamfer_utils import _build_feature_graph
from .experimental_pipe_chamfer_utils import _classify_pipe_endpoints
from .experimental_pipe_chamfer_utils import _source_face_patch_ids
from .feature_chamfer_gn_utils import PREVIEW_VALID
from .feature_chamfer_gn_utils import live_preview_parameters
from .feature_chamfer_gn_utils import owned_preview_modifier
from .feature_chamfer_gn_utils import preview_state
from .feature_chamfer_gn_utils import source_fingerprint


ENDPOINT_CLASSES = {
    "TERMINAL_FACE",
    "JUNCTION_BRANCH",
    "SURFACE_CONTINUATION",
    "AMBIGUOUS",
    "CYCLIC",
}


class FeatureChamferFinalizeError(RuntimeError):
    """携带稳定 error code 与诊断数据的 Finalize 前置检查错误。"""

    def __init__(self, error_code, message, diagnostics=None):
        super().__init__(message)
        self.error_code = error_code
        self.diagnostics = dict(diagnostics or {})
        self.diagnostics.update(
            status="failed",
            error_code=error_code,
            error_message=message,
        )


# 统计临时 cutter Mesh 的 manifold、loose geometry 与 zero-area 风险。
# mesh: 从受控 GN Preview evaluated result 复制出的临时 Mesh data。
def _cutter_risk_counts(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    result = {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "loose_edges": sum(1 for edge in bm.edges if not edge.link_faces),
        "loose_vertices": sum(1 for vertex in bm.verts if not vertex.link_edges),
        "zero_area": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    return result


# 复制 source 与受控 modifier，并把 terminal endpoint 沿 Feature tangent 推到 source 外。
# source_object/preview_modifier: 有效 Preview；feature_groups/endpoints: FeatureGraph metadata。
def _extended_evaluation_source(
    source_object,
    preview_modifier,
    feature_groups,
    endpoints,
):
    groups_by_id = {group["pipe_id"]: group for group in feature_groups}
    applied_offsets = []
    terminal_records = [record for record in endpoints if record["class"] == "TERMINAL_FACE"]
    terminal_vertex_indices = [record["feature_vertex_index"] for record in terminal_records]
    if len(terminal_vertex_indices) != len(set(terminal_vertex_indices)):
        duplicate_vertex = next(
            index
            for index in terminal_vertex_indices
            if terminal_vertex_indices.count(index) > 1
        )
        raise FeatureChamferFinalizeError(
            "ambiguous_endpoint",
            f"Multiple terminal extension records own Feature vertex {duplicate_vertex}",
        )

    evaluation_object = source_object.copy()
    evaluation_object.data = source_object.data.copy()
    evaluation_mesh = evaluation_object.data
    evaluation_object.name = f"{source_object.name}_HSTFinalizeEvaluation"
    source_object.users_collection[0].objects.link(evaluation_object)
    try:
        evaluation_modifier = evaluation_object.modifiers.get(preview_modifier.name)
        if evaluation_modifier is None or evaluation_modifier.node_group != preview_modifier.node_group:
            raise FeatureChamferFinalizeError(
                "evaluation_modifier_missing",
                "Temporary Finalize evaluation source lost the controlled GN modifier",
            )
        for record in endpoints:
            if record["class"] not in {"TERMINAL_FACE", "JUNCTION_BRANCH"}:
                continue
            vertex_index = record["feature_vertex_index"]
            group = groups_by_id[record["group_id"]]
            endpoint_index, neighbor_index = (
                (0, 1) if record["endpoint"] == "start" else (-1, -2)
            )
            outward = (
                group["points"][endpoint_index] - group["points"][neighbor_index]
            ).normalized()
            extension = float(record["extension"])
            if record["class"] == "TERMINAL_FACE":
                evaluation_object.data.vertices[vertex_index].co += outward * extension
            else:
                mesh = evaluation_object.data
                new_vertex_index = len(mesh.vertices)
                new_edge_index = len(mesh.edges)
                mesh.vertices.add(1)
                mesh.vertices[new_vertex_index].co = group["points"][endpoint_index] + outward * extension
                mesh.edges.add(1)
                mesh.edges[new_edge_index].vertices = (vertex_index, new_vertex_index)
                sharp_attribute = mesh.attributes.get("sharp_edge")
                if sharp_attribute is None or sharp_attribute.domain != "EDGE":
                    raise FeatureChamferFinalizeError(
                        "junction_extension_attribute_missing",
                        "Junction extension requires the sharp_edge Edge attribute",
                    )
                sharp_attribute.data[new_edge_index].value = True
            applied_offsets.append(
                {
                    "group_id": record["group_id"],
                    "endpoint": record["endpoint"],
                    "feature_vertex_index": vertex_index,
                    "origin": list(group["points"][endpoint_index]),
                    "outward": list(outward),
                    "extension": extension,
                    "class": record["class"],
                }
            )
        evaluation_object.data.update()
        return evaluation_object, evaluation_modifier, applied_offsets
    except Exception:
        bpy.data.objects.remove(evaluation_object, do_unlink=True)
        if bpy.data.meshes.get(evaluation_mesh.name) == evaluation_mesh:
            bpy.data.meshes.remove(evaluation_mesh)
        raise


# 验证 cutter 确实覆盖每个 extended endpoint，避免只写 metadata 却仍保留原 round cap。
# cutter_mesh/applied_offsets/radius/voxel_size: evaluated cutter 与 extension 参数。
def _validate_terminal_extension_geometry(
    cutter_mesh,
    applied_offsets,
    radius,
    voxel_size,
):
    validations = []
    tolerance = max(float(voxel_size) * 3.0, float(radius) * 0.2)
    for offset in applied_offsets:
        origin = Vector(offset["origin"])
        outward = Vector(offset["outward"])
        extension = float(offset["extension"])
        maximum_projection = max(
            (vertex.co - origin).dot(outward)
            for vertex in cutter_mesh.vertices
        )
        required_projection = extension + float(radius) * 0.5 - tolerance
        minimum_projection = min(
            (vertex.co - origin).dot(outward)
            for vertex in cutter_mesh.vertices
        )
        validations.append(
            {
                **offset,
                "maximum_cutter_projection": maximum_projection,
                "minimum_cutter_projection": minimum_projection,
                "required_projection": required_projection,
                "validated": maximum_projection >= required_projection,
            }
        )
    return validations


# 在内部 source duplicate 上评估延长后的 SDF cutter，不改变用户可见 Preview 状态。
# source_object/preview_modifier: 有效 Preview；feature_groups/endpoints: FeatureGraph metadata。
def evaluate_feature_chamfer_cutter(
    source_object,
    preview_modifier,
    feature_groups,
    endpoints,
):
    if owned_preview_modifier(source_object) != preview_modifier:
        raise FeatureChamferFinalizeError(
            "preview_owner_mismatch",
            "Preview modifier is not owned by Feature Chamfer GN",
        )
    if preview_state(source_object) != PREVIEW_VALID:
        raise FeatureChamferFinalizeError(
            "preview_stale",
            "Feature Chamfer Preview is stale",
        )
    identifiers = {
        item.name: item.identifier
        for item in preview_modifier.node_group.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT"
    }
    show_cutter_identifier = identifiers.get("Show Cutter")
    if show_cutter_identifier is None:
        raise FeatureChamferFinalizeError(
            "asset_socket_missing",
            "Preview asset is missing Show Cutter",
        )

    source_before = source_fingerprint(source_object)
    parameters_before = live_preview_parameters(preview_modifier)
    show_cutter_before = bool(preview_modifier[show_cutter_identifier])
    cutter_mesh = None
    evaluation_object = None
    evaluation_mesh = None
    try:
        evaluation_object, evaluation_modifier, applied_offsets = _extended_evaluation_source(
            source_object,
            preview_modifier,
            feature_groups,
            endpoints,
        )
        evaluation_mesh = evaluation_object.data
        evaluation_modifier[show_cutter_identifier] = True
        evaluation_object.update_tag(refresh={"DATA"})
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        cutter_mesh = bpy.data.meshes.new_from_object(
            evaluation_object.evaluated_get(depsgraph),
            depsgraph=depsgraph,
        )
    finally:
        if evaluation_object is not None:
            bpy.data.objects.remove(evaluation_object, do_unlink=True)
        if evaluation_mesh is not None and bpy.data.meshes.get(evaluation_mesh.name) == evaluation_mesh:
            bpy.data.meshes.remove(evaluation_mesh)
        bpy.context.view_layer.update()

    if cutter_mesh is None:
        raise FeatureChamferFinalizeError(
            "cutter_evaluation_failed",
            "GN cutter evaluation returned no Mesh",
        )
    risks = _cutter_risk_counts(cutter_mesh)
    extension_validations = _validate_terminal_extension_geometry(
        cutter_mesh,
        applied_offsets,
        parameters_before["radius"],
        parameters_before["voxel_size"],
    )
    source_after = source_fingerprint(source_object)
    parameters_after = live_preview_parameters(preview_modifier)
    invariant_diagnostics = {
        "cutter": risks,
        "preview_show_cutter_restored": parameters_after["show_cutter"] == show_cutter_before,
        "preview_parameters_unchanged": parameters_after == parameters_before,
        "source_fingerprint_unchanged": source_after == source_before,
        "terminal_extension_validations": extension_validations,
        "endpoint_extension_geometry_validated": all(
            validation["validated"] for validation in extension_validations
        ),
    }
    if not all(
        invariant_diagnostics[key]
        for key in (
            "preview_show_cutter_restored",
            "preview_parameters_unchanged",
            "source_fingerprint_unchanged",
        )
    ):
        bpy.data.meshes.remove(cutter_mesh)
        raise FeatureChamferFinalizeError(
            "cutter_evaluation_mutated_preview",
            "GN cutter evaluation changed source or visible Preview state",
            invariant_diagnostics,
        )
    if risks["faces"] == 0:
        bpy.data.meshes.remove(cutter_mesh)
        raise FeatureChamferFinalizeError(
            "cutter_empty",
            "GN cutter is empty",
            invariant_diagnostics,
        )
    if risks["non_manifold"] or risks["zero_area"]:
        bpy.data.meshes.remove(cutter_mesh)
        raise FeatureChamferFinalizeError(
            "cutter_invalid",
            "GN cutter must be closed manifold and contain no zero-area Faces",
            invariant_diagnostics,
        )
    if not invariant_diagnostics["endpoint_extension_geometry_validated"]:
        bpy.data.meshes.remove(cutter_mesh)
        raise FeatureChamferFinalizeError(
            "terminal_extension_not_in_cutter",
            "Evaluated GN cutter does not cover every terminal extension",
            invariant_diagnostics,
        )
    return cutter_mesh, invariant_diagnostics


# 复用 source Sharp FeatureGraph，生成与 SDF cutter 对应的 endpoint/region ownership metadata。
# source_object: Preview source；radius: live GN Radius；返回 groups 与可序列化端点记录。
def build_feature_chamfer_endpoint_context(source_object, radius):
    stats = _base_stats(source_object, radius, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = _build_feature_graph(source_object, 35.0, 3.0, stats)
    _classify_pipe_endpoints(source_object, groups, radius)
    endpoint_records = []
    for group in groups:
        if group["is_cyclic"]:
            endpoint_records.append(
                {
                    "group_id": group["pipe_id"],
                    "endpoint": "cyclic",
                    "class": "CYCLIC",
                    "feature_vertex_index": None,
                    "feature_degree": 2,
                    "patch_pair": list(group["patch_pair"]),
                    "extension": 0.0,
                    "terminal_face_index": None,
                }
            )
            continue
        for endpoint, vertex_offset in (("start", 0), ("end", -1)):
            endpoint_class = group[f"{endpoint}_endpoint_class"]
            feature_degree = group[f"{endpoint}_feature_degree"]
            if feature_degree > 2:
                endpoint_class = "JUNCTION_BRANCH"
                angle = float(group.get(f"{endpoint}_angle", 0.0))
                extension = min(
                    radius / max(math.sin(angle / 2.0), 1.0e-6)
                    + radius * 0.25,
                    radius * 3.0,
                )
            else:
                extension = float(group.get(f"{endpoint}_extension", 0.0))
            terminal_face_index = group.get(f"{endpoint}_terminal_face_index")
            if endpoint_class == "TERMINAL_FACE" and terminal_face_index is not None:
                endpoint_index = 0 if endpoint == "start" else -1
                neighbor_index = 1 if endpoint == "start" else -2
                outward = (
                    group["points"][endpoint_index]
                    - group["points"][neighbor_index]
                ).normalized()
                terminal_normal = source_object.data.polygons[terminal_face_index].normal
                support = abs(terminal_normal.dot(outward))
                if support <= math.cos(math.radians(15.0)):
                    endpoint_class = "AMBIGUOUS"
                    extension = 0.0
                else:
                    # 球形 cap 在 terminal Face 法线方向的 support radius 必须整体越过平面。
                    extension = radius / support + radius * 0.1
            if endpoint_class not in ENDPOINT_CLASSES:
                endpoint_class = "AMBIGUOUS"
            endpoint_records.append(
                {
                    "group_id": group["pipe_id"],
                    "endpoint": endpoint,
                    "class": endpoint_class,
                    "feature_vertex_index": group["vertex_indices"][vertex_offset],
                    "feature_degree": feature_degree,
                    "patch_pair": list(group["patch_pair"]),
                    "extension": extension,
                    "terminal_face_index": terminal_face_index,
                }
            )
    return groups, endpoint_records, stats


# 在 Boolean 前给 source Faces 写 original marker 与 Surface Patch ID。
# mesh/source_patch_ids: source duplicate Mesh 与 polygon index 对应的 Patch ID。
def _mark_tracked_boolean_source(mesh, source_patch_ids):
    original_attribute = mesh.attributes.get(FEATURE_CHAMFER_ORIGINAL_FACE_ATTRIBUTE)
    if original_attribute is not None:
        mesh.attributes.remove(original_attribute)
    original_attribute = mesh.attributes.new(
        FEATURE_CHAMFER_ORIGINAL_FACE_ATTRIBUTE,
        type="BOOLEAN",
        domain="FACE",
    )
    for value in original_attribute.data:
        value.value = True

    patch_attribute = mesh.attributes.get(FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE)
    if patch_attribute is not None:
        mesh.attributes.remove(patch_attribute)
    patch_attribute = mesh.attributes.new(
        FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE,
        type="INT",
        domain="FACE",
    )
    for polygon in mesh.polygons:
        patch_attribute.data[polygon.index].value = int(source_patch_ids[polygon.index])


# 对 source duplicate 与 evaluated GN cutter 执行 Exact Difference，并保留 Face provenance。
# source_object/cutter_mesh/source_patch_ids: 不可修改的 source、临时 cutter 与 Surface Patch IDs。
def tracked_boolean_difference(source_object, cutter_mesh, source_patch_ids):
    collection = source_object.users_collection[0]
    boolean_object = source_object.copy()
    boolean_object.data = source_object.data.copy()
    boolean_object.name = f"{source_object.name}_HSTTrackedBoolean"
    collection.objects.link(boolean_object)
    for modifier in list(boolean_object.modifiers):
        boolean_object.modifiers.remove(modifier)
    _mark_tracked_boolean_source(boolean_object.data, source_patch_ids)

    cutter_object = bpy.data.objects.new(
        f"{source_object.name}_HSTTrackedCutter",
        cutter_mesh.copy(),
    )
    cutter_object.matrix_world = source_object.matrix_world.copy()
    collection.objects.link(cutter_object)
    boolean_mesh = None
    boolean_source_mesh = boolean_object.data
    cutter_object_mesh = cutter_object.data
    try:
        modifier = boolean_object.modifiers.new("HST Feature Chamfer Tracked Difference", "BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.solver = "EXACT"
        modifier.operand_type = "OBJECT"
        modifier.object = cutter_object
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        boolean_mesh = bpy.data.meshes.new_from_object(
            boolean_object.evaluated_get(depsgraph),
            depsgraph=depsgraph,
        )
    finally:
        bpy.data.objects.remove(boolean_object, do_unlink=True)
        bpy.data.objects.remove(cutter_object, do_unlink=True)
        if bpy.data.meshes.get(boolean_source_mesh.name) == boolean_source_mesh:
            bpy.data.meshes.remove(boolean_source_mesh)
        if bpy.data.meshes.get(cutter_object_mesh.name) == cutter_object_mesh:
            bpy.data.meshes.remove(cutter_object_mesh)

    if boolean_mesh is None or not boolean_mesh.polygons:
        if boolean_mesh is not None:
            bpy.data.meshes.remove(boolean_mesh)
        raise FeatureChamferFinalizeError(
            "tracked_boolean_empty",
            "Tracked Boolean returned an empty Mesh",
        )
    original_attribute = boolean_mesh.attributes.get(FEATURE_CHAMFER_ORIGINAL_FACE_ATTRIBUTE)
    patch_attribute = boolean_mesh.attributes.get(FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE)
    if original_attribute is None or original_attribute.domain != "FACE":
        bpy.data.meshes.remove(boolean_mesh)
        raise FeatureChamferFinalizeError(
            "tracked_boolean_original_attribute_missing",
            "Tracked Boolean lost original Face provenance",
        )
    if patch_attribute is None or patch_attribute.domain != "FACE":
        bpy.data.meshes.remove(boolean_mesh)
        raise FeatureChamferFinalizeError(
            "tracked_boolean_patch_attribute_missing",
            "Tracked Boolean lost Surface Patch provenance",
        )

    original_faces = []
    groove_faces = []
    invalid_patch_faces = []
    valid_patch_ids = set(int(value) for value in source_patch_ids)
    for polygon in boolean_mesh.polygons:
        if bool(original_attribute.data[polygon.index].value):
            original_faces.append(polygon.index)
            patch_id = int(patch_attribute.data[polygon.index].value)
            if patch_id not in valid_patch_ids:
                invalid_patch_faces.append(polygon.index)
        else:
            groove_faces.append(polygon.index)
    face_count = len(boolean_mesh.polygons)
    diagnostics = {
        "faces": face_count,
        "original_faces": len(original_faces),
        "groove_faces": len(groove_faces),
        "ambiguous_faces": len(invalid_patch_faces),
        "coverage": (len(original_faces) + len(groove_faces)) / face_count,
        "original_patch_coverage": (
            (len(original_faces) - len(invalid_patch_faces)) / len(original_faces)
            if original_faces else 0.0
        ),
        "risks": _cutter_risk_counts(boolean_mesh),
    }
    if not groove_faces:
        bpy.data.meshes.remove(boolean_mesh)
        raise FeatureChamferFinalizeError(
            "tracked_boolean_no_groove_faces",
            "Tracked Boolean produced no cutter-derived groove Faces",
            {"tracked_boolean": diagnostics},
        )
    if diagnostics["coverage"] != 1.0 or invalid_patch_faces:
        bpy.data.meshes.remove(boolean_mesh)
        raise FeatureChamferFinalizeError(
            "tracked_boolean_ambiguous_provenance",
            "Tracked Boolean provenance coverage is incomplete",
            {"tracked_boolean": diagnostics},
        )
    return boolean_mesh, groove_faces, diagnostics


# 把 Boundary Edges 拆成按共享 Vertex 连通的组件，并读取两侧原面 Patch ownership。
# bm/boundary_edges/patch_layer: 已删除 groove Faces 的 BMesh、Boundary Edge 集合与 Face Patch layer。
def _boundary_components(bm, boundary_edges, patch_layer):
    remaining = set(boundary_edges)
    components = []
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        component_edges = {seed}
        component_vertices = set(seed.verts)
        stack = [seed]
        remaining.remove(seed)
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                linked = [candidate for candidate in vertex.link_edges if candidate in remaining]
                for candidate in linked:
                    remaining.remove(candidate)
                    component_edges.add(candidate)
                    component_vertices.update(candidate.verts)
                    stack.append(candidate)
        degrees = {
            vertex.index: sum(1 for edge in vertex.link_edges if edge in component_edges)
            for vertex in component_vertices
        }
        adjacent_patch_ids = sorted(
            {
                int(face[patch_layer])
                for edge in component_edges
                for face in edge.link_faces
            }
        )
        components.append(
            {
                "edge_indices": sorted(edge.index for edge in component_edges),
                "vertex_indices": sorted(vertex.index for vertex in component_vertices),
                "edge_count": len(component_edges),
                "vertex_count": len(component_vertices),
                "endpoint_count": sum(1 for degree in degrees.values() if degree == 1),
                "branch_vertex_count": sum(1 for degree in degrees.values() if degree > 2),
                "is_cyclic": bool(degrees) and all(degree == 2 for degree in degrees.values()),
                "adjacent_patch_ids": adjacent_patch_ids,
                "_points": [
                    vertex.co.copy()
                    for vertex in sorted(component_vertices, key=lambda item: item.index)
                ],
            }
        )
    return components


# 返回 point 到 Feature group polyline 的最短距离。
# point/group: Boundary Vertex 坐标与 FeatureGraph group。
def _point_group_distance(point, group):
    points = group["points"]
    segments = list(zip(points, points[1:]))
    if group["is_cyclic"] and len(points) > 2:
        segments.append((points[-1], points[0]))
    best = float("inf")
    for start, end in segments:
        direction = end - start
        length_squared = direction.length_squared
        if length_squared <= 1.0e-12:
            distance = (point - start).length
        else:
            factor = max(0.0, min(1.0, (point - start).dot(direction) / length_squared))
            distance = (point - (start + direction * factor)).length
        best = min(best, distance)
    return best


# 计算 Boundary component 到 Feature group 的稳健平均距离，避免仅靠 Surface Patch ID 猜 owner。
# component/group: Boundary component 与候选 FeatureGraph group。
def _component_group_distance(component, group):
    points = component["_points"]
    stride = max(1, len(points) // 32)
    samples = points[::stride][:32]
    distances = sorted(_point_group_distance(point, group) for point in samples)
    keep_count = max(1, len(distances) // 2)
    return sum(distances[:keep_count]) / keep_count


# 返回多个 Feature groups 是否在同一个拓扑 junction Vertex 相接。
# group_ids/group_by_id: 待验证 owner IDs 与 FeatureGraph lookup。
def _groups_share_junction(group_ids, group_by_id):
    endpoint_vertices = []
    for group_id in group_ids:
        group = group_by_id[group_id]
        if group["is_cyclic"]:
            return False
        endpoint_vertices.append(
            {group["vertex_indices"][0], group["vertex_indices"][-1]}
        )
    return bool(set.intersection(*endpoint_vertices)) if endpoint_vertices else False


# 返回多个 groups 是否属于由共享 endpoints 连通的同一个 junction region。
# group_ids/group_by_id: owner IDs 与 FeatureGraph lookup。
def _groups_form_junction_region(group_ids, group_by_id):
    adjacency = {group_id: set() for group_id in group_ids}
    endpoint_sets = {
        group_id: {
            group_by_id[group_id]["vertex_indices"][0],
            group_by_id[group_id]["vertex_indices"][-1],
        }
        for group_id in group_ids
        if not group_by_id[group_id]["is_cyclic"]
    }
    if len(endpoint_sets) != len(group_ids):
        return False
    for index, group_id_a in enumerate(group_ids):
        for group_id_b in group_ids[index + 1:]:
            if endpoint_sets[group_id_a] & endpoint_sets[group_id_b]:
                adjacency[group_id_a].add(group_id_b)
                adjacency[group_id_b].add(group_id_a)
    visited = set()
    stack = [group_ids[0]] if group_ids else []
    while stack:
        group_id = stack.pop()
        if group_id in visited:
            continue
        visited.add(group_id)
        stack.extend(adjacency[group_id] - visited)
    return len(visited) == len(group_ids)


# 根据明确的 Surface Patch pair 和 Feature endpoint metadata 给 Boundary components 分配 owner。
# components/feature_groups/endpoints/radius: Boundary、FeatureGraph metadata 与当前 Radius。
def _classify_boundary_regions(components, feature_groups, endpoints, radius):
    endpoint_by_group = {}
    for endpoint in endpoints:
        endpoint_by_group.setdefault(endpoint["group_id"], []).append(endpoint)
    group_by_id = {group["pipe_id"]: group for group in feature_groups}
    regions = []
    for component_index, component in enumerate(components):
        component_patches = set(component["adjacent_patch_ids"])
        candidates = [
            group["pipe_id"]
            for group in feature_groups
            if component_patches
            and component_patches.issubset(set(group["patch_pair"]))
        ]
        if len(candidates) != 1 and len(feature_groups) == 1:
            candidates = [feature_groups[0]["pipe_id"]]
        scores = sorted(
            (
                round(_component_group_distance(component, group_by_id[group_id]), 9),
                group_id,
            )
            for group_id in candidates
        )
        if scores:
            best_score = scores[0][0]
            owner_tolerance = max(float(radius) * 0.35, 1.0e-5)
            owner_ids = [
                group_id
                for score, group_id in scores
                if score <= best_score + owner_tolerance
            ]
        else:
            best_score = None
            owner_ids = []
        owner_endpoints = [
            endpoint
            for group_id in owner_ids
            for endpoint in endpoint_by_group.get(group_id, [])
        ]
        endpoint_classes = {endpoint["class"] for endpoint in owner_endpoints}
        feature_degrees = {endpoint["feature_degree"] for endpoint in owner_endpoints}
        if not owner_ids or "AMBIGUOUS" in endpoint_classes:
            region_class = "AMBIGUOUS"
        elif len(owner_ids) > 1:
            region_class = (
                "JUNCTION"
                if (
                    _groups_share_junction(owner_ids, group_by_id)
                    or _groups_form_junction_region(owner_ids, group_by_id)
                    or "JUNCTION_BRANCH" in endpoint_classes
                )
                else "AMBIGUOUS"
            )
        elif "JUNCTION_BRANCH" in endpoint_classes or any(degree > 2 for degree in feature_degrees):
            region_class = "JUNCTION"
        elif group_by_id[owner_ids[0]]["is_cyclic"]:
            region_class = "CYCLIC_TWO_RAIL"
        elif "SURFACE_CONTINUATION" in endpoint_classes:
            region_class = "END_CAP"
        else:
            region_class = "REGULAR_TWO_RAIL"
        if component["branch_vertex_count"]:
            if region_class not in {"JUNCTION", "END_CAP"}:
                region_class = "AMBIGUOUS"
        regions.append(
            {
                "region_id": len(regions),
                "class": region_class,
                "group_ids": owner_ids,
                "component_indices": [component_index],
                "component_count": 1,
                "boundary_edge_count": component["edge_count"],
                "endpoint_classes": sorted(endpoint_classes),
                "patch_pair": component["adjacent_patch_ids"],
                "owner_distance": best_score,
            }
        )
    return regions


# 删除 tracked Boolean groove Faces 并构建显式 Boundary region records。
# boolean_mesh/groove_faces/feature_groups/endpoints: tracked Boolean 与 Feature ownership metadata。
def build_tracked_boolean_boundary_regions(
    boolean_mesh,
    groove_faces,
    feature_groups,
    endpoints,
    radius,
):
    open_mesh = boolean_mesh.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(open_mesh)
        bm.faces.ensure_lookup_table()
        patch_layer = bm.faces.layers.int.get(FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE)
        if patch_layer is None:
            raise FeatureChamferFinalizeError(
                "boundary_patch_attribute_missing",
                "BoundaryGraph source Patch ownership is missing",
            )
        bmesh.ops.delete(
            bm,
            geom=[bm.faces[index] for index in groove_faces],
            context="FACES_KEEP_BOUNDARY",
        )
        boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
        if not boundary_edges:
            raise FeatureChamferFinalizeError(
                "boundary_graph_empty",
                "Deleting groove Faces produced no BoundaryGraph",
            )
        components = _boundary_components(bm, boundary_edges, patch_layer)
        regions = _classify_boundary_regions(
            components,
            feature_groups,
            endpoints,
            radius,
        )
        classified_edge_count = sum(region["boundary_edge_count"] for region in regions)
        diagnostics = {
            "boundary_edge_count": len(boundary_edges),
            "classified_edge_count": classified_edge_count,
            "coverage": classified_edge_count / len(boundary_edges),
            "component_count": len(components),
            "region_count": len(regions),
            "ambiguous_region_count": sum(
                1 for region in regions if region["class"] == "AMBIGUOUS"
            ),
            "components": [
                {key: value for key, value in component.items() if not key.startswith("_")}
                for component in components
            ],
            "regions": regions,
        }
        bm.to_mesh(open_mesh)
    except Exception:
        bm.free()
        bpy.data.meshes.remove(open_mesh)
        raise
    bm.free()
    if diagnostics["coverage"] != 1.0 or diagnostics["ambiguous_region_count"]:
        bpy.data.meshes.remove(open_mesh)
        raise FeatureChamferFinalizeError(
            "boundary_region_ambiguous",
            "BoundaryGraph contains unowned or ambiguous regions",
            {"boundary_graph": diagnostics},
        )
    return open_mesh, regions, diagnostics


# 提取 Phase 2B Finalize context；失败时释放临时 Mesh 并保持 source/Preview 不变。
# source_object: 有效 Preview source；返回 cutter_mesh、FeatureGraph metadata 与诊断。
def extract_feature_chamfer_finalize_context(source_object):
    modifier = owned_preview_modifier(source_object)
    diagnostics = {
        "phase": "2B",
        "source_object": source_object.name,
        "source_fingerprint": source_fingerprint(source_object),
        "asset_version": modifier.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) if modifier else None,
        "endpoint_extension_geometry_validated": False,
        "tracked_boolean_provenance_validated": False,
        "boundary_regions_validated": False,
        "go": False,
    }
    if modifier is None:
        raise FeatureChamferFinalizeError(
            "preview_missing",
            "Owned Feature Chamfer Preview is missing",
            diagnostics,
        )
    if modifier.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION:
        raise FeatureChamferFinalizeError(
            "asset_version_mismatch",
            "Feature Chamfer Preview asset version mismatch",
            diagnostics,
        )
    if modifier.get(FEATURE_CHAMFER_GN_FINGERPRINT_TAG) != source_fingerprint(source_object):
        raise FeatureChamferFinalizeError(
            "source_fingerprint_mismatch",
            "Feature Chamfer source fingerprint changed",
            diagnostics,
        )
    if modifier.get(FEATURE_CHAMFER_GN_PARAMETERS_TAG) != json.dumps(
        live_preview_parameters(modifier), sort_keys=True
    ):
        raise FeatureChamferFinalizeError(
            "preview_parameters_mismatch",
            "Feature Chamfer live parameters changed",
            diagnostics,
        )

    cutter_mesh = None
    boolean_mesh = None
    open_mesh = None
    try:
        groups, endpoint_records, feature_stats = build_feature_chamfer_endpoint_context(
            source_object,
            live_preview_parameters(modifier)["radius"],
        )
        diagnostics.update(
            endpoint_counts={
                endpoint_class: sum(
                    1 for record in endpoint_records if record["class"] == endpoint_class
                )
                for endpoint_class in sorted(ENDPOINT_CLASSES)
            },
            endpoints=endpoint_records,
            feature_group_count=len(groups),
            surface_patch_count=feature_stats["surface_patch_count"],
        )
        ambiguous = [record for record in endpoint_records if record["class"] == "AMBIGUOUS"]
        if ambiguous:
            raise FeatureChamferFinalizeError(
                "ambiguous_endpoint",
                "Feature Chamfer endpoint classification is ambiguous",
                diagnostics,
            )
        cutter_mesh, cutter_diagnostics = evaluate_feature_chamfer_cutter(
            source_object,
            modifier,
            groups,
            endpoint_records,
        )
        diagnostics.update(cutter_diagnostics)
        source_patch_ids = [int(value) for value in _source_face_patch_ids(source_object)]
        boolean_mesh, groove_faces, boolean_diagnostics = tracked_boolean_difference(
            source_object,
            cutter_mesh,
            source_patch_ids,
        )
        diagnostics["tracked_boolean"] = boolean_diagnostics
        diagnostics["tracked_boolean_provenance_validated"] = True
        open_mesh, boundary_regions, boundary_diagnostics = build_tracked_boolean_boundary_regions(
            boolean_mesh,
            groove_faces,
            groups,
            endpoint_records,
            live_preview_parameters(modifier)["radius"],
        )
        diagnostics["boundary_graph"] = boundary_diagnostics
        diagnostics["boundary_regions_validated"] = True
        diagnostics["go"] = True
        diagnostics["status"] = "phase_2b_go"
        return {
            "cutter_mesh": cutter_mesh,
            "boolean_mesh": boolean_mesh,
            "open_mesh": open_mesh,
            "groove_face_indices": groove_faces,
            "boundary_regions": boundary_regions,
            "feature_groups": groups,
            "endpoints": endpoint_records,
            "diagnostics": diagnostics,
        }
    except Exception:
        if cutter_mesh is not None and bpy.data.meshes.get(cutter_mesh.name) == cutter_mesh:
            bpy.data.meshes.remove(cutter_mesh)
        if boolean_mesh is not None and bpy.data.meshes.get(boolean_mesh.name) == boolean_mesh:
            bpy.data.meshes.remove(boolean_mesh)
        if open_mesh is not None and bpy.data.meshes.get(open_mesh.name) == open_mesh:
            bpy.data.meshes.remove(open_mesh)
        raise


# 释放 extract_feature_chamfer_finalize_context 返回的内部临时 cutter Mesh。
# finalize_context: Phase 2B context dict；可重复调用。
def release_feature_chamfer_finalize_context(finalize_context):
    cutter_mesh = finalize_context.get("cutter_mesh") if finalize_context else None
    boolean_mesh = finalize_context.get("boolean_mesh") if finalize_context else None
    open_mesh = finalize_context.get("open_mesh") if finalize_context else None
    if cutter_mesh is not None and bpy.data.meshes.get(cutter_mesh.name) == cutter_mesh:
        bpy.data.meshes.remove(cutter_mesh)
    if boolean_mesh is not None and bpy.data.meshes.get(boolean_mesh.name) == boolean_mesh:
        bpy.data.meshes.remove(boolean_mesh)
    if open_mesh is not None and bpy.data.meshes.get(open_mesh.name) == open_mesh:
        bpy.data.meshes.remove(open_mesh)
    if finalize_context is not None:
        finalize_context["cutter_mesh"] = None
        finalize_context["boolean_mesh"] = None
        finalize_context["open_mesh"] = None
