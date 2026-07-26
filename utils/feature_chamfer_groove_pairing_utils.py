# -*- coding: utf-8 -*-
"""Feature Chamfer 删除 Groove Faces 前的纯拓扑 Boundary pairing 合同。"""

import bpy

from collections import defaultdict
import hashlib
import json


GROOVE_PAIRING_CONTRACT = "HST_PHASE_C_PRE_DELETE_GROOVE_FACE_GRAPH_PAIRING_V1"


class GroovePairingError(RuntimeError):
    """Groove FaceGraph 无法给出唯一 pairing 时的 fail-closed 错误。"""

    # code/message/details: 稳定错误码、可读说明与调用方可序列化的诊断信息。
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# payload: 只包含 semantic provenance 与 Face/Edge/Vertex incidence 的嵌套数据；返回稳定 SHA-256。
def _topology_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


# value: 调用方提供的稳定 identity；返回可排序且保留类型差异的规范值。
def _canonical_identity(value):
    if isinstance(value, dict):
        return (
            "dict",
            tuple(
                sorted(
                    (
                        _canonical_identity(key),
                        _canonical_identity(item),
                    )
                    for key, item in value.items()
                )
            ),
        )
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_canonical_identity(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted(_canonical_identity(item) for item in value)))
    return (type(value).__name__, repr(value))


# edge/edge_identity: BMEdge-like 对象与调用方稳定 Edge identity 回调；返回非空规范 identity。
def _edge_key(edge, edge_identity):
    identity = edge_identity(edge)
    if identity is None:
        raise GroovePairingError(
            "missing_edge_identity",
            "Boundary Edge 缺少稳定 identity",
        )
    return _canonical_identity(identity)


# face/face_identity: BMFace-like 对象与调用方稳定 Face identity 回调；返回非空规范 identity。
def _face_key(face, face_identity):
    identity = face_identity(face)
    if identity is None:
        raise GroovePairingError(
            "missing_face_identity",
            "Groove Face 缺少稳定 identity",
        )
    return _canonical_identity(identity)


# bm/groove_faces/face_semantic_identity: closed-manifold Boolean BMesh、Groove Faces 与 pre-Boolean semantic identity；返回不读取坐标和临时 index 的稳定 Face/Boundary Edge identities。
def build_topology_only_pairing_identities(
    bm,
    groove_faces,
    face_semantic_identity,
):
    groove_set = set(groove_faces)
    if not groove_set:
        raise GroovePairingError("missing_groove_faces", "Groove Face 集合为空")
    groove_edges = {
        edge for face in groove_set for edge in face.edges
    }
    invalid_groove_edges = {
        edge for edge in groove_edges if len(edge.link_faces) != 2
    }
    if invalid_groove_edges:
        raise GroovePairingError(
            "non_manifold_boolean_output",
            "Boolean 的 Groove FaceGraph 不是 closed manifold",
            {
                "invalid_groove_edge_count": len(invalid_groove_edges),
                "groove_edge_count": len(groove_edges),
            },
        )
    semantic_by_face = {}
    for face in bm.faces:
        semantic = face_semantic_identity(face)
        if semantic is None:
            raise GroovePairingError(
                "missing_face_semantic_identity",
                "Boolean Face 缺少 source/cutter semantic identity",
            )
        semantic_by_face[face] = _canonical_identity(semantic)

    face_labels = {
        face: _topology_fingerprint(
            {
                "semantic": semantic_by_face[face],
                "role": "GROOVE" if face in groove_set else "SOURCE",
                "edge_count": len(face.edges),
            }
        )
        for face in bm.faces
    }
    vertex_labels = {
        vertex: _topology_fingerprint(
            {
                "edge_degree": len(vertex.link_edges),
                "face_degree": len(vertex.link_faces),
                "face_semantics": sorted(
                    semantic_by_face[face] for face in vertex.link_faces
                ),
            }
        )
        for vertex in bm.verts
    }
    for _ in range(min(len(bm.faces) + len(bm.verts), 64)):
        refined_faces = {
            face: _topology_fingerprint(
                {
                    "self": face_labels[face],
                    "edge_incidence": sorted(
                        (
                            {
                                "vertex_labels": sorted(
                                    vertex_labels[vertex]
                                    for vertex in edge.verts
                                ),
                                "neighbor_face_labels": sorted(
                                    face_labels[linked_face]
                                    for linked_face in edge.link_faces
                                    if linked_face is not face
                                ),
                            }
                            for edge in face.edges
                        ),
                        key=_topology_fingerprint,
                    ),
                }
            )
            for face in bm.faces
        }
        refined_vertices = {
            vertex: _topology_fingerprint(
                {
                    "self": vertex_labels[vertex],
                    "incident_edges": sorted(
                        (
                            {
                                "other_vertex": vertex_labels[
                                    edge.other_vert(vertex)
                                ],
                                "face_labels": sorted(
                                    face_labels[face]
                                    for face in edge.link_faces
                                ),
                            }
                            for edge in vertex.link_edges
                        ),
                        key=_topology_fingerprint,
                    ),
                }
            )
            for vertex in bm.verts
        }
        if refined_faces == face_labels and refined_vertices == vertex_labels:
            break
        face_labels = refined_faces
        vertex_labels = refined_vertices

    face_counts = defaultdict(int)
    for label in face_labels.values():
        face_counts[label] += 1
    duplicate_groove_labels = {
        label
        for face, label in face_labels.items()
        if face in groove_set and face_counts[label] != 1
    }
    if duplicate_groove_labels:
        raise GroovePairingError(
            "ambiguous_topology_face_identity",
            "Groove Face 拓扑 identity 不唯一",
            {"ambiguous_label_count": len(duplicate_groove_labels)},
        )

    boundary_edges = {
        edge
        for edge in bm.edges
        if len(groove_set.intersection(edge.link_faces)) == 1
    }
    edge_labels = {
        edge: _topology_fingerprint(
            {
                "endpoint_labels": sorted(
                    vertex_labels[vertex] for vertex in edge.verts
                ),
                "linked_face_labels": sorted(
                    face_labels[face] for face in edge.link_faces
                ),
                "linked_face_semantics": sorted(
                    semantic_by_face[face] for face in edge.link_faces
                ),
            }
        )
        for edge in boundary_edges
    }
    edge_counts = defaultdict(int)
    for label in edge_labels.values():
        edge_counts[label] += 1
    duplicate_edge_labels = {
        label for label in edge_labels.values() if edge_counts[label] != 1
    }
    if duplicate_edge_labels:
        raise GroovePairingError(
            "ambiguous_topology_edge_identity",
            "Groove/source 公共 Edge 拓扑 identity 不唯一",
            {"ambiguous_label_count": len(duplicate_edge_labels)},
        )
    return {
        "face_identity": lambda face: face_labels.get(face),
        "edge_identity": lambda edge: edge_labels.get(edge),
        "boundary_edge_count": len(boundary_edges),
        "refinement_contract": "SEMANTIC_INCIDENCE_ONLY_V1",
    }


# edges: Boundary Edge 集合；按共享 BMVert incidence 返回唯一 maximal open chain，拒绝 branch 与 cycle。
def _maximal_open_chains(edges):
    edge_set = set(edges)
    vertex_edges = defaultdict(set)
    for edge in edge_set:
        for vertex in edge.verts:
            vertex_edges[vertex].add(edge)
    branch_vertices = [vertex for vertex, linked in vertex_edges.items() if len(linked) > 2]
    if branch_vertices:
        raise GroovePairingError(
            "boundary_branch",
            "Boundary Edge 在共享 Vertex incidence 上出现分支",
            {"branch_vertex_count": len(branch_vertices)},
        )
    chains = []
    remaining = set(edge_set)
    while remaining:
        component = set()
        queue = [next(iter(remaining))]
        while queue:
            edge = queue.pop()
            if edge in component:
                continue
            component.add(edge)
            queue.extend(
                linked_edge
                for vertex in edge.verts
                for linked_edge in vertex_edges[vertex]
                if linked_edge not in component
            )
        endpoints = [
            vertex
            for vertex in {vertex for edge in component for vertex in edge.verts}
            if len(vertex_edges[vertex] & component) == 1
        ]
        if not endpoints:
            raise GroovePairingError(
                "boundary_cycle",
                "Boundary maximal chain 构成 cycle，无法确定开放 chain",
                {"edge_count": len(component)},
            )
        if len(endpoints) != 2:
            raise GroovePairingError(
                "boundary_branch",
                "Boundary component 不是唯一开放 chain",
                {"endpoint_count": len(endpoints), "edge_count": len(component)},
            )
        ordered = []
        previous_edge = None
        vertex = endpoints[0]
        while True:
            candidates = (vertex_edges[vertex] & component) - ({previous_edge} if previous_edge else set())
            if not candidates:
                break
            if len(candidates) != 1:
                raise GroovePairingError(
                    "boundary_branch",
                    "Boundary chain 遍历出现多个后继 Edge",
                )
            edge = next(iter(candidates))
            ordered.append(edge)
            vertex = edge.other_vert(vertex)
            previous_edge = edge
        if set(ordered) != component:
            raise GroovePairingError(
                "boundary_cycle",
                "Boundary chain 未能 exactly-once 消费全部 Edge",
            )
        chains.append(tuple(ordered))
        remaining -= component
    return chains


# groove_faces/face_identity/face_group_key: 全量 Groove Face 与稳定 identity 回调；完成 manifold 预检并按同组 adjacency 返回 corridor。
def _groove_face_components(groove_faces, face_identity, face_group_key):
    groove_set = set(groove_faces)
    if not groove_set:
        raise GroovePairingError("missing_groove_faces", "Groove Face 集合为空")
    face_keys = {}
    key_faces = {}
    group_keys = {}
    adjacency = defaultdict(set)
    for face in groove_set:
        key = _face_key(face, face_identity)
        if key in key_faces:
            raise GroovePairingError(
                "duplicate_face_identity",
                "Groove Face identity 不唯一",
            )
        face_keys[face] = key
        key_faces[key] = face
        raw_group_key = face_group_key(face)
        group_keys[face] = (
            None if raw_group_key is None else _canonical_identity(raw_group_key)
        )
    missing_boundary_group_faces = [
        face
        for face in groove_set
        if group_keys[face] is None
        and any(
            len(edge.link_faces) == 2
            and len(groove_set.intersection(edge.link_faces)) == 1
            for edge in face.edges
        )
    ]
    if missing_boundary_group_faces:
        raise GroovePairingError(
            "missing_face_group",
            "接触 groove/source 公共 Edge 的 Groove Face 缺少 semantic group",
            {"missing_face_count": len(missing_boundary_group_faces)},
        )
    for face in groove_set:
        for edge in face.edges:
            linked_faces = tuple(edge.link_faces)
            if len(linked_faces) != 2:
                raise GroovePairingError(
                    "non_manifold_groove",
                    "Groove Face 接触到非 closed-manifold Edge",
                    {"linked_face_count": len(linked_faces)},
                )
            linked_groove_faces = groove_set.intersection(linked_faces)
            if len(linked_groove_faces) == 2:
                first, second = tuple(linked_groove_faces)
                if (
                    group_keys[first] is not None
                    and group_keys[first] == group_keys[second]
                ):
                    adjacency[first].add(second)
                    adjacency[second].add(first)
    components = []
    remaining = {
        face for face in groove_set if group_keys[face] is not None
    }
    while remaining:
        component = set()
        queue = [next(iter(remaining))]
        while queue:
            face = queue.pop()
            if face in component:
                continue
            component.add(face)
            queue.extend(adjacency[face] - component)
        components.append(component)
        remaining -= component
    return components, face_keys, group_keys


# groove_faces/edge_identity/face_identity/face_group_key: 删除前 Groove FaceGraph、稳定 identity 与 Pipe/segment semantic batch 回调；返回冻结 pairing 合同。
def freeze_groove_boundary_pairing(
    groove_faces,
    edge_identity,
    face_identity,
    face_group_key,
):
    groove_set = set(groove_faces)
    components, face_keys, group_keys = _groove_face_components(
        groove_set,
        face_identity,
        face_group_key,
    )
    boundary_edges = set()
    boundary_groove_face = {}
    edge_keys = {}
    key_edges = {}
    for face in groove_set:
        for edge in face.edges:
            linked_faces = tuple(edge.link_faces)
            linked_groove_faces = groove_set.intersection(linked_faces)
            if len(linked_faces) != 2 or len(linked_groove_faces) != 1:
                continue
            groove_face = next(iter(linked_groove_faces))
            key = _edge_key(edge, edge_identity)
            if key in key_edges and key_edges[key] is not edge:
                raise GroovePairingError(
                    "duplicate_edge_identity",
                    "Boundary Edge identity 不唯一",
                )
            boundary_edges.add(edge)
            boundary_groove_face[edge] = groove_face
            edge_keys[edge] = key
            key_edges[key] = edge
    if not boundary_edges:
        raise GroovePairingError("missing_boundary", "Groove FaceGraph 没有 groove/source 公共 Edge")
    records = []
    consumed_edge_keys = set()
    for component_index, component in enumerate(components):
        group_key = group_keys[next(iter(component))]
        component_boundary_edges = {
            edge
            for edge in boundary_edges
            if boundary_groove_face[edge] in component
        }
        if not component_boundary_edges:
            continue
        chains = _maximal_open_chains(component_boundary_edges)
        if len(chains) < 2:
            raise GroovePairingError(
                "missing_opposite_chain",
                "Groove FaceGraph component 缺少两侧 Boundary chain",
                {"component_index": component_index, "exit_count": len(chains)},
            )
        if len(chains) > 2:
            raise GroovePairingError(
                "multiple_exit",
                "Groove FaceGraph component 存在多于两条 Boundary chain",
                {"component_index": component_index, "exit_count": len(chains)},
            )
        first_keys = tuple(edge_keys[edge] for edge in chains[0])
        second_keys = tuple(edge_keys[edge] for edge in chains[1])
        overlap = consumed_edge_keys.intersection(first_keys + second_keys)
        if overlap:
            raise GroovePairingError(
                "global_overlap",
                "Boundary Edge 被多个 pairing record 消费",
                {"overlap_count": len(overlap)},
            )
        consumed_edge_keys.update(first_keys + second_keys)
        records.append(
            {
                "group_id": group_key,
                "component_face_ids": tuple(sorted(face_keys[face] for face in component)),
                "first_edge_ids": first_keys,
                "second_edge_ids": second_keys,
            }
        )
    if consumed_edge_keys != set(edge_keys.values()):
        raise GroovePairingError(
            "global_overlap",
            "Boundary Edge 未被 pairing records exactly-once 消费",
        )
    return {
        "contract": GROOVE_PAIRING_CONTRACT,
        "records": tuple(records),
        "boundary_edge_ids": tuple(sorted(consumed_edge_keys)),
        "boundary_edge_refs": frozenset(boundary_edges),
    }


# frozen_pairing: freeze_groove_boundary_pairing 结果；返回与方向无关、可比较的规范 pairing。
def canonical_pairing(frozen_pairing):
    canonical_records = []
    for record in frozen_pairing["records"]:
        first = min(record["first_edge_ids"], tuple(reversed(record["first_edge_ids"])))
        second = min(record["second_edge_ids"], tuple(reversed(record["second_edge_ids"])))
        canonical_records.append((record["group_id"], tuple(sorted((first, second)))))
    return tuple(sorted(canonical_records))


# frozen_pairing/open_edges/edge_identity: 冻结合同、删除后开放 BMEdge 集合及可选稳定 identity 回调；核对集合无损转移。
def verify_open_boundary_transfer(frozen_pairing, open_edges, edge_identity=None):
    open_edge_set = set(open_edges)
    invalid_edges = [edge for edge in open_edge_set if len(edge.link_faces) != 1]
    if invalid_edges:
        raise GroovePairingError(
            "post_delete_edge_not_open",
            "删除后的候选 Edge 不是单 Face 开放 Edge",
            {"invalid_edge_count": len(invalid_edges)},
        )
    if edge_identity is None:
        matches = open_edge_set == set(frozen_pairing["boundary_edge_refs"])
    else:
        open_ids = [_edge_key(edge, edge_identity) for edge in open_edge_set]
        if len(open_ids) != len(set(open_ids)):
            raise GroovePairingError(
                "duplicate_post_delete_edge_identity",
                "删除后的开放 Edge identity 不唯一",
            )
        matches = set(open_ids) == set(frozen_pairing["boundary_edge_ids"])
    if not matches:
        raise GroovePairingError(
            "post_delete_boundary_mismatch",
            "删除前冻结的公共 Edge 与删除后开放 Edge 集合不一致",
        )
    return True
