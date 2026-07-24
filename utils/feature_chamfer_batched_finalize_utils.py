# -*- coding: utf-8 -*-
"""Feature Chamfer 分批 Finalize 的深 Module 与机器可读合同。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass

import bpy
import bmesh
from mathutils import Vector
from mathutils import geometry
from mathutils.bvhtree import BVHTree

from ..const import FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG
from .experimental_pipe_chamfer_utils import PIPE_ID_TAG
from .experimental_pipe_chamfer_utils import PROBE_EDGE_COMPOUND_ENDPOINT_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import BOUNDARY_OWNER_WITNESS_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import CUTTER_COMPONENT_MEMBERSHIP_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import ORIGINAL_FACE_ATTRIBUTE
from .experimental_pipe_chamfer_utils import SOURCE_PATCH_MEMBERSHIP_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import _bounds_overlap
from .experimental_pipe_chamfer_utils import _aligned_rail_correspondence
from .experimental_pipe_chamfer_utils import _build_joined_cutter_mesh
from .experimental_pipe_chamfer_utils import _build_pipe_mesh
from .experimental_pipe_chamfer_utils import _coordinate_parameters
from .experimental_pipe_chamfer_utils import _cutter_intersection_rails
from .experimental_pipe_chamfer_utils import _extract_boolean_rail_pair_records
from .experimental_pipe_chamfer_utils import _initialize_source_membership_schema
from .experimental_pipe_chamfer_utils import _initialize_boundary_witness_schema
from .experimental_pipe_chamfer_utils import _mark_boolean_boundary_witnesses
from .experimental_pipe_chamfer_utils import _mesh_risk_counts
from .experimental_pipe_chamfer_utils import _mark_original_faces
from .experimental_pipe_chamfer_utils import _non_overlapping_pipe_batches
from .experimental_pipe_chamfer_utils import _pipe_bounds
from .experimental_pipe_chamfer_utils import _synchronize_cutter_membership_schema
from .experimental_pipe_chamfer_utils import _source_face_patch_ids
from .experimental_pipe_chamfer_utils import _seed_cutter_edge_owner_witnesses
from .experimental_pipe_chamfer_utils import _group_patch_pair_spans
from .experimental_pipe_chamfer_utils import _build_strand_endpoint_port_tokens
from .experimental_pipe_chamfer_utils import build_chamfer_strip
from .feature_chamfer_gn_utils import owned_preview_curve
from .feature_chamfer_gn_utils import source_fingerprint
from .feature_chamfer_plan_utils import source_fingerprint as plan_source_fingerprint


BATCHED_BACKEND_ID = "BATCHED_CUT_FILL_V1"
DEBUG_PHASE_A = "PHASE_A_INPUT_CONTRACT"
DEBUG_PHASE_B = "PHASE_B_BATCH_PROBE"
DEBUG_PHASE_C = "PHASE_C_REGULAR_CORE"
SUPPORTED_DEBUG_STAGES = {DEBUG_PHASE_A, DEBUG_PHASE_B, DEBUG_PHASE_C}


class BatchedChamferError(RuntimeError):
    """携带稳定失败 code 与可序列化 diagnostics 的 Finalize 失败。"""

    def __init__(self, error_code, message, diagnostics):
        super().__init__(message)
        self.error_code = error_code
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class PreviewPipeSpec:
    """正式 Preview FeatureStrand 对应的一根可验证 Cutter Pipe。"""

    pipe_id: int
    strand_id: str
    ordered_edge_keys: tuple[str, ...]
    cyclic: bool
    start_endpoint_class: str
    end_endpoint_class: str
    start_extension: float
    end_extension: float
    mesh_fingerprint: str
    vertex_count: int
    edge_count: int
    face_count: int


@dataclass(frozen=True)
class BatchedChamferResult:
    """分批 Finalize 的稳定机器合同；阶段性 probe 也使用相同 schema。"""

    status: str
    backend_id: str
    debug_stage: str
    output_object_name: str | None
    plan_id: str
    source_fingerprint: str
    radius: float
    preview_pipe_contract_fingerprint: str
    pipe_specs: tuple[PreviewPipeSpec, ...]
    overlap_pairs: tuple[tuple[int, int], ...]
    color_batches: tuple[tuple[int, ...], ...]
    batch_records: tuple[dict, ...]
    boundary_edge_ledger: tuple[dict, ...]
    junction_regions: tuple[dict, ...]
    topology_diagnostics: dict
    batch_order_invariance_fingerprint: str
    failure_code: str | None

    def to_dict(self):
        """返回只含 JSON primitive 的稳定 diagnostics。"""

        return asdict(self)


# 返回只含稳定 semantic identity 的 staging Boundary 记录，避免 diagnostics 暴露临时 Mesh index。
# records: _extract_staging_boundary_records 输出；返回可用于正逆序比较的 canonical records。
def _canonical_boundary_records(records):
    return tuple(
        {
            key: value
            for key, value in record.items()
            if key != "debug_edge_index"
        }
        for record in sorted(records, key=lambda item: item["edge_id"])
    )


# 验证生成的 Regular Strip Faces 含有效面积、一致局部朝向，且不含重复 Face。
# regular_records: 含 coordinate Faces 的 Phase C records；返回 guard diagnostics。
def _validate_regular_strip_geometry(regular_records):
    zero_area_count = 0
    orientation_conflict_count = 0
    duplicate_face_count = 0
    self_intersection_count = 0
    seen_faces = set()
    triangulated_vertices = []
    triangulated_vertex_index_by_key = {}
    triangulated_faces = []
    triangulated_vertex_keys = []
    triangulated_coordinates = []
    for record in regular_records:
        edge_incidence = {}
        for face_index, face in enumerate(record.get("faces", [])):
            coordinates = [Vector(point) for point in face]
            normal = Vector()
            for index, coordinate in enumerate(coordinates):
                normal += coordinate.cross(coordinates[(index + 1) % len(coordinates)])
            if normal.length <= 1.0e-12:
                zero_area_count += 1
                continue
            normal.normalize()
            face_key = tuple(
                sorted(tuple(round(float(value), 8) for value in point) for point in face)
            )
            if face_key in seen_faces:
                duplicate_face_count += 1
            seen_faces.add(face_key)
            coordinate_keys = [
                tuple(round(float(value), 8) for value in point)
                for point in coordinates
            ]
            for start_key, end_key in zip(
                coordinate_keys,
                coordinate_keys[1:] + coordinate_keys[:1],
            ):
                edge_incidence.setdefault(
                    tuple(sorted((start_key, end_key))),
                    [],
                ).append((face_index, start_key, end_key))
            for triangle_indices in geometry.tessellate_polygon([coordinates]):
                triangle = tuple(
                    coordinates[index] for index in triangle_indices
                )
                triangle_keys = tuple(
                    tuple(round(float(value), 8) for value in point)
                    for point in triangle
                )
                triangle_vertex_indices = []
                for point, point_key in zip(triangle, triangle_keys):
                    vertex_index = triangulated_vertex_index_by_key.get(point_key)
                    if vertex_index is None:
                        vertex_index = len(triangulated_vertices)
                        triangulated_vertices.append(point)
                        triangulated_vertex_index_by_key[point_key] = vertex_index
                    triangle_vertex_indices.append(vertex_index)
                triangulated_faces.append(tuple(triangle_vertex_indices))
                triangulated_vertex_keys.append(frozenset(triangle_keys))
                triangulated_coordinates.append(triangle)
        for incidences in edge_incidence.values():
            if len(incidences) > 2:
                orientation_conflict_count += 1
                continue
            if len(incidences) == 2:
                _, start_a, end_a = incidences[0]
                _, start_b, end_b = incidences[1]
                if (start_a, end_a) != (end_b, start_b):
                    orientation_conflict_count += 1
    if triangulated_faces:
        overlap_pairs = set()
        for left_index, left_triangle in enumerate(triangulated_coordinates):
            for right_index in range(
                left_index + 1,
                len(triangulated_coordinates),
            ):
                if (
                    triangulated_vertex_keys[left_index]
                    & triangulated_vertex_keys[right_index]
                ):
                    continue
                right_triangle = triangulated_coordinates[right_index]
                left_minimum = Vector(
                    min(point[axis] for point in left_triangle)
                    for axis in range(3)
                )
                left_maximum = Vector(
                    max(point[axis] for point in left_triangle)
                    for axis in range(3)
                )
                right_minimum = Vector(
                    min(point[axis] for point in right_triangle)
                    for axis in range(3)
                )
                right_maximum = Vector(
                    max(point[axis] for point in right_triangle)
                    for axis in range(3)
                )
                bounds_overlap = all(
                    left_minimum[axis] <= right_maximum[axis] + 1.0e-8
                    and right_minimum[axis] <= left_maximum[axis] + 1.0e-8
                    for axis in range(3)
                )
                if not bounds_overlap:
                    continue
                segment_hits = []
                for segment_triangle, target_triangle in (
                    (left_triangle, right_triangle),
                    (right_triangle, left_triangle),
                ):
                    for start, end in zip(
                        segment_triangle,
                        (*segment_triangle[1:], segment_triangle[0]),
                    ):
                        direction = end - start
                        if direction.length_squared <= 1.0e-24:
                            continue
                        hit = geometry.intersect_ray_tri(
                            *target_triangle,
                            direction,
                            start,
                            True,
                        )
                        if hit is None:
                            continue
                        factor = (hit - start).dot(direction) / direction.length_squared
                        if -1.0e-8 <= factor <= 1.0 + 1.0e-8:
                            segment_hits.append(hit)
                if segment_hits:
                    overlap_pairs.add((left_index, right_index))
        self_intersection_count = len(overlap_pairs)
    return {
        "status": (
            "PASS"
            if not zero_area_count
            and not orientation_conflict_count
            and not duplicate_face_count
            and not self_intersection_count
            else "FAIL"
        ),
        "zero_area_face_count": zero_area_count,
        "orientation_conflict_count": orientation_conflict_count,
        "duplicate_face_count": duplicate_face_count,
        "self_intersection_count": self_intersection_count,
    }


# 对任意稳定 payload 生成 SHA-256；payload 中不得包含临时 Object 名或 BMesh index。
# payload: 可被 json.dumps 序列化的嵌套数据；返回十六进制 SHA-256。
def _stable_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


# 计算 Pipe Mesh 的 canonical 几何签名，忽略临时 Object/Mesh 名称与 Face 起点/方向。
# mesh: evaluated 四边 Even-Thickness Pipe Mesh；返回稳定 SHA-256。
def _mesh_fingerprint(mesh):
    coordinates = tuple(
        tuple(round(float(value), 8) for value in vertex.co)
        for vertex in mesh.vertices
    )
    payload = {
        "vertices": sorted(coordinates),
        "edges": sorted(
            sorted((coordinates[edge.vertices[0]], coordinates[edge.vertices[1]]))
            for edge in mesh.edges
        ),
        "faces": sorted(
            min(
                min(
                    tuple(oriented_coordinates[offset:] + oriented_coordinates[:offset])
                    for offset in range(len(oriented_coordinates))
                )
                for oriented_coordinates in (
                    face_coordinates,
                    list(reversed(face_coordinates)),
                )
            )
            for polygon in mesh.polygons
            for face_coordinates in [[coordinates[index] for index in polygon.vertices]]
        ),
    }
    return _stable_fingerprint(payload)


# 把 Face 顶点 loop 规范为不依赖起点与方向的稳定坐标签名。
# mesh/polygon: Boolean staging Mesh 与相邻 Polygon；返回量化后的 canonical loop。
def _canonical_face_loop(mesh, polygon):
    coordinates = [
        tuple(round(float(value), 8) for value in mesh.vertices[index].co)
        for index in polygon.vertices
    ]
    return min(
        tuple(oriented[offset:] + oriented[:offset])
        for oriented in (coordinates, list(reversed(coordinates)))
        for offset in range(len(oriented))
    )


# 读取同一 prefix 的 one-hot Mesh attribute，并返回当前元素唯一 semantic ID 集合。
# attributes/prefix/element_index: attributes collection、名称前缀与 domain index；返回 int ID set。
def _one_hot_ids(attributes, prefix, element_index):
    return {
        int(attribute.name.removeprefix(prefix))
        for attribute in attributes
        if attribute.name.startswith(prefix)
        and bool(attribute.data[element_index].value)
    }


# 从 independent Boolean staging 序列化真实 groove/source 交线及 direct Pipe/Patch provenance。
# working_object/plan_id/semantic_batch/marked_edge_indices: staging、Plan、稳定 batch 与 witness 标记；返回稳定 Boundary records。
def _extract_staging_boundary_records(
    working_object,
    plan_id,
    semantic_batch,
    marked_edge_indices,
):
    mesh = working_object.data
    original_attribute = mesh.attributes.get(ORIGINAL_FACE_ATTRIBUTE)
    if original_attribute is None or original_attribute.domain != "FACE":
        raise BatchedChamferError(
            "BATCH_BOUNDARY_PROVENANCE_MISSING",
            "Independent staging 缺少 original Face provenance",
            {"pipe_ids": list(semantic_batch)},
        )
    polygons_by_edge = {}
    edge_indices_by_vertex = {}
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            polygons_by_edge.setdefault(mesh.loops[loop_index].edge_index, []).append(
                polygon
            )
    for mesh_edge in mesh.edges:
        for vertex_index in mesh_edge.vertices:
            edge_indices_by_vertex.setdefault(vertex_index, []).append(mesh_edge.index)
    vertex_topology_signatures = {}
    for vertex_index, incident_edge_indices in edge_indices_by_vertex.items():
        incident_signatures = []
        for incident_edge_index in incident_edge_indices:
            incident_edge = mesh.edges[incident_edge_index]
            other_vertex_index = next(
                index for index in incident_edge.vertices if index != vertex_index
            )
            incident_signatures.append(
                {
                    "other_endpoint": tuple(
                        round(float(value), 8)
                        for value in mesh.vertices[other_vertex_index].co
                    ),
                    "adjacent_face_loops": sorted(
                        _stable_fingerprint(_canonical_face_loop(mesh, polygon))
                        for polygon in polygons_by_edge.get(incident_edge_index, ())
                    ),
                }
            )
        vertex_topology_signatures[vertex_index] = _stable_fingerprint(
            sorted(
                incident_signatures,
                key=lambda item: _stable_fingerprint(item),
            )
        )
    records = []
    record_by_edge_id = {}
    for edge_index in marked_edge_indices:
        edge = mesh.edges[edge_index]
        adjacent_polygons = polygons_by_edge.get(edge_index, [])
        source_polygons = [
            polygon
            for polygon in adjacent_polygons
            if bool(original_attribute.data[polygon.index].value)
        ]
        groove_polygons = [
            polygon
            for polygon in adjacent_polygons
            if not bool(original_attribute.data[polygon.index].value)
        ]
        owner_ids = _one_hot_ids(
            mesh.attributes,
            BOUNDARY_OWNER_WITNESS_ATTRIBUTE_PREFIX,
            edge_index,
        )
        patch_ids = _one_hot_ids(
            mesh.attributes,
            BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX,
            edge_index,
        )
        direct_owner_ids = (
            _one_hot_ids(
                mesh.attributes,
                CUTTER_COMPONENT_MEMBERSHIP_ATTRIBUTE_PREFIX,
                groove_polygons[0].index,
            )
            if len(groove_polygons) == 1
            else set()
        )
        direct_patch_ids = (
            _one_hot_ids(
                mesh.attributes,
                SOURCE_PATCH_MEMBERSHIP_ATTRIBUTE_PREFIX,
                source_polygons[0].index,
            )
            if len(source_polygons) == 1
            else set()
        )
        aggregate_direct_owner_ids = {
            owner_id
            for polygon in groove_polygons
            for owner_id in _one_hot_ids(
                mesh.attributes,
                CUTTER_COMPONENT_MEMBERSHIP_ATTRIBUTE_PREFIX,
                polygon.index,
            )
        }
        aggregate_direct_patch_ids = {
            patch_id
            for polygon in source_polygons
            for patch_id in _one_hot_ids(
                mesh.attributes,
                SOURCE_PATCH_MEMBERSHIP_ATTRIBUTE_PREFIX,
                polygon.index,
            )
        }
        accepted_face_fan = (
            len(adjacent_polygons) >= 2
            and len(source_polygons) >= 1
            and len(groove_polygons) >= 1
            and aggregate_direct_owner_ids == owner_ids
            and aggregate_direct_patch_ids == patch_ids
        )
        if (
            len(owner_ids) != 1
            or len(patch_ids) != 1
            or not (
                (
                    len(adjacent_polygons) == 2
                    and len(source_polygons) == 1
                    and len(groove_polygons) == 1
                    and direct_owner_ids == owner_ids
                    and direct_patch_ids == patch_ids
                )
                or accepted_face_fan
            )
        ):
            raise BatchedChamferError(
                "BATCH_BOUNDARY_PROVENANCE_CONFLICT",
                "Independent staging Boundary 的 direct Pipe/Patch provenance 不唯一或不一致",
                {
                    "pipe_ids": list(semantic_batch),
                    "debug_edge_index": int(edge_index),
                    "adjacent_face_count": len(adjacent_polygons),
                    "source_face_count": len(source_polygons),
                    "groove_face_count": len(groove_polygons),
                    "owner_ids": sorted(owner_ids),
                    "patch_ids": sorted(patch_ids),
                    "direct_owner_ids": sorted(direct_owner_ids),
                    "direct_patch_ids": sorted(direct_patch_ids),
                },
            )
        owner_pipe_id = next(iter(owner_ids))
        source_patch_id = next(iter(patch_ids))
        if owner_pipe_id not in semantic_batch:
            raise BatchedChamferError(
                "BATCH_BOUNDARY_OWNER_OUTSIDE_BATCH",
                "Boundary owner Pipe 不属于当前 semantic batch",
                {
                    "pipe_ids": list(semantic_batch),
                    "owner_pipe_id": owner_pipe_id,
                },
            )
        endpoint_port_tokens = sorted({
            int(attribute.name.removeprefix(
                f"{PROBE_EDGE_COMPOUND_ENDPOINT_ATTRIBUTE_PREFIX}{owner_pipe_id}_"
            ))
            for attribute in mesh.attributes
            if attribute.domain == "EDGE"
            and attribute.name.startswith(
                f"{PROBE_EDGE_COMPOUND_ENDPOINT_ATTRIBUTE_PREFIX}{owner_pipe_id}_"
            )
            and bool(attribute.data[edge_index].value)
        })
        endpoint_records = sorted(
            (
                tuple(round(float(value), 8) for value in mesh.vertices[index].co),
                vertex_topology_signatures[index],
                int(index),
            )
            for index in edge.vertices
        )
        endpoints = [record[0] for record in endpoint_records]
        endpoint_topology_signatures = [record[1] for record in endpoint_records]
        endpoint_tokens = [
            _stable_fingerprint(
                {
                    "plan_id": plan_id,
                    "semantic_batch_key": list(semantic_batch),
                    "coordinate": coordinate,
                    "vertex_topology_signature": topology_signature,
                }
            )
            for coordinate, topology_signature, _ in endpoint_records
        ]
        adjacent_face_signatures = sorted(
            _stable_fingerprint(
                {
                    "role": role,
                    "loop": _canonical_face_loop(mesh, polygon),
                    "membership_id": membership_id,
                }
            )
            for role, polygons, membership_id in (
                ("SOURCE", source_polygons, source_patch_id),
                ("GROOVE", groove_polygons, owner_pipe_id),
            )
            for polygon in polygons
        )
        stable_payload = {
            "plan_id": plan_id,
            "semantic_batch_key": list(semantic_batch),
            "endpoints": endpoints,
            "endpoint_topology_signatures": endpoint_topology_signatures,
            "endpoint_tokens": endpoint_tokens,
            "adjacent_face_signatures": adjacent_face_signatures,
            "owner_pipe_id": owner_pipe_id,
            "source_patch_id": source_patch_id,
            "endpoint_port_tokens": endpoint_port_tokens,
        }
        semantic_base_id = _stable_fingerprint(stable_payload)
        edge_id = semantic_base_id
        record = {
            "edge_id": edge_id,
            "semantic_base_id": semantic_base_id,
            **stable_payload,
            "debug_edge_index": int(edge_index),
        }
        previous = record_by_edge_id.get(edge_id)
        if previous is not None:
            if _canonical_boundary_records((previous,)) != _canonical_boundary_records(
                (record,)
            ):
                raise BatchedChamferError(
                    "BATCH_BOUNDARY_EDGE_ID_COLLISION",
                    "稳定 Boundary Edge ID 出现非等价冲突",
                    {"edge_id": edge_id, "pipe_ids": list(semantic_batch)},
                )
            continue
        record_by_edge_id[edge_id] = record
        records.append(record)
    return tuple(sorted(records, key=lambda record: record["edge_id"]))


# 读取 Preview 创建时冻结的 Pipe 合同，并用正式 Even-Thickness Pipe builder 重建 Mesh。
# source_object/preview_plan/preview_parameters/collection: 当前有效 Preview、live 参数与临时输出 Collection；返回 groups、Pipe Objects、Pipe specs。
def _build_preview_pipe_contract(
    source_object,
    preview_plan,
    preview_parameters,
    collection,
):
    radius = float(preview_parameters["radius"])
    curve_object = owned_preview_curve(source_object)
    raw_contract = (
        curve_object.get(FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG)
        if curve_object is not None
        else None
    )
    try:
        contract = json.loads(raw_contract) if isinstance(raw_contract, str) else None
    except (TypeError, ValueError) as error:
        raise BatchedChamferError(
            "PREVIEW_PIPE_CONTRACT_INVALID",
            "Preview Curve Pipe 合同不是有效 JSON",
            {},
        ) from error
    try:
        contract_radius = float(contract.get("radius", -1.0)) if isinstance(contract, dict) else -1.0
    except (TypeError, ValueError) as error:
        raise BatchedChamferError(
            "PREVIEW_PIPE_CONTRACT_INVALID",
            "Preview Pipe 合同 radius 无效",
            {},
        ) from error
    if (
        not isinstance(contract, dict)
        or contract.get("contract") != "GN_PREVIEW_PIPE_V1"
        or contract.get("plan_id") != preview_plan.plan_id
        or contract.get("source_fingerprint") != source_fingerprint(source_object)
        or abs(contract_radius - radius) > 1.0e-10
        or not isinstance(contract.get("pipes"), list)
    ):
        raise BatchedChamferError(
            "PREVIEW_PIPE_CONTRACT_MISMATCH",
            "Preview Curve 缺少与当前 ChamferPlan 匹配的 Pipe 合同",
            {"curve_object": curve_object.name if curve_object else None},
        )
    strands_by_id = {strand.strand_id: strand for strand in preview_plan.feature_strands}
    groups = []
    for pipe_record in contract["pipes"]:
        try:
            group = {
                "pipe_id": int(pipe_record["pipe_id"]),
                "edge_indices": [int(index) for index in pipe_record["edge_indices"]],
                "vertex_indices": [int(index) for index in pipe_record["vertex_indices"]],
                "points": [Vector(point) for point in pipe_record["points"]],
                "is_cyclic": bool(pipe_record["is_cyclic"]),
                "start_endpoint_class": str(pipe_record["start_endpoint_class"]),
                "end_endpoint_class": str(pipe_record["end_endpoint_class"]),
                "start_extension": float(pipe_record["start_extension"]),
                "end_extension": float(pipe_record["end_extension"]),
            }
            strand = strands_by_id[pipe_record["strand_id"]]
        except (KeyError, TypeError, ValueError) as error:
            raise BatchedChamferError(
                "PREVIEW_PIPE_CONTRACT_INVALID",
                "Preview Pipe 合同字段不完整",
                {},
            ) from error
        group["patch_pair_by_edge"] = [
            tuple(owner_pair) for owner_pair in strand.owner_surface_pairs
        ]
        group["convexity_by_edge"] = [
            int(value) for value in strand.convexity_by_edge
        ]
        group["patch_pair"] = group["patch_pair_by_edge"][0]
        group["convexity"] = group["convexity_by_edge"][0]
        if tuple(pipe_record.get("ordered_edge_keys", ())) != strand.ordered_edge_keys:
            raise BatchedChamferError(
                "PREVIEW_PIPE_CONTRACT_MISMATCH",
                "Preview Pipe 合同与 ChamferPlan strand 不一致",
                {"pipe_id": group["pipe_id"]},
            )
        group["strand"] = strand
        groups.append(group)
    pipe_ids = [group["pipe_id"] for group in groups]
    strand_ids = [group["strand"].strand_id for group in groups]
    if (
        len(groups) != len(preview_plan.feature_strands)
        or len(pipe_ids) != len(set(pipe_ids))
        or len(strand_ids) != len(set(strand_ids))
    ):
        raise BatchedChamferError(
            "PREVIEW_PIPE_MAPPING_INCOMPLETE",
            "Preview Pipe 合同与 FeatureStrand 不是一一对应",
            {"group_count": len(groups), "strand_count": len(preview_plan.feature_strands)},
        )
    pipes = []
    specs = []
    endpoint_tokens_by_pipe_id, _ = _build_strand_endpoint_port_tokens(
        preview_plan,
        groups,
        source_object.data,
    )
    for group in sorted(groups, key=lambda item: item["pipe_id"]):
        pipe = _build_pipe_mesh(
            source_object,
            group,
            radius,
            4,
            collection,
            endpoint_tokens_by_pipe_id.get(group["pipe_id"]),
        )
        risks = _mesh_risk_counts(pipe)
        if risks["non_manifold"] or risks["zero_area"]:
            raise BatchedChamferError(
                "PREVIEW_PIPE_INVALID",
                f"正式 Preview Pipe {group['pipe_id']} 不是有效 closed manifold",
                {
                    "pipe_id": int(group["pipe_id"]),
                    "topology": risks,
                },
            )
        strand = group["strand"]
        specs.append(
            PreviewPipeSpec(
                pipe_id=int(group["pipe_id"]),
                strand_id=strand.strand_id,
                ordered_edge_keys=strand.ordered_edge_keys,
                cyclic=bool(group["is_cyclic"]),
                start_endpoint_class=str(group.get("start_endpoint_class", "CYCLIC")),
                end_endpoint_class=str(group.get("end_endpoint_class", "CYCLIC")),
                start_extension=round(float(group.get("start_extension", 0.0)), 10),
                end_extension=round(float(group.get("end_extension", 0.0)), 10),
                mesh_fingerprint=_mesh_fingerprint(pipe.data),
                vertex_count=len(pipe.data.vertices),
                edge_count=len(pipe.data.edges),
                face_count=len(pipe.data.polygons),
            )
        )
        pipes.append(pipe)
    return groups, tuple(pipes), tuple(specs)


# 验证 Preview Plan RailChains 完整覆盖每条 FeatureStrand 的实际 owner Surface patches。
# preview_plan/groups: immutable ChamferPlan 与正式 Preview groups；覆盖不完整时 fail-closed。
def _validate_plan_rail_coverage(preview_plan, groups):
    rail_patches_by_strand = {}
    for rail in preview_plan.rail_chains:
        if not rail.side.startswith("OWNER_PATCH:"):
            continue
        rail_patches_by_strand.setdefault(rail.owner_strand_id, set()).add(
            int(rail.side.removeprefix("OWNER_PATCH:"))
        )
    missing = []
    for group in groups:
        strand_id = group["strand"].strand_id
        required_patches = {
            int(patch_id)
            for span in _group_patch_pair_spans(group)
            for patch_id in span["patch_pair"]
        }
        missing_patches = sorted(
            required_patches - rail_patches_by_strand.get(strand_id, set())
        )
        if missing_patches:
            missing.append(
                {
                    "pipe_id": int(group["pipe_id"]),
                    "strand_id": strand_id,
                    "missing_patch_ids": missing_patches,
                }
            )
    if missing:
        raise BatchedChamferError(
            "PREVIEW_PLAN_RAIL_COVERAGE_INCOMPLETE",
            "ChamferPlan RailChains 未覆盖正式 Preview FeatureStrand 的实际 Patch spans",
            {"missing_rail_bindings": missing},
        )


# 从正式 Pipe Mesh 计算稳定 overlap graph，owner 使用 Pipe ID 而非临时列表位置。
# pipes: 带 PIPE_ID_TAG 的正式 Pipe Objects；返回 pipe-id pairs。
def _pipe_overlap_pairs(pipes):
    trees = {}
    bounds = {}
    for pipe in pipes:
        pipe_id = int(pipe[PIPE_ID_TAG])
        pipe_bmesh = bmesh.new()
        pipe_bmesh.from_mesh(pipe.data)
        trees[pipe_id] = BVHTree.FromBMesh(pipe_bmesh)
        pipe_bmesh.free()
        bounds[pipe_id] = _pipe_bounds(pipe)
    pairs = []
    pipe_ids = sorted(trees)
    for offset, pipe_id_a in enumerate(pipe_ids):
        for pipe_id_b in pipe_ids[offset + 1 :]:
            if (
                _bounds_overlap(bounds[pipe_id_a], bounds[pipe_id_b])
                and trees[pipe_id_a].overlap(trees[pipe_id_b])
            ):
                pairs.append((pipe_id_a, pipe_id_b))
    return tuple(pairs)


# 把 Pipe-Pipe BVH overlap triangles 投影到两条 FeatureStrand，建立局部 normalized u setback intervals。
# groups/pipes/overlap_pairs/radius: Preview groups、正式 Pipes、overlap graph 与半径；返回 pipe_id→expanded u intervals。
def _pipe_overlap_setback_intervals(groups, pipes, overlap_pairs, radius):
    group_by_pipe_id = {int(group["pipe_id"]): group for group in groups}
    pipe_by_id = {int(pipe[PIPE_ID_TAG]): pipe for pipe in pipes}
    triangles_by_pipe_id = {}
    for pipe_id, pipe in pipe_by_id.items():
        pipe_bmesh = bmesh.new()
        pipe_bmesh.from_mesh(pipe.data)
        bmesh.ops.triangulate(pipe_bmesh, faces=list(pipe_bmesh.faces))
        pipe_bmesh.faces.ensure_lookup_table()
        triangles_by_pipe_id[pipe_id] = (
            pipe_bmesh,
            [tuple(vertex.co.copy() for vertex in face.verts) for face in pipe_bmesh.faces],
            BVHTree.FromBMesh(pipe_bmesh),
        )

    def strand_parameter(group, point):
        points = group["points"]
        segment_count = len(points) if group["is_cyclic"] else len(points) - 1
        lengths = [
            (points[(index + 1) % len(points)] - points[index]).length
            for index in range(segment_count)
        ]
        total = sum(lengths)
        cumulative = 0.0
        best = None
        for index, length in enumerate(lengths):
            start = points[index]
            end = points[(index + 1) % len(points)]
            segment = end - start
            factor = (
                max(0.0, min(1.0, (point - start).dot(segment) / segment.length_squared))
                if segment.length_squared > 1.0e-20
                else 0.0
            )
            closest = start.lerp(end, factor)
            candidate = ((point - closest).length_squared, (cumulative + length * factor) / total)
            if best is None or candidate < best:
                best = candidate
            cumulative += length
        return best[1], total

    # 合并相交或相邻的 normalized u intervals，消除同一 intersection component
    # 在多个 triangle pair 上留下的重复区间。
    def merge_intervals(intervals):
        merged = []
        for start, end in sorted(intervals):
            start = max(0.0, min(1.0, float(start)))
            end = max(0.0, min(1.0, float(end)))
            if end < start:
                start, end = end, start
            if merged and start <= merged[-1][1] + 1.0e-8:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged

    # 对 cyclic FeatureStrand 取最短 circular covering arc，避免 seam 两侧的一处
    # overlap 被错误扩张成 [0, 1]。
    def expanded_component_intervals(group, parameters, strand_length):
        margin_u = min(0.25, radius * 2.0 / max(strand_length, radius))
        if not group["is_cyclic"] or len(parameters) < 2:
            return [[
                max(0.0, min(parameters) - margin_u),
                min(1.0, max(parameters) + margin_u),
            ]]
        ordered = sorted(float(value) % 1.0 for value in parameters)
        gaps = [
            (
                (ordered[(index + 1) % len(ordered)] - ordered[index]) % 1.0,
                index,
            )
            for index in range(len(ordered))
        ]
        _, gap_index = max(gaps)
        arc_start = ordered[(gap_index + 1) % len(ordered)]
        arc_end = ordered[gap_index]
        arc_length = (arc_end - arc_start) % 1.0
        if arc_length + margin_u * 2.0 >= 1.0 - 1.0e-8:
            return [[0.0, 1.0]]
        expanded_start = (arc_start - margin_u) % 1.0
        expanded_end = (arc_end + margin_u) % 1.0
        if expanded_start <= expanded_end:
            return [[expanded_start, expanded_end]]
        return [[0.0, expanded_end], [expanded_start, 1.0]]

    intervals_by_pipe_id = {pipe_id: [] for pipe_id in pipe_by_id}
    try:
        for pipe_id_a, pipe_id_b in overlap_pairs:
            _, triangles_a, tree_a = triangles_by_pipe_id[pipe_id_a]
            _, triangles_b, tree_b = triangles_by_pipe_id[pipe_id_b]
            overlap_records = tree_a.overlap(tree_b)
            adjacency = {}
            for triangle_a, triangle_b in overlap_records:
                node_a = ("A", int(triangle_a))
                node_b = ("B", int(triangle_b))
                adjacency.setdefault(node_a, set()).add(node_b)
                adjacency.setdefault(node_b, set()).add(node_a)
            remaining = set(adjacency)
            components = []
            while remaining:
                component = set()
                stack = [min(remaining)]
                while stack:
                    node = stack.pop()
                    if node in component:
                        continue
                    component.add(node)
                    stack.extend(adjacency.get(node, ()) - component)
                remaining -= component
                components.append(component)
            for component in components:
                for pipe_id, side, triangles, group in (
                    (pipe_id_a, "A", triangles_a, group_by_pipe_id[pipe_id_a]),
                    (pipe_id_b, "B", triangles_b, group_by_pipe_id[pipe_id_b]),
                ):
                    triangle_indices = sorted(
                        index for node_side, index in component if node_side == side
                    )
                    samples = [
                        sum(triangles[index], Vector()) / 3.0
                        for index in triangle_indices
                    ]
                    if not samples:
                        continue
                    parameters_and_lengths = [
                        strand_parameter(group, point) for point in samples
                    ]
                    intervals_by_pipe_id[pipe_id].extend(
                        expanded_component_intervals(
                            group,
                            [item[0] for item in parameters_and_lengths],
                            parameters_and_lengths[0][1],
                        )
                    )
    finally:
        for pipe_bmesh, _, _ in triangles_by_pipe_id.values():
            pipe_bmesh.free()
    return {
        pipe_id: tuple(tuple(interval) for interval in merge_intervals(intervals))
        for pipe_id, intervals in intervals_by_pipe_id.items()
    }


# 对 closed Pipe Mesh 统一 outward winding，避免大半径 multi-component Exact Boolean 将 inside/outside 解释反转。
# pipes: 正式 Preview Pipe Objects；原地规范负 signed volume 的 Face winding，并返回翻转 Pipe IDs。
def _normalize_pipe_winding(pipes):
    flipped_pipe_ids = []
    for pipe in pipes:
        pipe_bmesh = bmesh.new()
        pipe_bmesh.from_mesh(pipe.data)
        signed_volume = pipe_bmesh.calc_volume(signed=True)
        if signed_volume < 0.0:
            bmesh.ops.reverse_faces(pipe_bmesh, faces=list(pipe_bmesh.faces))
            pipe_bmesh.to_mesh(pipe.data)
            pipe.data.update()
            flipped_pipe_ids.append(int(pipe[PIPE_ID_TAG]))
        pipe_bmesh.free()
    return tuple(sorted(flipped_pipe_ids))


# 把现有 greedy coloring 提升为稳定 Pipe ID 合同，并 fail-closed 验证 complete/independent。
# pipe_ids/overlap_pairs: 全部 Pipe IDs 与无向冲突边；返回 color batches。
def color_pipe_overlap_graph(pipe_ids, overlap_pairs):
    raw_pipe_ids = tuple(pipe_ids)
    normalized_pipe_ids = tuple(sorted({int(pipe_id) for pipe_id in raw_pipe_ids}))
    if len(normalized_pipe_ids) != len(raw_pipe_ids):
        raise ValueError("Pipe IDs must be unique")
    index_by_pipe_id = {
        pipe_id: index for index, pipe_id in enumerate(normalized_pipe_ids)
    }
    normalized_pairs = set()
    for raw_a, raw_b in overlap_pairs:
        pipe_id_a = int(raw_a)
        pipe_id_b = int(raw_b)
        if pipe_id_a == pipe_id_b:
            raise ValueError("Pipe overlap graph cannot contain self edges")
        if pipe_id_a not in index_by_pipe_id or pipe_id_b not in index_by_pipe_id:
            raise ValueError("Pipe overlap graph references an unknown Pipe ID")
        normalized_pairs.add(tuple(sorted((pipe_id_a, pipe_id_b))))
    index_pairs = {
        tuple(index_by_pipe_id[pipe_id] for pipe_id in pair)
        for pair in normalized_pairs
    }
    index_batches = _non_overlapping_pipe_batches(
        len(normalized_pipe_ids),
        index_pairs,
    )
    batches = tuple(
        tuple(sorted(normalized_pipe_ids[index] for index in batch))
        for batch in index_batches
    )
    flattened = [pipe_id for batch in batches for pipe_id in batch]
    if sorted(flattened) != list(normalized_pipe_ids) or len(flattened) != len(set(flattened)):
        raise RuntimeError("Pipe coloring does not consume every Pipe exactly once")
    if any(
        tuple(sorted((pipe_id_a, pipe_id_b))) in normalized_pairs
        for batch in batches
        for offset, pipe_id_a in enumerate(batch)
        for pipe_id_b in batch[offset + 1 :]
    ):
        raise RuntimeError("Pipe coloring produced an overlapping batch")
    return batches


# 计算不依赖 batch 执行方向的 graph/cut probe fingerprint。
# pipe_specs/overlap_pairs/color_batches: Preview Pipe 合同与确定 coloring；返回稳定 SHA-256。
def batch_order_invariance_fingerprint(pipe_specs, overlap_pairs, color_batches):
    semantic_batches = sorted(
        tuple(sorted(batch)) for batch in color_batches
    )
    payload = {
        "pipe_fingerprints": {
            str(spec.pipe_id): spec.mesh_fingerprint
            for spec in sorted(pipe_specs, key=lambda item: item.pipe_id)
        },
        "overlap_pairs": sorted(tuple(sorted(pair)) for pair in overlap_pairs),
        "semantic_batches": semantic_batches,
    }
    forward = _stable_fingerprint(payload)
    reverse_payload = {
        **payload,
        "semantic_batches": sorted(
            tuple(sorted(batch)) for batch in reversed(color_batches)
        ),
    }
    reverse = _stable_fingerprint(reverse_payload)
    if forward != reverse:
        raise RuntimeError("Canonical batch signature depends on execution order")
    return forward


# 在同一个 source duplicate 上依次 Apply 每个互斥 Cutter batch，并保留每步 canonical topology 签名。
# source_object/pipes/color_batches/probe_collection/order_label: Preview source、正式 Pipes、批次顺序、临时 Collection 与方向标签；返回真实 Cut 记录。
def _run_exact_boolean_cut_order(
    source_object,
    pipes,
    color_batches,
    probe_collection,
    order_label,
):
    pipes_by_id = {int(pipe[PIPE_ID_TAG]): pipe for pipe in pipes}
    working_mesh = source_object.data.copy()
    working_object = source_object.copy()
    working_object.data = working_mesh
    working_object.name = f"{source_object.name}_BatchedCut_{order_label}"
    for modifier in tuple(working_object.modifiers):
        working_object.modifiers.remove(modifier)
    probe_collection.objects.link(working_object)
    records = []
    try:
        for batch_index, batch in enumerate(color_batches):
            try:
                batch_pipes = [pipes_by_id[int(pipe_id)] for pipe_id in batch]
            except KeyError as error:
                raise BatchedChamferError(
                    "BATCH_PIPE_MISSING",
                    "真实 Cut probe 引用了不存在的 Pipe",
                    {"batch": list(batch)},
                ) from error
            cutter = _build_joined_cutter_mesh(
                batch_pipes,
                source_object,
                probe_collection,
                f"{order_label}_{batch_index}",
            )
            modifier = working_object.modifiers.new(
                f"HST Batched Cut {order_label} {batch_index}",
                type="BOOLEAN",
            )
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.use_self = True
            modifier.use_hole_tolerant = True
            modifier.operand_type = "OBJECT"
            modifier.object = cutter
            with bpy.context.temp_override(
                object=working_object,
                active_object=working_object,
                selected_objects=[working_object],
                selected_editable_objects=[working_object],
            ):
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            if not working_object.data.vertices or not working_object.data.polygons:
                raise BatchedChamferError(
                    "BATCH_CUT_EMPTY",
                    "真实 Cut probe 生成了空 Mesh",
                    {
                        "order": order_label,
                        "batch_index": batch_index,
                        "pipe_ids": list(batch),
                    },
                )
            records.append(
                {
                    "batch_index": batch_index,
                    "pipe_ids": list(batch),
                    "cut_signature": _mesh_fingerprint(working_object.data),
                    "vertex_count": len(working_object.data.vertices),
                    "edge_count": len(working_object.data.edges),
                    "face_count": len(working_object.data.polygons),
                }
            )
        return {
            "order": order_label,
            "cut_batch_count": len(records),
            "records": records,
            "final_cut_signature": _mesh_fingerprint(working_object.data),
        }
    finally:
        if bpy.data.objects.get(working_object.name) == working_object:
            bpy.data.objects.remove(working_object, do_unlink=True)
        if (
            working_mesh.users == 0
            and bpy.data.meshes.get(working_mesh.name) == working_mesh
        ):
            bpy.data.meshes.remove(working_mesh)


# 从同一份 source 为每个 batch 生成独立 Cut staging Mesh，供后续 Rail/regular-core ledger 消费。
# source_object/pipes/color_batches/probe_collection: Preview source、正式 Pipes、coloring 与临时 Collection；返回与 batch 顺序无关的 staging 诊断。
def _run_independent_batch_cut_probe(
    source_object,
    pipes,
    color_batches,
    probe_collection,
    plan_id,
    execution_order,
):
    pipes_by_id = {int(pipe[PIPE_ID_TAG]): pipe for pipe in pipes}
    _synchronize_cutter_membership_schema(pipes)
    records = []
    semantic_batches = tuple(tuple(sorted(batch)) for batch in color_batches)
    ordered_batches = (
        semantic_batches
        if execution_order == "FORWARD"
        else tuple(reversed(semantic_batches))
    )
    for semantic_batch in ordered_batches:
        working_mesh = source_object.data.copy()
        working_object = source_object.copy()
        working_object.data = working_mesh
        working_object.name = f"{source_object.name}_BatchedIndependentCut"
        for modifier in tuple(working_object.modifiers):
            working_object.modifiers.remove(modifier)
        probe_collection.objects.link(working_object)
        try:
            batch_pipes = [pipes_by_id[pipe_id] for pipe_id in semantic_batch]
            source_patch_ids = _source_face_patch_ids(source_object)
            _mark_original_faces(working_object, source_patch_ids)
            _initialize_source_membership_schema(
                working_object.data,
                batch_pipes,
                source_patch_ids,
            )
            cutter = _build_joined_cutter_mesh(
                batch_pipes,
                source_object,
                probe_collection,
                "INDEPENDENT_" + "_".join(str(pipe_id) for pipe_id in semantic_batch),
            )
            _initialize_boundary_witness_schema(
                working_object.data,
                (cutter,),
                source_patch_ids,
            )
            _seed_cutter_edge_owner_witnesses((cutter,))
            modifier = working_object.modifiers.new(
                "HST Batched Independent Cut",
                type="BOOLEAN",
            )
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.use_self = True
            modifier.use_hole_tolerant = True
            modifier.operand_type = "OBJECT"
            modifier.object = cutter
            with bpy.context.temp_override(
                object=working_object,
                active_object=working_object,
                selected_objects=[working_object],
                selected_editable_objects=[working_object],
            ):
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            boundary_witnesses = _mark_boolean_boundary_witnesses(working_object)
            if boundary_witnesses["conflicting_edge_indices"]:
                raise BatchedChamferError(
                    "BATCH_BOUNDARY_OWNER_CONFLICT",
                    "Independent staging Boundary 存在多 Pipe/Patch owner",
                    {
                        "pipe_ids": list(semantic_batch),
                        **boundary_witnesses,
                    },
                )
            boundary_records = _extract_staging_boundary_records(
                working_object,
                plan_id,
                semantic_batch,
                boundary_witnesses["marked_edge_indices"],
            )
            if not working_object.data.vertices or not working_object.data.polygons:
                pipe_diagnostics = []
                for pipe in batch_pipes:
                    pipe_bmesh = bmesh.new()
                    pipe_bmesh.from_mesh(pipe.data)
                    signed_volume = pipe_bmesh.calc_volume(signed=True)
                    pipe_bmesh.free()
                    minimum, maximum = _pipe_bounds(pipe)
                    pipe_diagnostics.append(
                        {
                            "pipe_id": int(pipe[PIPE_ID_TAG]),
                            "signed_volume": round(float(signed_volume), 10),
                            "minimum": [round(float(value), 8) for value in minimum],
                            "maximum": [round(float(value), 8) for value in maximum],
                            "topology": _mesh_risk_counts(pipe),
                        }
                    )
                raise BatchedChamferError(
                    "BATCH_CUT_EMPTY",
                    "独立 Cut staging 生成了空 Mesh",
                    {
                        "pipe_ids": list(semantic_batch),
                        "pipe_diagnostics": pipe_diagnostics,
                    },
                )
            records.append(
                {
                    "pipe_ids": list(semantic_batch),
                    "cut_signature": _mesh_fingerprint(working_object.data),
                    "vertex_count": len(working_object.data.vertices),
                    "edge_count": len(working_object.data.edges),
                    "face_count": len(working_object.data.polygons),
                    "boundary_witnesses": boundary_witnesses,
                    "boundary_records": _canonical_boundary_records(boundary_records),
                }
            )
        finally:
            if bpy.data.objects.get(working_object.name) == working_object:
                bpy.data.objects.remove(working_object, do_unlink=True)
            if (
                working_mesh.users == 0
                and bpy.data.meshes.get(working_mesh.name) == working_mesh
            ):
                bpy.data.meshes.remove(working_mesh)
    canonical_records = tuple(sorted(records, key=lambda record: record["pipe_ids"]))
    return {
        "execution_order": execution_order,
        "cut_signature": _stable_fingerprint(canonical_records),
        "records": canonical_records,
    }


# 在真实 staging Boundary records 上校验 Pipe→Strand→Plan Rail 绑定，并建立未消费初始 ledger。
# preview_plan/pipe_specs/staging_records: 当前 Plan、Preview Pipe 合同和 independent staging 记录；返回完整 Boundary universe ledger。
def _build_staging_boundary_ledger(preview_plan, pipe_specs, staging_records):
    strand_id_by_pipe_id = {
        int(spec.pipe_id): spec.strand_id
        for spec in pipe_specs
    }
    rail_by_owner_patch = {
        (rail.owner_strand_id, int(rail.side.removeprefix("OWNER_PATCH:"))): rail
        for rail in preview_plan.rail_chains
        if rail.side.startswith("OWNER_PATCH:")
    }
    ledger = []
    edge_ids = set()
    for staging_record in staging_records:
        semantic_batch = tuple(int(value) for value in staging_record["pipe_ids"])
        for boundary in staging_record["boundary_records"]:
            edge_id = boundary["edge_id"]
            if edge_id in edge_ids:
                raise BatchedChamferError(
                    "BATCH_BOUNDARY_EDGE_DUPLICATE",
                    "不同 independent staging 重复声明同一稳定 Boundary Edge",
                    {"edge_id": edge_id},
                )
            edge_ids.add(edge_id)
            pipe_id = int(boundary["owner_pipe_id"])
            patch_id = int(boundary["source_patch_id"])
            strand_id = strand_id_by_pipe_id.get(pipe_id)
            rail = rail_by_owner_patch.get((strand_id, patch_id))
            if strand_id is None:
                raise BatchedChamferError(
                    "BATCH_BOUNDARY_PLAN_BINDING_MISSING",
                    "真实 Boundary Edge 无法绑定 Preview Plan RailChain",
                    {
                        "edge_id": edge_id,
                        "pipe_id": pipe_id,
                        "strand_id": strand_id,
                        "patch_id": patch_id,
                    },
                )
            if rail is None:
                rail_id = f"rail:{strand_id}:patch:{patch_id}:OUTSIDE_PLAN"
                ledger.append(
                    {
                        "edge_id": edge_id,
                        "semantic_batch_key": list(semantic_batch),
                        "pipe_id": pipe_id,
                        "strand_id": strand_id,
                        "source_patch_id": patch_id,
                        "rail_id": rail_id,
                        "endpoints": boundary["endpoints"],
                        "endpoint_tokens": boundary["endpoint_tokens"],
                        "endpoint_topology_signatures": boundary.get(
                            "endpoint_topology_signatures",
                            (),
                        ),
                        "adjacent_face_signatures": boundary.get(
                            "adjacent_face_signatures",
                            (),
                        ),
                        "endpoint_port_tokens": boundary.get(
                            "endpoint_port_tokens",
                            (),
                        ),
                        "classification": "UNCLASSIFIED",
                        "consumer_id": None,
                        "outside_plan_owner_patch": True,
                    }
                )
                continue
            ledger.append(
                {
                    "edge_id": edge_id,
                    "semantic_batch_key": list(semantic_batch),
                    "pipe_id": pipe_id,
                    "strand_id": strand_id,
                    "source_patch_id": patch_id,
                    "rail_id": rail.rail_id,
                    "endpoints": boundary["endpoints"],
                    "endpoint_tokens": boundary["endpoint_tokens"],
                    "endpoint_topology_signatures": boundary.get(
                        "endpoint_topology_signatures",
                        (),
                    ),
                    "adjacent_face_signatures": boundary.get(
                        "adjacent_face_signatures",
                        (),
                    ),
                    "endpoint_port_tokens": boundary.get(
                        "endpoint_port_tokens",
                        (),
                    ),
                    "classification": "UNCLASSIFIED",
                    "consumer_id": None,
                }
            )
    endpoint_degree_by_rail_token = {}
    for entry in ledger:
        for endpoint_token in entry["endpoint_tokens"]:
            key = (entry["rail_id"], endpoint_token)
            endpoint_degree_by_rail_token[key] = (
                endpoint_degree_by_rail_token.get(key, 0) + 1
            )
    for entry in ledger:
        entry["endpoint_degrees"] = [
            endpoint_degree_by_rail_token[(entry["rail_id"], endpoint_token)]
            for endpoint_token in entry["endpoint_tokens"]
        ]
    return tuple(sorted(ledger, key=lambda entry: entry["edge_id"]))


# 把同一 Pipe/Patch 的真实 Boundary Edge 拆为有序 open/cyclic chains，保留稳定 Edge identity。
# ledger_entries: 已绑定 Plan RailChain 的真实 Boundary ledger 子集；返回有序 chain records。
def _ordered_stable_boundary_chains(ledger_entries):
    entries_by_id = {entry["edge_id"]: entry for entry in ledger_entries}
    edge_ids_by_endpoint = {}
    coordinate_by_endpoint = {}
    for entry in ledger_entries:
        for endpoint, coordinate in zip(
            entry["endpoint_tokens"],
            entry["endpoints"],
        ):
            edge_ids_by_endpoint.setdefault(endpoint, set()).add(entry["edge_id"])
            coordinate_by_endpoint[endpoint] = tuple(coordinate)
    special_endpoints = {
        endpoint
        for endpoint, edge_ids in edge_ids_by_endpoint.items()
        if len(edge_ids) != 2
    }
    remaining = set(entries_by_id)
    chains = []
    for start in sorted(special_endpoints):
        for seed_edge_id in sorted(edge_ids_by_endpoint[start] & remaining):
            edge_ids = []
            coordinates = [coordinate_by_endpoint[start]]
            endpoint_tokens = [start]
            current = start
            edge_id = seed_edge_id
            while edge_id in remaining:
                remaining.remove(edge_id)
                edge_ids.append(edge_id)
                endpoints = entries_by_id[edge_id]["endpoint_tokens"]
                following = endpoints[1] if endpoints[0] == current else endpoints[0]
                coordinates.append(coordinate_by_endpoint[following])
                endpoint_tokens.append(following)
                current = following
                if current in special_endpoints:
                    break
                candidates = sorted(edge_ids_by_endpoint[current] & remaining)
                if len(candidates) != 1:
                    break
                edge_id = candidates[0]
            if edge_ids:
                chains.append(
                    {
                        "edge_ids": edge_ids,
                        "coordinates": coordinates,
                        "endpoint_tokens": endpoint_tokens,
                        "is_cyclic": False,
                        "branch_setback": True,
                    }
                )
    remaining = set(entries_by_id)
    consumed_edge_ids = {
        edge_id for chain in chains for edge_id in chain["edge_ids"]
    }
    remaining -= consumed_edge_ids
    while remaining:
        component = set()
        stack = [min(remaining)]
        while stack:
            edge_id = stack.pop()
            if edge_id in component:
                continue
            component.add(edge_id)
            for endpoint in entries_by_id[edge_id]["endpoint_tokens"]:
                stack.extend(edge_ids_by_endpoint[endpoint] - component)
        remaining -= component
        component_degrees = {
            endpoint: len(edge_ids & component)
            for endpoint, edge_ids in edge_ids_by_endpoint.items()
            if edge_ids & component
        }
        open_endpoints = sorted(
            endpoint for endpoint, degree in component_degrees.items() if degree == 1
        )
        if len(open_endpoints) not in {0, 2}:
            raise BatchedChamferError(
                "BATCH_BOUNDARY_CHAIN_INVALID",
                "Boundary component 不是单一 open/cyclic chain",
                {
                    "edge_count": len(component),
                    "open_endpoint_count": len(open_endpoints),
                },
            )
        cyclic = not open_endpoints
        start = open_endpoints[0] if open_endpoints else min(component_degrees)
        ordered_edge_ids = []
        ordered_coordinates = [coordinate_by_endpoint[start]]
        ordered_endpoint_tokens = [start]
        current = start
        previous_edge_id = None
        while len(ordered_edge_ids) < len(component):
            candidates = sorted(
                (edge_ids_by_endpoint[current] & component)
                - ({previous_edge_id} if previous_edge_id else set())
                - set(ordered_edge_ids)
            )
            if not candidates:
                break
            edge_id = candidates[0]
            endpoints = entries_by_id[edge_id]["endpoint_tokens"]
            following = endpoints[1] if endpoints[0] == current else endpoints[0]
            ordered_edge_ids.append(edge_id)
            if not cyclic or following != start:
                ordered_coordinates.append(coordinate_by_endpoint[following])
                ordered_endpoint_tokens.append(following)
            previous_edge_id = edge_id
            current = following
        if len(ordered_edge_ids) != len(component):
            raise BatchedChamferError(
                "BATCH_BOUNDARY_CHAIN_DISCONNECTED",
                "Boundary component 无法形成连续稳定序列",
                {"component_edge_count": len(component)},
            )
        chains.append(
            {
                "edge_ids": ordered_edge_ids,
                "coordinates": ordered_coordinates,
                "endpoint_tokens": ordered_endpoint_tokens,
                "is_cyclic": cyclic,
            }
        )
    for chain in chains:
        chain_entries = [entries_by_id[edge_id] for edge_id in chain["edge_ids"]]
        for key in ("rail_id", "strand_id", "source_patch_id", "pipe_id"):
            values = {entry[key] for entry in chain_entries}
            if len(values) != 1:
                raise BatchedChamferError(
                    "BATCH_BOUNDARY_CHAIN_OWNER_MISMATCH",
                    "Boundary chain 混入多个 provenance owner",
                    {"key": key, "values": sorted(values)},
                )
            chain[key] = next(iter(values))
        chain["endpoint_port_tokens_by_edge"] = {
            entry["edge_id"]: list(entry.get("endpoint_port_tokens", ()))
            for entry in chain_entries
            if entry.get("endpoint_port_tokens")
        }
        chain["junction_endpoint_tokens_by_edge"] = {
            entry["edge_id"]: [
                endpoint_token
                for endpoint_token, degree in zip(
                    entry["endpoint_tokens"],
                    entry.get("endpoint_degrees", ()),
                )
                if int(degree) != 2
            ]
            for entry in chain_entries
            if any(int(degree) != 2 for degree in entry.get("endpoint_degrees", ()))
        }
        chain["endpoint_degrees_by_edge"] = {
            entry["edge_id"]: list(entry.get("endpoint_degrees", ()))
            for entry in chain_entries
        }
        chain["endpoint_topology_signatures_by_edge"] = {
            entry["edge_id"]: list(
                entry.get("endpoint_topology_signatures", ())
            )
            for entry in chain_entries
            if entry.get("endpoint_topology_signatures")
        }
    return tuple(
        sorted(
            chains,
            key=lambda chain: (chain["is_cyclic"], chain["edge_ids"]),
        )
    )


# 为每个 Plan RailChain 从真实 staging ledger 建立有序 Boundary chains。
# boundary_ledger: 尚未分类但 owner 已验证的完整 universe；返回 rail_id→chains。
def _build_staging_rail_chains(boundary_ledger):
    entries_by_rail = {}
    for entry in boundary_ledger:
        entries_by_rail.setdefault(entry["rail_id"], []).append(entry)
    return {
        rail_id: _ordered_stable_boundary_chains(entries)
        for rail_id, entries in sorted(entries_by_rail.items())
    }


# 对 cyclic rail 选择方向与 seam，使其与另一侧 rail 的 normalized correspondence 成本最小。
# left_chain/right_chain: 同一 Plan StripCorrespondence 的两个 cyclic chains；返回对齐后的右侧 chain。
def _align_cyclic_stable_chain(left_chain, right_chain):
    aligned_coordinates, _ = _aligned_rail_correspondence(
        {
            "coordinates": [Vector(point) for point in left_chain["coordinates"]],
            "is_cyclic": True,
        },
        {
            "coordinates": [Vector(point) for point in right_chain["coordinates"]],
            "is_cyclic": True,
        },
    )
    aligned_coordinates = [
        tuple(round(float(value), 8) for value in point)
        for point in aligned_coordinates
    ]
    edge_id_by_directed_endpoints = {}
    for edge_id, start, end in zip(
        right_chain["edge_ids"],
        right_chain["coordinates"],
        right_chain["coordinates"][1:] + right_chain["coordinates"][:1],
    ):
        edge_id_by_directed_endpoints[(tuple(start), tuple(end))] = edge_id
        edge_id_by_directed_endpoints[(tuple(end), tuple(start))] = edge_id
    aligned_edge_ids = [
        edge_id_by_directed_endpoints[(start, end)]
        for start, end in zip(
            aligned_coordinates,
            aligned_coordinates[1:] + aligned_coordinates[:1],
        )
    ]
    endpoint_token_by_coordinate = {
        tuple(coordinate): endpoint_token
        for coordinate, endpoint_token in zip(
            right_chain["coordinates"],
            right_chain.get("endpoint_tokens", ()),
        )
    }
    return {
        **right_chain,
        "edge_ids": aligned_edge_ids,
        "coordinates": aligned_coordinates,
        "endpoint_tokens": [
            endpoint_token_by_coordinate[coordinate]
            for coordinate in aligned_coordinates
        ],
        "is_cyclic": True,
    }


# 返回点到 open/cyclic polyline 的最短距离。
# point/coordinates/cyclic: 查询点、polyline 坐标与闭合标记；返回非负距离。
def _point_to_polyline_distance(point, coordinates, cyclic):
    point = Vector(point)
    coordinates = [Vector(value) for value in coordinates]
    segment_count = len(coordinates) if cyclic else len(coordinates) - 1
    distances = []
    for index in range(segment_count):
        start = coordinates[index]
        end = coordinates[(index + 1) % len(coordinates)]
        segment = end - start
        if segment.length_squared <= 1.0e-20:
            distances.append((point - start).length)
            continue
        factor = max(0.0, min(1.0, (point - start).dot(segment) / segment.length_squared))
        distances.append((point - start.lerp(end, factor)).length)
    return min(distances, default=float("inf"))


# 从 cyclic Boundary chain 提取与对侧 rail 满足 Chamfer width 的连续 open runs。
# chain/opposite_chain/radius: 当前真实 rail、对侧 rail 与 Chamfer radius；返回保留稳定 Edge IDs 的 runs。
def _cyclic_width_core_runs(chain, opposite_chain, radius):
    coordinates = [Vector(point) for point in chain["coordinates"]]
    opposite_coordinates = [Vector(point) for point in opposite_chain["coordinates"]]
    expected_width = radius * (2.0 ** 0.5)
    tolerance = max(radius * 0.60, 1.0e-5)
    owned = []
    for index in range(len(chain["edge_ids"])):
        midpoint = (
            coordinates[index]
            + coordinates[(index + 1) % len(coordinates)]
        ) * 0.5
        distance = _point_to_polyline_distance(
            midpoint,
            opposite_coordinates,
            True,
        )
        owned.append(abs(distance - expected_width) <= tolerance)
    if not any(owned):
        return ()
    if all(owned):
        return (chain,)
    first_unowned = owned.index(False)
    offset = first_unowned + 1
    edge_ids = chain["edge_ids"][offset:] + chain["edge_ids"][:offset]
    rotated_coordinates = chain["coordinates"][offset:] + chain["coordinates"][:offset]
    rotated_owned = owned[offset:] + owned[:offset]
    runs = []
    run_edge_ids = []
    run_coordinates = []
    for edge_id, start, is_owned in zip(
        edge_ids,
        rotated_coordinates,
        rotated_owned,
    ):
        if is_owned:
            if not run_edge_ids:
                run_coordinates = [start]
            run_edge_ids.append(edge_id)
            edge_index = chain["edge_ids"].index(edge_id)
            run_coordinates.append(
                chain["coordinates"][(edge_index + 1) % len(chain["coordinates"])]
            )
        elif run_edge_ids:
            runs.append(
                {
                    "edge_ids": run_edge_ids,
                    "coordinates": run_coordinates,
                    "is_cyclic": False,
                }
            )
            run_edge_ids = []
            run_coordinates = []
    if run_edge_ids:
        runs.append(
            {
                "edge_ids": run_edge_ids,
                "coordinates": run_coordinates,
                "is_cyclic": False,
            }
        )
    return tuple(runs)


# 为有序 Boundary chain 的每个点枚举局部可辨识的 FeatureStrand 投影候选。
# coordinates/feature_points/lengths/total_length/cyclic_chain/allowed_segment_indices: Boundary 点列、FeatureStrand 点列与弧长信息、Boundary 是否闭合、Patch owner 允许的 segment；返回逐点候选。
def _ordered_strand_projection_candidates(
    coordinates,
    feature_points,
    lengths,
    total_length,
    cyclic_chain,
    allowed_segment_indices=None,
):
    coordinate_vectors = [Vector(point) for point in coordinates]
    cumulative_lengths = [0.0]
    for length in lengths:
        cumulative_lengths.append(cumulative_lengths[-1] + length)
    candidate_layers = []
    for point_index, point in enumerate(coordinate_vectors):
        projections = []
        for segment_index, length in enumerate(lengths):
            if (
                allowed_segment_indices is not None
                and segment_index not in allowed_segment_indices
            ):
                continue
            start = feature_points[segment_index]
            end = feature_points[(segment_index + 1) % len(feature_points)]
            segment = end - start
            factor = (
                max(0.0, min(1.0, (point - start).dot(segment) / segment.length_squared))
                if segment.length_squared > 1.0e-20
                else 0.0
            )
            closest = start.lerp(end, factor)
            projections.append(
                {
                    "distance_squared": (point - closest).length_squared,
                    "u": (
                        cumulative_lengths[segment_index] + length * factor
                    )
                    / total_length,
                    "segment_index": segment_index,
                }
            )
        nearest_distance = min(
            projection["distance_squared"] for projection in projections
        ) ** 0.5
        adjacent_lengths = []
        if point_index:
            adjacent_lengths.append(
                (point - coordinate_vectors[point_index - 1]).length
            )
        elif cyclic_chain and len(coordinate_vectors) > 1:
            adjacent_lengths.append((point - coordinate_vectors[-1]).length)
        if point_index + 1 < len(coordinate_vectors):
            adjacent_lengths.append(
                (coordinate_vectors[point_index + 1] - point).length
            )
        elif cyclic_chain and len(coordinate_vectors) > 1:
            adjacent_lengths.append((coordinate_vectors[0] - point).length)
        local_resolution = min(adjacent_lengths, default=0.0)
        maximum_distance = nearest_distance + local_resolution + 1.0e-10
        local_candidates = [
            projection
            for projection in projections
            if projection["distance_squared"]
            <= maximum_distance * maximum_distance
        ]
        unique_by_u = {}
        for projection in sorted(
            local_candidates,
            key=lambda item: (
                item["distance_squared"],
                item["segment_index"],
            ),
        ):
            key = round(float(projection["u"]), 12)
            unique_by_u.setdefault(key, projection)
        candidate_layers.append(
            tuple(
                sorted(
                    unique_by_u.values(),
                    key=lambda item: (
                        item["u"],
                        item["distance_squared"],
                        item["segment_index"],
                    ),
                )
            )
        )
    return tuple(candidate_layers)


# 选择 ordered projection 的最小回退路径；有零回退解时不得保留局部 nearest 造成的假折返。
# candidate_layers/strand_cyclic/chain_cyclic: 逐点投影候选、FeatureStrand 与 Boundary 闭合标记；返回路径 cost/u/segment 或 None。
def _minimum_backtrack_projection_path(
    candidate_layers,
    strand_cyclic,
    chain_cyclic,
):
    if not candidate_layers or any(not layer for layer in candidate_layers):
        return None

    def equivalent(left, right):
        return len(left["u_values"]) == len(right["u_values"]) and all(
            abs(left_u - right_u) <= 1.0e-9
            for left_u, right_u in zip(left["u_values"], right["u_values"])
        )

    def retain_unique(paths, limit=2):
        retained = []
        for path in sorted(
            paths,
            key=lambda item: (
                item["backtrack"],
                item["cost"],
                item["switch_count"],
                item["segment_indices"],
            ),
        ):
            if any(equivalent(path, current) for current in retained):
                continue
            retained.append(path)
            if len(retained) >= limit:
                break
        return retained

    states = {}
    for candidate_index, candidate in enumerate(candidate_layers[0]):
        path = {
            "backtrack": 0.0,
            "cost": float(candidate["distance_squared"]),
            "switch_count": 0,
            "segment_indices": (int(candidate["segment_index"]),),
            "u_values": (float(candidate["u"]),),
            "first_candidate_index": candidate_index,
        }
        states[(candidate_index, round(float(candidate["u"]), 12))] = [path]
    for layer in candidate_layers[1:]:
        next_states = {}
        for candidate_index, candidate in enumerate(layer):
            candidate_paths = []
            raw_u = float(candidate["u"])
            for paths in states.values():
                for previous in paths:
                    previous_u = previous["u_values"][-1]
                    lifted_values = (raw_u,)
                    if strand_cyclic:
                        center = round(previous_u - raw_u)
                        lift_options = [
                            raw_u + offset
                            for offset in range(center - 1, center + 2)
                        ]
                        minimum_delta = min(
                            abs(value - previous_u) for value in lift_options
                        )
                        lifted_values = tuple(
                            value
                            for value in lift_options
                            if abs(abs(value - previous_u) - minimum_delta)
                            <= 1.0e-12
                        )
                    for lifted_u in lifted_values:
                        candidate_paths.append(
                            {
                                "backtrack": previous["backtrack"]
                                + max(0.0, previous_u - lifted_u),
                                "cost": previous["cost"]
                                + float(candidate["distance_squared"]),
                                "switch_count": previous["switch_count"]
                                + (
                                    previous["segment_indices"][-1]
                                    != int(candidate["segment_index"])
                                ),
                                "segment_indices": (
                                    *previous["segment_indices"],
                                    int(candidate["segment_index"]),
                                ),
                                "u_values": (*previous["u_values"], lifted_u),
                                "first_candidate_index": previous[
                                    "first_candidate_index"
                                ],
                            }
                        )
            for path in retain_unique(candidate_paths):
                key = (
                    candidate_index,
                    round(path["u_values"][-1], 12),
                    path["first_candidate_index"] if chain_cyclic else None,
                )
                next_states[key] = retain_unique(
                    [*next_states.get(key, ()), path]
                )
        states = next_states
        if not states:
            return None
    completed = [path for paths in states.values() for path in paths]
    candidates = retain_unique(completed)
    if not candidates:
        return None
    best = candidates[0]
    return best


# 返回 Boundary chain 每个有序点在 FeatureStrand 上的 normalized u；cyclic 时解开 seam。
# chain/strand: 当前真实 Boundary chain 与权威 Plan FeatureStrand；返回定向 chain 与逐点连续 u。
def _chain_strand_parameters(chain, strand):
    feature_points = [
        Vector(tuple(float(value) for value in key.split("#", 1)[0].split(",")))
        for key in strand.ordered_vertex_keys
    ]
    segment_count = len(feature_points) if strand.cyclic else len(feature_points) - 1
    lengths = [
        (feature_points[(index + 1) % len(feature_points)] - feature_points[index]).length
        for index in range(segment_count)
    ]
    total_length = sum(lengths)

    if total_length <= 1.0e-12:
        return chain, [0.0 for _ in chain["coordinates"]]
    source_patch_id = chain.get("source_patch_id")
    allowed_segment_indices = None
    if source_patch_id is not None:
        allowed_segment_indices = {
            segment_index
            for segment_index, patch_pair in enumerate(
                strand.owner_surface_pairs
            )
            if int(source_patch_id) in patch_pair
        }
        if not allowed_segment_indices:
            allowed_segment_indices = None
    forward_layers = _ordered_strand_projection_candidates(
        chain["coordinates"],
        feature_points,
        lengths,
        total_length,
        bool(chain.get("is_cyclic")),
        allowed_segment_indices,
    )
    reverse_layers = _ordered_strand_projection_candidates(
        list(reversed(chain["coordinates"])),
        feature_points,
        lengths,
        total_length,
        bool(chain.get("is_cyclic")),
        allowed_segment_indices,
    )
    forward_path = _minimum_backtrack_projection_path(
        forward_layers,
        bool(strand.cyclic),
        bool(chain.get("is_cyclic")),
    )
    reverse_path = _minimum_backtrack_projection_path(
        reverse_layers,
        bool(strand.cyclic),
        bool(chain.get("is_cyclic")),
    )
    paths = [
        (False, forward_path),
        (True, reverse_path),
    ]
    paths = [(reverse, path) for reverse, path in paths if path is not None]
    if not paths:
        raise BatchedChamferError(
            "NON_MONOTONIC_STRAND_PROJECTION",
            "Boundary chain 无法唯一映射为 FeatureStrand 单调路径",
            {"edge_ids": list(chain["edge_ids"])},
        )
    paths.sort(
        key=lambda item: (
            item[1]["backtrack"],
            item[1]["cost"],
            item[1]["switch_count"],
            item[1]["segment_indices"],
            tuple(round(float(value), 12) for value in item[1]["u_values"]),
            item[0],
        )
    )
    reverse, selected_path = paths[0]
    if len(paths) > 1 and len(chain["edge_ids"]) > 1:
        average_cost = selected_path["cost"] / max(
            1,
            len(selected_path["u_values"]),
        )
        ambiguity_tolerance = max(1.0e-16, average_cost * 1.0e-12)
        reverse_is_same_open_chain = (
            not chain.get("is_cyclic")
            and paths[0][1]["u_values"]
            and paths[1][1]["u_values"]
            and all(
                abs(left_u - right_u) <= 1.0e-9
                for left_u, right_u in zip(
                    paths[0][1]["u_values"],
                    reversed(paths[1][1]["u_values"]),
                )
            )
        )
        reverse_is_same_cyclic_support = (
            bool(chain.get("is_cyclic"))
            and tuple(paths[0][1]["segment_indices"])
            == tuple(reversed(paths[1][1]["segment_indices"]))
            and all(
                abs(left_u - right_u) <= 1.0e-9
                for left_u, right_u in zip(
                    paths[0][1]["u_values"],
                    reversed(paths[1][1]["u_values"]),
                )
            )
        )
        reverse_is_same_open_support = (
            not chain.get("is_cyclic")
            and paths[0][1]["u_values"]
            and paths[1][1]["u_values"]
            and abs(paths[0][1]["u_values"][0] - paths[1][1]["u_values"][0])
            <= 1.0e-9
            and abs(paths[0][1]["u_values"][-1] - paths[1][1]["u_values"][-1])
            <= 1.0e-9
            and abs(
                sum(
                    abs(following - current)
                    for current, following in zip(
                        paths[0][1]["u_values"],
                        paths[0][1]["u_values"][1:],
                    )
                )
                - sum(
                    abs(following - current)
                    for current, following in zip(
                        paths[1][1]["u_values"],
                        paths[1][1]["u_values"][1:],
                    )
                )
            )
            <= 1.0e-9
        )
        cyclic_chain_covers_open_strand = (
            bool(chain.get("is_cyclic"))
            and not strand.cyclic
            and min(selected_path["u_values"]) <= 1.0e-9
            and max(selected_path["u_values"]) >= 1.0 - 1.0e-9
        )
        collapsed_chain_has_no_direction = (
            max(selected_path["u_values"])
            - min(selected_path["u_values"])
            <= 1.0e-8
            and (
                max(
                    (
                        Vector(following) - Vector(current)
                    ).length
                    for current, following in zip(
                        chain["coordinates"],
                        chain["coordinates"][1:],
                    )
                )
                <= 1.0e-7
            )
        )
        if (
            abs(paths[1][1]["backtrack"] - selected_path["backtrack"])
            <= 1.0e-12
            and paths[1][1]["cost"] - selected_path["cost"]
            <= ambiguity_tolerance
            and not reverse_is_same_open_chain
            and not reverse_is_same_cyclic_support
            and not reverse_is_same_open_support
            and not cyclic_chain_covers_open_strand
            and not collapsed_chain_has_no_direction
        ):
            raise BatchedChamferError(
                "AMBIGUOUS_STRAND_PROJECTION_DIRECTION",
                "Boundary chain 的 FeatureStrand 正反方向投影无法唯一判定",
                {
                    "forward_cost": forward_path["cost"] if forward_path else None,
                    "reverse_cost": reverse_path["cost"] if reverse_path else None,
                    "forward_backtrack": (
                        forward_path["backtrack"] if forward_path else None
                    ),
                    "reverse_backtrack": (
                        reverse_path["backtrack"] if reverse_path else None
                    ),
                    "forward_u_values": (
                        list(forward_path["u_values"])
                        if forward_path
                        else None
                    ),
                    "reverse_u_values": (
                        list(reverse_path["u_values"])
                        if reverse_path
                        else None
                    ),
                    "forward_segment_indices": (
                        list(forward_path["segment_indices"])
                        if forward_path
                        else None
                    ),
                    "reverse_segment_indices": (
                        list(reverse_path["segment_indices"])
                        if reverse_path
                        else None
                    ),
                    "coordinates": list(chain["coordinates"]),
                    "is_cyclic": bool(chain.get("is_cyclic")),
                    "strand_is_cyclic": bool(strand.cyclic),
                    "source_patch_id": source_patch_id,
                    "allowed_segment_indices": (
                        sorted(allowed_segment_indices)
                        if allowed_segment_indices is not None
                        else None
                    ),
                    "edge_ids": list(chain["edge_ids"]),
                },
            )
    if reverse:
        reversed_edge_ids = list(reversed(chain["edge_ids"]))
        if chain.get("is_cyclic") and reversed_edge_ids:
            reversed_edge_ids = [*reversed_edge_ids[1:], reversed_edge_ids[0]]
        return (
            {
                **chain,
                "edge_ids": reversed_edge_ids,
                "coordinates": list(reversed(chain["coordinates"])),
                "endpoint_tokens": list(
                    reversed(chain.get("endpoint_tokens", ()))
                ),
            },
            list(selected_path["u_values"]),
        )
    return chain, list(selected_path["u_values"])


# 按 FeatureStrand 的 normalized u 统一 open rail run 方向。
# chain/strand: 当前 open rail 与权威 Plan FeatureStrand；返回 direction 与端点 u。
def _orient_chain_to_strand(chain, strand):
    oriented_chain, parameters = _chain_strand_parameters(chain, strand)
    return oriented_chain, parameters[0], parameters[-1]


# 把 overlap intervals 投影到 chain 的真实 Edge，并按 Edge 保守切为 regular/setback runs。
# chain/strand/forbidden_intervals: 有序 Boundary chain、Plan strand 与 normalized u 禁区；返回两类 maximal runs。
def _split_chain_by_forbidden_intervals(chain, strand, forbidden_intervals):
    oriented_chain, parameters = _chain_strand_parameters(chain, strand)
    cyclic_edge_count = len(oriented_chain["edge_ids"])
    if oriented_chain["is_cyclic"]:
        coordinates = list(oriented_chain["coordinates"])
        endpoint_tokens = list(oriented_chain.get("endpoint_tokens", ()))
        if len(parameters) == cyclic_edge_count:
            raw_delta = (parameters[0] - parameters[-1])
            if strand.cyclic:
                raw_delta = min(
                    (raw_delta + offset for offset in range(-2, 3)),
                    key=abs,
                )
            closure_parameter = parameters[-1] + raw_delta
            if closure_parameter + 1.0e-10 < parameters[-1]:
                forward_closure = float(parameters[0])
                while forward_closure + 1.0e-10 < parameters[-1]:
                    forward_closure += 1.0
                closure_parameter = forward_closure
            parameters = [*parameters, closure_parameter]
            coordinates = [*coordinates, coordinates[0]]
            if endpoint_tokens:
                endpoint_tokens = [*endpoint_tokens, endpoint_tokens[0]]
        else:
            coordinates = list(oriented_chain["coordinates"])
    else:
        coordinates = list(oriented_chain["coordinates"])
        endpoint_tokens = list(oriented_chain.get("endpoint_tokens", ()))
    intervals = [tuple(map(float, interval)) for interval in forbidden_intervals]

    def edge_is_forbidden(start_u, end_u):
        lower, upper = sorted((float(start_u), float(end_u)))
        offsets = range(-2, 3) if strand.cyclic else (0,)
        if upper - lower <= 1.0e-10:
            return any(
                start + offset - 1.0e-10
                <= lower
                <= end + offset + 1.0e-10
                for start, end in intervals
                for offset in offsets
            )
        return any(
            max(lower, start + offset) < min(upper, end + offset) - 1.0e-10
            for start, end in intervals
            for offset in offsets
        )

    forbidden = [
        edge_is_forbidden(parameters[index], parameters[index + 1])
        for index in range(len(oriented_chain["edge_ids"]))
    ]
    runs = {"regular": [], "setback": []}
    if not forbidden:
        return runs
    if oriented_chain["is_cyclic"] and all(value == forbidden[0] for value in forbidden):
        key = "setback" if forbidden[0] else "regular"
        if key == "regular":
            run_coordinates = coordinates
            run_parameters = parameters
            run_is_cyclic = False
        else:
            run_coordinates = coordinates[:-1]
            run_parameters = parameters[:-1]
            run_is_cyclic = True
        run_endpoint_tokens = (
            endpoint_tokens if key == "regular" else endpoint_tokens[:-1]
        )
        runs[key].append(
            {
                **oriented_chain,
                "coordinates": run_coordinates,
                "u_values": run_parameters,
                "u_interval": [min(parameters), max(parameters)],
                "is_cyclic": run_is_cyclic,
                "endpoint_tokens": run_endpoint_tokens,
            }
        )
        return runs
    start_offset = 0
    if oriented_chain["is_cyclic"]:
        start_offset = next(
            index + 1
            for index, (current, following) in enumerate(
                zip(forbidden, forbidden[1:] + forbidden[:1])
            )
            if current != following
        )
    edge_ids = (
        oriented_chain["edge_ids"][start_offset:]
        + oriented_chain["edge_ids"][:start_offset]
    )
    if oriented_chain["is_cyclic"]:
        rotated_coordinates = (
            coordinates[start_offset:-1] + coordinates[: start_offset + 1]
        )
        rotated_endpoint_tokens = (
            endpoint_tokens[start_offset:-1]
            + endpoint_tokens[: start_offset + 1]
        )
        rotated_parameters = parameters[start_offset:-1]
        rotated_parameters = list(rotated_parameters)
        for value in parameters[: start_offset + 1]:
            candidate = float(value)
            if strand.cyclic:
                candidate = min(
                    (candidate + offset for offset in range(-2, 3)),
                    key=lambda item: abs(item - rotated_parameters[-1]),
                )
            rotated_parameters.append(candidate)
    else:
        rotated_coordinates = list(coordinates)
        rotated_endpoint_tokens = list(endpoint_tokens)
        rotated_parameters = list(parameters)
    rotated_forbidden = forbidden[start_offset:] + forbidden[:start_offset]
    run_start = 0
    for index in range(1, len(edge_ids) + 1):
        if index < len(edge_ids) and rotated_forbidden[index] == rotated_forbidden[run_start]:
            continue
        key = "setback" if rotated_forbidden[run_start] else "regular"
        run_parameters = rotated_parameters[run_start : index + 1]
        runs[key].append(
            {
                "edge_ids": edge_ids[run_start:index],
                "coordinates": rotated_coordinates[run_start : index + 1],
                "is_cyclic": False,
                "u_values": run_parameters,
                "u_interval": [min(run_parameters), max(run_parameters)],
                "branch_setback": bool(oriented_chain.get("branch_setback")),
                "endpoint_tokens": rotated_endpoint_tokens[run_start : index + 1],
                "junction_endpoint_tokens_by_edge": {
                    edge_id: list(tokens)
                    for edge_id, tokens in oriented_chain.get(
                        "junction_endpoint_tokens_by_edge",
                        {},
                    ).items()
                    if edge_id in edge_ids[run_start:index]
                },
                "endpoint_degrees_by_edge": {
                    edge_id: list(degrees)
                    for edge_id, degrees in oriented_chain.get(
                        "endpoint_degrees_by_edge",
                        {},
                    ).items()
                    if edge_id in edge_ids[run_start:index]
                },
            }
        )
        run_start = index
    return runs


# 将当前 correspondence 的 rail pair 直接穿过 overlap 内部的完整 Edge span 并入 setback envelope。
# chains/strand/forbidden_intervals: 当前 pair 的两侧真实 Boundary chains、FeatureStrand 与原始 overlap 禁区；返回扩展禁区及 proof。
def _paired_rail_forbidden_edge_envelopes(chains, strand, forbidden_intervals):
    projected_edges = []
    for chain in chains:
        oriented_chain, parameters = _chain_strand_parameters(chain, strand)
        if oriented_chain["is_cyclic"]:
            parameters = list(parameters)
            closure_parameter = float(parameters[0])
            if strand.cyclic:
                closure_parameter = min(
                    (closure_parameter + offset for offset in range(-2, 3)),
                    key=lambda value: abs(value - parameters[-1]),
                )
                while closure_parameter + 1.0e-10 < parameters[-1]:
                    closure_parameter += 1.0
            parameters.append(closure_parameter)
        projected_edges.extend(
            {
                "edge_id": edge_id,
                "u_interval": sorted((float(start_u), float(end_u))),
            }
            for edge_id, start_u, end_u in zip(
                oriented_chain["edge_ids"],
                parameters,
                parameters[1:],
            )
        )
    envelope_records = []
    for interval_index, interval in enumerate(forbidden_intervals):
        forbidden_start, forbidden_end = sorted(map(float, interval))
        direct_hits = []
        for projected_edge in projected_edges:
            edge_start, edge_end = projected_edge["u_interval"]
            offsets = range(-2, 3) if strand.cyclic else (0,)
            candidates = [
                (edge_start + offset, edge_end + offset)
                for offset in offsets
                if (
                    (
                        edge_end - edge_start <= 1.0e-10
                        and forbidden_start - 1.0e-10
                        <= edge_start + offset
                        <= forbidden_end + 1.0e-10
                    )
                    or (
                        edge_end - edge_start > 1.0e-10
                        and edge_end + offset > forbidden_start + 1.0e-8
                        and edge_start + offset < forbidden_end - 1.0e-8
                    )
                )
            ]
            if candidates:
                direct_start, direct_end = min(
                    candidates,
                    key=lambda candidate: (
                        abs(
                            (candidate[0] + candidate[1]) * 0.5
                            - (forbidden_start + forbidden_end) * 0.5
                        ),
                        candidate,
                    ),
                )
                direct_hits.append(
                    {
                        **projected_edge,
                        "lifted_u_interval": [direct_start, direct_end],
                    }
                )
        effective_start = min(
            [forbidden_start, *(hit["lifted_u_interval"][0] for hit in direct_hits)]
        )
        effective_end = max(
            [forbidden_end, *(hit["lifted_u_interval"][1] for hit in direct_hits)]
        )
        envelope_records.append(
            {
                "interval_index": interval_index,
                "source_u_interval": [forbidden_start, forbidden_end],
                "effective_u_interval": [effective_start, effective_end],
                "direct_witness_edge_ids": sorted(
                    {hit["edge_id"] for hit in direct_hits}
                ),
            }
        )
    return (
        tuple(record["effective_u_interval"] for record in envelope_records),
        tuple(envelope_records),
    )


# 把已按 u 定向的 open run 保守裁到共同区间；不在真实 Boundary Edge 内插点。
# run/interval: 含逐点 u 的 open run 与目标 unwrapped u interval；返回连续子 run 或 None。
def _trim_open_run_to_interval(run, interval):
    parameters = [float(value) for value in run["u_values"]]
    candidates = []
    for shift in range(-2, 3):
        lower, upper = sorted(
            (float(interval[0]) + shift, float(interval[1]) + shift)
        )
        selected = [
            index
            for index, (start_u, end_u) in enumerate(
                zip(parameters, parameters[1:])
            )
            if lower - 1.0e-10
            <= (start_u + end_u) * 0.5
            <= upper + 1.0e-10
        ]
        if selected:
            candidates.append((len(selected), -abs(shift), selected))
    if not candidates:
        return None
    _, _, selected = max(candidates)
    if selected != list(range(selected[0], selected[-1] + 1)):
        return None
    start = selected[0]
    end = selected[-1] + 1
    selected_edge_ids = run["edge_ids"][start:end]
    return {
        **run,
        "edge_ids": selected_edge_ids,
        "coordinates": run["coordinates"][start : end + 1],
        "endpoint_tokens": list(run.get("endpoint_tokens", ()))[start : end + 1],
        "u_values": parameters[start : end + 1],
        "u_interval": [parameters[start], parameters[end]],
        "is_cyclic": False,
        "junction_endpoint_tokens_by_edge": {
            edge_id: list(tokens)
            for edge_id, tokens in run.get(
                "junction_endpoint_tokens_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
        "endpoint_degrees_by_edge": {
            edge_id: list(degrees)
            for edge_id, degrees in run.get(
                "endpoint_degrees_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
        "endpoint_topology_signatures_by_edge": {
            edge_id: list(signatures)
            for edge_id, signatures in run.get(
                "endpoint_topology_signatures_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
    }


# 求两个 unwrapped u intervals 的最大共同区间，并允许 cyclic strand 的整数 seam shift。
# left_interval/right_interval/cyclic: 左右区间与 strand 闭合标记；返回共同区间和右侧 shift。
def _common_run_interval(left_interval, right_interval, cyclic):
    shifts = range(-2, 3) if cyclic else (0,)
    candidates = []
    left_start, left_end = sorted(map(float, left_interval))
    for shift in shifts:
        right_start, right_end = sorted(
            (float(right_interval[0]) + shift, float(right_interval[1]) + shift)
        )
        start = max(left_start, right_start)
        end = min(left_end, right_end)
        if end - start > 1.0e-8:
            candidates.append((end - start, -abs(shift), start, end, shift))
    if not candidates:
        return None
    _, _, start, end, shift = max(candidates)
    return [start, end], shift


# 仅从 open run 两端删除完整 Boundary Edges，禁止内部删点或坐标插值。
# run/start_trim/end_trim: 当前 run 与两端裁剪 Edge 数；返回裁剪后 run 或 None。
def _trim_run_endpoint_edges(run, start_trim, end_trim):
    edge_count = len(run["edge_ids"])
    if start_trim < 0 or end_trim < 0 or start_trim + end_trim >= edge_count:
        return None
    edge_end = edge_count - end_trim
    point_end = edge_end + 1
    parameters = list(run["u_values"])[start_trim:point_end]
    selected_edge_ids = list(run["edge_ids"])[start_trim:edge_end]
    return {
        **run,
        "edge_ids": selected_edge_ids,
        "coordinates": list(run["coordinates"])[start_trim:point_end],
        "endpoint_tokens": list(run.get("endpoint_tokens", ()))[
            start_trim:point_end
        ],
        "u_values": parameters,
        "u_interval": [parameters[0], parameters[-1]],
        "junction_endpoint_tokens_by_edge": {
            edge_id: list(tokens)
            for edge_id, tokens in run.get(
                "junction_endpoint_tokens_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
        "endpoint_degrees_by_edge": {
            edge_id: list(degrees)
            for edge_id, degrees in run.get(
                "endpoint_degrees_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
        "endpoint_topology_signatures_by_edge": {
            edge_id: list(signatures)
            for edge_id, signatures in run.get(
                "endpoint_topology_signatures_by_edge",
                {},
            ).items()
            if edge_id in selected_edge_ids
        },
    }


# 移除 Boolean 数值产生的连续零长度 Edge，同时把这些 Edge 保留给结构化 junction setback。
# run/radius: 当前 open run 与 Chamfer radius；返回清理后的 run、移除 Edge IDs 和 proof。
def _defer_zero_length_run_edges(run, radius):
    coordinates = [Vector(point) for point in run["coordinates"]]
    maximum_length = max(radius * 1.0e-2, 2.0e-6)
    kept_edge_ids = []
    kept_coordinates = [coordinates[0]]
    kept_u_values = [float(run["u_values"][0])]
    kept_endpoint_tokens = list(run.get("endpoint_tokens", ()))[:1]
    deferred_edge_ids = []
    for edge_index, (edge_id, start, end, start_u, end_u) in enumerate(zip(
        run["edge_ids"],
        coordinates,
        coordinates[1:],
        run["u_values"],
        run["u_values"][1:],
    )):
        if (end - start).length <= maximum_length:
            deferred_edge_ids.append(edge_id)
            continue
        kept_edge_ids.append(edge_id)
        kept_coordinates.append(end)
        kept_u_values.append(float(end_u))
        if run.get("endpoint_tokens"):
            kept_endpoint_tokens.append(
                run["endpoint_tokens"][edge_index + 1]
            )
    if not deferred_edge_ids:
        return run, ()
    if not kept_edge_ids:
        return None, (
            {
                "proof_version": "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1",
                "edge_ids": deferred_edge_ids,
                "maximum_edge_length": maximum_length,
            },
        )
    cleaned = {
        **run,
        "edge_ids": kept_edge_ids,
        "coordinates": [tuple(point) for point in kept_coordinates],
        "endpoint_tokens": kept_endpoint_tokens,
        "u_values": kept_u_values,
        "u_interval": [kept_u_values[0], kept_u_values[-1]],
        "junction_endpoint_tokens_by_edge": {
            edge_id: list(tokens)
            for edge_id, tokens in run.get(
                "junction_endpoint_tokens_by_edge",
                {},
            ).items()
            if edge_id in kept_edge_ids
        },
        "endpoint_degrees_by_edge": {
            edge_id: list(degrees)
            for edge_id, degrees in run.get(
                "endpoint_degrees_by_edge",
                {},
            ).items()
            if edge_id in kept_edge_ids
        },
        "endpoint_topology_signatures_by_edge": {
            edge_id: list(signatures)
            for edge_id, signatures in run.get(
                "endpoint_topology_signatures_by_edge",
                {},
            ).items()
            if edge_id in kept_edge_ids
        },
    }
    return cleaned, (
        {
            "proof_version": "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1",
            "edge_ids": deferred_edge_ids,
            "maximum_edge_length": maximum_length,
        },
    )


# 对 rail pair 执行 monotonic 与双向 width envelope 硬门禁。
# left_run/right_run/radius: 已裁到共同 atom component 的两侧 runs 与半径；返回 guard diagnostics。
def _regular_pair_width_guard(left_run, right_run, radius):
    left_parameters = [float(value) for value in left_run["u_values"]]
    right_parameters = [float(value) for value in right_run["u_values"]]
    if any(
        following + 1.0e-8 < current
        for values in (left_parameters, right_parameters)
        for current, following in zip(values, values[1:])
    ):
        return {"status": "FAIL", "reason": "NON_MONOTONIC_U"}
    left_coordinates = [Vector(point) for point in left_run["coordinates"]]
    right_coordinates = [Vector(point) for point in right_run["coordinates"]]
    expected_width = radius * (2.0 ** 0.5)
    width_tolerance = max(radius * 0.60, 1.0e-5)
    width_errors = [
        abs(
            _point_to_polyline_distance(point, right_coordinates, False)
            - expected_width
        )
        for point in left_coordinates
    ] + [
        abs(
            _point_to_polyline_distance(point, left_coordinates, False)
            - expected_width
        )
        for point in right_coordinates
    ]
    inlier_ratio = (
        sum(error <= width_tolerance for error in width_errors) / len(width_errors)
        if width_errors
        else 0.0
    )
    sorted_errors = sorted(width_errors)
    percentile_error = (
        sorted_errors[max(0, int(len(sorted_errors) * 0.90) - 1)]
        if sorted_errors
        else float("inf")
    )
    return {
        "status": (
            "PASS"
            if inlier_ratio >= 0.90 and percentile_error <= width_tolerance
            else "FAIL"
        ),
        "reason": (
            None
            if inlier_ratio >= 0.90 and percentile_error <= width_tolerance
            else "PAIR_WIDTH_ENVELOPE_FAILED"
        ),
        "width_inlier_ratio": inlier_ratio,
        "width_percentile_error": percentile_error,
        "maximum_width_error": max(width_errors, default=0.0),
        "width_tolerance": width_tolerance,
        "left_start": [round(float(value), 8) for value in left_coordinates[0]],
        "left_end": [round(float(value), 8) for value in left_coordinates[-1]],
        "right_start": [round(float(value), 8) for value in right_coordinates[0]],
        "right_end": [round(float(value), 8) for value in right_coordinates[-1]],
    }


# 统计 Strip topology 中的零面积 Face，候选提交前即拒绝退化几何。
# strip/left_coordinates/right_coordinates: build_chamfer_strip 结果与两侧点列；返回零面积 Face 数。
def _strip_zero_area_face_count(strip, left_coordinates, right_coordinates):
    zero_area_face_count = 0
    for face in strip.get("faces", ()):
        coordinates = [
            left_coordinates[index] if side == "A" else right_coordinates[index]
            for side, index in face
        ]
        normal = Vector()
        for index, coordinate in enumerate(coordinates):
            normal += coordinate.cross(
                coordinates[(index + 1) % len(coordinates)]
            )
        if normal.length <= 1.0e-12:
            zero_area_face_count += 1
    return zero_area_face_count


# 按共同 Plan-u 样本在真实 Boundary Edge 内插虚拟 geometry 点；原始 Edge provenance 不拆分也不重复消费。
# left_run/right_run: 已裁到同一 component 的两侧 runs；返回共享单调采样网格上的 geometry runs。
def _synchronize_regular_run_geometry_samples(left_run, right_run):
    left_parameters = sorted(map(float, left_run["u_values"]))
    right_parameters = sorted(map(float, right_run["u_values"]))
    left_lower, left_upper = left_parameters[0], left_parameters[-1]
    right_lower, right_upper = right_parameters[0], right_parameters[-1]
    common_lower = max(left_lower, right_lower)
    common_upper = min(left_upper, right_upper)
    sample_parameters = sorted(
        {
            round(float(value), 12)
            for run in (left_run, right_run)
            for value in run["u_values"]
            if common_lower - 1.0e-10
            <= float(value)
            <= common_upper + 1.0e-10
        }
    )
    if len(sample_parameters) < 2:
        return left_run, right_run

    def virtualize(run):
        parameters = [float(value) for value in run["u_values"]]
        coordinates = [Vector(point) for point in run["coordinates"]]
        endpoint_tokens = list(run.get("endpoint_tokens", ()))
        synchronized_coordinates = []
        synchronized_tokens = []
        virtual_samples = []
        for sample_u in sample_parameters:
            exact_indices = [
                index
                for index, value in enumerate(parameters)
                if abs(value - sample_u) <= 1.0e-10
            ]
            if exact_indices:
                index = exact_indices[0]
                synchronized_coordinates.append(tuple(coordinates[index]))
                synchronized_tokens.append(
                    endpoint_tokens[index]
                    if index < len(endpoint_tokens)
                    else _stable_fingerprint([run["edge_ids"], sample_u])
                )
                continue
            containing_segments = [
                index
                for index, (start_u, end_u) in enumerate(
                    zip(parameters, parameters[1:])
                )
                if min(start_u, end_u) + 1.0e-10
                < sample_u
                < max(start_u, end_u) - 1.0e-10
            ]
            if len(containing_segments) != 1:
                raise BatchedChamferError(
                    "REGULAR_VIRTUAL_SAMPLE_OWNER_INVALID",
                    "Plan-u 虚拟采样点无法唯一归属真实 Boundary Edge",
                    {
                        "sample_u": sample_u,
                        "u_values": parameters,
                        "edge_ids": list(run["edge_ids"]),
                        "candidate_segment_count": len(containing_segments),
                    },
                )
            segment_index = containing_segments[0]
            start_u = parameters[segment_index]
            end_u = parameters[segment_index + 1]
            factor = (sample_u - start_u) / (end_u - start_u)
            coordinate = coordinates[segment_index].lerp(
                coordinates[segment_index + 1],
                factor,
            )
            source_edge_id = run["edge_ids"][segment_index]
            synchronized_coordinates.append(tuple(coordinate))
            synchronized_tokens.append(
                f"virtual:{source_edge_id}:{round(sample_u, 12)}"
            )
            virtual_samples.append(
                {
                    "sample_u": sample_u,
                    "source_edge_id": source_edge_id,
                    "source_edge_factor": factor,
                    "coordinate": tuple(coordinate),
                }
            )
        return {
            **run,
            "coordinates": synchronized_coordinates,
            "endpoint_tokens": synchronized_tokens,
            "u_values": list(sample_parameters),
            "u_interval": [sample_parameters[0], sample_parameters[-1]],
            "virtual_regular_samples": virtual_samples,
        }

    return virtualize(left_run), virtualize(right_run)


# 只接受最小总 Edge 裁剪量下唯一通过 width guard 的 pair，避免按距离成本猜结果。
# left_run/right_run/radius: atom component 两侧 runs 与半径；返回唯一 pair 或拒绝诊断。
def _conservative_endpoint_pair_trim(left_run, right_run, radius):
    maximum_left_trim = min(4, max(0, len(left_run["edge_ids"]) - 1))
    maximum_right_trim = min(4, max(0, len(right_run["edge_ids"]) - 1))
    maximum_total_trim = maximum_left_trim * 2 + maximum_right_trim * 2
    rejection_counts = {}
    minimum_trim_passing_count = 0
    best_strip_rejection = None
    for total_trim in range(maximum_total_trim + 1):
        passing = []
        for left_start_trim in range(maximum_left_trim + 1):
            for left_end_trim in range(maximum_left_trim + 1):
                for right_start_trim in range(maximum_right_trim + 1):
                    for right_end_trim in range(maximum_right_trim + 1):
                        trim_counts = (
                            left_start_trim,
                            left_end_trim,
                            right_start_trim,
                            right_end_trim,
                        )
                        if sum(trim_counts) != total_trim:
                            continue
                        trimmed_left = _trim_run_endpoint_edges(
                            left_run,
                            left_start_trim,
                            left_end_trim,
                        )
                        trimmed_right = _trim_run_endpoint_edges(
                            right_run,
                            right_start_trim,
                            right_end_trim,
                        )
                        if trimmed_left is None or trimmed_right is None:
                            continue
                        provenance_left = trimmed_left
                        provenance_right = trimmed_right
                        geometry_left, geometry_right = (
                            _synchronize_regular_run_geometry_samples(
                                trimmed_left,
                                trimmed_right,
                            )
                        )
                        guard = _regular_pair_width_guard(
                            geometry_left,
                            geometry_right,
                            radius,
                        )
                        if guard["status"] != "PASS":
                            continue
                        left_coordinates = [
                            Vector(point) for point in geometry_left["coordinates"]
                        ]
                        right_coordinates = [
                            Vector(point) for point in geometry_right["coordinates"]
                        ]
                        strip = build_chamfer_strip(
                            left_coordinates,
                            right_coordinates,
                            terminal_constraints={
                                "start_pairs": [(0, 0)],
                                "end_pairs": [
                                    (
                                        len(geometry_left["coordinates"]) - 1,
                                        len(geometry_right["coordinates"]) - 1,
                                    )
                                ],
                                "expected_width": radius * (2.0 ** 0.5),
                                "maximum_width_error": max(radius * 0.60, 1.0e-5),
                                "reject_zero_area_faces": True,
                                "prefer_hard_guard_path": True,
                            },
                        )
                        if (
                            strip["diagnostics"]["status"] == "PASS"
                            and strip["faces"]
                            and _strip_zero_area_face_count(
                                strip,
                                left_coordinates,
                                right_coordinates,
                            )
                            == 0
                        ):
                            passing.append(
                                {
                                    "left": {
                                        **geometry_left,
                                        "edge_ids": provenance_left["edge_ids"],
                                    },
                                    "right": {
                                        **geometry_right,
                                        "edge_ids": provenance_right["edge_ids"],
                                    },
                                    "provenance_left_edge_ids": list(
                                        provenance_left["edge_ids"]
                                    ),
                                    "provenance_right_edge_ids": list(
                                        provenance_right["edge_ids"]
                                    ),
                                    "trim_counts": trim_counts,
                                    "strip_diagnostics": strip["diagnostics"],
                                    **guard,
                                }
                            )
                        else:
                            rejection_reason = (
                                "STRIP_ZERO_AREA_FACE"
                                if strip["diagnostics"]["status"] == "PASS"
                                and strip["faces"]
                                else (
                                    strip["diagnostics"].get("reason")
                                    or "|".join(
                                        map(str, strip["diagnostics"].get("reasons", ()))
                                    )
                                    or "STRIP_GEOMETRY_GUARD"
                                )
                            )
                            rejection_counts[rejection_reason] = (
                                rejection_counts.get(rejection_reason, 0) + 1
                            )
                            strip_diagnostics = strip["diagnostics"]
                            rejection_rank = (
                                float(
                                    strip_diagnostics.get(
                                        "maximum_relative_advance",
                                        float("inf"),
                                    )
                                ),
                                float(
                                    strip_diagnostics.get(
                                        "maximum_width_error",
                                        float("inf"),
                                    )
                                ),
                                int(
                                    strip_diagnostics.get(
                                        "one_sided_step_count",
                                        1 << 30,
                                    )
                                ),
                                trim_counts,
                            )
                            if (
                                best_strip_rejection is None
                                or rejection_rank < best_strip_rejection[0]
                            ):
                                best_strip_rejection = (
                                    rejection_rank,
                                    {
                                        "reason": rejection_reason,
                                        "trim_counts": list(trim_counts),
                                        "status": strip_diagnostics.get("status"),
                                        "reasons": list(
                                            strip_diagnostics.get("reasons", ())
                                        ),
                                        "maximum_relative_advance": (
                                            strip_diagnostics.get(
                                                "maximum_relative_advance"
                                            )
                                        ),
                                        "maximum_relative_advance_limit": (
                                            strip_diagnostics.get(
                                                "maximum_relative_advance_limit"
                                            )
                                        ),
                                        "maximum_width_error": (
                                            strip_diagnostics.get(
                                                "maximum_width_error"
                                            )
                                        ),
                                        "width_error_inlier_ratio": (
                                            strip_diagnostics.get(
                                                "width_error_inlier_ratio"
                                            )
                                        ),
                                        "one_sided_step_count": (
                                            strip_diagnostics.get(
                                                "one_sided_step_count"
                                            )
                                        ),
                                        "zero_area_face_count": (
                                            _strip_zero_area_face_count(
                                                strip,
                                                left_coordinates,
                                                right_coordinates,
                                            )
                                        ),
                                    },
                                )
        unique_by_edges = {
            (
                tuple(candidate["provenance_left_edge_ids"]),
                tuple(candidate["provenance_right_edge_ids"]),
            ): candidate
            for candidate in passing
        }
        if len(unique_by_edges) == 1:
            return next(iter(unique_by_edges.values())), None
        if len(unique_by_edges) > 1:
            minimum_trim_passing_count = len(unique_by_edges)
            maximum_start_u = max(
                min(
                    float(candidate["left"]["u_interval"][0]),
                    float(candidate["right"]["u_interval"][0]),
                )
                for candidate in unique_by_edges.values()
            )
            minimum_end_u = min(
                max(
                    float(candidate["left"]["u_interval"][1]),
                    float(candidate["right"]["u_interval"][1]),
                )
                for candidate in unique_by_edges.values()
            )
            if minimum_end_u - maximum_start_u <= 1.0e-8:
                candidate_spans = sorted(
                    (
                        max(
                            min(map(float, candidate["left"]["u_interval"])),
                            min(map(float, candidate["right"]["u_interval"])),
                        ),
                        min(
                            max(map(float, candidate["left"]["u_interval"])),
                            max(map(float, candidate["right"]["u_interval"])),
                        ),
                    )
                    for candidate in unique_by_edges.values()
                )
                contiguous_clusters = []
                for span_start, span_end in candidate_spans:
                    if (
                        contiguous_clusters
                        and span_start
                        <= contiguous_clusters[-1][1] + 1.0e-8
                    ):
                        contiguous_clusters[-1][1] = max(
                            contiguous_clusters[-1][1],
                            span_end,
                        )
                    else:
                        contiguous_clusters.append([span_start, span_end])
                if len(contiguous_clusters) == 1:
                    maximum_start_u, minimum_end_u = (
                        contiguous_clusters[0]
                    )
            canonical_left = _trim_open_run_to_interval(
                left_run,
                [maximum_start_u, minimum_end_u],
            )
            canonical_right = _trim_open_run_to_interval(
                right_run,
                [maximum_start_u, minimum_end_u],
            )
            if canonical_left is not None and canonical_right is not None:
                canonical_left = _clip_run_geometry_to_interval(
                    canonical_left,
                    [maximum_start_u, minimum_end_u],
                )
                canonical_right = _clip_run_geometry_to_interval(
                    canonical_right,
                    [maximum_start_u, minimum_end_u],
                )
                geometry_left, geometry_right = (
                    _synchronize_regular_run_geometry_samples(
                        canonical_left,
                        canonical_right,
                    )
                )
                canonical_guard = _regular_pair_width_guard(
                    geometry_left,
                    geometry_right,
                    radius,
                )
                canonical_strip = build_chamfer_strip(
                    [Vector(point) for point in geometry_left["coordinates"]],
                    [Vector(point) for point in geometry_right["coordinates"]],
                    terminal_constraints={
                        "start_pairs": [(0, 0)],
                        "end_pairs": [
                            (
                                len(geometry_left["coordinates"]) - 1,
                                len(geometry_right["coordinates"]) - 1,
                            )
                        ],
                        "expected_width": radius * (2.0 ** 0.5),
                        "maximum_width_error": max(radius * 0.60, 1.0e-5),
                        "reject_zero_area_faces": True,
                        "prefer_hard_guard_path": True,
                    },
                )
                if (
                    canonical_guard["status"] == "PASS"
                    and canonical_strip["diagnostics"]["status"] == "PASS"
                    and canonical_strip["faces"]
                    and _strip_zero_area_face_count(
                        canonical_strip,
                        [
                            Vector(point)
                            for point in geometry_left["coordinates"]
                        ],
                        [
                            Vector(point)
                            for point in geometry_right["coordinates"]
                        ],
                    )
                    == 0
                ):
                    return (
                        {
                            "left": {
                                **geometry_left,
                                "edge_ids": canonical_left["edge_ids"],
                            },
                            "right": {
                                **geometry_right,
                                "edge_ids": canonical_right["edge_ids"],
                            },
                            "provenance_left_edge_ids": list(
                                canonical_left["edge_ids"]
                            ),
                            "provenance_right_edge_ids": list(
                                canonical_right["edge_ids"]
                            ),
                            "trim_counts": (None, None, None, None),
                            "canonical_overlap_of_minimum_trim_candidates": True,
                            "minimum_trim_candidate_count": len(
                                unique_by_edges
                            ),
                            "strip_diagnostics": canonical_strip[
                                "diagnostics"
                            ],
                            **canonical_guard,
                        },
                        None,
                    )
            return None, {
                "reason": "ENDPOINT_TRIM_AMBIGUOUS",
                "minimum_total_trim": total_trim,
                "candidate_count": len(unique_by_edges),
                "candidates": [
                    {
                        "trim_counts": list(candidate["trim_counts"]),
                        "left_edge_ids": list(
                            candidate["provenance_left_edge_ids"]
                        ),
                        "right_edge_ids": list(
                            candidate["provenance_right_edge_ids"]
                        ),
                        "left_u_interval": list(candidate["left"]["u_interval"]),
                        "right_u_interval": list(
                            candidate["right"]["u_interval"]
                        ),
                        "virtual_left_sample_count": len(
                            candidate["left"].get("virtual_regular_samples", ())
                        ),
                        "virtual_right_sample_count": len(
                            candidate["right"].get("virtual_regular_samples", ())
                        ),
                    }
                    for candidate in unique_by_edges.values()
                ],
                "strip_rejection_counts": rejection_counts,
                "best_strip_rejection": (
                    best_strip_rejection[1]
                    if best_strip_rejection is not None
                    else None
                ),
            }
    return None, {
        "reason": "PAIR_WIDTH_ENVELOPE_FAILED",
        "minimum_trim_passing_count": minimum_trim_passing_count,
        "strip_rejection_counts": rejection_counts,
        "best_strip_rejection": (
            best_strip_rejection[1]
            if best_strip_rejection is not None
            else None
        ),
        "untrimmed_guard": _regular_pair_width_guard(
            left_run,
            right_run,
            radius,
        ),
    }


# 检查两条 open runs 是否可作为同一 regular u component 的唯一匹配候选。
# left_run/right_run/strand/radius: 两侧真实 runs、Plan strand 与 Chamfer radius；返回候选和拒绝诊断。
def _regular_run_pair_evaluation(
    left_run,
    right_run,
    strand,
    radius,
    allow_cyclic_shift=True,
):
    common = _common_run_interval(
        left_run["u_interval"],
        right_run["u_interval"],
        strand.cyclic and allow_cyclic_shift,
    )
    if common is None:
        return None, {"reason": "U_INTERVAL_DISJOINT"}
    common_interval, right_shift = common
    trimmed_left = _trim_open_run_to_interval(left_run, common_interval)
    shifted_right = {
        **right_run,
        "u_values": [float(value) + right_shift for value in right_run["u_values"]],
        "u_interval": [
            float(right_run["u_interval"][0]) + right_shift,
            float(right_run["u_interval"][1]) + right_shift,
        ],
    }
    trimmed_left = (
        _clip_run_geometry_to_interval(trimmed_left, common_interval)
        if trimmed_left is not None
        else None
    )
    trimmed_right = _trim_open_run_to_interval(shifted_right, common_interval)
    trimmed_right = (
        _clip_run_geometry_to_interval(trimmed_right, common_interval)
        if trimmed_right is not None
        else None
    )
    if trimmed_left is not None and trimmed_right is not None:
        clipped_left, clipped_right = _synchronize_regular_run_geometry_samples(
            trimmed_left,
            trimmed_right,
        )
        direct_guard = _regular_pair_width_guard(
            clipped_left,
            clipped_right,
            radius,
        )
        direct_strip = build_chamfer_strip(
            [Vector(point) for point in clipped_left["coordinates"]],
            [Vector(point) for point in clipped_right["coordinates"]],
            terminal_constraints={
                "start_pairs": [(0, 0)],
                "end_pairs": [
                    (
                        len(clipped_left["coordinates"]) - 1,
                        len(clipped_right["coordinates"]) - 1,
                    )
                ],
                "expected_width": radius * (2.0 ** 0.5),
                "maximum_width_error": max(radius * 0.60, 1.0e-5),
                "reject_zero_area_faces": True,
                "prefer_hard_guard_path": True,
            },
        )
        if (
            direct_guard["status"] == "PASS"
            and direct_strip["diagnostics"]["status"] == "PASS"
            and direct_strip["faces"]
            and _strip_zero_area_face_count(
                direct_strip,
                [Vector(point) for point in clipped_left["coordinates"]],
                [Vector(point) for point in clipped_right["coordinates"]],
            )
            == 0
        ):
            return (
                {
                    "left": clipped_left,
                    "right": clipped_right,
                    "common_u_interval": common_interval,
                    "left_edge_count": len(clipped_left["edge_ids"]),
                    "right_edge_count": len(clipped_right["edge_ids"]),
                    "endpoint_trim_counts": [0, 0, 0, 0],
                    "canonical_overlap_of_minimum_trim_candidates": False,
                    "minimum_trim_candidate_count": 1,
                    "strip_diagnostics": direct_strip["diagnostics"],
                    **direct_guard,
                },
                None,
            )
    if trimmed_left is None or trimmed_right is None:
        return None, {
            "reason": "COMMON_INTERVAL_HAS_NO_REAL_EDGE",
            "common_u_interval": common_interval,
        }
    if len(trimmed_left["coordinates"]) < 2 or len(trimmed_right["coordinates"]) < 2:
        return None, {
            "reason": "COMMON_INTERVAL_TOO_SHORT",
            "common_u_interval": common_interval,
        }
    trimmed_pair, trim_rejection = _conservative_endpoint_pair_trim(
        trimmed_left,
        trimmed_right,
        radius,
    )
    if trimmed_pair is None:
        return None, {
            **trim_rejection,
            "common_u_interval": common_interval,
            "left_edge_count": len(trimmed_left["edge_ids"]),
            "right_edge_count": len(trimmed_right["edge_ids"]),
        }
    trimmed_left = trimmed_pair["left"]
    trimmed_right = trimmed_pair["right"]
    diagnostics = {
        "common_u_interval": common_interval,
        "left_edge_count": len(trimmed_left["edge_ids"]),
        "right_edge_count": len(trimmed_right["edge_ids"]),
        "endpoint_trim_counts": list(trimmed_pair["trim_counts"]),
        "canonical_overlap_of_minimum_trim_candidates": bool(
            trimmed_pair.get("canonical_overlap_of_minimum_trim_candidates")
        ),
        "minimum_trim_candidate_count": int(
            trimmed_pair.get("minimum_trim_candidate_count", 1)
        ),
        "width_inlier_ratio": trimmed_pair["width_inlier_ratio"],
        "width_percentile_error": trimmed_pair["width_percentile_error"],
        "maximum_width_error": trimmed_pair["maximum_width_error"],
        "width_tolerance": trimmed_pair["width_tolerance"],
        "left_start": trimmed_pair["left_start"],
        "left_end": trimmed_pair["left_end"],
        "right_start": trimmed_pair["right_start"],
        "right_end": trimmed_pair["right_end"],
    }
    return (
        {
            "left": trimmed_left,
            "right": trimmed_right,
            **diagnostics,
        },
        None,
    )


# 兼容调用 seam，仅返回已通过硬门禁的 regular run pair。
# left_run/right_run/strand/radius: 两侧 runs、Plan strand 与半径；返回候选或 None。
def _regular_run_pair_candidate(left_run, right_run, strand, radius):
    candidate, _ = _regular_run_pair_evaluation(
        left_run,
        right_run,
        strand,
        radius,
    )
    return candidate


# 枚举 bipartite component 的 perfect matching，最多保留两个以判断唯一性。
# left_ids/right_ids/candidates: 稳定 run IDs 与候选 pair map；返回零、一个或两个 matching。
def _unique_perfect_matching(left_ids, right_ids, candidates):
    left_ids = tuple(sorted(left_ids))
    right_ids = set(right_ids)
    solutions = []

    def visit(offset, available_right, matching):
        if len(solutions) >= 2:
            return
        if offset == len(left_ids):
            if not available_right:
                solutions.append(tuple(matching))
            return
        left_id = left_ids[offset]
        for right_id in sorted(
            right_ids & available_right & set(candidates.get(left_id, ()))
        ):
            visit(
                offset + 1,
                available_right - {right_id},
                [*matching, (left_id, right_id)],
            )

    visit(0, right_ids, [])
    return tuple(solutions)


# 把同一 rail、u 连续且共享语义 component 的 fragments 确定性拼成 maximal run。
# runs: 同一 correspondence side 的 open runs；返回按稳定 Edge IDs 排序的 stitched runs。
def _stitch_contiguous_regular_runs(runs, radius, strand_length, strand_cyclic):
    remaining = [dict(run) for run in runs]
    parameter_tolerance = max(
        2.0e-3,
        radius / max(float(strand_length), 1.0e-12),
    )
    point_tolerance = max(1.0e-4, radius * 0.50)
    changed = True
    while changed:
        changed = False
        successor_indices = {index: [] for index in range(len(remaining))}
        predecessor_indices = {index: [] for index in range(len(remaining))}
        for left_index, left in enumerate(remaining):
            left_parameters = [float(value) for value in left["u_values"]]
            if any(
                following + 1.0e-8 < current
                for current, following in zip(
                    left_parameters,
                    left_parameters[1:],
                )
            ):
                continue
            for right_index, right in enumerate(remaining):
                if left_index == right_index:
                    continue
                right_parameters = [float(value) for value in right["u_values"]]
                if any(
                    following + 1.0e-8 < current
                    for current, following in zip(
                        right_parameters,
                        right_parameters[1:],
                    )
                ):
                    continue
                u_gap = abs(
                    left_parameters[-1] - right_parameters[0]
                )
                seam_shift = 0
                if strand_cyclic and u_gap > parameter_tolerance:
                    seam_candidates = sorted(
                        (
                            abs(
                                float(left["u_values"][-1])
                                - (right_parameters[0] + shift)
                            ),
                            abs(shift),
                            shift,
                        )
                        for shift in range(-2, 3)
                    )
                    u_gap, _, seam_shift = seam_candidates[0]
                point_gap = (
                    Vector(left["coordinates"][-1])
                    - Vector(right["coordinates"][0])
                ).length
                left_endpoint_tokens = left.get("endpoint_tokens", ())
                right_endpoint_tokens = right.get("endpoint_tokens", ())
                topology_contiguous = (
                    left_endpoint_tokens
                    and right_endpoint_tokens
                    and left_endpoint_tokens[-1] == right_endpoint_tokens[0]
                )
                if (
                    u_gap > parameter_tolerance
                    or point_gap > point_tolerance
                    or not topology_contiguous
                ):
                    continue
                successor_indices[left_index].append(
                    (right_index, seam_shift)
                )
                predecessor_indices[right_index].append(
                    (left_index, seam_shift)
                )
        unique_pairs = sorted(
            (left_index, candidates[0][0], candidates[0][1])
            for left_index, candidates in successor_indices.items()
            if len(candidates) == 1
            and len(predecessor_indices[candidates[0][0]]) == 1
        )
        if unique_pairs:
            left_index, right_index, seam_shift = unique_pairs[0]
            left = remaining[left_index]
            right = remaining[right_index]
            shifted_right_u_values = [
                float(value) + seam_shift
                for value in right["u_values"]
            ]
            left_endpoint_tokens = left["endpoint_tokens"]
            right_endpoint_tokens = right["endpoint_tokens"]
            merged = {
                    **left,
                    "edge_ids": [*left["edge_ids"], *right["edge_ids"]],
                    "coordinates": [
                        *left["coordinates"],
                        *right["coordinates"][1:],
                    ],
                    "u_values": [
                        *left["u_values"],
                        *shifted_right_u_values[1:],
                    ],
                    "endpoint_tokens": [
                        *left_endpoint_tokens,
                        *right_endpoint_tokens[1:],
                    ],
                    "u_interval": [
                        float(left["u_values"][0]),
                        shifted_right_u_values[-1],
                    ],
            }
            for index in sorted((left_index, right_index), reverse=True):
                remaining.pop(index)
            remaining.append(merged)
            changed = True
    return tuple(sorted(remaining, key=lambda run: run["edge_ids"]))


# 仅移除 stitch 后形成、被同点真实 Boundary 支路夹住的微型闭环；被移除 Edge 继续留给 junction handoff。
# run/radius: stitched open run 与 Chamfer radius；返回 monotonic regular run、deferred Edge proof 或 None。
def _defer_stitched_micro_loops(run, radius):
    parameters = [float(value) for value in run["u_values"]]
    if all(
        following + 1.0e-8 >= current
        for current, following in zip(parameters, parameters[1:])
    ):
        return run, ()
    coordinates = [Vector(point) for point in run["coordinates"]]
    candidates = []
    maximum_loop_length = radius * 0.10
    for start in range(len(run["edge_ids"])):
        for end in range(start + 2, len(run["edge_ids"]) + 1):
            if (coordinates[end] - coordinates[start]).length > 1.0e-8:
                continue
            loop_length = sum(
                (coordinates[index + 1] - coordinates[index]).length
                for index in range(start, end)
            )
            if loop_length > maximum_loop_length + 1.0e-10:
                continue
            retained_parameters = parameters[: start + 1] + parameters[end + 1 :]
            if len(retained_parameters) < 2 or any(
                following + 1.0e-8 < current
                for current, following in zip(
                    retained_parameters,
                    retained_parameters[1:],
                )
            ):
                continue
            candidates.append((end - start, loop_length, start, end))
    if len(candidates) != 1:
        return None, ()
    edge_count, loop_length, start, end = candidates[0]
    retained = {
        **run,
        "edge_ids": [*run["edge_ids"][:start], *run["edge_ids"][end:]],
        "coordinates": [
            *run["coordinates"][: start + 1],
            *run["coordinates"][end + 1 :],
        ],
        "endpoint_tokens": [
            *run.get("endpoint_tokens", ())[: start + 1],
            *run.get("endpoint_tokens", ())[end + 1 :],
        ],
        "u_values": [*parameters[: start + 1], *parameters[end + 1 :]],
        "u_interval": [parameters[0], parameters[-1]],
        "deferred_micro_loop_edge_ids": list(run["edge_ids"][start:end]),
    }
    if len(retained["edge_ids"]) + 1 != len(retained["coordinates"]):
        return None, ()
    proof = {
        "proof_version": "STITCHED_MICRO_LOOP_JUNCTION_V1",
        "edge_ids": list(run["edge_ids"][start:end]),
        "edge_count": edge_count,
        "loop_length": loop_length,
        "maximum_loop_length": maximum_loop_length,
        "loop_coordinate": tuple(coordinates[start]),
        "branch_setback": bool(run.get("branch_setback")),
    }
    return retained, (proof,)


# 识别同一 Rail 内贴附于主 Boundary chain 的独立微型闭环；仅以直接拓扑与最近真实 Edge 证明交给 junction。
# chains/radius: 同一语义 Rail 的 Boundary chains 与 Chamfer radius；返回保留的 regular chains 和逐微环 proof。
def _defer_attached_cyclic_micro_components(chains, radius):
    if len(chains) < 2:
        return tuple(chains), ()

    def chain_length(chain):
        coordinates = [Vector(point) for point in chain["coordinates"]]
        if len(coordinates) < 2:
            return 0.0
        segment_count = len(chain["edge_ids"])
        return sum(
            (
                coordinates[(index + 1) % len(coordinates)]
                - coordinates[index]
            ).length
            for index in range(segment_count)
        )

    def closest_support_witness(point, support):
        coordinates = [Vector(value) for value in support["coordinates"]]
        witnesses = []
        for index, edge_id in enumerate(support["edge_ids"]):
            start = coordinates[index]
            end = coordinates[(index + 1) % len(coordinates)]
            direction = end - start
            squared_length = direction.length_squared
            factor = (
                0.0
                if squared_length <= 1.0e-20
                else max(
                    0.0,
                    min(1.0, (point - start).dot(direction) / squared_length),
                )
            )
            closest = start + direction * factor
            witnesses.append(((point - closest).length, edge_id, factor))
        return min(witnesses, key=lambda witness: witness[:2])

    lengths = [chain_length(chain) for chain in chains]
    maximum_component_length = max(float(radius) * 0.10, 2.0e-6)
    maximum_support_distance = max(float(radius) * 0.05, 1.0e-6)
    deferred_indices = set()
    proofs = []
    for candidate_index, candidate in enumerate(chains):
        candidate_edge_ids = list(candidate["edge_ids"])
        endpoint_degrees = candidate.get("endpoint_degrees_by_edge", {})
        if (
            not candidate.get("is_cyclic")
            or not 3 <= len(candidate_edge_ids) <= 4
            or lengths[candidate_index] > maximum_component_length + 1.0e-10
            or any(
                tuple(endpoint_degrees.get(edge_id, ())) != (2, 2)
                for edge_id in candidate_edge_ids
            )
        ):
            continue
        support_candidates = []
        for support_index, support in enumerate(chains):
            if support_index == candidate_index or not support.get("is_cyclic"):
                continue
            if lengths[support_index] < lengths[candidate_index] * 8.0:
                continue
            witnesses = [
                closest_support_witness(Vector(point), support)
                for point in candidate["coordinates"]
            ]
            maximum_distance = max(witness[0] for witness in witnesses)
            if maximum_distance <= maximum_support_distance + 1.0e-10:
                support_candidates.append(
                    (maximum_distance, support_index, witnesses)
                )
        if len(support_candidates) != 1:
            continue
        maximum_distance, support_index, witnesses = support_candidates[0]
        deferred_indices.add(candidate_index)
        proofs.append(
            {
                "proof_version": "ATTACHED_CYCLIC_MICRO_COMPONENT_SETBACK_V1",
                "edge_ids": candidate_edge_ids,
                "edge_count": len(candidate_edge_ids),
                "component_length": lengths[candidate_index],
                "maximum_component_length": maximum_component_length,
                "maximum_support_distance": maximum_support_distance,
                "observed_maximum_support_distance": maximum_distance,
                "support_edge_ids": sorted(
                    {witness[1] for witness in witnesses}
                ),
                "support_factors": [witness[2] for witness in witnesses],
                "support_chain_length": lengths[support_index],
                "endpoint_degrees_by_edge": {
                    edge_id: list(endpoint_degrees[edge_id])
                    for edge_id in candidate_edge_ids
                },
            }
        )
    return (
        tuple(
            chain
            for chain_index, chain in enumerate(chains)
            if chain_index not in deferred_indices
        ),
        tuple(proofs),
    )


# 证明大半径 Boolean 在主 Rail 上留下的孤立短 Edge 已失去对侧 regular 区域，必须交给 junction handoff。
# unresolved/atom/strand/radius: unmatched component、Plan atom、权威 FeatureStrand 与半径；返回严格 topology proof 或 None。
def _radius_collapsed_single_edge_setback_proof(
    unresolved,
    atom,
    strand,
    forbidden_intervals,
    radius,
):
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    run = present_runs[0]
    if len(run.get("edge_ids", ())) != 1:
        return None
    edge_id = run["edge_ids"][0]
    endpoint_degrees = list(
        run.get("endpoint_degrees_by_edge", {}).get(edge_id, ())
    )
    if endpoint_degrees != [2, 2]:
        return None
    coordinates = [Vector(point) for point in run.get("coordinates", ())]
    if len(coordinates) != 2:
        return None
    edge_length = (coordinates[1] - coordinates[0]).length
    maximum_edge_length = max(float(radius) * 0.37, 2.0e-6)
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    strand_length = _feature_strand_arc_length(strand)
    component_arc_length = (component_end - component_start) * strand_length
    maximum_component_arc_length = max(float(radius) * 0.45, 2.0e-6)
    adjacent_forbidden_boundaries = []
    for interval_index, interval in enumerate(forbidden_intervals):
        for boundary_side, boundary_u in (
            ("START", float(interval[0])),
            ("END", float(interval[1])),
        ):
            boundary_distance = min(
                abs(component_start - (boundary_u + shift))
                for shift in (range(-2, 3) if strand.cyclic else (0,))
            )
            if boundary_distance * strand_length <= radius * 0.5 + 1.0e-10:
                adjacent_forbidden_boundaries.append(
                    {
                        "interval_index": interval_index,
                        "boundary_side": boundary_side,
                        "boundary_u": boundary_u,
                        "arc_distance": boundary_distance * strand_length,
                    }
                )
    if (
        component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
        or edge_length > maximum_edge_length + 1.0e-10
        or component_arc_length > maximum_component_arc_length + 1.0e-10
        or len(adjacent_forbidden_boundaries) != 1
    ):
        return None
    return {
        "proof_version": "RADIUS_COLLAPSED_SINGLE_EDGE_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": edge_id,
        "coordinates": [tuple(point) for point in coordinates],
        "component_u_interval": [component_start, component_end],
        "edge_length": edge_length,
        "maximum_edge_length": maximum_edge_length,
        "component_arc_length": component_arc_length,
        "maximum_component_arc_length": maximum_component_arc_length,
        "adjacent_forbidden_boundary": adjacent_forbidden_boundaries[0],
        "endpoint_degrees": endpoint_degrees,
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 沿真实 Edge 边界把一条 run 裁为多个 normalized u intervals，避免长侧 fragment
# 同时覆盖对侧多个已分段 fragments 时形成非一一候选。
# run/intervals: 当前 open run 与目标 u intervals；返回互不重叠的真实子 runs。
def _partition_run_by_intervals(run, intervals):
    parameters = [float(value) for value in run["u_values"]]
    edge_midpoints = [
        (start + end) * 0.5
        for start, end in zip(parameters, parameters[1:])
    ]
    buckets = []
    for midpoint in edge_midpoints:
        matching = []
        for interval_index, interval in enumerate(intervals):
            for shift in range(-2, 3):
                lower, upper = sorted(
                    (float(interval[0]) + shift, float(interval[1]) + shift)
                )
                if lower - 1.0e-10 <= midpoint <= upper + 1.0e-10:
                    matching.append((interval_index, shift))
                    break
        buckets.append(min(matching) if matching else None)
    fragments = []
    start = 0
    for index in range(1, len(buckets) + 1):
        if index < len(buckets) and buckets[index] == buckets[start]:
            continue
        if buckets[start] is not None:
            fragment_parameters = parameters[start : index + 1]
            fragments.append(
                {
                    **run,
                    "edge_ids": run["edge_ids"][start:index],
                    "coordinates": run["coordinates"][start : index + 1],
                    "endpoint_tokens": list(
                        run.get("endpoint_tokens", ())
                    )[start : index + 1],
                    "u_values": fragment_parameters,
                    "u_interval": [
                        fragment_parameters[0],
                        fragment_parameters[-1],
                    ],
                }
            )
        start = index
    return tuple(fragments)


# 若一个长 fragment 覆盖多个互不相交的对侧 fragments，则按对侧 intervals 确定性拆分长侧。
# left_runs/right_runs: 同一 Plan atom 两侧 runs；返回共同 component 粒度的两侧 fragments。
def _balance_regular_run_fragments(left_runs, right_runs, cyclic):
    balanced_left = []
    right_intervals = [run["u_interval"] for run in right_runs]
    for run in left_runs:
        overlapping = [
            interval
            for interval in right_intervals
            if _common_run_interval(run["u_interval"], interval, cyclic) is not None
        ]
        balanced_left.extend(
            _partition_run_by_intervals(run, overlapping)
            if len(overlapping) > 1
            else (run,)
        )
    balanced_right = []
    left_intervals = [run["u_interval"] for run in balanced_left]
    for run in right_runs:
        overlapping = [
            interval
            for interval in left_intervals
            if _common_run_interval(run["u_interval"], interval, cyclic) is not None
        ]
        balanced_right.extend(
            _partition_run_by_intervals(run, overlapping)
            if len(overlapping) > 1
            else (run,)
        )
    return tuple(balanced_left), tuple(balanced_right)


# 从原始 run 提取 regular core 两端被 endpoint trim 留下的真实 Edge residues。
# run/core_edge_ids: 当前 provenance run 与已通过门禁的连续 core Edge IDs；返回 START/END residue runs。
def _regular_endpoint_residue_runs(run, core_edge_ids):
    run_edge_ids = list(run["edge_ids"])
    core_edge_ids = list(core_edge_ids)
    if not core_edge_ids:
        return None
    core_indices = [
        run_edge_ids.index(edge_id)
        for edge_id in core_edge_ids
        if edge_id in run_edge_ids
    ]
    if (
        len(core_indices) != len(core_edge_ids)
        or core_indices != list(
            range(core_indices[0], core_indices[0] + len(core_indices))
        )
        or [run_edge_ids[index] for index in core_indices] != core_edge_ids
    ):
        return None
    first_index = core_indices[0]
    last_index = core_indices[-1]
    start_residue = (
        _trim_run_endpoint_edges(
            run,
            0,
            len(run_edge_ids) - first_index,
        )
        if first_index > 0
        else None
    )
    end_residue = (
        _trim_run_endpoint_edges(
            run,
            last_index + 1,
            0,
        )
        if last_index + 1 < len(run_edge_ids)
        else None
    )
    return {
        "START": start_residue,
        "END": end_residue,
    }


# 对两条单 Edge residue 执行严格 linear quad fallback；仅在原 strip 因无单调 path 失败时启用。
# left_run/right_run/strand/radius/rejection: 两侧单 Edge、权威 strand、半径与原拒绝诊断；返回 candidate 或 None。
def _single_edge_linear_regular_pair_candidate(
    left_run,
    right_run,
    strand,
    radius,
    rejection,
):
    if (
        len(left_run.get("edge_ids", ())) != 1
        or len(right_run.get("edge_ids", ())) != 1
    ):
        return None
    accepted_rejection = (
        rejection.get("reason") == "COMMON_INTERVAL_HAS_NO_REAL_EDGE"
        or (
            rejection.get("reason") == "PAIR_WIDTH_ENVELOPE_FAILED"
            and rejection.get("untrimmed_guard", {}).get("status") == "PASS"
            and rejection.get("best_strip_rejection", {}).get("reason")
            == "NO_MONOTONIC_CORRESPONDENCE_PATH"
        )
    )
    if not accepted_rejection:
        return None
    common = _common_run_interval(
        left_run["u_interval"],
        right_run["u_interval"],
        strand.cyclic,
    )
    if common is None:
        return None
    common_interval, right_shift = common
    linear_left = _clip_run_geometry_to_interval(
        left_run,
        common_interval,
    )
    linear_right = _clip_run_geometry_to_interval(
        {
            **right_run,
            "u_values": [
                float(value) + right_shift
                for value in right_run["u_values"]
            ],
            "u_interval": [
                float(right_run["u_interval"][0]) + right_shift,
                float(right_run["u_interval"][1]) + right_shift,
            ],
        },
        common_interval,
    )
    geometry_left, geometry_right = _synchronize_regular_run_geometry_samples(
        linear_left,
        linear_right,
    )
    geometry_left = {
        **geometry_left,
        "coordinates": [
            geometry_left["coordinates"][0],
            geometry_left["coordinates"][-1],
        ],
        "u_values": [
            geometry_left["u_values"][0],
            geometry_left["u_values"][-1],
        ],
    }
    geometry_right = {
        **geometry_right,
        "coordinates": [
            geometry_right["coordinates"][0],
            geometry_right["coordinates"][-1],
        ],
        "u_values": [
            geometry_right["u_values"][0],
            geometry_right["u_values"][-1],
        ],
    }
    synchronized_guard = _regular_pair_width_guard(
        geometry_left,
        geometry_right,
        radius,
    )
    left_coordinates = [
        Vector(point) for point in geometry_left["coordinates"]
    ]
    right_coordinates = [
        Vector(point) for point in geometry_right["coordinates"]
    ]
    quadrilateral = (
        left_coordinates[0],
        left_coordinates[1],
        right_coordinates[1],
        right_coordinates[0],
    )
    quadrilateral_area = sum(
        current.cross(following).length
        for current, following in zip(
            quadrilateral,
            (*quadrilateral[1:], quadrilateral[0]),
        )
    ) * 0.5
    if (
        synchronized_guard["status"] != "PASS"
        or quadrilateral_area <= 1.0e-12
    ):
        return None
    return {
        "left": {
            **geometry_left,
            "edge_ids": list(left_run["edge_ids"]),
        },
        "right": {
            **geometry_right,
            "edge_ids": list(right_run["edge_ids"]),
        },
        "provenance_left_edge_ids": list(left_run["edge_ids"]),
        "provenance_right_edge_ids": list(right_run["edge_ids"]),
        "trim_counts": (0, 0, 0, 0),
        "single_edge_linear_regular_fallback": True,
        "common_u_interval": list(common_interval),
        "left_edge_count": 1,
        "right_edge_count": 1,
        "endpoint_trim_counts": [0, 0, 0, 0],
        "strip_diagnostics": {
            "status": "PASS",
            "path": [[0, 0], [1, 1]],
            "widths": synchronized_guard.get("widths", []),
            "width_errors": synchronized_guard.get("width_errors", []),
            "one_sided_step_count": 0,
            "maximum_relative_advance": 0.0,
        },
        **synchronized_guard,
    }


# 对 endpoint-trim 歧义的短等量 runs 执行同步 Plan-u quad 证明；只接受完整共同覆盖、width 与正面积全部通过的 pair。
# left_run/right_run/strand/radius/rejection: 两侧真实 runs、权威 strand、半径与原拒绝诊断；返回严格 regular candidate 或 None。
def _aligned_linear_regular_pair_candidate(
    left_run,
    right_run,
    strand,
    radius,
    rejection,
):
    left_edge_count = len(left_run.get("edge_ids", ()))
    right_edge_count = len(right_run.get("edge_ids", ()))
    if (
        rejection.get("reason") != "ENDPOINT_TRIM_AMBIGUOUS"
        or rejection.get("minimum_total_trim") != 1
        or rejection.get("candidate_count") != 2
        or left_edge_count != right_edge_count
        or not 2 <= left_edge_count <= 4
    ):
        return None
    candidate_trim_counts = {
        tuple(candidate.get("trim_counts", ()))
        for candidate in rejection.get("candidates", ())
    }
    if candidate_trim_counts != {(0, 0, 1, 0), (1, 0, 0, 0)}:
        return None
    common = _common_run_interval(
        left_run["u_interval"],
        right_run["u_interval"],
        strand.cyclic,
    )
    if common is None:
        return None
    common_interval, right_shift = common
    common_length = common_interval[1] - common_interval[0]
    left_length = max(map(float, left_run["u_interval"])) - min(
        map(float, left_run["u_interval"])
    )
    right_length = max(map(float, right_run["u_interval"])) - min(
        map(float, right_run["u_interval"])
    )
    if (
        common_length <= 1.0e-10
        or common_length < left_length * 0.98 - 1.0e-10
        or common_length < right_length * 0.98 - 1.0e-10
    ):
        return None
    shifted_right = {
        **right_run,
        "u_values": [
            float(value) + right_shift for value in right_run["u_values"]
        ],
        "u_interval": [
            float(right_run["u_interval"][0]) + right_shift,
            float(right_run["u_interval"][1]) + right_shift,
        ],
    }
    linear_left = _clip_run_geometry_to_interval(
        left_run,
        common_interval,
    )
    linear_right = _clip_run_geometry_to_interval(
        shifted_right,
        common_interval,
    )
    geometry_left, geometry_right = _synchronize_regular_run_geometry_samples(
        linear_left,
        linear_right,
    )
    sample_records = [
        {
            "u": float(sample_u),
            "left": Vector(left_point),
            "right": Vector(right_point),
            "left_token": geometry_left["endpoint_tokens"][index],
            "right_token": geometry_right["endpoint_tokens"][index],
        }
        for index, (sample_u, left_point, right_point) in enumerate(
            zip(
                geometry_left["u_values"],
                geometry_left["coordinates"],
                geometry_right["coordinates"],
            )
        )
    ]
    filtered_records = []
    for record in sample_records:
        if filtered_records:
            previous = filtered_records[-1]
            left_step = (record["left"] - previous["left"]).length
            right_step = (record["right"] - previous["right"]).length
            if min(left_step, right_step) <= 1.0e-10:
                if left_step <= 1.0e-10 < right_step:
                    previous["left"] = record["left"]
                    previous["left_token"] = record["left_token"]
                elif right_step <= 1.0e-10 < left_step:
                    previous["right"] = record["right"]
                    previous["right_token"] = record["right_token"]
                previous["u"] = record["u"]
                continue
        filtered_records.append(record)
    geometry_left = {
        **geometry_left,
        "coordinates": [tuple(record["left"]) for record in filtered_records],
        "endpoint_tokens": [
            record["left_token"] for record in filtered_records
        ],
        "u_values": [record["u"] for record in filtered_records],
    }
    geometry_right = {
        **geometry_right,
        "coordinates": [tuple(record["right"]) for record in filtered_records],
        "endpoint_tokens": [
            record["right_token"] for record in filtered_records
        ],
        "u_values": [record["u"] for record in filtered_records],
    }
    left_coordinates = [
        Vector(point) for point in geometry_left["coordinates"]
    ]
    right_coordinates = [
        Vector(point) for point in geometry_right["coordinates"]
    ]
    if (
        len(left_coordinates) != len(right_coordinates)
        or len(left_coordinates) < 3
    ):
        return None
    synchronized_guard = _regular_pair_width_guard(
        geometry_left,
        geometry_right,
        radius,
    )
    expected_width = radius * (2.0 ** 0.5)
    width_tolerance = max(radius * 0.60, 1.0e-5)
    direct_widths = [
        (left_point - right_point).length
        for left_point, right_point in zip(
            left_coordinates,
            right_coordinates,
        )
    ]
    quad_areas = []
    for index in range(len(left_coordinates) - 1):
        quadrilateral = (
            left_coordinates[index],
            left_coordinates[index + 1],
            right_coordinates[index + 1],
            right_coordinates[index],
        )
        normal = Vector()
        for current, following in zip(
            quadrilateral,
            (*quadrilateral[1:], quadrilateral[0]),
        ):
            normal += current.cross(following)
        quad_areas.append(normal.length * 0.5)
    if (
        synchronized_guard["status"] != "PASS"
        or any(
            abs(width - expected_width) > width_tolerance
            for width in direct_widths
        )
        or any(area <= 1.0e-12 for area in quad_areas)
    ):
        return None
    return {
        "left": {
            **geometry_left,
            "edge_ids": list(left_run["edge_ids"]),
        },
        "right": {
            **geometry_right,
            "edge_ids": list(right_run["edge_ids"]),
        },
        "provenance_left_edge_ids": list(left_run["edge_ids"]),
        "provenance_right_edge_ids": list(right_run["edge_ids"]),
        "trim_counts": (0, 0, 0, 0),
        "aligned_linear_regular_fallback": True,
        "common_u_interval": list(common_interval),
        "left_edge_count": left_edge_count,
        "right_edge_count": right_edge_count,
        "endpoint_trim_counts": [0, 0, 0, 0],
        "strip_diagnostics": {
            "status": "PASS",
            "path": [[index, index] for index in range(len(left_coordinates))],
            "widths": direct_widths,
            "width_errors": [
                abs(width - expected_width) for width in direct_widths
            ],
            "one_sided_step_count": 0,
            "maximum_relative_advance": 0.0,
            "quad_areas": quad_areas,
        },
        **synchronized_guard,
    }


# 对 cyclic full-span rail 使用真实 Edge 顺序建立一条完整 Regular Strip；
# left_run/right_run/strand/radius: 两侧完整 open rail、FeatureStrand 与半径；返回严格 geometry guard candidate 或 None。
def _full_cyclic_regular_pair_candidate(left_run, right_run, strand, radius):
    if (
        not strand.cyclic
        or left_run.get("component_u_interval")
        != right_run.get("component_u_interval")
        or len(left_run.get("edge_ids", ())) < 3
        or len(right_run.get("edge_ids", ())) < 3
    ):
        return None, {"reason": "NOT_FULL_CYCLIC_PAIR"}
    if not left_run.get("full_cyclic_atom") or not right_run.get(
        "full_cyclic_atom"
    ):
        return None, {"reason": "FULL_CYCLIC_MARKER_MISSING"}
    aligned_left = left_run
    aligned_right = right_run
    width_guard = _regular_pair_width_guard(aligned_left, aligned_right, radius)
    strip = build_chamfer_strip(
        [Vector(point) for point in aligned_left["coordinates"]],
        [Vector(point) for point in aligned_right["coordinates"]],
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(
                len(aligned_left["coordinates"]) - 1,
                len(aligned_right["coordinates"]) - 1,
            )],
            "expected_width": radius * (2.0 ** 0.5),
            "maximum_width_error": max(radius * 0.60, 1.0e-5),
            "reject_zero_area_faces": True,
            "prefer_hard_guard_path": True,
        },
    )
    if (
        width_guard["status"] != "PASS"
        or strip["diagnostics"]["status"] != "PASS"
        or not strip["faces"]
        or _strip_zero_area_face_count(
            strip,
            [Vector(point) for point in aligned_left["coordinates"]],
            [Vector(point) for point in aligned_right["coordinates"]],
        )
    ):
        return None, {
            "reason": "FULL_CYCLIC_GEOMETRY_GUARD",
            "width_guard": width_guard,
            "strip_diagnostics": strip["diagnostics"],
            "zero_area_face_count": _strip_zero_area_face_count(
                strip,
                [Vector(point) for point in aligned_left["coordinates"]],
                [Vector(point) for point in aligned_right["coordinates"]],
            ),
        }
    return {
        "left": aligned_left,
        "right": aligned_right,
        "trim_counts": (0, 0, 0, 0),
        "width_inlier_ratio": width_guard["width_inlier_ratio"],
        "maximum_width_error": width_guard["maximum_width_error"],
        "strip_diagnostics": strip["diagnostics"],
        "full_cyclic_regular_pair": True,
    }, None


# 递归证明 endpoint trim 两端成对留下的 residues，禁止已知双侧 regular 残段静默转成 setback。
# left_run/right_run/core_candidate/strand/radius/depth: 原 pair、已通过 core、权威 strand、半径与递归深度；返回 residue matches 或拒绝诊断。
def _paired_regular_endpoint_residue_matches(
    left_run,
    right_run,
    core_candidate,
    strand,
    radius,
    depth=0,
):
    if depth > 8:
        return None, {"reason": "REGULAR_ENDPOINT_RESIDUE_DEPTH_EXCEEDED"}
    left_residues = _regular_endpoint_residue_runs(
        left_run,
        core_candidate["left"]["edge_ids"],
    )
    right_residues = _regular_endpoint_residue_runs(
        right_run,
        core_candidate["right"]["edge_ids"],
    )
    if left_residues is None or right_residues is None:
        return None, {"reason": "REGULAR_ENDPOINT_RESIDUE_PROVENANCE_INVALID"}
    residue_matches = []
    for endpoint_role in ("START", "END"):
        left_residue = left_residues[endpoint_role]
        right_residue = right_residues[endpoint_role]
        if left_residue is None and right_residue is None:
            continue
        if left_residue is None or right_residue is None:
            continue
        common = _common_run_interval(
            left_residue["u_interval"],
            right_residue["u_interval"],
            strand.cyclic,
        )
        if common is None:
            continue
        common_interval, _ = common
        left_residue_lower, left_residue_upper = sorted(
            map(float, left_residue["u_interval"])
        )
        right_residue_lower, right_residue_upper = sorted(
            map(float, right_residue["u_interval"])
        )
        shared_coverage = common_interval[1] - common_interval[0]
        minimum_residue_coverage = min(
            left_residue_upper - left_residue_lower,
            right_residue_upper - right_residue_lower,
        )
        if shared_coverage < minimum_residue_coverage * 0.90 - 1.0e-10:
            continue
        residue_candidate, rejection = _regular_run_pair_evaluation(
            left_residue,
            right_residue,
            strand,
            radius,
        )
        if residue_candidate is None:
            residue_candidate = _single_edge_linear_regular_pair_candidate(
                left_residue,
                right_residue,
                strand,
                radius,
                rejection,
            )
        if residue_candidate is None:
            residue_candidate = _aligned_linear_regular_pair_candidate(
                left_residue,
                right_residue,
                strand,
                radius,
                rejection,
            )
        if residue_candidate is None:
            return None, {
                "reason": "REGULAR_ENDPOINT_RESIDUE_UNPROVEN",
                "endpoint_role": endpoint_role,
                "left_edge_ids": list(left_residue["edge_ids"]),
                "right_edge_ids": list(right_residue["edge_ids"]),
                "pair_rejection": rejection,
            }
        nested_matches, nested_rejection = (
            _paired_regular_endpoint_residue_matches(
                left_residue,
                right_residue,
                residue_candidate,
                strand,
                radius,
                depth + 1,
            )
        )
        if nested_matches is None:
            return None, nested_rejection
        residue_matches.extend((residue_candidate, *nested_matches))
    return tuple(residue_matches), None


# 对单个 Plan correspondence 的多条 open rail runs 建立唯一 component matching。
# correspondence/left_runs/right_runs/strand/radius: 语义 pair 与局部 regular runs；返回 matched pairs 和诊断。
def _match_regular_run_components(
    correspondence,
    left_runs,
    right_runs,
    strand,
    radius,
):
    strand_length = _feature_strand_arc_length(strand)
    left_runs = _stitch_contiguous_regular_runs(
        left_runs,
        radius,
        strand_length,
        strand.cyclic,
    )
    right_runs = _stitch_contiguous_regular_runs(
        right_runs,
        radius,
        strand_length,
        strand.cyclic,
    )
    normalized_sides = []
    micro_loop_proofs = []
    for side, runs in (("LEFT", left_runs), ("RIGHT", right_runs)):
        normalized = []
        for run in runs:
            current, zero_length_proofs = _defer_zero_length_run_edges(
                run,
                radius,
            )
            if current is None:
                micro_loop_proofs.extend(
                    {**proof, "side": side}
                    for proof in zero_length_proofs
                )
                continue
            current, loop_proofs = _defer_stitched_micro_loops(current, radius)
            if current is None:
                normalized.append(run)
                continue
            normalized.append(current)
            micro_loop_proofs.extend(
                {**proof, "side": side}
                for proof in (*zero_length_proofs, *loop_proofs)
            )
        normalized_sides.append(tuple(normalized))
    left_runs, right_runs = normalized_sides
    non_monotonic_runs = [
        (side, run)
        for side, runs in (("LEFT", left_runs), ("RIGHT", right_runs))
        for run in runs
        if any(
            following + 1.0e-8 < current
            for current, following in zip(run["u_values"], run["u_values"][1:])
        )
    ]
    if non_monotonic_runs:
        return (), (
            {
                "correspondence_id": correspondence.correspondence_id,
                "left_run_ids": [
                    _stable_fingerprint(run["edge_ids"])
                    for side, run in non_monotonic_runs
                    if side == "LEFT"
                ],
                "right_run_ids": [
                    _stable_fingerprint(run["edge_ids"])
                    for side, run in non_monotonic_runs
                    if side == "RIGHT"
                ],
                "solution_count_capped": 0,
                "left_runs": [
                    {
                        "run_id": _stable_fingerprint(run["edge_ids"]),
                        "edge_count": len(run["edge_ids"]),
                        "edge_ids": list(run["edge_ids"]),
                        "coordinates": list(run["coordinates"]),
                        "u_values": list(run["u_values"]),
                        "u_interval": list(run["u_interval"]),
                        "branch_setback": bool(run.get("branch_setback")),
                    }
                    for side, run in non_monotonic_runs
                    if side == "LEFT"
                ],
                "right_runs": [
                    {
                        "run_id": _stable_fingerprint(run["edge_ids"]),
                        "edge_count": len(run["edge_ids"]),
                        "edge_ids": list(run["edge_ids"]),
                        "coordinates": list(run["coordinates"]),
                        "u_values": list(run["u_values"]),
                        "u_interval": list(run["u_interval"]),
                        "branch_setback": bool(run.get("branch_setback")),
                    }
                    for side, run in non_monotonic_runs
                    if side == "RIGHT"
                ],
                    "reason": "NON_MONOTONIC_U",
                    "micro_loop_junction_proofs": list(micro_loop_proofs),
                },
            )
    left_runs, right_runs = _balance_regular_run_fragments(
        left_runs,
        right_runs,
        strand.cyclic,
    )
    left_by_id = {
        _stable_fingerprint(run["edge_ids"]): run for run in left_runs
    }
    right_by_id = {
        _stable_fingerprint(run["edge_ids"]): run for run in right_runs
    }
    candidate_records = {}
    rejected_candidate_records = {}
    adjacency_left = {run_id: set() for run_id in left_by_id}
    adjacency_right = {run_id: set() for run_id in right_by_id}
    for left_id, left_run in sorted(left_by_id.items()):
        for right_id, right_run in sorted(right_by_id.items()):
            candidate, rejection = _full_cyclic_regular_pair_candidate(
                left_run,
                right_run,
                strand,
                radius,
            )
            full_cyclic_pair = bool(
                left_run.get("full_cyclic_atom")
                and right_run.get("full_cyclic_atom")
            )
            if candidate is None and not full_cyclic_pair:
                candidate, rejection = _regular_run_pair_evaluation(
                    left_run,
                    right_run,
                    strand,
                    radius,
                    allow_cyclic_shift=not (
                        left_run.get("component_id")
                        and right_run.get("component_id")
                    ),
                )
            if candidate is None and not full_cyclic_pair:
                candidate = _single_edge_linear_regular_pair_candidate(
                    left_run,
                    right_run,
                    strand,
                    radius,
                    rejection,
                )
            if candidate is None and not full_cyclic_pair:
                candidate = _aligned_linear_regular_pair_candidate(
                    left_run,
                    right_run,
                    strand,
                    radius,
                    rejection,
                )
            if candidate is not None:
                residue_matches, residue_rejection = (
                    _paired_regular_endpoint_residue_matches(
                        left_run,
                        right_run,
                        candidate,
                        strand,
                        radius,
                    )
                )
                if residue_matches is None:
                    rejection = residue_rejection
                    candidate = None
                else:
                    candidate = {
                        **candidate,
                        "endpoint_residue_matches": list(residue_matches),
                    }
            if candidate is None:
                if rejection.get("reason") != "U_INTERVAL_DISJOINT":
                    rejected_candidate_records.setdefault(left_id, {})[
                        right_id
                    ] = rejection
                continue
            candidate_records[(left_id, right_id)] = candidate
            adjacency_left[left_id].add(right_id)
            adjacency_right[right_id].add(left_id)
    matched = []
    unresolved = []
    visited_left = set()
    visited_right = set()
    for seed_side, seed_id in [
        *(("L", run_id) for run_id in sorted(left_by_id)),
        *(("R", run_id) for run_id in sorted(right_by_id)),
    ]:
        if (seed_side == "L" and seed_id in visited_left) or (
            seed_side == "R" and seed_id in visited_right
        ):
            continue
        component_left = set()
        component_right = set()
        stack = [(seed_side, seed_id)]
        while stack:
            side, run_id = stack.pop()
            if side == "L":
                if run_id in component_left:
                    continue
                component_left.add(run_id)
                stack.extend(("R", value) for value in adjacency_left[run_id])
            else:
                if run_id in component_right:
                    continue
                component_right.add(run_id)
                stack.extend(("L", value) for value in adjacency_right[run_id])
        visited_left |= component_left
        visited_right |= component_right
        solutions = (
            _unique_perfect_matching(
                component_left,
                component_right,
                adjacency_left,
            )
            if len(component_left) == len(component_right)
            else ()
        )
        if len(solutions) != 1:
            unresolved.append(
                {
                    "correspondence_id": correspondence.correspondence_id,
                    "left_run_ids": sorted(component_left),
                    "right_run_ids": sorted(component_right),
                    "solution_count_capped": len(solutions),
                    "left_runs": [
                        {
                            "run_id": run_id,
                            "edge_count": len(left_by_id[run_id]["edge_ids"]),
                            "edge_ids": list(left_by_id[run_id]["edge_ids"]),
                            "coordinates": list(left_by_id[run_id]["coordinates"]),
                            "u_values": list(left_by_id[run_id]["u_values"]),
                            "u_interval": [
                                round(float(value), 10)
                                for value in left_by_id[run_id]["u_interval"]
                            ],
                            "branch_setback": bool(
                                left_by_id[run_id].get("branch_setback")
                            ),
                            "junction_endpoint_tokens_by_edge": dict(
                                left_by_id[run_id].get(
                                    "junction_endpoint_tokens_by_edge",
                                    {},
                                )
                            ),
                            "endpoint_degrees_by_edge": dict(
                                left_by_id[run_id].get(
                                    "endpoint_degrees_by_edge",
                                    {},
                                )
                            ),
                            "candidate_right_run_ids": sorted(
                                adjacency_left[run_id]
                            ),
                            "rejected_right_runs": {
                                right_id: rejected_candidate_records.get(
                                    run_id,
                                    {},
                                )[right_id]
                                for right_id in sorted(
                                    rejected_candidate_records.get(run_id, {})
                                )
                            },
                        }
                        for run_id in sorted(component_left)
                    ],
                    "right_runs": [
                        {
                            "run_id": run_id,
                            "edge_count": len(right_by_id[run_id]["edge_ids"]),
                            "edge_ids": list(right_by_id[run_id]["edge_ids"]),
                            "coordinates": list(right_by_id[run_id]["coordinates"]),
                            "u_values": list(right_by_id[run_id]["u_values"]),
                            "u_interval": [
                                round(float(value), 10)
                                for value in right_by_id[run_id]["u_interval"]
                            ],
                            "branch_setback": bool(
                                right_by_id[run_id].get("branch_setback")
                            ),
                            "junction_endpoint_tokens_by_edge": dict(
                                right_by_id[run_id].get(
                                    "junction_endpoint_tokens_by_edge",
                                    {},
                                )
                            ),
                            "endpoint_degrees_by_edge": dict(
                                right_by_id[run_id].get(
                                    "endpoint_degrees_by_edge",
                                    {},
                                )
                            ),
                            "candidate_left_run_ids": sorted(
                                adjacency_right[run_id]
                            ),
                            "rejected_left_runs": {
                                left_id: rejected_candidate_records.get(
                                    left_id,
                                    {},
                                )[run_id]
                                for left_id in sorted(left_by_id)
                                if run_id
                                in rejected_candidate_records.get(left_id, {})
                            },
                        }
                        for run_id in sorted(component_right)
                    ],
                    "reason": (
                        "NO_PERFECT_MATCHING"
                        if not solutions
                        else "AMBIGUOUS_PERFECT_MATCHING"
                    ),
                    "micro_loop_junction_proofs": list(micro_loop_proofs),
                }
            )
            continue
        for left_id, right_id in solutions[0]:
            candidate = candidate_records[(left_id, right_id)]
            matched.append(
                {
                    "left_run_id": left_id,
                    "right_run_id": right_id,
                    "micro_loop_junction_proofs": list(micro_loop_proofs),
                    **candidate,
                }
            )
    return tuple(matched), tuple(unresolved)


# 从已唯一匹配并裁切的真实 rail runs 生成 Strip Faces 与 ledger 消费记录。
# correspondence/match/pipe_id/radius/ledger_by_edge_id: 语义 pair、唯一 matching、owner Pipe、半径与 ledger；返回 record 或失败诊断。
def _build_regular_record_from_match(
    correspondence,
    match,
    pipe_id,
    radius,
    ledger_by_edge_id,
    atom=None,
):
    left_core = match["left"]
    right_core = match["right"]
    left_open = [Vector(point) for point in left_core["coordinates"]]
    right_open = [Vector(point) for point in right_core["coordinates"]]
    if len(left_open) < 2 or len(right_open) < 2:
        return None, {"reason": "REGULAR_COMPONENT_TOO_SHORT"}
    expected_width = radius * (2.0 ** 0.5)
    width_tolerance = max(radius * 0.60, 1.0e-5)
    if (
        (
            match.get("single_edge_linear_regular_fallback")
            or match.get("aligned_linear_regular_fallback")
        )
        and len(left_open) == len(right_open)
        and len(left_open) >= 2
    ):
        linear_faces = tuple(
            (
                ("A", index),
                ("A", index + 1),
                ("B", index + 1),
                ("B", index),
            )
            for index in range(len(left_open) - 1)
        )
        strip = {
            "faces": linear_faces,
            "diagnostics": match["strip_diagnostics"],
        }
    else:
        strip = build_chamfer_strip(
            left_open,
            right_open,
            terminal_constraints={
                "start_pairs": [(0, 0)],
                "end_pairs": [(len(left_open) - 1, len(right_open) - 1)],
                "expected_width": expected_width,
                "maximum_width_error": width_tolerance,
                "reject_zero_area_faces": True,
                "prefer_hard_guard_path": True,
            },
        )
    if strip["diagnostics"]["status"] != "PASS" or not strip["faces"]:
        return None, {
            "reason": "STRIP_GEOMETRY_GUARD",
            "diagnostics": strip["diagnostics"],
            "single_edge_linear_regular_fallback": match.get(
                "single_edge_linear_regular_fallback"
            ),
            "aligned_linear_regular_fallback": match.get(
                "aligned_linear_regular_fallback"
            ),
            "left_coordinate_count": len(left_open),
            "right_coordinate_count": len(right_open),
        }
    coordinates_a = [
        tuple(round(float(value), 8) for value in point) for point in left_open
    ]
    coordinates_b = [
        tuple(round(float(value), 8) for value in point) for point in right_open
    ]
    faces = [
        [
            coordinates_a[index] if side == "A" else coordinates_b[index]
            for side, index in face
        ]
        for face in strip["faces"]
    ]
    zero_area_face_count = 0
    for face in faces:
        coordinates = [Vector(point) for point in face]
        normal = Vector()
        for index, coordinate in enumerate(coordinates):
            normal += coordinate.cross(
                coordinates[(index + 1) % len(coordinates)]
            )
        if normal.length <= 1.0e-12:
            zero_area_face_count += 1
    if zero_area_face_count:
        return None, {
            "reason": "STRIP_ZERO_AREA_FACE",
            "zero_area_face_count": zero_area_face_count,
            "geometry_guard": strip["diagnostics"],
        }
    consumed_edge_ids = set(left_core["edge_ids"] + right_core["edge_ids"])
    regular_edge_ids = set(consumed_edge_ids)
    extension_records = []
    # Boundary Edge 只有进入生成 Faces 的两侧 core 才属于 Regular consumer；
    # atom 外侧 terminal Edge 必须由后续 structural handoff 单独证明和消费。
    allow_terminal_extensions = False
    atom_start, atom_end = (
        sorted(map(float, atom["u_interval"]))
        if allow_terminal_extensions
        else (0.0, 0.0)
    )
    for side, core in (("LEFT", left_core), ("RIGHT", right_core)):
        if not allow_terminal_extensions:
            continue
        core_endpoint_tokens = list(core.get("endpoint_tokens", ()))
        if len(core_endpoint_tokens) < 2:
            continue
        endpoint_roles = (
            ("START", core_endpoint_tokens[0]),
            ("END", core_endpoint_tokens[-1]),
        )
        for endpoint_role, endpoint_token in endpoint_roles:
            core_start, core_end = sorted(map(float, core["u_interval"]))
            if (
                endpoint_role == "START"
                and abs(core_start - atom_start) > 1.0e-8
            ) or (
                endpoint_role == "END"
                and abs(core_end - atom_end) > 1.0e-8
            ):
                continue
            candidates = []
            for ledger_entry in ledger_by_edge_id.values():
                if (
                    ledger_entry["edge_id"] in regular_edge_ids
                    or ledger_entry["classification"] != "UNCLASSIFIED"
                    or ledger_entry["strand_id"]
                    != correspondence.owner_strand_id
                    or ledger_entry["source_patch_id"]
                    != correspondence.owner_surface_pair[
                        0 if side == "LEFT" else 1
                    ]
                    or endpoint_token not in ledger_entry["endpoint_tokens"]
                    or "strand_u_interval" not in ledger_entry
                ):
                    continue
                candidate_start, candidate_end = map(
                    float, ledger_entry["strand_u_interval"]
                )
                outward = (
                    endpoint_role == "START"
                    and candidate_end <= atom_start + 1.0e-8
                    and candidate_start < atom_start - 1.0e-10
                ) or (
                    endpoint_role == "END"
                    and candidate_start >= atom_end - 1.0e-8
                    and candidate_end > atom_end + 1.0e-10
                )
                if not outward:
                    continue
                candidates.append(ledger_entry)
            if len(candidates) != 1:
                continue
            candidate = candidates[0]
            coordinates = [Vector(point) for point in candidate["endpoints"]]
            edge_length = (coordinates[1] - coordinates[0]).length
            candidate_endpoint_tokens = list(candidate["endpoint_tokens"])
            outer_tokens = set(candidate_endpoint_tokens) - {endpoint_token}
            rail_entries = [
                entry
                for entry in ledger_by_edge_id.values()
                if entry["rail_id"] == candidate["rail_id"]
            ]
            outer_degrees = sorted(
                sum(token in entry["endpoint_tokens"] for entry in rail_entries)
                for token in outer_tokens
            )
            shared_degree = sum(
                endpoint_token in entry["endpoint_tokens"]
                for entry in rail_entries
            )
            if (
                edge_length > radius * 2.0 + 1.0e-10
                or len(outer_tokens) != 1
                or outer_degrees != [1]
                or shared_degree != 2
            ):
                continue
            regular_edge_ids.add(candidate["edge_id"])
            extension_records.append(
                {
                    "edge_id": candidate["edge_id"],
                    "side": side,
                    "endpoint_role": endpoint_role,
                    "shared_endpoint_token": endpoint_token,
                    "outer_endpoint_token": next(iter(outer_tokens)),
                    "outer_endpoint_degree": outer_degrees[0],
                    "edge_length": edge_length,
                    "atom_id": atom["atom_id"],
                    "span_id": int(atom["span_id"]),
                    "convexity": int(atom["convexity"]),
                    "candidate_u_interval": list(
                        candidate["strand_u_interval"]
                    ),
                    "outward_side": endpoint_role,
                }
            )
    consumed_edge_ids = regular_edge_ids
    consumer_id = (
        f"regular:{correspondence.correspondence_id}:"
        + _stable_fingerprint(
            [
                left_core["edge_ids"],
                right_core["edge_ids"],
                sorted(record["edge_id"] for record in extension_records),
            ]
        )[:20]
    )
    for edge_id in consumed_edge_ids:
        if ledger_by_edge_id[edge_id]["classification"] != "UNCLASSIFIED":
            raise BatchedChamferError(
                "REGULAR_CORE_LEDGER_CONFLICT",
                "真实 Boundary Edge 被多个 Regular Strip 消费",
                {
                    "edge_id": edge_id,
                    "existing_consumer_id": ledger_by_edge_id[edge_id][
                        "consumer_id"
                    ],
                    "current_consumer_id": consumer_id,
                    "current_atom_id": atom["atom_id"] if atom else None,
                    "current_correspondence_id": correspondence.correspondence_id,
                    "current_left_u_interval": list(left_core["u_interval"]),
                    "current_right_u_interval": list(right_core["u_interval"]),
                },
            )
        ledger_by_edge_id[edge_id]["classification"] = "REGULAR_STRIP_CONSUMED"
        ledger_by_edge_id[edge_id]["consumer_id"] = consumer_id
    return (
        {
            "consumer_id": consumer_id,
            "pipe_id": int(pipe_id),
            "strand_id": correspondence.owner_strand_id,
            "correspondence_id": correspondence.correspondence_id,
            "patch_pair": list(correspondence.owner_surface_pair),
            "left_edge_ids": left_core["edge_ids"],
            "right_edge_ids": right_core["edge_ids"],
            "terminal_extension_edge_ids": sorted(
                record["edge_id"] for record in extension_records
            ),
            "left_u_interval": list(left_core["u_interval"]),
            "right_u_interval": list(right_core["u_interval"]),
        "terminal_extension_records": extension_records,
        "atom_id": atom["atom_id"] if atom is not None else None,
        "span_id": int(atom["span_id"]) if atom is not None else None,
            "micro_loop_junction_proofs": list(
                match.get("micro_loop_junction_proofs", ())
            ),
        "u_interval": [
            round(
                max(
                    min(map(float, left_core["u_interval"])),
                    min(map(float, right_core["u_interval"])),
                ),
                10,
            ),
            round(
                min(
                    max(map(float, left_core["u_interval"])),
                    max(map(float, right_core["u_interval"])),
                ),
                10,
            ),
        ],
        "virtual_atom_boundaries": {
            "left": list(left_core.get("virtual_atom_boundaries", ())),
            "right": list(right_core.get("virtual_atom_boundaries", ())),
        },
        "virtual_regular_samples": {
            "left": list(left_core.get("virtual_regular_samples", ())),
            "right": list(right_core.get("virtual_regular_samples", ())),
        },
        "faces": faces,
            "face_count": len(faces),
            "geometry_guard": {
                **strip["diagnostics"],
                "endpoint_trim_counts": list(
                    match.get("endpoint_trim_counts", ())
                ),
                "pair_width_inlier_ratio": match["width_inlier_ratio"],
                "pair_maximum_width_error": match["maximum_width_error"],
            },
        },
        None,
    )


# 返回 Feature group 中每个连续 Patch pair span 的 normalized u intervals。
# group: 已冻结 Preview Pipe group；返回 correspondence patch pair→可含 wrap 的 intervals。
def _group_correspondence_span_records(group):
    points = group["points"]
    segment_count = len(group["edge_indices"])
    lengths = [
        (points[(index + 1) % len(points)] - points[index]).length
        for index in range(segment_count)
    ]
    total = sum(lengths)
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    records_by_pair = {}
    for span in _group_patch_pair_spans(group):
        ordered_offsets = [int(value) for value in span["edge_offsets"]]
        runs = []
        start = ordered_offsets[0]
        previous = ordered_offsets[0]
        for offset in ordered_offsets[1:]:
            if offset != previous + 1:
                runs.append((start, previous + 1))
                start = offset
            previous = offset
        runs.append((start, previous + 1))
        if (
            group["is_cyclic"]
            and len(runs) == 2
            and runs[0][1] == segment_count
            and runs[1][0] == 0
        ):
            runs = [(runs[0][0], runs[1][1] + segment_count)]
        intervals = [
            [
                cumulative[start] / total if total > 1.0e-12 else 0.0,
                (
                    cumulative[end - segment_count] / total + 1.0
                    if end > segment_count and total > 1.0e-12
                    else cumulative[end] / total if total > 1.0e-12 else 0.0
                ),
            ]
            for start, end in runs
        ]
        patch_pair = tuple(span["patch_pair"])
        records_by_pair.setdefault(patch_pair, []).extend(
            {
                "span_id": int(span["span_id"]),
                "patch_pair": list(patch_pair),
                "convexity": int(span["convexity"]),
                "u_interval": interval,
            }
            for interval in intervals
        )
    return {
        patch_pair: tuple(
            sorted(records, key=lambda record: (record["span_id"], record["u_interval"]))
        )
        for patch_pair, records in sorted(records_by_pair.items())
    }


# 从 Plan span 减去 overlap forbidden intervals，生成 canonical regular atoms。
# span_intervals/forbidden_intervals/cyclic: Plan span、overlap intervals 与闭合标记；返回稳定 atom records。
def _regular_plan_atoms(span_records, forbidden_intervals, cyclic):
    base_segments = []
    for span_record in span_records:
        start, end = span_record["u_interval"]
        start = float(start)
        end = float(end)
        if cyclic and end < start:
            base_segments.extend(
                (
                    (start, 1.0, span_record),
                    (0.0, end, span_record),
                )
            )
        else:
            span_start, span_end = sorted((start, end))
            base_segments.append((span_start, span_end, span_record))
    forbidden_segments = [tuple(sorted(map(float, interval))) for interval in forbidden_intervals]
    atoms = []
    for span_start, span_end, span_record in base_segments:
        remaining = [(span_start, span_end)]
        lifted_forbidden_segments = {
            (forbidden_start + shift, forbidden_end + shift)
            for forbidden_start, forbidden_end in forbidden_segments
            for shift in (range(-2, 3) if cyclic else (0,))
            if max(span_start, forbidden_start + shift)
            < min(span_end, forbidden_end + shift) - 1.0e-10
        }
        for forbidden_start, forbidden_end in sorted(lifted_forbidden_segments):
            next_remaining = []
            for current_start, current_end in remaining:
                if forbidden_end <= current_start or forbidden_start >= current_end:
                    next_remaining.append((current_start, current_end))
                    continue
                if current_start < forbidden_start:
                    next_remaining.append((current_start, forbidden_start))
                if forbidden_end < current_end:
                    next_remaining.append((forbidden_end, current_end))
            remaining = next_remaining
        atoms.extend(
            (start, end, span_record)
            for start, end in remaining
        )
    atoms = [
        (round(float(start), 10), round(float(end), 10), span_record)
        for start, end, span_record in atoms
        if end - start > 1.0e-8
    ]
    if (
        cyclic
        and len(atoms) > 1
        and atoms[0][0] <= 1.0e-10
        and atoms[-1][1] >= 1.0 - 1.0e-10
        and atoms[0][2]["span_id"] == atoms[-1][2]["span_id"]
    ):
        wrapped = (atoms[-1][0], atoms[0][1] + 1.0, atoms[0][2])
        atoms = [wrapped, *atoms[1:-1]]
    return tuple(
        {
            "atom_id": _stable_fingerprint(
                [
                    int(span_record["span_id"]),
                    int(span_record["convexity"]),
                    list(span_record["patch_pair"]),
                    start,
                    end,
                ]
            )[:20],
            "span_id": int(span_record["span_id"]),
            "patch_pair": list(span_record["patch_pair"]),
            "convexity": int(span_record["convexity"]),
            "u_interval": [start, end],
            "cyclic": bool(cyclic),
        }
        for start, end, span_record in sorted(
            atoms,
            key=lambda item: (item[0], item[1], item[2]["span_id"]),
        )
    )


# 把 run 的 u lift 对齐到 Plan atom，并沿真实 Edge midpoint 裁入 atom。
# run/atom/cyclic: Boundary run、Plan atom 与闭合标记；返回 canonical lift fragment 或 None。
def _trim_run_to_plan_atom(run, atom, cyclic):
    atom_start, atom_end = map(float, atom["u_interval"])
    shifts = range(-2, 3) if cyclic else (0,)
    best = None
    for shift in shifts:
        shifted_interval = [
            float(run["u_interval"][0]) + shift,
            float(run["u_interval"][1]) + shift,
        ]
        common = _common_run_interval(
            shifted_interval,
            [atom_start, atom_end],
            False,
        )
        if common is None:
            continue
        common_interval, _ = common
        candidate = (common_interval[1] - common_interval[0], -abs(shift), shift)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    shift = best[2]
    shifted = {
        **run,
        "u_values": [float(value) + shift for value in run["u_values"]],
        "u_interval": [
            float(run["u_interval"][0]) + shift,
            float(run["u_interval"][1]) + shift,
        ],
    }
    trimmed = _trim_open_run_to_interval(
        shifted,
        [atom_start, atom_end],
    )
    if trimmed is None or not trimmed["edge_ids"]:
        return None
    return {
        **trimmed,
        "atom_id": atom["atom_id"],
        "atom_u_interval": list(atom["u_interval"]),
    }


# 在 Plan atom 边界对 crossing Boundary Edge 创建 regular geometry 虚拟端点；ledger 仍消费原始 Edge ID。
# run/interval: 已按 atom lift 的真实 run 与权威 atom interval；返回只改变几何端点、不拆分 provenance 的 run。
def _clip_run_geometry_to_interval(run, interval):
    parameters = [float(value) for value in run["u_values"]]
    coordinates = [Vector(point) for point in run["coordinates"]]
    lower, upper = sorted(map(float, interval))
    if len(parameters) != len(coordinates):
        raise BatchedChamferError(
            "REGULAR_RUN_PARAMETER_COUNT_MISMATCH",
            "Regular run 的坐标与 FeatureStrand 参数数量不一致",
            {
                "edge_ids": list(run["edge_ids"]),
                "coordinate_count": len(coordinates),
                "parameter_count": len(parameters),
            },
        )
    clipped = list(coordinates)
    clipped_parameters = list(parameters)
    virtual_boundaries = []
    endpoint_boundaries = (
        (
            (0, lower, "START"),
            (len(parameters) - 1, upper, "END"),
        )
        if parameters[-1] >= parameters[0]
        else (
            (0, upper, "END"),
            (len(parameters) - 1, lower, "START"),
        )
    )
    for point_index, boundary_u, endpoint_role in endpoint_boundaries:
        current_u = clipped_parameters[point_index]
        outside = current_u < lower - 1.0e-10 or current_u > upper + 1.0e-10
        if not outside:
            continue
        neighbor_index = 1 if point_index == 0 else len(parameters) - 2
        neighbor_u = clipped_parameters[neighbor_index]
        span = neighbor_u - current_u
        if abs(span) <= 1.0e-12 or not (
            min(current_u, neighbor_u) - 1.0e-10
            <= boundary_u
            <= max(current_u, neighbor_u) + 1.0e-10
        ):
            raise BatchedChamferError(
                "CROSS_ATOM_BOUNDARY_INTERPOLATION_INVALID",
                "Cross-atom Boundary Edge 无法在权威 Plan atom 边界生成虚拟端点",
                {
                    "edge_ids": list(run["edge_ids"]),
                    "u_values": parameters,
                    "atom_interval": [lower, upper],
                    "endpoint_role": endpoint_role,
                },
            )
        factor = (boundary_u - current_u) / span
        clipped[point_index] = coordinates[point_index].lerp(
            coordinates[neighbor_index],
            factor,
        )
        clipped_parameters[point_index] = boundary_u
        edge_index = 0 if point_index == 0 else len(run["edge_ids"]) - 1
        virtual_boundaries.append(
            {
                "endpoint_role": endpoint_role,
                "boundary_u": boundary_u,
                "source_edge_id": run["edge_ids"][edge_index],
                "source_edge_factor": factor,
                "coordinate": tuple(clipped[point_index]),
            }
        )
    if clipped_parameters[-1] + 1.0e-10 < clipped_parameters[0]:
        clipped.reverse()
        clipped_parameters.reverse()
        reversed_edge_ids = list(reversed(run["edge_ids"]))
        if run.get("is_cyclic") and reversed_edge_ids:
            reversed_edge_ids = [*reversed_edge_ids[1:], reversed_edge_ids[0]]
        virtual_boundaries = [
            {
                **boundary,
                "source_edge_factor": 1.0
                - float(boundary["source_edge_factor"]),
            }
            for boundary in reversed(virtual_boundaries)
        ]
    else:
        reversed_edge_ids = list(run["edge_ids"])
    return {
        **run,
        "edge_ids": reversed_edge_ids,
        "coordinates": [tuple(point) for point in clipped],
        "u_values": clipped_parameters,
        "u_interval": [clipped_parameters[0], clipped_parameters[-1]],
        "virtual_atom_boundaries": virtual_boundaries,
    }


# 计算 atom 中左右 fragments 共同覆盖的 u components；只使用 interval topology，不用距离打分。
# left_runs/right_runs/atom: atom 两侧 fragments 与 Plan atom；返回共同覆盖 intervals。
def _common_atom_component_intervals(left_runs, right_runs, atom):
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    boundaries = sorted(
        {
            round(float(value), 10)
            for value in atom["u_interval"]
        }
        | {
            round(float(value), 10)
            for run in (*left_runs, *right_runs)
            for value in run["u_interval"]
        }
    )
    common_segments = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start <= 1.0e-8:
            continue
        midpoint = (start + end) * 0.5
        if midpoint < atom_start - 1.0e-10 or midpoint > atom_end + 1.0e-10:
            continue
        left_covered = any(
            min(run["u_interval"]) - 1.0e-10
            <= midpoint
            <= max(run["u_interval"]) + 1.0e-10
            for run in left_runs
        )
        right_covered = any(
            min(run["u_interval"]) - 1.0e-10
            <= midpoint
            <= max(run["u_interval"]) + 1.0e-10
            for run in right_runs
        )
        if left_covered and right_covered:
            if common_segments and start <= common_segments[-1][1] + 1.0e-8:
                common_segments[-1][1] = end
            else:
                common_segments.append([start, end])
    return tuple(common_segments)


# 按 Edge 与 component 的实际 u overlap 做唯一归属，再在 component 边界生成虚拟端点。
# run/components: 已归属同一 Plan atom 的 open run 与互不重叠共同区间；返回不重复消费 Edge 的 fragments。
def _partition_run_to_component_intervals(run, components):
    parameters = [float(value) for value in run["u_values"]]
    component_bounds = [sorted(map(float, interval)) for interval in components]
    edge_owners = []
    for edge_start, edge_end in zip(parameters, parameters[1:]):
        edge_lower, edge_upper = sorted((edge_start, edge_end))
        overlaps = [
            max(0.0, min(edge_upper, upper) - max(edge_lower, lower))
            for lower, upper in component_bounds
        ]
        maximum_overlap = max(overlaps, default=0.0)
        matching_components = [
            component_index
            for component_index, overlap in enumerate(overlaps)
            if overlap > 1.0e-10
            and abs(overlap - maximum_overlap) <= 1.0e-10
        ]
        edge_owners.append(
            matching_components[0] if len(matching_components) == 1 else None
        )
    fragments = []
    fragment_start = 0
    for edge_index in range(1, len(edge_owners) + 1):
        if (
            edge_index < len(edge_owners)
            and edge_owners[edge_index] == edge_owners[fragment_start]
        ):
            continue
        component_index = edge_owners[fragment_start]
        if component_index is not None:
            selected_edge_ids = list(
                run["edge_ids"][fragment_start:edge_index]
            )
            fragment = {
                **run,
                "edge_ids": selected_edge_ids,
                "coordinates": list(run["coordinates"])[
                    fragment_start : edge_index + 1
                ],
                "endpoint_tokens": list(run.get("endpoint_tokens", ()))[
                    fragment_start : edge_index + 1
                ],
                "u_values": parameters[fragment_start : edge_index + 1],
                "u_interval": [
                    parameters[fragment_start],
                    parameters[edge_index],
                ],
                "is_cyclic": False,
                "junction_endpoint_tokens_by_edge": {
                    edge_id: list(tokens)
                    for edge_id, tokens in run.get(
                        "junction_endpoint_tokens_by_edge",
                        {},
                    ).items()
                    if edge_id in selected_edge_ids
                },
                "endpoint_degrees_by_edge": {
                    edge_id: list(degrees)
                    for edge_id, degrees in run.get(
                        "endpoint_degrees_by_edge",
                        {},
                    ).items()
                    if edge_id in selected_edge_ids
                },
                "endpoint_topology_signatures_by_edge": {
                    edge_id: list(signatures)
                    for edge_id, signatures in run.get(
                        "endpoint_topology_signatures_by_edge",
                        {},
                    ).items()
                    if edge_id in selected_edge_ids
                },
            }
            fragments.append(
                (
                    component_index,
                    _clip_run_geometry_to_interval(
                        fragment,
                        component_bounds[component_index],
                    ),
                )
            )
        fragment_start = edge_index
    return tuple(fragments)


# 把 atom 内 fragments 裁到双侧共同 u components，再交给唯一 matching。
# left_runs/right_runs/atom: atom 两侧 fragments 与 Plan atom；返回 component-indexed runs。
def _partition_atom_runs_by_common_components(left_runs, right_runs, atom):
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    full_cyclic_atom = (
        abs(atom_start) <= 1.0e-8
        and abs(atom_end - 1.0) <= 1.0e-8
        and len(left_runs) == 1
        and len(right_runs) == 1
    )
    if (
        full_cyclic_atom
        and left_runs[0].get("full_cyclic_atom")
        and right_runs[0].get("full_cyclic_atom")
    ):
        component_interval = [
            min(
                *map(float, left_runs[0]["u_interval"]),
                *map(float, right_runs[0]["u_interval"]),
            ),
            max(
                *map(float, left_runs[0]["u_interval"]),
                *map(float, right_runs[0]["u_interval"]),
            ),
        ]
        component_id = f"{atom['atom_id']}:0"
        return (
            ({
                **left_runs[0],
                "component_id": component_id,
                "component_u_interval": component_interval,
            },),
            ({
                **right_runs[0],
                "component_id": component_id,
                "component_u_interval": component_interval,
            },),
            (component_interval,),
        )
    if full_cyclic_atom:
        left_run = left_runs[0]
        right_run = right_runs[0]
        left_start, left_end = sorted(map(float, left_run["u_interval"]))
        right_start, right_end = sorted(map(float, right_run["u_interval"]))
        if (
            left_start <= 1.0e-8
            and right_end >= 1.0 - 1.0e-8
            and left_end > right_start + 1.0e-8
        ):
            lifted_right = {
                **right_run,
                "u_values": [float(value) - 1.0 for value in right_run["u_values"]],
                "u_interval": [right_start - 1.0, right_end - 1.0],
            }
            component_interval = [right_start - 1.0, left_end]
            component_id = f"{atom['atom_id']}:0"
            return (
                (
                    {
                        **left_run,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": component_interval,
                        "full_cyclic_atom": True,
                    },
                ),
                (
                    {
                        **lifted_right,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": component_interval,
                        "full_cyclic_atom": True,
                    },
                ),
                (component_interval,),
            )
    components = _common_atom_component_intervals(
        left_runs,
        right_runs,
        atom,
    )
    partitioned_left = []
    partitioned_right = []
    for runs, target in (
        (left_runs, partitioned_left),
        (right_runs, partitioned_right),
    ):
        for run in runs:
            for component_index, trimmed in (
                _partition_run_to_component_intervals(run, components)
            ):
                interval = components[component_index]
                component_id = f"{atom['atom_id']}:{component_index}"
                target.append(
                    {
                        **trimmed,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": list(interval),
                    }
                )
    return tuple(partitioned_left), tuple(partitioned_right), components


# 为 cyclic full-span atom 选择两侧 rail 的唯一 seam lift，使双侧覆盖同一完整周期；
# left_runs/right_runs/atom: 单 atom 两侧已按 topology stitch 的 runs 与 Plan atom；返回 lift 后 runs 或原输入。
def _lift_full_cyclic_atom_runs(left_runs, right_runs, atom):
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        abs(atom_start) > 1.0e-8
        or abs(atom_end - 1.0) > 1.0e-8
        or len(left_runs) != 1
        or len(right_runs) != 1
    ):
        return left_runs, right_runs
    candidates = []
    for left_shift in (-1, 0, 1):
        for right_shift in (-1, 0, 1):
            left_values = [
                float(value) + left_shift for value in left_runs[0]["u_values"]
            ]
            right_values = [
                float(value) + right_shift for value in right_runs[0]["u_values"]
            ]
            left_start, left_end = sorted((left_values[0], left_values[-1]))
            right_start, right_end = sorted((right_values[0], right_values[-1]))
            common_coverage = max(
                0.0,
                min(left_end, right_end) - max(left_start, right_start),
            )
            union_coverage = max(left_end, right_end) - min(
                left_start,
                right_start,
            )
            candidates.append(
                (
                    common_coverage,
                    -abs(union_coverage - 1.0),
                    -(abs(left_shift) + abs(right_shift)),
                    -abs(left_shift),
                    left_shift,
                    right_shift,
                    left_values,
                    right_values,
                )
            )
    (
        common_coverage,
        negative_coverage_error,
        _,
        _,
        left_shift,
        right_shift,
        left_values,
        right_values,
    ) = max(candidates)
    if (
        common_coverage <= 1.0e-8
        or -negative_coverage_error > 2.0e-2
    ):
        return left_runs, right_runs

    def shifted(run, shift, values):
        if not shift:
            return run
        return {
            **run,
            "u_values": values,
            "u_interval": [values[0], values[-1]],
        }

    return (
        [shifted(left_runs[0], left_shift, left_values)],
        [shifted(right_runs[0], right_shift, right_values)],
    )


# 对 cyclic full-span 的两条完整 rail 重新建立共同 phase；只旋转 normalized u，不改变 Edge 顺序或 provenance。
# left_runs/right_runs/atom: 单 atom 两侧 stitched runs 与 Plan atom；返回 phase 对齐的 runs 或原输入。
def _align_full_cyclic_atom_run_phase(left_runs, right_runs, atom):
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        abs(atom_start) > 1.0e-8
        or abs(atom_end - 1.0) > 1.0e-8
        or len(left_runs) != 1
        or len(right_runs) != 1
    ):
        return left_runs, right_runs
    left_run = left_runs[0]
    right_run = right_runs[0]
    left_values = [float(value) for value in left_run["u_values"]]
    right_values = [float(value) for value in right_run["u_values"]]
    if len(left_values) < 2 or len(right_values) < 2:
        return left_runs, right_runs
    left_start, left_end = sorted((left_values[0], left_values[-1]))
    right_start, right_end = sorted((right_values[0], right_values[-1]))
    left_coverage = left_end - left_start
    right_coverage = right_end - right_start
    if min(left_coverage, right_coverage) < 0.50:
        return left_runs, right_runs
    start_shift = left_start - right_start
    shifted_right_values = [value + start_shift for value in right_values]
    end_error = abs(shifted_right_values[-1] - left_end)
    maximum_end_error = max(2.0e-2, min(left_coverage, right_coverage) * 0.20)
    if end_error > maximum_end_error:
        return left_runs, right_runs
    return (
        [{**left_run, "full_cyclic_atom": True}],
        [
            {
                **right_run,
                "u_values": shifted_right_values,
                "u_interval": [shifted_right_values[0], shifted_right_values[-1]],
                "cyclic_phase_shift": start_shift,
                "full_cyclic_atom": True,
            }
        ],
    )


# 返回 FeatureStrand 折线总弧长，short setback 只按真实弧长证明，不用 normalized u 近似距离。
# strand: 权威 ChamferPlan FeatureStrand；返回其 ordered vertices 组成的实际弧长。
def _feature_strand_arc_length(strand):
    coordinates = [
        Vector(tuple(float(value) for value in key.split("#", 1)[0].split(",")))
        for key in strand.ordered_vertex_keys
    ]
    segment_count = len(coordinates) if strand.cyclic else len(coordinates) - 1
    return sum(
        (
            coordinates[(index + 1) % len(coordinates)]
            - coordinates[index]
        ).length
        for index in range(segment_count)
    )


# 对单侧单 Edge unresolved component 生成 fail-closed short setback proof；其余 regular 失败保持 unresolved。
# unresolved/atom/strand/forbidden_intervals/radius: component、Plan atom、FeatureStrand、overlap 禁区与半径；返回 proof 或 None。
def _short_component_setback_proof(
    unresolved,
    atom,
    strand,
    forbidden_intervals,
    radius,
    adjacent_atoms=(),
    forbidden_envelopes=(),
):
    left_runs = unresolved.get("left_runs", ())
    right_runs = unresolved.get("right_runs", ())
    present_sides = [
        (side, runs)
        for side, runs in (("LEFT", left_runs), ("RIGHT", right_runs))
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or (left_runs and right_runs)
    ):
        return None
    present_side, present_runs = present_sides[0]
    if (
        len(present_runs) != 1
        or len(present_runs[0].get("edge_ids", ())) != 1
    ):
        return None
    present_run = present_runs[0]
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    present_start, present_end = sorted(map(float, present_runs[0]["u_interval"]))
    containment_tolerance_u = 1.0e-8
    if (
        component_start < atom_start - containment_tolerance_u
        or component_end > atom_end + containment_tolerance_u
        or present_start < component_start - containment_tolerance_u
        or present_end > component_end + containment_tolerance_u
    ):
        return None
    strand_length = _feature_strand_arc_length(strand)
    component_arc_length = (component_end - component_start) * strand_length
    maximum_arc_length = radius * 2.0
    epsilon_u = 1.0e-8
    atom_boundary_candidates = []
    if (
        abs(component_start - atom_start) * strand_length
        <= maximum_arc_length + 1.0e-10
    ):
        atom_boundary_candidates.append(("ATOM_START", atom_start))
    if (
        abs(component_end - atom_end) * strand_length
        <= maximum_arc_length + 1.0e-10
    ):
        atom_boundary_candidates.append(("ATOM_END", atom_end))
    source_boundary_candidates = []
    if len(atom_boundary_candidates) != 1:
        for envelope in forbidden_envelopes:
            source_start, source_end = sorted(
                map(float, envelope["source_u_interval"])
            )
            for boundary_side, boundary_u in (
                ("FORBIDDEN_START", source_start),
                ("FORBIDDEN_END", source_end),
            ):
                for offset in (range(-2, 3) if strand.cyclic else (0,)):
                    lifted_boundary_u = boundary_u + offset
                    boundary_distance = min(
                        abs(component_start - lifted_boundary_u),
                        abs(component_end - lifted_boundary_u),
                    ) * strand_length
                    if boundary_distance <= maximum_arc_length + 1.0e-10:
                        source_boundary_candidates.append(
                            {
                                "boundary_id": (
                                    "overlap-forbidden-source:"
                                    f"{int(envelope['interval_index'])}:"
                                    f"{boundary_side.lower()}:"
                                    f"{lifted_boundary_u:.10f}"
                                ),
                                "boundary_type": "OVERLAP_FORBIDDEN",
                                "boundary_side": boundary_side,
                                "boundary_u": lifted_boundary_u,
                                "direct_witness_edge_ids": list(
                                    envelope["direct_witness_edge_ids"]
                                ),
                            }
                        )
        unique_source_boundaries = {
            candidate["boundary_id"]: candidate
            for candidate in source_boundary_candidates
        }
        if len(unique_source_boundaries) != 1:
            return None
        source_boundary = next(iter(unique_source_boundaries.values()))
        atom_side = "ATOM_START_END_COLLAPSED"
        atom_boundary_u = source_boundary["boundary_u"]
    else:
        atom_side, atom_boundary_u = atom_boundary_candidates[0]
        source_boundary = None
    adjacent_boundaries = []
    for interval_index, interval in enumerate(forbidden_intervals):
        forbidden_start, forbidden_end = sorted(map(float, interval))
        candidates = (
            ("FORBIDDEN_START", forbidden_start),
            ("FORBIDDEN_END", forbidden_end),
        )
        for boundary_side, boundary_u in candidates:
            if abs(boundary_u - atom_boundary_u) <= epsilon_u:
                adjacent_boundaries.append(
                    {
                        "boundary_id": (
                            f"overlap-forbidden:{interval_index}:"
                            f"{boundary_side.lower()}:{boundary_u:.10f}"
                        ),
                        "boundary_type": "OVERLAP_FORBIDDEN",
                        "boundary_side": boundary_side,
                        "boundary_u": boundary_u,
                        "atom_boundary_side": atom_side,
                    }
                )
    if not strand.cyclic:
        for endpoint_role, endpoint_u, port_id in (
            ("START", 0.0, strand.start_port_id),
            ("END", 1.0, strand.end_port_id),
        ):
            if port_id and abs(endpoint_u - atom_boundary_u) <= epsilon_u:
                adjacent_boundaries.append(
                    {
                        "boundary_id": port_id,
                        "boundary_type": "PLAN_ENDPOINT",
                        "boundary_side": endpoint_role,
                        "boundary_u": endpoint_u,
                        "atom_boundary_side": atom_side,
                    }
                )
    unique_boundaries = {
        boundary["boundary_id"]: boundary for boundary in adjacent_boundaries
    }
    if source_boundary is not None:
        unique_boundaries[source_boundary["boundary_id"]] = {
            **source_boundary,
            "atom_boundary_side": atom_side,
        }
    if not unique_boundaries and forbidden_intervals:
        interval_boundary_candidates = []
        for interval_index, interval in enumerate(forbidden_intervals):
            forbidden_start, forbidden_end = sorted(map(float, interval))
            for boundary_side, boundary_u in (
                ("FORBIDDEN_START", forbidden_start),
                ("FORBIDDEN_END", forbidden_end),
            ):
                for offset in (range(-2, 3) if strand.cyclic else (0,)):
                    lifted_boundary_u = boundary_u + offset
                    boundary_distance = min(
                        abs(component_start - lifted_boundary_u),
                        abs(component_end - lifted_boundary_u),
                    ) * strand_length
                    if boundary_distance <= 1.0e-8 * strand_length + 1.0e-10:
                        interval_boundary_candidates.append(
                            {
                                "boundary_id": (
                                    f"overlap-forbidden:{interval_index}:"
                                    f"{boundary_side.lower()}:"
                                    f"{lifted_boundary_u:.10f}"
                                ),
                                "boundary_type": "OVERLAP_FORBIDDEN",
                                "boundary_side": boundary_side,
                                "boundary_u": lifted_boundary_u,
                                "atom_boundary_side": atom_side,
                            }
                        )
        unique_interval_boundaries = {
            candidate["boundary_id"]: candidate
            for candidate in interval_boundary_candidates
        }
        if len(unique_interval_boundaries) == 1:
            unique_boundaries.update(unique_interval_boundaries)
    if not unique_boundaries and forbidden_envelopes:
        envelope_candidates = []
        for envelope in forbidden_envelopes:
            envelope_start, envelope_end = sorted(
                map(float, envelope["effective_u_interval"])
            )
            for boundary_side, boundary_u in (
                ("FORBIDDEN_START", envelope_start),
                ("FORBIDDEN_END", envelope_end),
            ):
                for offset in (range(-2, 3) if strand.cyclic else (0,)):
                    lifted_boundary_u = boundary_u + offset
                    boundary_distance = min(
                        abs(component_start - lifted_boundary_u),
                        abs(component_end - lifted_boundary_u),
                    ) * strand_length
                    atom_boundary_distance = abs(
                        atom_boundary_u - lifted_boundary_u
                    ) * strand_length
                    if (
                        boundary_distance <= maximum_arc_length + 1.0e-10
                        and atom_boundary_distance
                        <= maximum_arc_length + 1.0e-10
                    ):
                        envelope_candidates.append(
                            {
                                "boundary_id": (
                                    "overlap-forbidden-envelope:"
                                    f"{int(envelope['interval_index'])}:"
                                    f"{boundary_side.lower()}:"
                                    f"{lifted_boundary_u:.10f}"
                                ),
                                "boundary_type": (
                                    "OVERLAP_FORBIDDEN_ENVELOPE"
                                ),
                                "boundary_side": boundary_side,
                                "boundary_u": lifted_boundary_u,
                                "atom_boundary_side": atom_side,
                                "direct_witness_edge_ids": list(
                                    envelope["direct_witness_edge_ids"]
                                ),
                            }
                        )
        unique_envelope_candidates = {
            candidate["boundary_id"]: candidate
            for candidate in envelope_candidates
        }
        if len(unique_envelope_candidates) == 1:
            unique_boundaries.update(unique_envelope_candidates)
    if not unique_boundaries and adjacent_atoms:
        adjacent_candidates = []
        for candidate in adjacent_atoms:
            if candidate["atom_id"] == atom["atom_id"]:
                continue
            candidate_start, candidate_end = sorted(
                map(float, candidate["u_interval"])
            )
            boundary_distance_u = min(
                abs(candidate_boundary + offset - atom_boundary_u)
                for candidate_boundary in (candidate_start, candidate_end)
                for offset in (range(-2, 3) if strand.cyclic else (0,))
            )
            if (
                boundary_distance_u * strand_length
                <= maximum_arc_length + 1.0e-10
            ):
                adjacent_candidates.append(candidate)
        unique_adjacent = {
            candidate["atom_id"]: candidate
            for candidate in adjacent_candidates
        }
        if len(unique_adjacent) == 1:
            adjacent_atom = next(iter(unique_adjacent.values()))
            if (
                int(adjacent_atom["span_id"]) != int(atom["span_id"])
                or int(adjacent_atom["convexity"]) != int(atom["convexity"])
            ):
                boundary_id = (
                    "plan-atom-boundary:"
                    + _stable_fingerprint(
                        {
                            "atom_ids": sorted(
                                (atom["atom_id"], adjacent_atom["atom_id"])
                            ),
                            "boundary_u": round(atom_boundary_u, 10),
                        }
                    )[:20]
                )
                unique_boundaries[boundary_id] = {
                    "boundary_id": boundary_id,
                    "boundary_type": "PLAN_ATOM_BOUNDARY",
                    "boundary_side": atom_side,
                    "boundary_u": atom_boundary_u,
                    "atom_boundary_side": atom_side,
                    "adjacent_boundary_distance": boundary_distance_u
                    * strand_length,
                    "adjacent_atom_id": adjacent_atom["atom_id"],
                    "adjacent_span_id": int(adjacent_atom["span_id"]),
                    "adjacent_convexity": int(adjacent_atom["convexity"]),
                }
    if len(unique_boundaries) != 1:
        return None
    adjacent_boundary = next(iter(unique_boundaries.values()))
    boundary_distance = min(
        abs(component_start - adjacent_boundary["boundary_u"]),
        abs(component_end - adjacent_boundary["boundary_u"]),
    ) * strand_length
    if (
        component_arc_length > maximum_arc_length + 1.0e-10
        or boundary_distance > maximum_arc_length + 1.0e-10
    ):
        return None
    endpoint_degrees = tuple(
        present_run.get("endpoint_degrees_by_edge", {}).get(
            present_run["edge_ids"][0],
            (),
        )
    )
    if (
        present_run.get("branch_setback") is False
        or (
            adjacent_boundary["boundary_type"] == "JUNCTION_ENDPOINT"
            and sorted(map(int, endpoint_degrees)) != [1, 2]
        )
    ):
        return None
    return {
        "proof_version": "SHORT_COMPONENT_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": present_run["edge_ids"][0],
        "coordinates": list(present_run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "component_arc_length": component_arc_length,
        "maximum_arc_length": maximum_arc_length,
        "boundary_distance": boundary_distance,
        "boundary_id": adjacent_boundary["boundary_id"],
        "boundary_type": adjacent_boundary["boundary_type"],
        "boundary_side": adjacent_boundary["boundary_side"],
        "atom_boundary_side": adjacent_boundary["atom_boundary_side"],
        "adjacent_atom_id": adjacent_boundary.get("adjacent_atom_id"),
        "adjacent_span_id": adjacent_boundary.get("adjacent_span_id"),
        "adjacent_convexity": adjacent_boundary.get("adjacent_convexity"),
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 用同一 correspondence 相邻 Plan atom 的权威边界证明 cyclic short component；不接受普通 atom 内部碎片。
# unresolved/atom/plan_atoms/strand/radius: 单侧 component、当前及全量 Plan atoms、权威 strand 与半径；返回 proof 或 None。
def _cyclic_adjacent_atom_short_component_setback_proof(
    unresolved,
    atom,
    plan_atoms,
    strand,
    radius,
):
    if not strand.cyclic:
        return None
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
        or len(present_sides[0][1][0].get("edge_ids", ())) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    present_run = present_runs[0]
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    strand_length = _feature_strand_arc_length(strand)
    maximum_arc_length = radius * 2.0
    component_arc_length = (component_end - component_start) * strand_length
    if component_arc_length > maximum_arc_length + 1.0e-10:
        return None
    boundary_candidates = []
    for atom_side, boundary_u in (
        ("ATOM_START", atom_start),
        ("ATOM_END", atom_end),
    ):
        boundary_distance = min(
            abs(component_start - boundary_u),
            abs(component_end - boundary_u),
        ) * strand_length
        if boundary_distance > maximum_arc_length + 1.0e-10:
            continue
        adjacent_atoms = []
        for candidate in plan_atoms:
            if candidate["atom_id"] == atom["atom_id"]:
                continue
            candidate_start, candidate_end = sorted(
                map(float, candidate["u_interval"])
            )
            if any(
                abs(candidate_boundary + offset - boundary_u) <= 1.0e-8
                for candidate_boundary in (candidate_start, candidate_end)
                for offset in range(-2, 3)
            ):
                adjacent_atoms.append(candidate)
        unique_adjacent_atoms = {
            candidate["atom_id"]: candidate for candidate in adjacent_atoms
        }
        if len(unique_adjacent_atoms) == 1:
            boundary_candidates.append(
                (
                    atom_side,
                    boundary_u,
                    boundary_distance,
                    next(iter(unique_adjacent_atoms.values())),
                )
            )
    if len(boundary_candidates) != 1:
        return None
    atom_side, boundary_u, boundary_distance, adjacent_atom = (
        boundary_candidates[0]
    )
    if (
        int(adjacent_atom["span_id"]) == int(atom["span_id"])
        and int(adjacent_atom["convexity"]) == int(atom["convexity"])
    ):
        return None
    boundary_id = (
        "plan-atom-boundary:"
        + _stable_fingerprint(
            {
                "atom_ids": sorted((atom["atom_id"], adjacent_atom["atom_id"])),
                "boundary_u": round(boundary_u, 10),
            }
        )[:20]
    )
    return {
        "proof_version": "SHORT_COMPONENT_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": present_run["edge_ids"][0],
        "coordinates": list(present_run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "component_arc_length": component_arc_length,
        "maximum_arc_length": maximum_arc_length,
        "boundary_distance": boundary_distance,
        "boundary_id": boundary_id,
        "boundary_type": "PLAN_ATOM_BOUNDARY",
        "boundary_side": atom_side,
        "atom_boundary_side": atom_side,
        "adjacent_atom_id": adjacent_atom["atom_id"],
        "adjacent_span_id": int(adjacent_atom["span_id"]),
        "adjacent_convexity": int(adjacent_atom["convexity"]),
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 对 junction branch 产生的单 Edge 数值碎片生成严格 proof；只接受极短真实 Edge。
# unresolved/atom/radius: 单个 unresolved component、Plan atom 与 Chamfer radius；返回 proof 或 None。
def _branch_micro_fragment_setback_proof(unresolved, atom, radius):
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    run = present_runs[0]
    if len(run.get("edge_ids", ())) != 1 or not run.get("branch_setback"):
        return None
    edge_id = run["edge_ids"][0]
    junction_tokens = list(
        run.get("junction_endpoint_tokens_by_edge", {}).get(edge_id, ())
    )
    endpoint_degrees = list(
        run.get("endpoint_degrees_by_edge", {}).get(edge_id, ())
    )
    branch_endpoint_count = sum(int(degree) != 2 for degree in endpoint_degrees)
    if (
        branch_endpoint_count != 2
        or len(junction_tokens) != 2
        or len(endpoint_degrees) != 2
        or sorted(map(int, endpoint_degrees))[0] != 1
        or sorted(map(int, endpoint_degrees))[1] <= 2
    ):
        return None
    coordinates = [Vector(point) for point in run.get("coordinates", ())]
    if len(coordinates) != 2:
        return None
    edge_length = (coordinates[1] - coordinates[0]).length
    maximum_edge_length = max(radius * 1.0e-4, 2.0e-6)
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        edge_length > maximum_edge_length + 1.0e-12
        or component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
    ):
        return None
    return {
        "proof_version": "BRANCH_MICRO_FRAGMENT_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": edge_id,
        "coordinates": list(run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "edge_length": edge_length,
        "maximum_edge_length": maximum_edge_length,
        "junction_endpoint_token": junction_tokens[0],
        "endpoint_degrees": endpoint_degrees,
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 对 terminal degree-1 产生的单 Edge 数值碎片生成严格 proof；仅接受极短且直接邻接 Rail terminal 的 Edge。
# unresolved/atom/radius: 单个 unresolved component、Plan atom 与 Chamfer radius；返回 proof 或 None。
def _terminal_micro_fragment_setback_proof(unresolved, atom, radius):
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    run = present_runs[0]
    if len(run.get("edge_ids", ())) != 1 or not run.get("branch_setback"):
        return None
    edge_id = run["edge_ids"][0]
    endpoint_degrees = list(
        run.get("endpoint_degrees_by_edge", {}).get(edge_id, ())
    )
    terminal_tokens = list(
        run.get("junction_endpoint_tokens_by_edge", {}).get(edge_id, ())
    )
    if (
        sorted(map(int, endpoint_degrees)) != [1, 2]
        or len(terminal_tokens) != 1
    ):
        return None
    coordinates = [Vector(point) for point in run.get("coordinates", ())]
    if len(coordinates) != 2:
        return None
    edge_length = (coordinates[1] - coordinates[0]).length
    maximum_edge_length = max(radius * 1.0e-2, 2.0e-6)
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        edge_length > maximum_edge_length + 1.0e-12
        or component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
    ):
        return None
    return {
        "proof_version": "TERMINAL_MICRO_FRAGMENT_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": edge_id,
        "coordinates": list(run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "edge_length": edge_length,
        "maximum_edge_length": maximum_edge_length,
        "terminal_endpoint_token": terminal_tokens[0],
        "endpoint_degrees": endpoint_degrees,
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 对 degree-1 terminal 前的一段短 maximal Boundary tail 生成 proof；允许少量普通 Edge，但必须唯一终止于真实 terminal。
# unresolved/atom/radius: 单个 unresolved component、Plan atom 与 Chamfer radius；返回 terminal tail proof 或 None。
def _terminal_short_tail_setback_proof(unresolved, atom, radius):
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    run = present_runs[0]
    edge_ids = list(run.get("edge_ids", ()))
    if not run.get("branch_setback") or not 2 <= len(edge_ids) <= 3:
        return None
    endpoint_degrees_by_edge = run.get("endpoint_degrees_by_edge", {})
    terminal_edge_ids = [
        edge_id
        for edge_id in edge_ids
        if sorted(map(int, endpoint_degrees_by_edge.get(edge_id, ()))) == [1, 2]
    ]
    regular_edge_ids = [
        edge_id
        for edge_id in edge_ids
        if list(map(int, endpoint_degrees_by_edge.get(edge_id, ()))) == [2, 2]
    ]
    terminal_tokens = [
        token
        for edge_id in terminal_edge_ids
        for token in run.get("junction_endpoint_tokens_by_edge", {}).get(
            edge_id,
            (),
        )
    ]
    if (
        len(terminal_edge_ids) != 1
        or len(regular_edge_ids) != len(edge_ids) - 1
        or len(terminal_tokens) != 1
        or terminal_edge_ids[0] not in {edge_ids[0], edge_ids[-1]}
    ):
        return None
    coordinates = [Vector(point) for point in run.get("coordinates", ())]
    if len(coordinates) != len(edge_ids) + 1:
        return None
    component_length = sum(
        (following - current).length
        for current, following in zip(coordinates, coordinates[1:])
    )
    maximum_component_length = max(radius * 0.50, 2.0e-6)
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        component_length > maximum_component_length + 1.0e-10
        or component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
    ):
        return None
    return {
        "proof_version": "TERMINAL_SHORT_TAIL_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_ids": edge_ids,
        "coordinates": list(run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "component_length": component_length,
        "maximum_component_length": maximum_component_length,
        "terminal_edge_id": terminal_edge_ids[0],
        "terminal_endpoint_token": terminal_tokens[0],
        "endpoint_degrees_by_edge": {
            edge_id: list(endpoint_degrees_by_edge[edge_id])
            for edge_id in edge_ids
        },
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 对完全位于 junction endpoint graph 的多 Edge 数值碎片生成严格 proof；禁止普通 degree-2 Edge 混入。
# unresolved/atom/radius: 单个 unresolved component、Plan atom 与 Chamfer radius；返回 proof 或 None。
def _junction_micro_component_setback_proof(unresolved, atom, radius):
    present_sides = [
        (side, runs)
        for side, runs in (
            ("LEFT", unresolved.get("left_runs", ())),
            ("RIGHT", unresolved.get("right_runs", ())),
        )
        if runs
    ]
    if (
        unresolved.get("reason") != "NO_PERFECT_MATCHING"
        or unresolved.get("solution_count_capped") != 0
        or len(present_sides) != 1
        or len(present_sides[0][1]) != 1
    ):
        return None
    present_side, present_runs = present_sides[0]
    run = present_runs[0]
    edge_ids = list(run.get("edge_ids", ()))
    endpoint_degrees_by_edge = run.get("endpoint_degrees_by_edge", {})
    junction_tokens_by_edge = run.get("junction_endpoint_tokens_by_edge", {})
    if (
        len(edge_ids) < 2
        or not run.get("branch_setback")
        or any(
            edge_id not in endpoint_degrees_by_edge
            or edge_id not in junction_tokens_by_edge
            or any(int(degree) == 2 for degree in endpoint_degrees_by_edge[edge_id])
            for edge_id in edge_ids
        )
    ):
        return None
    coordinates = [Vector(point) for point in run.get("coordinates", ())]
    if len(coordinates) != len(edge_ids) + 1:
        return None
    component_length = sum(
        (following - current).length
        for current, following in zip(coordinates, coordinates[1:])
    )
    maximum_component_length = max(radius * 1.0e-3, 2.0e-6)
    if component_length > maximum_component_length + 1.0e-12:
        return None
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    if (
        component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
    ):
        return None
    return {
        "proof_version": "JUNCTION_MICRO_COMPONENT_SETBACK_V1",
        "correspondence_id": unresolved["correspondence_id"],
        "atom_id": atom["atom_id"],
        "component_id": unresolved["component_id"],
        "present_side": present_side,
        "edge_id": edge_ids[0],
        "edge_ids": edge_ids,
        "coordinates": list(run["coordinates"]),
        "component_u_interval": [component_start, component_end],
        "component_length": component_length,
        "maximum_component_length": maximum_component_length,
        "junction_endpoint_tokens_by_edge": dict(junction_tokens_by_edge),
        "endpoint_degrees_by_edge": dict(endpoint_degrees_by_edge),
        "span_id": int(atom["span_id"]),
        "patch_pair": list(atom["patch_pair"]),
        "convexity": int(atom["convexity"]),
    }


# 从已证明的 short component 原子提交 ledger 与 setback port，消费前再次核对 owner 与分类。
# proof/correspondence/pipe_id/ledger_by_edge_id: proof、Plan correspondence、Pipe owner 与 ledger；返回 port record。
def _commit_short_component_setback(
    proof,
    correspondence,
    pipe_id,
    ledger_by_edge_id,
):
    edge_ids = list(
        proof["edge_ids"]
        if "edge_ids" in proof
        else (proof["edge_id"],)
    )
    ledger_entries = []
    for edge_id in edge_ids:
        ledger_entry = ledger_by_edge_id.get(edge_id)
        if ledger_entry is None or ledger_entry["classification"] != "UNCLASSIFIED":
            raise BatchedChamferError(
                "REGULAR_CORE_LEDGER_CONFLICT",
                "Short component setback 提交时 Boundary Edge 已被消费",
                {"edge_id": edge_id, "proof": proof},
            )
        if (
            ledger_entry["pipe_id"] != pipe_id
            or ledger_entry["strand_id"] != correspondence.owner_strand_id
            or ledger_entry["source_patch_id"] not in correspondence.owner_surface_pair
            or ledger_entry.get("outside_plan_owner_patch")
        ):
            raise BatchedChamferError(
                "SHORT_COMPONENT_SETBACK_OWNER_MISMATCH",
                "Short component setback 与 Boundary owner provenance 不一致",
                {"edge_id": edge_id, "proof": proof, "ledger": ledger_entry},
            )
        ledger_entries.append(ledger_entry)
    owner_keys = {
        (entry["rail_id"], entry["source_patch_id"])
        for entry in ledger_entries
    }
    if len(owner_keys) != 1:
        raise BatchedChamferError(
            "SHORT_COMPONENT_SETBACK_OWNER_MISMATCH",
            "Short component setback 混入多个 Rail/Patch owner",
            {"edge_ids": edge_ids, "proof": proof},
        )
    ledger_entry = ledger_entries[0]
    consumer_id = (
        "short-setback:"
        + _stable_fingerprint(
            {
                "correspondence_id": proof["correspondence_id"],
                "atom_id": proof["atom_id"],
                "component_id": proof["component_id"],
                "edge_ids": edge_ids,
                "proof_version": proof["proof_version"],
                "boundary_id": proof.get("boundary_id"),
            }
        )[:20]
    )
    for ledger_entry_item in ledger_entries:
        ledger_entry_item["classification"] = "SETBACK_RESERVED"
        ledger_entry_item["consumer_id"] = consumer_id
    return {
        "port_id": consumer_id,
        "pipe_id": int(pipe_id),
        "strand_id": correspondence.owner_strand_id,
        "rail_id": ledger_entry["rail_id"],
        "source_patch_id": int(ledger_entry["source_patch_id"]),
        "reason": proof["proof_version"],
        "outside_plan_owner_patch": False,
        "ordered_edge_ids": edge_ids,
        "ordered_coordinates": proof["coordinates"],
        "is_cyclic": False,
        "direction": "FEATURE_STRAND_FORWARD",
        "u_interval": proof["component_u_interval"],
        "boundary_id": proof.get("boundary_id"),
        "proof": proof,
    }


# 证明 atom 末端的单侧 maximal Boundary tail 已从相邻 Regular Strip 过渡到权威 span/overlap 边界。
# oriented_chain/start_u/end_u/claim/regular_records/ledger_by_edge_id/radius: 当前尾链、投影、唯一 atom、已提交 Strip、ledger 与半径；返回 handoff proof 或 None。
def _regular_terminal_tail_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claim,
    regular_records,
    ledger_by_edge_id,
    radius,
):
    if oriented_chain.get("is_cyclic") or not oriented_chain.get("edge_ids"):
        return None
    chain_coordinates = [Vector(point) for point in oriented_chain["coordinates"]]
    chain_length = sum(
        (following - current).length
        for current, following in zip(chain_coordinates, chain_coordinates[1:])
    )
    maximum_chain_length = radius * 4.50
    raw_chain_interval = sorted((float(start_u), float(end_u)))
    atom_start, atom_end = sorted(map(float, claim["u_interval"]))
    strand_length = max(float(claim["strand_length"]), 1.0e-12)
    candidate_boundary_tolerance = max(
        1.0e-8,
        radius * 2.0 / strand_length,
    )
    lifted_candidates = []
    for shift in range(-2, 3) if claim["strand_cyclic"] else (0,):
        chain_start = raw_chain_interval[0] + shift
        chain_end = raw_chain_interval[1] + shift
        if (
            chain_start <= atom_start + candidate_boundary_tolerance
            and chain_end >= atom_start - candidate_boundary_tolerance
        ):
            lifted_candidates.append(
                (abs(shift), "ATOM_START", chain_start, chain_end, atom_start)
            )
        if (
            chain_start <= atom_end + candidate_boundary_tolerance
            and chain_end >= atom_end - candidate_boundary_tolerance
        ):
            lifted_candidates.append(
                (abs(shift), "ATOM_END", chain_start, chain_end, atom_end)
            )
    if not lifted_candidates:
        for envelope in claim["forbidden_envelopes"]:
            for forbidden_boundary_side, raw_boundary_u in (
                (
                    "FORBIDDEN_START",
                    float(envelope["effective_u_interval"][0]),
                ),
                (
                    "FORBIDDEN_END",
                    float(envelope["effective_u_interval"][1]),
                ),
            ):
                for shift in range(-2, 3) if claim["strand_cyclic"] else (0,):
                    chain_start = raw_chain_interval[0] + shift
                    chain_end = raw_chain_interval[1] + shift
                    lifted_boundary_u = raw_boundary_u + shift
                    if (
                        chain_start
                        <= lifted_boundary_u + candidate_boundary_tolerance
                        and chain_end
                        >= lifted_boundary_u - candidate_boundary_tolerance
                    ):
                        lifted_candidates.append(
                            (
                                abs(shift),
                                forbidden_boundary_side,
                                chain_start,
                                chain_end,
                                lifted_boundary_u,
                            )
                        )
    lifted_candidates = {
        (
            candidate[1],
            round(candidate[2], 10),
            round(candidate[3], 10),
            round(candidate[4], 10),
        ): candidate
        for candidate in lifted_candidates
    }
    if claim["strand_cyclic"] and lifted_candidates:
        minimum_shift = min(
            candidate[0] for candidate in lifted_candidates.values()
        )
        lifted_candidates = {
            key: candidate
            for key, candidate in lifted_candidates.items()
            if candidate[0] == minimum_shift
        }
    if len(lifted_candidates) > 1:
        ranked_candidates = sorted(
            lifted_candidates.values(),
            key=lambda candidate: (
                min(
                    abs(candidate[2] - candidate[4]),
                    abs(candidate[3] - candidate[4]),
                ),
                candidate[0],
                candidate[1],
            ),
        )
        best_distance = min(
            abs(ranked_candidates[0][2] - ranked_candidates[0][4]),
            abs(ranked_candidates[0][3] - ranked_candidates[0][4]),
        )
        second_distance = min(
            abs(ranked_candidates[1][2] - ranked_candidates[1][4]),
            abs(ranked_candidates[1][3] - ranked_candidates[1][4]),
        )
        if second_distance - best_distance > 1.0e-8:
            lifted_candidates = {
                _stable_fingerprint(ranked_candidates[0]): ranked_candidates[0]
            }
        elif (
            len(ranked_candidates) == 2
            and {
                ranked_candidates[0][1],
                ranked_candidates[1][1],
            }
            == {"ATOM_START", "ATOM_END"}
            and abs(atom_end - atom_start) * strand_length
            <= radius * 1.0e-2 + 1.0e-10
            and abs(ranked_candidates[0][2] - atom_start) <= 1.0e-8
            and abs(ranked_candidates[0][3] - atom_end) <= 1.0e-8
        ):
            atom_boundary_side = "ATOM_START_END_COLLAPSED"
            chain_start = ranked_candidates[0][2]
            chain_end = ranked_candidates[0][3]
            atom_boundary_u = (
                ranked_candidates[0][4] + ranked_candidates[1][4]
            ) * 0.5
            lifted_candidates = {
                _stable_fingerprint(
                    (atom_boundary_side, chain_start, chain_end, atom_boundary_u)
                ): (
                    ranked_candidates[0][0],
                    atom_boundary_side,
                    chain_start,
                    chain_end,
                    atom_boundary_u,
                )
            }
    if len(lifted_candidates) != 1:
        return {"rejected_stage": "ATOM_BOUNDARY", "candidates": list(lifted_candidates.values())}
    _, atom_boundary_side, chain_start, chain_end, atom_boundary_u = (
        next(iter(lifted_candidates.values()))
    )
    atom_boundary_distance = (
        min(abs(chain_start - atom_boundary_u), abs(chain_end - atom_boundary_u))
        * strand_length
    )
    boundary_witnesses = []
    if atom_boundary_side.startswith("REGULAR_"):
        boundary_witnesses.append(
            {
                "boundary_type": "REGULAR_COMPONENT_BOUNDARY",
                "regular_boundary_side": atom_boundary_side.removeprefix(
                    "REGULAR_"
                ),
                "lifted_boundary_u": atom_boundary_u,
            }
        )
    if atom_boundary_side == "ATOM_START_END_COLLAPSED":
        lower_forbidden_witnesses = [
            envelope
            for envelope in claim["forbidden_envelopes"]
            if envelope["direct_witness_edge_ids"]
            and abs(
                float(envelope["effective_u_interval"][1]) - atom_start
            )
            <= 1.0e-8
        ]
        upper_forbidden_witnesses = [
            envelope
            for envelope in claim["forbidden_envelopes"]
            if envelope["direct_witness_edge_ids"]
            and abs(
                float(envelope["effective_u_interval"][0]) - atom_end
            )
            <= 1.0e-8
        ]
        if (
            len(lower_forbidden_witnesses) == 1
            and len(upper_forbidden_witnesses) == 1
            and int(lower_forbidden_witnesses[0]["interval_index"])
            != int(upper_forbidden_witnesses[0]["interval_index"])
        ):
            coincident_forbidden_witnesses = [
                {
                    "boundary_type": "COLLAPSED_FORBIDDEN_GAP",
                    "forbidden_boundary_side": boundary_side,
                    "interval_index": int(envelope["interval_index"]),
                    "source_u_interval": list(envelope["source_u_interval"]),
                    "effective_u_interval": list(
                        envelope["effective_u_interval"]
                    ),
                    "direct_witness_edge_ids": list(
                        envelope["direct_witness_edge_ids"]
                    ),
                    "lifted_boundary_u": boundary_u,
                }
                for boundary_side, boundary_u, envelope in (
                    ("FORBIDDEN_END", atom_start, lower_forbidden_witnesses[0]),
                    ("FORBIDDEN_START", atom_end, upper_forbidden_witnesses[0]),
                )
            ]
            boundary_witnesses.append(
                {
                    "boundary_type": "COLLAPSED_FORBIDDEN_GAP",
                    "lifted_boundary_u": atom_boundary_u,
                    "coincident_witnesses": coincident_forbidden_witnesses,
                }
            )
    if atom_boundary_side != "ATOM_START_END_COLLAPSED":
        for span_interval in claim["span_u_intervals"]:
            for span_boundary_side, raw_boundary_u in (
                ("SPAN_START", float(span_interval[0])),
                ("SPAN_END", float(span_interval[1])),
            ):
                for shift in range(-2, 3) if claim["strand_cyclic"] else (0,):
                    lifted_boundary_u = raw_boundary_u + shift
                    if abs(lifted_boundary_u - atom_boundary_u) <= 1.0e-8:
                        boundary_witnesses.append(
                            {
                                "boundary_type": "PLAN_SPAN",
                                "span_boundary_side": span_boundary_side,
                                "raw_boundary_u": raw_boundary_u,
                                "lifted_boundary_u": lifted_boundary_u,
                            }
                        )
        for envelope in claim["forbidden_envelopes"]:
            for forbidden_boundary_side, forbidden_boundary_u in (
                ("FORBIDDEN_START", float(envelope["effective_u_interval"][0])),
                ("FORBIDDEN_END", float(envelope["effective_u_interval"][1])),
            ):
                for shift in range(-2, 3) if claim["strand_cyclic"] else (0,):
                    lifted_boundary_u = forbidden_boundary_u + shift
                    if abs(lifted_boundary_u - atom_boundary_u) <= 1.0e-8:
                        boundary_witnesses.append(
                            {
                                "boundary_type": "OVERLAP_FORBIDDEN_ENVELOPE",
                                "forbidden_boundary_side": forbidden_boundary_side,
                                "interval_index": int(envelope["interval_index"]),
                                "source_u_interval": list(
                                    envelope["source_u_interval"]
                                ),
                                "effective_u_interval": list(
                                    envelope["effective_u_interval"]
                                ),
                                "direct_witness_edge_ids": list(
                                    envelope["direct_witness_edge_ids"]
                                ),
                                "lifted_boundary_u": lifted_boundary_u,
                            }
                        )
    boundary_witness_groups = {}
    for witness in boundary_witnesses:
        key = (
            witness["boundary_type"],
            round(float(witness["lifted_boundary_u"]), 10),
            witness.get("span_boundary_side"),
            witness.get("forbidden_boundary_side"),
            witness.get("regular_boundary_side"),
        )
        boundary_witness_groups.setdefault(key, []).append(witness)
    if (
        claim["strand_cyclic"]
        and boundary_witness_groups
        and {
            key[0] for key in boundary_witness_groups
        }
        == {"PLAN_SPAN"}
        and len(boundary_witness_groups) == 2
        and {
            key[2] for key in boundary_witness_groups
        }
        == {"SPAN_START", "SPAN_END"}
        and max(
            key[1] for key in boundary_witness_groups
        )
        - min(key[1] for key in boundary_witness_groups)
        <= 1.0e-8
    ):
        coincident_witnesses = [
            witness
            for witnesses in boundary_witness_groups.values()
            for witness in witnesses
        ]
        boundary_u = sum(
            float(witness["lifted_boundary_u"])
            for witness in coincident_witnesses
        ) / len(coincident_witnesses)
        boundary_witness_groups = {
            (
                "PLAN_SPAN",
                round(boundary_u, 10),
                "CYCLIC_SEAM",
                None,
                None,
            ): [
                {
                    "boundary_type": "PLAN_SPAN",
                    "span_boundary_side": "CYCLIC_SEAM",
                    "lifted_boundary_u": boundary_u,
                    "coincident_witnesses": coincident_witnesses,
                }
            ]
        }
    if len(boundary_witness_groups) != 1:
        return {
            "rejected_stage": "BOUNDARY_WITNESS",
            "witnesses": [
                witness
                for witnesses in boundary_witness_groups.values()
                for witness in witnesses
            ],
        }
    grouped_witnesses = next(iter(boundary_witness_groups.values()))
    boundary_witness = (
        grouped_witnesses[0]
        if len(grouped_witnesses) == 1
        else {
            "boundary_type": grouped_witnesses[0]["boundary_type"],
            "lifted_boundary_u": grouped_witnesses[0]["lifted_boundary_u"],
            "boundary_side": grouped_witnesses[0].get("span_boundary_side")
            or grouped_witnesses[0].get("forbidden_boundary_side"),
            "coincident_witnesses": grouped_witnesses,
        }
    )
    plan_boundary_types = {
        "PLAN_SPAN",
        "OVERLAP_FORBIDDEN_ENVELOPE",
        "COLLAPSED_FORBIDDEN_GAP",
        "REGULAR_COMPONENT_BOUNDARY",
    }
    if (
        boundary_witness["boundary_type"]
        not in plan_boundary_types
        or chain_length > maximum_chain_length + 1.0e-10
        or atom_boundary_distance > radius * 2.0 + 1.0e-10
    ):
        return {
            "rejected_stage": "TERMINAL_TAIL_LIMITS",
            "boundary_type": boundary_witness["boundary_type"],
            "chain_length": chain_length,
            "maximum_chain_length": maximum_chain_length,
            "atom_boundary_distance": atom_boundary_distance,
            "maximum_atom_boundary_distance": radius * 2.0,
        }
    inner_u = (
        chain_end
        if atom_boundary_side in {"ATOM_START", "FORBIDDEN_START"}
        else chain_start
    )
    chain_endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            chain_endpoint_counts[endpoint_token] = (
                chain_endpoint_counts.get(endpoint_token, 0) + 1
            )
    chain_terminal_tokens = {
        token for token, count in chain_endpoint_counts.items() if count == 1
    }
    chain_rail_id = ledger_by_edge_id[oriented_chain["edge_ids"][0]].get(
        "rail_id"
    )
    all_rail_entries = [
        entry
        for entry in ledger_by_edge_id.values()
        if chain_rail_id is None or entry.get("rail_id") == chain_rail_id
    ]
    chain_terminal_degrees = sorted(
        sum(token in entry["endpoint_tokens"] for entry in all_rail_entries)
        for token in chain_terminal_tokens
    )
    adjacent_records = []
    rejected_adjacent_records = []
    side_edge_key = "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        side_interval_key = (
            "left_u_interval"
            if claim["side"] == "LEFT"
            else "right_u_interval"
        )
        record_start, record_end = sorted(
            map(float, record.get(side_interval_key, record["u_interval"]))
        )
        matching_record_boundary = None
        if record_start - 1.0e-8 <= inner_u <= record_end + 1.0e-8:
            matching_record_boundary = (
                "START"
                if abs(record_start - inner_u) <= abs(record_end - inner_u)
                else "END"
            )
        elif abs(record_start - inner_u) <= 1.0e-8:
            matching_record_boundary = "START"
        if abs(record_end - inner_u) <= 1.0e-8:
            matching_record_boundary = "END"
        if matching_record_boundary is None:
            continue
        record_endpoint_tokens = {
            endpoint_token
            for edge_id in (
                *record[side_edge_key],
                *record.get("terminal_extension_edge_ids", ()),
            )
            for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]
        }
        shared_tokens = sorted(chain_terminal_tokens & record_endpoint_tokens)
        chain_terminal_signatures = {
            signature
            for edge_id in oriented_chain["edge_ids"]
            for signature in ledger_by_edge_id[edge_id].get(
                "endpoint_topology_signatures",
                (),
            )
        }
        record_boundary_edge_id = record[side_edge_key][
            0 if matching_record_boundary == "START" else -1
        ]
        record_boundary_signatures = set(
            ledger_by_edge_id[record_boundary_edge_id].get(
                "endpoint_topology_signatures",
                (),
            )
        )
        shared_topology_signatures = sorted(
            chain_terminal_signatures & record_boundary_signatures
        )
        chain_face_signatures = {
            signature
            for edge_id in oriented_chain["edge_ids"]
            for signature in ledger_by_edge_id[edge_id].get(
                "adjacent_face_signatures",
                (),
            )
        }
        record_boundary_face_signatures = set(
            ledger_by_edge_id[record_boundary_edge_id].get(
                "adjacent_face_signatures",
                (),
            )
        )
        shared_face_signatures = sorted(
            chain_face_signatures & record_boundary_face_signatures
        )
        cyclic_full_span_closure = False
        direct_projection_gap_u = abs(
            (
                record_start
                if matching_record_boundary == "START"
                else record_end
            )
            - inner_u
        )
        direct_projection_gap_arc_length = (
            direct_projection_gap_u * strand_length
        )
        plan_span_topology_adjacent = (
            boundary_witness["boundary_type"] == "PLAN_SPAN"
            and (len(shared_tokens) == 1 or cyclic_full_span_closure)
        )
        boolean_split_topology_adjacent = (
            boundary_witness["boundary_type"]
            in {
                "OVERLAP_FORBIDDEN_ENVELOPE",
                "REGULAR_COMPONENT_BOUNDARY",
            }
            and not shared_tokens
            and (
                len(shared_topology_signatures) == 1
                or len(shared_face_signatures) == 1
            )
        )
        if (
            plan_span_topology_adjacent
            or boolean_split_topology_adjacent
            or (
                boundary_witness["boundary_type"]
                != "PLAN_SPAN"
                and len(shared_tokens) == 1
            )
        ):
            adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "regular_boundary_side": matching_record_boundary,
                    "shared_endpoint_token": (
                        shared_tokens[0]
                        if len(shared_tokens) == 1
                        else None
                    ),
                    "shared_endpoint_tokens": shared_tokens,
                    "shared_topology_signature": (
                        shared_topology_signatures[0]
                        if len(shared_topology_signatures) == 1
                        else None
                    ),
                    "shared_face_signature": (
                        shared_face_signatures[0]
                        if len(shared_face_signatures) == 1
                        else None
                    ),
                    "adjacency_type": (
                        "CYCLIC_FULL_SPAN_CLOSURE"
                        if cyclic_full_span_closure
                        else "BOOLEAN_SPLIT_TOPOLOGY_SIGNATURE"
                        if boolean_split_topology_adjacent
                        else "SHARED_BOUNDARY_ENDPOINT"
                    ),
                    "projection_gap_u": direct_projection_gap_u,
                    "projection_gap_arc_length": (
                        direct_projection_gap_arc_length
                    ),
                    "u_interval": list(record["u_interval"]),
                }
            )
        else:
            rejected_adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "matching_record_boundary": matching_record_boundary,
                    "record_u_interval": list(record["u_interval"]),
                    "shared_tokens": shared_tokens,
                    "record_endpoint_tokens": sorted(record_endpoint_tokens),
                    "shared_topology_signatures": shared_topology_signatures,
                    "shared_face_signatures": shared_face_signatures,
                }
            )
    if len(adjacent_records) != 1:
        if (
            atom_boundary_side == "ATOM_START_END_COLLAPSED"
            and boundary_witness["boundary_type"]
            == "COLLAPSED_FORBIDDEN_GAP"
            and chain_length <= radius * 1.0e-2 + 1.0e-10
        ):
            adjacent_records = [
                {
                    "consumer_id": None,
                    "regular_boundary_side": "COLLAPSED",
                    "shared_endpoint_token": None,
                    "adjacency_type": "COLLAPSED_FORBIDDEN_GAP",
                    "u_interval": [chain_start, chain_end],
                    "projection_gap_u": 0.0,
                    "projection_gap_arc_length": 0.0,
                }
            ]
        elif (
            not adjacent_records
            and boundary_witness["boundary_type"]
            == "OVERLAP_FORBIDDEN_ENVELOPE"
            and atom_boundary_distance <= radius * 2.0 + 1.0e-10
            and len(chain_terminal_tokens) == 2
            and all(degree <= 2 for degree in chain_terminal_degrees)
        ):
            adjacent_records = [
                {
                    "consumer_id": None,
                    "regular_boundary_side": "OVERLAP_BOUNDARY",
                    "shared_endpoint_token": None,
                    "adjacency_type": "PROVEN_OVERLAP_BOUNDARY_SETBACK",
                    "u_interval": [chain_start, chain_end],
                    "direct_witness_edge_ids": list(
                        boundary_witness.get("direct_witness_edge_ids", ())
                    ),
                }
            ]
        else:
            return {
                "rejected_stage": "ADJACENT_REGULAR",
                "adjacent_records": adjacent_records,
                "rejected_adjacent_records": rejected_adjacent_records,
                "inner_u": inner_u,
                "chain_terminal_tokens": sorted(chain_terminal_tokens),
                "chain_terminal_degrees": chain_terminal_degrees,
                "chain_length": chain_length,
                "maximum_chain_length": maximum_chain_length,
                "atom_boundary_distance": atom_boundary_distance,
                "maximum_atom_boundary_distance": radius * 2.0,
                "boundary_witness": boundary_witness,
                "adjacency_contract": "EXACT_OR_CONTAINING_REGULAR_INTERVAL",
            }
    return {
        "proof_version": "REGULAR_TERMINAL_TAIL_HANDOFF_V1",
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "convexity": int(claim["convexity"]),
        "side": claim["side"],
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "atom_u_interval": list(claim["u_interval"]),
        "atom_boundary_side": atom_boundary_side,
        "boundary_witness": boundary_witness,
        "chain_length": chain_length,
        "maximum_chain_length": maximum_chain_length,
        "atom_boundary_distance": atom_boundary_distance,
        "maximum_atom_boundary_distance": radius * 2.0,
        "regular_adjacency_contract": "EXACT_OR_CONTAINING_REGULAR_INTERVAL",
        "adjacent_regular": adjacent_records[0],
        "chain_terminal_degrees": chain_terminal_degrees,
    }


# 证明 maximal chain 的 atom 内侧仅含短残段，atom 外侧部分终止于相邻 Plan span/junction；
# 禁止把跨 span 的大 Edge误报为 regular，而是保留为 Junction handoff。
# oriented_chain/start_u/end_u/claim/regular_records/ledger_by_edge_id/radius: 当前链、投影、atom、Strip、ledger 与半径；返回跨 span 结构 proof 或 None。
def _atom_boundary_junction_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claim,
    regular_records,
    ledger_by_edge_id,
    radius,
):
    if oriented_chain.get("is_cyclic") or not oriented_chain.get("edge_ids"):
        return None
    chain_start, chain_end = sorted((float(start_u), float(end_u)))
    atom_start, atom_end = sorted(map(float, claim["u_interval"]))
    boundary_candidates = []
    for shift in range(-2, 3) if claim.get("strand_cyclic") else (0,):
        lifted_start = chain_start + shift
        lifted_end = chain_end + shift
        if lifted_start < atom_start - 1.0e-8 < lifted_end + 1.0e-8:
            boundary_candidates.append(
                (abs(shift), "ATOM_START", atom_start, lifted_end)
            )
        if lifted_start - 1.0e-8 < atom_end < lifted_end - 1.0e-8:
            boundary_candidates.append(
                (abs(shift), "ATOM_END", atom_end, lifted_start)
            )
    if boundary_candidates:
        minimum_shift = min(candidate[0] for candidate in boundary_candidates)
        boundary_candidates = [
            candidate
            for candidate in boundary_candidates
            if candidate[0] == minimum_shift
        ]
    if len(boundary_candidates) != 1:
        return None
    _, boundary_side, boundary_u, inner_u = boundary_candidates[0]
    inside_atom_arc_length = abs(inner_u - boundary_u) * max(
        float(claim["strand_length"]), 1.0e-12
    )
    maximum_inside_atom_arc_length = radius * 2.0
    if inside_atom_arc_length > maximum_inside_atom_arc_length + 1.0e-10:
        return {
            "rejected_stage": "ATOM_BOUNDARY_INSIDE_LENGTH",
            "inside_atom_arc_length": inside_atom_arc_length,
            "maximum_inside_atom_arc_length": maximum_inside_atom_arc_length,
            "boundary_side": boundary_side,
        }
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    adjacent_records = []
    chain_terminal_tokens = {
        token
        for token in oriented_chain.get("endpoint_tokens", ())
        if sum(
            token in ledger_by_edge_id[edge_id]["endpoint_tokens"]
            for edge_id in oriented_chain["edge_ids"]
        )
        == 1
    }
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        record_start, record_end = sorted(map(float, record["u_interval"]))
        endpoint_candidates = sorted(
            (
                (
                    abs(record_u - chain_u),
                    record_boundary_side,
                    record_u,
                )
                for record_boundary_side, record_u in (
                    ("START", record_start),
                    ("END", record_end),
                )
                for chain_u in (chain_start, chain_end)
            )
        )
        _, record_boundary_side, record_boundary_u = endpoint_candidates[0]
        if endpoint_candidates[0][0] > 1.0e-4:
            continue
        boundary_edge_id = record[side_edge_key][
            0 if record_boundary_side == "START" else -1
        ]
        shared_tokens = sorted(
            chain_terminal_tokens
            & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
        )
        if len(shared_tokens) == 1:
            adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "regular_boundary_side": record_boundary_side,
                    "shared_endpoint_token": shared_tokens[0],
                    "u_interval": list(record["u_interval"]),
                }
            )
    unique_adjacent = {
        (record["consumer_id"], record["shared_endpoint_token"]): record
        for record in adjacent_records
    }
    if len(unique_adjacent) != 1 or len(chain_terminal_tokens) != 2:
        return {
            "rejected_stage": "ATOM_BOUNDARY_ADJACENT_REGULAR",
            "boundary_side": boundary_side,
            "boundary_u": boundary_u,
            "inner_u": inner_u,
            "chain_terminal_tokens": sorted(chain_terminal_tokens),
            "adjacent_records": adjacent_records,
        }
    adjacent = next(iter(unique_adjacent.values()))
    adjacent_start, adjacent_end = sorted(
        map(float, adjacent["u_interval"])
    )
    residual_gap_arc_length = min(
        abs(chain_start - adjacent_start),
        abs(chain_start - adjacent_end),
        abs(chain_end - adjacent_start),
        abs(chain_end - adjacent_end),
    ) * max(float(claim["strand_length"]), 1.0e-12)
    maximum_residual_gap_arc_length = radius * 2.0
    if residual_gap_arc_length > maximum_residual_gap_arc_length + 1.0e-10:
        return {
            "rejected_stage": "ATOM_BOUNDARY_REGULAR_GAP",
            "residual_gap_arc_length": residual_gap_arc_length,
            "maximum_residual_gap_arc_length": maximum_residual_gap_arc_length,
            "adjacent_regular": adjacent,
        }
    outer_tokens = chain_terminal_tokens - {adjacent["shared_endpoint_token"]}
    if len(outer_tokens) != 1:
        return None
    outer_token = next(iter(outer_tokens))
    rail_id = ledger_by_edge_id[oriented_chain["edge_ids"][0]]["rail_id"]
    outer_degree = sum(
        outer_token in entry["endpoint_tokens"]
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == rail_id
    )
    if outer_degree not in {1, 2}:
        return None
    chain_coordinates = [Vector(point) for point in oriented_chain["coordinates"]]
    chain_length = sum(
        (following - current).length
        for current, following in zip(chain_coordinates, chain_coordinates[1:])
    )
    return {
        "proof_version": "ATOM_BOUNDARY_JUNCTION_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "convexity": int(claim["convexity"]),
        "side": claim["side"],
        "atom_boundary_side": boundary_side,
        "atom_boundary_u": boundary_u,
        "inside_atom_arc_length": inside_atom_arc_length,
        "maximum_inside_atom_arc_length": maximum_inside_atom_arc_length,
        "residual_gap_arc_length": residual_gap_arc_length,
        "maximum_residual_gap_arc_length": maximum_residual_gap_arc_length,
        "chain_length": chain_length,
        "adjacent_regular": adjacent,
        "outer_endpoint_token": outer_token,
        "outer_endpoint_degree": outer_degree,
    }


# 将 regular matching 中的裁剪残段与随后提交的完整 structural handoff 做双向核对；
# strip_attempts/setback_ports/ledger_by_edge_id: matching 诊断、已提交端口与 Boundary Edge ledger；返回更新后的诊断和核对记录。
def _reconcile_structural_handoff_components(
    strip_attempts,
    setback_ports,
    ledger_by_edge_id,
):
    proof_entries = []
    for port in setback_ports:
        port_edge_ids = set(port.get("ordered_edge_ids", ()))
        for proof in port.get("micro_loop_junction_proofs", ()):
            if proof.get("proof_version") != "REGULAR_TERMINAL_TAIL_HANDOFF_V1":
                continue
            proof_edge_ids = set(proof.get("edge_ids", ()))
            if not proof_edge_ids or not proof_edge_ids.issubset(port_edge_ids):
                continue
            if proof.get("boundary_witness", {}).get("boundary_type") not in {
                "OVERLAP_FORBIDDEN_ENVELOPE",
                "REGULAR_COMPONENT_BOUNDARY",
            }:
                continue
            if proof.get("adjacent_regular", {}).get("adjacency_type") not in {
                "BOOLEAN_SPLIT_TOPOLOGY_SIGNATURE",
            }:
                continue
            chain_length = float(proof.get("chain_length", float("inf")))
            maximum_chain_length = float(
                proof.get("maximum_chain_length", float("-inf"))
            )
            if chain_length > maximum_chain_length + 1.0e-10:
                continue
            if sorted(map(int, proof.get("chain_terminal_degrees", ()))) != [1, 2]:
                continue
            proof_entries.append((port, proof, proof_edge_ids))

    reconciled_components = []
    for attempt in strip_attempts:
        remaining_components = []
        attempt_reconciled = []
        for unresolved in attempt.get("unresolved_components", ()):
            if unresolved.get("reason") != "NO_PERFECT_MATCHING":
                remaining_components.append(unresolved)
                continue
            component_runs = list(unresolved.get("left_runs", ())) + list(
                unresolved.get("right_runs", ())
            )
            if bool(unresolved.get("left_runs")) == bool(
                unresolved.get("right_runs")
            ):
                remaining_components.append(unresolved)
                continue
            component_edge_ids = {
                edge_id
                for run in component_runs
                for edge_id in run.get("edge_ids", ())
            }
            if not component_edge_ids:
                remaining_components.append(unresolved)
                continue
            component_start, component_end = sorted(
                map(float, unresolved.get("component_u_interval", (0.0, 0.0)))
            )
            matching_entries = []
            for port, proof, proof_edge_ids in proof_entries:
                if proof.get("correspondence_id") != attempt["correspondence_id"]:
                    continue
                if proof.get("atom_id") != unresolved.get("atom_id"):
                    continue
                component_side = (
                    "LEFT" if unresolved.get("left_runs") else "RIGHT"
                )
                if proof.get("side") != component_side:
                    continue
                proof_start, proof_end = sorted(
                    map(float, proof.get("component_u_interval", (0.0, 0.0)))
                )
                if (
                    component_start < proof_start - 1.0e-8
                    or component_end > proof_end + 1.0e-8
                    or not component_edge_ids.issubset(proof_edge_ids)
                ):
                    continue
                proof_source_patch_id = int(
                    proof.get("patch_pair", (-1, -1))[
                        0 if component_side == "LEFT" else 1
                    ]
                )
                if any(
                    int(ledger_by_edge_id[edge_id]["source_patch_id"])
                    != proof_source_patch_id
                    for edge_id in component_edge_ids
                ):
                    continue
                if any(
                    ledger_by_edge_id[edge_id].get("consumer_id")
                    != port["port_id"]
                    for edge_id in component_edge_ids
                ):
                    continue
                matching_entries.append((port, proof))
            unique_ports = {
                port["port_id"]: (port, proof)
                for port, proof in matching_entries
            }
            if len(unique_ports) != 1:
                remaining_components.append(unresolved)
                continue
            port, proof = next(iter(unique_ports.values()))
            reconciliation = {
                "proof_version": "STRUCTURAL_HANDOFF_COMPONENT_RECONCILIATION_V1",
                "component_id": unresolved.get("component_id"),
                "correspondence_id": attempt["correspondence_id"],
                "atom_id": unresolved.get("atom_id"),
                "component_u_interval": [component_start, component_end],
                "edge_ids": sorted(component_edge_ids),
                "port_id": port["port_id"],
                "structural_proof_version": proof["proof_version"],
                "structural_component_u_interval": list(
                    proof["component_u_interval"]
                ),
            }
            attempt_reconciled.append(reconciliation)
            reconciled_components.append(reconciliation)
        attempt["unresolved_components"] = remaining_components
        attempt["structural_handoff_components"] = attempt_reconciled
    return reconciled_components


# 证明 maximal Boundary chain 从唯一 Regular Strip 端点穿过权威 Plan span 边界，并终止于真实 Rail terminal/junction。
# oriented_chain/start_u/end_u/claim/regular_records/ledger_by_edge_id/source_patch_id: 当前链、投影、唯一 atom、已提交 Strip、完整 ledger 与 owner Patch；返回 crossing handoff proof 或 None。
def _plan_span_crossing_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius,
):
    if (
        oriented_chain.get("is_cyclic")
        or not oriented_chain.get("edge_ids")
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    chain_start, chain_end = sorted((float(start_u), float(end_u)))
    if chain_end - chain_start <= 1.0e-8:
        return None
    chain_coordinates = [Vector(point) for point in oriented_chain["coordinates"]]
    chain_length = sum(
        (following - current).length
        for current, following in zip(chain_coordinates, chain_coordinates[1:])
    )
    crossing_candidates = []
    for span_interval in claim["span_u_intervals"]:
        for span_boundary_side, raw_boundary_u in (
            ("SPAN_START", float(span_interval[0])),
            ("SPAN_END", float(span_interval[1])),
        ):
            for shift in range(-2, 3) if claim["strand_cyclic"] else (0,):
                lifted_boundary_u = raw_boundary_u + shift
                if (
                    chain_start + 1.0e-8 < lifted_boundary_u
                    and lifted_boundary_u < chain_end - 1.0e-8
                ):
                    crossing_candidates.append(
                        {
                            "span_boundary_side": span_boundary_side,
                            "raw_boundary_u": raw_boundary_u,
                            "lifted_boundary_u": lifted_boundary_u,
                        }
                    )
    unique_crossings = {
        (
            candidate["span_boundary_side"],
            round(candidate["lifted_boundary_u"], 10),
        ): candidate
        for candidate in crossing_candidates
    }
    if len(unique_crossings) != 1:
        return None
    crossing = next(iter(unique_crossings.values()))
    inner_boundary_side = (
        "START" if crossing["span_boundary_side"] == "SPAN_END" else "END"
    )
    inner_u = chain_start if inner_boundary_side == "START" else chain_end
    strand_length = max(float(claim["strand_length"]), 1.0e-12)
    inside_span_arc_length = abs(
        inner_u - float(crossing["lifted_boundary_u"])
    ) * strand_length
    maximum_inside_span_arc_length = radius * 2.0
    if inside_span_arc_length > maximum_inside_span_arc_length + 1.0e-10:
        return {
            "rejected_stage": "PLAN_SPAN_CROSSING_INSIDE_LENGTH",
            "chain_length": chain_length,
            "inside_span_arc_length": inside_span_arc_length,
            "maximum_inside_span_arc_length": maximum_inside_span_arc_length,
            "span_boundary": crossing,
        }
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    chain_endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            chain_endpoint_counts[endpoint_token] = (
                chain_endpoint_counts.get(endpoint_token, 0) + 1
            )
    chain_terminal_tokens = {
        token for token, count in chain_endpoint_counts.items() if count == 1
    }
    if len(chain_terminal_tokens) != 2:
        return None
    adjacent_records = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        record_start, record_end = sorted(map(float, record["u_interval"]))
        record_boundary_side = (
            "END" if inner_boundary_side == "START" else "START"
        )
        record_boundary_u = (
            record_end if record_boundary_side == "END" else record_start
        )
        if abs(record_boundary_u - inner_u) > 1.0e-4:
            continue
        boundary_edge_id = record[side_edge_key][
            -1 if record_boundary_side == "END" else 0
        ]
        record_endpoint_tokens = set(
            ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"]
        )
        shared_tokens = sorted(chain_terminal_tokens & record_endpoint_tokens)
        if len(shared_tokens) != 1:
            continue
        adjacent_records.append(
            {
                "consumer_id": record["consumer_id"],
                "regular_boundary_side": record_boundary_side,
                "shared_endpoint_token": shared_tokens[0],
                "u_interval": list(record["u_interval"]),
                "projection_gap_u": abs(record_boundary_u - inner_u),
            }
        )
    unique_adjacent_records = {
        (
            record["consumer_id"],
            record["regular_boundary_side"],
            record["shared_endpoint_token"],
        ): record
        for record in adjacent_records
    }
    if len(unique_adjacent_records) != 1:
        return None
    adjacent_record = next(iter(unique_adjacent_records.values()))
    outer_terminal_tokens = chain_terminal_tokens - {
        adjacent_record["shared_endpoint_token"]
    }
    if len(outer_terminal_tokens) != 1:
        return None
    outer_terminal_token = next(iter(outer_terminal_tokens))
    rail_id = ledger_by_edge_id[oriented_chain["edge_ids"][0]]["rail_id"]
    outer_terminal_degree = sum(
        outer_terminal_token in entry["endpoint_tokens"]
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == rail_id
    )
    if outer_terminal_degree not in {1, 2}:
        return None
    return {
        "proof_version": "PLAN_SPAN_CROSSING_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "convexity": int(claim["convexity"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "span_boundary": crossing,
        "adjacent_regular": adjacent_record,
        "outer_terminal_token": outer_terminal_token,
        "outer_terminal_degree": outer_terminal_degree,
        "chain_length": chain_length,
        "inside_span_arc_length": inside_span_arc_length,
        "maximum_inside_span_arc_length": maximum_inside_span_arc_length,
        "handoff_boundary_type": (
            "PLAN_TERMINAL"
            if outer_terminal_degree == 1
            else "PLAN_JUNCTION_BRANCH"
        ),
    }


# 证明单 Edge Boundary 连接同一 correspondence 的两个 Regular Strip terminals，作为 deterministic bridge 交给 junction handoff。
# oriented_chain/claim/regular_records/ledger_by_edge_id/source_patch_id: 当前单 Edge、唯一 atom、已提交 Strip、完整 ledger 与 owner Patch；返回 bridge proof 或 None。
def _regular_component_bridge_handoff_proof(
    oriented_chain,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius=None,
):
    if (
        oriented_chain.get("is_cyclic")
        or not oriented_chain.get("edge_ids")
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    edge_ids = list(oriented_chain["edge_ids"])
    if len(edge_ids) != 1:
        if radius is None or len(edge_ids) > 2:
            return None
        chain_length = sum(
            (
                Vector(ledger_by_edge_id[edge_id]["endpoints"][1])
                - Vector(ledger_by_edge_id[edge_id]["endpoints"][0])
            ).length
            for edge_id in edge_ids
        )
        if chain_length > radius * 1.0e-1 + 1.0e-10:
            return None
    chain_endpoint_counts = {}
    for edge_id in edge_ids:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            chain_endpoint_counts[endpoint_token] = (
                chain_endpoint_counts.get(endpoint_token, 0) + 1
            )
    chain_terminal_tokens = {
        token for token, count in chain_endpoint_counts.items() if count == 1
    }
    if len(chain_terminal_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    adjacent_records = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        record_endpoint_tokens = {
            token
            for record_edge_id in record[side_edge_key]
            for token in ledger_by_edge_id[record_edge_id]["endpoint_tokens"]
        }
        shared_tokens = sorted(chain_terminal_tokens & record_endpoint_tokens)
        if len(shared_tokens) == 1:
            adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "shared_endpoint_token": shared_tokens[0],
                    "side_u_interval": list(
                        record.get(
                            "left_u_interval"
                            if claim["side"] == "LEFT"
                            else "right_u_interval",
                            record["u_interval"],
                        )
                    ),
                }
            )
    unique_records = {
        (record["consumer_id"], record["shared_endpoint_token"]): record
        for record in adjacent_records
    }
    if (
        len(unique_records) != 2
        or {
            record["shared_endpoint_token"]
            for record in unique_records.values()
        }
        != chain_terminal_tokens
    ):
        return None
    return {
        "proof_version": "REGULAR_COMPONENT_BRIDGE_HANDOFF_V1",
        "edge_ids": edge_ids,
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "convexity": int(claim["convexity"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "adjacent_regular_records": sorted(
            unique_records.values(),
            key=lambda record: (
                record["side_u_interval"],
                record["consumer_id"],
            ),
        ),
        "bridge_endpoint_tokens": sorted(chain_terminal_tokens),
        "maximum_bridge_length": radius * 1.0e-1 if radius is not None else None,
    }


# 证明单 Edge Boundary 是 Boolean 产生的近零长度 connector，并以真实共享端点接续唯一 Regular Strip。
# oriented_chain/claim/regular_records/ledger_by_edge_id/source_patch_id/radius: 当前单 Edge、atom、已提交 Strip、ledger、owner Patch 与半径；返回严格 connector proof 或 None。
def _zero_length_regular_connector_handoff_proof(
    oriented_chain,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius,
):
    if (
        oriented_chain.get("is_cyclic")
        or len(oriented_chain.get("edge_ids", ())) != 1
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    edge_id = oriented_chain["edge_ids"][0]
    edge_entry = ledger_by_edge_id[edge_id]
    coordinates = [Vector(point) for point in edge_entry["endpoints"]]
    edge_length = (coordinates[1] - coordinates[0]).length
    maximum_edge_length = max(radius * 1.0e-2, 2.0e-6)
    if edge_length > maximum_edge_length + 1.0e-10:
        return None
    connector_tokens = set(edge_entry["endpoint_tokens"])
    if len(connector_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    adjacent_records = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        for boundary_side, boundary_edge_id in (
            ("START", record[side_edge_key][0]),
            ("END", record[side_edge_key][-1]),
        ):
            shared_tokens = sorted(
                connector_tokens
                & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
            )
            if len(shared_tokens) == 1:
                adjacent_records.append(
                    {
                        "consumer_id": record["consumer_id"],
                        "regular_boundary_side": boundary_side,
                        "shared_endpoint_token": shared_tokens[0],
                        "u_interval": list(record["u_interval"]),
                    }
                )
    unique_records = {
        (
            record["consumer_id"],
            record["regular_boundary_side"],
            record["shared_endpoint_token"],
        ): record
        for record in adjacent_records
    }


# 证明短 Boundary tail 以真实共享端点延续唯一 Regular Strip，且另一端是 Rail terminal。
# oriented_chain/claim/regular_records/ledger_by_edge_id/source_patch_id/radius: 当前短链、atom、Strip、ledger、owner Patch 与半径；返回 terminal proof 或 None。
def _short_regular_terminal_handoff_proof(
    oriented_chain,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius,
):
    if (
        oriented_chain.get("is_cyclic")
        or not oriented_chain.get("edge_ids")
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    edge_ids = list(oriented_chain["edge_ids"])
    chain_length = sum(
        (
            Vector(ledger_by_edge_id[edge_id]["endpoints"][1])
            - Vector(ledger_by_edge_id[edge_id]["endpoints"][0])
        ).length
        for edge_id in edge_ids
    )
    maximum_chain_length = radius * 1.0
    if chain_length > maximum_chain_length + 1.0e-10:
        return None
    endpoint_counts = {}
    for edge_id in edge_ids:
        for token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            endpoint_counts[token] = endpoint_counts.get(token, 0) + 1
    terminal_tokens = {
        token for token, count in endpoint_counts.items() if count == 1
    }
    if len(terminal_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    adjacent_records = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        for boundary_side, boundary_edge_id in (
            ("START", record[side_edge_key][0]),
            ("END", record[side_edge_key][-1]),
        ):
            shared_tokens = sorted(
                terminal_tokens
                & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
            )
            if len(shared_tokens) == 1:
                adjacent_records.append(
                    {
                        "consumer_id": record["consumer_id"],
                        "regular_boundary_side": boundary_side,
                        "shared_endpoint_token": shared_tokens[0],
                        "u_interval": list(record["u_interval"]),
                    }
                )
    unique_records = {
        (
            record["consumer_id"],
            record["regular_boundary_side"],
            record["shared_endpoint_token"],
        ): record
        for record in adjacent_records
    }
    same_consumer_records = {}
    for record in unique_records.values():
        same_consumer_records.setdefault(record["consumer_id"], []).append(
            record
        )
    collapsed_same_consumer_records = {
        consumer_id: records
        for consumer_id, records in same_consumer_records.items()
        if len(records) == 2
        and {record["regular_boundary_side"] for record in records}
        == {"START", "END"}
        and len(
            {record["shared_endpoint_token"] for record in records}
        )
        == 1
    }
    if len(collapsed_same_consumer_records) == 1:
        consumer_id, records = next(
            iter(collapsed_same_consumer_records.items())
        )
        representative = min(
            records,
            key=lambda record: record["regular_boundary_side"],
        )
        unique_records = {
            (
                consumer_id,
                "COLLAPSED",
                representative["shared_endpoint_token"],
            ): {
                **representative,
                "regular_boundary_side": "COLLAPSED",
            }
        }
    if (
        len(unique_records) == 2
        and {
            record["shared_endpoint_token"]
            for record in unique_records.values()
        }
        == terminal_tokens
    ):
        return {
            "proof_version": "SHORT_REGULAR_BRIDGE_HANDOFF_V1",
            "edge_ids": edge_ids,
            "correspondence_id": claim["correspondence_id"],
            "atom_id": claim["atom_id"],
            "span_id": int(claim["span_id"]),
            "patch_pair": list(claim["patch_pair"]),
            "side": claim["side"],
            "source_patch_id": int(source_patch_id),
            "chain_length": chain_length,
            "maximum_chain_length": maximum_chain_length,
            "adjacent_regular_records": sorted(
                unique_records.values(),
                key=lambda record: (
                    record["u_interval"],
                    record["consumer_id"],
                ),
            ),
            "bridge_endpoint_tokens": sorted(terminal_tokens),
        }
    if len(unique_records) != 1:
        return {
            "rejected_stage": "SHORT_REGULAR_TERMINAL_ADJACENCY",
            "edge_ids": edge_ids,
            "chain_length": chain_length,
            "maximum_chain_length": maximum_chain_length,
            "terminal_tokens": sorted(terminal_tokens),
            "adjacent_records": adjacent_records,
        }
    adjacent_record = next(iter(unique_records.values()))
    outer_tokens = terminal_tokens - {
        adjacent_record["shared_endpoint_token"]
    }
    rail_id = ledger_by_edge_id[edge_ids[0]]["rail_id"]
    outer_degrees = sorted(
        sum(
            token in entry["endpoint_tokens"]
            for entry in ledger_by_edge_id.values()
            if entry["rail_id"] == rail_id
        )
        for token in outer_tokens
    )
    if len(outer_tokens) != 1 or outer_degrees != [1]:
        return {
            "rejected_stage": "SHORT_REGULAR_TERMINAL_OUTER_ENDPOINT",
            "edge_ids": edge_ids,
            "chain_length": chain_length,
            "maximum_chain_length": maximum_chain_length,
            "terminal_tokens": sorted(terminal_tokens),
            "adjacent_record": adjacent_record,
            "outer_tokens": sorted(outer_tokens),
            "outer_degrees": outer_degrees,
        }
    return {
        "proof_version": "SHORT_REGULAR_TERMINAL_HANDOFF_V1",
        "edge_ids": edge_ids,
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "chain_length": chain_length,
        "maximum_chain_length": maximum_chain_length,
        "adjacent_regular": adjacent_record,
        "outer_endpoint_token": next(iter(outer_tokens)),
        "outer_endpoint_degree": outer_degrees[0],
    }


# 证明单 Edge residual 从唯一 Regular Strip 端点延续，且同 atom 对侧 Boundary 覆盖其完整 u 区间。
# oriented_chain/claim/regular_records/ledger_by_edge_id/source_patch_id: 当前单 Edge、atom、Strip、ledger 与 owner Patch；返回 paired coverage proof 或 None。
def _paired_boundary_residual_handoff_proof(
    oriented_chain,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius,
    micro_loop_proof_by_edge_id,
):
    if (
        oriented_chain.get("is_cyclic")
        or len(oriented_chain.get("edge_ids", ())) != 1
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    def reject(stage, **diagnostics):
        return {
            "rejected_stage": stage,
            **diagnostics,
        }
    edge_id = oriented_chain["edge_ids"][0]
    terminal_tokens = set(ledger_by_edge_id[edge_id]["endpoint_tokens"])
    if len(terminal_tokens) != 2:
        return reject("TERMINAL_TOKENS", tokens=sorted(terminal_tokens))
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    adjacent = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        for boundary_side, boundary_edge_id in (
            ("START", record[side_edge_key][0]),
            ("END", record[side_edge_key][-1]),
        ):
            shared_tokens = sorted(
                terminal_tokens
                & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
            )
            if len(shared_tokens) == 1:
                adjacent.append(
                    {
                        "consumer_id": record["consumer_id"],
                        "regular_boundary_side": boundary_side,
                        "shared_endpoint_token": shared_tokens[0],
                        "u_interval": list(record["u_interval"]),
                    }
                )
    unique_adjacent = {
        (
            record["consumer_id"],
            record["regular_boundary_side"],
            record["shared_endpoint_token"],
        ): record
        for record in adjacent
    }
    adjacent_by_consumer = {}
    for record in unique_adjacent.values():
        adjacent_by_consumer.setdefault(record["consumer_id"], []).append(
            record
        )
    collapsed_adjacent = {
        consumer_id: records
        for consumer_id, records in adjacent_by_consumer.items()
        if len(records) == 2
        and {record["regular_boundary_side"] for record in records}
        == {"START", "END"}
        and len(
            {record["shared_endpoint_token"] for record in records}
        )
        == 1
    }
    if len(collapsed_adjacent) == 1:
        consumer_id, records = next(iter(collapsed_adjacent.items()))
        representative = min(
            records,
            key=lambda record: record["regular_boundary_side"],
        )
        unique_adjacent = {
            (consumer_id, "COLLAPSED", representative["shared_endpoint_token"]): {
                **representative,
                "regular_boundary_side": "COLLAPSED",
            }
        }
    if len(unique_adjacent) != 1:
        return reject(
            "ADJACENT_REGULAR",
            terminal_tokens=sorted(terminal_tokens),
            adjacent_records=adjacent,
        )
    adjacent_record = next(iter(unique_adjacent.values()))
    outer_tokens = terminal_tokens - {adjacent_record["shared_endpoint_token"]}
    if len(outer_tokens) != 1:
        return reject("OUTER_TOKEN", outer_tokens=sorted(outer_tokens))
    chain_coordinates = [
        Vector(point) for point in oriented_chain["coordinates"]
    ]
    chain_start, chain_end = chain_coordinates
    chain_edge = chain_end - chain_start
    chain_length = chain_edge.length
    adjacent_edge_id = next(
        (
            boundary_edge_id
            for record in regular_records
            if record["consumer_id"] == adjacent_record["consumer_id"]
            for boundary_edge_id in record[side_edge_key]
            if adjacent_record["shared_endpoint_token"]
            in ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"]
        ),
        None,
    )
    if adjacent_edge_id is None:
        return reject("ADJACENT_EDGE")
    adjacent_start, adjacent_end = map(
        Vector,
        ledger_by_edge_id[adjacent_edge_id]["endpoints"],
    )
    adjacent_outer_token = next(
        token
        for token in ledger_by_edge_id[adjacent_edge_id]["endpoint_tokens"]
        if token != adjacent_record["shared_endpoint_token"]
    )
    adjacent_outer_point = (
        adjacent_start
        if ledger_by_edge_id[adjacent_edge_id]["endpoint_tokens"][0]
        == adjacent_outer_token
        else adjacent_end
    )
    shared_point = (
        chain_start
        if ledger_by_edge_id[edge_id]["endpoint_tokens"][0]
        == adjacent_record["shared_endpoint_token"]
        else chain_end
    )
    residual_outer_point = chain_end if shared_point == chain_start else chain_start
    continuation = residual_outer_point - shared_point
    previous = shared_point - adjacent_outer_point
    if chain_length <= 1.0e-12 or previous.length <= 1.0e-12:
        return reject(
            "DEGENERATE_CONTINUATION",
            chain_length=chain_length,
            previous_length=previous.length,
        )
    continuation_cosine = continuation.dot(previous) / (
        continuation.length * previous.length
    )
    maximum_chain_length = radius * 2.0
    outer_degrees = sorted(
        sum(
            token in entry["endpoint_tokens"]
            for entry in ledger_by_edge_id.values()
            if entry["rail_id"] == ledger_by_edge_id[edge_id]["rail_id"]
        )
        for token in outer_tokens
    )
    folded_same_consumer_terminal = False
    numeric_connector_edge_ids = []
    numeric_connector_bridge = False
    direct_rail_terminal = False
    if (
        chain_length > maximum_chain_length + 1.0e-10
        or continuation_cosine < 0.95
        or outer_degrees not in ([1], [2])
    ):
        return reject(
            "RESIDUAL_GEOMETRY_LIMITS",
            chain_length=chain_length,
            maximum_chain_length=maximum_chain_length,
            continuation_cosine=continuation_cosine,
            minimum_continuation_cosine=0.95,
            outer_degrees=outer_degrees,
            adjacent_regular_boundary_side=adjacent_record[
                "regular_boundary_side"
            ],
            folded_same_consumer_terminal=folded_same_consumer_terminal,
            numeric_connector_bridge=numeric_connector_bridge,
            numeric_connector_edge_ids=numeric_connector_edge_ids,
            direct_rail_terminal=direct_rail_terminal,
        )
    return {
        "proof_version": "PAIRED_BOUNDARY_RESIDUAL_HANDOFF_V1",
        "edge_ids": [edge_id],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "adjacent_regular": adjacent_record,
        "continuation_cosine": continuation_cosine,
        "chain_length": chain_length,
        "maximum_chain_length": maximum_chain_length,
        "folded_same_consumer_terminal": folded_same_consumer_terminal,
        "numeric_connector_bridge": numeric_connector_bridge,
        "numeric_connector_edge_ids": numeric_connector_edge_ids,
        "direct_rail_terminal": direct_rail_terminal,
        "outer_endpoint_token": next(iter(outer_tokens)),
    }


# 证明单 Edge Boundary 以真实端点连接唯一 Regular Strip 与已证明 overlap setback。
# oriented_chain/claim/regular_records/ledger_by_edge_id/source_patch_id/overlap_proof_by_edge_id: 当前单 Edge、atom、Strip、ledger、owner Patch 与 paired overlap proofs；返回 bridge proof 或 None。
def _regular_overlap_bridge_handoff_proof(
    oriented_chain,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    overlap_proof_by_edge_id,
):
    if (
        oriented_chain.get("is_cyclic")
        or len(oriented_chain.get("edge_ids", ())) != 1
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    edge_id = oriented_chain["edge_ids"][0]
    bridge_tokens = set(ledger_by_edge_id[edge_id]["endpoint_tokens"])
    if len(bridge_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    regular_adjacencies = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        for boundary_side, boundary_edge_id in (
            ("START", record[side_edge_key][0]),
            ("END", record[side_edge_key][-1]),
        ):
            shared_tokens = sorted(
                bridge_tokens
                & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
            )
            if len(shared_tokens) == 1:
                regular_adjacencies.append(
                    {
                        "consumer_id": record["consumer_id"],
                        "regular_boundary_side": boundary_side,
                        "shared_endpoint_token": shared_tokens[0],
                        "u_interval": list(record["u_interval"]),
                    }
                )
    unique_regular = {
        (
            record["consumer_id"],
            record["regular_boundary_side"],
            record["shared_endpoint_token"],
        ): record
        for record in regular_adjacencies
    }
    overlap_adjacencies = []
    for overlap_edge_id, proof in overlap_proof_by_edge_id.items():
        if overlap_edge_id not in ledger_by_edge_id:
            continue
        overlap_entry = ledger_by_edge_id[overlap_edge_id]
        if overlap_entry["rail_id"] != ledger_by_edge_id[edge_id]["rail_id"]:
            continue
        shared_tokens = sorted(
            bridge_tokens & set(overlap_entry["endpoint_tokens"])
        )
        if len(shared_tokens) == 1:
            overlap_adjacencies.append(
                {
                    "edge_id": overlap_edge_id,
                    "shared_endpoint_token": shared_tokens[0],
                    "proof_version": proof["proof_version"],
                }
            )
    unique_overlap = {
        (record["edge_id"], record["shared_endpoint_token"]): record
        for record in overlap_adjacencies
    }
    if (
        len(unique_regular) != 1
        or len(unique_overlap) != 1
        or {
            next(iter(unique_regular.values()))["shared_endpoint_token"],
            next(iter(unique_overlap.values()))["shared_endpoint_token"],
        }
        != bridge_tokens
    ):
        return None
    return {
        "proof_version": "REGULAR_OVERLAP_BRIDGE_HANDOFF_V1",
        "edge_ids": [edge_id],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "adjacent_regular": next(iter(unique_regular.values())),
        "adjacent_overlap": next(iter(unique_overlap.values())),
        "bridge_endpoint_tokens": sorted(bridge_tokens),
    }
    if len(unique_records) != 1:
        return {
            "rejected_stage": "ZERO_LENGTH_REGULAR_CONNECTOR_ADJACENCY",
            "edge_id": edge_id,
            "edge_length": edge_length,
            "maximum_edge_length": maximum_edge_length,
            "connector_tokens": sorted(connector_tokens),
            "adjacent_records": adjacent_records,
        }
    adjacent_record = next(iter(unique_records.values()))
    rail_entries = [
        entry
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == edge_entry["rail_id"]
    ]
    outer_tokens = connector_tokens - {
        adjacent_record["shared_endpoint_token"]
    }
    outer_degrees = sorted(
        sum(token in entry["endpoint_tokens"] for entry in rail_entries)
        for token in outer_tokens
    )
    if len(outer_tokens) != 1 or outer_degrees not in ([1], [2]):
        return {
            "rejected_stage": "ZERO_LENGTH_REGULAR_CONNECTOR_OUTER_TERMINAL",
            "edge_id": edge_id,
            "edge_length": edge_length,
            "maximum_edge_length": maximum_edge_length,
            "connector_tokens": sorted(connector_tokens),
            "adjacent_record": adjacent_record,
            "outer_tokens": sorted(outer_tokens),
            "outer_degrees": outer_degrees,
        }
    return {
        "proof_version": "ZERO_LENGTH_REGULAR_CONNECTOR_HANDOFF_V1",
        "edge_ids": [edge_id],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "edge_length": edge_length,
        "maximum_edge_length": maximum_edge_length,
        "adjacent_regular": adjacent_record,
        "outer_endpoint_token": next(iter(outer_tokens)),
        "outer_endpoint_degree": outer_degrees[0],
    }


# 证明 atom 内 maximal Boundary tail 从唯一 Regular Strip 端点延续，并终止于真实 Rail terminal/junction。
# oriented_chain/start_u/end_u/claim/regular_records/ledger_by_edge_id/source_patch_id: 当前链、投影、唯一 atom、已提交 Strip、完整 ledger 与 owner Patch；返回 component-terminal handoff proof 或 None。
def _regular_component_terminal_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    structural_proof_by_edge_id=None,
):
    if (
        oriented_chain.get("is_cyclic")
        or not oriented_chain.get("edge_ids")
        or len(oriented_chain["edge_ids"]) < 2
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    chain_start, chain_end = sorted((float(start_u), float(end_u)))
    atom_start, atom_end = sorted(map(float, claim["u_interval"]))
    if (
        chain_end - chain_start <= 1.0e-8
        or chain_start < atom_start - 1.0e-10
        or chain_end > atom_end + 1.0e-10
        or any(
            _common_run_interval(
                [chain_start, chain_end],
                envelope["effective_u_interval"],
                bool(claim["strand_cyclic"]),
            )
            is not None
            for envelope in claim["forbidden_envelopes"]
        )
    ):
        return None
    chain_endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            chain_endpoint_counts[endpoint_token] = (
                chain_endpoint_counts.get(endpoint_token, 0) + 1
            )
    chain_terminal_tokens = {
        token for token, count in chain_endpoint_counts.items() if count == 1
    }
    if len(chain_terminal_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    side_interval_key = (
        "left_u_interval" if claim["side"] == "LEFT" else "right_u_interval"
    )
    structural_proof_by_edge_id = structural_proof_by_edge_id or {}
    adjacent_records = []
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        record_start, record_end = sorted(
            map(float, record.get(side_interval_key, record["u_interval"]))
        )
        boundary_candidates = (
            ("AFTER_REGULAR", "END", record_end, chain_start),
            ("BEFORE_REGULAR", "START", record_start, chain_end),
        )
        for (
            tail_direction,
            regular_boundary_side,
            record_boundary_u,
            chain_boundary_u,
        ) in boundary_candidates:
            boundary_edge_id = record[side_edge_key][
                -1 if regular_boundary_side == "END" else 0
            ]
            record_endpoint_tokens = set(
                ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"]
            )
            shared_tokens = sorted(
                chain_terminal_tokens & record_endpoint_tokens
            )
            exact_boundary = (
                abs(record_boundary_u - chain_boundary_u) <= 1.0e-8
                and len(shared_tokens) == 1
            )
            connector_records = []
            ordered_boundary = (
                record_boundary_u <= chain_boundary_u + 1.0e-10
                if tail_direction == "AFTER_REGULAR"
                else chain_boundary_u <= record_boundary_u + 1.0e-10
            )
            if not exact_boundary and ordered_boundary:
                for connector_edge_id, proof in (
                    structural_proof_by_edge_id.items()
                ):
                    if (
                        connector_edge_id in oriented_chain["edge_ids"]
                        or connector_edge_id not in ledger_by_edge_id
                        or proof.get("proof_version")
                        != "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1"
                    ):
                        continue
                    connector_entry = ledger_by_edge_id[connector_edge_id]
                    connector_tokens = set(
                        connector_entry["endpoint_tokens"]
                    )
                    chain_tokens = sorted(
                        connector_tokens & chain_terminal_tokens
                    )
                    regular_tokens = sorted(
                        connector_tokens & record_endpoint_tokens
                    )
                    if (
                        connector_entry["rail_id"]
                        == ledger_by_edge_id[
                            oriented_chain["edge_ids"][0]
                        ]["rail_id"]
                        and len(connector_tokens) == 2
                        and len(chain_tokens) == 1
                        and len(regular_tokens) == 1
                        and chain_tokens[0] != regular_tokens[0]
                    ):
                        connector_records.append(
                            {
                                "edge_id": connector_edge_id,
                                "chain_endpoint_token": chain_tokens[0],
                                "regular_endpoint_token": regular_tokens[0],
                                "proof_version": proof["proof_version"],
                            }
                        )
            if not exact_boundary and len(connector_records) != 1:
                continue
            adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "tail_direction": tail_direction,
                    "regular_boundary_side": regular_boundary_side,
                    "regular_boundary_u": record_boundary_u,
                    "shared_endpoint_token": (
                        shared_tokens[0] if exact_boundary else None
                    ),
                    "zero_length_connector": (
                        None if exact_boundary else connector_records[0]
                    ),
                    "side_u_interval": [record_start, record_end],
                }
            )
    unique_adjacent_records = {
        (
            record["consumer_id"],
            record["tail_direction"],
            record["shared_endpoint_token"],
        ): record
        for record in adjacent_records
    }
    if len(unique_adjacent_records) != 1:
        return None
    adjacent_record = next(iter(unique_adjacent_records.values()))
    adjacent_chain_token = adjacent_record["shared_endpoint_token"] or (
        adjacent_record["zero_length_connector"]["chain_endpoint_token"]
    )
    outer_terminal_tokens = chain_terminal_tokens - {adjacent_chain_token}
    if len(outer_terminal_tokens) != 1:
        return None
    outer_terminal_token = next(iter(outer_terminal_tokens))
    rail_id = ledger_by_edge_id[oriented_chain["edge_ids"][0]]["rail_id"]
    outer_terminal_degree = sum(
        outer_terminal_token in entry["endpoint_tokens"]
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == rail_id
    )
    if outer_terminal_degree not in {1, 2}:
        return None
    adjacent_regular_gap_arc_length = 0.0
    return {
        "proof_version": "REGULAR_COMPONENT_TERMINAL_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "convexity": int(claim["convexity"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "adjacent_regular": adjacent_record,
        "outer_terminal_token": outer_terminal_token,
        "outer_terminal_degree": outer_terminal_degree,
        "adjacent_regular_gap_arc_length": adjacent_regular_gap_arc_length,
        "handoff_boundary_type": (
            "PLAN_TERMINAL"
            if outer_terminal_degree == 1
            else "PLAN_JUNCTION_BRANCH"
        ),
    }


# 证明 cyclic Plan span 末端的 residual chain 从唯一 Regular Strip 延伸到权威 span 边界。
# oriented_chain/start_u/end_u/claim/regular_records/ledger_by_edge_id/source_patch_id: 当前残链、投影、atom、Strip、ledger 与 owner Patch；返回严格 cyclic terminal proof 或 None。
def _cyclic_span_terminal_residual_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claim,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
    radius,
):
    if (
        oriented_chain.get("is_cyclic")
        or not oriented_chain.get("edge_ids")
        or not claim.get("strand_cyclic")
        or int(source_patch_id) not in set(map(int, claim["patch_pair"]))
    ):
        return None
    chain_start, chain_end = sorted((float(start_u), float(end_u)))
    chain_coordinates = [Vector(point) for point in oriented_chain["coordinates"]]
    chain_length = sum(
        (following - current).length
        for current, following in zip(chain_coordinates, chain_coordinates[1:])
    )
    maximum_chain_length = radius * 4.10
    span_intervals = [
        sorted(map(float, interval)) for interval in claim["span_u_intervals"]
    ]
    if not span_intervals:
        return None
    boundary_candidates = []
    for span_start, span_end in span_intervals:
        if (
            span_start - 1.0e-10 <= chain_start
            and chain_end <= span_end + 1.0e-10
            and span_end - chain_end <= 2.0e-3
        ):
            boundary_candidates.append(
                {
                    "tail_direction": "AFTER_REGULAR",
                    "span_boundary_side": "SPAN_END",
                    "span_boundary_u": span_end,
                    "chain_regular_u": chain_start,
                }
            )
        if (
            span_start - 1.0e-10 <= chain_start
            and chain_end <= span_end + 1.0e-10
            and chain_start - span_start <= 2.0e-3
        ):
            boundary_candidates.append(
                {
                    "tail_direction": "BEFORE_REGULAR",
                    "span_boundary_side": "SPAN_START",
                    "span_boundary_u": span_start,
                    "chain_regular_u": chain_end,
                }
            )
    endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            endpoint_counts[token] = endpoint_counts.get(token, 0) + 1
    terminal_tokens = {
        token for token, count in endpoint_counts.items() if count == 1
    }
    if len(terminal_tokens) != 2:
        return None
    side_edge_key = (
        "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    )
    side_interval_key = (
        "left_u_interval" if claim["side"] == "LEFT" else "right_u_interval"
    )
    proven = []
    for boundary in boundary_candidates:
        for record in regular_records:
            if record["correspondence_id"] != claim["correspondence_id"]:
                continue
            record_start, record_end = sorted(
                map(float, record.get(side_interval_key, record["u_interval"]))
            )
            regular_boundary_side = (
                "END"
                if boundary["tail_direction"] == "AFTER_REGULAR"
                else "START"
            )
            record_boundary_u = (
                record_end if regular_boundary_side == "END" else record_start
            )
            boundary_edge_id = record[side_edge_key][
                -1 if regular_boundary_side == "END" else 0
            ]
            shared_tokens = sorted(
                terminal_tokens
                & set(ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"])
            )
            if len(shared_tokens) != 1:
                continue
            projection_gap_u = abs(
                record_boundary_u - boundary["chain_regular_u"]
            )
            proven.append(
                {
                    **boundary,
                    "consumer_id": record["consumer_id"],
                    "regular_boundary_side": regular_boundary_side,
                    "regular_boundary_u": record_boundary_u,
                    "shared_endpoint_token": shared_tokens[0],
                    "projection_gap_u": projection_gap_u,
                    "regular_u_interval": [record_start, record_end],
                }
            )
    unique_proven = {
        (
            record["consumer_id"],
            record["tail_direction"],
            record["shared_endpoint_token"],
        ): record
        for record in proven
    }
    if len(unique_proven) != 1:
        return None
    adjacent = next(iter(unique_proven.values()))
    boundary_gap_arc_length = abs(
        float(adjacent["span_boundary_u"]) - chain_end
        if adjacent["tail_direction"] == "AFTER_REGULAR"
        else chain_start - float(adjacent["span_boundary_u"])
    ) * max(float(claim["strand_length"]), 1.0e-12)
    maximum_boundary_gap_arc_length = radius * 2.0
    projection_gap_arc_length = float(adjacent["projection_gap_u"]) * max(
        float(claim["strand_length"]), 1.0e-12
    )
    maximum_projection_gap_arc_length = radius * 2.0
    if (
        chain_length > maximum_chain_length + 1.0e-10
        or boundary_gap_arc_length > maximum_boundary_gap_arc_length + 1.0e-10
        or projection_gap_arc_length
        > maximum_projection_gap_arc_length + 1.0e-10
    ):
        return {
            "rejected_stage": "CYCLIC_SPAN_BOUNDARY_GAP",
            "chain_length": chain_length,
            "maximum_chain_length": maximum_chain_length,
            "boundary_gap_arc_length": boundary_gap_arc_length,
            "maximum_boundary_gap_arc_length": maximum_boundary_gap_arc_length,
            "projection_gap_arc_length": projection_gap_arc_length,
            "maximum_projection_gap_arc_length": (
                maximum_projection_gap_arc_length
            ),
        }
    outer_tokens = terminal_tokens - {adjacent["shared_endpoint_token"]}
    if len(outer_tokens) != 1:
        return None
    outer_token = next(iter(outer_tokens))
    rail_id = ledger_by_edge_id[oriented_chain["edge_ids"][0]]["rail_id"]
    outer_degree = sum(
        outer_token in entry["endpoint_tokens"]
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == rail_id
    )
    outer_port_tokens = sorted(
        {
            int(port_token)
            for entry in ledger_by_edge_id.values()
            if entry["rail_id"] == rail_id
            and outer_token in entry["endpoint_tokens"]
            for port_token in entry.get("endpoint_port_tokens", ())
        }
    )
    outer_topology_signatures = sorted(
        {
            topology_signature
            for entry in ledger_by_edge_id.values()
            if entry["rail_id"] == rail_id
            for token, topology_signature in zip(
                entry["endpoint_tokens"],
                entry.get("endpoint_topology_signatures", ()),
            )
            if token == outer_token
        }
    )
    if outer_degree == 2 and not outer_topology_signatures:
        return {
            "rejected_stage": "CYCLIC_SPAN_TOPOLOGY_AUDIT",
            "outer_token": outer_token,
            "rail_id": rail_id,
            "endpoint_records": [
                {
                    "edge_id": entry["edge_id"],
                    "endpoint_tokens": list(entry["endpoint_tokens"]),
                    "endpoint_topology_signatures": list(
                        entry.get("endpoint_topology_signatures", ())
                    ),
                }
                for entry in ledger_by_edge_id.values()
                if entry["rail_id"] == rail_id
                and outer_token in entry["endpoint_tokens"]
            ],
        }
    # degree-2 只代表普通连续点；必须再有唯一 Plan port，或同一 token 的
    # 唯一 Boolean topology signature 作为 span seam 的双向结构证据。
    if (
        outer_degree != 2
        or (len(outer_port_tokens), len(outer_topology_signatures))
        not in {(1, 1), (0, 1)}
    ):
        return None
    return {
        "proof_version": "CYCLIC_SPAN_TERMINAL_RESIDUAL_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "correspondence_id": claim["correspondence_id"],
        "atom_id": claim["atom_id"],
        "span_id": int(claim["span_id"]),
        "patch_pair": list(claim["patch_pair"]),
        "side": claim["side"],
        "source_patch_id": int(source_patch_id),
        "adjacent_regular": adjacent,
        "outer_endpoint_token": outer_token,
        "outer_endpoint_degree": outer_degree,
        "outer_plan_port_token": (
            outer_port_tokens[0] if outer_port_tokens else None
        ),
        "outer_topology_signature": outer_topology_signatures[0],
        "span_boundary": {
            "side": adjacent["span_boundary_side"],
            "u": adjacent["span_boundary_u"],
        },
        "chain_length": chain_length,
        "maximum_chain_length": maximum_chain_length,
        "boundary_gap_arc_length": boundary_gap_arc_length,
        "maximum_boundary_gap_arc_length": maximum_boundary_gap_arc_length,
        "projection_gap_arc_length": projection_gap_arc_length,
        "maximum_projection_gap_arc_length": maximum_projection_gap_arc_length,
    }


# 证明一条 maximal Boundary chain 完全落在当前 Rail 所有 correspondence spans 之外。
# oriented_chain/start_u/end_u/claims: 当前有序链、FeatureStrand 投影与该 Rail 的全部 atom claims；返回 span-gap handoff proof 或 None。
def _outside_correspondence_span_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claims,
    ledger_by_edge_id,
):
    if oriented_chain.get("is_cyclic") or not oriented_chain.get("edge_ids") or not claims:
        return None
    chain_interval = sorted((float(start_u), float(end_u)))
    endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            endpoint_counts[endpoint_token] = endpoint_counts.get(endpoint_token, 0) + 1
    chain_terminal_tokens = {
        token for token, count in endpoint_counts.items() if count == 1
    }
    all_rail_entries = [
        entry
        for entry in ledger_by_edge_id.values()
        if entry["rail_id"] == ledger_by_edge_id[oriented_chain["edge_ids"][0]]["rail_id"]
    ]
    terminal_degrees = sorted(
        sum(token in entry["endpoint_tokens"] for entry in all_rail_entries)
        for token in chain_terminal_tokens
    )
    if len(chain_terminal_tokens) != 2 or terminal_degrees not in ([1, 1], [1, 2]):
        return None
    grouped_claims = {}
    for claim in claims:
        key = (
            claim["correspondence_id"],
            claim["side"],
            bool(claim["strand_cyclic"]),
        )
        grouped_claims.setdefault(key, []).append(claim)
    gap_witnesses = []
    for (correspondence_id, side, strand_cyclic), current_claims in sorted(
        grouped_claims.items()
    ):
        span_intervals = sorted(
            {
                tuple(round(float(value), 10) for value in interval)
                for claim in current_claims
                for interval in claim["span_u_intervals"]
            }
        )
        if not span_intervals or any(
            _common_run_interval(
                chain_interval,
                span_interval,
                strand_cyclic,
            )
            is not None
            for span_interval in span_intervals
        ):
            return None
        expanded_spans = sorted(
            {
                (
                    float(span_interval[0]) + shift,
                    float(span_interval[1]) + shift,
                )
                for span_interval in span_intervals
                for shift in (range(-2, 3) if strand_cyclic else (0,))
            }
        )
        lower_candidates = [
            interval for interval in expanded_spans
            if interval[1] <= chain_interval[0] + 1.0e-10
        ]
        upper_candidates = [
            interval for interval in expanded_spans
            if interval[0] >= chain_interval[1] - 1.0e-10
        ]
        if not lower_candidates or not upper_candidates:
            return None
        lower_span = max(lower_candidates, key=lambda interval: interval[1])
        upper_span = min(upper_candidates, key=lambda interval: interval[0])
        if (
            lower_span[1] > chain_interval[0] + 1.0e-10
            or upper_span[0] < chain_interval[1] - 1.0e-10
            or upper_span[0] - lower_span[1] <= 1.0e-8
        ):
            return None
        gap_witnesses.append(
            {
                "correspondence_id": correspondence_id,
                "side": side,
                "span_u_intervals": [list(interval) for interval in span_intervals],
                "enclosing_gap_u_interval": [lower_span[1], upper_span[0]],
                "lower_span_u_interval": list(lower_span),
                "upper_span_u_interval": list(upper_span),
            }
        )
    if not gap_witnesses:
        return None
    return {
        "proof_version": "OUTSIDE_CORRESPONDENCE_SPAN_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": chain_interval,
        "gap_witnesses": gap_witnesses,
        "atom_claim_ids": sorted(
            {
                claim["atom_id"]
                for claim in claims
            }
        ),
        "terminal_endpoint_tokens": sorted(chain_terminal_tokens),
        "terminal_endpoint_degrees": terminal_degrees,
        "handoff_boundary_type": (
            "PLAN_TERMINAL"
            if terminal_degrees == [1, 1]
            else "PLAN_JUNCTION_BRANCH"
        ),
    }


# 证明同一 owner Rail 上两个相邻 correspondence 在共享 Plan span 边界形成唯一 junction handoff。
# oriented_chain/start_u/end_u/claims/regular_records/ledger_by_edge_id/source_patch_id: 当前 maximal 链、投影、atom claims、已提交 Strip、ledger 与 owner Patch；返回 transition proof 或 None。
def _correspondence_transition_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claims,
    regular_records,
    ledger_by_edge_id,
    source_patch_id,
):
    if oriented_chain.get("is_cyclic") or not oriented_chain.get("edge_ids"):
        return None
    unique_claims = {
        (claim["correspondence_id"], claim["atom_id"], claim["side"]): claim
        for claim in claims
    }
    if len(unique_claims) != 2:
        return None
    current_claims = list(unique_claims.values())
    if (
        len({claim["correspondence_id"] for claim in current_claims}) != 2
        or any(
            int(source_patch_id) not in set(map(int, claim["patch_pair"]))
            for claim in current_claims
        )
        or len(
            set(map(int, current_claims[0]["patch_pair"]))
            & set(map(int, current_claims[1]["patch_pair"]))
        )
        != 1
        or (
            set(map(int, current_claims[0]["patch_pair"]))
            & set(map(int, current_claims[1]["patch_pair"]))
        )
        != {int(source_patch_id)}
    ):
        return None
    chain_start, chain_end = sorted((float(start_u), float(end_u)))
    transition_candidates = []
    for lower_claim in current_claims:
        for upper_claim in current_claims:
            if lower_claim is upper_claim:
                continue
            cyclic = bool(lower_claim["strand_cyclic"])
            if cyclic != bool(upper_claim["strand_cyclic"]):
                continue
            for lower_shift in range(-2, 3) if cyclic else (0,):
                lower_span_intervals = (
                    lower_claim["span_u_intervals"]
                    or (lower_claim["u_interval"],)
                )
                for upper_shift in range(-2, 3) if cyclic else (0,):
                    upper_span_intervals = (
                        upper_claim["span_u_intervals"]
                        or (upper_claim["u_interval"],)
                    )
                    for lower_span in lower_span_intervals:
                        lower_start, lower_end = (
                            float(lower_span[0]) + lower_shift,
                            float(lower_span[1]) + lower_shift,
                        )
                        for upper_span in upper_span_intervals:
                            upper_start, upper_end = (
                                float(upper_span[0]) + upper_shift,
                                float(upper_span[1]) + upper_shift,
                            )
                            if (
                                abs(lower_end - upper_start) > 1.0e-8
                                or chain_start < lower_start - 1.0e-10
                                or chain_start > lower_end + 1.0e-10
                                or chain_end < upper_start - 1.0e-10
                                or chain_end > upper_end + 1.0e-10
                                or chain_start >= lower_end - 1.0e-8
                                or chain_end <= upper_start + 1.0e-8
                            ):
                                continue
                            transition_candidates.append(
                                {
                                    "lower_claim": lower_claim,
                                    "upper_claim": upper_claim,
                                    "lower_u_interval": [lower_start, lower_end],
                                    "upper_u_interval": [upper_start, upper_end],
                            "transition_u": (lower_end + upper_start) * 0.5,
                            "chain_start": chain_start,
                            "chain_end": chain_end,
                        }
                    )
    unique_transitions = {
        _stable_fingerprint(
            {
                "lower": candidate["lower_claim"]["atom_id"],
                "upper": candidate["upper_claim"]["atom_id"],
                "transition_u": round(candidate["transition_u"], 10),
            }
        ): candidate
        for candidate in transition_candidates
    }
    if len(unique_transitions) != 1:
        return {
            "rejected_stage": "CORRESPONDENCE_TRANSITION",
            "candidate_count": len(unique_transitions),
            "candidates": list(unique_transitions.values()),
            "claims": current_claims,
        }
    transition = next(iter(unique_transitions.values()))
    chain_endpoint_counts = {}
    for edge_id in oriented_chain["edge_ids"]:
        for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]:
            chain_endpoint_counts[endpoint_token] = (
                chain_endpoint_counts.get(endpoint_token, 0) + 1
            )
    chain_terminal_tokens = {
        token for token, count in chain_endpoint_counts.items() if count == 1
    }
    adjacent_records = []
    for role, claim, boundary_u, required_record_boundary in (
        (
            "LOWER",
            transition["lower_claim"],
            chain_start,
            "END",
        ),
        (
            "UPPER",
            transition["upper_claim"],
            chain_end,
            "START",
        ),
    ):
        side_edge_key = (
            "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
        )
        candidates = []
        for record in regular_records:
            if record["correspondence_id"] != claim["correspondence_id"]:
                continue
            record_start, record_end = sorted(map(float, record["u_interval"]))
            record_boundary_u = (
                record_end if required_record_boundary == "END" else record_start
            )
            boundary_edge_id = record[side_edge_key][
                -1 if required_record_boundary == "END" else 0
            ]
            record_endpoint_tokens = set(
                ledger_by_edge_id[boundary_edge_id]["endpoint_tokens"]
            )
            shared_tokens = sorted(chain_terminal_tokens & record_endpoint_tokens)
            if len(shared_tokens) == 1:
                candidates.append(
                    {
                        "role": role,
                        "consumer_id": record["consumer_id"],
                        "correspondence_id": record["correspondence_id"],
                        "record_boundary_side": required_record_boundary,
                        "shared_endpoint_token": shared_tokens[0],
                        "u_interval": list(record["u_interval"]),
                        "projected_boundary_gap_u": abs(
                            record_boundary_u - boundary_u
                        ),
                        "adjacency_type": "SHARED_BOUNDARY_ENDPOINT",
                    }
                )
        if len(candidates) != 1:
            return {
                "rejected_stage": "CORRESPONDENCE_TRANSITION_ADJACENCY",
                "role": role,
                "claim": claim,
                "required_record_boundary": required_record_boundary,
                "boundary_u": boundary_u,
                "chain_terminal_tokens": sorted(chain_terminal_tokens),
                "candidates": candidates,
            }
        adjacent_records.append(candidates[0])
    if len({record["shared_endpoint_token"] for record in adjacent_records}) != 2:
        return None
    return {
        "proof_version": "CORRESPONDENCE_TRANSITION_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "source_patch_id": int(source_patch_id),
        "transition_sides": {
            "lower": transition["lower_claim"]["side"],
            "upper": transition["upper_claim"]["side"],
        },
        "transition_u": transition["transition_u"],
        "lower_atom": {
            key: transition["lower_claim"][key]
            for key in (
                "correspondence_id",
                "atom_id",
                "span_id",
                "patch_pair",
                "convexity",
            )
        },
        "upper_atom": {
            key: transition["upper_claim"][key]
            for key in (
                "correspondence_id",
                "atom_id",
                "span_id",
                "patch_pair",
                "convexity",
            )
        },
        "adjacent_regular_records": adjacent_records,
    }


# 用已验证的真实 cyclic Rail pair 构建独立 Regular Strip topology，不修改 staging/source Mesh。
# preview_plan/staging_rail_chains/boundary_ledger/overlap_pairs/radius: Plan、rails、完整 ledger、overlap graph 与 radius；返回 records、分类 ledger、ports、diagnostics。
def _build_cyclic_regular_strip_partition(
    preview_plan,
    groups,
    staging_rail_chains,
    boundary_ledger,
    overlap_pairs,
    overlap_setback_intervals,
    radius,
):
    del overlap_pairs
    strands_by_id = {
        strand.strand_id: strand for strand in preview_plan.feature_strands
    }
    pipe_id_by_strand_id = {
        group["strand"].strand_id: int(group["pipe_id"])
        for group in groups
    }
    correspondence_spans_by_strand_id = {
        group["strand"].strand_id: _group_correspondence_span_records(group)
        for group in groups
    }
    ledger_by_edge_id = {entry["edge_id"]: dict(entry) for entry in boundary_ledger}
    # 冻结每条真实 Boundary Edge 在权威 FeatureStrand 上的定向 u interval；
    # 后续跨 atom 的消费只能使用这份 direct chain projection 证据。
    for chains in staging_rail_chains.values():
        for chain in chains:
            strand = strands_by_id.get(chain.get("strand_id"))
            if strand is None:
                continue
            oriented_chain, parameters = _chain_strand_parameters(chain, strand)
            projected_parameters = list(parameters)
            if oriented_chain.get("is_cyclic"):
                closure_parameter = float(projected_parameters[0])
                if strand.cyclic:
                    closure_parameter = min(
                        (
                            closure_parameter + offset
                            for offset in range(-2, 3)
                        ),
                        key=lambda value: abs(
                            value - projected_parameters[-1]
                        ),
                    )
                    while closure_parameter + 1.0e-10 < projected_parameters[-1]:
                        closure_parameter += 1.0
                projected_parameters.append(closure_parameter)
            if len(projected_parameters) != len(oriented_chain["edge_ids"]) + 1:
                continue
            for edge_id, start_u, end_u in zip(
                oriented_chain["edge_ids"],
                projected_parameters,
                projected_parameters[1:],
            ):
                current_interval = sorted((float(start_u), float(end_u)))
                existing_interval = ledger_by_edge_id[edge_id].get(
                    "strand_u_interval"
                )
                if existing_interval is not None and any(
                    abs(left - right) > 1.0e-10
                    for left, right in zip(existing_interval, current_interval)
                ):
                    raise BatchedChamferError(
                        "BOUNDARY_EDGE_STRAND_INTERVAL_CONFLICT",
                        "同一 Boundary Edge 观察到不一致的 FeatureStrand u interval",
                        {
                            "edge_id": edge_id,
                            "existing_interval": existing_interval,
                            "current_interval": current_interval,
                        },
                    )
                ledger_by_edge_id[edge_id]["strand_u_interval"] = current_interval
    regular_records = []
    setback_ports = []
    strip_attempts = []
    overlap_proof_by_edge_id = {}
    micro_loop_proof_by_edge_id = {}
    regular_atom_claims_by_rail_id = {}
    correspondence_strand_ids = {
        correspondence.owner_strand_id
        for correspondence in preview_plan.strip_correspondences
    }
    for correspondence in preview_plan.strip_correspondences:
        left_chains = staging_rail_chains.get(correspondence.left_rail_id, ())
        right_chains = staging_rail_chains.get(correspondence.right_rail_id, ())
        left_chains, left_micro_component_proofs = (
            _defer_attached_cyclic_micro_components(left_chains, radius)
        )
        right_chains, right_micro_component_proofs = (
            _defer_attached_cyclic_micro_components(right_chains, radius)
        )
        if (
            len(left_chains) == 1
            and len(right_chains) == 1
            and left_chains[0].get("is_cyclic")
            and right_chains[0].get("is_cyclic")
        ):
            right_chains = (
                _align_cyclic_stable_chain(left_chains[0], right_chains[0]),
            )
        for side, proofs in (
            ("LEFT", left_micro_component_proofs),
            ("RIGHT", right_micro_component_proofs),
        ):
            for proof in proofs:
                current = {
                    **proof,
                    "side": side,
                    "rail_id": (
                        correspondence.left_rail_id
                        if side == "LEFT"
                        else correspondence.right_rail_id
                    ),
                }
                for edge_id in proof["edge_ids"]:
                    existing = micro_loop_proof_by_edge_id.get(edge_id)
                    if existing is not None and existing != current:
                        raise BatchedChamferError(
                            "MICRO_LOOP_JUNCTION_PROOF_CONFLICT",
                            "同一 Boundary Edge 观察到不一致的 attached cyclic micro proof",
                            {"existing": existing, "current": current},
                        )
                    micro_loop_proof_by_edge_id[edge_id] = current
        strand = strands_by_id[correspondence.owner_strand_id]
        pipe_id = pipe_id_by_strand_id[correspondence.owner_strand_id]
        span_records = correspondence_spans_by_strand_id[
            correspondence.owner_strand_id
        ].get(tuple(correspondence.owner_surface_pair), ())
        forbidden_intervals = overlap_setback_intervals.get(pipe_id, ())
        effective_forbidden_intervals, forbidden_envelopes = (
            _paired_rail_forbidden_edge_envelopes(
                (*left_chains, *right_chains),
                strand,
                forbidden_intervals,
            )
        )
        plan_atoms = _regular_plan_atoms(
            span_records,
            effective_forbidden_intervals,
            strand.cyclic,
        )
        for side, rail_id in (
            ("LEFT", correspondence.left_rail_id),
            ("RIGHT", correspondence.right_rail_id),
        ):
            regular_atom_claims_by_rail_id.setdefault(rail_id, []).extend(
                {
                    "correspondence_id": correspondence.correspondence_id,
                    "side": side,
                    "atom_id": atom["atom_id"],
                    "span_id": int(atom["span_id"]),
                    "patch_pair": list(atom["patch_pair"]),
                    "convexity": int(atom["convexity"]),
                    "u_interval": list(atom["u_interval"]),
                    "span_u_intervals": [
                        list(record["u_interval"])
                        for record in span_records
                        if int(record["span_id"]) == int(atom["span_id"])
                    ],
                    "forbidden_envelopes": [
                        {
                            **envelope,
                            "source_u_interval": list(
                                envelope["source_u_interval"]
                            ),
                            "effective_u_interval": list(
                                envelope["effective_u_interval"]
                            ),
                            "direct_witness_edge_ids": list(
                                envelope["direct_witness_edge_ids"]
                            ),
                        }
                        for envelope in forbidden_envelopes
                    ],
                    "strand_cyclic": bool(strand.cyclic),
                    "strand_length": _feature_strand_arc_length(strand),
                }
                for atom in plan_atoms
            )
        left_runs_by_atom = {atom["atom_id"]: [] for atom in plan_atoms}
        right_runs_by_atom = {atom["atom_id"]: [] for atom in plan_atoms}
        for chains, target_by_atom in (
            (left_chains, left_runs_by_atom),
            (right_chains, right_runs_by_atom),
        ):
            for chain in chains:
                split = _split_chain_by_forbidden_intervals(
                    chain,
                    strand,
                    effective_forbidden_intervals,
                )
                for setback_run in split["setback"]:
                    for edge_id, start_u, end_u in zip(
                        setback_run["edge_ids"],
                        setback_run["u_values"],
                        setback_run["u_values"][1:],
                    ):
                        edge_interval = sorted((float(start_u), float(end_u)))
                        matching_intervals = [
                            {
                                "interval_index": interval_index,
                                "source_u_interval": [
                                    float(source_start),
                                    float(source_end),
                                ],
                                "effective_u_interval": [
                                    float(forbidden_start),
                                    float(forbidden_end),
                                ],
                                "direct_witness_edge_ids": list(
                                    envelope["direct_witness_edge_ids"]
                                ),
                            }
                            for envelope in forbidden_envelopes
                            for interval_index, interval, effective_interval in (
                                (
                                    envelope["interval_index"],
                                    envelope["source_u_interval"],
                                    envelope["effective_u_interval"],
                                ),
                            )
                            for source_start, source_end in (
                                sorted(map(float, interval)),
                            )
                            for forbidden_start, forbidden_end in (
                                sorted(map(float, effective_interval)),
                            )
                            if any(
                                (
                                    forbidden_start + offset - 1.0e-10
                                    <= edge_interval[0]
                                    <= forbidden_end + offset + 1.0e-10
                                )
                                if edge_interval[1] - edge_interval[0] <= 1.0e-10
                                else (
                                    max(
                                        edge_interval[0],
                                        forbidden_start + offset,
                                    )
                                    < min(
                                        edge_interval[1],
                                        forbidden_end + offset,
                                    )
                                    - 1.0e-10
                                )
                                for offset in (
                                    range(-2, 3) if strand.cyclic else (0,)
                                )
                            )
                        ]
                        if not matching_intervals:
                            raise BatchedChamferError(
                                "OVERLAP_EDGE_SETBACK_PROOF_MISSING",
                                "Setback partition Edge 无法反查 overlap forbidden interval",
                                {
                                    "edge_id": edge_id,
                                    "edge_u_interval": edge_interval,
                                    "forbidden_intervals": list(forbidden_intervals),
                                },
                            )
                        proof = {
                            "proof_version": "PAIRED_RAIL_OVERLAP_SETBACK_V1",
                            "pipe_id": pipe_id,
                            "strand_id": correspondence.owner_strand_id,
                            "rail_id": ledger_by_edge_id[edge_id]["rail_id"],
                            "edge_id": edge_id,
                            "edge_u_interval": edge_interval,
                            "forbidden_intervals": matching_intervals,
                        }
                        existing = overlap_proof_by_edge_id.get(edge_id)
                        if existing is not None:
                            existing_core = {
                                key: value
                                for key, value in existing.items()
                                if key != "forbidden_intervals"
                            }
                            current_core = {
                                key: value
                                for key, value in proof.items()
                                if key != "forbidden_intervals"
                            }
                            if existing_core != current_core:
                                raise BatchedChamferError(
                                    "OVERLAP_EDGE_SETBACK_PROOF_CONFLICT",
                                    "同一 Boundary Edge 观察到不一致的 overlap setback proof",
                                    {"existing": existing, "current": proof},
                                )
                            merged_intervals = {}
                            for evidence in (
                                *existing["forbidden_intervals"],
                                *proof["forbidden_intervals"],
                            ):
                                key = (
                                    int(evidence["interval_index"]),
                                    tuple(evidence["source_u_interval"]),
                                    tuple(evidence["effective_u_interval"]),
                                )
                                merged = merged_intervals.setdefault(
                                    key,
                                    {
                                        **evidence,
                                        "direct_witness_edge_ids": [],
                                    },
                                )
                                merged["direct_witness_edge_ids"] = sorted(
                                    {
                                        *merged["direct_witness_edge_ids"],
                                        *evidence["direct_witness_edge_ids"],
                                    }
                                )
                            proof["forbidden_intervals"] = [
                                merged_intervals[key]
                                for key in sorted(merged_intervals)
                            ]
                        overlap_proof_by_edge_id[edge_id] = proof
                for run in split["regular"]:
                    for atom in plan_atoms:
                        trimmed = _trim_run_to_plan_atom(
                            run,
                            atom,
                            strand.cyclic,
                        )
                        if trimmed is not None:
                            target_by_atom[atom["atom_id"]].append(trimmed)
        for target_by_atom in (left_runs_by_atom, right_runs_by_atom):
            for atom_id, runs in target_by_atom.items():
                target_by_atom[atom_id] = list(
                    _stitch_contiguous_regular_runs(
                        runs,
                        radius,
                        _feature_strand_arc_length(strand),
                        strand.cyclic,
                    )
                )
        left_runs = [
            run for runs in left_runs_by_atom.values() for run in runs
        ]
        right_runs = [
            run for runs in right_runs_by_atom.values() for run in runs
        ]
        matched_components = []
        unresolved_components = []
        short_setback_proofs = []
        atom_by_id = {atom["atom_id"]: atom for atom in plan_atoms}
        for atom in plan_atoms:
            (
                left_runs_by_atom[atom["atom_id"]],
                right_runs_by_atom[atom["atom_id"]],
            ) = _lift_full_cyclic_atom_runs(
                left_runs_by_atom[atom["atom_id"]],
                right_runs_by_atom[atom["atom_id"]],
                atom,
            )
            aligned_left_runs, aligned_right_runs = (
                _align_full_cyclic_atom_run_phase(
                left_runs_by_atom[atom["atom_id"]],
                right_runs_by_atom[atom["atom_id"]],
                atom,
                )
            )
            left_runs_by_atom[atom["atom_id"]] = aligned_left_runs
            right_runs_by_atom[atom["atom_id"]] = aligned_right_runs
            atom_left, atom_right, component_intervals = (
                _partition_atom_runs_by_common_components(
                    left_runs_by_atom[atom["atom_id"]],
                    right_runs_by_atom[atom["atom_id"]],
                    atom,
                )
            )
            if not component_intervals:
                residual_runs = (
                    *left_runs_by_atom[atom["atom_id"]],
                    *right_runs_by_atom[atom["atom_id"]],
                )
                component_intervals = tuple(
                    sorted(
                        {
                            tuple(
                                round(float(value), 10)
                                for value in sorted(run["u_interval"])
                            )
                            for run in residual_runs
                        }
                    )
                )
                atom_left = tuple(
                    {
                        **trimmed,
                        "atom_id": atom["atom_id"],
                        "component_id": f"{atom['atom_id']}:{component_index}",
                        "component_u_interval": list(interval),
                    }
                    for component_index, interval in enumerate(component_intervals)
                    for run in left_runs_by_atom[atom["atom_id"]]
                    for trimmed in (_trim_open_run_to_interval(run, interval),)
                    if trimmed is not None
                )
                atom_right = tuple(
                    {
                        **trimmed,
                        "atom_id": atom["atom_id"],
                        "component_id": f"{atom['atom_id']}:{component_index}",
                        "component_u_interval": list(interval),
                    }
                    for component_index, interval in enumerate(component_intervals)
                    for run in right_runs_by_atom[atom["atom_id"]]
                    for trimmed in (_trim_open_run_to_interval(run, interval),)
                    if trimmed is not None
                )
            for component_index, component_interval in enumerate(
                component_intervals
            ):
                component_id = f"{atom['atom_id']}:{component_index}"
                component_left = [
                    run for run in atom_left if run["component_id"] == component_id
                ]
                component_right = [
                    run for run in atom_right if run["component_id"] == component_id
                ]
                atom_matches, atom_unresolved = _match_regular_run_components(
                    correspondence,
                    component_left,
                    component_right,
                    strand,
                    radius,
                )
                matched_components.extend(
                    {
                        **match,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": list(component_interval),
                    }
                    for match in atom_matches
                )
                for record in (*atom_matches, *atom_unresolved):
                    for proof in record.get("micro_loop_junction_proofs", ()):
                        for edge_id in proof["edge_ids"]:
                            existing = micro_loop_proof_by_edge_id.get(edge_id)
                            current = {
                                **proof,
                                "correspondence_id": correspondence.correspondence_id,
                                "atom_id": atom["atom_id"],
                                "component_id": component_id,
                            }
                            if existing is not None and existing != current:
                                if (
                                    existing["proof_version"]
                                    != "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1"
                                    or current["proof_version"]
                                    != "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1"
                                ):
                                    raise BatchedChamferError(
                                        "MICRO_LOOP_JUNCTION_PROOF_CONFLICT",
                                        "同一 Boundary Edge 观察到不一致的 micro-loop junction proof",
                                        {"existing": existing, "current": current},
                                    )
                                current = {
                                    **existing,
                                    "edge_ids": sorted(
                                        {
                                            *existing["edge_ids"],
                                            *current["edge_ids"],
                                        }
                                    ),
                                    "atom_ids": sorted(
                                        {
                                            existing.get("atom_id"),
                                            current.get("atom_id"),
                                            *existing.get("atom_ids", ()),
                                        }
                                    ),
                                    "component_ids": sorted(
                                        {
                                            existing.get("component_id"),
                                            current.get("component_id"),
                                            *existing.get("component_ids", ()),
                                        }
                                    ),
                                }
                            micro_loop_proof_by_edge_id[edge_id] = current
                unresolved_components.extend(
                    {
                        **unresolved,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": list(component_interval),
                    }
                    for unresolved in atom_unresolved
                )
        matched_components = tuple(matched_components)
        consumed_component_edges = {
            edge_id
            for match in matched_components
            for side in ("left", "right")
            for edge_id in match[side]["edge_ids"]
        }
        inferred_residue_matches = []
        for match in matched_components:
            for residue_match in match.get("endpoint_residue_matches", ()):
                residue_edge_ids = {
                    edge_id
                    for side in ("left", "right")
                    for edge_id in residue_match[side]["edge_ids"]
                }
                if residue_edge_ids & consumed_component_edges:
                    continue
                inferred_residue_matches.append(
                    {
                        **residue_match,
                        "left_run_id": _stable_fingerprint(
                            residue_match["left"]["edge_ids"]
                        ),
                        "right_run_id": _stable_fingerprint(
                            residue_match["right"]["edge_ids"]
                        ),
                        "micro_loop_junction_proofs": list(
                            match.get("micro_loop_junction_proofs", ())
                        ),
                        "endpoint_residue_of": [
                            match["left_run_id"],
                            match["right_run_id"],
                        ],
                        "atom_id": match["atom_id"],
                        "component_id": match["component_id"],
                        "component_u_interval": list(
                            match["component_u_interval"]
                        ),
                    }
                )
                consumed_component_edges |= residue_edge_ids
        matched_components = (
            *matched_components,
            *inferred_residue_matches,
        )
        unique_matched_components = {}
        for match in matched_components:
            match_key = (
                tuple(match["left"]["edge_ids"]),
                tuple(match["right"]["edge_ids"]),
            )
            existing = unique_matched_components.get(match_key)
            if existing is not None and (
                existing["atom_id"] != match["atom_id"]
                or existing["component_id"] != match["component_id"]
            ):
                same_atom = existing["atom_id"] == match["atom_id"]
                same_effective_core = same_atom and all(
                    max(
                        abs(existing_value - current_value)
                        for existing_value, current_value in zip(
                            sorted(map(float, existing[side]["u_interval"])),
                            sorted(map(float, match[side]["u_interval"])),
                        )
                    )
                    <= 1.0e-8
                    for side in ("left", "right")
                )
                if same_effective_core:
                    continue
                raise BatchedChamferError(
                    "REGULAR_MATCH_PROVENANCE_CONFLICT",
                    "同一 Boundary provenance 被多个 Plan component 匹配",
                    {"existing": existing, "current": match},
                )
            unique_matched_components[match_key] = match
        matched_components = tuple(unique_matched_components.values())
        unresolved_by_component = {}
        for unresolved in unresolved_components:
            component_key = (
                unresolved["correspondence_id"],
                unresolved["atom_id"],
                unresolved["component_id"],
            )
            unresolved_by_component.setdefault(component_key, []).append(unresolved)
        retained_unresolved = []
        for component_key, component_records in sorted(unresolved_by_component.items()):
            atom = atom_by_id[component_key[1]]
            proof_candidates = [
                proof
                for unresolved in component_records
                for proof in (
                    _short_component_setback_proof(
                        unresolved,
                        atom,
                        strand,
                        effective_forbidden_intervals,
                        radius,
                        plan_atoms,
                        forbidden_envelopes,
                    ),
                    _branch_micro_fragment_setback_proof(
                        unresolved,
                        atom,
                        radius,
                    ),
                    _terminal_micro_fragment_setback_proof(
                        unresolved,
                        atom,
                        radius,
                    ),
                    _terminal_short_tail_setback_proof(
                        unresolved,
                        atom,
                        radius,
                    ),
                    _junction_micro_component_setback_proof(
                        unresolved,
                        atom,
                        radius,
                    ),
                    _radius_collapsed_single_edge_setback_proof(
                        unresolved,
                        atom,
                        strand,
                        forbidden_intervals,
                        radius,
                    ),
                )
                if proof is not None
            ]
            unique_proofs = {
                _stable_fingerprint(proof): proof for proof in proof_candidates
            }
            if len(component_records) == 1 and len(unique_proofs) == 1:
                short_setback_proofs.append(next(iter(unique_proofs.values())))
            else:
                retained_unresolved.extend(component_records)
        unresolved_components = tuple(retained_unresolved)
        matched_count = 0
        for match in matched_components:
            record, failure = _build_regular_record_from_match(
                correspondence,
                match,
                pipe_id,
                radius,
                ledger_by_edge_id,
                atom_by_id[match["atom_id"]],
            )
            if record is None:
                unresolved_components = (
                    *unresolved_components,
                    {
                        "correspondence_id": correspondence.correspondence_id,
                        **failure,
                    },
                )
                continue
            regular_records.append(record)
            matched_count += 1
        committed_short_setback_proofs = []
        for proof in short_setback_proofs:
            proof_edge_ids = set(
                proof.get("edge_ids", (proof.get("edge_id"),))
            ) - {None}
            if any(
                ledger_by_edge_id[edge_id]["classification"] != "UNCLASSIFIED"
                for edge_id in proof_edge_ids
            ):
                continue
            setback_ports.append(
                _commit_short_component_setback(
                    proof,
                    correspondence,
                    pipe_id,
                    ledger_by_edge_id,
                )
            )
            committed_short_setback_proofs.append(proof)
        empty_correspondence_proof = None
        if (
            not matched_count
            and not committed_short_setback_proofs
            and not unresolved_components
            and not left_runs
            and not right_runs
            and left_chains
            and right_chains
        ):
            chain_edge_ids = {
                edge_id
                for chain in (*left_chains, *right_chains)
                for edge_id in chain["edge_ids"]
            }
            overlap_edge_ids = {
                edge_id
                for edge_id in chain_edge_ids
                if edge_id in overlap_proof_by_edge_id
            }
            if (
                not plan_atoms
                and chain_edge_ids
                and overlap_edge_ids == chain_edge_ids
            ):
                empty_correspondence_proof = {
                    "proof_version": "OVERLAP_ONLY_CORRESPONDENCE_V1",
                    "correspondence_id": correspondence.correspondence_id,
                    "pipe_id": int(pipe_id),
                    "left_rail_id": correspondence.left_rail_id,
                    "right_rail_id": correspondence.right_rail_id,
                    "plan_atom_count": len(plan_atoms),
                    "chain_edge_count": len(chain_edge_ids),
                    "overlap_edge_ids": sorted(overlap_edge_ids),
                    "effective_forbidden_intervals": [
                        list(interval)
                        for interval in effective_forbidden_intervals
                    ],
                }
        correspondence_proven = bool(
            matched_count
            or committed_short_setback_proofs
            or empty_correspondence_proof
        )
        if (
            not correspondence_proven
            and not unresolved_components
            and not left_runs
            and not right_runs
            and left_chains
            and right_chains
            and all(
                edge_id in overlap_proof_by_edge_id
                or edge_id in micro_loop_proof_by_edge_id
                for chain in (*left_chains, *right_chains)
                for edge_id in chain["edge_ids"]
            )
        ):
            empty_correspondence_proof = {
                "proof_version": "SETBACK_ONLY_CORRESPONDENCE_V1",
                "correspondence_id": correspondence.correspondence_id,
                "pipe_id": int(pipe_id),
                "plan_atom_count": len(plan_atoms),
                "left_chain_count": len(left_chains),
                "right_chain_count": len(right_chains),
                "proven_edge_ids": sorted(
                    {
                        edge_id
                        for chain in (*left_chains, *right_chains)
                        for edge_id in chain["edge_ids"]
                    }
                ),
            }
            correspondence_proven = True
        if (
            not correspondence_proven
            and not unresolved_components
            and len(left_runs) + len(right_runs) == 1
        ):
            residual_run = (*left_runs, *right_runs)[0]
            residual_edge_ids = list(residual_run["edge_ids"])
            residual_atom = atom_by_id.get(residual_run.get("atom_id"))
            if residual_atom is None:
                residual_candidates = []
                for atom in plan_atoms:
                    common = _common_run_interval(
                        residual_run["u_interval"],
                        atom["u_interval"],
                        strand.cyclic,
                    )
                    if common is None:
                        continue
                    common_interval, _ = common
                    residual_start, residual_end = sorted(
                        map(float, residual_run["u_interval"])
                    )
                    atom_start, atom_end = sorted(
                        map(float, atom["u_interval"])
                    )
                    residual_coverage = residual_end - residual_start
                    common_coverage = (
                        common_interval[1] - common_interval[0]
                    )
                    if (
                        residual_coverage <= 1.0e-10
                        or common_coverage
                        >= residual_coverage * 0.99 - 1.0e-10
                        or (
                            abs(residual_start - atom_start) <= 1.0e-8
                            and abs(residual_end - atom_end) <= 1.0e-8
                        )
                    ):
                        residual_candidates.append(atom)
                if len(residual_candidates) == 1:
                    residual_atom = residual_candidates[0]
            if residual_atom is None:
                exact_residual_candidates = [
                    atom
                    for atom in plan_atoms
                    if max(
                        abs(
                            float(residual_boundary)
                            - float(atom_boundary)
                        )
                        for residual_boundary, atom_boundary in zip(
                            sorted(map(float, residual_run["u_interval"])),
                            sorted(map(float, atom["u_interval"])),
                        )
                    )
                    <= 1.0e-8
                ]
                if len(exact_residual_candidates) == 1:
                    residual_atom = exact_residual_candidates[0]
            if len(residual_edge_ids) == 1 and residual_atom is not None:
                residual_side = (
                    "LEFT" if residual_run in left_runs else "RIGHT"
                )
                residual_interval = list(residual_run["u_interval"])
                residual_component_id = (
                    f"{residual_atom['atom_id']}:residual"
                )
                residual_unresolved = {
                    "reason": "NO_PERFECT_MATCHING",
                    "solution_count_capped": 0,
                    "correspondence_id": correspondence.correspondence_id,
                    "atom_id": residual_atom["atom_id"],
                    "component_id": residual_component_id,
                    "component_u_interval": residual_interval,
                    "left_runs": (
                        [residual_run] if residual_side == "LEFT" else []
                    ),
                    "right_runs": (
                        [residual_run] if residual_side == "RIGHT" else []
                    ),
                }
                residual_proof = _short_component_setback_proof(
                    residual_unresolved,
                    residual_atom,
                    strand,
                    effective_forbidden_intervals,
                    radius,
                    plan_atoms,
                    forbidden_envelopes,
                )
                if residual_proof is None:
                    empty_correspondence_proof = {
                        "proof_version": "SHORT_COMPONENT_PROOF_REJECTED",
                        "residual_atom": dict(residual_atom),
                        "residual_unresolved": residual_unresolved,
                        "effective_forbidden_intervals": [
                            list(interval)
                            for interval in effective_forbidden_intervals
                        ],
                        "forbidden_envelopes": list(forbidden_envelopes),
                    }
                if residual_proof is not None:
                    setback_ports.append(
                        _commit_short_component_setback(
                            residual_proof,
                            correspondence,
                            pipe_id,
                            ledger_by_edge_id,
                        )
                    )
                    committed_short_setback_proofs.append(residual_proof)
                    empty_correspondence_proof = {
                        "proof_version": "SHORT_COMPONENT_ONLY_CORRESPONDENCE_V1",
                        "correspondence_id": correspondence.correspondence_id,
                        "pipe_id": int(pipe_id),
                        "edge_ids": residual_edge_ids,
                        "short_component_proof": residual_proof,
                    }
                    correspondence_proven = True
        strip_attempts.append(
            {
                "correspondence_id": correspondence.correspondence_id,
                "status": "PASS" if correspondence_proven else "DEFERRED",
                "reason": (
                    None
                    if correspondence_proven
                    else "NO_UNIQUE_REGULAR_COMPONENT"
                ),
                "pipe_id": pipe_id,
                "left_chain_count": len(left_chains),
                "right_chain_count": len(right_chains),
                "left_regular_run_count": len(left_runs),
                "right_regular_run_count": len(right_runs),
                "plan_atom_count": len(plan_atoms),
                "matched_component_count": matched_count,
                "short_setback_count": len(committed_short_setback_proofs),
                "empty_correspondence_proof": empty_correspondence_proof,
                "unresolved_components": unresolved_components,
            "atom_run_diagnostics": [
                    {
                        "atom_id": atom["atom_id"],
                        "span_id": int(atom["span_id"]),
                        "patch_pair": list(atom["patch_pair"]),
                        "convexity": int(atom["convexity"]),
                        "u_interval": list(atom["u_interval"]),
                        "left_runs": [
                            {
                                "edge_ids": list(run["edge_ids"]),
                                "full_cyclic_atom": bool(
                                    run.get("full_cyclic_atom")
                                ),
                                "cyclic_phase_shift": run.get(
                                    "cyclic_phase_shift"
                                ),
                                "u_values": list(run["u_values"]),
                                "edge_lengths": [
                                    (Vector(end) - Vector(start)).length
                                    for start, end in zip(
                                        run["coordinates"],
                                        run["coordinates"][1:],
                                    )
                                ],
                                "coordinates": [
                                    tuple(float(value) for value in point)
                                    for point in run["coordinates"]
                                ],
                                "u_interval": list(run["u_interval"]),
                            }
                            for run in left_runs_by_atom[atom["atom_id"]]
                        ],
                        "right_runs": [
                            {
                                "edge_ids": list(run["edge_ids"]),
                                "full_cyclic_atom": bool(
                                    run.get("full_cyclic_atom")
                                ),
                                "cyclic_phase_shift": run.get(
                                    "cyclic_phase_shift"
                                ),
                                "u_values": list(run["u_values"]),
                                "edge_lengths": [
                                    (Vector(end) - Vector(start)).length
                                    for start, end in zip(
                                        run["coordinates"],
                                        run["coordinates"][1:],
                                    )
                                ],
                                "coordinates": [
                                    tuple(float(value) for value in point)
                                    for point in run["coordinates"]
                                ],
                                "u_interval": list(run["u_interval"]),
                            }
                            for run in right_runs_by_atom[atom["atom_id"]]
                        ],
                    }
                    for atom in plan_atoms
                ],
            }
        )
    for strand_id, strand in sorted(strands_by_id.items()):
        if strand_id in correspondence_strand_ids:
            continue
        owner_patch_ids = {
            int(patch_id)
            for owner_pair in strand.owner_surface_pairs
            for patch_id in owner_pair
        }
        strand_entries = [
            entry
            for entry in ledger_by_edge_id.values()
            if entry["strand_id"] == strand_id
            and not entry.get("outside_plan_owner_patch")
        ]
        if (
            len(owner_patch_ids) != 1
            or not strand_entries
            or any(
                int(entry["source_patch_id"]) not in owner_patch_ids
                for entry in strand_entries
            )
        ):
            continue
        unclassified_entries = [
            entry
            for entry in strand_entries
            if entry["classification"] == "UNCLASSIFIED"
            and entry["edge_id"] not in overlap_proof_by_edge_id
            and entry["edge_id"] not in micro_loop_proof_by_edge_id
        ]
        if len(unclassified_entries) != len(strand_entries):
            continue
        whole_strand_edge_ids = {
            entry["edge_id"] for entry in unclassified_entries
        }
        if whole_strand_edge_ids:
            for entry in unclassified_entries:
                micro_loop_proof_by_edge_id[entry["edge_id"]] = {
                    "proof_version": "NO_REGULAR_STRIP_CORRESPONDENCE_V1",
                    "edge_ids": sorted(whole_strand_edge_ids),
                    "strand_id": strand_id,
                    "owner_patch_id": next(iter(owner_patch_ids)),
                    "whole_strand_edge_count": len(whole_strand_edge_ids),
                }
    unclassified_by_rail = {}
    for entry in ledger_by_edge_id.values():
        if entry["classification"] == "UNCLASSIFIED":
            unclassified_by_rail.setdefault(entry["rail_id"], []).append(entry)
    for rail_id, entries in sorted(unclassified_by_rail.items()):
        entries_by_evidence = {}
        for entry in entries:
            if entry.get("outside_plan_owner_patch"):
                evidence_key = "OUTSIDE_PLAN_SETBACK"
            elif entry["edge_id"] in overlap_proof_by_edge_id:
                evidence_key = "PIPE_OVERLAP_SETBACK"
            elif entry["edge_id"] in micro_loop_proof_by_edge_id:
                evidence_key = micro_loop_proof_by_edge_id[entry["edge_id"]][
                    "proof_version"
                ]
            else:
                evidence_key = "UNPROVEN_PLAN_BOUNDARY"
            entries_by_evidence.setdefault(evidence_key, []).append(entry)
        for evidence_key, evidence_entries in sorted(entries_by_evidence.items()):
            if not evidence_entries:
                continue
            for chain in _ordered_stable_boundary_chains(evidence_entries):
                first_entry = ledger_by_edge_id[chain["edge_ids"][0]]
                strand = strands_by_id[first_entry["strand_id"]]
                oriented_chain, start_u, end_u = _orient_chain_to_strand(
                    chain,
                    strand,
                )
                reason = evidence_key
                if reason == "UNPROVEN_PLAN_BOUNDARY":
                    chain_u_interval = sorted(
                        (float(start_u), float(end_u))
                    )
                    overlapping_atom_claims = [
                        claim
                        for claim in regular_atom_claims_by_rail_id.get(
                            rail_id,
                            (),
                        )
                        if _common_run_interval(
                            chain_u_interval,
                            claim["u_interval"],
                            bool(claim["strand_cyclic"]),
                        )
                        is not None
                        or (
                            chain_u_interval[1] - chain_u_interval[0]
                            <= 1.0e-8
                            and any(
                                min(map(float, claim["u_interval"]))
                                - 1.0e-10
                                <= chain_u_interval[0] + shift
                                <= max(map(float, claim["u_interval"]))
                                + 1.0e-10
                                for shift in (
                                    range(-2, 3)
                                    if claim["strand_cyclic"]
                                    else (0,)
                                )
                            )
                        )
                    ]
                    terminal_tail_proof = (
                        (
                            next(iter(unique_terminal_tail_proofs.values()))
                            if len(unique_terminal_tail_proofs) == 1
                            else None
                        )
                        if (
                            unique_terminal_tail_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _regular_terminal_tail_handoff_proof(
                                        oriented_chain,
                                        start_u,
                                        end_u,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        radius,
                                    ),
                                )
                                if proof is not None
                                and "proof_version" in proof
                            }
                        )
                        else None
                    )
                    terminal_tail_rejections = [
                        proof
                        for claim in overlapping_atom_claims
                        for proof in (
                            _regular_terminal_tail_handoff_proof(
                                oriented_chain,
                                start_u,
                                end_u,
                                claim,
                                regular_records,
                                ledger_by_edge_id,
                                radius,
                            ),
                        )
                        if proof is not None
                        and "proof_version" not in proof
                    ]
                    atom_boundary_junction_proof = (
                        (
                            next(iter(unique_atom_boundary_proofs.values()))
                            if len(unique_atom_boundary_proofs) == 1
                            else None
                        )
                        if (
                            unique_atom_boundary_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _atom_boundary_junction_handoff_proof(
                                        oriented_chain,
                                        start_u,
                                        end_u,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    outside_span_proof = (
                        _outside_correspondence_span_handoff_proof(
                            oriented_chain,
                            start_u,
                            end_u,
                            regular_atom_claims_by_rail_id.get(rail_id, ()),
                            ledger_by_edge_id,
                        )
                        if not overlapping_atom_claims
                        else None
                    )
                    correspondence_transition_proof = (
                        _correspondence_transition_handoff_proof(
                            oriented_chain,
                            start_u,
                            end_u,
                            overlapping_atom_claims,
                            regular_records,
                            ledger_by_edge_id,
                            first_entry["source_patch_id"],
                        )
                        if len(overlapping_atom_claims) > 1
                        else None
                    )
                    plan_span_crossing_proof = (
                        (
                            next(iter(unique_plan_span_crossing_proofs.values()))
                            if len(unique_plan_span_crossing_proofs) == 1
                            else None
                        )
                        if (
                            unique_plan_span_crossing_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _plan_span_crossing_handoff_proof(
                                        oriented_chain,
                                        start_u,
                                        end_u,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    regular_component_terminal_proof = (
                        (
                            next(
                                iter(
                                    unique_regular_component_terminal_proofs.values()
                                )
                            )
                            if len(unique_regular_component_terminal_proofs) == 1
                            else None
                        )
                        if (
                            unique_regular_component_terminal_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _regular_component_terminal_handoff_proof(
                                        oriented_chain,
                                        start_u,
                                        end_u,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        micro_loop_proof_by_edge_id,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    cyclic_span_terminal_residual_proof = (
                        (
                            next(
                                iter(
                                    unique_cyclic_span_terminal_residual_proofs.values()
                                )
                            )
                            if len(
                                unique_cyclic_span_terminal_residual_proofs
                            )
                            == 1
                            else None
                        )
                        if (
                            unique_cyclic_span_terminal_residual_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _cyclic_span_terminal_residual_handoff_proof(
                                        oriented_chain,
                                        start_u,
                                        end_u,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    regular_component_bridge_proof = (
                        (
                            next(
                                iter(
                                    unique_regular_component_bridge_proofs.values()
                                )
                            )
                            if len(unique_regular_component_bridge_proofs) == 1
                            else None
                        )
                        if (
                            unique_regular_component_bridge_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _regular_component_bridge_handoff_proof(
                                        oriented_chain,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    zero_length_regular_connector_proof = (
                        (
                            next(
                                iter(
                                    unique_zero_length_regular_connector_proofs.values()
                                )
                            )
                            if len(
                                unique_zero_length_regular_connector_proofs
                            )
                            == 1
                            else None
                        )
                        if (
                            unique_zero_length_regular_connector_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _zero_length_regular_connector_handoff_proof(
                                        oriented_chain,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    regular_overlap_bridge_proof = (
                        (
                            next(iter(unique_regular_overlap_bridge_proofs.values()))
                            if len(unique_regular_overlap_bridge_proofs) == 1
                            else None
                        )
                        if (
                            unique_regular_overlap_bridge_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _regular_overlap_bridge_handoff_proof(
                                        oriented_chain,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        overlap_proof_by_edge_id,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    short_regular_terminal_proof = (
                        (
                            next(iter(unique_short_regular_terminal_proofs.values()))
                            if len(unique_short_regular_terminal_proofs) == 1
                            else None
                        )
                        if (
                            unique_short_regular_terminal_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _short_regular_terminal_handoff_proof(
                                        oriented_chain,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    paired_boundary_residual_proof = (
                        (
                            next(iter(unique_paired_boundary_residual_proofs.values()))
                            if len(unique_paired_boundary_residual_proofs) == 1
                            else None
                        )
                        if (
                            unique_paired_boundary_residual_proofs := {
                                _stable_fingerprint(proof): proof
                                for claim in overlapping_atom_claims
                                for proof in (
                                    _paired_boundary_residual_handoff_proof(
                                        oriented_chain,
                                        claim,
                                        regular_records,
                                        ledger_by_edge_id,
                                        first_entry["source_patch_id"],
                                        radius,
                                        micro_loop_proof_by_edge_id,
                                    ),
                                )
                                if proof is not None
                            }
                        )
                        else None
                    )
                    isolated_zero_length_residual_proof = None
                    if len(oriented_chain.get("edge_ids", ())) == 1:
                        isolated_zero_edge_id = oriented_chain["edge_ids"][0]
                        isolated_zero_edge_length = (
                            Vector(
                                ledger_by_edge_id[isolated_zero_edge_id][
                                    "endpoints"
                                ][1]
                            )
                            - Vector(
                                ledger_by_edge_id[isolated_zero_edge_id][
                                    "endpoints"
                                ][0]
                            )
                        ).length
                        isolated_zero_maximum_length = max(
                            radius * 1.0e-2,
                            2.0e-6,
                        )
                        if (
                            isolated_zero_edge_length
                            <= isolated_zero_maximum_length + 1.0e-10
                            and len(overlapping_atom_claims) == 1
                        ):
                            isolated_zero_length_residual_proof = {
                                "proof_version": "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1",
                                "edge_ids": [isolated_zero_edge_id],
                                "edge_length": isolated_zero_edge_length,
                                "maximum_edge_length": isolated_zero_maximum_length,
                                "atom_id": overlapping_atom_claims[0][
                                    "atom_id"
                                ],
                            }
                    structural_proof_candidates = (
                        terminal_tail_proof,
                        atom_boundary_junction_proof,
                        outside_span_proof,
                        correspondence_transition_proof,
                        plan_span_crossing_proof,
                        regular_component_terminal_proof,
                        cyclic_span_terminal_residual_proof,
                        regular_component_bridge_proof,
                        zero_length_regular_connector_proof,
                        regular_overlap_bridge_proof,
                        short_regular_terminal_proof,
                        paired_boundary_residual_proof,
                        isolated_zero_length_residual_proof,
                    )
                    structural_proof = next(
                        (
                            proof
                            for proof in structural_proof_candidates
                            if proof is not None
                            and "proof_version" in proof
                        ),
                        None,
                    )
                    if structural_proof is not None:
                        reason = structural_proof["proof_version"]
                        for edge_id in oriented_chain["edge_ids"]:
                            micro_loop_proof_by_edge_id[edge_id] = (
                                structural_proof
                            )
                    else:
                        raise BatchedChamferError(
                            "UNPROVEN_PLAN_BOUNDARY_EDGE",
                            "真实 Plan Boundary Edge 未被 regular 或结构化 setback proof 消费",
                            {
                            "terminal_tail_rejection": (
                                terminal_tail_proof
                                or terminal_tail_rejections
                            ),
                            "atom_boundary_junction_rejection": (
                                atom_boundary_junction_proof
                                if atom_boundary_junction_proof is not None
                                and "proof_version"
                                not in atom_boundary_junction_proof
                                else None
                            ),
                            "correspondence_transition_rejection": (
                                correspondence_transition_proof
                                if correspondence_transition_proof is not None
                                and "proof_version"
                                not in correspondence_transition_proof
                                else None
                            ),
                    "zero_length_regular_connector_rejection": (
                                zero_length_regular_connector_proof
                                if zero_length_regular_connector_proof
                                is not None
                                and "proof_version"
                                not in zero_length_regular_connector_proof
                                else None
                            ),
                            "short_regular_terminal_rejection": (
                                short_regular_terminal_proof
                                if short_regular_terminal_proof is not None
                                and "proof_version"
                                not in short_regular_terminal_proof
                                else None
                            ),
                            "paired_boundary_residual_rejection": (
                                paired_boundary_residual_proof
                            ),
                            "cyclic_span_terminal_residual_rejection": (
                                cyclic_span_terminal_residual_proof
                            ),
                            "rail_id": rail_id,
                            "rail_entry_states": [
                                {
                                    "edge_id": entry["edge_id"],
                                    "classification": entry["classification"],
                                    "consumer_id": entry.get("consumer_id"),
                                    "endpoint_tokens": list(
                                        entry["endpoint_tokens"]
                                    ),
                                    "overlap_proof_version": (
                                        overlap_proof_by_edge_id[
                                            entry["edge_id"]
                                        ]["proof_version"]
                                        if entry["edge_id"]
                                        in overlap_proof_by_edge_id
                                        else None
                                    ),
                                    "structural_proof_version": (
                                        micro_loop_proof_by_edge_id[
                                            entry["edge_id"]
                                        ]["proof_version"]
                                        if entry["edge_id"]
                                        in micro_loop_proof_by_edge_id
                                        else None
                                    ),
                                }
                                for entry in ledger_by_edge_id.values()
                                if entry["rail_id"] == rail_id
                            ],
                            "source_patch_id": int(first_entry["source_patch_id"]),
                            "chain_endpoint_tokens": list(
                                oriented_chain.get("endpoint_tokens", ())
                            ),
                            "edge_ids": list(oriented_chain["edge_ids"]),
                            "edge_lengths": [
                                round(
                                    (
                                        Vector(entry["endpoints"][1])
                                        - Vector(entry["endpoints"][0])
                                    ).length,
                                    12,
                                )
                                for entry in evidence_entries
                                if entry["edge_id"]
                                in set(oriented_chain["edge_ids"])
                            ],
                            "u_interval": [
                                round(float(start_u), 10),
                                round(float(end_u), 10),
                            ],
                            "regular_atom_claims": overlapping_atom_claims,
                            "all_regular_atom_claims": (
                                regular_atom_claims_by_rail_id.get(rail_id, ())
                            ),
                            "strip_attempts": [
                                attempt
                                for attempt in strip_attempts
                                if attempt["correspondence_id"]
                                in {
                                    claim["correspondence_id"]
                                    for claim in overlapping_atom_claims
                                }
                            ],
                "correspondence_regular_records": [
                                {
                                    "consumer_id": record["consumer_id"],
                                    "correspondence_id": record[
                                        "correspondence_id"
                                    ],
                                    "u_interval": record["u_interval"],
                                    "left_edge_ids": record["left_edge_ids"],
                                    "right_edge_ids": record["right_edge_ids"],
                                    "terminal_extension_edge_ids": record[
                                        "terminal_extension_edge_ids"
                                    ],
                                    "left_u_interval": record["left_u_interval"],
                                    "right_u_interval": record["right_u_interval"],
                                "geometry_guard": record["geometry_guard"],
                                "left_boundary_endpoint_tokens": {
                                    "start": list(
                                        ledger_by_edge_id[
                                            record["left_edge_ids"][0]
                                        ]["endpoint_tokens"]
                                    ),
                                    "end": list(
                                        ledger_by_edge_id[
                                            record["left_edge_ids"][-1]
                                        ]["endpoint_tokens"]
                                    ),
                                },
                                "right_boundary_endpoint_tokens": {
                                    "start": list(
                                        ledger_by_edge_id[
                                            record["right_edge_ids"][0]
                                        ]["endpoint_tokens"]
                                    ),
                                    "end": list(
                                        ledger_by_edge_id[
                                            record["right_edge_ids"][-1]
                                        ]["endpoint_tokens"]
                                    ),
                                },
                                }
                                for record in regular_records
                                if record["correspondence_id"]
                                in {
                                    claim["correspondence_id"]
                                    for claim in overlapping_atom_claims
                                }
                            ],
                            },
                        )
                overlap_proofs = [
                    overlap_proof_by_edge_id[edge_id]
                    for edge_id in oriented_chain["edge_ids"]
                    if edge_id in overlap_proof_by_edge_id
                ]
                micro_loop_proofs = [
                    micro_loop_proof_by_edge_id[edge_id]
                    for edge_id in oriented_chain["edge_ids"]
                    if edge_id in micro_loop_proof_by_edge_id
                ]
                if reason == "PIPE_OVERLAP_SETBACK" and len(overlap_proofs) != len(
                    oriented_chain["edge_ids"]
                ):
                    raise BatchedChamferError(
                        "OVERLAP_EDGE_SETBACK_PROOF_MISSING",
                        "Overlap setback port 含未证明的 Boundary Edge",
                        {"edge_ids": list(oriented_chain["edge_ids"])},
                    )
                if reason in {
                    "STITCHED_MICRO_LOOP_JUNCTION_V1",
                    "ZERO_LENGTH_BOOLEAN_EDGE_SETBACK_V1",
                    "ATTACHED_CYCLIC_MICRO_COMPONENT_SETBACK_V1",
                    "RADIUS_COLLAPSED_SINGLE_EDGE_SETBACK_V1",
                    "NO_REGULAR_STRIP_CORRESPONDENCE_V1",
                    "REGULAR_TERMINAL_TAIL_HANDOFF_V1",
                    "ATOM_BOUNDARY_JUNCTION_HANDOFF_V1",
                    "OUTSIDE_CORRESPONDENCE_SPAN_HANDOFF_V1",
                    "CORRESPONDENCE_TRANSITION_HANDOFF_V1",
                    "PLAN_SPAN_CROSSING_HANDOFF_V1",
                    "REGULAR_COMPONENT_TERMINAL_HANDOFF_V1",
                    "REGULAR_COMPONENT_BRIDGE_HANDOFF_V1",
                } and len(micro_loop_proofs) != len(oriented_chain["edge_ids"]):
                    raise BatchedChamferError(
                        "MICRO_LOOP_JUNCTION_PROOF_MISSING",
                        "Micro-loop setback port 含未证明的 Boundary Edge",
                        {"edge_ids": list(oriented_chain["edge_ids"])},
                    )
                port_id = (
                    f"setback:{rail_id}:"
                    + _stable_fingerprint(oriented_chain["edge_ids"])[:20]
                )
                for edge_id in oriented_chain["edge_ids"]:
                    if ledger_by_edge_id[edge_id]["classification"] != "UNCLASSIFIED":
                        raise BatchedChamferError(
                            "REGULAR_CORE_LEDGER_CONFLICT",
                            "Setback port 重复消费 Boundary Edge",
                            {"edge_id": edge_id, "port_id": port_id},
                        )
                    ledger_by_edge_id[edge_id]["classification"] = "SETBACK_RESERVED"
                    ledger_by_edge_id[edge_id]["consumer_id"] = port_id
                setback_ports.append(
                    {
                        "port_id": port_id,
                        "pipe_id": int(first_entry["pipe_id"]),
                        "strand_id": first_entry["strand_id"],
                        "rail_id": rail_id,
                        "source_patch_id": int(first_entry["source_patch_id"]),
                        "reason": reason,
                        "outside_plan_owner_patch": bool(
                            first_entry.get("outside_plan_owner_patch")
                        ),
                        "ordered_edge_ids": oriented_chain["edge_ids"],
                        "ordered_coordinates": oriented_chain["coordinates"],
                        "is_cyclic": bool(oriented_chain["is_cyclic"]),
                        "direction": (
                            "FEATURE_STRAND_FORWARD"
                            if not strand.cyclic
                            else "STABLE_CYCLIC_BOUNDARY_ORDER"
                        ),
                        "u_interval": [
                            round(float(start_u), 10),
                            round(float(end_u), 10),
                        ],
                        "overlap_edge_proofs": overlap_proofs,
                        "micro_loop_junction_proofs": micro_loop_proofs,
                    }
                )
    reconciled_structural_handoff_components = (
        _reconcile_structural_handoff_components(
            strip_attempts,
            setback_ports,
            ledger_by_edge_id,
        )
    )
    classified_ledger = tuple(
        ledger_by_edge_id[edge_id]
        for edge_id in sorted(ledger_by_edge_id)
    )
    classified_count = sum(
        entry["classification"] != "UNCLASSIFIED"
        for entry in classified_ledger
    )
    ledger_edge_ids = {entry["edge_id"] for entry in classified_ledger}
    regular_edge_ids = {
        edge_id
        for record in regular_records
        for edge_id in (
            *record["left_edge_ids"],
            *record["right_edge_ids"],
            *record["terminal_extension_edge_ids"],
        )
    }
    setback_edge_ids = {
        edge_id
        for port in setback_ports
        for edge_id in port["ordered_edge_ids"]
    }
    regular_records_by_consumer = {
        record["consumer_id"]: record for record in regular_records
    }
    setback_ports_by_consumer = {
        port["port_id"]: port for port in setback_ports
    }
    regular_ledger_edges_by_consumer = {}
    setback_ledger_edges_by_consumer = {}
    invalid_ledger_classification_count = 0
    orphan_ledger_consumer_count = 0
    outside_plan_regular_edge_count = 0
    outside_plan_wrong_reason_count = 0
    for entry in classified_ledger:
        classification = entry["classification"]
        consumer_id = entry.get("consumer_id")
        if classification == "REGULAR_STRIP_CONSUMED":
            regular_ledger_edges_by_consumer.setdefault(consumer_id, set()).add(
                entry["edge_id"]
            )
            if consumer_id not in regular_records_by_consumer:
                orphan_ledger_consumer_count += 1
            if entry.get("outside_plan_owner_patch"):
                outside_plan_regular_edge_count += 1
        elif classification == "SETBACK_RESERVED":
            setback_ledger_edges_by_consumer.setdefault(consumer_id, set()).add(
                entry["edge_id"]
            )
            port = setback_ports_by_consumer.get(consumer_id)
            if port is None:
                orphan_ledger_consumer_count += 1
            elif entry.get("outside_plan_owner_patch") and port.get("reason") != (
                "OUTSIDE_PLAN_SETBACK"
            ):
                outside_plan_wrong_reason_count += 1
        else:
            invalid_ledger_classification_count += 1
    consumer_edge_mismatch_count = sum(
        set(
            record["left_edge_ids"]
            + record["right_edge_ids"]
            + record["terminal_extension_edge_ids"]
        )
        != regular_ledger_edges_by_consumer.get(consumer_id, set())
        for consumer_id, record in regular_records_by_consumer.items()
    ) + sum(
        set(port["ordered_edge_ids"])
        != setback_ledger_edges_by_consumer.get(consumer_id, set())
        for consumer_id, port in setback_ports_by_consumer.items()
    )
    unresolved_remote_component_ids = {
        (
            attempt["correspondence_id"],
            unresolved.get("component_id")
            or unresolved.get("atom_id")
            or _stable_fingerprint(
                {
                    "left": unresolved.get("left_run_ids", ()),
                    "right": unresolved.get("right_run_ids", ()),
                    "reason": unresolved.get("reason"),
                }
            )[:20],
        )
        for attempt in strip_attempts
        for unresolved in attempt.get("unresolved_components", ())
    }
    unresolved_remote_component_count = len(unresolved_remote_component_ids)
    deferred_attempt_count = sum(
        attempt.get("status") == "DEFERRED"
        for attempt in strip_attempts
    )
    return (
        tuple(sorted(regular_records, key=lambda record: record["consumer_id"])),
        classified_ledger,
        tuple(sorted(setback_ports, key=lambda port: port["port_id"])),
        {
            "real_regular_strip_face_count": sum(
                record["face_count"] for record in regular_records
            ),
            "classified_boundary_edge_count": classified_count,
            "unclassified_boundary_edge_count": len(classified_ledger) - classified_count,
            "regular_edge_count": len(regular_edge_ids),
            "setback_edge_count": len(setback_edge_ids),
            "missing_from_partition_count": len(
                ledger_edge_ids - regular_edge_ids - setback_edge_ids
            ),
            "extra_in_partition_count": len(
                (regular_edge_ids | setback_edge_ids) - ledger_edge_ids
            ),
            "duplicate_partition_edge_count": len(
                regular_edge_ids & setback_edge_ids
            ),
            "invalid_ledger_classification_count": invalid_ledger_classification_count,
            "orphan_ledger_consumer_count": orphan_ledger_consumer_count,
            "consumer_edge_mismatch_count": consumer_edge_mismatch_count,
            "outside_plan_edge_count": sum(
                bool(entry.get("outside_plan_owner_patch"))
                for entry in classified_ledger
            ),
            "outside_plan_regular_edge_count": outside_plan_regular_edge_count,
            "outside_plan_wrong_reason_count": outside_plan_wrong_reason_count,
            "unresolved_remote_component_count": unresolved_remote_component_count,
            "reconciled_structural_handoff_component_count": len(
                reconciled_structural_handoff_components
            ),
            "reconciled_structural_handoff_components": (
                reconciled_structural_handoff_components
            ),
            "deferred_attempt_count": deferred_attempt_count,
            "all_ledger_edges_consumed_once": (
                classified_count == len(classified_ledger)
                and ledger_edge_ids == regular_edge_ids | setback_edge_ids
                and not regular_edge_ids & setback_edge_ids
                and not invalid_ledger_classification_count
                and not orphan_ledger_consumer_count
                and not consumer_edge_mismatch_count
                and not outside_plan_regular_edge_count
                and not outside_plan_wrong_reason_count
            ),
            "strip_attempts": strip_attempts,
        },
    )


# 分别执行正序与逆序 Exact Boolean batch Cut，并比较最终 canonical topology。
# source_object/pipes/color_batches/probe_collection: Preview source、正式 Pipes、确定 coloring 与临时 Collection；返回 order diagnostics。
def _run_batch_order_cut_probe(
    source_object,
    pipes,
    color_batches,
    probe_collection,
    plan_id,
):
    forward = _run_independent_batch_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        plan_id,
        "FORWARD",
    )
    reverse = _run_independent_batch_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        plan_id,
        "REVERSE",
    )
    return {
        "real_cut_probe": True,
        "cut_strategy": "INDEPENDENT_STAGING",
        "forward_cut_signature": forward["cut_signature"],
        "reverse_cut_signature": reverse["cut_signature"],
        "forward_cut_batch_count": len(forward["records"]),
        "reverse_cut_batch_count": len(reverse["records"]),
        "batch_order_invariant": (
            forward["cut_signature"] == reverse["cut_signature"]
        ),
        "forward_cut_records": forward["records"],
        "reverse_cut_records": reverse["records"],
        "forward_reverse_built_independently": True,
        "sequential_probe_executed": False,
        "sequential_probe_reason": (
            "Rejected by Phase B design: overlapping batches must not mutate one shared Mesh"
        ),
    }


# 从 per-Pipe Boolean intersection 提取显式 Pipe/Patch owner 的 regular-core Rail records，并建立 exactly-once ledger。
# source_object/groups/pipes/overlap_pairs/radius: Preview source、冻结 groups、正式 Pipes、Pipe overlap graph 与 radius；返回 Phase C records/ledger/ports/diagnostics。
def _build_regular_core_contract(
    source_object,
    groups,
    pipes,
    overlap_pairs,
    radius,
):
    rails, rail_diagnostics = _cutter_intersection_rails(
        source_object,
        groups,
        pipes,
        radius,
    )
    pipe_trees = {}
    pipe_bounds = {}
    for pipe in pipes:
        pipe_id = int(pipe[PIPE_ID_TAG])
        pipe_bmesh = bmesh.new()
        pipe_bmesh.from_mesh(pipe.data)
        pipe_trees[pipe_id] = BVHTree.FromBMesh(pipe_bmesh)
        pipe_bmesh.free()
        pipe_bounds[pipe_id] = _pipe_bounds(pipe)
    rail_records, rail_summary = _extract_boolean_rail_pair_records(
        None,
        groups,
        pipe_trees,
        pipe_bounds,
        radius,
        rails=rails,
        ownership_backend="CUTTER_FACE_COMPONENT_PROVENANCE",
        pipe_overlap_pairs=overlap_pairs,
    )
    regular_records = []
    ledger = []
    for record in rail_records:
        if record.get("geometry_guard", {}).get("status") != "PASS":
            continue
        group_id = int(record["group_id"])
        owner_key = f"pipe:{group_id}:span:{int(record['span_id'])}"
        regular_records.append(
            {
                "owner_key": owner_key,
                "pipe_id": group_id,
                "span_id": int(record["span_id"]),
                "source_edge_ids": list(record["source_edge_ids"]),
                "patch_pair": [
                    int(record["left_patch_id"]),
                    int(record["right_patch_id"]),
                ],
                "rail_left": [list(point) for point in record["rail_left"]],
                "rail_right": [list(point) for point in record["rail_right"]],
                "left_cyclic": bool(record.get("left_cyclic")),
                "right_cyclic": bool(record.get("right_cyclic")),
                "endpoint_trim": record.get("endpoint_trim", {}),
                "geometry_guard": record["geometry_guard"],
            }
        )
        for side, coordinates in (
            ("LEFT", record["rail_left"]),
            ("RIGHT", record["rail_right"]),
        ):
            for segment_index in range(len(coordinates) - 1):
                ledger.append(
                    {
                        "edge_key": _stable_fingerprint(
                            sorted(
                                (
                                    [round(float(value), 8) for value in coordinates[segment_index]],
                                    [round(float(value), 8) for value in coordinates[segment_index + 1]],
                                )
                            )
                        ),
                        "owner_key": owner_key,
                        "pipe_id": group_id,
                        "side": side,
                        "segment_index": segment_index,
                        "consumption": "REGULAR_CORE",
                    }
                )
    edge_key_counts = {}
    for entry in ledger:
        edge_key = entry["edge_key"]
        edge_key_counts[edge_key] = edge_key_counts.get(edge_key, 0) + 1
    duplicate_edge_keys = sorted(
        edge_key for edge_key, count in edge_key_counts.items() if count > 1
    )
    setback_ports = [
        {
            "port_key": f"pipe:{int(record['group_id'])}:span:{int(record['span_id'])}:DEFERRED",
            "pipe_id": int(record["group_id"]),
            "span_id": int(record["span_id"]),
            "reason": record.get("reason", "JUNCTION_OR_TERMINAL"),
            "patch_pair": list(record.get("patch_pair", ())),
        }
        for record in rail_summary.get("deferred_spans", [])
    ] + [
        {
            "port_key": f"pipe:{int(record['group_id'])}:span:{int(record['span_id'])}:OCCLUDED",
            "pipe_id": int(record["group_id"]),
            "span_id": int(record["span_id"]),
            "reason": "OVERLAP_OCCLUDED",
            "patch_pair": list(record.get("patch_pair", ())),
        }
        for record in rail_summary.get("occluded_spans", [])
    ]
    diagnostics = {
        "ownership_backend": rail_summary.get("ownership_backend"),
        "span_count": rail_summary.get("span_count", 0),
        "regular_core_count": len(regular_records),
        "setback_port_count": len(setback_ports),
        "unresolved_span_count": len(rail_summary.get("unresolved_spans", [])),
        "classification_coverage": rail_summary.get("classification_coverage", 0.0),
        "ledger_edge_count": len(ledger),
        "duplicate_ledger_edge_keys": duplicate_edge_keys,
        "all_ledger_edges_consumed_once": not duplicate_edge_keys,
        "cross_pipe_owner_guessing": False,
        "global_fill": False,
        "rail_diagnostics": rail_diagnostics,
    }
    if diagnostics["unresolved_span_count"]:
        raise BatchedChamferError(
            "REGULAR_CORE_SPAN_UNRESOLVED",
            "Phase C 存在未分类 regular/junction span",
            diagnostics,
        )
    if duplicate_edge_keys:
        raise BatchedChamferError(
            "REGULAR_CORE_LEDGER_CONFLICT",
            "Phase C Rail ledger 存在重复消费",
            diagnostics,
        )
    return tuple(regular_records), tuple(ledger), tuple(setback_ports), diagnostics


# 删除本次 batched probe 创建的 Object/Mesh/Collection，不触碰调用前存在的用户数据。
# created_objects/created_collections: 调用前后差集；无返回值。
def _cleanup_created_data(created_objects, created_collections):
    for obj in list(created_objects):
        if bpy.data.objects.get(obj.name) != obj:
            continue
        object_type = obj.type
        data = obj.data if object_type in {"MESH", "CURVE"} else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if object_type == "MESH":
                bpy.data.meshes.remove(data)
            else:
                bpy.data.curves.remove(data)
    for collection in list(created_collections):
        if bpy.data.collections.get(collection.name) == collection:
            bpy.data.collections.remove(collection)


# 构建分批 Feature Chamfer；Phase A/B 只验证权威输入与 overlap/order，不生成产品输出。
# source_object: Preview source Mesh；preview_plan: 当前有效 immutable ChamferPlan；preview_parameters: live modifier 参数；debug_stage: 阶段门禁。
def build_batched_feature_chamfer(
    source_object,
    preview_plan,
    preview_parameters,
    debug_stage,
):
    if debug_stage not in SUPPORTED_DEBUG_STAGES:
        raise BatchedChamferError(
            "BATCHED_STAGE_NOT_IMPLEMENTED",
            f"Batched Finalize stage 尚未通过门禁：{debug_stage}",
            {"debug_stage": debug_stage},
        )
    if source_object is None or source_object.type != "MESH":
        raise BatchedChamferError(
            "INVALID_CONTEXT",
            "Batched Feature Chamfer requires one Mesh source Object",
            {},
        )
    fingerprint_before = source_fingerprint(source_object)
    plan_fingerprint_before = plan_source_fingerprint(source_object)
    radius = float(preview_parameters.get("radius", 0.0))
    if (
        preview_plan is None
        or preview_plan.source_fingerprint != plan_fingerprint_before
        or abs(float(preview_plan.radius) - radius) > 1.0e-10
        or preview_plan.input_contract != "GN_PREVIEW_V1"
    ):
        raise BatchedChamferError(
            "PREVIEW_INPUT_CONTRACT_MISMATCH",
            "Batched backend 只接受当前有效 GN_PREVIEW_V1 ChamferPlan",
            {
                "source_fingerprint": plan_fingerprint_before,
                "plan_source_fingerprint": (
                    preview_plan.source_fingerprint if preview_plan else None
                ),
                "plan_radius": preview_plan.radius if preview_plan else None,
                "preview_radius": radius,
            },
        )
    previous_objects = set(bpy.data.objects)
    previous_collections = set(bpy.data.collections)
    probe_collection = bpy.data.collections.new(
        f"{source_object.name}_FeatureChamferBatchedProbe"
    )
    bpy.context.scene.collection.children.link(probe_collection)
    try:
        groups, pipes, pipe_specs = _build_preview_pipe_contract(
            source_object,
            preview_plan,
            preview_parameters,
            probe_collection,
        )
        _validate_plan_rail_coverage(preview_plan, groups)
        normalized_pipe_ids = _normalize_pipe_winding(pipes)
        if normalized_pipe_ids:
            pipe_specs = tuple(
                PreviewPipeSpec(
                    **{
                        **asdict(spec),
                        "mesh_fingerprint": _mesh_fingerprint(
                            next(
                                pipe.data
                                for pipe in pipes
                                if int(pipe[PIPE_ID_TAG]) == spec.pipe_id
                            )
                        ),
                    }
                )
                for spec in pipe_specs
            )
        overlap_pairs = _pipe_overlap_pairs(pipes)
        overlap_setback_intervals = _pipe_overlap_setback_intervals(
            groups,
            pipes,
            overlap_pairs,
            radius,
        )
        pipe_ids = tuple(spec.pipe_id for spec in pipe_specs)
        color_batches = color_pipe_overlap_graph(pipe_ids, overlap_pairs)
        graph_order_fingerprint = batch_order_invariance_fingerprint(
            pipe_specs,
            overlap_pairs,
            color_batches,
        )
        cut_order_diagnostics = {
            "real_cut_probe": False,
            "forward_cut_signature": None,
            "reverse_cut_signature": None,
            "forward_cut_batch_count": 0,
            "reverse_cut_batch_count": 0,
            "batch_order_invariant": None,
            "forward_cut_records": [],
            "reverse_cut_records": [],
        }
        regular_core_records = ()
        boundary_edge_ledger = ()
        junction_regions = ()
        regular_core_diagnostics = {
            "regular_core_count": 0,
            "setback_port_count": 0,
        }
        if debug_stage in {DEBUG_PHASE_B, DEBUG_PHASE_C}:
            cut_order_diagnostics = _run_batch_order_cut_probe(
                source_object,
                pipes,
                color_batches,
                probe_collection,
                preview_plan.plan_id,
            )
            if not cut_order_diagnostics["batch_order_invariant"]:
                raise BatchedChamferError(
                    "BATCH_ORDER_TOPOLOGY_MISMATCH",
                    "正序与逆序 batch Cut 生成了不同的 oriented topology",
                    cut_order_diagnostics,
                )
        if debug_stage == DEBUG_PHASE_C:
            staging_boundary_ledger = _build_staging_boundary_ledger(
                preview_plan,
                pipe_specs,
                cut_order_diagnostics["forward_cut_records"],
            )
            reverse_staging_boundary_ledger = _build_staging_boundary_ledger(
                preview_plan,
                pipe_specs,
                cut_order_diagnostics["reverse_cut_records"],
            )
            staging_rail_chains = _build_staging_rail_chains(
                staging_boundary_ledger
            )
            reverse_staging_rail_chains = _build_staging_rail_chains(
                reverse_staging_boundary_ledger
            )
            boundary_universe_fingerprint = _stable_fingerprint(
                staging_boundary_ledger
            )
            reverse_boundary_universe_fingerprint = _stable_fingerprint(
                reverse_staging_boundary_ledger
            )
            rail_chain_fingerprint = _stable_fingerprint(staging_rail_chains)
            reverse_rail_chain_fingerprint = _stable_fingerprint(
                reverse_staging_rail_chains
            )
            if (
                boundary_universe_fingerprint
                != reverse_boundary_universe_fingerprint
                or rail_chain_fingerprint != reverse_rail_chain_fingerprint
            ):
                raise BatchedChamferError(
                    "PHASE_C_ORDER_MISMATCH",
                    "正序/逆序 independent staging 的 Boundary universe 或 Rail chain 不一致",
                    {
                        "forward_boundary_universe_fingerprint": boundary_universe_fingerprint,
                        "reverse_boundary_universe_fingerprint": reverse_boundary_universe_fingerprint,
                        "forward_rail_chain_fingerprint": rail_chain_fingerprint,
                        "reverse_rail_chain_fingerprint": reverse_rail_chain_fingerprint,
                    },
                )
            (
                regular_core_records,
                boundary_edge_ledger,
                junction_regions,
                regular_core_diagnostics,
            ) = _build_cyclic_regular_strip_partition(
                preview_plan,
                groups,
                staging_rail_chains,
                staging_boundary_ledger,
                overlap_pairs,
                overlap_setback_intervals,
                radius,
            )
            (
                reverse_regular_core_records,
                reverse_boundary_edge_ledger,
                reverse_junction_regions,
                reverse_regular_core_diagnostics,
            ) = _build_cyclic_regular_strip_partition(
                preview_plan,
                groups,
                reverse_staging_rail_chains,
                reverse_staging_boundary_ledger,
                overlap_pairs,
                overlap_setback_intervals,
                radius,
            )
            regular_geometry_fingerprint = _stable_fingerprint(
                regular_core_records
            )
            reverse_regular_geometry_fingerprint = _stable_fingerprint(
                reverse_regular_core_records
            )
            ledger_fingerprint = _stable_fingerprint(boundary_edge_ledger)
            reverse_ledger_fingerprint = _stable_fingerprint(
                reverse_boundary_edge_ledger
            )
            port_fingerprint = _stable_fingerprint(junction_regions)
            reverse_port_fingerprint = _stable_fingerprint(
                reverse_junction_regions
            )
            if (
                regular_geometry_fingerprint
                != reverse_regular_geometry_fingerprint
                or ledger_fingerprint != reverse_ledger_fingerprint
                or port_fingerprint != reverse_port_fingerprint
            ):
                raise BatchedChamferError(
                    "PHASE_C_ORDER_MISMATCH",
                    "正序/逆序 Phase C regular geometry、ledger 或 setback ports 不一致",
                    {
                        "forward_geometry_fingerprint": regular_geometry_fingerprint,
                        "reverse_geometry_fingerprint": reverse_regular_geometry_fingerprint,
                        "forward_ledger_fingerprint": ledger_fingerprint,
                        "reverse_ledger_fingerprint": reverse_ledger_fingerprint,
                        "forward_port_fingerprint": port_fingerprint,
                        "reverse_port_fingerprint": reverse_port_fingerprint,
                    },
                )
            regular_core_diagnostics = {
                **regular_core_diagnostics,
                "regular_core_count": len(regular_core_records),
                "setback_port_count": len(junction_regions),
                "unresolved_span_count": regular_core_diagnostics[
                    "unclassified_boundary_edge_count"
                ],
                "observed_boundary_edge_count": len(staging_boundary_ledger),
                "observed_rail_chain_count": sum(
                    len(chains) for chains in staging_rail_chains.values()
                ),
                "observed_rail_chains": staging_rail_chains,
                "boundary_identity_backend": "INDEPENDENT_STAGING_DIRECT_PROVENANCE",
                "overlap_setback_intervals": overlap_setback_intervals,
                "phase_c_boundary_universe_fingerprint": boundary_universe_fingerprint,
                "phase_c_reverse_boundary_universe_fingerprint": reverse_boundary_universe_fingerprint,
                "phase_c_rail_chain_fingerprint": rail_chain_fingerprint,
                "phase_c_reverse_rail_chain_fingerprint": reverse_rail_chain_fingerprint,
                "phase_c_boundary_order_invariant": True,
                "phase_c_geometry_fingerprint": regular_geometry_fingerprint,
                "phase_c_reverse_geometry_fingerprint": reverse_regular_geometry_fingerprint,
                "phase_c_ledger_fingerprint": ledger_fingerprint,
                "phase_c_reverse_ledger_fingerprint": reverse_ledger_fingerprint,
                "phase_c_port_fingerprint": port_fingerprint,
                "phase_c_reverse_port_fingerprint": reverse_port_fingerprint,
                "phase_c_regular_order_invariant": True,
                "reverse_phase_c_counts": {
                    "regular_core_count": len(reverse_regular_core_records),
                    "ledger_edge_count": len(reverse_boundary_edge_ledger),
                    "setback_port_count": len(reverse_junction_regions),
                    "classified_boundary_edge_count": reverse_regular_core_diagnostics[
                        "classified_boundary_edge_count"
                    ],
                },
                "cross_pipe_owner_guessing": False,
                "global_fill": False,
            }
            strip_geometry_guard = _validate_regular_strip_geometry(
                regular_core_records
            )
            regular_core_diagnostics["strip_geometry_guard"] = (
                strip_geometry_guard
            )
            if strip_geometry_guard["status"] != "PASS":
                raise BatchedChamferError(
                    "REGULAR_STRIP_GEOMETRY_INVALID",
                    "Phase C Regular Strip orientation/area/duplicate Face guard 失败",
                    strip_geometry_guard,
                )
        order_fingerprint = graph_order_fingerprint
        contract_fingerprint = _stable_fingerprint(
            [asdict(spec) for spec in pipe_specs]
        )
        overlap_set = set(overlap_pairs)
        batch_records = tuple(
            {
                "batch_index": batch_index,
                "pipe_ids": list(batch),
                "internal_overlap_pairs": [
                    list(pair)
                    for pair in overlap_pairs
                    if pair[0] in batch and pair[1] in batch
                ],
                "cut_signature": _stable_fingerprint(
                    {
                        "pipe_ids": sorted(batch),
                        "pipe_meshes": {
                            str(spec.pipe_id): spec.mesh_fingerprint
                            for spec in pipe_specs
                            if spec.pipe_id in batch
                        },
                    }
                ),
            }
            for batch_index, batch in enumerate(color_batches)
        )
        if any(record["internal_overlap_pairs"] for record in batch_records):
            raise BatchedChamferError(
                "BATCH_INTERNAL_OVERLAP",
                "Overlap graph coloring 产生了相交 batch",
                {"overlap_pairs": sorted(overlap_set)},
            )
        if source_fingerprint(source_object) != fingerprint_before:
            raise BatchedChamferError(
                "SOURCE_MUTATED",
                "Batched probe 修改了 source Mesh",
                {},
            )
        return BatchedChamferResult(
            status="PROTOTYPE",
            backend_id=BATCHED_BACKEND_ID,
            debug_stage=debug_stage,
            output_object_name=None,
            plan_id=preview_plan.plan_id,
            source_fingerprint=plan_fingerprint_before,
            radius=radius,
            preview_pipe_contract_fingerprint=contract_fingerprint,
            pipe_specs=pipe_specs,
            overlap_pairs=overlap_pairs,
            color_batches=color_batches,
            batch_records=(
                *batch_records,
                *regular_core_records,
            ),
            boundary_edge_ledger=boundary_edge_ledger,
            junction_regions=junction_regions,
            topology_diagnostics={
                "pipe_count": len(pipe_specs),
                "batch_count": len(color_batches),
                "all_pipes_colored_once": (
                    sorted(pipe_id for batch in color_batches for pipe_id in batch)
                    == sorted(pipe_ids)
                ),
                "batch_internal_overlap_count": sum(
                    len(record["internal_overlap_pairs"])
                    for record in batch_records
                ),
                "source_unchanged": True,
                "normalized_pipe_winding_ids": list(normalized_pipe_ids),
                **regular_core_diagnostics,
                **cut_order_diagnostics,
            },
            batch_order_invariance_fingerprint=order_fingerprint,
            failure_code=None,
        )
    finally:
        _cleanup_created_data(
            set(bpy.data.objects) - previous_objects,
            set(bpy.data.collections) - previous_collections,
        )
