# -*- coding: utf-8 -*-
"""旁路验证稳定 Face 记录号能否携带完整身份穿过 Boolean。"""

import hashlib
import json
import os
import struct
import time
from pathlib import Path

import bpy


INPUT_BLEND = Path(os.environ["HST_FACE_RECORD_INPUT_BLEND"])
ORACLE_JSON = Path(os.environ["HST_FACE_RECORD_ORACLE"])
OUTPUT_JSON = Path(os.environ["HST_FACE_RECORD_OUTPUT"])
SOURCE_OBJECT_NAME = "Extruded.002"
RECORD_ATTRIBUTE = "hst_feature_chamfer_face_record_id"
FIXED_BOUNDARY_ATTRIBUTE = "hst_feature_chamfer_fixed_intersection_edge"
SOURCE_RECORD_OFFSET = 1
CUTTER_RECORD_OFFSET = 1_000_001
PIPE_PREFIX = "hst_feature_chamfer_pipe_member_"
PATCH_PREFIX = "hst_feature_chamfer_boundary_patch_"
SEGMENT_PREFIX = "hst_feature_chamfer_segment_face_"
STATION_PREFIX = "hst_feature_chamfer_segment_station_face_"
STATION_SQUARED_PREFIX = "hst_feature_chamfer_segment_station_squared_face_"
WITNESS_ENDPOINTS = (
    (-0.97608030, -1.07864141, 0.15915006),
    (-0.97608018, -1.07483113, 0.16071391),
)


# value: 任意 JSON 数据；返回稳定 SHA-256。
def _stable_fingerprint(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# coordinate: 三维坐标；返回冻结 oracle 使用的八位小数坐标。
def _coordinate_key(coordinate):
    return tuple(round(float(value), 8) for value in coordinate)


# mesh/edge: evaluated Mesh 与 Edge；返回方向无关的量化端点键。
def _edge_key(mesh, edge):
    return tuple(sorted(
        _coordinate_key(mesh.vertices[index].co)
        for index in edge.vertices
    ))


# mesh/edge: evaluated Mesh 与 Edge；返回方向无关的原始浮点位键。
def _edge_bits_key(mesh, edge):
    return tuple(sorted(
        tuple(struct.pack(">d", float(value)).hex() for value in mesh.vertices[index].co)
        for index in edge.vertices
    ))


# node_group/geometry_socket/offset/name: 在指定 Geometry 的 FACE 域写入非零整数记录号；返回输出 Geometry。
def _install_record_store(node_group, geometry_socket, offset, name):
    index = node_group.nodes.new("GeometryNodeInputIndex")
    index.name = f"{name} Face Index"
    add = node_group.nodes.new("FunctionNodeIntegerMath")
    add.name = f"{name} Face Record Offset"
    add.operation = "ADD"
    add.inputs[1].default_value = int(offset)
    node_group.links.new(index.outputs["Index"], add.inputs[0])
    store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store.name = f"{name} Face Record Carrier"
    store.data_type = "INT"
    store.domain = "FACE"
    store.inputs["Name"].default_value = RECORD_ATTRIBUTE
    node_group.links.new(geometry_socket, store.inputs["Geometry"])
    node_group.links.new(add.outputs[0], store.inputs["Value"])
    return store.outputs["Geometry"]


# node_group: 在正式 wrapper 的 source/Cutter 输入处安装两组不重叠记录号；返回链路和固定规模统计。
def _install_face_record_carriers(node_group):
    boolean_node = node_group.nodes["Boolean Pro"]
    switch_node = node_group.nodes["HST Boolean Result or Cutter"]
    source_links = [
        link for link in tuple(node_group.links)
        if link.to_node == boolean_node and link.to_socket.name == "Geometry"
    ]
    cutter_links = [
        link for link in tuple(node_group.links)
        if link.to_node == boolean_node and link.to_socket.name == "Geometry B"
    ]
    switch_cutter_links = [
        link for link in tuple(node_group.links)
        if link.to_node == switch_node and link.to_socket.name == "True"
    ]
    if len(source_links) != 1 or len(cutter_links) != 1 or len(switch_cutter_links) != 1:
        raise RuntimeError("Preview source/Cutter seam 不唯一")
    source_socket = source_links[0].from_socket
    cutter_socket = cutter_links[0].from_socket
    for link in source_links + cutter_links + switch_cutter_links:
        node_group.links.remove(link)
    source_record_socket = _install_record_store(
        node_group,
        source_socket,
        SOURCE_RECORD_OFFSET,
        "HST Source",
    )
    cutter_record_socket = _install_record_store(
        node_group,
        cutter_socket,
        CUTTER_RECORD_OFFSET,
        "HST Cutter",
    )
    node_group.links.new(source_record_socket, boolean_node.inputs["Geometry"])
    node_group.links.new(cutter_record_socket, boolean_node.inputs["Geometry B"])
    node_group.links.new(cutter_record_socket, switch_node.inputs["True"])
    return {
        "_source_socket": source_record_socket,
        "_cutter_socket": cutter_record_socket,
        "node_delta": 6,
        "link_delta": 8,
        "mesh_attribute_count": 1,
        "record_attribute": RECORD_ATTRIBUTE,
        "record_type": "INT",
        "record_domain": "FACE",
        "source_record_offset": SOURCE_RECORD_OFFSET,
        "cutter_record_offset": CUTTER_RECORD_OFFSET,
    }


# source_object/node_group/geometry_socket: 临时把指定 Geometry 接到正式输出并复制 evaluated Mesh。
def _evaluate_socket(source_object, node_group, geometry_socket):
    group_output = next(
        node for node in node_group.nodes
        if node.bl_idname == "NodeGroupOutput" and node.is_active_output
    )
    geometry_input = group_output.inputs["Geometry"]
    previous_links = [
        link for link in tuple(node_group.links)
        if link.to_socket == geometry_input
    ]
    if len(previous_links) != 1:
        raise RuntimeError("Preview Geometry 输出 seam 不唯一")
    previous_socket = previous_links[0].from_socket
    node_group.links.remove(previous_links[0])
    node_group.links.new(geometry_socket, geometry_input)
    node_group.update_tag()
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    mesh = bpy.data.meshes.new_from_object(
        source_object.evaluated_get(depsgraph),
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    node_group.links.remove(next(
        link for link in tuple(node_group.links)
        if link.to_socket == geometry_input
    ))
    node_group.links.new(previous_socket, geometry_input)
    node_group.update_tag()
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    return mesh


# source_object: 复制正式 Preview 当前 Boolean 输出 evaluated Mesh。
def _evaluate_boolean(source_object):
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return bpy.data.meshes.new_from_object(
        source_object.evaluated_get(depsgraph),
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )


# mesh: 建立 Face→Edge 与 Vertex→Face 邻接表。
def _mesh_adjacency(mesh):
    faces_by_edge = {}
    faces_by_vertex = {}
    for polygon in mesh.polygons:
        for vertex_index in polygon.vertices:
            faces_by_vertex.setdefault(vertex_index, []).append(polygon.index)
        for loop_index in polygon.loop_indices:
            edge_index = mesh.loops[loop_index].edge_index
            faces_by_edge.setdefault(edge_index, []).append(polygon.index)
    return faces_by_edge, faces_by_vertex


# mesh/face_index: 读取一个输入 Face 的完整稀疏事实，作为 Python 内存 ledger 值。
def _face_facts(mesh, face_index):
    pipe_ids = sorted(
        int(attribute.name.removeprefix(PIPE_PREFIX))
        for attribute in mesh.attributes
        if attribute.domain == "FACE"
        and attribute.name.startswith(PIPE_PREFIX)
        and bool(attribute.data[face_index].value)
    )
    patch_ids = sorted(
        int(attribute.name.removeprefix(PATCH_PREFIX))
        for attribute in mesh.attributes
        if attribute.domain == "FACE"
        and attribute.name.startswith(PATCH_PREFIX)
        and bool(attribute.data[face_index].value)
    )
    segment_ids = sorted(
        int(attribute.name.removeprefix(SEGMENT_PREFIX))
        for attribute in mesh.attributes
        if attribute.domain == "FACE"
        and attribute.name.startswith(SEGMENT_PREFIX)
        and float(attribute.data[face_index].value) > 1.0e-6
    )
    segments = []
    for segment_id in segment_ids:
        segments.append({
            "segment_id": segment_id,
            "membership": float(mesh.attributes[f"{SEGMENT_PREFIX}{segment_id}"].data[face_index].value),
            "station_weighted": float(mesh.attributes[f"{STATION_PREFIX}{segment_id}"].data[face_index].value),
            "station_squared_weighted": float(mesh.attributes[f"{STATION_SQUARED_PREFIX}{segment_id}"].data[face_index].value),
        })
    return {
        "pipe_ids": pipe_ids,
        "patch_ids": patch_ids,
        "segments": segments,
    }


# mesh/side: 冻结记录号→完整 Face 事实的 Python ledger；返回 ledger 与输入统计。
def _build_input_ledger(mesh, side):
    attribute = mesh.attributes.get(RECORD_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
        raise RuntimeError(f"{side} 输入缺少 INT/FACE 记录号")
    ledger = {}
    face_records = []
    for polygon in mesh.polygons:
        record_id = int(attribute.data[polygon.index].value)
        if record_id <= 0 or record_id in ledger:
            raise RuntimeError(f"{side} 输入 Face 记录号不唯一: {record_id}")
        facts = _face_facts(mesh, polygon.index)
        ledger[record_id] = facts
        face_records.append({
            "record_id": record_id,
            "input_face_index": polygon.index,
            "vertex_indices": list(polygon.vertices),
            "coordinates": [
                list(_coordinate_key(mesh.vertices[index].co))
                for index in polygon.vertices
            ],
            **facts,
        })
    return ledger, {
        "side": side,
        "face_count": len(face_records),
        "record_min": min(ledger) if ledger else None,
        "record_max": max(ledger) if ledger else None,
        "record_count": len(ledger),
        "ledger_fingerprint": _stable_fingerprint(face_records),
        "multi_pipe_face_count": sum(len(item["pipe_ids"]) > 1 for item in face_records),
        "multi_segment_face_count": sum(len(item["segments"]) > 1 for item in face_records),
        "face_records": face_records,
    }


# mesh/ledger: 核对 Boolean 输出每张 Face 的记录号与旧动态事实是否指向同一输入 Face。
def _audit_output_faces(mesh, ledger):
    attribute = mesh.attributes.get(RECORD_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
        raise RuntimeError("Boolean 输出缺少 INT/FACE 记录号")
    unknown = []
    fact_mismatches = []
    records = []
    for polygon in mesh.polygons:
        record_id = int(attribute.data[polygon.index].value)
        actual = _face_facts(mesh, polygon.index)
        expected = ledger.get(record_id)
        if expected is None:
            unknown.append({"output_face_index": polygon.index, "record_id": record_id})
        elif actual != expected:
            fact_mismatches.append({
                "output_face_index": polygon.index,
                "record_id": record_id,
                "expected": expected,
                "actual": actual,
            })
        records.append({
            "output_face_index": polygon.index,
            "record_id": record_id,
            "vertex_indices": list(polygon.vertices),
            "coordinates": [
                list(_coordinate_key(mesh.vertices[index].co))
                for index in polygon.vertices
            ],
        })
    return records, {
        "output_face_count": len(records),
        "known_record_count": len(records) - len(unknown),
        "unknown_record_count": len(unknown),
        "fact_mismatch_count": len(fact_mismatches),
        "first_unknown": unknown[0] if unknown else None,
        "first_fact_mismatch": fact_mismatches[0] if fact_mismatches else None,
        "record_fingerprint": _stable_fingerprint(records),
    }


# values: 数值序列；返回 Blender FACE→EDGE/POINT 数值域的算术平均。
def _domain_average(values):
    return sum(float(value) for value in values) / len(values)


# mesh/face_indices/ledger: 从记录号账本恢复一个 domain 元素上的完整稀疏事实。
def _restore_domain_facts(mesh, face_indices, ledger):
    record_attribute = mesh.attributes[RECORD_ATTRIBUTE]
    facts = [ledger[int(record_attribute.data[index].value)] for index in face_indices]
    pipe_ids = sorted({pipe_id for item in facts for pipe_id in item["pipe_ids"]})
    patch_ids = sorted({patch_id for item in facts for patch_id in item["patch_ids"]})
    segment_ids = sorted({
        segment["segment_id"]
        for item in facts
        for segment in item["segments"]
    })
    segments = []
    for segment_id in segment_ids:
        values = []
        for item in facts:
            segment = next(
                (entry for entry in item["segments"] if entry["segment_id"] == segment_id),
                None,
            )
            values.append(segment or {
                "membership": 0.0,
                "station_weighted": 0.0,
                "station_squared_weighted": 0.0,
            })
        membership = _domain_average([item["membership"] for item in values])
        if membership <= 1.0e-6:
            continue
        segments.append({
            "segment_id": segment_id,
            "membership": membership,
            "station": _domain_average([item["station_weighted"] for item in values]) / membership,
            "station_squared": _domain_average([item["station_squared_weighted"] for item in values]) / membership,
        })
    return {"pipe_ids": pipe_ids, "patch_ids": patch_ids, "segments": segments}


# mesh/edge/faces_by_edge/faces_by_vertex/ledger/segment_contract: 仅用记录号账本恢复一条 Boundary Edge 身份。
def _restore_edge(mesh, edge, faces_by_edge, faces_by_vertex, ledger, segment_contract):
    edge_facts = _restore_domain_facts(mesh, faces_by_edge[edge.index], ledger)
    segments = []
    for segment in edge_facts["segments"]:
        contract = segment_contract.get(segment["segment_id"], {})
        endpoints = []
        for vertex_index in edge.vertices:
            point_facts = _restore_domain_facts(
                mesh,
                faces_by_vertex[vertex_index],
                ledger,
            )
            point_segment = next(
                item for item in point_facts["segments"]
                if item["segment_id"] == segment["segment_id"]
            )
            endpoints.append({
                "coordinate": list(_coordinate_key(mesh.vertices[vertex_index].co)),
                "station": round(point_segment["station"], 10),
                "station_squared": round(point_segment["station_squared"], 10),
            })
        endpoints.sort(key=lambda item: item["coordinate"])
        segments.append({
            "segment_id": segment["segment_id"],
            "pipe_id": int(contract.get("pipe_id", -1)),
            "port_indices": sorted(int(value) for value in contract.get("port_indices", ())),
            "membership": round(segment["membership"], 10),
            "station": round(segment["station"], 10),
            "station_squared": round(segment["station_squared"], 10),
            "endpoints": endpoints,
        })
    return {
        "historical_edge_key": _edge_bits_key(mesh, edge),
        "endpoints": [list(item) for item in _edge_key(mesh, edge)],
        "pipe_ids": edge_facts["pipe_ids"],
        "patch_ids": edge_facts["patch_ids"],
        "segments": segments,
    }


# oracle_record/prototype_record: 按预冻结一 float32 ULP 比较完整身份；返回首个字段差异。
def _compare_identity(oracle_record, prototype_record):
    for field in ("pipe_ids", "patch_ids"):
        if oracle_record[field] != prototype_record[field]:
            return {"field": field, "oracle": oracle_record[field], "prototype": prototype_record[field]}
    oracle_segments = oracle_record["segments"]
    prototype_segments = prototype_record["segments"]
    if [item["segment_id"] for item in oracle_segments] != [item["segment_id"] for item in prototype_segments]:
        return {
            "field": "segment_ids",
            "oracle": [item["segment_id"] for item in oracle_segments],
            "prototype": [item["segment_id"] for item in prototype_segments],
        }
    for oracle_segment, prototype_segment in zip(oracle_segments, prototype_segments):
        for field in ("pipe_id", "port_indices"):
            if oracle_segment[field] != prototype_segment[field]:
                return {"field": f"segment_{oracle_segment['segment_id']}.{field}", "oracle": oracle_segment[field], "prototype": prototype_segment[field]}
        for field in ("membership", "station", "station_squared"):
            oracle_bits = struct.unpack(">I", struct.pack(">f", float(oracle_segment[field])))[0]
            prototype_bits = struct.unpack(">I", struct.pack(">f", float(prototype_segment[field])))[0]
            if abs(oracle_bits - prototype_bits) > 1:
                return {"field": f"segment_{oracle_segment['segment_id']}.{field}", "oracle": oracle_segment[field], "prototype": prototype_segment[field]}
        if len(oracle_segment["endpoints"]) != len(prototype_segment["endpoints"]):
            return {"field": f"segment_{oracle_segment['segment_id']}.endpoints", "oracle": oracle_segment["endpoints"], "prototype": prototype_segment["endpoints"]}
        oracle_endpoints = sorted(oracle_segment["endpoints"], key=lambda item: item["coordinate"])
        for oracle_endpoint, prototype_endpoint in zip(oracle_endpoints, prototype_segment["endpoints"]):
            if oracle_endpoint["coordinate"] != prototype_endpoint["coordinate"]:
                return {"field": f"segment_{oracle_segment['segment_id']}.endpoint_coordinate", "oracle": oracle_endpoint, "prototype": prototype_endpoint}
            for field in ("station", "station_squared"):
                oracle_bits = struct.unpack(">I", struct.pack(">f", float(oracle_endpoint[field])))[0]
                prototype_bits = struct.unpack(">I", struct.pack(">f", float(prototype_endpoint[field])))[0]
                if abs(oracle_bits - prototype_bits) > 1:
                    return {"field": f"segment_{oracle_segment['segment_id']}.endpoint_{field}", "oracle": oracle_endpoint[field], "prototype": prototype_endpoint[field]}
    return None


# oracle/prototype_records: 保留重复 raw Edge multiplicity，逐组比较完整 ledger。
def _compare_records(oracle, prototype_records):
    oracle_by_key = {}
    for record in oracle["records"]:
        key = tuple(sorted(tuple(endpoint) for endpoint in record["endpoints"]))
        oracle_by_key.setdefault(key, []).append(record)
    prototype_by_key = {}
    for record in prototype_records:
        key = tuple(sorted(tuple(endpoint) for endpoint in record["endpoints"]))
        prototype_by_key.setdefault(key, []).append(record)
    missing = sorted(set(oracle_by_key) - set(prototype_by_key))
    extra = sorted(set(prototype_by_key) - set(oracle_by_key))
    multiplicity = [
        key for key in sorted(set(oracle_by_key) & set(prototype_by_key))
        if len(oracle_by_key[key]) != len(prototype_by_key[key])
    ]
    compared = 0
    first_difference = None
    for key in sorted(set(oracle_by_key) & set(prototype_by_key)):
        if key in multiplicity:
            continue
        oracle_group = sorted(oracle_by_key[key], key=lambda item: json.dumps(item["segments"], sort_keys=True))
        prototype_group = sorted(prototype_by_key[key], key=lambda item: json.dumps(item["segments"], sort_keys=True))
        unmatched = list(prototype_group)
        for oracle_record in oracle_group:
            matched_index = None
            differences = []
            for index, prototype_record in enumerate(unmatched):
                difference = _compare_identity(oracle_record, prototype_record)
                if difference is None:
                    matched_index = index
                    break
                differences.append(difference)
            compared += 1
            if matched_index is None:
                first_difference = {
                    "edge_key": [list(endpoint) for endpoint in key],
                    "candidate_differences": differences,
                }
                break
            unmatched.pop(matched_index)
        if first_difference:
            break
    passed = not missing and not extra and not multiplicity and first_difference is None
    return {
        "status": "PASS" if passed else "STOP",
        "oracle_unique_count": len(oracle_by_key),
        "prototype_unique_count": len(prototype_by_key),
        "oracle_record_count": sum(len(value) for value in oracle_by_key.values()),
        "prototype_record_count": sum(len(value) for value in prototype_by_key.values()),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "multiplicity_mismatch_count": len(multiplicity),
        "compared_record_count": compared,
        "first_difference": first_difference,
        "float_tolerance": "one_float32_ulp",
    }


# mesh/edge/faces_by_edge/ledger: 冻结首个 Pipe 5 witness 的输出 Face 与记录号回查证据。
def _freeze_witness(mesh, edge, faces_by_edge, ledger):
    record_attribute = mesh.attributes[RECORD_ATTRIBUTE]
    adjacent_faces = []
    for face_index in faces_by_edge[edge.index]:
        polygon = mesh.polygons[face_index]
        record_id = int(record_attribute.data[face_index].value)
        adjacent_faces.append({
            "output_face_index": face_index,
            "record_id_after_boolean": record_id,
            "candidate_input_record_ids": [record_id] if record_id in ledger else [],
            "ledger_facts": ledger.get(record_id),
            "vertex_indices": list(polygon.vertices),
            "coordinates": [list(_coordinate_key(mesh.vertices[index].co)) for index in polygon.vertices],
        })
    return {
        "output_edge_index": edge.index,
        "quantized_endpoint_key": [list(item) for item in _edge_key(mesh, edge)],
        "float64_endpoint_bits": [list(item) for item in _edge_bits_key(mesh, edge)],
        "adjacent_output_faces": adjacent_faces,
    }


# 无参数；执行三层旁路验证并输出可机器读取 JSON。
def main():
    started_at = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=str(INPUT_BLEND))
    source_object = bpy.data.objects[SOURCE_OBJECT_NAME]
    modifier = next(item for item in source_object.modifiers if item.type == "NODES")
    node_group = modifier.node_group
    carrier_contract = _install_face_record_carriers(node_group)
    source_mesh = _evaluate_socket(source_object, node_group, carrier_contract["_source_socket"])
    cutter_mesh = _evaluate_socket(source_object, node_group, carrier_contract["_cutter_socket"])
    source_ledger, source_input = _build_input_ledger(source_mesh, "SOURCE")
    cutter_ledger, cutter_input = _build_input_ledger(cutter_mesh, "CUTTER")
    ledger = {**source_ledger, **cutter_ledger}
    if len(ledger) != len(source_ledger) + len(cutter_ledger):
        raise RuntimeError("source/Cutter Face 记录号范围冲突")
    boolean_started_at = time.perf_counter()
    boolean_mesh = _evaluate_boolean(source_object)
    boolean_seconds = time.perf_counter() - boolean_started_at
    output_faces, face_audit = _audit_output_faces(boolean_mesh, ledger)
    faces_by_edge, faces_by_vertex = _mesh_adjacency(boolean_mesh)
    boundary_attribute = boolean_mesh.attributes.get(FIXED_BOUNDARY_ATTRIBUTE)
    if boundary_attribute is None or boundary_attribute.domain != "EDGE":
        raise RuntimeError("Boolean 输出缺少固定原生相交边属性")
    oracle = json.loads(ORACLE_JSON.read_text(encoding="utf-8"))
    segment_contract = {
        int(segment["segment_id"]): {
            "pipe_id": int(segment["pipe_id"]),
            "port_indices": list(segment["port_indices"]),
        }
        for record in oracle["records"]
        for segment in record["segments"]
    }
    prototype_records = []
    witness = None
    witness_key = tuple(sorted(WITNESS_ENDPOINTS))
    restore_started_at = time.perf_counter()
    for edge in boolean_mesh.edges:
        if not bool(boundary_attribute.data[edge.index].value):
            continue
        prototype_records.append(_restore_edge(
            boolean_mesh,
            edge,
            faces_by_edge,
            faces_by_vertex,
            ledger,
            segment_contract,
        ))
        if _edge_key(boolean_mesh, edge) == witness_key:
            witness = _freeze_witness(boolean_mesh, edge, faces_by_edge, ledger)
    restore_seconds = time.perf_counter() - restore_started_at
    comparison = _compare_records(oracle, prototype_records)
    witness_oracle = next(
        record for record in oracle["records"]
        if tuple(sorted(tuple(endpoint) for endpoint in record["endpoints"])) == witness_key
    )
    witness_prototype = next(
        record for record in prototype_records
        if tuple(sorted(tuple(endpoint) for endpoint in record["endpoints"])) == witness_key
    )
    witness["oracle_identity"] = {
        key: witness_oracle[key] for key in ("pipe_ids", "patch_ids", "segments")
    }
    witness["prototype_identity"] = {
        key: witness_prototype[key] for key in ("pipe_ids", "patch_ids", "segments")
    }
    witness["identity_difference"] = _compare_identity(witness_oracle, witness_prototype)
    face_carrier_pass = (
        face_audit["unknown_record_count"] == 0
        and face_audit["fact_mismatch_count"] == 0
        and witness["identity_difference"] is None
    )
    result = {
        "schema_version": 1,
        "status": "PASS" if comparison["status"] == "PASS" else "STOP",
        "stage": "FACE_RECORD_CARRIER",
        "scope": {
            "input_blend": str(INPUT_BLEND),
            "oracle": str(ORACLE_JSON),
            "blender_version": bpy.app.version_string,
            "prototype_only": True,
            "formal_entry_modified": False,
            "bridge_fill_run": False,
        },
        "carrier_contract": {
            key: value
            for key, value in carrier_contract.items()
            if not key.startswith("_")
        },
        "input_ledgers": {
            "source": source_input,
            "cutter": cutter_input,
            "combined_record_count": len(ledger),
        },
        "output_face_trace": {
            **face_audit,
            "records": output_faces,
        },
        "witness_pipe_5": witness,
        "full_identity_comparison": comparison,
        "timings": {
            "boolean_evaluate_seconds": boolean_seconds,
            "python_restore_seconds": restore_seconds,
            "total_seconds": time.perf_counter() - started_at,
        },
        "gates": {
            "face_record_carrier": "PASS" if face_carrier_pass else "STOP",
            "full_mixed_identity": comparison["status"],
            "bridge_fill": "NOT_RUN_DUE_TO_IDENTITY_GATE" if comparison["status"] != "PASS" else "NOT_RUN_BY_THIS_PROBE",
        },
        "forbidden_recovery": {
            "nearest_or_bvh": False,
            "single_owner": False,
            "fixed_slots": False,
            "fixed_bitmask": False,
            "station_clamp": False,
            "fixture_name_or_edge_id_special_case": False,
        },
        "ledger_fingerprint": _stable_fingerprint(prototype_records),
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[HST_FACE_RECORD_CARRIER]" + json.dumps({
        "status": result["status"],
        "gates": result["gates"],
        "face_trace": face_audit,
        "comparison": comparison,
        "timings": result["timings"],
        "ledger_fingerprint": result["ledger_fingerprint"],
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
