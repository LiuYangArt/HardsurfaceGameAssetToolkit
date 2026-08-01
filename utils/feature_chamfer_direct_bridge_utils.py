# -*- coding: utf-8 -*-
"""从 Boolean Pro Boundary Edges 直接执行槽段 Bridge 与 junction Fill。"""

import json
import math

import bpy
import bmesh
from mathutils.bvhtree import BVHTree

from .experimental_pipe_chamfer_utils import CHAMFER_FACE_ATTRIBUTE
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
MAX_RESIDUAL_CYCLE_CANDIDATES = 64
MAX_RESIDUAL_CYCLE_ENUMERATION_STATES = 4096
MAX_RESIDUAL_CYCLE_PAIRING_STATES = 4096
MIN_TURN_SAMPLE_RADIANS = math.radians(1.0)
MIN_MAJOR_TURN_RADIANS = math.radians(30.0)
TARGET_CYCLIC_BRIDGE_TURN_RADIANS = math.radians(90.0)
MIN_CYCLIC_BRIDGE_SIDE_EDGE_COUNT = 8
BRIDGE_MERGE_DISTANCE_FACTOR = 1.0e-2
MIN_BRIDGE_MERGE_DISTANCE = 1.0e-12
MAX_BRIDGE_DISSOLVE_DEVIATION_RADIANS = math.radians(0.1)
MAX_BRIDGE_MERGE_DISTANCE_TO_MEDIAN_EDGE_RATIO = 0.01


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


# 按拓扑顺序返回 simple open/cyclic Edge chain 的全部 Vertex。
# edges: 单一连通 Edge selection；返回有序 Vertex 列表。
def _ordered_chain_vertices(edges):
    cyclic, endpoint_count = _component_shape(edges)
    if cyclic:
        return _ordered_cycle_vertices(edges)
    if endpoint_count != 2:
        return []
    adjacency = {}
    for edge in edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    start_vertex = min(
        (
            vertex
            for vertex, linked_edges in adjacency.items()
            if len(linked_edges) == 1
        ),
        key=lambda vertex: vertex.index,
    )
    ordered_vertices = [start_vertex]
    previous_edge = None
    current_vertex = start_vertex
    while True:
        next_edges = [
            edge
            for edge in adjacency[current_vertex]
            if edge is not previous_edge
        ]
        if not next_edges:
            break
        next_edge = next_edges[0]
        next_vertex = next_edge.other_vert(current_vertex)
        if next_vertex in ordered_vertices:
            return []
        ordered_vertices.append(next_vertex)
        previous_edge = next_edge
        current_vertex = next_vertex
    return ordered_vertices


# 枚举分支 Boundary 图中的 simple cycles，并选出覆盖边最多的互斥孔集合。
# residual_component: Bridge 后的自然 Boundary 连通分量；返回可独立 Fill 的 cyclic Edge Loop。
def _boundary_cycles_by_graph(residual_component):
    cyclic, endpoint_count = _component_shape(residual_component)
    if cyclic and endpoint_count == 0:
        return [set(residual_component)]
    adjacency = {}
    edge_by_vertex_pair = {}
    for edge in residual_component:
        first_vertex, second_vertex = edge.verts
        adjacency.setdefault(first_vertex, set()).add(second_vertex)
        adjacency.setdefault(second_vertex, set()).add(first_vertex)
        edge_by_vertex_pair[frozenset((first_vertex, second_vertex))] = edge

    vertex_keys = {
        vertex: tuple(round(float(component), 9) for component in vertex.co)
        for vertex in adjacency
    }
    vertex_ranks = {
        vertex: rank
        for rank, vertex in enumerate(
            sorted(adjacency, key=lambda item: (vertex_keys[item], item.index))
        )
    }

    def edge_geometry_key(edge):
        return tuple(sorted(vertex_keys[vertex] for vertex in edge.verts))

    def cycle_geometry_key(edges):
        return tuple(sorted(edge_geometry_key(edge) for edge in edges))

    cycle_edge_sets = set()
    cycle_enumeration_states = 0
    ordered_vertices = sorted(adjacency, key=lambda vertex: vertex_ranks[vertex])
    for start_vertex in ordered_vertices:
        def walk(current_vertex, path, visited_vertices):
            nonlocal cycle_enumeration_states
            cycle_enumeration_states += 1
            if cycle_enumeration_states > MAX_RESIDUAL_CYCLE_ENUMERATION_STATES:
                raise FeatureChamferDirectBridgeError(
                    "junction_hole_cycle_budget_exceeded",
                    "Residual junction Boundary is too complex to split safely",
                    {
                        "edge_count": len(residual_component),
                        "search_state_limit": MAX_RESIDUAL_CYCLE_ENUMERATION_STATES,
                    },
                )
            for next_vertex in sorted(
                adjacency[current_vertex],
                key=lambda vertex: vertex_ranks[vertex],
            ):
                if next_vertex is start_vertex:
                    if len(path) >= 3:
                        cycle_edges = frozenset(
                            edge_by_vertex_pair[frozenset((first, second))]
                            for first, second in zip(
                                path,
                                path[1:] + [start_vertex],
                            )
                        )
                        cycle_edge_sets.add(cycle_edges)
                        if len(cycle_edge_sets) > MAX_RESIDUAL_CYCLE_CANDIDATES:
                            raise FeatureChamferDirectBridgeError(
                                "junction_hole_cycle_budget_exceeded",
                                "Residual junction Boundary exposes too many hole candidates",
                                {
                                    "edge_count": len(residual_component),
                                    "candidate_limit": MAX_RESIDUAL_CYCLE_CANDIDATES,
                                },
                            )
                    continue
                if (
                    next_vertex in visited_vertices
                    or vertex_ranks[next_vertex] < vertex_ranks[start_vertex]
                ):
                    continue
                walk(
                    next_vertex,
                    path + [next_vertex],
                    visited_vertices | {next_vertex},
                )

        walk(start_vertex, [start_vertex], {start_vertex})

    simple_cycles = sorted(
        (
            set(cycle_edges)
            for cycle_edges in cycle_edge_sets
            if _component_shape(set(cycle_edges))[0]
        ),
        key=cycle_geometry_key,
    )
    best_cycles = []
    best_coverage = -1
    best_signature = None
    cycle_pairing_states = 0

    def choose(cycle_index, chosen_cycles, claimed_edges):
        nonlocal best_cycles, best_coverage, best_signature, cycle_pairing_states
        cycle_pairing_states += 1
        if cycle_pairing_states > MAX_RESIDUAL_CYCLE_PAIRING_STATES:
            raise FeatureChamferDirectBridgeError(
                "junction_hole_cycle_budget_exceeded",
                "Residual junction Boundary pairing exceeded the safe search budget",
                {
                    "edge_count": len(residual_component),
                    "candidate_count": len(simple_cycles),
                    "search_state_limit": MAX_RESIDUAL_CYCLE_PAIRING_STATES,
                },
            )
        if cycle_index == len(simple_cycles):
            coverage = len(claimed_edges)
            signature = tuple(sorted(
                cycle_geometry_key(cycle_edges)
                for cycle_edges in chosen_cycles
            ))
            if (
                coverage > best_coverage
                or (
                    coverage == best_coverage
                    and (best_signature is None or signature < best_signature)
                )
            ):
                best_coverage = coverage
                best_cycles = list(chosen_cycles)
                best_signature = signature
            return
        choose(cycle_index + 1, chosen_cycles, claimed_edges)
        cycle_edges = simple_cycles[cycle_index]
        if not cycle_edges & claimed_edges:
            choose(
                cycle_index + 1,
                chosen_cycles + [cycle_edges],
                claimed_edges | cycle_edges,
            )

    choose(0, [], set())
    return best_cycles


# 清理 Boolean Pro 留下的单面孤岛，真正空孔按 Blender Fill 后显式三角化非平面 n-gon。
# bm/residual_components: 全部槽段 Bridge 后的 BMesh 与自然 Boundary components；返回 Fill/清理记录和新面。
def _fill_junction_holes(
    bm,
    residual_components,
    boundary_layer,
    segment_layers,
    patch_layers,
    chamfer_faces,
    chamfer_face_layer,
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
        internal_chords = [
            edge
            for edge in bm.edges
            if edge not in residual_component
            and all(vertex in component_vertices for vertex in edge.verts)
        ]
        has_internal_chord = bool(internal_chords)
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
        if (
            not has_internal_chord
            and any(len(face.verts) > 4 for face in new_faces)
        ):
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
        for face in triangulated_faces:
            face[chamfer_face_layer] = 1
        bm.normal_update()
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        fill_records.append(
            {
                "edge_count": len(residual_component),
                "face_count": len(triangulated_faces),
                "native_operator": "Blender Fill",
                "triangulated": not has_internal_chord,
                "kept_ngon_to_preserve_existing_chord": has_internal_chord,
                "internal_chord_count": len(internal_chords),
                "internal_chord_edge_indices": sorted(
                    edge.index for edge in internal_chords
                ),
                "created_self_intersection_count": 0,
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
        cycle_budget_exceeded = False
        try:
            graph_cycles = _boundary_cycles_by_graph(residual_component)
        except FeatureChamferDirectBridgeError as error:
            if error.error_code != "junction_hole_cycle_budget_exceeded":
                raise
            cycle_budget_exceeded = True
            graph_cycles = []
        if graph_cycles:
            junction_holes.extend(graph_cycles)
            continue
        _, endpoint_count = _component_shape(residual_component)
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
                        "component_edge_count": len(residual_component),
                        "component_endpoint_count": endpoint_count,
                    },
                )
            owner_edges.setdefault(owner_id, set()).add(edge)
        owner_components = [
            (owner_id, component)
            for owner_id, edges in owner_edges.items()
            for component in _edge_components(edges)
        ]
        if (len(owner_components) == 1 or len(owner_edges) == 1) and not cycle_budget_exceeded:
            junction_holes.append(residual_component)
            continue
        cyclic_owner_components = [
            component
            for _, component in owner_components
            if _component_shape(component)[0]
        ]
        if not all(
            _component_shape(component)[0]
            for _, component in owner_components
        ) and not cycle_budget_exceeded:
            junction_holes.append(residual_component)
            continue
        if cycle_budget_exceeded:
            junction_holes.extend(cyclic_owner_components)
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


# 从 component 的自然端点恢复两端 station，作为完整槽段左右链的 terminal interval 身份。
# component/segment_id/layers: 单一 open chain、槽段 ID 与 point provenance；返回有序端点 station 或 None。
def _component_terminal_station_interval(
    component,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    endpoints = _component_endpoints(component)
    if endpoints is None:
        return None
    endpoint_stations = [
        sum(
            _vertex_station_endpoints(
                vertex,
                segment_id,
                segment_point_layers,
                station_point_layers,
                station_squared_point_layers,
            )
        )
        * 0.5
        for vertex in endpoints
    ]
    return tuple(sorted(endpoint_stations))


# 依据槽段 exact owner Surface pair 与 station 区间选择唯一左右两侧，歧义候选留给 fail-closed。
# components/patch_layers/owner_pairs/segment_id/layers: 当前槽段分量、Patch、source pairs、槽段与 Point provenance；返回唯一 pair、两侧 chains 和 junction fragments。
def _segment_side_chains(
    components,
    patch_layers,
    owner_pairs,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    patch_components = {}
    for component in components:
        component_patch_ids = {
            patch_id
            for patch_id, layer in patch_layers.items()
            if all(bool(edge[layer]) for edge in component)
        }
        if len(component_patch_ids) != 1:
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
    component_pair_candidates = []
    for owner_pair in owner_pairs:
        component_groups = [
            complete_patch_components.get(patch_id, [])
            for patch_id in owner_pair
        ]
        if not all(component_groups):
            continue
        if not all(len(component_group) == 1 for component_group in component_groups):
            continue
        first_component, second_component = (
            component_groups[0][0],
            component_groups[1][0],
        )
        if all(
            _component_shape(component)[0]
            for component in (first_component, second_component)
        ):
            component_pair_candidates.append(
                (owner_pair, first_component, second_component)
            )
            continue
        first_interval = _component_terminal_station_interval(
            first_component,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        second_interval = _component_terminal_station_interval(
            second_component,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        if first_interval is not None and second_interval is not None:
            component_pair_candidates.append(
                (owner_pair, first_component, second_component)
            )
    if len(component_pair_candidates) != 1:
        return None, None, set()
    selected_pair, first_component, second_component = component_pair_candidates[0]
    selected_components = [first_component, second_component]
    junction_fragments = {
        edge
        for patch_id, patch_group in patch_components.items()
        if patch_id not in selected_pair
        for component in patch_group
        for edge in component
    }
    return selected_pair, selected_components, junction_fragments


# 从 Preview 冻结合同读取当前槽段的 exact source Edge owner Surface pairs，并与 ChamferPlan 交叉核验。
# segment/expected_chamfer_plan: 当前槽段 JSON 记录与 immutable plan；返回保持 source Edge 顺序去重后的 pairs。
def _segment_owner_surface_pairs(segment, expected_chamfer_plan):
    owner_pairs = []
    for raw_owner_pair in segment.get("owner_surface_pairs", ()):
        owner_pair = tuple(int(patch_id) for patch_id in raw_owner_pair)
        if len(owner_pair) != 2 or owner_pair[0] == owner_pair[1]:
            raise FeatureChamferDirectBridgeError(
                "segment_owner_pair_invalid",
                f"Segment {segment['segment_id']} has an invalid owner Surface pair",
            )
        if owner_pair not in owner_pairs:
            owner_pairs.append(owner_pair)
    plan_owner_pairs = {
        correspondence.owner_surface_pair
        for correspondence in expected_chamfer_plan.strip_correspondences
        if correspondence.owner_strand_id == segment["strand_id"]
    }
    if not owner_pairs:
        raise FeatureChamferDirectBridgeError(
            "segment_owner_pair_missing",
            f"Segment {segment['segment_id']} has no source Edge owner Surface pair",
        )
    if any(owner_pair not in plan_owner_pairs for owner_pair in owner_pairs):
        raise FeatureChamferDirectBridgeError(
            "segment_owner_pair_plan_mismatch",
            f"Segment {segment['segment_id']} owner Surface pair does not match ChamferPlan",
            {
                "segment_id": int(segment["segment_id"]),
                "contract_owner_pairs": [list(pair) for pair in owner_pairs],
                "plan_owner_pairs": [list(pair) for pair in sorted(plan_owner_pairs)],
            },
        )
    return owner_pairs


# 当一侧在 Surface Patch 接缝切换时，按组件顺序和共同 owner pair 选中整条槽边。
# components/patch_layers/owner_pairs: 两条完整边链、Patch 属性与 Plan owner pairs；返回配对或 None。
def _seam_spanning_side_chains(components, patch_layers, owner_pairs):
    if len(components) != 2:
        return None
    component_patch_ids = [
        {
            patch_id
            for patch_id, layer in patch_layers.items()
            if any(bool(edge[layer]) for edge in component)
        }
        for component in components
    ]
    candidate_pairs = [
        owner_pair
        for owner_pair in owner_pairs
        if all(
            set(owner_pair) & patch_ids
            for patch_ids in component_patch_ids
        )
    ]
    if len(candidate_pairs) != 1:
        return None
    return candidate_pairs[0], list(components), set()


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


# 计算 open/cyclic 折线的累计长度，用于证明 Bridge 输入清理没有改变原链形状。
# coordinates/cyclic: 按拓扑顺序排列的坐标与闭环标记；返回累计弧长。
def _polyline_length(coordinates, cyclic):
    coordinate_pairs = list(zip(coordinates, coordinates[1:]))
    if cyclic and len(coordinates) > 1:
        coordinate_pairs.append((coordinates[-1], coordinates[0]))
    return sum((end - start).length for start, end in coordinate_pairs)


# 计算点到有限线段的最短距离，避免只用无限直线误放行超出端点的清理结果。
# point/start/end: 待检查点与线段两端坐标；返回非负距离。
def _point_to_segment_distance(point, start, end):
    segment = end - start
    squared_length = segment.length_squared
    if squared_length <= 1.0e-30:
        return (point - start).length
    factor = max(0.0, min(1.0, (point - start).dot(segment) / squared_length))
    return (point - (start + segment * factor)).length


# 双向核对两条 open/cyclic 折线的 Vertex 到对方线段最大偏差，证明清理前后几何等价。
# source/cleaned/cyclic: 清理前后有序坐标及闭环标记；返回双向最大偏差。
def _polyline_maximum_deviation(source, cleaned, cyclic):
    def segments(coordinates):
        result = list(zip(coordinates, coordinates[1:]))
        if cyclic and len(coordinates) > 1:
            result.append((coordinates[-1], coordinates[0]))
        return result

    source_segments = segments(source)
    cleaned_segments = segments(cleaned)
    if not source_segments or not cleaned_segments:
        return math.inf

    def maximum_vertex_distance(coordinates, target_segments):
        return max(
            min(
                _point_to_segment_distance(coordinate, start, end)
                for start, end in target_segments
            )
            for coordinate in coordinates
        )

    return max(
        maximum_vertex_distance(source, cleaned_segments),
        maximum_vertex_distance(cleaned, source_segments),
    )


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
    component_endpoints = set(_component_endpoints(component) or ())
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
                "component_endpoint": vertex in component_endpoints,
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


# 从 Boolean 已插值的 station 一阶、二阶矩恢复 Boundary Edge 对应的 Pipe edge 端点值。
# edge/segment_id/layers: Boundary Edge、槽段 ID 与 provenance layers；返回有序 station 端点二元组。
def _edge_station_endpoints(
    edge,
    segment_id,
    segment_layers,
    station_edge_layers,
    station_squared_edge_layers,
):
    membership = float(edge[segment_layers[segment_id]])
    if membership <= 1.0e-6:
        raise FeatureChamferDirectBridgeError(
            "segment_station_edge_membership_missing",
            f"Segment {segment_id} Edge lacks station membership",
        )
    mean = float(edge[station_edge_layers[segment_id]]) / membership
    mean_squared = (
        float(edge[station_squared_edge_layers[segment_id]]) / membership
    )
    deviation = max(0.0, mean_squared - mean * mean) ** 0.5
    return tuple(sorted((mean - deviation, mean + deviation)))


# 将 cyclic Edge 的 station 端点提升到同一圈，避免闭合边的 0/1 被线性平均到环中部。
# edge/segment_id/layers: Boundary Edge、槽段 ID 与 provenance layers；返回 0..1 的环绕 station。
def _cyclic_edge_station(
    edge,
    segment_id,
    segment_layers,
    station_edge_layers,
    station_squared_edge_layers,
):
    low, high = _edge_station_endpoints(
        edge,
        segment_id,
        segment_layers,
        station_edge_layers,
        station_squared_edge_layers,
    )
    if high - low > 0.5:
        low += 1.0
    return ((low + high) * 0.5) % 1.0


# 验证同一 Bridge job 的两侧链在 segment station 上相交，防止跨槽段或反向错连。
# components/segment_id/layers: 已按 exact owner pair 锁定的两侧链、槽段与 station layers；返回两侧区间与 overlap 身份。
def _validate_bridge_job_station_interval(
    components,
    segment_id,
    segment_layers,
    station_edge_layers,
):
    side_station_intervals = []
    for component in components:
        stations = [
            _edge_station_midpoint(
                edge,
                segment_id,
                segment_layers,
                station_edge_layers,
            )
            for edge in component
        ]
        side_station_intervals.append((min(stations), max(stations)))
    overlap_low = max(interval[0] for interval in side_station_intervals)
    overlap_high = min(interval[1] for interval in side_station_intervals)
    interval_overlap_valid = overlap_low <= overlap_high + 5.0e-4
    if not interval_overlap_valid:
        raise FeatureChamferDirectBridgeError(
            "segment_station_interval_mismatch",
            f"Segment {segment_id} side chains do not share one station interval",
            {
                "segment_id": segment_id,
                "side_station_intervals": [
                    [float(value) for value in interval]
                    for interval in side_station_intervals
                ],
            },
        )
    return side_station_intervals, interval_overlap_valid


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


# 从 Pipe 合同的弧长采样中归并圆角采样，找出彼此由直段分开的显著转折区间。
# segment: 已锁定槽段的 immutable Pipe 合同；返回按 station 排序的转折区间。
def _segment_major_turn_regions(segment):
    point_coordinates = tuple(segment.get("point_coordinates", ()))
    point_stations = tuple(float(value) for value in segment.get("point_stations", ()))
    if (
        len(point_coordinates) < 3
        or len(point_coordinates) != len(point_stations)
    ):
        return []
    points = [tuple(float(value) for value in point) for point in point_coordinates]
    turn_samples = []
    for point_index in range(1, len(points) - 1):
        previous_vector = tuple(
            points[point_index][axis] - points[point_index - 1][axis]
            for axis in range(3)
        )
        next_vector = tuple(
            points[point_index + 1][axis] - points[point_index][axis]
            for axis in range(3)
        )
        previous_length = math.sqrt(sum(value * value for value in previous_vector))
        next_length = math.sqrt(sum(value * value for value in next_vector))
        if previous_length <= 1.0e-9 or next_length <= 1.0e-9:
            continue
        cosine = sum(
            previous_vector[axis] * next_vector[axis]
            for axis in range(3)
        ) / (previous_length * next_length)
        turn_radians = math.acos(max(-1.0, min(1.0, cosine)))
        if turn_radians < MIN_TURN_SAMPLE_RADIANS:
            continue
        turn_samples.append(
            {
                "point_index": point_index,
                "station": point_stations[point_index],
                "turn_radians": turn_radians,
            }
        )
    turn_clusters = []
    for sample in turn_samples:
        split_cluster = not turn_clusters
        if turn_clusters:
            previous_sample = turn_clusters[-1][-1]
            previous_index = previous_sample["point_index"]
            point_index = sample["point_index"]
            if point_index > previous_index + 1:
                split_cluster = True
            else:
                connector_length = math.dist(
                    points[previous_index],
                    points[point_index],
                )
                previous_sample_length = math.dist(
                    points[previous_index - 1],
                    points[previous_index],
                )
                next_sample_length = math.dist(
                    points[point_index],
                    points[point_index + 1],
                )
                split_cluster = connector_length > 2.0 * max(
                    previous_sample_length,
                    next_sample_length,
                )
        if split_cluster:
            turn_clusters.append([sample])
        else:
            turn_clusters[-1].append(sample)
    regions = []
    for cluster in turn_clusters:
        total_turn = sum(sample["turn_radians"] for sample in cluster)
        if total_turn < MIN_MAJOR_TURN_RADIANS:
            continue
        first_index = cluster[0]["point_index"]
        last_index = cluster[-1]["point_index"]
        regions.append(
            {
                "station_low": point_stations[first_index],
                "station_high": point_stations[last_index],
                "cut_station": point_stations[last_index],
                "turn_radians": total_turn,
            }
        )
    return regions


# 将 chain 上重合的连续 Boolean 顶点折叠为几何采样，避免零长度边伪造局部急转。
# component: 单一 open chain；返回按拓扑顺序排列的代表 Vertex。
def _distinct_chain_vertices(component):
    ordered_vertices = _ordered_chain_vertices(component)
    if len(ordered_vertices) != len(component) + 1:
        return []
    chain_length = sum(edge.calc_length() for edge in component)
    coordinate_tolerance = max(1.0e-8, chain_length * 1.0e-8)
    vertex_groups = []
    for vertex in ordered_vertices:
        if (
            vertex_groups
            and (vertex.co - vertex_groups[-1][-1].co).length <= coordinate_tolerance
        ):
            vertex_groups[-1].append(vertex)
        else:
            vertex_groups.append([vertex])
    return [group[len(group) // 2] for group in vertex_groups]


# 验证一侧 chain 在合同转折区间内确有同向几何转折，并选取现有转折边界 Vertex。
# component/region/segment_id/layers: 槽边、转折区间、槽段与 provenance；返回切点与实测 station。
def _component_turn_cut_vertex(
    component,
    region,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    distinct_vertices = _distinct_chain_vertices(component)
    if len(distinct_vertices) < 3:
        return None
    station_vertices = []
    for vertex in distinct_vertices:
        station_endpoints = _vertex_station_endpoints(
            vertex,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        station_vertices.append((sum(station_endpoints) * 0.5, vertex))
    if station_vertices[0][0] > station_vertices[-1][0]:
        station_vertices.reverse()
    station_tolerance = max(
        5.0e-4,
        (region["station_high"] - region["station_low"]) * 0.25,
    )
    turn_radians = 0.0
    for vertex_index in range(1, len(station_vertices) - 1):
        station, vertex = station_vertices[vertex_index]
        if not (
            region["station_low"] - station_tolerance
            <= station
            <= region["station_high"] + station_tolerance
        ):
            continue
        previous_vertex = station_vertices[vertex_index - 1][1]
        next_vertex = station_vertices[vertex_index + 1][1]
        previous_vector = vertex.co - previous_vertex.co
        next_vector = next_vertex.co - vertex.co
        if previous_vector.length <= 1.0e-9 or next_vector.length <= 1.0e-9:
            continue
        turn_radians += previous_vector.angle(next_vector)
    if turn_radians < MIN_MAJOR_TURN_RADIANS:
        return None
    interior_candidates = station_vertices[1:-1]
    cut_station, cut_vertex = min(
        interior_candidates,
        key=lambda item: (
            abs(item[0] - region["cut_station"]),
            item[0] < region["cut_station"],
            item[1].index,
        ),
    )
    if abs(cut_station - region["cut_station"]) > station_tolerance:
        return None
    return cut_vertex, cut_station, turn_radians


# 对已经锁定且含多个共同大转折的左右 chain 同步切段，不插点也不建立逐点对应。
# components/segment/layers: 同一 Bridge job 的两侧 chain、合同与 provenance；返回子 jobs 与切段诊断。
def _split_bridge_job_at_common_turns(
    components,
    segment,
    segment_layers,
    segment_point_layers,
    station_edge_layers,
    station_point_layers,
    station_squared_point_layers,
):
    if len(components) != 2 or any(
        _component_shape(component) != (False, 2)
        for component in components
    ):
        return None
    segment_id = int(segment["segment_id"])
    side_station_intervals, _ = _validate_bridge_job_station_interval(
        components,
        segment_id,
        segment_layers,
        station_edge_layers,
    )
    overlap_low = max(interval[0] for interval in side_station_intervals)
    overlap_high = min(interval[1] for interval in side_station_intervals)
    common_turns = []
    for region in _segment_major_turn_regions(segment):
        if not (
            overlap_low + 5.0e-4
            < region["cut_station"]
            < overlap_high - 5.0e-4
        ):
            continue
        side_cuts = [
            _component_turn_cut_vertex(
                component,
                region,
                segment_id,
                segment_point_layers,
                station_point_layers,
                station_squared_point_layers,
            )
            for component in components
        ]
        if any(cut is None for cut in side_cuts):
            continue
        side_cut_stations = [cut[1] for cut in side_cuts]
        station_tolerance = max(
            1.0e-3,
            (region["station_high"] - region["station_low"]) * 0.5,
        )
        if abs(side_cut_stations[0] - side_cut_stations[1]) > station_tolerance:
            continue
        if any(
            common_turns
            and cut[0] is common_turns[-1]["side_cuts"][side_index][0]
            for side_index, cut in enumerate(side_cuts)
        ):
            continue
        common_turns.append(
            {
                "contract_station": region["cut_station"],
                "contract_turn_degrees": math.degrees(region["turn_radians"]),
                "side_cut_stations": side_cut_stations,
                "side_turn_degrees": [
                    math.degrees(cut[2]) for cut in side_cuts
                ],
                "side_cuts": side_cuts,
            }
        )
    if not common_turns:
        return None
    side_runs = [
        _component_station_runs(
            component,
            [turn["side_cuts"][side_index][0] for turn in common_turns],
            segment_id,
            segment_layers,
            station_edge_layers,
        )
        for side_index, component in enumerate(components)
    ]
    if len(side_runs[0]) != len(common_turns) + 1 or len(side_runs[1]) != len(side_runs[0]):
        raise FeatureChamferDirectBridgeError(
            "segment_turn_split_incomplete",
            f"Segment {segment_id} common turn split did not preserve both chains",
            {
                "segment_id": segment_id,
                "common_turn_count": len(common_turns),
                "side_run_counts": [len(runs) for runs in side_runs],
            },
        )
    for side_index, component in enumerate(components):
        if set().union(*side_runs[side_index]) != set(component) or sum(
            len(run) for run in side_runs[side_index]
        ) != len(component):
            raise FeatureChamferDirectBridgeError(
                "segment_turn_split_incomplete",
                f"Segment {segment_id} common turn split lost or reused Boundary Edges",
                {"segment_id": segment_id, "side_index": side_index},
            )
    return (
        list(zip(side_runs[0], side_runs[1])),
        [
            {
                key: value
                for key, value in turn.items()
                if key != "side_cuts"
            }
            for turn in common_turns
        ],
    )


# 从冻结 cyclic Pipe 合同累计闭合转向，生成以合同 seam 和方向为锚点的局部 Bridge 区间。
# segment: 已锁定的 immutable cyclic Pipe 合同；返回按合同顺序排列的切点 station。
def _cyclic_bridge_cut_stations(segment):
    point_coordinates = tuple(segment.get("point_coordinates", ()))
    point_stations = tuple(float(value) for value in segment.get("point_stations", ()))
    if (
        not bool(segment.get("is_cyclic"))
        or len(point_coordinates) < 3
        or len(point_coordinates) != len(point_stations)
        or any(
            current_station <= previous_station
            for previous_station, current_station in zip(
                point_stations,
                point_stations[1:],
            )
        )
        or point_stations[0] < -1.0e-6
        or point_stations[-1] >= 1.0 - 1.0e-6
    ):
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_contract_invalid",
            f"Segment {segment.get('segment_id')} lacks an ordered cyclic Pipe contract",
        )
    points = [tuple(float(value) for value in point) for point in point_coordinates]
    turns = []
    for point_index in range(len(points)):
        previous_point = points[(point_index - 1) % len(points)]
        point = points[point_index]
        next_point = points[(point_index + 1) % len(points)]
        previous_vector = tuple(
            point[axis] - previous_point[axis]
            for axis in range(3)
        )
        next_vector = tuple(
            next_point[axis] - point[axis]
            for axis in range(3)
        )
        previous_length = math.sqrt(sum(value * value for value in previous_vector))
        next_length = math.sqrt(sum(value * value for value in next_vector))
        if previous_length <= 1.0e-9 or next_length <= 1.0e-9:
            turns.append(0.0)
            continue
        cosine = sum(
            previous_vector[axis] * next_vector[axis]
            for axis in range(3)
        ) / (previous_length * next_length)
        turns.append(math.acos(max(-1.0, min(1.0, cosine))))
    total_turn = sum(turns)
    job_count = int(round(total_turn / TARGET_CYCLIC_BRIDGE_TURN_RADIANS))
    if job_count < 2:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_turn_contract_invalid",
            f"Segment {segment['segment_id']} cyclic Pipe has no local Bridge intervals",
            {
                "segment_id": int(segment["segment_id"]),
                "contract_total_turn_degrees": math.degrees(total_turn),
            },
        )
    target_turn = total_turn / job_count
    cut_stations = []
    cumulative_turn = 0.0
    target_index = 1
    for point_index, turn_radians in enumerate(turns):
        previous_turn = cumulative_turn
        cumulative_turn += turn_radians
        while (
            target_index < job_count
            and cumulative_turn + 1.0e-9 >= target_turn * target_index
        ):
            previous_index = (point_index - 1) % len(points)
            candidates = (
                (
                    abs(previous_turn - target_turn * target_index),
                    previous_index,
                ),
                (
                    abs(cumulative_turn - target_turn * target_index),
                    point_index,
                ),
            )
            selected_index = min(candidates)[1]
            station = point_stations[selected_index]
            if station >= 1.0 - 1.0e-6:
                station = 0.0
            if cut_stations and station <= cut_stations[-1] + 1.0e-6:
                raise FeatureChamferDirectBridgeError(
                    "cyclic_bridge_cut_not_unique",
                    f"Segment {segment['segment_id']} cyclic cuts are not unique",
                )
            cut_stations.append(station)
            target_index += 1
    if len(cut_stations) != job_count - 1:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_cut_incomplete",
            f"Segment {segment['segment_id']} cyclic Pipe did not yield complete local intervals",
        )
    return [0.0, *cut_stations]


# 根据冻结 Pipe 在目标切点前后的真实采样间隔，限定 Boolean Boundary 可接受的局部 station 邻域。
# segment/target_station: cyclic Pipe 合同与其中一个切点；返回局部或典型采样一步的环绕 station 容差。
def _cyclic_contract_station_neighborhood(segment, target_station):
    point_stations = tuple(float(value) for value in segment.get("point_stations", ()))
    if len(point_stations) < 3:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_contract_invalid",
            f"Segment {segment.get('segment_id')} lacks cyclic station samples",
        )

    def circular_distance(first, second):
        difference = abs(first - second)
        return min(difference, 1.0 - difference)

    target_index = min(
        range(len(point_stations)),
        key=lambda index: circular_distance(point_stations[index], target_station),
    )
    if circular_distance(point_stations[target_index], target_station) > 1.0e-6:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_cut_not_on_contract",
            f"Segment {segment.get('segment_id')} cyclic cut is not a Pipe sample",
        )
    previous_station = point_stations[(target_index - 1) % len(point_stations)]
    station = point_stations[target_index]
    next_station = point_stations[(target_index + 1) % len(point_stations)]
    previous_interval = (station - previous_station) % 1.0
    next_interval = (next_station - station) % 1.0
    positive_intervals = sorted(
        (current_station - previous_station) % 1.0
        for previous_station, current_station in zip(
            point_stations,
            (*point_stations[1:], point_stations[0]),
        )
        if (current_station - previous_station) % 1.0 > 1.0e-6
    )
    if not positive_intervals:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_contract_invalid",
            f"Segment {segment.get('segment_id')} lacks positive cyclic station intervals",
        )
    median_interval = positive_intervals[len(positive_intervals) // 2]
    neighborhood = max(previous_interval, next_interval, median_interval)
    if neighborhood <= 1.0e-6 or neighborhood >= 0.5:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_contract_invalid",
            f"Segment {segment.get('segment_id')} has an invalid local station interval",
        )
    return neighborhood + 1.0e-6


# 用 station provenance 归并完整 Boundary 环上的连续同 station 碎点。
# component/segment_id/layers: 完整 cyclic Boundary 与 provenance；返回按 topology 排列的 station plateau。
def _cyclic_station_plateaus(
    component,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    ordered_vertices = _ordered_cycle_vertices(component)
    station_vertices = []
    for vertex in ordered_vertices:
        station_endpoints = _vertex_station_endpoints(
            vertex,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        station_vertices.append(
            (
                sum(station_endpoints) * 0.5 % 1.0,
                vertex,
            )
        )
    plateaus = []
    for station, vertex in station_vertices:
        if plateaus and min(
            abs(station - plateaus[-1]["station"]),
            1.0 - abs(station - plateaus[-1]["station"]),
        ) <= 1.0e-6:
            plateaus[-1]["vertices"].append(vertex)
        else:
            plateaus.append({"station": station, "vertices": [vertex]})
    if len(plateaus) > 1 and min(
        abs(plateaus[0]["station"] - plateaus[-1]["station"]),
        1.0 - abs(plateaus[0]["station"] - plateaus[-1]["station"]),
    ) <= 1.0e-6:
        plateaus[0]["vertices"] = (
            plateaus[-1]["vertices"] + plateaus[0]["vertices"]
        )
        plateaus.pop()
    for plateau in plateaus:
        plateau["vertex"] = plateau["vertices"][len(plateau["vertices"]) // 2]
    return plateaus


# 在两侧 station plateau 中先锁定局部合同邻域，再以真实空间邻接选择同一切点。
# components/target_station/station_neighborhood/segment_id/layers: 完整双环、合同 station、局部采样容差与 provenance；返回两侧已有切点和实测 station。
def _cyclic_common_cut_vertices(
    components,
    target_station,
    station_neighborhood,
    segment_id,
    segment_point_layers,
    station_point_layers,
    station_squared_point_layers,
):
    side_plateaus = [
        _cyclic_station_plateaus(
            component,
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        for component in components
    ]

    def circular_distance(first, second):
        difference = abs(first - second)
        return min(difference, 1.0 - difference)

    local_side_plateaus = []
    for plateaus in side_plateaus:
        local_plateaus = [
            plateau
            for plateau in plateaus
            if circular_distance(plateau["station"], target_station)
            <= station_neighborhood
        ]
        if not local_plateaus:
            raise FeatureChamferDirectBridgeError(
                "cyclic_bridge_station_missing",
                f"Segment {segment_id} cyclic side lacks a local contract cut station",
                {
                    "segment_id": segment_id,
                    "contract_station": target_station,
                    "station_neighborhood": station_neighborhood,
                },
            )
        local_side_plateaus.append(local_plateaus)

    candidates = []
    for first_plateau in local_side_plateaus[0]:
        for second_plateau in local_side_plateaus[1]:
            station_delta = circular_distance(
                first_plateau["station"],
                second_plateau["station"],
            )
            contract_distance = max(
                circular_distance(first_plateau["station"], target_station),
                circular_distance(second_plateau["station"], target_station),
            )
            boundary_distance = (
                first_plateau["vertex"].co - second_plateau["vertex"].co
            ).length
            candidates.append(
                (
                    contract_distance,
                    station_delta,
                    boundary_distance,
                    first_plateau,
                    second_plateau,
                )
            )
    if not candidates:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_station_missing",
            f"Segment {segment_id} cyclic sides lack a local contract cut station",
            {
                "segment_id": segment_id,
                "contract_station": target_station,
                "station_neighborhood": station_neighborhood,
            },
        )
    best_contract_distance = min(item[0] for item in candidates)
    local_candidates = [
        item
        for item in candidates
        if item[0] <= max(1.0e-6, best_contract_distance + 1.0e-4)
    ]
    local_candidates.sort(
        key=lambda item: (
            item[1],
            item[2],
            item[0],
            tuple(float(value) for value in item[3]["vertex"].co),
            tuple(float(value) for value in item[4]["vertex"].co),
            item[3]["vertex"].index,
            item[4]["vertex"].index,
        )
    )
    _, _, _, first_plateau, second_plateau = local_candidates[0]
    return [
        (first_plateau["vertex"], first_plateau["station"]),
        (second_plateau["vertex"], second_plateau["station"]),
    ]


# 沿原环拓扑把 N 个已有切点划成 N 条 open Edge runs，不按空间位置重排或建立逐边对应。
# component/cut_vertices: 完整 cyclic Boundary 与合同切点；返回按当前环拓扑位置排列的 open Edge sets，调用方再按共同端点对重排两侧。
def _cyclic_component_runs(component, cut_vertices):
    ordered_vertices = _ordered_cycle_vertices(component)
    positions = {vertex: index for index, vertex in enumerate(ordered_vertices)}
    if len(set(cut_vertices)) != len(cut_vertices) or any(
        vertex not in positions
        for vertex in cut_vertices
    ):
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_cut_vertex_invalid",
            "Cyclic Bridge cuts do not bind unique existing Boundary Vertices",
        )
    ordered_edges = []
    edge_by_vertices = {
        frozenset(edge.verts): edge
        for edge in component
    }
    for vertex_index, vertex in enumerate(ordered_vertices):
        next_vertex = ordered_vertices[(vertex_index + 1) % len(ordered_vertices)]
        edge = edge_by_vertices.get(frozenset((vertex, next_vertex)))
        if edge is None:
            raise FeatureChamferDirectBridgeError(
                "cyclic_bridge_traversal_incomplete",
                "Cyclic Bridge traversal lost a Boundary Edge",
            )
        ordered_edges.append(edge)
    cut_positions = sorted(positions[vertex] for vertex in cut_vertices)
    runs = []
    for cut_index, start_position in enumerate(cut_positions):
        end_position = cut_positions[(cut_index + 1) % len(cut_positions)]
        if end_position <= start_position:
            end_position += len(ordered_edges)
        run = {
            ordered_edges[position % len(ordered_edges)]
            for position in range(start_position, end_position)
        }
        if not run or _component_shape(run) != (False, 2):
            raise FeatureChamferDirectBridgeError(
                "cyclic_bridge_run_invalid",
                "Cyclic Bridge produced a non-open local Boundary arc",
            )
        runs.append(run)
    return runs


# 对已锁定的完整 cyclic 双环按共同累计转向 station 划成局部 Bridge jobs。
# components/segment/layers: 两侧完整环、冻结合同与 station provenance；返回局部 jobs 和诊断。
def _split_cyclic_bridge_job(
    components,
    segment,
    segment_layers,
    segment_point_layers,
    station_edge_layers,
    station_squared_edge_layers,
    station_point_layers,
    station_squared_point_layers,
):
    if len(components) != 2 or any(
        _component_shape(component) != (True, 0)
        for component in components
    ):
        return None
    if min(len(component) for component in components) < MIN_CYCLIC_BRIDGE_SIDE_EDGE_COUNT:
        return None
    segment_id = int(segment["segment_id"])
    if not bool(segment.get("is_cyclic")):
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_contract_mismatch",
            f"Segment {segment_id} exposes cyclic Boundary Loops without cyclic Pipe authority",
        )
    contract_cut_stations = _cyclic_bridge_cut_stations(segment)
    station_neighborhoods = [
        _cyclic_contract_station_neighborhood(segment, target_station)
        for target_station in contract_cut_stations
    ]
    common_cuts = [
        _cyclic_common_cut_vertices(
            components,
            target_station,
            station_neighborhoods[cut_index],
            segment_id,
            segment_point_layers,
            station_point_layers,
            station_squared_point_layers,
        )
        for cut_index, target_station in enumerate(contract_cut_stations)
    ]
    for cut_index, target_station in enumerate(contract_cut_stations):
        side_stations = [common_cuts[cut_index][side_index][1] for side_index in range(2)]
        if any(
            min(
                abs(side_station - target_station),
                1.0 - abs(side_station - target_station),
            ) > station_neighborhoods[cut_index]
            for side_station in side_stations
        ):
            raise FeatureChamferDirectBridgeError(
                "cyclic_bridge_station_outside_contract_neighborhood",
                f"Segment {segment_id} cyclic side is outside its local Pipe interval",
                {
                    "segment_id": segment_id,
                    "contract_station": target_station,
                    "side_cut_stations": side_stations,
                },
            )
    side_runs = [
        _cyclic_component_runs(
            component,
            [common_cut[side_index][0] for common_cut in common_cuts],
        )
        for side_index, component in enumerate(components)
    ]
    if len(side_runs[0]) != len(side_runs[1]) or len(side_runs[0]) < 2:
        raise FeatureChamferDirectBridgeError(
            "cyclic_bridge_split_incomplete",
            f"Segment {segment_id} cyclic sides produced different local job counts",
        )
    for side_index, component in enumerate(components):
        if set().union(*side_runs[side_index]) != set(component) or sum(
            len(run) for run in side_runs[side_index]
        ) != len(component):
            raise FeatureChamferDirectBridgeError(
                "cyclic_bridge_split_incomplete",
                f"Segment {segment_id} cyclic split lost or reused Boundary Edges",
                {"segment_id": segment_id, "side_index": side_index},
            )
    for side_index in range(2):
        run_by_endpoint_pair = {}
        for run in side_runs[side_index]:
            endpoints = _component_endpoints(run)
            if endpoints is None:
                raise FeatureChamferDirectBridgeError(
                    "cyclic_bridge_run_invalid",
                    f"Segment {segment_id} cyclic local arc has no two endpoints",
                )
            endpoint_pair = frozenset(endpoints)
            if endpoint_pair in run_by_endpoint_pair:
                raise FeatureChamferDirectBridgeError(
                    "cyclic_bridge_run_ambiguous",
                    f"Segment {segment_id} cyclic local arcs repeat one endpoint pair",
                )
            run_by_endpoint_pair[endpoint_pair] = run
        ordered_runs = []
        for cut_index in range(len(common_cuts)):
            endpoint_pair = frozenset(
                (
                    common_cuts[cut_index][side_index][0],
                    common_cuts[(cut_index + 1) % len(common_cuts)][side_index][0],
                )
            )
            run = run_by_endpoint_pair.get(endpoint_pair)
            if run is None:
                raise FeatureChamferDirectBridgeError(
                    "cyclic_bridge_interval_missing",
                    f"Segment {segment_id} cyclic side lacks one contract station interval",
                )
            ordered_runs.append(run)
        side_runs[side_index] = ordered_runs
    return (
        list(zip(side_runs[0], side_runs[1])),
        [
            {
                "contract_station": target_station,
                "side_cut_stations": [
                    common_cuts[cut_index][side_index][1]
                    for side_index in range(2)
                ],
                "side_cut_vertex_indices": [
                    common_cuts[cut_index][side_index][0].index
                    for side_index in range(2)
                ],
            }
        for cut_index, target_station in enumerate(contract_cut_stations)
        ],
        [
            sorted(edge.index for edge in component)
            for component in components
        ],
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
        [
            witness
            for witness in _component_junction_witnesses(
                component,
                segment_id,
                segment_layers,
                segment_point_layers,
                station_point_layers,
                station_squared_point_layers,
            )
            if not witness["component_endpoint"]
        ]
        for component in side_chains
    ]
    paired_foreign_segments = [
        {
            foreign_segment_id
            for witness in witnesses
            for foreign_segment_id in witness["foreign_segment_ids"]
        }
        for witnesses in witness_groups
    ]
    shared_foreign_segments = (
        set.intersection(*paired_foreign_segments)
        if all(paired_foreign_segments)
        else set()
    )
    witness_station_groups = [
        {
            round(sum(witness["station_endpoints"]) * 0.5, 6)
            for witness in witnesses
        }
        for witnesses in witness_groups
    ]
    all_witness_stations = [
        sum(witness["station_endpoints"]) * 0.5
        for witnesses in witness_groups
        for witness in witnesses
    ]
    clustered_cut_stations = []
    for station in sorted(all_witness_stations):
        if (
            not clustered_cut_stations
            or abs(station - clustered_cut_stations[-1]) > 1.0e-4
        ):
            clustered_cut_stations.append(station)
    if (
        all(len(witnesses) == 2 for witnesses in witness_groups)
        and (
            not shared_foreign_segments
            or (
                len(shared_foreign_segments) == 1
                and witness_station_groups[0] == witness_station_groups[1]
            )
        )
    ):
        cut_stations = clustered_cut_stations
        if len(cut_stations) != 2:
            return None
        interval_jobs = []
        junction_fragments = set()
        bridge_between_stations = bool(shared_foreign_segments)
        intervals = (
            (float("-inf"), cut_stations[0], bridge_between_stations),
            (cut_stations[0], cut_stations[1], not bridge_between_stations),
            (cut_stations[1], float("inf"), bridge_between_stations),
        )
        for low, high, is_junction in intervals:
            interval_sides = [
                {
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
                for component in side_chains
            ]
            if any(not interval_side for interval_side in interval_sides):
                continue
            if is_junction:
                junction_fragments.update(set().union(*interval_sides))
            else:
                interval_jobs.append(tuple(interval_sides))
        if interval_jobs:
            return interval_jobs, junction_fragments
        return None
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


# 对被另一根 Pipe 截断的同一槽段，按 owner Patch、junction witness 与 station 生成多个实际 Bridge jobs。
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
    if any(_component_shape(component)[0] for component in interrupted_side):
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
    if len(interrupted_side) >= 2:
        regular_components = [
            component
            for component in interrupted_side
            if len(component) > 4
        ]
        if len(regular_components) == 1:
            regular_endpoints = _component_endpoints(regular_components[0])
            if regular_endpoints is None:
                return None
            endpoint_margin = min(
                min(endpoint_stations[vertex], 1.0 - endpoint_stations[vertex])
                for vertex in regular_endpoints
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
        else:
            complete_side_length = sum(edge.calc_length() for edge in complete_side)
            comparable_components = [
                component
                for component in interrupted_side
                if sum(edge.calc_length() for edge in component)
                > 0.1 * complete_side_length
            ]
            if len(comparable_components) == 1:
                selected_component = comparable_components[0]
                selected_endpoints = _component_endpoints(selected_component) or ()
                selected_foreign_ids = {
                    other_id
                    for vertex in selected_endpoints
                    for edge in vertex.link_edges
                    for other_id, layer in segment_layers.items()
                    if other_id != segment_id
                    and float(edge[layer]) > 1.0e-6
                }
                deferred_components = [
                    component
                    for component in interrupted_side
                    if component is not selected_component
                ]
                deferred_foreign_ids = [
                    {
                        other_id
                        for vertex in (_component_endpoints(component) or ())
                        for edge in vertex.link_edges
                        for other_id, layer in segment_layers.items()
                        if other_id != segment_id
                        and float(edge[layer]) > 1.0e-6
                    }
                    for component in deferred_components
                ]
                if not all(
                    selected_foreign_ids & foreign_ids
                    for foreign_ids in deferred_foreign_ids
                ):
                    return None
                return owner_pair, [(selected_component, complete_side)], set().union(
                    *deferred_components
                )
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


# 在单侧 Bridge chain 内逐个处理极短 Edge 连通簇，并溶解无第三条 Edge 接入的严格共线中间点。
# bm/component/radius/boundary_layer: 当前 BMesh、单侧真实 Bridge chain、Radius 与 Boundary layer；返回清理后的 chain 和统计。
def _clean_bridge_component(
    bm,
    component,
    radius,
    boundary_layer,
):
    source_component = set(component)
    source_cyclic, source_endpoint_count = _component_shape(source_component)
    if source_endpoint_count not in {0, 2}:
        source_vertices = {
            vertex
            for edge in source_component
            for vertex in edge.verts
        }
        return source_component, {
            "cleanup_status": "SKIPPED_NON_SIMPLE_COMPONENT",
            "source_shape": [source_cyclic, source_endpoint_count],
            "source_edge_count": len(source_component),
            "cleaned_edge_count": len(source_component),
            "source_vertex_count": len(source_vertices),
            "cleaned_vertex_count": len(source_vertices),
            "merged_vertex_count": 0,
            "dissolved_vertex_count": 0,
        }
    source_vertices = {
        vertex
        for edge in source_component
        for vertex in edge.verts
    }
    source_coordinates = [
        vertex.co.copy()
        for vertex in _ordered_chain_vertices(source_component)
    ]
    if len(source_coordinates) != len(source_vertices):
        raise FeatureChamferDirectBridgeError(
            "bridge_cleanup_source_order_invalid",
            "Bridge cleanup could not order the complete source chain",
        )
    source_length = _polyline_length(source_coordinates, source_cyclic)
    protected_endpoints = set(_component_endpoints(source_component) or ())
    source_edge_lengths = sorted(edge.calc_length() for edge in source_component)
    median_edge_length = source_edge_lengths[len(source_edge_lengths) // 2]
    merge_distance = max(
        min(
            float(radius) * BRIDGE_MERGE_DISTANCE_FACTOR,
            median_edge_length * MAX_BRIDGE_MERGE_DISTANCE_TO_MEDIAN_EDGE_RATIO,
        ),
        MIN_BRIDGE_MERGE_DISTANCE,
    )
    zero_edge_count_before = sum(
        edge.calc_length() <= merge_distance
        for edge in source_component
    )
    source_vertex_count = len(source_vertices)
    merge_vertices = set(source_vertices - protected_endpoints)

    # 只把阈值内的真实 source Edge 组成局部连通簇，避免一次范围查询越过长边折叠整环。
    # merge_vertices/source_component/merge_distance: 可动点、原侧链与阈值；循环消费仍有效的极短 Edge 簇。
    merge_edges = {
        edge
        for edge in source_component
        if edge.calc_length() <= merge_distance
        and all(vertex in merge_vertices for vertex in edge.verts)
        and all(
            len(vertex.link_edges) == 2
            or edge.calc_length() <= MIN_BRIDGE_MERGE_DISTANCE
            for vertex in edge.verts
        )
    }
    while merge_edges:
        merge_components = _edge_components(merge_edges)
        merge_component = min(
            merge_components,
            key=lambda item: min(edge.index for edge in item),
        )
        component_vertices = {
            vertex
            for edge in merge_component
            for vertex in edge.verts
        }
        bmesh.ops.remove_doubles(
            bm,
            verts=sorted(component_vertices, key=lambda vertex: vertex.index),
            use_connected=True,
            dist=merge_distance,
        )
        merge_vertices = {
            vertex
            for vertex in merge_vertices
            if vertex.is_valid
        }
        merge_edges = {
            edge
            for edge in source_component
            if edge.is_valid
            and edge.calc_length() <= merge_distance
            and all(vertex in merge_vertices for vertex in edge.verts)
            and all(
                len(vertex.link_edges) == 2
                or edge.calc_length() <= MIN_BRIDGE_MERGE_DISTANCE
                for vertex in edge.verts
            )
        }

    active_vertices = {
        vertex
        for vertex in source_vertices
        if vertex.is_valid
    }

    # 从仍存活的原侧链 Vertex 恢复清理后的 Boundary chain，禁止游走到另一侧或相邻 job。
    # active_vertices: 当前侧链清理后仍有效的 Vertex；返回唯一简单 chain。
    def refreshed_component():
        candidate_edges = {
            edge
            for vertex in active_vertices
            for edge in vertex.link_edges
            if edge.is_valid
            and bool(edge[boundary_layer])
            and all(edge_vertex in active_vertices for edge_vertex in edge.verts)
        }
        components = _edge_components(candidate_edges)
        if len(components) != 1:
            raise FeatureChamferDirectBridgeError(
                "bridge_cleanup_component_incomplete",
                "Bridge cleanup did not preserve one Boundary chain",
                {
                    "source_edge_count": len(source_component),
                    "candidate_edge_count": len(candidate_edges),
                    "component_count": len(components),
                },
            )
        refreshed = components[0]
        cyclic, endpoint_count = _component_shape(refreshed)
        if cyclic != source_cyclic or endpoint_count != source_endpoint_count:
            raise FeatureChamferDirectBridgeError(
                "bridge_cleanup_shape_changed",
                "Bridge cleanup changed open/cyclic chain topology",
                {
                    "source_shape": [source_cyclic, source_endpoint_count],
                    "cleaned_shape": [cyclic, endpoint_count],
                },
            )
        if protected_endpoints and (
            not protected_endpoints.issubset(active_vertices)
            or set(_component_endpoints(refreshed) or ()) != protected_endpoints
        ):
            raise FeatureChamferDirectBridgeError(
                "bridge_cleanup_endpoints_changed",
                "Bridge cleanup changed open chain endpoints",
            )
        return refreshed

    cleaned_component = refreshed_component()
    merged_vertex_count = source_vertex_count - len(active_vertices)
    dissolved_vertex_count = 0
    while True:
        ordered_vertices = _ordered_chain_vertices(cleaned_component)
        dissolve_candidate = None
        for vertex_index, vertex in enumerate(ordered_vertices):
            if vertex in protected_endpoints or len(vertex.link_edges) != 2:
                continue
            if source_cyclic:
                previous_vertex = ordered_vertices[vertex_index - 1]
                next_vertex = ordered_vertices[
                    (vertex_index + 1) % len(ordered_vertices)
                ]
            elif 0 < vertex_index < len(ordered_vertices) - 1:
                previous_vertex = ordered_vertices[vertex_index - 1]
                next_vertex = ordered_vertices[vertex_index + 1]
            else:
                continue
            previous_vector = previous_vertex.co - vertex.co
            next_vector = next_vertex.co - vertex.co
            if (
                previous_vector.length <= merge_distance
                or next_vector.length <= merge_distance
            ):
                continue
            cosine = max(
                -1.0,
                min(
                    1.0,
                    previous_vector.normalized().dot(next_vector.normalized()),
                ),
            )
            deviation = math.pi - math.acos(cosine)
            if deviation > MAX_BRIDGE_DISSOLVE_DEVIATION_RADIANS:
                continue
            chord = next_vertex.co - previous_vertex.co
            if chord.length <= merge_distance:
                continue
            line_distance = previous_vector.cross(chord).length / chord.length
            if line_distance > merge_distance:
                continue
            dissolve_candidate = vertex
            break
        if dissolve_candidate is None:
            break
        bmesh.ops.dissolve_verts(
            bm,
            verts=[dissolve_candidate],
            use_face_split=False,
            use_boundary_tear=False,
        )
        active_vertices.discard(dissolve_candidate)
        dissolved_vertex_count += 1
        cleaned_component = refreshed_component()

    zero_edge_count_after = sum(
        edge.calc_length() <= merge_distance
        for edge in cleaned_component
    )
    cleaned_coordinates = [
        vertex.co.copy()
        for vertex in _ordered_chain_vertices(cleaned_component)
    ]
    if len(cleaned_coordinates) != len(active_vertices):
        raise FeatureChamferDirectBridgeError(
            "bridge_cleanup_result_order_invalid",
            "Bridge cleanup could not order the complete cleaned chain",
        )
    cleaned_length = _polyline_length(cleaned_coordinates, source_cyclic)
    maximum_deviation = _polyline_maximum_deviation(
        source_coordinates,
        cleaned_coordinates,
        source_cyclic,
    )
    operation_count = merged_vertex_count + dissolved_vertex_count
    numeric_tolerance = max(1.0e-12, source_length * 1.0e-7)
    geometric_tolerance = (
        merge_distance * max(1, 2 * operation_count + 1)
        + numeric_tolerance
    )
    length_tolerance = (
        merge_distance * max(1, 4 * operation_count + 2)
        + numeric_tolerance
    )
    length_delta = abs(cleaned_length - source_length)
    if maximum_deviation > geometric_tolerance or length_delta > length_tolerance:
        raise FeatureChamferDirectBridgeError(
            "bridge_cleanup_geometry_changed",
            "Bridge cleanup changed the source chain geometry beyond tolerance",
            {
                "merge_distance": merge_distance,
                "geometric_tolerance": geometric_tolerance,
                "maximum_deviation": maximum_deviation,
                "length_delta": length_delta,
                "length_tolerance": length_tolerance,
            },
        )
    return cleaned_component, {
        "merge_distance": merge_distance,
        "radius_merge_distance": float(radius) * BRIDGE_MERGE_DISTANCE_FACTOR,
        "median_source_edge_length": median_edge_length,
        "median_edge_merge_cap": (
            median_edge_length * MAX_BRIDGE_MERGE_DISTANCE_TO_MEDIAN_EDGE_RATIO
        ),
        "source_edge_count": len(source_component),
        "cleaned_edge_count": len(cleaned_component),
        "source_vertex_count": source_vertex_count,
        "cleaned_vertex_count": len(active_vertices),
        "merged_vertex_count": merged_vertex_count,
        "dissolved_vertex_count": dissolved_vertex_count,
        "zero_edge_count_before": zero_edge_count_before,
        "zero_edge_count_after": zero_edge_count_after,
        "source_length": source_length,
        "cleaned_length": cleaned_length,
        "length_delta": length_delta,
        "length_tolerance": length_tolerance,
        "maximum_geometric_deviation": maximum_deviation,
        "geometric_tolerance": geometric_tolerance,
        "max_dissolve_deviation_degrees": math.degrees(
            MAX_BRIDGE_DISSOLVE_DEVIATION_RADIANS
        ),
    }


# 只焊接 Bridge 后新增区域附近的重合 Vertex，让 junction Fill 消费真实孔洞且不改变槽外 source。
# bm/chamfer_face_layer: 已完成全部 Bridge 的 BMesh 与新增 Face 标记；返回焊接前的新增零面积 Face 数。
def _weld_coincident_vertices(bm, chamfer_face_layer):
    zero_area_faces = [
        face
        for face in bm.faces
        if bool(face[chamfer_face_layer]) and face.calc_area() <= 1.0e-12
    ]
    if zero_area_faces:
        affected_vertices = {
            linked_vertex
            for face in zero_area_faces
            for vertex in face.verts
            for edge in vertex.link_edges
            for linked_vertex in edge.verts
        }
        bmesh.ops.remove_doubles(
            bm,
            verts=list(affected_vertices),
            dist=1.0e-8,
        )
    return len(zero_area_faces)


# 在最终检查前清除新增区域仍残留的零面积 Faces，并保持边界重新可检测。
# bm/chamfer_face_layer: Bridge/Fill 完成后的 BMesh 与新增 Face 标记；返回删除 Face 数量。
def _remove_zero_area_faces(bm, chamfer_face_layer):
    zero_area_faces = [
        face
        for face in bm.faces
        if bool(face[chamfer_face_layer]) and face.calc_area() <= 1.0e-12
    ]
    for face in zero_area_faces:
        if not face.is_valid:
            continue
        vertices = list(face.verts)
        if len(vertices) < 3:
            continue
        nearest_pair = min(
            (
                (first, second)
                for index, first in enumerate(vertices)
                for second in vertices[index + 1 :]
            ),
            key=lambda pair: (pair[0].co - pair[1].co).length,
        )
        bmesh.ops.pointmerge(
            bm,
            verts=list(nearest_pair),
            merge_co=(nearest_pair[0].co + nearest_pair[1].co) * 0.5,
        )
    return len(zero_area_faces)


# 清理新增零面积 Face 合并后形成的重复 Edge，恢复闭合曲面的二面共边合同。
# bm/chamfer_face_layer: 已完成零面积清理的 BMesh 与新增 Face 标记；返回重复 Edge 数。
def _weld_duplicate_edges(bm, chamfer_face_layer):
    edges_by_vertex_pair = {}
    for edge in bm.edges:
        vertex_pair = frozenset(edge.verts)
        edges_by_vertex_pair.setdefault(vertex_pair, []).append(edge)
    duplicate_edges = [
        edge
        for group in edges_by_vertex_pair.values()
        if len(group) > 1
        for edge in group[1:]
        if any(bool(face[chamfer_face_layer]) for face in edge.link_faces)
    ]
    if duplicate_edges:
        affected_vertices = {
            linked_vertex
            for edge in duplicate_edges
            for vertex in edge.verts
            for linked_edge in vertex.link_edges
            for linked_vertex in linked_edge.verts
        }
        bmesh.ops.remove_doubles(
            bm,
            verts=list(affected_vertices),
            dist=1.0e-8,
        )
    return len(duplicate_edges)


# 移除新增零面积 Face 清理后留下的局部孤立 Edge，不触碰槽外 source 几何。
# bm/chamfer_face_layer: 已完成退化 Face 合并的 BMesh 与新增 Face 标记；返回删除的孤立 Edge 数。
def _remove_wire_edges(bm, chamfer_face_layer):
    wire_edges = [
        edge
        for edge in bm.edges
        if len(edge.link_faces) == 0
        and any(
            any(bool(face[chamfer_face_layer]) for face in linked_edge.link_faces)
            for vertex in edge.verts
            for linked_edge in vertex.link_edges
            if linked_edge is not edge
        )
    ]
    if wire_edges:
        bmesh.ops.delete(
            bm,
            geom=wire_edges,
            context="EDGES",
        )
    return len(wire_edges)


# 清理补面区域内部的共面 Edge，减少 Bridge/Fill 产生的冗余布线。
# bm: 已完成 Bridge/Fill 的 BMesh；chamfer_face_layer: 标记补面 Faces 的整数层；返回实际减少的 Face 数量。
def _dissolve_chamfer_patch_edges(bm, chamfer_face_layer):
    dissolve_edges = [
        edge
        for edge in bm.edges
        if len(edge.link_faces) == 2
        and all(bool(face[chamfer_face_layer]) for face in edge.link_faces)
    ]
    if not dissolve_edges:
        return 0
    face_count_before = len(bm.faces)
    bmesh.ops.dissolve_limit(
        bm,
        angle_limit=MAX_BRIDGE_DISSOLVE_DEVIATION_RADIANS,
        use_dissolve_boundaries=False,
        verts=list({vertex for edge in dissolve_edges for vertex in edge.verts}),
        edges=dissolve_edges,
        delimit={"NORMAL"},
    )
    for face in bm.faces:
        if bool(face[chamfer_face_layer]):
            face[chamfer_face_layer] = 1
    return face_count_before - len(bm.faces)

# 返回最终拓扑异常 Edge 的最小诊断，区分孤立边、开放边和多面共边。
# bm: 已完成清理的 BMesh；返回最多 16 条异常 Edge 记录。
def _non_manifold_edge_records(bm):
    return [
        {
            "edge_index": edge.index,
            "face_count": len(edge.link_faces),
            "length": edge.calc_length(),
            "vertex_indices": [vertex.index for vertex in edge.verts],
            "coordinates": [
                [float(component) for component in vertex.co]
                for vertex in edge.verts
            ],
            "face_indices": [face.index for face in edge.link_faces],
        }
        for edge in bm.edges
        if len(edge.link_faces) != 2
    ][:16]


# 返回 Mesh 非邻接自交记录；可只统计与本次新 Faces 有关的 pair。
# bm/target_faces: 待检查 BMesh 与可选新面集合；返回稳定诊断列表。
def _self_intersection_records(bm, target_faces=None):
    target_layer_name = "hst_intersection_target"
    target_layer = bm.faces.layers.int.get(target_layer_name)
    if target_layer is None:
        target_layer = bm.faces.layers.int.new(target_layer_name)
    target_face_set = set(target_faces) if target_faces is not None else None
    for face in bm.faces:
        face[target_layer] = int(
            target_face_set is None or face in target_face_set
        )
    temporary_mesh = bpy.data.meshes.new("HST_FeatureChamfer_IntersectionCheck")
    bm.to_mesh(temporary_mesh)
    temporary_mesh.update()
    bm.faces.layers.int.remove(target_layer)
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
        triangulated_target_layer = triangulated.faces.layers.int.get(
            target_layer_name
        )
        tree = BVHTree.FromBMesh(triangulated, epsilon=1.0e-8)
        intersections = []
        for first_index, second_index in tree.overlap(tree):
            if first_index >= second_index:
                continue
            first = triangulated.faces[first_index]
            second = triangulated.faces[second_index]
            if set(first.verts) & set(second.verts):
                continue
            first_target = bool(first[triangulated_target_layer])
            second_target = bool(second[triangulated_target_layer])
            if target_face_set is not None and not (first_target or second_target):
                continue
            intersections.append(
                {
                    "first_face": first_index,
                    "second_face": second_index,
                    "first_target": first_target,
                    "second_target": second_target,
                    "first_center": [
                        float(value) for value in first.calc_center_median()
                    ],
                    "second_center": [
                        float(value) for value in second.calc_center_median()
                    ],
                }
            )
        return intersections
    finally:
        triangulated.free()
        bpy.data.meshes.remove(temporary_mesh)


# 检查最终 Mesh 的全部非邻接自交，防止仅靠 manifold 统计误报产品成功。
# bm: 最终 BMesh；返回非邻接相交 pair 数。
def _self_intersection_count(bm):
    return len(_self_intersection_records(bm))


# 把 Direct Bridge 中断瞬间的 BMesh 发布为结果，保留已执行步骤产生的真实坏拓扑。
# bm/source_object/output_object/output_mesh/error/source_fingerprint_before: 当前运行现场；返回结果与统计。
def _publish_interrupted_direct_bridge_bmesh(
    bm,
    source_object,
    output_object,
    output_mesh,
    error,
    source_fingerprint_before,
):
    chamfer_face_layer = bm.faces.layers.int.get(CHAMFER_FACE_ATTRIBUTE)
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    chamfer_face_indices = {
        face.index
        for face in bm.faces
        if chamfer_face_layer is not None and bool(face[chamfer_face_layer])
    }
    if output_object is None:
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
    error_stats = dict(error.stats)
    error_stats.update(
        status="finished",
        backend="DIRECT_EDGE_LOOP_BRIDGE",
        output_quality="PIPELINE_INTERRUPTED",
        interrupted_stage="DIRECT_BRIDGE",
        interrupted_error_code=error.error_code,
        interrupted_error_message=str(error),
        boundary_edge_count=sum(len(edge.link_faces) == 1 for edge in bm.edges),
        non_manifold_edge_count=sum(len(edge.link_faces) != 2 for edge in bm.edges),
        zero_area_face_count=sum(
            face.calc_area() <= 1.0e-12
            for face in bm.faces
        ),
        chamfer_face_count=len(chamfer_face_indices),
        output_object_name=output_object.name,
        source_fingerprint_unchanged=(
            source_fingerprint(source_object) == source_fingerprint_before
        ),
    )
    return error_stats


# 从正式 evaluated Preview 直接 Bridge 普通槽段，再 Fill 自然剩余的 junction 孔洞。
# source_object/expected_chamfer_plan/dissolve_chamfer: 正式 source、Preview immutable plan 与是否清理补面布线；返回 Operator 可记录的 stats。
def build_direct_edge_loop_chamfer(
    source_object,
    expected_chamfer_plan,
    dissolve_chamfer=True,
):
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
        chamfer_face_layer = bm.faces.layers.int.get(
            CHAMFER_FACE_ATTRIBUTE
        ) or bm.faces.layers.int.new(CHAMFER_FACE_ATTRIBUTE)
        for face in bm.faces:
            face[chamfer_face_layer] = 0
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
        claimed_source_edges = set()
        bridge_records = []
        deferred_segments = []
        chamfer_faces = set()
        bridge_faces_for_validation = set()
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
            owner_pairs = _segment_owner_surface_pairs(
                segment,
                expected_chamfer_plan,
            )
            owner_pair = None
            junction_fragments = set()
            bridge_jobs = None
            if len(components) == 2:
                owner_pair, side_chains, junction_fragments = _segment_side_chains(
                    components,
                    patch_layers,
                    owner_pairs,
                    segment_id,
                    segment_point_layers,
                    station_point_layers,
                    station_squared_point_layers,
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
                        segment_id,
                        segment_point_layers,
                        station_point_layers,
                        station_squared_point_layers,
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
                                    "cyclic": _component_shape(component)[0],
                                    "endpoint_count": _component_shape(component)[1],
                                    "patch_ids": [
                                        patch_id
                                        for patch_id, layer in patch_layers.items()
                                        if all(bool(edge[layer]) for edge in component)
                                    ],
                                }
                                for component in components
                            ],
                            "junction_fragment_edge_count": len(junction_fragments),
                        },
                    )
            has_patch_seam = (
                len(components) == 2
                and any(
                    any(bool(edge[layer]) for edge in component)
                    and not all(bool(edge[layer]) for edge in component)
                    for component in components
                    for layer in patch_layers.values()
                )
            )
            if has_patch_seam:
                seam_result = _seam_spanning_side_chains(
                    components,
                    patch_layers,
                    owner_pairs,
                )
                if seam_result is not None:
                    owner_pair, side_chains, seam_fragments = seam_result
                    junction_fragments.update(seam_fragments)
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
                elif has_patch_seam:
                    seam_result = _seam_spanning_side_chains(
                        components,
                        patch_layers,
                        owner_pairs,
                    )
                    if seam_result is not None:
                        owner_pair, side_chains, seam_fragments = seam_result
                        junction_fragments.update(seam_fragments)
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
                seam_result = _seam_spanning_side_chains(
                    components,
                    patch_layers,
                    owner_pairs,
                )
                if seam_result is not None:
                    owner_pair, side_chains, seam_fragments = seam_result
                    junction_fragments.update(seam_fragments)
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
                        "owner_pairs": [list(pair) for pair in owner_pairs],
                        "component_patches": [
                            {
                                "edge_count": len(component),
                                "cyclic": _component_shape(component)[0],
                                "endpoint_count": _component_shape(component)[1],
                                "patch_ids": [
                                    patch_id
                                    for patch_id, layer in patch_layers.items()
                                    if all(bool(edge[layer]) for edge in component)
                                ],
                                "patch_edge_counts": {
                                    str(patch_id): sum(
                                        bool(edge[layer])
                                        for edge in component
                                    )
                                    for patch_id, layer in patch_layers.items()
                                    if any(bool(edge[layer]) for edge in component)
                                },
                            }
                            for component in components
                        ],
                    },
                )
            bridge_jobs = bridge_jobs or [side_chains]
            expanded_bridge_jobs = []
            for parent_bridge_job_index, components in enumerate(bridge_jobs):
                cyclic_split = _split_cyclic_bridge_job(
                    components,
                    segment,
                    segment_layers,
                    segment_point_layers,
                    station_edge_layers,
                    station_squared_edge_layers,
                    station_point_layers,
                    station_squared_point_layers,
                )
                if cyclic_split is not None:
                    split_jobs, common_stations, source_side_edge_indices = cyclic_split
                    source_side_edge_sets = [set(component) for component in components]
                    expanded_bridge_jobs.extend(
                        {
                            "components": split_components,
                            "parent_bridge_job_index": parent_bridge_job_index,
                            "turn_split_job_index": 0,
                            "turn_split_job_count": 1,
                            "common_turns": [],
                            "cyclic_split_job_index": split_job_index,
                            "cyclic_split_job_count": len(split_jobs),
                            "common_cyclic_stations": common_stations,
                            "cyclic_source_side_edge_indices": source_side_edge_indices,
                            "cyclic_source_side_edge_sets": source_side_edge_sets,
                        }
                        for split_job_index, split_components in enumerate(split_jobs)
                    )
                    continue
                turn_split = _split_bridge_job_at_common_turns(
                    components,
                    segment,
                    segment_layers,
                    segment_point_layers,
                    station_edge_layers,
                    station_point_layers,
                    station_squared_point_layers,
                )
                if turn_split is None:
                    expanded_bridge_jobs.append(
                        {
                            "components": components,
                            "parent_bridge_job_index": parent_bridge_job_index,
                            "turn_split_job_index": 0,
                            "turn_split_job_count": 1,
                            "common_turns": [],
                            "cyclic_split_job_index": 0,
                            "cyclic_split_job_count": 1,
                            "common_cyclic_stations": [],
                            "cyclic_source_side_edge_indices": [],
                            "cyclic_source_side_edge_sets": [],
                        }
                    )
                    continue
                split_jobs, common_turns = turn_split
                expanded_bridge_jobs.extend(
                    {
                        "components": split_components,
                        "parent_bridge_job_index": parent_bridge_job_index,
                        "turn_split_job_index": split_job_index,
                        "turn_split_job_count": len(split_jobs),
                        "common_turns": common_turns,
                        "cyclic_split_job_index": 0,
                        "cyclic_split_job_count": 1,
                        "common_cyclic_stations": [],
                        "cyclic_source_side_edge_indices": [],
                        "cyclic_source_side_edge_sets": [],
                    }
                    for split_job_index, split_components in enumerate(split_jobs)
                )
            for bridge_job_index, bridge_job in enumerate(expanded_bridge_jobs):
                components = []
                bridge_cleanup_records = []
                for component in bridge_job["components"]:
                    source_edges = set(component)
                    if source_edges & claimed_source_edges:
                        raise FeatureChamferDirectBridgeError(
                            "segment_source_selection_overlap",
                            f"Segment {segment_id} reuses an earlier source Bridge edge",
                        )
                    source_edge_indices = sorted(edge.index for edge in source_edges)
                    claimed_source_edges.update(source_edges)
                    cleaned_component, cleanup_record = _clean_bridge_component(
                        bm,
                        component,
                        expected_chamfer_plan.radius,
                        boundary_layer,
                    )
                    cleanup_record["source_edge_indices"] = source_edge_indices
                    components.append(cleaned_component)
                    bridge_cleanup_records.append(cleanup_record)
                selected_edges = set().union(*components)
                shapes = [_component_shape(component) for component in components]
                invalid_input_shapes = [
                    [cyclic, endpoint_count]
                    for cyclic, endpoint_count in shapes
                    if endpoint_count not in {0, 2}
                ]
                if selected_edges & junction_fragments:
                    raise FeatureChamferDirectBridgeError(
                        "segment_junction_fragment_selected",
                        f"Segment {segment_id} Bridge includes a junction fragment",
                    )
                if bridge_job["common_cyclic_stations"]:
                    side_station_intervals = [
                        tuple(
                            sorted(
                                _cyclic_edge_station(
                                    edge,
                                    segment_id,
                                    segment_layers,
                                    station_edge_layers,
                                    station_squared_edge_layers,
                                )
                                for edge in component
                            )
                        )
                        for component in components
                    ]
                    side_station_intervals = [
                        (stations[0], stations[-1])
                        for stations in side_station_intervals
                    ]
                    interval_overlap_valid = True
                else:
                    side_station_intervals, interval_overlap_valid = (
                        _validate_bridge_job_station_interval(
                            components,
                            segment_id,
                            segment_layers,
                            station_edge_layers,
                        )
                    )
                side_junction_witnesses = [
                    _component_junction_witnesses(
                        component,
                        segment_id,
                        segment_layers,
                        segment_point_layers,
                        station_point_layers,
                        station_squared_point_layers,
                    )
                    for component in components
                ]
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
                foreign_existing_edges = {
                    edge
                    for face in bridge_faces
                    for edge in face.edges
                    if edge in edges_before_bridge and edge not in selected_edges
                    and any(
                        other_segment_id != segment_id
                        and float(edge[layer]) > 1.0e-6
                        for other_segment_id, layer in segment_layers.items()
                    )
                }
                if foreign_existing_edges:
                    raise FeatureChamferDirectBridgeError(
                        "bridge_crosses_other_segment",
                        f"Blender Bridge crosses another segment for segment {segment_id}",
                        {
                            "segment_id": segment_id,
                            "bridge_job_index": bridge_job_index,
                            "foreign_edge_indices": sorted(
                                edge.index for edge in foreign_existing_edges
                            ),
                        },
                    )
                claimed_edges.update(selected_edges)
                chamfer_faces.update(bridge_faces)
                bridge_faces_for_validation.update(bridge_faces)
                for face in bridge_faces:
                    face[chamfer_face_layer] = 1
                bridge_self_intersection_count = 0
                bridge_records.append(
                    {
                        "segment_id": segment_id,
                        "bridge_job_index": bridge_job_index,
                        "parent_bridge_job_index": bridge_job[
                            "parent_bridge_job_index"
                        ],
                        "common_turn_split_applied": bool(
                            bridge_job["common_turns"]
                        ),
                        "common_turns": bridge_job["common_turns"],
                        "turn_split_job_index": bridge_job[
                            "turn_split_job_index"
                        ],
                        "turn_split_job_count": bridge_job[
                            "turn_split_job_count"
                        ],
                        "cyclic_split_applied": bool(
                            bridge_job["common_cyclic_stations"]
                        ),
                        "cyclic_split_job_index": bridge_job[
                            "cyclic_split_job_index"
                        ],
                        "cyclic_split_job_count": bridge_job[
                            "cyclic_split_job_count"
                        ],
                        "common_cyclic_stations": bridge_job[
                            "common_cyclic_stations"
                        ],
                        "cyclic_source_side_edge_indices": bridge_job[
                            "cyclic_source_side_edge_indices"
                        ],
                        "cyclic_source_side_edge_counts": [
                            len(side_edges)
                            for side_edges in bridge_job[
                                "cyclic_source_side_edge_sets"
                            ]
                        ],
                        "cyclic_source_side_edge_identity_tokens": [
                            sorted(id(edge) for edge in side_edges)
                            for side_edges in bridge_job[
                                "cyclic_source_side_edge_sets"
                            ]
                        ],
                        "cyclic_job_side_edge_indices": [
                            record["source_edge_indices"]
                            for record in bridge_cleanup_records
                        ],
                        "cyclic_job_side_edge_identity_tokens": [
                            sorted(id(edge) for edge in component)
                            for component in bridge_job["components"]
                        ],
                        "cyclic_job_side_endpoint_vertex_indices": [
                            sorted(vertex.index for vertex in _component_endpoints(component))
                            if _component_endpoints(component) is not None
                            else []
                            for component in components
                        ],
                        "bridge_input_cleanup": bridge_cleanup_records,
                        "invalid_input_shapes": invalid_input_shapes,
                        "pipe_id": int(segment["pipe_id"]),
                        "port_indices": list(segment.get("port_indices", ())),
                        "source_edge_indices": list(
                            segment.get("source_edge_indices", ())
                        ),
                        "contract_owner_surface_pairs": [
                            list(pair) for pair in owner_pairs
                        ],
                        "owner_surface_pair": list(owner_pair) if owner_pair else None,
                        "side_edge_counts": sorted(len(component) for component in components),
                        "side_lengths": sorted(
                            sum(edge.calc_length() for edge in component)
                            for component in components
                        ),
                        "side_station_intervals": [
                            [float(value) for value in interval]
                            for interval in side_station_intervals
                        ],
                        "side_terminal_witness_counts": [
                            sum(
                                bool(witness["component_endpoint"])
                                for witness in witnesses
                            )
                            for witnesses in side_junction_witnesses
                        ],
                        "side_interior_witness_counts": [
                            sum(
                                not witness["component_endpoint"]
                                for witness in witnesses
                            )
                            for witnesses in side_junction_witnesses
                        ],
                        "station_interval_overlap_valid": interval_overlap_valid,
                        "foreign_existing_edge_count": 0,
                        "junction_fragment_edge_count": len(junction_fragments),
                        "face_count": len(bridge_faces),
                        "cumulative_self_intersection_count": bridge_self_intersection_count,
                        "created_self_intersection_count": bridge_self_intersection_count,
                        "native_operator": "Blender Bridge Edge Loops",
                    }
                )
        bridge_intersections = (
            _self_intersection_records(bm, bridge_faces_for_validation)
            if bridge_faces_for_validation
            else []
        )
        if bridge_intersections:
            raise FeatureChamferDirectBridgeError(
                "bridge_faces_self_intersect",
                "Blender Bridge output contains self-intersecting Faces",
                {
                    "self_intersection_count": len(bridge_intersections),
                    "self_intersections": bridge_intersections[:16],
                    "bridge_records": bridge_records,
                },
            )
        if deferred_segments:
            raise FeatureChamferDirectBridgeError(
                "unbridged_segment_remaining",
                "Direct Bridge left ordinary Pipe segments unconsumed",
                {"deferred_segments": deferred_segments},
            )

        zero_area_faces_welded_before_fill = _weld_coincident_vertices(
            bm,
            chamfer_face_layer,
        )
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
            chamfer_face_layer,
        )
        fill_intersections = (
            _self_intersection_records(bm, fill_faces)
            if fill_faces
            else []
        )
        if fill_intersections:
            raise FeatureChamferDirectBridgeError(
                "junction_fill_self_intersects",
                "Blender Fill output contains self-intersecting Faces",
                {
                    "self_intersection_count": len(fill_intersections),
                    "self_intersections": fill_intersections[:16],
                    "junction_fill_records": fill_records,
                },
            )
        chamfer_faces.update(fill_faces)
        dissolved_chamfer_face_count = (
            _dissolve_chamfer_patch_edges(bm, chamfer_face_layer)
            if dissolve_chamfer
            else 0
        )

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
        zero_area_faces_removed = _remove_zero_area_faces(
            bm,
            chamfer_face_layer,
        )
        duplicate_edges_welded = _weld_duplicate_edges(
            bm,
            chamfer_face_layer,
        )
        wire_edges_removed = _remove_wire_edges(bm, chamfer_face_layer)
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
        final_chamfer_faces = {
            face
            for face in bm.faces
            if bool(face[chamfer_face_layer])
        }
        final_intersections = _self_intersection_records(
            bm,
            final_chamfer_faces,
        )
        self_intersection_count = len(final_intersections)
        topology_issue_records = _non_manifold_edge_records(bm)
        output_quality = (
            "TOPOLOGY_ISSUES_PRESENT"
            if (
                remaining_boundary_count
                or non_manifold_count
                or zero_area_count
                or self_intersection_count
            )
            else "CLEAN"
        )

        bm.faces.index_update()
        chamfer_face_indices = {
            face.index
            for face in bm.faces
            if bool(face[chamfer_face_layer])
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
        if source_fingerprint(source_object) != source_fingerprint_before:
            raise FeatureChamferDirectBridgeError(
                "source_changed_during_finalize",
                "Finalize changed the source Mesh",
            )
        return {
            "status": "finished",
            "backend": "DIRECT_EDGE_LOOP_BRIDGE",
            "runtime_path": (
                "Fixed Boolean Boundary Edges -> segment groups -> "
                "Blender Bridge Edge Loops -> Blender Fill"
            ),
            "feature_graph_contract": "GN_PREVIEW_V1",
            "bridge_shape_contract": "SEGMENT_OWNER_INTERVAL_OVERLAP_V1",
            "plan_id": expected_chamfer_plan.plan_id,
            "source_fingerprint_unchanged": True,
            "output_quality": output_quality,
            "topology_issue_records": topology_issue_records,
            "self_intersection_records": final_intersections[:16],
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
            "zero_area_faces_removed": zero_area_faces_removed,
            "duplicate_edges_welded": duplicate_edges_welded,
            "wire_edges_removed": wire_edges_removed,
            "dissolve_chamfer_requested": bool(dissolve_chamfer),
            "dissolved_chamfer_face_count": dissolved_chamfer_face_count,
            "topology_before_zero_cleanup": topology_before_zero_cleanup,
            "regular_patch_face_count": sum(record["face_count"] for record in bridge_records),
            "junction_patch_face_count": sum(record["face_count"] for record in fill_records),
            "boundary_edge_count": remaining_boundary_count,
            "non_manifold_edge_count": non_manifold_count,
            "zero_area_face_count": zero_area_count,
            "self_intersection_count": self_intersection_count,
            "self_intersection_validation_strategy": "BATCHED_BRIDGE_FILL_FINAL",
            "self_intersection_validation_pass_count": (
                1
                + int(bool(bridge_faces_for_validation))
                + int(bool(fill_faces))
            ),
            "chamfer_face_count": len(chamfer_face_indices),
            "output_object_name": output_object.name,
        }
    except FeatureChamferDirectBridgeError as error:
        if bm is None:
            raise
        return _publish_interrupted_direct_bridge_bmesh(
            bm,
            source_object,
            output_object,
            output_mesh,
            error,
            source_fingerprint_before,
        )
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
