# -*- coding: utf-8 -*-
"""显式 Boundary region 驱动的 Feature Chamfer Patch Module。"""

import bpy
import bmesh
from mathutils import Vector
from mathutils import geometry


# 把 degree-2/degree-1 Boundary Edges 拆成有序 open/cyclic chains。
# edges: 同一 Boundary component 的 Edges；返回 chain records。
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
        endpoints = [vertex for vertex, linked in adjacency.items() if len(linked) == 1]
        cyclic = not endpoints and all(len(linked) == 2 for linked in adjacency.values())
        if not cyclic and len(endpoints) != 2:
            continue
        start = min(endpoints or adjacency.keys(), key=lambda vertex: vertex.index)
        ordered_edges = []
        ordered_vertices = [start]
        current = start
        previous = None
        while len(ordered_edges) < len(component):
            next_edge = next(
                (
                    edge for edge in sorted(adjacency[current], key=lambda item: item.index)
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
            chains.append({"edges": ordered_edges, "vertices": ordered_vertices, "is_cyclic": cyclic})
    return chains


# 验证两条 rail chains 是互不相交的有效 Boundary。
# chain_a/chain_b: 待配对 chains。
def _rail_pair_is_valid(chain_a, chain_b):
    return (
        not set(chain_a["edges"]) & set(chain_b["edges"])
        and not set(chain_a["vertices"]) & set(chain_b["vertices"])
        and all(len(edge.link_faces) == 1 for edge in chain_a["edges"] + chain_b["edges"])
    )


# 返回 closed loop 的 normalized arc-length 参数。
# loop: 有序 BMVert 序列。
def _normalized_loop_parameters(loop):
    lengths = [(loop[(index + 1) % len(loop)].co - vertex.co).length for index, vertex in enumerate(loop)]
    total = sum(lengths)
    cumulative = 0.0
    parameters = []
    for length in lengths:
        parameters.append(cumulative / total if total > 1.0e-10 else 0.0)
        cumulative += length
    return parameters


# 对齐 loop B 的方向与 cyclic offset。
# loop_a/loop_b: 待配对 closed loops。
def _align_loops(loop_a, loop_b):
    parameters_a = _normalized_loop_parameters(loop_a)
    best = None
    for candidate in (list(loop_b), list(reversed(loop_b))):
        for offset in range(len(candidate)):
            rotated = candidate[offset:] + candidate[:offset]
            parameters_b = _normalized_loop_parameters(rotated)
            cost = sum(
                (
                    loop_a[index_a].co
                    - rotated[min(range(len(rotated)), key=lambda index: abs(parameters_b[index] - parameter))].co
                ).length_squared
                for index_a, parameter in enumerate(parameters_a)
            )
            if best is None or cost < best[0]:
                best = (cost, rotated)
    return best[1]


# 以 normalized arc-length zipper bridge 两个 closed rails。
# bm/loop_a/loop_b: 目标 BMesh 与 rails；返回新 Faces。
def _zipper_bridge(bm, loop_a, loop_b):
    loop_b = _align_loops(loop_a, loop_b)
    parameters_a = _normalized_loop_parameters(loop_a) + [1.0]
    parameters_b = _normalized_loop_parameters(loop_b) + [1.0]
    index_a = index_b = 0
    faces = []
    while index_a < len(loop_a) or index_b < len(loop_b):
        current_a = loop_a[index_a % len(loop_a)]
        current_b = loop_b[index_b % len(loop_b)]
        next_a = parameters_a[index_a + 1]
        next_b = parameters_b[index_b + 1]
        if abs(next_a - next_b) <= 1.0e-9:
            vertices = (current_a, loop_a[(index_a + 1) % len(loop_a)], loop_b[(index_b + 1) % len(loop_b)], current_b)
            index_a += 1
            index_b += 1
        elif next_a < next_b:
            vertices = (current_a, loop_a[(index_a + 1) % len(loop_a)], current_b)
            index_a += 1
        else:
            vertices = (current_a, loop_b[(index_b + 1) % len(loop_b)], current_b)
            index_b += 1
        face = bm.faces.new(vertices)
        if face.calc_area() <= 1.0e-12:
            raise ValueError("Regular Strip produced a zero-area Face")
        faces.append(face)
    return faces


# 用 constrained Delaunay triangulation 填充单个 cyclic boundary。
# bm/loop: 目标 BMesh 与 Boundary loop。
def _triangulate_loop(bm, loop):
    center = sum((vertex.co for vertex in loop), Vector()) / len(loop)
    normal = Vector()
    for index, vertex in enumerate(loop):
        normal += (vertex.co - center).cross(loop[(index + 1) % len(loop)].co - center)
    if normal.length <= 1.0e-8:
        raise ValueError("Boundary has no stable best-fit plane")
    normal.normalize()
    axis_x = (loop[0].co - center).normalized()
    axis_y = normal.cross(axis_x).normalized()
    points = [Vector(((vertex.co - center).dot(axis_x), (vertex.co - center).dot(axis_y))) for vertex in loop]
    constraints = [(index, (index + 1) % len(loop)) for index in range(len(loop))]
    _, _, triangles, _, _, _ = geometry.delaunay_2d_cdt(points, constraints, [list(range(len(loop)))], 1, 1.0e-7, True)
    faces = []
    for triangle in triangles:
        if len(triangle) != 3 or any(index >= len(loop) for index in triangle):
            raise ValueError("Constrained triangulation inserted unsupported interior vertices")
        face = bm.faces.new(tuple(loop[index] for index in triangle))
        if face.calc_area() <= 1.0e-12:
            raise ValueError("Boundary Patch produced a zero-area Face")
        faces.append(face)
    return faces


class FeatureChamferPatchError(RuntimeError):
    """携带稳定 error code 与 Patch 统计的错误。"""

    def __init__(self, error_code, message, diagnostics=None):
        super().__init__(message)
        self.error_code = error_code
        self.diagnostics = dict(diagnostics or {})
        self.diagnostics.update(
            status="failed",
            error_code=error_code,
            error_message=message,
        )


# 从当前 BMesh 按原 Boundary component 的 Vertex indices 还原合法 edge chain。
# bm/vertex_indices: open Boolean BMesh 与 component 的 Vertex indices。
def _component_chain(bm, vertex_indices):
    vertices = {bm.verts[index] for index in vertex_indices}
    edges = {
        edge
        for vertex in vertices
        for edge in vertex.link_edges
        if len(edge.link_faces) == 1 and all(endpoint in vertices for endpoint in edge.verts)
    }
    chains = _ordered_edge_chains(edges)
    if len(chains) != 1:
        raise FeatureChamferPatchError(
            "boundary_component_invalid",
            f"Boundary component resolved to {len(chains)} chains",
        )
    return chains[0]


# 用 boundary centroid fan 填充强非平面 END_CAP/JUNCTION loop。
# bm/vertices: Patch BMesh 与有序 cyclic Boundary vertices；返回新 Faces。
def _centroid_fan_fill(bm, vertices):
    center = sum((vertex.co for vertex in vertices), vertices[0].co.copy() * 0.0) / len(vertices)
    center_vertex = bm.verts.new(center)
    faces = []
    for index, vertex in enumerate(vertices):
        next_vertex = vertices[(index + 1) % len(vertices)]
        face = bm.faces.new((vertex, next_vertex, center_vertex))
        if face.calc_area() <= 1.0e-12:
            raise FeatureChamferPatchError(
                "filler_zero_area",
                "Centroid fan produced a zero-area Face",
            )
        faces.append(face)
    return faces


# 拒绝把 tracked Boolean groove surface 当成 Chamfer；保留旧函数名作为统一 complex seam。
# donor_mesh/groove_face_indices/regions: 旧 Phase 2B donor 与复杂 Boundary regions。
def _preserve_tracked_boolean_surface(donor_mesh, groove_face_indices, regions):
    del donor_mesh, groove_face_indices
    raise FeatureChamferPatchError(
        "structured_junction_not_implemented",
        "END_CAP/JUNCTION requires structured rails, setback ports, and a Vertex Mesh solver",
        {
            "unsupported_region_count": len(regions),
            "unsupported_region_classes": sorted(
                {region["class"] for region in regions}
            ),
            "strategy": "FAIL_CLOSED",
        },
    )

# 使用统一入口生成 Patch；GN 路径消费显式 regions，旧 Operator 通过 legacy_context Adapter 保持行为。
# open_mesh/regions/components: Phase 2B 输出；donor_mesh/groove_face_indices: 复杂 region 的安全曲面 donor。
# legacy_context: 旧 Operator 的兼容 Patch 上下文。
def patch_boolean_result(
    open_mesh=None,
    regions=None,
    components=None,
    donor_mesh=None,
    groove_face_indices=None,
    legacy_context=None,
):
    if legacy_context is not None:
        return legacy_context["patch_callable"](
            legacy_context["bm"],
            legacy_context["loops"],
            legacy_context["groups"],
            legacy_context["pipe_trees"],
            legacy_context["pipe_bounds"],
            legacy_context["source_object"],
            legacy_context["radius"],
            legacy_context["junction_count"],
            legacy_context["stats"],
            legacy_context["debug_stage"],
            legacy_context.get("boolean_rail_pairs"),
            legacy_context.get("boolean_rail_summary"),
            legacy_context.get("boundary_rail_topology"),
        )
    if open_mesh is None or regions is None or components is None:
        raise FeatureChamferPatchError(
            "patch_context_missing",
            "Patch requires explicit Boundary regions or a legacy Adapter context",
        )
    complex_regions = [
        region for region in regions
        if region["class"] in {"END_CAP", "JUNCTION"}
    ]
    if complex_regions:
        return _preserve_tracked_boolean_surface(
            donor_mesh,
            groove_face_indices,
            complex_regions,
        )
    patched_mesh = open_mesh.copy()
    bm = bmesh.new()
    bm.from_mesh(patched_mesh)
    bm.verts.ensure_lookup_table()
    stats = {
        "regular_region_count": 0,
        "cyclic_region_count": 0,
        "end_cap_region_count": 0,
        "junction_region_count": 0,
        "patch_face_count": 0,
    }
    created_faces = []
    try:
        component_chains = {
            index: _component_chain(bm, component["vertex_indices"])
            for index, component in enumerate(components)
        }
        unresolved_regular = []
        filler_regions = []
        for region in regions:
            region_class = region["class"]
            chains = [component_chains[index] for index in region["component_indices"]]
            if region_class in {"REGULAR_TWO_RAIL", "CYCLIC_TWO_RAIL"}:
                if len(chains) == 2 and _rail_pair_is_valid(chains[0], chains[1]):
                    faces = _zipper_bridge(
                        bm,
                        chains[0]["vertices"],
                        chains[1]["vertices"],
                    )
                    created_faces.extend(faces)
                    if region_class == "CYCLIC_TWO_RAIL":
                        stats["cyclic_region_count"] += 1
                    else:
                        stats["regular_region_count"] += 1
                elif len(chains) == 1:
                    unresolved_regular.append(region)
                else:
                    raise FeatureChamferPatchError(
                        "regular_region_invalid",
                        f"{region_class} requires one paired component or two rail chains",
                        stats,
                    )
            elif region_class in {"END_CAP", "JUNCTION"}:
                filler_regions.append(region)
            else:
                raise FeatureChamferPatchError(
                    "ambiguous_region",
                    "Patch received an AMBIGUOUS Boundary region",
                    stats,
                )

        # Phase 2B 可能把两侧 rails 作为独立 cyclic components 输出；按同一 group owner 配对。
        by_group = {}
        for region in unresolved_regular:
            if len(region["group_ids"]) == 1:
                by_group.setdefault(region["group_ids"][0], []).append(region)
            else:
                filler_regions.append(region)
        for group_id, owned_regions in by_group.items():
            if len(owned_regions) == 1:
                region = owned_regions[0]
                chain = component_chains[region["component_indices"][0]]
                if not chain["is_cyclic"]:
                    raise FeatureChamferPatchError(
                        "regular_rail_ownership_incomplete",
                        f"Group {group_id} single regular region is not a cyclic terminal boundary",
                        stats,
                    )
                created_faces.extend(_triangulate_loop(bm, chain["vertices"]))
                stats["regular_region_count"] += 1
                continue
            if len(owned_regions) != 2:
                raise FeatureChamferPatchError(
                    "regular_rail_ownership_incomplete",
                    f"Group {group_id} has {len(owned_regions)} regular rail regions; expected 2",
                    stats,
                )
            chain_a = component_chains[owned_regions[0]["component_indices"][0]]
            chain_b = component_chains[owned_regions[1]["component_indices"][0]]
            if not _rail_pair_is_valid(chain_a, chain_b):
                raise FeatureChamferPatchError(
                    "regular_rail_pair_invalid",
                    f"Group {group_id} rail pair is invalid",
                    stats,
                )
            created_faces.extend(_zipper_bridge(bm, chain_a["vertices"], chain_b["vertices"]))
            if all(region["class"] == "CYCLIC_TWO_RAIL" for region in owned_regions):
                stats["cyclic_region_count"] += 1
            else:
                stats["regular_region_count"] += 1

        # END_CAP/JUNCTION 只接受 simple cyclic hole；复杂 shared-port region 继续 fail-closed。
        for region in filler_regions:
            for component_index in region["component_indices"]:
                chain = component_chains[component_index]
                if not chain["is_cyclic"]:
                    raise FeatureChamferPatchError(
                        "filler_region_open_chain",
                        f"{region['class']} Boundary is not cyclic",
                        stats,
                    )
                faces_before = set(bm.faces)
                verts_before = set(bm.verts)
                try:
                    faces = _triangulate_loop(bm, chain["vertices"])
                except (ValueError, RuntimeError) as error:
                    partial_faces = [face for face in bm.faces if face not in faces_before]
                    if partial_faces:
                        bmesh.ops.delete(bm, geom=partial_faces, context="FACES_ONLY")
                    partial_vertices = [
                        vertex
                        for vertex in bm.verts
                        if vertex not in verts_before and not vertex.link_faces
                    ]
                    if partial_vertices:
                        bmesh.ops.delete(bm, geom=partial_vertices, context="VERTS")
                    try:
                        faces = _centroid_fan_fill(bm, chain["vertices"])
                    except FeatureChamferPatchError as fallback_error:
                        raise FeatureChamferPatchError(
                            "filler_triangulation_failed",
                            f"{region['class']} filler failed: {error}; {fallback_error}",
                            stats,
                        ) from fallback_error
                created_faces.extend(faces)
            if region["class"] == "END_CAP":
                stats["end_cap_region_count"] += 1
            else:
                stats["junction_region_count"] += 1

        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        duplicate_faces = []
        faces_by_vertices = {}
        for face in bm.faces:
            key = frozenset(vertex.index for vertex in face.verts)
            if key in faces_by_vertices:
                duplicate_faces.append(face)
            else:
                faces_by_vertices[key] = face
        if duplicate_faces:
            bmesh.ops.delete(bm, geom=duplicate_faces, context="FACES_ONLY")
        loose_edges_to_remove = [edge for edge in bm.edges if not edge.link_faces]
        loose_vertices_to_remove = [vertex for vertex in bm.verts if not vertex.link_edges]
        if loose_edges_to_remove:
            bmesh.ops.delete(bm, geom=loose_edges_to_remove, context="EDGES")
        if loose_vertices_to_remove:
            bmesh.ops.delete(bm, geom=loose_vertices_to_remove, context="VERTS")
        remaining_boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
        non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
        over_connected = sum(1 for edge in bm.edges if len(edge.link_faces) > 2)
        loose_edges = sum(1 for edge in bm.edges if not edge.link_faces)
        zero_area = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)
        stats.update(
            patch_face_count=len(created_faces),
            boundary_after=remaining_boundary,
            non_manifold_after=non_manifold,
            over_connected_after=over_connected,
            loose_edges_after=loose_edges,
            zero_area_after=zero_area,
            duplicate_faces_removed=len(duplicate_faces),
            loose_edges_removed=len(loose_edges_to_remove),
            loose_vertices_removed=len(loose_vertices_to_remove),
        )
        if remaining_boundary or non_manifold or zero_area:
            raise FeatureChamferPatchError(
                "patched_mesh_invalid",
                "Patch result is not closed manifold",
                stats,
            )
        bm.to_mesh(patched_mesh)
    except Exception:
        bm.free()
        if bpy.data.meshes.get(patched_mesh.name) == patched_mesh:
            bpy.data.meshes.remove(patched_mesh)
        raise
    bm.free()
    stats["status"] = "finished"
    return patched_mesh, stats
