# -*- coding: utf-8 -*-
"""Feature Chamfer 最终 Boolean Boundary 的 immutable topology binding。"""

from __future__ import annotations

from dataclasses import dataclass

import bpy


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
