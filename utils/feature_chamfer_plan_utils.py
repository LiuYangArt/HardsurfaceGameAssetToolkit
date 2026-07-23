# -*- coding: utf-8 -*-
"""Feature Chamfer Preview 与 Finalize 共享的 immutable shadow plan。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace

import bpy


PLAN_SCHEMA_VERSION = 1
PLAN_PROPERTY = "hst_feature_chamfer_plan"
PLAN_ID_PROPERTY = "hst_feature_chamfer_plan_id"
PLAN_MODE = "SHADOW"


@dataclass(frozen=True)
class FeatureStrand:
    strand_id: str
    ordered_edge_keys: tuple[str, ...]
    ordered_vertex_keys: tuple[str, ...]
    cyclic: bool
    owner_surface_pairs: tuple[tuple[int, int], ...]
    convexity_by_edge: tuple[int, ...]
    selected_pair_vertex_keys: tuple[str, ...]
    start_feature_degree: int
    end_feature_degree: int
    start_port_id: str | None
    end_port_id: str | None


@dataclass(frozen=True)
class JunctionPort:
    port_id: str
    vertex_key: str
    incident_strand_ids: tuple[str, ...]
    feature_degree: int


@dataclass(frozen=True)
class RailChain:
    rail_id: str
    owner_strand_id: str
    side: str
    boundary_edge_keys: tuple[str, ...]
    endpoint_port_ids: tuple[str, ...]


@dataclass(frozen=True)
class JunctionPortPatchIncidence:
    incidence_id: str
    owner_strand_id: str
    junction_port_id: str
    endpoint_role: str
    source_patch_ids: tuple[int, ...]


@dataclass(frozen=True)
class StripCorrespondence:
    correspondence_id: str
    owner_strand_id: str
    left_rail_id: str
    right_rail_id: str
    owner_surface_pair: tuple[int, int]


@dataclass(frozen=True)
class UnsupportedRegion:
    region_id: str
    reason_code: str
    owner_strand_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChamferPlan:
    schema_version: int
    plan_id: str
    source_fingerprint: str
    radius: float
    input_contract: str
    mode: str
    sharp_edge_count: int
    surface_patch_count: int
    feature_strands: tuple[FeatureStrand, ...]
    junction_ports: tuple[JunctionPort, ...]
    rail_chains: tuple[RailChain, ...]
    junction_port_patch_incidences: tuple[JunctionPortPatchIncidence, ...]
    strip_correspondences: tuple[StripCorrespondence, ...]
    unsupported_regions: tuple[UnsupportedRegion, ...]
    provenance: tuple[str, ...]
    is_complete: bool


# 把坐标量化成方向无关的稳定 key，避免 plan identity 依赖临时 Mesh index。
# point: 三维坐标；返回稳定字符串。
def _point_key(point):
    return ",".join(f"{float(component):.8f}" for component in point)


# 计算 source Edge 的方向无关坐标 key。
# mesh/edge_index: source Mesh 与 Edge index；返回稳定字符串。
def _edge_key(mesh, edge_index):
    edge = mesh.edges[edge_index]
    endpoints = sorted(_point_key(mesh.vertices[index].co) for index in edge.vertices)
    return "|".join(endpoints)


# 返回 source Vertex 的坐标加 incident Edge 几何签名，区分未焊接的重合顶点。
# mesh/vertex_index: source Mesh 与 Vertex index；返回不依赖临时 index 的稳定 key。
def _vertex_key(mesh, vertex_index):
    vertex = mesh.vertices[vertex_index]
    incident_edge_keys = sorted(
        _edge_key(mesh, edge.index)
        for edge in mesh.edges
        if vertex_index in edge.vertices
    )
    topology_hash = hashlib.sha256(
        json.dumps(incident_edge_keys, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{_point_key(vertex.co)}#{topology_hash}"


# 返回每个 Sharp vertex 的实际 Feature degree，供 terminal 与内部 junction port 共用。
# mesh: source Mesh；返回 point key 到 incident Sharp Edge 数量的映射。
def _sharp_feature_degrees(mesh):
    sharp_attribute = mesh.attributes.get("sharp_edge")
    feature_degrees = {}
    if sharp_attribute is None:
        return feature_degrees
    for edge in mesh.edges:
        if not sharp_attribute.data[edge.index].value:
            continue
        for vertex_index in edge.vertices:
            vertex_key = _vertex_key(mesh, vertex_index)
            feature_degrees[vertex_key] = feature_degrees.get(vertex_key, 0) + 1
    return feature_degrees


# 返回 source Vertex 邻接 Face 的 Surface Patch ID，不使用坐标、BVH 或最近距离推断。
# mesh/patch_ids_by_face: source Mesh 与按 polygon index 排列的 Patch ID；返回 Vertex key 到 Patch IDs 的映射。
def _source_vertex_patch_incidence(mesh, patch_ids_by_face):
    patch_ids_by_vertex_key = {}
    for polygon in mesh.polygons:
        patch_id = int(patch_ids_by_face[polygon.index])
        for vertex_index in polygon.vertices:
            vertex_key = _vertex_key(mesh, vertex_index)
            patch_ids_by_vertex_key.setdefault(vertex_key, set()).add(patch_id)
    return {
        vertex_key: tuple(sorted(patch_ids))
        for vertex_key, patch_ids in patch_ids_by_vertex_key.items()
    }


# 规范化 strand 方向/seam，并同步 owner Surface pair，使 correspondence 不错位。
# edge_keys/vertex_keys/owner_pairs/convexities/degrees/cyclic: Edge、Vertex、owner 与端点语义；返回 canonical 序列。
def _canonical_strand(
    edge_keys,
    vertex_keys,
    owner_pairs,
    convexities,
    endpoint_degrees,
    cyclic,
):
    if cyclic:
        variants = []
        for ordered_edges, ordered_vertices, ordered_owners, ordered_convexities in (
            (edge_keys, vertex_keys, owner_pairs, convexities),
            (
                tuple(reversed(edge_keys[:-1])) + edge_keys[-1:],
                tuple(reversed(vertex_keys)),
                tuple(reversed(owner_pairs[:-1])) + owner_pairs[-1:],
                tuple(reversed(convexities[:-1])) + convexities[-1:],
            ),
        ):
            for offset in range(len(ordered_edges)):
                variants.append(
                    (
                        ordered_edges[offset:] + ordered_edges[:offset],
                        ordered_vertices[offset:] + ordered_vertices[:offset],
                        ordered_owners[offset:] + ordered_owners[:offset],
                        ordered_convexities[offset:] + ordered_convexities[:offset],
                        endpoint_degrees,
                    )
                )
        return min(variants)
    forward = (edge_keys, vertex_keys, owner_pairs, convexities, endpoint_degrees)
    reverse = (
        tuple(reversed(edge_keys)),
        tuple(reversed(vertex_keys)),
        tuple(reversed(owner_pairs)),
        tuple(reversed(convexities)),
        tuple(reversed(endpoint_degrees)),
    )
    return min(forward, reverse)


# 验证 canonical strand 的每条 Edge/owner/convexity 仍对应同一 Vertex segment。
# mesh/strand: source Mesh 与 FeatureStrand；不满足时抛出 ValueError。
def _validate_feature_strand_alignment(mesh, strand):
    edge_owner_records = {
        _edge_key(mesh, edge.index): edge.index
        for edge in mesh.edges
    }
    segment_count = len(strand.ordered_vertex_keys) if strand.cyclic else len(strand.ordered_vertex_keys) - 1
    if len(strand.ordered_edge_keys) != segment_count:
        raise ValueError("FeatureStrand Edge/Vertex coverage is inconsistent")
    for offset, edge_key in enumerate(strand.ordered_edge_keys):
        edge_index = edge_owner_records.get(edge_key)
        if edge_index is None:
            raise ValueError("FeatureStrand references an unknown source Edge")
        actual_vertices = {
            _vertex_key(mesh, vertex_index)
            for vertex_index in mesh.edges[edge_index].vertices
        }
        expected_vertices = {
            strand.ordered_vertex_keys[offset],
            strand.ordered_vertex_keys[(offset + 1) % len(strand.ordered_vertex_keys)],
        }
        if actual_vertices != expected_vertices:
            raise ValueError("FeatureStrand Edge metadata is misaligned with its Vertex walk")


# 由稳定 payload 计算 SHA-256；plan_id 字段本身不参与 hash。
# plan: immutable ChamferPlan；返回 fingerprint。
def chamfer_plan_fingerprint(plan):
    payload = asdict(
        replace(
            plan,
            plan_id="",
            unsupported_regions=(),
            is_complete=True,
        )
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# 从现有 GN Preview FeatureGraph 构建 immutable shadow plan，不改变现有算法和输出。
# source_object/groups/radius/input_contract: source Mesh、已有 groups、半径和合同；source_patch_ids: 可选的 Face→Patch authoritative 映射；返回 ChamferPlan。
def build_chamfer_plan(
    source_object,
    groups,
    radius,
    input_contract,
    source_patch_ids=None,
):
    mesh = source_object.data
    strands = []
    for group in groups:
        edge_keys = tuple(_edge_key(mesh, index) for index in group["edge_indices"])
        vertex_keys = tuple(
            _vertex_key(mesh, index) for index in group["vertex_indices"]
        )
        owner_surface_pairs = tuple(
            tuple(int(item) for item in pair)
            for pair in group["patch_pair_by_edge"]
        )
        convexity_by_edge = tuple(int(value) for value in group["convexity_by_edge"])
        edge_keys, vertex_keys, owner_surface_pairs, convexity_by_edge, endpoint_degrees = _canonical_strand(
            edge_keys,
            vertex_keys,
            owner_surface_pairs,
            convexity_by_edge,
            (
                int(group["start_feature_degree"]),
                int(group["end_feature_degree"]),
            ),
            bool(group["is_cyclic"]),
        )
        strand_identity = hashlib.sha256(
            json.dumps(
                {"edges": edge_keys, "vertices": vertex_keys, "cyclic": group["is_cyclic"]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]
        strand_id = f"strand:{strand_identity}"
        start_port_id = None
        end_port_id = None
        if not group["is_cyclic"]:
            start_port_id = f"port:{vertex_keys[0]}"
            end_port_id = f"port:{vertex_keys[-1]}"
        feature_strand = FeatureStrand(
                strand_id=strand_id,
                ordered_edge_keys=edge_keys,
                ordered_vertex_keys=vertex_keys,
                cyclic=bool(group["is_cyclic"]),
                owner_surface_pairs=owner_surface_pairs,
                convexity_by_edge=convexity_by_edge,
                selected_pair_vertex_keys=tuple(
                    sorted(
                        _vertex_key(mesh, index)
                        for index in group["selected_pair_vertex_ids"]
                    )
                ),
                start_feature_degree=endpoint_degrees[0],
                end_feature_degree=endpoint_degrees[1],
                start_port_id=start_port_id,
                end_port_id=end_port_id,
            )
        _validate_feature_strand_alignment(mesh, feature_strand)
        strands.append(feature_strand)
    strands = tuple(sorted(strands, key=lambda strand: strand.strand_id))
    feature_degrees = _sharp_feature_degrees(mesh)
    port_incidence = {}
    for strand in strands:
        port_vertex_keys = {
            vertex_key
            for vertex_key in strand.selected_pair_vertex_keys
            if feature_degrees[vertex_key] != 2
        }
        if strand.start_port_id is not None:
            port_vertex_keys.add(strand.start_port_id.removeprefix("port:"))
        if strand.end_port_id is not None:
            port_vertex_keys.add(strand.end_port_id.removeprefix("port:"))
        for vertex_key in port_vertex_keys:
            port_incidence.setdefault(vertex_key, set()).add(strand.strand_id)
    ports = tuple(
        JunctionPort(
            port_id=f"port:{vertex_key}",
            vertex_key=vertex_key,
            incident_strand_ids=tuple(sorted(strand_ids)),
            feature_degree=feature_degrees[vertex_key],
        )
        for vertex_key, strand_ids in sorted(port_incidence.items())
    )
    junction_port_patch_incidences = ()
    if source_patch_ids is not None:
        if len(source_patch_ids) != len(mesh.polygons):
            raise ValueError("ChamferPlan source Patch incidence is incomplete")
        patch_ids_by_vertex_key = _source_vertex_patch_incidence(
            mesh,
            source_patch_ids,
        )
        junction_port_patch_incidences = tuple(
            JunctionPortPatchIncidence(
                incidence_id=(
                    f"port-patch:{strand.strand_id}:{endpoint_role}:"
                    f"{port_id}"
                ),
                owner_strand_id=strand.strand_id,
                junction_port_id=port_id,
                endpoint_role=endpoint_role,
                source_patch_ids=patch_ids_by_vertex_key.get(
                    port_id.removeprefix("port:"),
                    (),
                ),
            )
            for strand in strands
            if not strand.cyclic
            for endpoint_role, port_id in (
                ("START", strand.start_port_id),
                ("END", strand.end_port_id),
            )
            if port_id is not None
        )
    provenance = (
        "UI:Feature Chamfer GN",
        "OPERATOR:hst.feature_chamfer_gn",
        "FEATURE_GRAPH:GN_PREVIEW_V1",
        "PLAN_MODE:SHADOW",
    )
    expected_rails = tuple(
        RailChain(
            rail_id=f"rail:{strand.strand_id}:patch:{patch_id}",
            owner_strand_id=strand.strand_id,
            side=f"OWNER_PATCH:{patch_id}",
            boundary_edge_keys=(),
            endpoint_port_ids=tuple(
                sorted(
                    {
                        *(
                            f"port:{vertex_key}"
                            for vertex_key in strand.selected_pair_vertex_keys
                            if feature_degrees[vertex_key] != 2
                        ),
                        *(
                            port_id
                            for port_id in (
                                strand.start_port_id,
                                strand.end_port_id,
                            )
                            if port_id is not None
                        ),
                    }
                )
            ),
        )
        for strand in strands
        for patch_id in sorted(
            {
                patch_id
                for owner_pair in strand.owner_surface_pairs
                for patch_id in owner_pair
            }
        )
    )
    expected_correspondences = tuple(
        StripCorrespondence(
            correspondence_id=f"strip:{strand.strand_id}:{owner_pair[0]}:{owner_pair[1]}",
            owner_strand_id=strand.strand_id,
            left_rail_id=f"rail:{strand.strand_id}:patch:{owner_pair[0]}",
            right_rail_id=f"rail:{strand.strand_id}:patch:{owner_pair[1]}",
            owner_surface_pair=owner_pair,
        )
        for strand in strands
        for owner_pair in sorted(set(strand.owner_surface_pairs))
        if owner_pair[0] != owner_pair[1]
    )
    plan = ChamferPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        plan_id="",
        source_fingerprint=source_fingerprint(source_object),
        radius=round(float(radius), 10),
        input_contract=input_contract,
        mode=PLAN_MODE,
        sharp_edge_count=sum(len(strand.ordered_edge_keys) for strand in strands),
        surface_patch_count=len(
            {
                patch_id
                for strand in strands
                for owner_pair in strand.owner_surface_pairs
                for patch_id in owner_pair
            }
        ),
        feature_strands=strands,
        junction_ports=ports,
        rail_chains=expected_rails,
        junction_port_patch_incidences=junction_port_patch_incidences,
        strip_correspondences=expected_correspondences,
        unsupported_regions=(),
        provenance=provenance,
        is_complete=True,
    )
    return replace(plan, plan_id=chamfer_plan_fingerprint(plan))


# 从 plan 的 FeatureStrand 读取 local-space points，供 Preview adapter 生成 Curve。
# strand: immutable FeatureStrand；返回三维坐标元组。
def feature_strand_points(strand):
    return tuple(
        tuple(float(component) for component in vertex_key.split("#", 1)[0].split(","))
        for vertex_key in strand.ordered_vertex_keys
    )


# 把 backend stable diagnostic families 追加为 UnsupportedRegion，不改变 semantic plan ID。
# plan/families: 原 immutable plan 与 Phase 1 family records；返回新的 incomplete plan。
def chamfer_plan_with_unsupported_regions(plan, families, fallback_reason_code=None):
    strand_ids = tuple(strand.strand_id for strand in plan.feature_strands)
    unsupported_regions = tuple(
        UnsupportedRegion(
            region_id=item["diagnostic_id"],
            reason_code=item["family"],
            owner_strand_ids=strand_ids,
            evidence_ids=(item["diagnostic_id"],),
        )
        for item in families
        if item.get("diagnostic_id") and item.get("family")
    )
    if not unsupported_regions and fallback_reason_code:
        reason_code = str(fallback_reason_code)
        region_id = "runtime:" + hashlib.sha256(reason_code.encode("utf-8")).hexdigest()[:16]
        unsupported_regions = (
            UnsupportedRegion(
                region_id=region_id,
                reason_code=reason_code,
                owner_strand_ids=strand_ids,
                evidence_ids=(region_id,),
            ),
        )
    if not unsupported_regions:
        return plan
    return replace(
        plan,
        unsupported_regions=unsupported_regions,
        is_complete=False,
    )


# 清除 Finalize runtime diagnostics，恢复同一 semantic plan 的 complete 视图。
# plan: 可能含 UnsupportedRegion 的 plan；返回 plan_id 不变的 complete plan。
def chamfer_plan_without_unsupported_regions(plan):
    return replace(plan, unsupported_regions=(), is_complete=True)


# 返回 Mesh topology、坐标和 Sharp Edge 的稳定指纹。
# source_object: source Mesh Object；返回 SHA-256。
def source_fingerprint(source_object):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    payload = {
        "vertices": [_point_key(vertex.co) for vertex in mesh.vertices],
        "edges": [sorted(int(index) for index in edge.vertices) for edge in mesh.edges],
        "faces": [list(int(index) for index in polygon.vertices) for polygon in mesh.polygons],
        "sharp": [
            bool(sharp_attribute and sharp_attribute.data[edge.index].value)
            for edge in mesh.edges
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# 把 immutable plan 转为稳定 JSON 字符串，供 Blender ID Property 持久化。
# plan: ChamferPlan；返回 JSON。
def chamfer_plan_json(plan):
    return json.dumps(asdict(plan), sort_keys=True, separators=(",", ":"))


# 从稳定 JSON 还原 immutable ChamferPlan。
# payload: JSON 字符串；返回 ChamferPlan。
def chamfer_plan_from_json(payload):
    data = json.loads(payload)
    return ChamferPlan(
        schema_version=int(data["schema_version"]),
        plan_id=data["plan_id"],
        source_fingerprint=data["source_fingerprint"],
        radius=float(data["radius"]),
        input_contract=data["input_contract"],
        mode=data["mode"],
        sharp_edge_count=int(data["sharp_edge_count"]),
        surface_patch_count=int(data["surface_patch_count"]),
        feature_strands=tuple(
            FeatureStrand(
                strand_id=item["strand_id"],
                ordered_edge_keys=tuple(item["ordered_edge_keys"]),
                ordered_vertex_keys=tuple(item["ordered_vertex_keys"]),
                cyclic=bool(item["cyclic"]),
                owner_surface_pairs=tuple(
                    tuple(pair) for pair in item["owner_surface_pairs"]
                ),
                convexity_by_edge=tuple(item["convexity_by_edge"]),
                selected_pair_vertex_keys=tuple(item["selected_pair_vertex_keys"]),
                start_feature_degree=int(item["start_feature_degree"]),
                end_feature_degree=int(item["end_feature_degree"]),
                start_port_id=item["start_port_id"],
                end_port_id=item["end_port_id"],
            )
            for item in data["feature_strands"]
        ),
        junction_ports=tuple(
            JunctionPort(
                port_id=item["port_id"],
                vertex_key=item["vertex_key"],
                incident_strand_ids=tuple(item["incident_strand_ids"]),
                feature_degree=int(item["feature_degree"]),
            )
            for item in data["junction_ports"]
        ),
        rail_chains=tuple(
            RailChain(
                rail_id=item["rail_id"],
                owner_strand_id=item["owner_strand_id"],
                side=item["side"],
                boundary_edge_keys=tuple(item["boundary_edge_keys"]),
                endpoint_port_ids=tuple(item["endpoint_port_ids"]),
            )
            for item in data["rail_chains"]
        ),
        junction_port_patch_incidences=tuple(
            JunctionPortPatchIncidence(
                incidence_id=item["incidence_id"],
                owner_strand_id=item["owner_strand_id"],
                junction_port_id=item["junction_port_id"],
                endpoint_role=item["endpoint_role"],
                source_patch_ids=tuple(item["source_patch_ids"]),
            )
            for item in data.get("junction_port_patch_incidences", ())
        ),
        strip_correspondences=tuple(
            StripCorrespondence(
                correspondence_id=item["correspondence_id"],
                owner_strand_id=item["owner_strand_id"],
                left_rail_id=item["left_rail_id"],
                right_rail_id=item["right_rail_id"],
                owner_surface_pair=tuple(item["owner_surface_pair"]),
            )
            for item in data["strip_correspondences"]
        ),
        unsupported_regions=tuple(
            UnsupportedRegion(
                region_id=item["region_id"],
                reason_code=item["reason_code"],
                owner_strand_ids=tuple(item["owner_strand_ids"]),
                evidence_ids=tuple(item["evidence_ids"]),
            )
            for item in data["unsupported_regions"]
        ),
        provenance=tuple(data["provenance"]),
        is_complete=bool(data["is_complete"]),
    )


# 把 plan 与独立 plan ID 写入 Blender ID custom properties。
# id_block/plan: Object、Modifier 等 ID Property owner 与 ChamferPlan；无返回值。
def write_chamfer_plan(id_block, plan):
    id_block[PLAN_PROPERTY] = chamfer_plan_json(plan)
    id_block[PLAN_ID_PROPERTY] = plan.plan_id


# 从 Blender ID custom properties 读取并验证 plan；缺失时返回 None，损坏时抛错。
# id_block: Object、Modifier 等 ID Property owner；返回 ChamferPlan 或 None。
def read_chamfer_plan(id_block):
    payload = id_block.get(PLAN_PROPERTY) if id_block is not None else None
    if not payload:
        return None
    plan = chamfer_plan_from_json(payload)
    if plan.plan_id != chamfer_plan_fingerprint(plan):
        raise ValueError("Stored ChamferPlan fingerprint does not match immutable payload")
    if id_block.get(PLAN_ID_PROPERTY) != plan.plan_id:
        raise ValueError("Stored ChamferPlan ID property does not match payload")
    return plan
