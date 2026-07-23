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
    return {
        "edge_ids": aligned_edge_ids,
        "coordinates": aligned_coordinates,
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
    }


# 移除 Boolean 数值产生的连续零长度 Edge，同时把这些 Edge 保留给结构化 junction setback。
# run/radius: 当前 open run 与 Chamfer radius；返回清理后的 run、移除 Edge IDs 和 proof。
def _defer_zero_length_run_edges(run, radius):
    coordinates = [Vector(point) for point in run["coordinates"]]
    maximum_length = max(radius * 1.0e-5, 1.0e-8)
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
        return None, ()
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
                        guard = _regular_pair_width_guard(
                            trimmed_left,
                            trimmed_right,
                            radius,
                        )
                        if guard["status"] != "PASS":
                            continue
                        left_coordinates = [
                            Vector(point) for point in trimmed_left["coordinates"]
                        ]
                        right_coordinates = [
                            Vector(point) for point in trimmed_right["coordinates"]
                        ]
                        strip = build_chamfer_strip(
                            left_coordinates,
                            right_coordinates,
                            terminal_constraints={
                                "start_pairs": [(0, 0)],
                                "end_pairs": [
                                    (
                                        len(trimmed_left["coordinates"]) - 1,
                                        len(trimmed_right["coordinates"]) - 1,
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
                                    "left": trimmed_left,
                                    "right": trimmed_right,
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
                tuple(candidate["left"]["edge_ids"]),
                tuple(candidate["right"]["edge_ids"]),
            ): candidate
            for candidate in passing
        }
        if len(unique_by_edges) == 1:
            return next(iter(unique_by_edges.values())), None
        if len(unique_by_edges) > 1:
            minimum_trim_passing_count = len(unique_by_edges)
            return None, {
                "reason": "ENDPOINT_TRIM_AMBIGUOUS",
                "minimum_total_trim": total_trim,
                "candidate_count": len(unique_by_edges),
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
def _regular_run_pair_evaluation(left_run, right_run, strand, radius):
    common = _common_run_interval(
        left_run["u_interval"],
        right_run["u_interval"],
        strand.cyclic,
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
    trimmed_right = _trim_open_run_to_interval(shifted_right, common_interval)
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
        for left_index, left in enumerate(remaining):
            if changed:
                break
            for right_index, right in enumerate(remaining):
                if left_index == right_index:
                    continue
                u_gap = abs(
                    float(left["u_values"][-1]) - float(right["u_values"][0])
                )
                seam_shift = 0
                if strand_cyclic and u_gap > parameter_tolerance:
                    seam_candidates = sorted(
                        (
                            abs(
                                float(left["u_values"][-1])
                                - (float(right["u_values"][0]) + shift)
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
                shifted_right_u_values = [
                    float(value) + seam_shift
                    for value in right["u_values"]
                ]
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
                break
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
                normalized.append(run)
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
            candidate, rejection = _regular_run_pair_evaluation(
                left_run,
                right_run,
                strand,
                radius,
            )
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
            matched.append(
                {
                    "left_run_id": left_id,
                    "right_run_id": right_id,
                    "micro_loop_junction_proofs": list(micro_loop_proofs),
                    **candidate_records[(left_id, right_id)],
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
):
    left_core = match["left"]
    right_core = match["right"]
    left_open = [Vector(point) for point in left_core["coordinates"]]
    right_open = [Vector(point) for point in right_core["coordinates"]]
    if len(left_open) < 2 or len(right_open) < 2:
        return None, {"reason": "REGULAR_COMPONENT_TOO_SHORT"}
    expected_width = radius * (2.0 ** 0.5)
    width_tolerance = max(radius * 0.60, 1.0e-5)
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
        }
    consumer_id = (
        f"regular:{correspondence.correspondence_id}:"
        + _stable_fingerprint(
            [left_core["edge_ids"], right_core["edge_ids"]]
        )[:20]
    )
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
    for edge_id in consumed_edge_ids:
        if ledger_by_edge_id[edge_id]["classification"] != "UNCLASSIFIED":
            raise BatchedChamferError(
                "REGULAR_CORE_LEDGER_CONFLICT",
                "真实 Boundary Edge 被多个 Regular Strip 消费",
                {"edge_id": edge_id},
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
            "micro_loop_junction_proofs": list(
                match.get("micro_loop_junction_proofs", ())
            ),
        "u_interval": [
            round(float(value), 10)
            for value in match["common_u_interval"]
        ],
        "virtual_atom_boundaries": {
            "left": list(left_core.get("virtual_atom_boundaries", ())),
            "right": list(right_core.get("virtual_atom_boundaries", ())),
        },
        "faces": faces,
            "face_count": len(faces),
            "geometry_guard": {
                **strip["diagnostics"],
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


# 把 atom 内 fragments 裁到双侧共同 u components，再交给唯一 matching。
# left_runs/right_runs/atom: atom 两侧 fragments 与 Plan atom；返回 component-indexed runs。
def _partition_atom_runs_by_common_components(left_runs, right_runs, atom):
    components = _common_atom_component_intervals(
        left_runs,
        right_runs,
        atom,
    )
    partitioned_left = []
    partitioned_right = []
    for component_index, interval in enumerate(components):
        component_id = f"{atom['atom_id']}:{component_index}"
        for runs, target in (
            (left_runs, partitioned_left),
            (right_runs, partitioned_right),
        ):
            for run in runs:
                trimmed = _trim_open_run_to_interval(run, interval)
                if trimmed is None:
                    continue
                trimmed = _clip_run_geometry_to_interval(trimmed, interval)
                target.append(
                    {
                        **trimmed,
                        "atom_id": atom["atom_id"],
                        "component_id": component_id,
                        "component_u_interval": list(interval),
                    }
                )
    return tuple(partitioned_left), tuple(partitioned_right), components


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
    component_start, component_end = sorted(
        map(float, unresolved["component_u_interval"])
    )
    atom_start, atom_end = sorted(map(float, atom["u_interval"]))
    present_start, present_end = sorted(map(float, present_runs[0]["u_interval"]))
    if (
        component_start < atom_start - 1.0e-10
        or component_end > atom_end + 1.0e-10
        or present_start < component_start - 1.0e-10
        or present_end > component_end + 1.0e-10
    ):
        return None
    strand_length = _feature_strand_arc_length(strand)
    component_arc_length = (component_end - component_start) * strand_length
    maximum_arc_length = radius * 2.0
    boundary_candidates = []
    epsilon_u = 1.0e-8
    if abs(component_start - atom_start) * strand_length <= maximum_arc_length + 1.0e-10:
        boundary_candidates.append(("ATOM_START", atom_start))
    if abs(component_end - atom_end) * strand_length <= maximum_arc_length + 1.0e-10:
        boundary_candidates.append(("ATOM_END", atom_end))
    if len(boundary_candidates) != 1:
        return None
    atom_side, atom_boundary_u = boundary_candidates[0]
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
                    }
                )
    unique_boundaries = {
        boundary["boundary_id"]: boundary for boundary in adjacent_boundaries
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
    present_run = present_runs[0]
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
        "atom_boundary_side": atom_side,
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
    maximum_chain_length = radius * 4.10
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
    if (
        boundary_witness["boundary_type"]
        not in {
            "OVERLAP_FORBIDDEN_ENVELOPE",
            "COLLAPSED_FORBIDDEN_GAP",
        }
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
    adjacent_records = []
    rejected_adjacent_records = []
    adjacency_tolerance_u = max(
        1.0e-8,
        radius * 1.0e-2 / strand_length,
    )
    side_edge_key = "left_edge_ids" if claim["side"] == "LEFT" else "right_edge_ids"
    for record in regular_records:
        if record["correspondence_id"] != claim["correspondence_id"]:
            continue
        record_start, record_end = sorted(map(float, record["u_interval"]))
        matching_record_boundary = None
        if abs(record_start - inner_u) <= adjacency_tolerance_u:
            matching_record_boundary = "START"
        if abs(record_end - inner_u) <= adjacency_tolerance_u:
            if matching_record_boundary is not None:
                continue
            matching_record_boundary = "END"
        if matching_record_boundary is None:
            continue
        record_endpoint_tokens = {
            endpoint_token
            for edge_id in record[side_edge_key]
            for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]
        }
        shared_tokens = sorted(chain_terminal_tokens & record_endpoint_tokens)
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
        direct_overlap_boundary_adjacent = (
            not shared_tokens
            and boundary_witness["boundary_type"]
            == "OVERLAP_FORBIDDEN_ENVELOPE"
            and direct_projection_gap_arc_length <= radius * 0.50 + 1.0e-10
            and chain_length <= maximum_chain_length + 1.0e-10
        )
        if len(shared_tokens) == 1 or direct_overlap_boundary_adjacent:
            adjacent_records.append(
                {
                    "consumer_id": record["consumer_id"],
                    "regular_boundary_side": matching_record_boundary,
                    "shared_endpoint_token": (
                        shared_tokens[0] if shared_tokens else None
                    ),
                    "adjacency_type": (
                        "SHARED_BOUNDARY_ENDPOINT"
                        if shared_tokens
                        else "OVERLAP_BOUNDARY_PROJECTED_GAP"
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
                }
            )
    if len(adjacent_records) != 1:
        nearest_candidates = []
        for record in regular_records:
            if record["correspondence_id"] != claim["correspondence_id"]:
                continue
            record_start, record_end = sorted(map(float, record["u_interval"]))
            boundary_candidates = (
                (("START", record_start), ("END", record_end))
            )
            for record_boundary_side, record_boundary_u in boundary_candidates:
                if (
                    abs(record_boundary_u - inner_u)
                    > candidate_boundary_tolerance
                ):
                    continue
                side_edge_key = (
                    "left_edge_ids"
                    if claim["side"] == "LEFT"
                    else "right_edge_ids"
                )
                record_endpoint_tokens = {
                    endpoint_token
                    for edge_id in record[side_edge_key]
                    for endpoint_token in ledger_by_edge_id[edge_id][
                        "endpoint_tokens"
                    ]
                }
                shared_tokens = sorted(
                    chain_terminal_tokens & record_endpoint_tokens
                )
                projection_gap_u = abs(record_boundary_u - inner_u)
                projection_gap_arc_length = projection_gap_u * strand_length
                topology_adjacent = len(shared_tokens) == 1
                overlap_boundary_adjacent = (
                    not shared_tokens
                    and boundary_witness["boundary_type"]
                    == "OVERLAP_FORBIDDEN_ENVELOPE"
                    and projection_gap_arc_length <= radius * 0.50 + 1.0e-10
                    and chain_length <= radius * 4.0 + 1.0e-10
                )
                if not topology_adjacent and not overlap_boundary_adjacent:
                    continue
                nearest_candidates.append(
                    {
                        "consumer_id": record["consumer_id"],
                        "regular_boundary_side": record_boundary_side,
                        "shared_endpoint_token": (
                            shared_tokens[0] if shared_tokens else None
                        ),
                        "adjacency_type": (
                            "SHARED_BOUNDARY_ENDPOINT"
                            if topology_adjacent
                            else "OVERLAP_BOUNDARY_PROJECTED_GAP"
                        ),
                        "u_interval": list(record["u_interval"]),
                        "projection_gap_u": projection_gap_u,
                        "projection_gap_arc_length": (
                            projection_gap_arc_length
                        ),
                        "maximum_projection_gap_arc_length": radius * 0.50,
                    }
                )
        if (
            not nearest_candidates
            and claim["strand_cyclic"]
            and boundary_witness["boundary_type"]
            == "OVERLAP_FORBIDDEN_ENVELOPE"
            and chain_length <= maximum_chain_length + 1.0e-10
        ):
            cyclic_seam_candidates = []
            for record in regular_records:
                if record["correspondence_id"] != claim["correspondence_id"]:
                    continue
                side_edge_key = (
                    "left_edge_ids"
                    if claim["side"] == "LEFT"
                    else "right_edge_ids"
                )
                record_endpoint_tokens = {
                    endpoint_token
                    for edge_id in record[side_edge_key]
                    for endpoint_token in ledger_by_edge_id[edge_id][
                        "endpoint_tokens"
                    ]
                }
                shared_tokens = sorted(
                    chain_terminal_tokens & record_endpoint_tokens
                )
                if shared_tokens:
                    continue
                for record_boundary_side, record_boundary_u in (
                    ("START", float(record["u_interval"][0])),
                    ("END", float(record["u_interval"][1])),
                ):
                    projection_gap_u = min(
                        abs(record_boundary_u - inner_u - shift)
                        for shift in range(-2, 3)
                    )
                    projection_gap_arc_length = (
                        projection_gap_u * strand_length
                    )
                    if projection_gap_arc_length > radius * 1.10 + 1.0e-10:
                        continue
                    cyclic_seam_candidates.append(
                        {
                            "consumer_id": record["consumer_id"],
                            "regular_boundary_side": record_boundary_side,
                            "shared_endpoint_token": None,
                            "adjacency_type": "CYCLIC_SEAM_PROJECTED_GAP",
                            "u_interval": list(record["u_interval"]),
                            "projection_gap_u": projection_gap_u,
                            "projection_gap_arc_length": (
                                projection_gap_arc_length
                            ),
                            "maximum_projection_gap_arc_length": radius * 1.10,
                        }
                    )
            unique_cyclic_seam_candidates = {
                (
                    candidate["consumer_id"],
                    candidate["regular_boundary_side"],
                ): candidate
                for candidate in cyclic_seam_candidates
            }
            if len(unique_cyclic_seam_candidates) == 1:
                nearest_candidates = [
                    next(iter(unique_cyclic_seam_candidates.values()))
                ]
        if len(nearest_candidates) > 1:
            nearest_candidates.sort(
                key=lambda candidate: (
                    float(candidate["projection_gap_arc_length"]),
                    candidate["consumer_id"],
                    candidate["regular_boundary_side"],
                )
            )
            if (
                float(nearest_candidates[1]["projection_gap_arc_length"])
                - float(nearest_candidates[0]["projection_gap_arc_length"])
                > 1.0e-8
            ):
                nearest_candidates = [nearest_candidates[0]]
        if (
            not nearest_candidates
            and claim["strand_cyclic"]
            and boundary_witness["boundary_type"]
            == "OVERLAP_FORBIDDEN_ENVELOPE"
            and chain_length <= maximum_chain_length + 1.0e-10
        ):
            projected_candidates = []
            for record in regular_records:
                if record["correspondence_id"] != claim["correspondence_id"]:
                    continue
                for record_boundary_side, record_boundary_u in (
                    ("START", float(record["u_interval"][0])),
                    ("END", float(record["u_interval"][1])),
                ):
                    projection_gap_u = min(
                        abs(record_boundary_u - inner_u - shift)
                        for shift in range(-2, 3)
                    )
                    projection_gap_arc_length = projection_gap_u * strand_length
                    if projection_gap_arc_length > radius * 1.10 + 1.0e-10:
                        continue
                    projected_candidates.append(
                        {
                            "consumer_id": record["consumer_id"],
                            "regular_boundary_side": record_boundary_side,
                            "shared_endpoint_token": None,
                            "adjacency_type": "OVERLAP_BOUNDARY_CYCLIC_PROJECTION",
                            "u_interval": list(record["u_interval"]),
                            "projection_gap_u": projection_gap_u,
                            "projection_gap_arc_length": projection_gap_arc_length,
                            "maximum_projection_gap_arc_length": radius * 1.10,
                        }
                    )
            projected_candidates.sort(
                key=lambda candidate: (
                    candidate["projection_gap_arc_length"],
                    candidate["consumer_id"],
                    candidate["regular_boundary_side"],
                )
            )
            if (
                len(projected_candidates) == 1
                or (
                    len(projected_candidates) > 1
                    and projected_candidates[1]["projection_gap_arc_length"]
                    - projected_candidates[0]["projection_gap_arc_length"]
                    > 1.0e-8
                )
            ):
                nearest_candidates = [projected_candidates[0]]
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
        elif len(nearest_candidates) == 1:
            adjacent_records = nearest_candidates
        else:
            return {
                "rejected_stage": "ADJACENT_REGULAR",
                "adjacent_records": adjacent_records,
                "rejected_adjacent_records": rejected_adjacent_records,
                "nearest_candidates": nearest_candidates,
                "inner_u": inner_u,
                "chain_terminal_tokens": sorted(chain_terminal_tokens),
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
        "regular_adjacency_tolerance_u": adjacency_tolerance_u,
        "adjacent_regular": adjacent_records[0],
    }


# 证明一条 maximal Boundary chain 完全落在当前 Rail 所有 correspondence spans 之外。
# oriented_chain/start_u/end_u/claims: 当前有序链、FeatureStrand 投影与该 Rail 的全部 atom claims；返回 span-gap handoff proof 或 None。
def _outside_correspondence_span_handoff_proof(
    oriented_chain,
    start_u,
    end_u,
    claims,
):
    if oriented_chain.get("is_cyclic") or not oriented_chain.get("edge_ids") or not claims:
        return None
    chain_interval = sorted((float(start_u), float(end_u)))
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
        or
        len({claim["side"] for claim in current_claims}) != 1
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
                lower_start, lower_end = (
                    float(lower_claim["u_interval"][0]) + lower_shift,
                    float(lower_claim["u_interval"][1]) + lower_shift,
                )
                for upper_shift in range(-2, 3) if cyclic else (0,):
                    upper_start, upper_end = (
                        float(upper_claim["u_interval"][0]) + upper_shift,
                        float(upper_claim["u_interval"][1]) + upper_shift,
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
        return None
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
            if abs(record_boundary_u - boundary_u) > 1.0e-8:
                continue
            record_endpoint_tokens = {
                endpoint_token
                for edge_id in record[side_edge_key]
                for endpoint_token in ledger_by_edge_id[edge_id]["endpoint_tokens"]
            }
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
                    }
                )
        if len(candidates) != 1:
            return None
        adjacent_records.append(candidates[0])
    if len({record["shared_endpoint_token"] for record in adjacent_records}) != 2:
        return None
    return {
        "proof_version": "CORRESPONDENCE_TRANSITION_HANDOFF_V1",
        "edge_ids": list(oriented_chain["edge_ids"]),
        "component_u_interval": [chain_start, chain_end],
        "source_patch_id": int(source_patch_id),
        "side": current_claims[0]["side"],
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
            atom_left, atom_right, component_intervals = (
                _partition_atom_runs_by_common_components(
                    left_runs_by_atom[atom["atom_id"]],
                    right_runs_by_atom[atom["atom_id"]],
                    atom,
                )
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
                        forbidden_intervals,
                        radius,
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
        for proof in short_setback_proofs:
            setback_ports.append(
                _commit_short_component_setback(
                    proof,
                    correspondence,
                    pipe_id,
                    ledger_by_edge_id,
                )
            )
        strip_attempts.append(
            {
                "correspondence_id": correspondence.correspondence_id,
                "status": "PASS" if matched_count else "DEFERRED",
                "reason": (
                    None if matched_count else "NO_UNIQUE_REGULAR_COMPONENT"
                ),
                "pipe_id": pipe_id,
                "left_chain_count": len(left_chains),
                "right_chain_count": len(right_chains),
                "left_regular_run_count": len(left_runs),
                "right_regular_run_count": len(right_runs),
                "plan_atom_count": len(plan_atoms),
                "matched_component_count": matched_count,
                "short_setback_count": len(short_setback_proofs),
                "unresolved_components": unresolved_components,
                "atom_run_diagnostics": [
                    {
                        "atom_id": atom["atom_id"],
                        "u_interval": list(atom["u_interval"]),
                        "left_runs": [
                            {
                                "edge_ids": list(run["edge_ids"]),
                                "u_interval": list(run["u_interval"]),
                            }
                            for run in left_runs_by_atom[atom["atom_id"]]
                        ],
                        "right_runs": [
                            {
                                "edge_ids": list(run["edge_ids"]),
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
                    outside_span_proof = (
                        _outside_correspondence_span_handoff_proof(
                            oriented_chain,
                            start_u,
                            end_u,
                            regular_atom_claims_by_rail_id.get(rail_id, ()),
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
                    structural_proof = (
                        terminal_tail_proof
                        if terminal_tail_proof is not None
                        and "proof_version" in terminal_tail_proof
                        else (
                            outside_span_proof
                            or correspondence_transition_proof
                        )
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
                            "rail_id": rail_id,
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
                    "OUTSIDE_CORRESPONDENCE_SPAN_HANDOFF_V1",
                    "CORRESPONDENCE_TRANSITION_HANDOFF_V1",
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
        for edge_id in (*record["left_edge_ids"], *record["right_edge_ids"])
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
        set(record["left_edge_ids"] + record["right_edge_ids"])
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
