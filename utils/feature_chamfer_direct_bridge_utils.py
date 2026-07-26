# -*- coding: utf-8 -*-
"""从 Boolean Pro Boundary Edges 直接执行槽段 Bridge 与 junction Fill。"""

import json

import bpy
import bmesh
from mathutils.bvhtree import BVHTree

from .experimental_pipe_chamfer_utils import CHAMFER_FACE_ATTRIBUTE
from .experimental_pipe_chamfer_utils import _add_source_normal_transfer
from .feature_chamfer_gn_utils import BOUNDARY_EDGE_ATTRIBUTE
from .feature_chamfer_gn_utils import SEGMENT_BOUNDARY_POINT_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SEGMENT_BOUNDARY_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SEGMENT_STATION_BOUNDARY_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SEGMENT_STATION_BOUNDARY_POINT_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SEGMENT_STATION_SQUARED_BOUNDARY_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SEGMENT_STATION_SQUARED_BOUNDARY_POINT_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import SOURCE_PATCH_ATTRIBUTE_PREFIX
from .feature_chamfer_gn_utils import owned_preview_curve
from .feature_chamfer_gn_utils import source_fingerprint
from ..const import FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG


class FeatureChamferDirectBridgeError(RuntimeError):
    """携带稳定 error code 与诊断数据的 Direct Bridge 失败。"""

    def __init__(self, error_code, message, stats=None):
        super().__init__(message)
        self.error_code = error_code
        self.stats = dict(stats or {})
        self.stats.update(
            status="failed",
            error_code=error_code,
            error_message=message,
        )


BRIDGE_EDGE_OWNER_LAYER = "hst_direct_bridge_owner"


# 返回 BMesh Edge 自然连通分量，不重排、不合并、也不要求两组长度一致。
# edges: 当前 Bridge/Fill selection；返回 Edge set 列表。
def _edge_components(edges):
    remaining = set(edges)
    components = []
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        remaining.remove(seed)
        component = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop(0)
            for vertex in sorted(edge.verts, key=lambda item: item.index):
                for neighbor in sorted(vertex.link_edges, key=lambda item: item.index):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        pending.append(neighbor)
        components.append(component)
    return components


# 判断 Edge component 是否形成单一 open chain 或 cyclic loop。
# edges: 单一连通 Edge selection；返回 (cyclic, endpoint_count)。
def _component_shape(edges):
    vertices = {vertex for edge in edges for vertex in edge.verts}
    degrees = [
        sum(linked_edge in edges for linked_edge in vertex.link_edges)
        for vertex in vertices
    ]
    if any(degree not in {1, 2} for degree in degrees):
        return False, -1
    endpoint_count = sum(degree == 1 for degree in degrees)
    return endpoint_count == 0, endpoint_count


# 按拓扑顺序返回 simple cyclic Edge component 的全部 Vertex。
# edges: 单一 cyclic Edge selection；返回不重复起点的有序 Vertex 列表。
def _ordered_cycle_vertices(edges):
    adjacency = {}
    for edge in edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    if not adjacency or any(len(linked_edges) != 2 for linked_edges in adjacency.values()):
        raise FeatureChamferDirectBridgeError(
            "junction_hole_not_simple",
            "Junction hole is not a simple cyclic Edge Loop",
        )
    start_vertex = min(adjacency, key=lambda vertex: vertex.index)
    ordered_vertices = [start_vertex]
    previous_edge = None
    current_vertex = start_vertex
    while True:
        next_edge = next(
            edge
            for edge in adjacency[current_vertex]
            if edge is not previous_edge
        )
        next_vertex = next_edge.other_vert(current_vertex)
        if next_vertex is start_vertex:
            break
        if next_vertex in ordered_vertices:
            raise FeatureChamferDirectBridgeError(
                "junction_hole_repeats_vertex",
                "Junction hole repeats a Vertex before closing",
            )
        ordered_vertices.append(next_vertex)
        previous_edge = next_edge
        current_vertex = next_vertex
    if len(ordered_vertices) != len(adjacency):
        raise FeatureChamferDirectBridgeError(
            "junction_hole_incomplete",
            "Junction hole traversal did not consume its complete Edge Loop",
        )
    return ordered_vertices


# 清理 Boolean Pro 留下的单面孤岛，真正空孔按 Blender Fill 后显式三角化非平面 n-gon。
# bm/residual_components: 全部槽段 Bridge 后的 BMesh 与自然 Boundary components；返回 Fill/清理记录和新面。
def _fill_junction_holes(
    bm,
    residual_components,
    boundary_layer,
    segment_layers,
    patch_layers,
    chamfer_faces,
):
    fill_records = []
    cleanup_records = []
    fill_faces = set()
    for residual_component in residual_components:
        cyclic, endpoint_count = _component_shape(residual_component)
        if not cyclic or endpoint_count != 0:
            raise FeatureChamferDirectBridgeError(
                "residual_hole_not_cyclic",
                "Bridge left a residual Boundary that is not a junction hole",
                {
                    "edge_count": len(residual_component),
                    "endpoint_count": endpoint_count,
                },
            )
        ordered_vertices = _ordered_cycle_vertices(residual_component)
        component_vertices = set(ordered_vertices)
        occupying_faces = [
            face
            for face in bm.faces
            if set(face.verts) == component_vertices
            and set(face.edges) == residual_component
        ]
        if occupying_faces:
            isolated_sheet = (
                len(occupying_faces) == 1
                and all(
                    tuple(edge.link_faces) == (occupying_faces[0],)
                    for edge in residual_component
                )
            )
            if not isolated_sheet:
                raise FeatureChamferDirectBridgeError(
                    "junction_hole_already_occupied",
                    "Residual junction cycle is occupied by non-isolated Faces",
                    {
                        "edge_count": len(residual_component),
                        "occupying_face_count": len(occupying_faces),
                    },
                )
            cleanup_records.append(
                {
                    "edge_count": len(residual_component),
                    "face_area": occupying_faces[0].calc_area(),
                    "reason": "isolated_boolean_sheet",
                }
            )
            bmesh.ops.delete(
                bm,
                geom=occupying_faces,
                context="FACES",
            )
            continue
        fill_result = bmesh.ops.contextual_create(
            bm,
            geom=sorted(residual_component, key=lambda edge: edge.index),
            mat_nr=0,
            use_smooth=False,
        )
        new_faces = {
            face
            for face in fill_result.get("faces", ())
            if isinstance(face, bmesh.types.BMFace)
        }
        if not new_faces:
            raise FeatureChamferDirectBridgeError(
                "junction_fill_created_invalid_faces",
                "Blender Fill did not create junction Faces",
                {
                    "edge_count": len(residual_component),
                    "face_count": len(new_faces),
                },
            )
        if any(
            not edge.is_valid or len(edge.link_faces) != 2
            for edge in residual_component
        ):
            raise FeatureChamferDirectBridgeError(
                "junction_fill_incomplete",
                "Blender Fill did not consume the complete junction Edge Loop",
                {"edge_count": len(residual_component)},
            )
        triangulated_faces = set(new_faces)
        if any(len(face.verts) > 4 for face in new_faces):
            triangulate_result = bmesh.ops.triangulate(
                bm,
                faces=list(new_faces),
                quad_method="BEAUTY",
                ngon_method="BEAUTY",
            )
            triangulated_faces = {
                face
                for face in triangulate_result.get("faces", ())
                if isinstance(face, bmesh.types.BMFace) and face.is_valid
            }
        fill_faces.update(triangulated_faces)
        cumulative_self_intersection_count = _self_intersection_count(bm)
        if cumulative_self_intersection_count:
            raise FeatureChamferDirectBridgeError(
                "junction_fill_self_intersects",
                "Blender Fill created self-intersecting junction Faces",
                {
                    "edge_count": len(residual_component),
                    "face_count": len(triangulated_faces),
                    "self_intersection_count": cumulative_self_intersection_count,
                    "vertex_indices": [vertex.index for vertex in ordered_vertices],
                    "coordinates": [
                        [float(value) for value in vertex.co]
                        for vertex in ordered_vertices
                    ],
                    "edge_provenance": [
                        {
                            "edge_index": edge.index,
                            "is_boolean_boundary": bool(edge[boundary_layer]),
                            "segment_ids": [
                                segment_id
                                for segment_id, layer in segment_layers.items()
                                if float(edge[layer]) > 1.0e-6
                            ],
                            "patch_ids": [
                                patch_id
                                for patch_id, layer in patch_layers.items()
                                if bool(edge[layer])
                            ],
                        }
                        for edge in sorted(
                            residual_component,
                            key=lambda item: item.index,
                        )
                    ],
                    "edge_face_provenance": [
                        {
                            "edge_index": edge.index,
                            "linked_faces": [
                                face.index for face in edge.link_faces
                            ],
                            "linked_chamfer_faces": [
                                face.index
                                for face in edge.link_faces
                                if face in chamfer_faces
                            ],
                        }
                        for edge in sorted(
                            residual_component,
                            key=lambda item: item.index,
                        )
                    ],
                },
            )
        fill_records.append(
            {
                "edge_count": len(residual_component),
                "face_count": len(triangulated_faces),
                "native_operator": "Blender Fill",
                "triangulated": True,
                "cumulative_self_intersection_count": cumulative_self_intersection_count,
            }
        )
    return fill_records, cleanup_records, fill_faces


# 按 Boolean segment 或 Bridge owner 把混合 residual cycle 拆成独立 junction 孔。
# residual_components/layers: Bridge 后边界与 provenance；返回每根 Pipe 的 simple cyclic loops。
def _split_junction_hole_components(
    residual_components,
    segment_layers,
    bridge_owner_layer,
):
    junction_holes = []
    for residual_component in residual_components:
        owner_edges = {}
        for edge in residual_component:
            segment_ids = [
                segment_id
                for segment_id, layer in segment_layers.items()
                if float(edge[layer]) > 1.0e-6
            ]
            bridge_owner = int(edge[bridge_owner_layer]) - 1
            if len(segment_ids) == 1:
                owner_id = segment_ids[0]
            elif not segment_ids and bridge_owner >= 0:
                owner_id = bridge_owner
            else:
                raise FeatureChamferDirectBridgeError(
                    "junction_hole_owner_ambiguous",
                    "Residual junction Edge does not have one Pipe owner",
                    {
                        "edge_index": edge.index,
                        "segment_ids": segment_ids,
                        "bridge_owner": bridge_owner,
                    },
                )
            owner_edges.setdefault(owner_id, set()).add(edge)
        owner_components = [
            (owner_id, component)
            for owner_id, edges in owner_edges.items()
            for component in _edge_components(edges)
        ]
        if len(owner_components) == 1 or len(owner_edges) == 1:
            junction_holes.append(residual_component)
            continue
        if not all(
            _component_shape(component)[0]
            for _, component in owner_components
        ):
            junction_holes.append(residual_component)
            continue
        for owner_id, component in owner_components:
            cyclic, endpoint_count = _component_shape(component)
            if not cyclic or endpoint_count != 0:
                raise FeatureChamferDirectBridgeError(
                    "junction_hole_owner_component_open",
                    "Pipe-owned residual junction component is not a complete hole",
                    {
                        "segment_id": owner_id,
                        "edge_count": len(component),
                        "endpoint_count": endpoint_count,
                    },
                )
            junction_holes.append(component)
    return junction_holes


# 从 BMesh 读取 Boolean Pro 已物化的 Boundary 与 segment layers。
# bm/segment_records: evaluated Preview BMesh 与冻结槽段合同；返回 layer 字典或 fail-closed。
def _direct_bridge_layers(bm, segment_records):
    boundary_layer = (
        bm.edges.layers.bool.get(BOUNDARY_EDGE_ATTRIBUTE)
        or bm.edges.layers.int.get(BOUNDARY_EDGE_ATTRIBUTE)
    )
    if boundary_layer is None:
        raise FeatureChamferDirectBridgeError(
            "boundary_attribute_missing",
            "Boolean Pro output lacks Boundary Edges",
        )
    segment_layers = {}
    segment_point_layers = {}
    station_edge_layers = {}
    station_squared_edge_layers = {}
    station_point_layers = {}
    station_squared_point_layers = {}
    for segment in segment_records:
        attribute_name = (
            SEGMENT_BOUNDARY_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        layer = bm.edges.layers.float.get(attribute_name)
        if layer is None:
            raise FeatureChamferDirectBridgeError(
                "segment_attribute_missing",
                f"Boolean Pro output lacks segment attribute {segment['segment_id']}",
            )
        segment_layers[int(segment["segment_id"])] = layer
        segment_id = int(segment["segment_id"])
        point_layer = bm.verts.layers.float.get(
            SEGMENT_BOUNDARY_POINT_ATTRIBUTE_PREFIX + str(segment_id)
        )
        station_edge_layer = bm.edges.layers.float.get(
            SEGMENT_STATION_BOUNDARY_ATTRIBUTE_PREFIX + str(segment_id)
        )
        station_squared_edge_layer = bm.edges.layers.float.get(
            SEGMENT_STATION_SQUARED_BOUNDARY_ATTRIBUTE_PREFIX + str(segment_id)
        )
        station_point_layer = bm.verts.layers.float.get(
            SEGMENT_STATION_BOUNDARY_POINT_ATTRIBUTE_PREFIX + str(segment_id)
        )
        station_squared_point_layer = bm.verts.layers.float.get(
            SEGMENT_STATION_SQUARED_BOUNDARY_POINT_ATTRIBUTE_PREFIX + str(segment_id)
        )
        if any(
            item is None
            for item in (
                point_layer,
                station_edge_layer,
                station_squared_edge_layer,
                station_point_layer,
                station_squared_point_layer,
            )
        ):
            raise FeatureChamferDirectBridgeError(
                "segment_station_attribute_missing",
                f"Boolean Pro output lacks segment station {segment_id}",
            )
        segment_point_layers[segment_id] = point_layer
        station_edge_layers[segment_id] = station_edge_layer
        station_squared_edge_layers[segment_id] = station_squared_edge_layer
        station_point_layers[segment_id] = station_point_layer
        station_squared_point_layers[segment_id] = station_squared_point_layer
    patch_layers = {
        int(layer_name.removeprefix(SOURCE_PATCH_ATTRIBUTE_PREFIX)): layer
        for layer_name, layer in bm.edges.layers.bool.items()
        if layer_name.startswith(SOURCE_PATCH_ATTRIBUTE_PREFIX)
    }
    if not patch_layers:
        raise FeatureChamferDirectBridgeError(
            "source_patch_attributes_missing",
            "Boolean Pro output lacks source Surface Patch attributes",
        )
    return (
        boundary_layer,
        segment_layers,
        patch_layers,
        segment_point_layers,
        station_edge_layers,
        station_squared_edge_layers,
        station_point_layers,
        station_squared_point_layers,
    )


# 在所有 segment selection 中取得只属于当前段的 Boundary Edges，交叉共享区留给最终 Fill。
# bm/boundary_layer/segment_layers/segment_id: 当前 evaluated Preview 与属性层；返回 Edge set。
def _exclusive_segment_edges(
    bm,
    boundary_layer,
    segment_layers,
    segment_id,
):
    target_layer = segment_layers[segment_id]
    return {
        edge
        for edge in bm.edges
        if bool(edge[boundary_layer])
        and float(edge[target_layer]) > 1.0e-6
        and sum(
            float(edge[layer]) > 1.0e-6
            for layer in segment_layers.values()
        )
        == 1
    }


# 依据 ChamferPlan owner Surface pairs 选择唯一槽段左右两侧，其他 Patch 只留给 junction Fill。
# components/patch_layers/owner_pairs: 当前槽段分量、Boolean Pro Patch 属性与计划 pairs；返回唯一 pair、两侧 chains 和 junction fragments。
def _segment_side_chains(components, patch_layers, owner_pairs):
    patch_components = {}
    junction_fragments = set()
    for component in components:
        component_patch_ids = {
            patch_id
            for patch_id, layer in patch_layers.items()
            if all(bool(edge[layer]) for edge in component)
        }
        if len(component_patch_ids) != 1:
            junction_fragments.update(component)
            continue
        patch_components.setdefault(next(iter(component_patch_ids)), []).append(component)
    complete_patch_components = {
        patch_id: [
            component
            for component in components_for_patch
            if _component_shape(component)[1] in {0, 2}
        ]
        for patch_id, components_for_patch in patch_components.items()
    }
    fragmented_owner_pairs = [
        owner_pair
        for owner_pair in owner_pairs
        if all(complete_patch_components.get(patch_id) for patch_id in owner_pair)
        and any(
            len(complete_patch_components.get(patch_id, ())) > 1
            for patch_id in owner_pair
        )
    ]
    if fragmented_owner_pairs:
        has_one_sided_interruption = any(
            sum(
                len(complete_patch_components.get(patch_id, ())) > 1
                for patch_id in owner_pair
            )
            == 1
            for owner_pair in fragmented_owner_pairs
        )
        if has_one_sided_interruption and len(owner_pairs) == 1:
            return None, None, junction_fragments
    direct_candidate_pairs = [
        owner_pair
        for owner_pair in owner_pairs
        if all(complete_patch_components.get(patch_id) for patch_id in owner_pair)
    ]
    for owner_pair in direct_candidate_pairs:
        first_candidates = complete_patch_components[owner_pair[0]]
        second_candidates = complete_patch_components[owner_pair[1]]
        if len(first_candidates) == 1 and len(second_candidates) > 1:
            partner_candidates = [
                component
                for component in second_candidates
                if _component_shape(component)[0] or len(component) > 1
            ]
            if len(partner_candidates) == 1:
                selected = [first_candidates[0], partner_candidates[0]]
                selected_edges = set().union(*selected)
                junction_fragments.update(
                    edge
                    for component in second_candidates
                    for edge in component
                    if edge not in selected_edges
                )
                return owner_pair, selected, junction_fragments
        if len(second_candidates) == 1 and len(first_candidates) > 1:
            partner_candidates = [
                component
                for component in first_candidates
                if _component_shape(component)[0] or len(component) > 1
            ]
            if len(partner_candidates) == 1:
                selected = [partner_candidates[0], second_candidates[0]]
                selected_edges = set().union(*selected)
                junction_fragments.update(
                    edge
                    for component in first_candidates
                    for edge in component
                    if edge not in selected_edges
                )
                return owner_pair, selected, junction_fragments
    for owner_pair in direct_candidate_pairs:
        full_span_components = []
        for patch_id in owner_pair:
            candidates = complete_patch_components[patch_id]
            full_span = [
                component
                for component in candidates
                if len(candidates) == 1
                or _component_shape(component)[0]
                or len(component) > 4
            ]
            if len(full_span) != 1:
                break
            full_span_components.append(full_span[0])
        else:
            if len(full_span_components) == 2:
                selected_edges = set().union(*full_span_components)
                junction_fragments.update(
                    edge
                    for patch_group in patch_components.values()
                    for component in patch_group
                    for edge in component
                    if edge not in selected_edges
                )
                return owner_pair, full_span_components, junction_fragments
    candidate_pairs = [
        owner_pair
        for owner_pair in owner_pairs
        if all(complete_patch_components.get(patch_id) for patch_id in owner_pair)
    ]
    if len(candidate_pairs) != 1:
        return None, None, junction_fragments
    selected_pair = candidate_pairs[0]
    selected_components = []
    for patch_id in selected_pair:
        candidates = complete_patch_components[patch_id]
        eligible = [
            component
            for component in candidates
            if len(candidates) == 1
            or _component_shape(component)[0]
            or len(component) > 4
        ]
        if len(eligible) != 1:
            return None, None, junction_fragments
        selected_components.append(eligible[0])
    selected_edges = set().union(*selected_components)
    junction_fragments.update(
        edge
        for patch_id, patch_group in patch_components.items()
        if patch_id not in selected_pair
        for component in patch_group
        for edge in component
    )
    return selected_pair, selected_components, junction_fragments


# 从 Boolean 已插值的 station 一阶、二阶矩恢复当前 Boundary Vertex 对应的 Pipe edge 端点值。
# vertex/segment_id/layers: Boundary Vertex、槽段 ID 与 provenance layers；返回有序 station 端点二元组。
def _vertex_station_endpoints(
    vertex,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    membership = float(vertex[segment_point_layers[segment_id]])
    if membership <= 1.0e-6:
        raise FeatureChamferDirectBridgeError(
            "segment_station_membership_missing",
            f"Segment {segment_id} junction Vertex lacks station membership",
        )
    mean = float(vertex[station_point_layers[segment_id]]) / membership
    mean_squared = (
        float(vertex[station_squared_point_layers[segment_id]]) / membership
    )
    deviation = max(0.0, mean_squared - mean * mean) ** 0.5
    return tuple(sorted((mean - deviation, mean + deviation)))


# 返回 Edge component 的两个自然端点；cyclic 或 branch component 会安全失败。
# component: 单一 Boundary component；返回按 Vertex index 排序的两个端点。
def _component_endpoints(component):
    vertices = {vertex for edge in component for vertex in edge.verts}
    endpoints = [
        vertex
        for vertex in vertices
        if sum(edge in component for edge in vertex.link_edges) == 1
    ]
    if len(endpoints) != 2:
        return None
    return tuple(sorted(endpoints, key=lambda vertex: vertex.index))


# 汇总完整边链上与其他 Pipe 交汇的 station witness，仅用于确定 junction 分段。
# component/segment_id/layers: 当前完整边链、槽段 ID 与 Boolean Pro provenance；返回 witness 记录。
def _component_junction_witnesses(
    component,
    segment_id,
    segment_layers,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    witnesses = []
    for vertex in {item for edge in component for item in edge.verts}:
        foreign_ids = sorted({
            other_id
            for linked_edge in vertex.link_edges
            for other_id, layer in segment_layers.items()
            if other_id != segment_id and float(linked_edge[layer]) > 1.0e-6
        })
        if not foreign_ids:
            continue
        witnesses.append(
            {
                "vertex_index": vertex.index,
                "foreign_segment_ids": foreign_ids,
                "station_endpoints": list(
                    _vertex_station_endpoints(
                        vertex,
                        segment_id,
                        segment_point_layers,
                        station_point_layers,
                        station_squared_point_layers,
                    )
                ),
                "coordinate": [float(value) for value in vertex.co],
            }
        )
    return sorted(witnesses, key=lambda item: item["vertex_index"])


# 读取一个 Boundary Edge 的 station 中点；仅用于已锁定 Pipe/槽段/Surface Patch 的 run 排序。
# edge/segment_id/station_layers: 当前 Edge、槽段 ID 与 station layers；返回 0..1 station。
def _edge_station_midpoint(
    edge,
    segment_id,
    segment_layers,
    station_edge_layers,
):
    membership = float(edge[segment_layers[segment_id]])
    if membership <= 1.0e-6:
        raise FeatureChamferDirectBridgeError(
            "segment_station_edge_membership_missing",
            f"Segment {segment_id} Edge lacks station membership",
        )
    return float(edge[station_edge_layers[segment_id]]) / membership


# 在已锁定的一侧完整 chain 中按 station 唯一定位并插入一个同步 junction 切点。
# bm/component/segment_id/target_station/layers: BMesh、目标 chain、槽段、station 与 layers；返回切点 Vertex。
def _split_component_at_station(
    component,
    segment_id,
    target_station,
    segment_layers,
    segment_point_layers,
    station_edge_layers,
    station_squared_edge_layers,
    station_point_layers,
    station_squared_point_layers,
):
    candidates = []
    station_ranges = []
    for edge in component:
        membership = float(edge[segment_layers[segment_id]])
        if membership <= 1.0e-6:
            continue
        mean = float(edge[station_edge_layers[segment_id]]) / membership
        mean_squared = (
            float(edge[station_squared_edge_layers[segment_id]]) / membership
        )
        deviation = max(0.0, mean_squared - mean * mean) ** 0.5
        low = mean - deviation
        high = mean + deviation
        station_ranges.append((edge, low, high))
        if low - 1.0e-6 <= target_station <= high + 1.0e-6:
            candidates.append((edge, low, high))
    exact_vertices = {
        vertex
        for edge, low, high in candidates
        for vertex in edge.verts
        for station in _vertex_station_endpoints(
            vertex,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        if abs(station - target_station) <= 1.0e-6
    }
    if len(exact_vertices) == 1:
        return next(iter(exact_vertices))
    strict_candidates = [
        item
        for item in candidates
        if item[1] + 1.0e-6 < target_station < item[2] - 1.0e-6
    ]
    if not strict_candidates:
        nearest_candidates = sorted(
            station_ranges,
            key=lambda item: min(
                abs(target_station - item[1]),
                abs(target_station - item[2]),
            ),
        )
        if nearest_candidates:
            nearest_distance = min(
                abs(target_station - nearest_candidates[0][1]),
                abs(target_station - nearest_candidates[0][2]),
            )
            if (
                nearest_distance <= 5.0e-4
                and (
                    len(nearest_candidates) == 1
                    or min(
                        abs(target_station - nearest_candidates[1][1]),
                        abs(target_station - nearest_candidates[1][2]),
                    )
                    - nearest_distance
                    > 1.0e-6
                )
            ):
                edge, low, high = nearest_candidates[0]
                endpoint_stations = {
                    vertex: min(
                        _vertex_station_endpoints(
                            vertex,
                            segment_id,
                            segment_point_layers,
                            station_point_layers,
                            station_squared_point_layers,
                        ),
                        key=lambda station: min(
                            abs(station - low),
                            abs(station - high),
                        ),
                    )
                    for vertex in edge.verts
                }
                return min(
                    endpoint_stations,
                    key=lambda vertex: abs(
                        endpoint_stations[vertex] - target_station
                    ),
                )
    if len(strict_candidates) > 1:
        geometric_candidates = [
            item
            for item in strict_candidates
            if item[0].calc_length() > 1.0e-3
        ]
        if len(geometric_candidates) == 1:
            strict_candidates = geometric_candidates
    if len(strict_candidates) > 1:
        candidate_distances = [
            (
                abs(
                    _edge_station_midpoint(
                        item[0],
                        segment_id,
                        segment_layers,
                        station_edge_layers,
                    )
                    - target_station
                ),
                item,
            )
            for item in strict_candidates
        ]
        candidate_distances.sort(key=lambda item: item[0])
        if (
            len(candidate_distances) > 1
            and abs(candidate_distances[0][0] - candidate_distances[1][0]) <= 1.0e-7
        ):
            raise FeatureChamferDirectBridgeError(
                "segment_station_split_ambiguous",
                f"Segment {segment_id} station has tied counterpart Edges",
                {
                    "segment_id": segment_id,
                    "station": target_station,
                    "candidates": [
                        {
                            "edge_index": item[1][0].index,
                            "low": item[1][1],
                            "high": item[1][2],
                            "midpoint": _edge_station_midpoint(
                                item[1][0],
                                segment_id,
                                segment_layers,
                                station_edge_layers,
                            ),
                            "vertex_indices": [
                                vertex.index for vertex in item[1][0].verts
                            ],
                            "coordinates": [
                                [float(component) for component in vertex.co]
                                for vertex in item[1][0].verts
                            ],
                        }
                        for item in candidate_distances
                    ],
                },
            )
        strict_candidates = [candidate_distances[0][1]]
    if len(strict_candidates) != 1:
        raise FeatureChamferDirectBridgeError(
            "segment_station_split_not_unique",
            f"Segment {segment_id} station does not select one counterpart Edge",
                {
                    "segment_id": segment_id,
                    "station": target_station,
                    "candidate_count": len(strict_candidates),
                },
            )
    edge, low, high = strict_candidates[0]
    start_vertex = edge.verts[0]
    start_values = _vertex_station_endpoints(
        start_vertex,
        segment_id,
        segment_point_layers,
        station_point_layers,
        station_squared_point_layers,
    )
    start_station = min(start_values, key=lambda value: abs(value - low))
    factor = (target_station - start_station) / (high - low)
    new_edge, split_vertex = bmesh.utils.edge_split(edge, start_vertex, factor)
    membership = float(edge[segment_layers[segment_id]])
    split_vertex[segment_point_layers[segment_id]] = membership
    split_vertex[station_point_layers[segment_id]] = membership * target_station
    split_vertex[station_squared_point_layers[segment_id]] = (
        membership * target_station * target_station
    )
    child_edges = (edge, new_edge)
    for child_edge in child_edges:
        child_other = child_edge.other_vert(split_vertex)
        child_other_stations = _vertex_station_endpoints(
            child_other,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        child_other_station = min(
            child_other_stations,
            key=lambda value: abs(value - (start_station if child_other is start_vertex else high)),
        )
        child_low, child_high = sorted((target_station, child_other_station))
        child_edge[segment_layers[segment_id]] = membership
        child_edge[station_edge_layers[segment_id]] = (
            membership * (child_low + child_high) * 0.5
        )
        child_edge[station_squared_edge_layers[segment_id]] = (
            membership * (child_low * child_low + child_high * child_high) * 0.5
        )
    component.add(new_edge)
    return split_vertex


# 将一条已同步插入 junction 切点的 chain 切成 station 区间 runs。
# component/cut_vertices/segment_id/layers: 原 chain、切点与 station layers；返回按 station 排序的 run Edge sets。
def _component_station_runs(
    component,
    cut_vertices,
    segment_id,
    segment_layers,
    station_edge_layers,
):
    cut_vertices = set(cut_vertices)
    runs = []
    remaining = set(component)
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        remaining.remove(seed)
        run = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop()
            for vertex in edge.verts:
                if vertex in cut_vertices:
                    continue
                for neighbor in vertex.link_edges:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        run.add(neighbor)
                        pending.append(neighbor)
        runs.append(run)
    return sorted(
        runs,
        key=lambda run: min(
            _edge_station_midpoint(
                edge,
                segment_id,
                segment_layers,
                station_edge_layers,
            )
            for edge in run
        ),
    )


# 即使 Boundary 仍连通，也按交叉 witness 在槽两侧同步插点并拆成 Bridge jobs。
# side_chains/segment/layers: 同一槽段两侧完整链与 provenance；返回 jobs 或 None。
def _split_connected_segment_jobs(
    side_chains,
    segment,
    segment_layers,
    segment_point_layers,
    station_edge_layers,
    station_squared_edge_layers,
    station_point_layers,
    station_squared_point_layers,
):
    segment_id = int(segment["segment_id"])
    witness_groups = [
        _component_junction_witnesses(
            component,
            segment_id,
            segment_layers,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        for component in side_chains
    ]
    interrupted_sides = [index for index, witnesses in enumerate(witness_groups) if witnesses]
    if len(interrupted_sides) != 1:
        return None
    interrupted_index = interrupted_sides[0]
    foreign_groups = {}
    for witness in witness_groups[interrupted_index]:
        foreign_groups.setdefault(tuple(witness["foreign_segment_ids"]), []).append(witness)
    paired_groups = [witnesses for witnesses in foreign_groups.values() if len(witnesses) == 2]
    if len(paired_groups) != 1:
        return None
    cut_stations = sorted(
        sum(witness["station_endpoints"]) * 0.5
        for witness in paired_groups[0]
    )
    jobs_by_interval = []
    junction_fragments = set()
    intervals = (
        (float("-inf"), cut_stations[0], False),
        (cut_stations[0], cut_stations[1], True),
        (cut_stations[1], float("inf"), False),
    )
    for low, high, is_junction in intervals:
        interval_sides = []
        for component in side_chains:
            interval_edges = {
                edge
                for edge in component
                if low
                <= _edge_station_midpoint(
                    edge,
                    segment_id,
                    segment_layers,
                    station_edge_layers,
                )
                < high
            }
            if not interval_edges:
                break
            interval_sides.append(interval_edges)
        if len(interval_sides) != 2:
            return None
        if is_junction:
            junction_fragments.update(set().union(*interval_sides))
        else:
            jobs_by_interval.append(tuple(interval_sides))
    return jobs_by_interval, junction_fragments


# 对被另一根 Pipe 截断的同一槽段，按 owner Patch 与 station 生成多个实际 Bridge jobs。
# components/segment/layers/owner_pairs: 当前自然分量、合同、provenance 与 Plan owner pairs；返回 Bridge jobs 或 None。
def _split_interrupted_segment_jobs(
    components,
    segment,
    patch_layers,
    owner_pairs,
    segment_layers,
    segment_point_layers,
    station_edge_layers,
    station_squared_edge_layers,
    station_point_layers,
    station_squared_point_layers,
):
    segment_id = int(segment["segment_id"])
    patch_components = {}
    for component in components:
        patch_ids = {
            patch_id
            for patch_id, layer in patch_layers.items()
            if all(bool(edge[layer]) for edge in component)
        }
        if len(patch_ids) == 1:
            patch_components.setdefault(next(iter(patch_ids)), []).append(component)
    candidate_pairs = [
        owner_pair
        for owner_pair in owner_pairs
        if all(patch_components.get(patch_id) for patch_id in owner_pair)
    ]
    if len(candidate_pairs) != 1:
        return None
    owner_pair = candidate_pairs[0]
    component_groups = [patch_components[patch_id] for patch_id in owner_pair]
    interrupted_side = None
    complete_side = None
    for component_group in component_groups:
        if len(component_group) > 1:
            interrupted_side = component_group
        elif len(component_group) == 1:
            complete_side = component_group[0]
    if interrupted_side is None or complete_side is None:
        return None
    interrupted_endpoints = [
        vertex
        for component in interrupted_side
        for vertex in (_component_endpoints(component) or ())
    ]
    endpoint_stations = {
        vertex: min(
            _vertex_station_endpoints(
                vertex,
                segment_id,
                segment_point_layers,
                station_point_layers,
                station_squared_point_layers,
            ),
            key=lambda station: min(
                abs(
                    station
                    - _edge_station_midpoint(
                        edge,
                        segment_id,
                        segment_layers,
                        station_edge_layers,
                    )
                )
                for edge in vertex.link_edges
                if float(edge[segment_layers[segment_id]]) > 1.0e-6
            ),
        )
        for vertex in interrupted_endpoints
    }
    junction_vertices = {
        vertex
        for vertex in interrupted_endpoints
        if any(
            float(edge[layer]) > 1.0e-6
            for edge in vertex.link_edges
            for other_id, layer in segment_layers.items()
            if other_id != segment_id
        )
        and endpoint_stations[vertex] > 0.05
        and endpoint_stations[vertex] < 0.95
    }
    foreign_groups = {}
    for vertex in junction_vertices:
        foreign_ids = tuple(sorted({
            other_id
            for edge in vertex.link_edges
            for other_id, layer in segment_layers.items()
            if other_id != segment_id and float(edge[layer]) > 1.0e-6
        }))
        foreign_groups.setdefault(foreign_ids, set()).add(vertex)
    paired_groups = [group for group in foreign_groups.values() if len(group) == 2]
    if len(paired_groups) == 1:
        junction_vertices = paired_groups[0]
    if not junction_vertices and len(interrupted_side) >= 2:
        regular_components = [
            component
            for component in interrupted_side
            if len(component) > 4
        ]
        if len(regular_components) == 1:
            endpoint_margin = min(
                min(endpoint_stations[vertex], 1.0 - endpoint_stations[vertex])
                for vertex in (_component_endpoints(regular_components[0]) or ())
            )
            if endpoint_margin < 0.05:
                return owner_pair, [(regular_components[0], complete_side)], set().union(
                    *(
                        component
                        for component in interrupted_side
                        if component is not regular_components[0]
                    )
                )
            interrupted_side = regular_components
            junction_vertices = set(_component_endpoints(regular_components[0]) or ())
    if len(junction_vertices) != 2:
        return None
    cut_stations = []
    for vertex in sorted(junction_vertices, key=lambda item: item.index):
        cut_stations.append(endpoint_stations[vertex])
    cut_stations.sort()
    split_vertices = [
        _split_component_at_station(
            complete_side,
            segment_id,
            station,
            segment_layers,
            segment_point_layers,
            station_edge_layers,
            station_squared_edge_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        for station in cut_stations
        if station > 1.0e-6 and station < 1.0 - 1.0e-6
    ]
    if not split_vertices and len(interrupted_runs := interrupted_side) == 1:
        return owner_pair, [(interrupted_side[0], complete_side)], set()
    complete_runs = _component_station_runs(
        complete_side,
        split_vertices,
        segment_id,
        segment_layers,
        station_edge_layers,
    )
    interrupted_runs = sorted(
        interrupted_side,
        key=lambda run: min(
            _edge_station_midpoint(
                edge,
                segment_id,
                segment_layers,
                station_edge_layers,
            )
            for edge in run
        ),
    )
    if len(interrupted_runs) == 1 and len(complete_runs) == 3:
        return owner_pair, [(interrupted_runs[0], complete_runs[1])], set().union(
            complete_runs[0],
            complete_runs[-1],
        )
    if len(complete_runs) != 3 or len(interrupted_runs) != 2:
        return None
    return owner_pair, [
        (interrupted_runs[0], complete_runs[0]),
        (interrupted_runs[1], complete_runs[-1]),
    ], set(complete_runs[1])


# 只焊接 Bridge 后坐标重合的 Vertex，让 junction Fill 消费焊接后重新形成的真实孔洞。
# bm: 已完成全部 Bridge 的 BMesh；返回焊接前的零面积 Face 数。
def _weld_coincident_vertices(bm):
    zero_area_count = sum(
        face.calc_area() <= 1.0e-12
        for face in bm.faces
    )
    if zero_area_count:
        bmesh.ops.remove_doubles(
            bm,
            verts=list(bm.verts),
            dist=1.0e-8,
        )
    return zero_area_count


# 检查最终 Mesh 是否产生非邻接自交，防止仅靠 manifold 统计误报产品成功。
# bm: 最终 BMesh；返回非邻接相交 pair 数。
def _self_intersection_count(bm):
    temporary_mesh = bpy.data.meshes.new("HST_FeatureChamfer_IntersectionCheck")
    bm.to_mesh(temporary_mesh)
    triangulated = bmesh.new()
    triangulated.from_mesh(temporary_mesh)
    try:
        bmesh.ops.triangulate(
            triangulated,
            faces=list(triangulated.faces),
            quad_method="BEAUTY",
            ngon_method="BEAUTY",
        )
        triangulated.faces.ensure_lookup_table()
        triangulated.faces.index_update()
        tree = BVHTree.FromBMesh(triangulated, epsilon=1.0e-8)
        intersection_count = 0
        for first_index, second_index in tree.overlap(tree):
            if first_index >= second_index:
                continue
            first = triangulated.faces[first_index]
            second = triangulated.faces[second_index]
            if set(first.verts) & set(second.verts):
                continue
            intersection_count += 1
        return intersection_count
    finally:
        triangulated.free()
        bpy.data.meshes.remove(temporary_mesh)


# 从正式 evaluated Preview 直接 Bridge 普通槽段，再 Fill 自然剩余的 junction 孔洞。
# source_object/expected_chamfer_plan: 正式 source 与 Preview immutable plan；返回 Operator 可记录的 stats。
def build_direct_edge_loop_chamfer(source_object, expected_chamfer_plan):
    source_fingerprint_before = source_fingerprint(source_object)
    curve_object = owned_preview_curve(source_object)
    if curve_object is None:
        raise FeatureChamferDirectBridgeError(
            "preview_curve_missing",
            "Owned Preview Curve is missing",
        )
    try:
        pipe_contract = json.loads(
            curve_object[FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG]
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise FeatureChamferDirectBridgeError(
            "preview_contract_invalid",
            "Preview Pipe contract is invalid",
        ) from error
    if pipe_contract.get("plan_id") != expected_chamfer_plan.plan_id:
        raise FeatureChamferDirectBridgeError(
            "preview_contract_plan_mismatch",
            "Preview Pipe contract does not match ChamferPlan",
        )
    if pipe_contract.get("source_fingerprint") != source_fingerprint_before:
        raise FeatureChamferDirectBridgeError(
            "source_fingerprint_mismatch",
            "Source changed after Preview",
        )
    segment_records = tuple(pipe_contract.get("segments", ()))
    if not segment_records:
        raise FeatureChamferDirectBridgeError(
            "preview_segment_contract_missing",
            "Preview Pipe contract has no direct Bridge segments",
        )

    evaluated_mesh = None
    output_object = None
    output_mesh = None
    bm = None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        evaluated_mesh = bpy.data.meshes.new_from_object(
            source_object.evaluated_get(depsgraph),
            depsgraph=depsgraph,
            preserve_all_data_layers=True,
        )
        bm = bmesh.new()
        bm.from_mesh(evaluated_mesh)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bridge_owner_layer = bm.edges.layers.int.get(
            BRIDGE_EDGE_OWNER_LAYER
        ) or bm.edges.layers.int.new(BRIDGE_EDGE_OWNER_LAYER)
        (
            boundary_layer,
            segment_layers,
            patch_layers,
            segment_point_layers,
            station_edge_layers,
            station_squared_edge_layers,
            station_point_layers,
            station_squared_point_layers,
        ) = _direct_bridge_layers(bm, segment_records)
        initial_boundary_count = sum(
            bool(edge[boundary_layer])
            for edge in bm.edges
        )
        claimed_edges = set()
        bridge_records = []
        deferred_segments = []
        chamfer_faces = set()
        for segment in segment_records:
            segment_id = int(segment["segment_id"])
            selected_edges = _exclusive_segment_edges(
                bm,
                boundary_layer,
                segment_layers,
                segment_id,
            )
            components = _edge_components(selected_edges)
            if not selected_edges:
                deferred_segments.append(
                    {
                        "segment_id": segment_id,
                        "pipe_id": int(segment["pipe_id"]),
                        "reason": "junction_consumed",
                    }
                )
                continue
            owner_pairs = []
            for correspondence in expected_chamfer_plan.strip_correspondences:
                if (
                    correspondence.owner_strand_id == segment["strand_id"]
                    and correspondence.owner_surface_pair not in owner_pairs
                ):
                    owner_pairs.append(correspondence.owner_surface_pair)
            if not owner_pairs:
                raise FeatureChamferDirectBridgeError(
                    "segment_owner_pair_missing",
                    f"Segment {segment_id} has no owner Surface pair",
                )
            owner_pair = None
            junction_fragments = set()
            bridge_jobs = None
            if len(components) == 2:
                owner_pair, side_chains, junction_fragments = _segment_side_chains(
                    components,
                    patch_layers,
                    owner_pairs,
                )
            else:
                interrupted_result = _split_interrupted_segment_jobs(
                    components,
                    segment,
                    patch_layers,
                    owner_pairs,
                    segment_layers,
                    segment_point_layers,
                    station_edge_layers,
                    station_squared_edge_layers,
                    station_point_layers,
                    station_squared_point_layers,
                )
                if interrupted_result is not None:
                    owner_pair, bridge_jobs, interrupted_fragments = interrupted_result
                    junction_fragments.update(interrupted_fragments)
                    side_chains = bridge_jobs[0]
                else:
                    owner_pair, side_chains, junction_fragments = _segment_side_chains(
                        components,
                        patch_layers,
                        owner_pairs,
                    )
                if side_chains is None:
                    raise FeatureChamferDirectBridgeError(
                        "segment_side_count_invalid",
                        f"Segment {segment_id} does not expose two complete side chains",
                        {
                            "segment_id": segment_id,
                            "pipe_id": int(segment["pipe_id"]),
                            "component_count": len(components),
                            "edge_count": len(selected_edges),
                            "owner_pairs": [list(pair) for pair in owner_pairs],
                            "component_patches": [
                                {
                                    "edge_count": len(component),
                                    "patch_ids": [
                                        patch_id
                                        for patch_id, layer in patch_layers.items()
                                        if all(bool(edge[layer]) for edge in component)
                                    ],
                                }
                                for component in components
                            ],
                        },
                    )
            if side_chains is not None and bridge_jobs is None:
                connected_split = _split_connected_segment_jobs(
                    side_chains,
                    segment,
                    segment_layers,
                    segment_point_layers,
                    station_edge_layers,
                    station_squared_edge_layers,
                    station_point_layers,
                    station_squared_point_layers,
                )
                if connected_split is not None:
                    bridge_jobs, connected_fragments = connected_split
                    junction_fragments.update(connected_fragments)
            if side_chains is None:
                if (
                    len(components) == 1
                    and bool(segment.get("port_indices"))
                    and _component_shape(components[0])[0]
                ):
                    deferred_segments.append(
                        {
                            "segment_id": segment_id,
                            "pipe_id": int(segment["pipe_id"]),
                            "reason": "terminal_hole",
                            "edge_count": len(selected_edges),
                        }
                    )
                    continue
                if selected_edges and all(
                    len(component) == 1
                    for component in components
                ):
                    deferred_segments.append(
                        {
                            "segment_id": segment_id,
                            "pipe_id": int(segment["pipe_id"]),
                            "reason": "junction_connector",
                            "component_count": len(components),
                        }
                    )
                    continue
                if (
                    len(components) == 1
                    and len(selected_edges) <= 2
                    and bool(segment.get("port_indices"))
                ):
                    deferred_segments.append(
                        {
                            "segment_id": segment_id,
                            "pipe_id": int(segment["pipe_id"]),
                            "reason": "junction_connector",
                            "component_count": 1,
                            "edge_count": len(selected_edges),
                        }
                    )
                    continue
                raise FeatureChamferDirectBridgeError(
                    "segment_side_count_invalid",
                    f"Segment {segment_id} does not expose two complete side chains",
                    {
                        "segment_id": segment_id,
                        "pipe_id": int(segment["pipe_id"]),
                        "component_count": len(components),
                        "edge_count": len(selected_edges),
                    },
                )
            bridge_jobs = bridge_jobs or [side_chains]
            for bridge_job_index, components in enumerate(bridge_jobs):
                selected_edges = set().union(*components)
                shapes = [_component_shape(component) for component in components]
                if any(endpoint_count not in {0, 2} for _, endpoint_count in shapes):
                    raise FeatureChamferDirectBridgeError(
                        "segment_chain_incomplete",
                        f"Segment {segment_id} exposes incomplete side chains",
                        {"segment_id": segment_id, "shapes": shapes},
                    )
                if selected_edges & claimed_edges:
                    raise FeatureChamferDirectBridgeError(
                        "segment_selection_overlap",
                        f"Segment {segment_id} reuses an earlier Bridge edge",
                    )
                faces_before_bridge = set(bm.faces)
                edges_before_bridge = set(bm.edges)
                bridge_result = bmesh.ops.bridge_loops(
                    bm,
                    edges=sorted(selected_edges, key=lambda edge: edge.index),
                    use_pairs=False,
                    use_cyclic=False,
                    use_merge=False,
                    merge_factor=0.0,
                )
                bridge_faces = {
                    face
                    for face in bm.faces
                    if face not in faces_before_bridge
                }
                bridge_new_edges = {
                    edge
                    for edge in bm.edges
                    if edge not in edges_before_bridge
                }
                for edge in bridge_new_edges:
                    edge[bridge_owner_layer] = segment_id + 1
                if not bridge_faces:
                    raise FeatureChamferDirectBridgeError(
                        "bridge_created_no_faces",
                        f"Blender Bridge created no Faces for segment {segment_id}",
                    )
                claimed_edges.update(selected_edges)
                bridge_self_intersection_count = _self_intersection_count(bm)
                if bridge_self_intersection_count:
                    raise FeatureChamferDirectBridgeError(
                        "bridge_faces_self_intersect",
                        f"Blender Bridge self-intersects for segment {segment_id}",
                        {
                            "segment_id": segment_id,
                            "bridge_job_index": bridge_job_index,
                            "side_edge_counts": sorted(
                                len(component) for component in components
                            ),
                            "self_intersection_count": bridge_self_intersection_count,
                            "side_junction_witnesses": [
                                _component_junction_witnesses(
                                    component,
                                    segment_id,
                                    segment_layers,
                                    segment_point_layers,
                                    station_point_layers,
                                    station_squared_point_layers,
                                )
                                for component in components
                            ],
                            "side_cyclic": [
                                _component_shape(component)[0]
                                for component in components
                            ],
                        },
                    )
                chamfer_faces.update(bridge_faces)
                bridge_records.append(
                    {
                        "segment_id": segment_id,
                        "bridge_job_index": bridge_job_index,
                        "pipe_id": int(segment["pipe_id"]),
                        "port_indices": list(segment.get("port_indices", ())),
                        "owner_surface_pair": list(owner_pair) if owner_pair else None,
                        "side_edge_counts": sorted(len(component) for component in components),
                        "side_lengths": sorted(
                            sum(edge.calc_length() for edge in component)
                            for component in components
                        ),
                        "junction_fragment_edge_count": len(junction_fragments),
                        "face_count": len(bridge_faces),
                        "cumulative_self_intersection_count": bridge_self_intersection_count,
                        "native_operator": "Blender Bridge Edge Loops",
                    }
                )
        if deferred_segments:
            raise FeatureChamferDirectBridgeError(
                "unbridged_segment_remaining",
                "Direct Bridge left ordinary Pipe segments unconsumed",
                {"deferred_segments": deferred_segments},
            )

        zero_area_faces_welded_before_fill = _weld_coincident_vertices(bm)
        bm.edges.index_update()
        bm.faces.index_update()
        residual_edges = {
            edge
            for edge in bm.edges
            if len(edge.link_faces) == 1
        }
        residual_components = sorted(
            _edge_components(residual_edges),
            key=lambda component: min(edge.index for edge in component),
        )
        junction_holes = _split_junction_hole_components(
            residual_components,
            segment_layers,
            bridge_owner_layer,
        )
        fill_records, cleanup_records, fill_faces = _fill_junction_holes(
            bm,
            junction_holes,
            boundary_layer,
            segment_layers,
            patch_layers,
            chamfer_faces,
        )
        chamfer_faces.update(fill_faces)

        self_intersection_count_after_fill = _self_intersection_count(bm)

        topology_before_zero_cleanup = {
            "boundary_count": sum(len(edge.link_faces) == 1 for edge in bm.edges),
            "non_manifold_count": sum(len(edge.link_faces) != 2 for edge in bm.edges),
            "zero_area_count": sum(
                face.calc_area() <= 1.0e-12
                for face in bm.faces
            ),
            "zero_area_faces": [
                {
                    "face_index": face.index,
                    "edge_lengths": sorted(edge.calc_length() for edge in face.edges),
                    "vertex_indices": [vertex.index for vertex in face.verts],
                    "coordinates": [
                        [float(component) for component in vertex.co]
                        for vertex in face.verts
                    ],
                }
                for face in bm.faces
                if face.calc_area() <= 1.0e-12
            ],
        }
        bmesh.ops.recalc_face_normals(
            bm,
            faces=list(bm.faces),
        )
        bm.normal_update()
        remaining_boundary_count = sum(
            len(edge.link_faces) == 1
            for edge in bm.edges
        )
        non_manifold_count = sum(
            len(edge.link_faces) != 2
            for edge in bm.edges
        )
        zero_area_count = sum(
            face.calc_area() <= 1.0e-12
            for face in bm.faces
        )
        self_intersection_count = _self_intersection_count(bm)
        if remaining_boundary_count or non_manifold_count or zero_area_count:
            raise FeatureChamferDirectBridgeError(
                "final_topology_invalid",
                "Direct Bridge/Fill output is not a clean closed Mesh",
                {
                    "boundary_count": remaining_boundary_count,
                    "non_manifold_count": non_manifold_count,
                    "zero_area_count": zero_area_count,
                    "self_intersection_count": self_intersection_count,
                    "self_intersection_count_after_fill": self_intersection_count_after_fill,
                    "topology_before_zero_cleanup": topology_before_zero_cleanup,
                    "zero_area_faces_welded_before_fill": zero_area_faces_welded_before_fill,
                    "bridge_records": bridge_records,
                    "deferred_segments": deferred_segments,
                    "junction_fill_records": fill_records,
                    "boolean_cleanup_records": cleanup_records,
                },
            )
        if self_intersection_count:
            raise FeatureChamferDirectBridgeError(
                "final_geometry_self_intersects",
                "Direct Bridge/Fill output contains self-intersecting Faces",
                {
                    "self_intersection_count": self_intersection_count,
                    "self_intersection_count_after_fill": self_intersection_count_after_fill,
                    "bridge_records": bridge_records,
                    "junction_fill_records": fill_records,
                },
            )

        bm.faces.index_update()
        chamfer_face_indices = {
            face.index
            for face in chamfer_faces
            if face.is_valid
        }
        output_mesh = bpy.data.meshes.new(
            f"{source_object.data.name}_FeatureChamfer"
        )
        bm.to_mesh(output_mesh)
        output_mesh.update()
        output_object = bpy.data.objects.new(
            f"{source_object.name}_FeatureChamfer",
            output_mesh,
        )
        source_object.users_collection[0].objects.link(output_object)
        output_object.matrix_world = source_object.matrix_world.copy()
        chamfer_attribute = output_mesh.attributes.new(
            CHAMFER_FACE_ATTRIBUTE,
            type="BOOLEAN",
            domain="FACE",
        )
        for polygon in output_mesh.polygons:
            chamfer_attribute.data[polygon.index].value = (
                polygon.index in chamfer_face_indices
            )
        _add_source_normal_transfer(output_object, source_object)
        if source_fingerprint(source_object) != source_fingerprint_before:
            raise FeatureChamferDirectBridgeError(
                "source_changed_during_finalize",
                "Finalize changed the source Mesh",
            )
        return {
            "status": "finished",
            "backend": "DIRECT_EDGE_LOOP_BRIDGE",
            "runtime_path": (
                "Preview Pipe -> Boolean Pro Boundary Edges -> segment groups -> "
                "Blender Bridge Edge Loops -> Blender Fill"
            ),
            "feature_graph_contract": "GN_PREVIEW_V1",
            "plan_id": expected_chamfer_plan.plan_id,
            "source_fingerprint_unchanged": True,
            "initial_boundary_edge_count": initial_boundary_count,
            "bridge_job_count": len(bridge_records),
            "bridge_face_count": sum(record["face_count"] for record in bridge_records),
            "bridge_records": bridge_records,
            "deferred_segment_count": len(deferred_segments),
            "deferred_segments": deferred_segments,
            "junction_fill_count": len(fill_records),
            "junction_fill_face_count": sum(record["face_count"] for record in fill_records),
            "junction_fill_records": fill_records,
            "boolean_cleanup_count": len(cleanup_records),
            "boolean_cleanup_records": cleanup_records,
            "zero_area_faces_welded_before_fill": zero_area_faces_welded_before_fill,
            "topology_before_zero_cleanup": topology_before_zero_cleanup,
            "regular_patch_face_count": sum(record["face_count"] for record in bridge_records),
            "junction_patch_face_count": sum(record["face_count"] for record in fill_records),
            "boundary_edge_count": remaining_boundary_count,
            "non_manifold_edge_count": non_manifold_count,
            "zero_area_face_count": zero_area_count,
            "self_intersection_count": self_intersection_count,
            "output_object_name": output_object.name,
        }
    except Exception:
        if output_object is not None and bpy.data.objects.get(output_object.name) == output_object:
            bpy.data.objects.remove(output_object, do_unlink=True)
        if output_mesh is not None and output_mesh.users == 0:
            bpy.data.meshes.remove(output_mesh)
        raise
    finally:
        if bm is not None:
            bm.free()
        if evaluated_mesh is not None and evaluated_mesh.users == 0:
            bpy.data.meshes.remove(evaluated_mesh)
