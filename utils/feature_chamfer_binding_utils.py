# -*- coding: utf-8 -*-
"""Feature Chamfer 最终 Boolean Boundary 的 immutable topology binding。"""

from __future__ import annotations

from dataclasses import dataclass

import bpy
import bmesh

from .feature_chamfer_plan_utils import _edge_key as plan_edge_key


@dataclass(frozen=True)
class BoundaryRailStrand:
    strand_id: str
    ordered_edge_indices: tuple[int, ...]
    ordered_vertex_indices: tuple[int, ...]
    cyclic: bool
    endpoint_junction_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryJunctionPort:
    port_id: str
    junction_id: str
    rail_strand_id: str
    boundary_vertex_index: int
    boundary_degree: int


@dataclass(frozen=True)
class BoundaryJunction:
    junction_id: str
    boundary_vertex_index: int
    boundary_degree: int
    port_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryGraphDecomposition:
    plan_id: str
    status: str
    boundary_edge_count: int
    consumed_edge_count: int
    missing_edge_indices: tuple[int, ...]
    duplicate_edge_indices: tuple[int, ...]
    rail_strands: tuple[BoundaryRailStrand, ...]
    junctions: tuple[BoundaryJunction, ...]
    ports: tuple[BoundaryJunctionPort, ...]
    coordinate_reconstruction: bool
    centerline_sorting: bool
    moves_boundary: bool


@dataclass(frozen=True)
class StrandEndpointPortToken:
    token: int
    pipe_id: int
    endpoint_role: str
    port_id: str


@dataclass(frozen=True)
class BooleanBoundaryEdgeBinding:
    boundary_edge_index: int
    pipe_id: int
    owner_strand_id: str
    source_patch_id: int
    rail_id: str


@dataclass(frozen=True)
class BooleanRailBinding:
    rail_id: str
    owner_strand_id: str
    source_patch_id: int
    boundary_edge_indices: tuple[int, ...]
    boundary_rail_strand_ids: tuple[str, ...]
    endpoint_port_ids: tuple[str, ...]


@dataclass(frozen=True)
class FinalizationBinding:
    plan_id: str
    status: str
    boundary_edge_count: int
    consumed_edge_count: int
    edge_bindings: tuple[BooleanBoundaryEdgeBinding, ...]
    rail_bindings: tuple[BooleanRailBinding, ...]
    unowned_edge_indices: tuple[int, ...]
    multi_owner_edge_indices: tuple[int, ...]
    missing_patch_edge_indices: tuple[int, ...]
    incompatible_edge_indices: tuple[int, ...]
    missing_rail_ids: tuple[str, ...]
    missing_port_ids: tuple[str, ...]
    topology_incompatible_rail_ids: tuple[str, ...]
    graph: BoundaryGraphDecomposition
    coordinate_reconstruction: bool
    centerline_sorting: bool
    moves_boundary: bool


# vertex/vertex_ids: Boundary BMVert 与当前输入的本地 identity 映射；返回 traversal 排序 key。
def _vertex_key(vertex, vertex_ids):
    return (
        tuple(round(float(component), 8) for component in vertex.co),
        vertex_ids[vertex],
    )


# edge/edge_ids/vertex_ids: Boundary BMEdge 与本地 Edge/Vertex identity；返回方向无关 traversal key。
def _edge_key(edge, edge_ids, vertex_ids):
    return (
        tuple(sorted(_vertex_key(vertex, vertex_ids) for vertex in edge.verts)),
        edge_ids[edge],
    )


# start/adjacency/degree_by_vertex/remaining/edge_ids/vertex_ids: run 起点、邻接、度数、原地消费集合与本地 identity；返回有序 Edge/Vertex。
def _trace_run(
    start,
    adjacency,
    degree_by_vertex,
    remaining,
    edge_ids,
    vertex_ids,
):
    ordered_edges = []
    ordered_vertices = [start]
    current = start
    previous_edge = None
    while True:
        next_edge = next(
            (
                edge
                for edge in sorted(
                    adjacency[current],
                    key=lambda item: _edge_key(item, edge_ids, vertex_ids),
                )
                if edge in remaining and edge is not previous_edge
            ),
            None,
        )
        if next_edge is None:
            break
        remaining.remove(next_edge)
        ordered_edges.append(next_edge)
        following = next_edge.other_vert(current)
        previous_edge = next_edge
        current = following
        if current is start:
            break
        ordered_vertices.append(current)
        if degree_by_vertex[current] != 2:
            break
    return ordered_edges, ordered_vertices, current


# plan_id/boundary_edges: shared plan ID 与按调用侧顺序排列的原始 Boundary BMEdge refs；返回 immutable topology decomposition。
def bind_boundary_graph(plan_id, boundary_edges):
    boundary_edges = tuple(boundary_edges)
    unique_boundary_edges = tuple(dict.fromkeys(boundary_edges))
    boundary_edge_ids = {
        edge: index for index, edge in enumerate(unique_boundary_edges)
    }
    duplicate_input_indices = tuple(
        index
        for index, edge in enumerate(boundary_edges)
        if boundary_edges.index(edge) != index
    )
    boundary_vertices = tuple(
        dict.fromkeys(
            vertex
            for edge in unique_boundary_edges
            for vertex in edge.verts
        )
    )
    local_vertex_ids = {
        vertex: index for index, vertex in enumerate(boundary_vertices)
    }
    boundary_vertex_ids = {
        vertex: index
        for index, vertex in enumerate(
            sorted(
                boundary_vertices,
                key=lambda item: _vertex_key(item, local_vertex_ids),
            )
        )
    }
    adjacency = {}
    for edge in unique_boundary_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    degree_by_vertex = {
        vertex: len(edges)
        for vertex, edges in adjacency.items()
    }
    junction_vertices = {
        vertex for vertex, degree in degree_by_vertex.items() if degree != 2
    }
    junction_id_by_vertex = {
        vertex: f"boundary-junction:{boundary_vertex_ids[vertex]}"
        for vertex in junction_vertices
    }
    remaining = set(unique_boundary_edges)
    traced_runs = []
    for start in sorted(
        junction_vertices,
        key=lambda item: _vertex_key(item, local_vertex_ids),
    ):
        for edge in sorted(
            adjacency[start],
            key=lambda item: _edge_key(
                item,
                boundary_edge_ids,
                local_vertex_ids,
            ),
        ):
            if edge not in remaining:
                continue
            edges, vertices, end_vertex = _trace_run(
                start,
                adjacency,
                degree_by_vertex,
                remaining,
                boundary_edge_ids,
                local_vertex_ids,
            )
            traced_runs.append((edges, vertices, False, (start, end_vertex)))
    while remaining:
        seed = min(
            remaining,
            key=lambda item: _edge_key(
                item,
                boundary_edge_ids,
                local_vertex_ids,
            ),
        )
        start = min(
            seed.verts,
            key=lambda item: _vertex_key(item, local_vertex_ids),
        )
        edges, vertices, end_vertex = _trace_run(
            start,
            adjacency,
            degree_by_vertex,
            remaining,
            boundary_edge_ids,
            local_vertex_ids,
        )
        traced_runs.append((edges, vertices, end_vertex is start, ()))

    rail_strands = []
    ports = []
    port_ids_by_junction = {
        junction_id: [] for junction_id in junction_id_by_vertex.values()
    }
    for edges, vertices, cyclic, endpoint_vertices in traced_runs:
        rail_id = "boundary-rail:" + "-".join(
            str(boundary_edge_ids[edge]) for edge in edges
        )
        endpoint_vertices = tuple(
            vertex
            for vertex in endpoint_vertices
            if vertex in junction_id_by_vertex
        )
        endpoint_junction_ids = tuple(
            junction_id_by_vertex[vertex] for vertex in endpoint_vertices
        )
        rail_strands.append(
            BoundaryRailStrand(
                strand_id=rail_id,
                ordered_edge_indices=tuple(boundary_edge_ids[edge] for edge in edges),
                ordered_vertex_indices=tuple(
                    boundary_vertex_ids[vertex] for vertex in vertices
                ),
                cyclic=cyclic,
                endpoint_junction_ids=endpoint_junction_ids,
            )
        )
        for endpoint_index, vertex in enumerate(endpoint_vertices):
            junction_id = junction_id_by_vertex[vertex]
            port_id = f"port:{junction_id}:{rail_id}:{endpoint_index}"
            ports.append(
                BoundaryJunctionPort(
                    port_id=port_id,
                    junction_id=junction_id,
                    rail_strand_id=rail_id,
                    boundary_vertex_index=boundary_vertex_ids[vertex],
                    boundary_degree=degree_by_vertex[vertex],
                )
            )
            port_ids_by_junction[junction_id].append(port_id)
    junctions = tuple(
        BoundaryJunction(
            junction_id=junction_id,
            boundary_vertex_index=boundary_vertex_ids[vertex],
            boundary_degree=degree_by_vertex[vertex],
            port_ids=tuple(sorted(port_ids_by_junction[junction_id])),
        )
        for vertex, junction_id in sorted(
            junction_id_by_vertex.items(),
            key=lambda item: item[1],
        )
    )
    consumptions = [
        edge_index
        for strand in rail_strands
        for edge_index in strand.ordered_edge_indices
    ]
    boundary_indices = set(boundary_edge_ids.values())
    consumed_indices = set(consumptions)
    duplicate_indices = tuple(sorted({
        *duplicate_input_indices,
        *(
            edge_index
            for edge_index in consumed_indices
            if consumptions.count(edge_index) != 1
        ),
    }))
    missing_indices = tuple(sorted(boundary_indices - consumed_indices))
    status = (
        "PASS"
        if boundary_indices and not missing_indices and not duplicate_indices
        else "FAIL"
    )
    return BoundaryGraphDecomposition(
        plan_id=plan_id,
        status=status,
        boundary_edge_count=len(boundary_edges),
        consumed_edge_count=len(boundary_indices & consumed_indices),
        missing_edge_indices=missing_indices,
        duplicate_edge_indices=duplicate_indices,
        rail_strands=tuple(rail_strands),
        junctions=junctions,
        ports=tuple(ports),
        coordinate_reconstruction=False,
        centerline_sorting=False,
        moves_boundary=False,
    )


# plan/groups/source_mesh: shared plan、Feature groups 与 source Mesh；返回 Pipe ID 到 FeatureStrand 的显式映射。
def _plan_strands_by_pipe_id(plan, groups, source_mesh):
    strands_by_edge_keys = {}
    for strand in plan.feature_strands:
        key = frozenset(strand.ordered_edge_keys)
        if key in strands_by_edge_keys:
            return {}
        strands_by_edge_keys[key] = strand
    mapping = {}
    for group in groups:
        pipe_id = int(group["pipe_id"])
        if pipe_id in mapping:
            return {}
        edge_keys = frozenset(
            plan_edge_key(source_mesh, edge_index)
            for edge_index in group["edge_indices"]
        )
        strand = strands_by_edge_keys.get(edge_keys)
        if strand is None:
            return {}
        mapping[pipe_id] = strand
    if set(mapping.values()) != set(plan.feature_strands):
        return {}
    return mapping


# plan/groups/bm/groove_faces: shared plan、Feature groups、caller-owned disposable Boolean BMesh 与待删除 cutter Faces；函数会原地删除 groove Faces并返回 binding。
# component_layer_name/source_patch_layer_name: groove Face 的 Pipe owner layer 与保留 source Face 的 Patch layer 名称。
# endpoint_port_tokens/endpoint_token_layer_names: plan-local StrandEndpointPort token registry 与 groove Face token layers。
def bind_boolean_boundary(
    plan,
    groups,
    bm,
    groove_faces,
    *,
    component_layer_name,
    source_patch_layer_name,
    source_mesh,
    endpoint_port_tokens=(),
    endpoint_token_layer_names=(),
):
    groove_faces = tuple(groove_faces)
    component_layer = bm.faces.layers.int.get(component_layer_name)
    source_patch_layer = bm.faces.layers.int.get(source_patch_layer_name)
    component_present_layer = bm.faces.layers.int.get(
        f"{component_layer_name}_present"
    )
    source_patch_present_layer = bm.faces.layers.int.get(
        f"{source_patch_layer_name}_present"
    )
    strands_by_pipe_id = _plan_strands_by_pipe_id(plan, groups, source_mesh)
    endpoint_port_tokens = tuple(endpoint_port_tokens)
    valid_endpoint_roles = {"START", "END"}
    endpoint_tokens_by_value = {
        record.token: record for record in endpoint_port_tokens
    }
    endpoint_registry_valid = (
        len(endpoint_tokens_by_value) == len(endpoint_port_tokens)
        and all(
            record.token > 0
            and record.endpoint_role in valid_endpoint_roles
            and record.pipe_id in strands_by_pipe_id
            and record.port_id
            in {
                strands_by_pipe_id[record.pipe_id].start_port_id,
                strands_by_pipe_id[record.pipe_id].end_port_id,
            }
            and (
                record.port_id
                == strands_by_pipe_id[record.pipe_id].start_port_id
            )
            == (record.endpoint_role == "START")
            for record in endpoint_port_tokens
        )
    )
    endpoint_token_layers = tuple(
        layer
        for layer in (
            bm.faces.layers.int.get(layer_name)
            for layer_name in endpoint_token_layer_names
        )
        if layer is not None
    )
    edge_owner_ledger = {}
    vertex_endpoint_token_ledger = {}
    observed_endpoint_tokens = set()
    for face in groove_faces:
        owner = (
            int(face[component_layer])
            if component_layer is not None
            and component_present_layer is not None
            and bool(face[component_present_layer])
            else -1
        )
        for edge in face.edges:
            edge_owner_ledger.setdefault(edge, set()).add(owner)
        for layer in endpoint_token_layers:
            token = int(face[layer])
            if token <= 0:
                continue
            observed_endpoint_tokens.add(token)
            for vertex in face.verts:
                vertex_endpoint_token_ledger.setdefault(vertex, set()).add(token)
    bmesh.ops.delete(
        bm,
        geom=list(groove_faces),
        context="FACES_KEEP_BOUNDARY",
    )
    boundary_edges = tuple(edge for edge in bm.edges if len(edge.link_faces) == 1)
    boundary_edge_ids = {
        edge: index for index, edge in enumerate(boundary_edges)
    }
    graph = bind_boundary_graph(plan.plan_id, boundary_edges)
    expected_rail_by_id = {
        rail.rail_id: rail for rail in plan.rail_chains
    }
    edge_bindings = []
    unowned = []
    multi_owner = []
    missing_patch = []
    incompatible = []
    for edge in boundary_edges:
        edge_index = boundary_edge_ids[edge]
        ledger_owners = edge_owner_ledger.get(edge, set())
        if any(owner < 0 for owner in ledger_owners):
            unowned.append(edge_index)
            continue
        owners = {
            owner
            for owner in ledger_owners
            if owner >= 0
        }
        if not owners:
            unowned.append(edge_index)
            continue
        if len(owners) != 1:
            multi_owner.append(edge_index)
            continue
        retained_faces = tuple(edge.link_faces)
        if (
            source_patch_layer is None
            or source_patch_present_layer is None
            or len(retained_faces) != 1
            or not bool(retained_faces[0][source_patch_present_layer])
        ):
            missing_patch.append(edge_index)
            continue
        patch_id = int(retained_faces[0][source_patch_layer])
        if patch_id < 0:
            missing_patch.append(edge_index)
            continue
        pipe_id = next(iter(owners))
        strand = strands_by_pipe_id.get(pipe_id)
        rail_id = (
            f"rail:{strand.strand_id}:patch:{patch_id}"
            if strand is not None
            else ""
        )
        if (
            strand is None
            or patch_id
            not in {
                owner_patch
                for pair in strand.owner_surface_pairs
                for owner_patch in pair
            }
            or rail_id not in expected_rail_by_id
        ):
            incompatible.append(edge_index)
            continue
        edge_bindings.append(
            BooleanBoundaryEdgeBinding(
                boundary_edge_index=edge_index,
                pipe_id=pipe_id,
                owner_strand_id=strand.strand_id,
                source_patch_id=patch_id,
                rail_id=rail_id,
            )
        )
    bindings_by_rail = {}
    for record in edge_bindings:
        bindings_by_rail.setdefault(record.rail_id, []).append(record)
    edge_objects_by_index = dict(enumerate(boundary_edges))
    topology_incompatible_rail_ids = []
    rail_bindings = []
    for rail_id, records in sorted(bindings_by_rail.items()):
        rail_edge_objects = tuple(
            edge_objects_by_index[index]
            for index in sorted(
                record.boundary_edge_index for record in records
            )
        )
        rail_graph = bind_boundary_graph(plan.plan_id, rail_edge_objects)
        graph_rails = rail_graph.rail_strands
        owner_strand = next(
            strand
            for strand in plan.feature_strands
            if strand.strand_id == records[0].owner_strand_id
        )
        if owner_strand.cyclic and expected_rail_by_id[rail_id].endpoint_port_ids:
            topology_incompatible_rail_ids.append(rail_id)
        record_edge_indices = {
            record.boundary_edge_index for record in records
        }
        graph_edge_indices = set(range(len(rail_edge_objects)))
        topology_compatible = (
            len(graph_rails) == 1
            and len(record_edge_indices) == len(graph_edge_indices)
        )
        expected_endpoint_port_ids = expected_rail_by_id[rail_id].endpoint_port_ids
        actual_endpoint_port_ids = set()
        endpoint_roles = set()
        rail_tokens_valid = True
        rail_vertices = {
            vertex
            for edge in rail_edge_objects
            for vertex in edge.verts
        }
        for vertex in rail_vertices:
            for token in vertex_endpoint_token_ledger.get(vertex, set()):
                endpoint = endpoint_tokens_by_value.get(token)
                if endpoint is None or endpoint.pipe_id != records[0].pipe_id:
                    rail_tokens_valid = False
                    continue
                actual_endpoint_port_ids.add(endpoint.port_id)
                endpoint_roles.add(endpoint.endpoint_role)
        if owner_strand.cyclic:
            topology_compatible = (
                topology_compatible
                and graph_rails[0].cyclic
                and not expected_endpoint_port_ids
            )
        else:
            topology_compatible = (
                topology_compatible
                and set(expected_endpoint_port_ids) == actual_endpoint_port_ids
                and endpoint_roles == {"START", "END"}
                and rail_tokens_valid
            )
        if not topology_compatible and rail_id not in topology_incompatible_rail_ids:
            topology_incompatible_rail_ids.append(rail_id)
        rail_bindings.append(BooleanRailBinding(
            rail_id=rail_id,
            owner_strand_id=records[0].owner_strand_id,
            source_patch_id=records[0].source_patch_id,
            boundary_edge_indices=(
                tuple(
                    sorted(record_edge_indices)[local_index]
                    for local_index in graph_rails[0].ordered_edge_indices
                )
                if len(graph_rails) == 1
                else tuple(record.boundary_edge_index for record in records)
            ),
            boundary_rail_strand_ids=tuple(
                graph_rail.strand_id for graph_rail in graph_rails
            ),
            endpoint_port_ids=expected_rail_by_id[rail_id].endpoint_port_ids,
        ))
    rail_bindings = tuple(rail_bindings)
    bound_rail_ids = set(bindings_by_rail)
    expected_rail_ids = set(expected_rail_by_id)
    missing_rail_ids = tuple(sorted(expected_rail_ids - bound_rail_ids))
    bound_port_ids = {
        port_id
        for rail in rail_bindings
        for port_id in rail.endpoint_port_ids
    }
    expected_port_ids = {port.port_id for port in plan.junction_ports}
    missing_port_ids = tuple(sorted(expected_port_ids - bound_port_ids))
    complete = (
        graph.status == "PASS"
        and len(edge_bindings) == len(boundary_edges)
        and not unowned
        and not multi_owner
        and not missing_patch
        and not incompatible
        and not missing_rail_ids
        and not missing_port_ids
        and not topology_incompatible_rail_ids
        and endpoint_registry_valid
        and observed_endpoint_tokens <= set(endpoint_tokens_by_value)
    )
    return FinalizationBinding(
        plan_id=plan.plan_id,
        status="PASS" if complete else "boundary_binding_incomplete",
        boundary_edge_count=len(boundary_edges),
        consumed_edge_count=len(edge_bindings),
        edge_bindings=tuple(edge_bindings),
        rail_bindings=rail_bindings,
        unowned_edge_indices=tuple(unowned),
        multi_owner_edge_indices=tuple(multi_owner),
        missing_patch_edge_indices=tuple(missing_patch),
        incompatible_edge_indices=tuple(incompatible),
        missing_rail_ids=missing_rail_ids,
        missing_port_ids=missing_port_ids,
        topology_incompatible_rail_ids=tuple(topology_incompatible_rail_ids),
        graph=graph,
        coordinate_reconstruction=False,
        centerline_sorting=False,
        moves_boundary=False,
    )
