# -*- coding: utf-8 -*-
"""一步式 Feature Chamfer 的 Manifold Boolean 与 Python provenance 运行时。"""

import json
import time

import bpy
import bmesh
from mathutils import Vector

from .experimental_pipe_chamfer_utils import CUTTER_COMPONENT_MEMBERSHIP_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import ORIGINAL_FACE_ATTRIBUTE
from .experimental_pipe_chamfer_utils import CUTTER_COMPONENT_ID_ATTRIBUTE
from .experimental_pipe_chamfer_utils import CUTTER_COMPONENT_PRESENT_ATTRIBUTE
from .experimental_pipe_chamfer_utils import SOURCE_PATCH_ID_ATTRIBUTE
from .experimental_pipe_chamfer_utils import SOURCE_PATCH_PRESENT_ATTRIBUTE
from .experimental_pipe_chamfer_utils import SOURCE_PATCH_MEMBERSHIP_ATTRIBUTE_PREFIX
from .experimental_pipe_chamfer_utils import _base_stats
from .experimental_pipe_chamfer_utils import _build_cutter_set
from .experimental_pipe_chamfer_utils import _build_pipe_mesh_curve
from .experimental_pipe_chamfer_utils import _build_preview_feature_graph
from .experimental_pipe_chamfer_utils import _classify_pipe_endpoints
from .experimental_pipe_chamfer_utils import _clean_open_boundary_degenerates
from .experimental_pipe_chamfer_utils import _groove_face_indices
from .experimental_pipe_chamfer_utils import _mark_original_faces
from .experimental_pipe_chamfer_utils import _source_face_patch_ids
from .feature_chamfer_gn_utils import BOUNDARY_EDGE_ATTRIBUTE
from .feature_chamfer_gn_utils import FeatureChamferPreviewError
from .feature_chamfer_gn_utils import _serialize_preview_pipe_contract
from .feature_chamfer_plan_utils import build_chamfer_plan


COMPACT_EDGE_RECORD_ATTRIBUTE = "hst_chamfer_edge_record_id"
COMPACT_POINT_RECORD_ATTRIBUTE = "hst_chamfer_point_record_id"


# 验证 source 满足 Manifold solver 的闭合输入合同。
# source_object: 正式输入 Mesh Object；验证失败时抛出可诊断错误。
def _validate_manifold_source(source_object):
    bm = bmesh.new()
    try:
        bm.from_mesh(source_object.data)
        if any(len(edge.link_faces) != 2 for edge in bm.edges):
            raise FeatureChamferPreviewError(
                "Feature Chamfer Manifold Boolean requires a closed manifold source Mesh"
            )
    finally:
        bm.free()


# 构建共享 FeatureGraph、immutable ChamferPlan 与 Direct Bridge Pipe 合同。
# source_object/radius: 正式输入 Mesh 与 Radius；返回统计、groups、plan、合同及 Patch IDs。
def _build_one_step_contract(source_object, radius):
    stats = _base_stats(source_object, radius, 8, 35.0, 3.0, 1.5, "ONE_STEP")
    groups = _build_preview_feature_graph(source_object, radius, stats)
    _classify_pipe_endpoints(source_object, groups, radius)
    source_patch_ids = _source_face_patch_ids(source_object)
    plan = build_chamfer_plan(
        source_object,
        groups,
        radius,
        "ONE_STEP_MANIFOLD_V1",
        source_patch_ids=source_patch_ids,
    )
    pipe_contract = json.loads(
        _serialize_preview_pipe_contract(source_object, groups, plan, radius)
    )
    pipe_contract["contract"] = "ONE_STEP_MANIFOLD_PIPE_V1"
    return stats, groups, plan, pipe_contract, source_patch_ids


# 删除临时 Object 及其独占 datablock。
# object_to_remove: 待删除 Object；不存在时无操作。
def _remove_object_data(object_to_remove):
    if object_to_remove is None:
        return
    data = object_to_remove.data
    if bpy.data.objects.get(object_to_remove.name) == object_to_remove:
        bpy.data.objects.remove(object_to_remove, do_unlink=True)
    if data is None or data.users != 0:
        return
    if isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Curve):
        bpy.data.curves.remove(data)


# 删除当前调用创建的临时 Collection 与其中所有 Object。
# collection: 待清理 Collection；不存在时无操作。
def _remove_collection_data(collection):
    if collection is None or bpy.data.collections.get(collection.name) != collection:
        return
    for object_to_remove in tuple(collection.objects):
        _remove_object_data(object_to_remove)
    bpy.data.collections.remove(collection)


# 清理一步式运行时为 Keep Cutter 暂存的诊断集合，供事务失败时回滚。
# collection_name: 当前执行返回的集合名称；为空或集合已被撤销时无操作。
def discard_one_step_cutter(collection_name):
    if not collection_name:
        return
    _remove_collection_data(bpy.data.collections.get(collection_name))


# 复制 source 并移除全部 Modifier，作为一次性 Boolean 输入。
# source_object: 正式输入；返回不共享 Mesh data 的临时 Object。
def _duplicate_runtime_source(source_object):
    runtime_source = source_object.copy()
    runtime_source.data = source_object.data.copy()
    runtime_source.name = f"{source_object.name}_FeatureChamferRuntime"
    source_object.users_collection[0].objects.link(runtime_source)
    for modifier in tuple(runtime_source.modifiers):
        runtime_source.modifiers.remove(modifier)
    runtime_source.matrix_world = source_object.matrix_world.copy()
    return runtime_source


# 用 Blender BooleanModifier 的 MANIFOLD solver 应用 Difference。
# runtime_source/cutter_collection/source_patch_ids/pipe_contract: 临时 source、批量 Cutter、Surface Patch IDs 与冻结合同；返回求值秒数。
def _apply_manifold_difference(
    runtime_source,
    cutter_collection,
    source_patch_ids,
    pipe_contract,
):
    _mark_original_faces(runtime_source, source_patch_ids)
    modifier = runtime_source.modifiers.new(
        "HST Feature Chamfer Manifold Difference",
        type="BOOLEAN",
    )
    modifier.operation = "DIFFERENCE"
    modifier.solver = "MANIFOLD"
    if len(cutter_collection.objects) == 1:
        modifier.operand_type = "OBJECT"
        modifier.object = cutter_collection.objects[0]
    else:
        modifier.operand_type = "COLLECTION"
        modifier.collection = cutter_collection
    started_at = time.perf_counter()
    with bpy.context.temp_override(
        object=runtime_source,
        active_object=runtime_source,
        selected_objects=[runtime_source],
        selected_editable_objects=[runtime_source],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return time.perf_counter() - started_at


# 把 Pipe 折线转换为归一化累计长度记录，供已锁定 Pipe owner 的 Boundary station 计算。
# pipe_record: immutable Pipe 合同记录；返回点、线段和总长。
def _pipe_polyline_record(pipe_record):
    points = [Vector(point) for point in pipe_record["points"]]
    segments = []
    cumulative = 0.0
    pairs = list(zip(points, points[1:]))
    if pipe_record["is_cyclic"] and len(points) > 1:
        pairs.append((points[-1], points[0]))
    for start, end in pairs:
        length = (end - start).length
        if length <= 1.0e-12:
            continue
        segments.append((start, end, cumulative, length))
        cumulative += length
    if cumulative <= 1.0e-12:
        raise FeatureChamferPreviewError(
            f"Runtime Pipe {pipe_record['pipe_id']} lacks usable length"
        )
    return {"segments": segments, "total_length": cumulative}


# 在已由 Boolean one-hot 锁定的 Pipe 折线上计算一个点的全局 station。
# coordinate/polyline: source-local 坐标与预计算 Pipe 折线；返回 0..1 station。
def _project_pipe_station(coordinate, polyline):
    best = None
    for start, end, cumulative, length in polyline["segments"]:
        direction = end - start
        factor = max(
            0.0,
            min(1.0, (coordinate - start).dot(direction) / (length * length)),
        )
        projected = start + direction * factor
        candidate = (
            (coordinate - projected).length_squared,
            (cumulative + length * factor) / polyline["total_length"],
        )
        if best is None or candidate < best:
            best = candidate
    return best[1]


# 把 Pipe 全局 station 映射到某个 segment 的局部 0..1 station。
# segment/pipe_station: segment 合同与 Pipe station；不属于该段时返回 None。
def _segment_station(segment, pipe_station, clamp=False):
    if segment["is_cyclic"]:
        return pipe_station % 1.0
    start = float(segment["spline_start_station"])
    end = float(segment["spline_end_station"])
    value = pipe_station
    if end < start:
        end += 1.0
        if value < start:
            value += 1.0
    if not clamp and (value < start - 1.0e-5 or value > end + 1.0e-5):
        return None
    span = end - start
    if span <= 1.0e-12:
        raise FeatureChamferPreviewError(
            f"Runtime segment {segment['segment_id']} lacks usable span"
        )
    return max(0.0, min(1.0, (value - start) / span))


# 建立固定数量的 compact record-id layers 与 Python registry。
# bm: 当前开口 BMesh；返回 Boundary layer、record-id layers 与空 registry。
def _new_direct_bridge_layers(bm):
    boundary_layer = bm.edges.layers.bool.new(BOUNDARY_EDGE_ATTRIBUTE)
    edge_record_layer = bm.edges.layers.int.new(COMPACT_EDGE_RECORD_ATTRIBUTE)
    point_record_layer = bm.verts.layers.int.new(COMPACT_POINT_RECORD_ATTRIBUTE)
    registry = {
        "edge_records": [{}],
        "point_records": [{}],
    }
    return boundary_layer, edge_record_layer, point_record_layer, registry


# 从 Boolean Face one-hot 读取当前 Face 的全部 Pipe/Patch owners。
# face/layers_by_id: BMesh Face 与 ID→layer；返回命中的 ID set。
def _face_memberships(face, layers_by_id):
    return {
        owner_id
        for owner_id, layer in layers_by_id.items()
        if bool(face[layer])
    }


# 删除 cutter-derived Faces，并把严格 Boolean owner 传播为 Direct Bridge provenance。
# runtime_source/pipe_contract/radius/source_patch_ids/stats: Boolean 输出、冻结合同、Radius、Patch IDs 与统计；返回开口 evaluated Mesh。
def _materialize_direct_bridge_mesh(
    runtime_source,
    pipe_contract,
    radius,
    source_patch_ids,
    stats,
):
    segment_records = tuple(pipe_contract["segments"])
    segments_by_pipe = {}
    for segment in segment_records:
        segments_by_pipe.setdefault(int(segment["pipe_id"]), []).append(segment)
    segments_by_endpoint = {}
    for segment in segment_records:
        endpoint_records = (
            (segment["point_coordinates"][0], 0.0),
            (segment["point_coordinates"][-1], 1.0),
        )
        for coordinate, local_station in endpoint_records:
            key = tuple(round(float(value), 8) for value in coordinate)
            segments_by_endpoint.setdefault(key, []).append((segment, local_station))
    pipe_polylines = {
        int(pipe["pipe_id"]): _pipe_polyline_record(pipe)
        for pipe in pipe_contract["pipes"]
    }
    groove_face_indices = set(_groove_face_indices(runtime_source, stats))
    bm = bmesh.new()
    try:
        bm.from_mesh(runtime_source.data)
        bm.faces.ensure_lookup_table()
        original_layer = bm.faces.layers.bool.get(ORIGINAL_FACE_ATTRIBUTE)
        pipe_id_layer = bm.faces.layers.int.get(CUTTER_COMPONENT_ID_ATTRIBUTE)
        pipe_present_layer = bm.faces.layers.bool.get(CUTTER_COMPONENT_PRESENT_ATTRIBUTE)
        patch_id_layer = bm.faces.layers.int.get(SOURCE_PATCH_ID_ATTRIBUTE)
        patch_present_layer = bm.faces.layers.bool.get(SOURCE_PATCH_PRESENT_ATTRIBUTE)
        if any(layer is None for layer in (
            original_layer,
            pipe_id_layer,
            patch_id_layer,
        )):
            raise FeatureChamferPreviewError(
                "Manifold Boolean did not preserve compact owner provenance"
            )
        edge_pipe_ids = {}
        edge_patch_ids = {}
        for face in bm.faces:
            is_original = bool(face[original_layer])
            identity_layer = patch_id_layer if is_original else pipe_id_layer
            target = edge_patch_ids if is_original else edge_pipe_ids
            identity = int(face[identity_layer])
            for edge in face.edges:
                edge_key = tuple(sorted(vertex.index for vertex in edge.verts))
                target.setdefault(edge_key, set()).add(identity)
        boundary_layer, edge_record_layer, point_record_layer, registry = (
            _new_direct_bridge_layers(bm)
        )
        record_id_by_edge_key = {}
        for edge_key in set(edge_pipe_ids) & set(edge_patch_ids):
            registry["edge_records"].append({
                "pipe_ids": tuple(sorted(edge_pipe_ids[edge_key])),
                "patch_ids": tuple(sorted(edge_patch_ids[edge_key])),
                "segments": {},
            })
            record_id_by_edge_key[edge_key] = len(registry["edge_records"]) - 1
        for edge in bm.edges:
            edge_key = tuple(sorted(vertex.index for vertex in edge.verts))
            edge[edge_record_layer] = record_id_by_edge_key.get(edge_key, 0)
        to_delete = [bm.faces[index] for index in sorted(groove_face_indices)]
        bmesh.ops.delete(bm, geom=to_delete, context="FACES_KEEP_BOUNDARY")
        stats["boundary_degenerate_cleanup"] = _clean_open_boundary_degenerates(
            bm,
            radius,
        )
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
        for edge in boundary_edges:
            witness_record_id = int(edge[edge_record_layer])
            witness_record = registry["edge_records"][witness_record_id]
            pipe_ids = tuple(witness_record.get("pipe_ids", ()))
            patch_ids = tuple(witness_record.get("patch_ids", ()))
            if not pipe_ids or not patch_ids:
                raise FeatureChamferPreviewError(
                    "Open boundary lost exact Manifold Boolean owner provenance"
                )
            edge[boundary_layer] = True
            selected_segments = {}
            for pipe_id in pipe_ids:
                midpoint_pipe_station = _project_pipe_station(
                    (edge.verts[0].co + edge.verts[1].co) * 0.5,
                    pipe_polylines[pipe_id],
                )
                for segment in segments_by_pipe.get(pipe_id, ()):
                    endpoint_pipe_stations = tuple(
                        _project_pipe_station(vertex.co, pipe_polylines[pipe_id])
                        for vertex in edge.verts
                    )
                    segment_endpoint_stations = tuple(
                        _segment_station(
                            segment,
                            pipe_station,
                            clamp=True,
                        )
                        for pipe_station in endpoint_pipe_stations
                    )
                    midpoint_station = sum(segment_endpoint_stations) * 0.5
                    if (
                        not segment["is_cyclic"]
                        and min(segment_endpoint_stations) >= 1.0 - 1.0e-5
                        and max(segment_endpoint_stations) >= 1.0 - 1.0e-5
                        and _segment_station(segment, midpoint_pipe_station) is None
                    ):
                        continue
                    if midpoint_station is None:
                        continue
                    fixed_station = None
                    endpoint_coordinate = (
                        segment["point_coordinates"][0]
                        if midpoint_station <= 0.5
                        else segment["point_coordinates"][-1]
                    )
                    endpoint_projection_station = _project_pipe_station(
                        Vector(endpoint_coordinate),
                        pipe_polylines[pipe_id],
                    )
                    pipe_station_distance = abs(
                        midpoint_pipe_station - endpoint_projection_station
                    )
                    if segment["is_cyclic"]:
                        pipe_station_distance = min(
                            pipe_station_distance,
                            1.0 - pipe_station_distance,
                        )
                    endpoint_station_margin = (
                        2.0 * radius / pipe_polylines[pipe_id]["total_length"]
                    )
                    if pipe_station_distance <= max(1.0e-5, endpoint_station_margin):
                        fixed_station = 0.0 if midpoint_station <= 0.5 else 1.0
                    selected_segments[int(segment["segment_id"])] = (
                        segment,
                        fixed_station,
                        segment_endpoint_stations,
                    )
                    if fixed_station is not None:
                        endpoint_coordinate = (
                            segment["point_coordinates"][0]
                            if midpoint_station <= 0.5
                            else segment["point_coordinates"][-1]
                        )
                        endpoint_key = tuple(
                            round(float(value), 8) for value in endpoint_coordinate
                        )
                        for incident_segment, incident_station in segments_by_endpoint.get(
                            endpoint_key,
                            (),
                        ):
                            selected_segments[int(incident_segment["segment_id"])] = (
                                incident_segment,
                                incident_station,
                                None,
                            )
            edge_segments = {}
            point_segments = {vertex: {} for vertex in edge.verts}
            for segment_id, (
                segment,
                fixed_station,
                segment_endpoint_stations,
            ) in selected_segments.items():
                pipe_id = int(segment["pipe_id"])
                if fixed_station is None:
                    endpoint_stations = segment_endpoint_stations
                else:
                    endpoint_stations = (fixed_station, fixed_station)
                if endpoint_stations:
                    edge_segments[segment_id] = {
                        "membership": 1.0,
                        "station": sum(endpoint_stations) / 2.0,
                        "station_squared": sum(
                            station * station for station in endpoint_stations
                        ) / 2.0,
                    }
                    for vertex, station in zip(edge.verts, endpoint_stations):
                        point_segments[vertex][segment_id] = {
                            "membership": 1.0,
                            "station": station,
                            "station_squared": station * station,
                        }
            edge_record = {
                "patch_ids": patch_ids,
                "segments": edge_segments,
            }
            registry["edge_records"].append(edge_record)
            edge[edge_record_layer] = len(registry["edge_records"]) - 1
            for vertex, segments in point_segments.items():
                prior_id = int(vertex[point_record_layer])
                prior_segments = dict(
                    registry["point_records"][prior_id].get("segments", {})
                )
                prior_segments.update(segments)
                registry["point_records"].append({"segments": prior_segments})
                vertex[point_record_layer] = len(registry["point_records"]) - 1
        evaluated_mesh = runtime_source.data.copy()
        evaluated_mesh.name = f"{runtime_source.data.name}_FeatureChamferOpen"
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        bm.to_mesh(evaluated_mesh)
        evaluated_mesh.update()
        stats["materialized_boundary_edge_count"] = len(boundary_edges)
        stats["compact_runtime_contract"] = True
        stats["compact_runtime_mesh_layer_count"] = 3
        return evaluated_mesh, registry
    finally:
        bm.free()


# 生成 Pipe、执行 Manifold Difference，并返回 Direct Bridge 可直接消费的 Mesh 与合同。
# source_object/radius/show_cutter: 正式输入、Radius 与是否保留 Cutter；返回 runtime bundle。
def build_one_step_manifold_runtime(source_object, radius, show_cutter=False):
    _validate_manifold_source(source_object)
    started_at = time.perf_counter()
    stats, groups, plan, pipe_contract, source_patch_ids = _build_one_step_contract(
        source_object,
        radius,
    )
    analysis_seconds = time.perf_counter() - started_at
    pipe_collection = bpy.data.collections.new(
        f"{source_object.name}_FeatureChamferPipesRuntime"
    )
    bpy.context.scene.collection.children.link(pipe_collection)
    cutter_collection = None
    runtime_source = None
    evaluated_mesh = None
    try:
        build_started_at = time.perf_counter()
        pipes = [
            _build_pipe_mesh_curve(
                source_object,
                group,
                radius,
                8,
                pipe_collection,
            )
            for group in groups
        ]
        cutter_collection, _, _ = _build_cutter_set(pipes, source_object, stats)
        for cutter in cutter_collection.objects:
            for attribute in tuple(cutter.data.attributes):
                if attribute.name.startswith((
                    CUTTER_COMPONENT_MEMBERSHIP_ATTRIBUTE_PREFIX,
                    SOURCE_PATCH_MEMBERSHIP_ATTRIBUTE_PREFIX,
                )) or attribute.name.startswith("hst_pipe_endpoint_member_"):
                    cutter.data.attributes.remove(attribute)
        runtime_source = _duplicate_runtime_source(source_object)
        cutter_seconds = time.perf_counter() - build_started_at
        boolean_seconds = _apply_manifold_difference(
            runtime_source,
            cutter_collection,
            source_patch_ids,
            pipe_contract,
        )
        evaluated_mesh, compact_registry = _materialize_direct_bridge_mesh(
            runtime_source,
            pipe_contract,
            radius,
            source_patch_ids,
            stats,
        )
        if show_cutter:
            cutter_collection.name = f"{source_object.name}_FeatureChamferCutter"
            for cutter in cutter_collection.objects:
                cutter.hide_set(False)
                cutter.hide_render = False
                cutter.display_type = "WIRE"
            retained_cutter_name = cutter_collection.name
            cutter_collection = None
        else:
            retained_cutter_name = None
        return {
            "plan": plan,
            "pipe_contract": pipe_contract,
            "evaluated_mesh": evaluated_mesh,
            "compact_registry": compact_registry,
            "feature_graph": stats,
            "analysis_seconds": analysis_seconds,
            "cutter_build_seconds": cutter_seconds,
            "boolean_seconds": boolean_seconds,
            "cutter_collection_name": retained_cutter_name,
            "solver": "MANIFOLD",
            "station_tolerance": max(
                5.0e-4,
                2.0 * radius
                / max(
                    min(
                        _pipe_polyline_record(pipe)["total_length"]
                        for pipe in pipe_contract["pipes"]
                    ),
                    1.0e-12,
                ),
            ),
        }
    except Exception:
        if evaluated_mesh is not None and evaluated_mesh.users == 0:
            bpy.data.meshes.remove(evaluated_mesh)
        raise
    finally:
        _remove_object_data(runtime_source)
        _remove_collection_data(pipe_collection)
        _remove_collection_data(cutter_collection)
