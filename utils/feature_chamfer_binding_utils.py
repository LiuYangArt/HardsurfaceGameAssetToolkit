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
    strand_id: str
    endpoint_role: str
    port_id: str


@dataclass(frozen=True)
class BoundaryWitness:
    witness_id: str
    owner_rail_ids: tuple[str, ...]
    junction_port_id: str | None
    source_patch_id: int
    expected_consumption_count: int = 1


@dataclass(frozen=True)
class BoundaryWitnessAssignment:
    boundary_edge_index: int
    witness: BoundaryWitness


@dataclass(frozen=True)
class BoundaryWitnessValidation:
    status: str
    consumed_edge_count: int
    missing_edge_indices: tuple[int, ...]
    duplicate_edge_indices: tuple[int, ...]
    conflicting_edge_indices: tuple[int, ...]
    duplicate_witness_ids: tuple[str, ...]
    unknown_witness_ids: tuple[str, ...]
    unknown_rail_ids: tuple[str, ...]
    unknown_port_ids: tuple[str, ...]
    unknown_patch_ids: tuple[int, ...]
    incompatible_witness_ids: tuple[str, ...]
    assignments: tuple[BoundaryWitnessAssignment, ...]


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
class BoundaryEdgeBindingDiagnostic:
    boundary_edge_index: int
    vertex_indices: tuple[int, ...]
    linked_face_indices: tuple[int, ...]
    direct_owner_pipe_ids: tuple[int, ...]
    owner_witness_pipe_ids: tuple[int, ...]
    unknown_owner_present: bool
    vertex_owner_pipe_ids: tuple[tuple[int, tuple[int, ...]], ...]
    adjacent_owner_pipe_ids: tuple[int, ...]
    candidate_owner_pipe_ids: tuple[int, ...]
    candidate_owner_strand_ids: tuple[str, ...]
    endpoint_tokens: tuple[int, ...]
    endpoint_token_records: tuple[StrandEndpointPortToken, ...]
    compatible_port_ids: tuple[str, ...]
    retained_patch_ids: tuple[int, ...]
    patch_witness_ids: tuple[int, ...]
    rejection_reason: str


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
    conflicting_provenance_edge_indices: tuple[int, ...]
    edge_diagnostics: tuple[BoundaryEdgeBindingDiagnostic, ...]
    graph: BoundaryGraphDecomposition
    coordinate_reconstruction: bool
    centerline_sorting: bool
    moves_boundary: bool


# plan: ChamferPlan；返回 Rail、Port、Strand 与 Patch 的 plan-local 索引。
def _boundary_witness_plan_indices(plan):
    rails_by_id = {rail.rail_id: rail for rail in plan.rail_chains}
    ports_by_id = {port.port_id: port for port in plan.junction_ports}
    strands_by_id = {
        strand.strand_id: strand for strand in plan.feature_strands
    }
    known_patch_ids = {
        patch_id
        for strand in plan.feature_strands
        for owner_pair in strand.owner_surface_pairs
        for patch_id in owner_pair
    }
    return rails_by_id, ports_by_id, strands_by_id, known_patch_ids


# witness/plan_indices: 单条 BoundaryWitness 与 ChamferPlan 索引；返回未知引用与语义不相容证据。
def _boundary_witness_semantic_evidence(witness, plan_indices):
    rails_by_id, ports_by_id, strands_by_id, known_patch_ids = plan_indices
    unknown_rail_ids = set(witness.owner_rail_ids) - set(rails_by_id)
    unknown_port_ids = (
        {witness.junction_port_id} - set(ports_by_id)
        if witness.junction_port_id is not None
        else set()
    )
    unknown_patch_ids = (
        {witness.source_patch_id}
        if witness.source_patch_id not in known_patch_ids
        else set()
    )
    incompatible = (
        not witness.witness_id
        or not witness.owner_rail_ids
        or len(witness.owner_rail_ids) != len(set(witness.owner_rail_ids))
        or not isinstance(witness.expected_consumption_count, int)
        or isinstance(witness.expected_consumption_count, bool)
        or witness.expected_consumption_count <= 0
    )
    known_rails = tuple(
        rails_by_id[rail_id]
        for rail_id in witness.owner_rail_ids
        if rail_id in rails_by_id
    )
    expected_side = f"OWNER_PATCH:{witness.source_patch_id}"
    if any(
        rail.side != expected_side
        or rail.owner_strand_id not in strands_by_id
        for rail in known_rails
    ):
        incompatible = True
    if len(witness.owner_rail_ids) > 1 and witness.junction_port_id is None:
        incompatible = True
    port = ports_by_id.get(witness.junction_port_id)
    if port is not None and any(
        rail.owner_strand_id not in port.incident_strand_ids
        or port.port_id not in rail.endpoint_port_ids
        for rail in known_rails
    ):
        incompatible = True
    return (
        unknown_rail_ids,
        unknown_port_ids,
        unknown_patch_ids,
        incompatible,
    )


# plan/boundary_edge_count/witness_registry/witness_ids_by_edge: plan-local witness 合同与每条 Boundary Edge 的 producer witness IDs；返回 exactly-once 验证。
def validate_boundary_witnesses(
    plan,
    boundary_edge_count,
    witness_registry,
    witness_ids_by_edge,
):
    witness_registry = tuple(witness_registry)
    witness_ids_by_edge = tuple(tuple(ids) for ids in witness_ids_by_edge)
    witness_counts = {}
    for witness in witness_registry:
        witness_counts[witness.witness_id] = (
            witness_counts.get(witness.witness_id, 0) + 1
        )
    duplicate_witness_ids = {
        witness_id for witness_id, count in witness_counts.items() if count != 1
    }
    witness_by_id = {
        witness.witness_id: witness
        for witness in witness_registry
        if witness.witness_id not in duplicate_witness_ids
    }
    plan_indices = _boundary_witness_plan_indices(plan)
    missing_edge_indices = []
    duplicate_edge_indices = []
    conflicting_edge_indices = []
    unknown_witness_ids = set()
    unknown_rail_ids = set()
    unknown_port_ids = set()
    unknown_patch_ids = set()
    incompatible_witness_ids = set()
    invalid_witness_ids = set()
    assignments = []
    consumption_counts = {}
    referenced_witness_ids = {
        witness_id
        for witness_ids in witness_ids_by_edge[:int(boundary_edge_count)]
        for witness_id in witness_ids
    }
    for witness_id, witness in witness_by_id.items():
        (
            invalid_rails,
            invalid_ports,
            invalid_patches,
            incompatible,
        ) = _boundary_witness_semantic_evidence(witness, plan_indices)
        unknown_rail_ids.update(invalid_rails)
        unknown_port_ids.update(invalid_ports)
        unknown_patch_ids.update(invalid_patches)
        if invalid_rails or invalid_ports or invalid_patches:
            invalid_witness_ids.add(witness_id)
        if incompatible:
            incompatible_witness_ids.add(witness_id)
    for edge_index in range(int(boundary_edge_count)):
        witness_ids = (
            witness_ids_by_edge[edge_index]
            if edge_index < len(witness_ids_by_edge)
            else ()
        )
        if not witness_ids:
            missing_edge_indices.append(edge_index)
            continue
        if len(witness_ids) != len(set(witness_ids)):
            duplicate_edge_indices.append(edge_index)
            continue
        resolved = []
        for witness_id in witness_ids:
            witness = witness_by_id.get(witness_id)
            if witness_id in duplicate_witness_ids:
                continue
            if witness is None:
                unknown_witness_ids.add(witness_id)
                continue
            if (
                witness_id in incompatible_witness_ids
                or witness_id in invalid_witness_ids
            ):
                continue
            resolved.append(witness)
        if len(resolved) != 1 or len(witness_ids) != 1:
            conflicting_edge_indices.append(edge_index)
            continue
        witness = resolved[0]
        assignments.append(BoundaryWitnessAssignment(edge_index, witness))
        consumption_counts[witness.witness_id] = (
            consumption_counts.get(witness.witness_id, 0) + 1
        )
    for witness_id, witness in witness_by_id.items():
        if (
            witness_id in referenced_witness_ids
            and witness_id not in incompatible_witness_ids
            and consumption_counts.get(witness_id, 0)
            != witness.expected_consumption_count
        ):
            incompatible_witness_ids.add(witness_id)
            conflicting_edge_indices.extend(
                assignment.boundary_edge_index
                for assignment in assignments
                if assignment.witness.witness_id == witness_id
            )
    conflicting_edge_indices = set(conflicting_edge_indices)
    valid_assignments = tuple(
        assignment
        for assignment in assignments
        if assignment.boundary_edge_index not in conflicting_edge_indices
        and assignment.witness.witness_id not in incompatible_witness_ids
    )
    status = (
        "PASS"
        if len(valid_assignments) == boundary_edge_count
        and not missing_edge_indices
        and not duplicate_edge_indices
        and not conflicting_edge_indices
        and not duplicate_witness_ids
        and not unknown_witness_ids
        and not unknown_rail_ids
        and not unknown_port_ids
        and not unknown_patch_ids
        and not incompatible_witness_ids
        else "boundary_witness_incomplete"
    )
    return BoundaryWitnessValidation(
        status=status,
        consumed_edge_count=(
            boundary_edge_count if status == "PASS" else len(valid_assignments)
        ),
        missing_edge_indices=tuple(sorted(set(missing_edge_indices))),
        duplicate_edge_indices=tuple(sorted(set(duplicate_edge_indices))),
        conflicting_edge_indices=tuple(sorted(conflicting_edge_indices)),
        duplicate_witness_ids=tuple(sorted(duplicate_witness_ids)),
        unknown_witness_ids=tuple(sorted(unknown_witness_ids)),
        unknown_rail_ids=tuple(sorted(unknown_rail_ids)),
        unknown_port_ids=tuple(sorted(unknown_port_ids)),
        unknown_patch_ids=tuple(sorted(unknown_patch_ids)),
        incompatible_witness_ids=tuple(sorted(incompatible_witness_ids)),
        assignments=valid_assignments,
    )


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
# component_membership_layer_names/endpoint_membership_layer_names/source_patch_membership_layer_names: Collection Boolean 可合并的 one-hot owner/token/Patch provenance layers。
# boundary_owner_witness_layer_names/boundary_patch_witness_layer_names: Boolean 后显式写入的 EDGE owner/Patch witness layers。
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
    component_membership_layer_names=(),
    endpoint_membership_layer_names=(),
    source_patch_membership_layer_names=(),
    boundary_owner_witness_layer_names=(),
    boundary_patch_witness_layer_names=(),
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
            and record.strand_id == strands_by_pipe_id[record.pipe_id].strand_id
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
    component_membership_layers = tuple(
        (pipe_id, layer)
        for pipe_id, layer in (
            (
                int(layer_name.rsplit("_", 1)[1]),
                bm.faces.layers.int.get(layer_name)
                or bm.faces.layers.bool.get(layer_name),
            )
            for layer_name in component_membership_layer_names
        )
        if layer is not None
    )
    endpoint_membership_layers = tuple(
        (token, layer)
        for token, layer in (
            (
                int(layer_name.rsplit("_", 1)[1]),
                bm.faces.layers.int.get(layer_name)
                or bm.faces.layers.bool.get(layer_name),
            )
            for layer_name in endpoint_membership_layer_names
        )
        if layer is not None
    )
    source_patch_membership_layers = tuple(
        (patch_id, layer)
        for patch_id, layer in (
            (
                int(layer_name.rsplit("_", 1)[1]),
                bm.faces.layers.int.get(layer_name)
                or bm.faces.layers.bool.get(layer_name),
            )
            for layer_name in source_patch_membership_layer_names
        )
        if layer is not None
    )
    boundary_owner_witness_layers = tuple(
        (pipe_id, layer)
        for pipe_id, layer in (
            (
                int(layer_name.rsplit("_", 1)[1]),
                bm.edges.layers.int.get(layer_name)
                or bm.edges.layers.bool.get(layer_name),
            )
            for layer_name in boundary_owner_witness_layer_names
        )
        if layer is not None
    )
    boundary_patch_witness_layers = tuple(
        (patch_id, layer)
        for patch_id, layer in (
            (
                int(layer_name.rsplit("_", 1)[1]),
                bm.edges.layers.int.get(layer_name)
                or bm.edges.layers.bool.get(layer_name),
            )
            for layer_name in boundary_patch_witness_layer_names
        )
        if layer is not None
    )
    edge_owner_ledger = {}
    vertex_owner_ledger = {}
    vertex_endpoint_token_ledger = {}
    observed_endpoint_tokens = set()
    for face in groove_faces:
        owners = {
            pipe_id
            for pipe_id, layer in component_membership_layers
            if bool(face[layer])
        }
        if not owners and component_membership_layers:
            legacy_owner = (
                int(face[component_layer])
                if component_layer is not None
                and component_present_layer is not None
                and bool(face[component_present_layer])
                else -1
            )
            owners = {legacy_owner}
        elif not component_membership_layers:
            owners = {
                int(face[component_layer])
                if component_layer is not None
                and component_present_layer is not None
                and bool(face[component_present_layer])
                else -1
            }
        for edge in face.edges:
            edge_owner_ledger.setdefault(edge, set()).update(owners)
        for vertex in face.verts:
            vertex_owner_ledger.setdefault(vertex, set()).update(owners)
        for layer in endpoint_token_layers:
            token = int(face[layer])
            if token <= 0:
                continue
            observed_endpoint_tokens.add(token)
            for vertex in face.verts:
                vertex_endpoint_token_ledger.setdefault(vertex, set()).add(token)
        for token, layer in endpoint_membership_layers:
            if not bool(face[layer]):
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
    plan_ports_by_id = {
        port.port_id: port for port in plan.junction_ports
    }
    edge_bindings = []
    unowned = []
    multi_owner = []
    missing_patch = []
    incompatible = []
    edge_diagnostics = []
    for edge in boundary_edges:
        edge_index = boundary_edge_ids[edge]
        ledger_owners = edge_owner_ledger.get(edge, set())
        direct_owners = {
            owner
            for owner in ledger_owners
            if owner >= 0
        }
        witness_owners = {
            pipe_id
            for pipe_id, layer in boundary_owner_witness_layers
            if bool(edge[layer])
        }
        owners = set(direct_owners)
        if not direct_owners and len(witness_owners) == 1:
            owners = set(witness_owners)
        unknown_owner_present = any(owner < 0 for owner in ledger_owners)
        vertex_owner_pipe_ids = tuple(
            (
                vertex.index,
                tuple(sorted(
                    owner
                    for owner in vertex_owner_ledger.get(vertex, set())
                    if owner >= 0
                )),
            )
            for vertex in sorted(edge.verts, key=lambda item: item.index)
        )
        vertex_owners = {
            owner
            for _, owner_ids in vertex_owner_pipe_ids
            for owner in owner_ids
        }
        endpoint_tokens = {
            token
            for vertex in edge.verts
            for token in vertex_endpoint_token_ledger.get(vertex, set())
        }
        token_records = tuple(
            endpoint_tokens_by_value[token]
            for token in sorted(endpoint_tokens)
            if token in endpoint_tokens_by_value
        )
        adjacent_owner_pipe_ids = {
            owner
            for vertex in edge.verts
            for adjacent_edge in vertex.link_edges
            if adjacent_edge is not edge
            for owner in edge_owner_ledger.get(adjacent_edge, set())
            if owner >= 0
        }
        candidate_owner_pipe_ids = vertex_owners | adjacent_owner_pipe_ids
        candidate_owner_strand_ids = {
            strands_by_pipe_id[pipe_id].strand_id
            for pipe_id in candidate_owner_pipe_ids
            if pipe_id in strands_by_pipe_id
        }
        compatible_port_ids = {
            port_id
            for port_id, port in plan_ports_by_id.items()
            if len(candidate_owner_strand_ids) >= 2
            and candidate_owner_strand_ids <= set(port.incident_strand_ids)
        }
        retained_faces = tuple(edge.link_faces)
        if source_patch_membership_layers:
            direct_retained_patch_ids = {
                patch_id
                for patch_id, layer in source_patch_membership_layers
                if len(retained_faces) == 1 and bool(retained_faces[0][layer])
            }
        elif (
            source_patch_layer is not None
            and source_patch_present_layer is not None
            and len(retained_faces) == 1
            and bool(retained_faces[0][source_patch_present_layer])
        ):
            direct_retained_patch_ids = {
                int(retained_faces[0][source_patch_layer])
            }
        else:
            direct_retained_patch_ids = set()
        retained_patch_ids = set(direct_retained_patch_ids)
        witnessed_patch_ids = {
            patch_id
            for patch_id, layer in boundary_patch_witness_layers
            if bool(edge[layer])
        }
        if not retained_patch_ids and len(witnessed_patch_ids) == 1:
            retained_patch_ids = set(witnessed_patch_ids)
        diagnostic_values = {
            "boundary_edge_index": edge_index,
            "vertex_indices": tuple(sorted(vertex.index for vertex in edge.verts)),
            "linked_face_indices": tuple(
                sorted(face.index for face in retained_faces)
            ),
            "direct_owner_pipe_ids": tuple(sorted(direct_owners)),
            "owner_witness_pipe_ids": tuple(sorted(witness_owners)),
            "unknown_owner_present": unknown_owner_present,
            "vertex_owner_pipe_ids": vertex_owner_pipe_ids,
            "adjacent_owner_pipe_ids": tuple(sorted(adjacent_owner_pipe_ids)),
            "candidate_owner_pipe_ids": tuple(sorted(candidate_owner_pipe_ids)),
            "candidate_owner_strand_ids": tuple(sorted(candidate_owner_strand_ids)),
            "endpoint_tokens": tuple(sorted(endpoint_tokens)),
            "endpoint_token_records": token_records,
            "compatible_port_ids": tuple(sorted(compatible_port_ids)),
            "retained_patch_ids": tuple(sorted(retained_patch_ids)),
            "patch_witness_ids": tuple(sorted(witnessed_patch_ids)),
        }
        if unknown_owner_present:
            unowned.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="unknown_owner_present",
            ))
            continue
        if direct_owners and witness_owners and direct_owners != witness_owners:
            multi_owner.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="direct_owner_witness_conflict",
            ))
            continue
        if len(witness_owners) > 1:
            multi_owner.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="conflicting_owner_witnesses",
            ))
            continue
        if (
            direct_retained_patch_ids
            and witnessed_patch_ids
            and direct_retained_patch_ids != witnessed_patch_ids
        ):
            missing_patch.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="direct_patch_witness_conflict",
            ))
            continue
        if len(witnessed_patch_ids) > 1:
            missing_patch.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="conflicting_patch_witnesses",
            ))
            continue
        if not owners:
            unowned.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="no_direct_owner",
            ))
            continue
        if len(owners) != 1:
            multi_owner.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="multiple_direct_owners",
            ))
            continue
        patch_id = (
            next(iter(retained_patch_ids))
            if len(retained_patch_ids) == 1
            else -1
        )
        if patch_id < 0:
            missing_patch.append(edge_index)
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="missing_source_patch",
            ))
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
            edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
                **diagnostic_values,
                rejection_reason="incompatible_plan_owner",
            ))
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
        edge_diagnostics.append(BoundaryEdgeBindingDiagnostic(
            **diagnostic_values,
            rejection_reason="",
        ))
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
                if (
                    endpoint is None
                    or endpoint.pipe_id != records[0].pipe_id
                    or endpoint.strand_id != records[0].owner_strand_id
                ):
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
    conflicting_provenance_edge_indices = tuple(sorted(set(multi_owner)))
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
        conflicting_provenance_edge_indices=conflicting_provenance_edge_indices,
        edge_diagnostics=tuple(edge_diagnostics),
        graph=graph,
        coordinate_reconstruction=False,
        centerline_sorting=False,
        moves_boundary=False,
    )
