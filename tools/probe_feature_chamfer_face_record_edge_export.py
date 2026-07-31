# -*- coding: utf-8 -*-
"""验证输入 Face 整数记录号能否在 Boolean active seam 物化到切口 Edge。"""

import json
import os
import struct
import time
from pathlib import Path

import bpy


INPUT_BLEND = Path(os.environ["HST_FACE_RECORD_INPUT_BLEND"])
OUTPUT_JSON = Path(os.environ["HST_FACE_RECORD_OUTPUT"])
SOURCE_OBJECT_NAME = "Extruded.002"
CUTTER_RECORD_ATTRIBUTE = "hst_feature_chamfer_cutter_face_record_id"
SOURCE_RECORD_ATTRIBUTE = "hst_feature_chamfer_source_face_record_id"
CUTTER_EDGE_RECORD_ATTRIBUTE = "hst_feature_chamfer_boundary_cutter_record_id"
SOURCE_EDGE_RECORD_ATTRIBUTE = "hst_feature_chamfer_boundary_source_record_id"
FIXED_BOUNDARY_ATTRIBUTE = "hst_feature_chamfer_fixed_intersection_edge"
PIPE_PREFIX = "hst_feature_chamfer_pipe_member_"
SEGMENT_PREFIX = "hst_feature_chamfer_segment_face_"
STATION_PREFIX = "hst_feature_chamfer_segment_station_face_"
STATION_SQUARED_PREFIX = "hst_feature_chamfer_segment_station_squared_face_"
WITNESS_ENDPOINTS = tuple(sorted((
    (-0.97608030, -1.07864141, 0.15915006),
    (-0.97608018, -1.07483113, 0.16071391),
)))
ORACLE_PIPE_PREFIX = "hst_feature_chamfer_boundary_pipe_"
ORACLE_SEGMENT_PREFIX = "hst_feature_chamfer_boundary_segment_"
ORACLE_STATION_PREFIX = "hst_feature_chamfer_boundary_station_"
ORACLE_STATION_SQUARED_PREFIX = "hst_feature_chamfer_boundary_station_squared_"


# coordinate: 三维坐标；返回八位小数量化坐标。
def _coordinate_key(coordinate):
    return tuple(round(float(value), 8) for value in coordinate)


# mesh/edge: evaluated Mesh 与 Edge；返回方向无关量化端点键。
def _edge_key(mesh, edge):
    return tuple(sorted(
        _coordinate_key(mesh.vertices[index].co)
        for index in edge.vertices
    ))


# mesh/edge: evaluated Mesh 与 Edge；返回方向无关 float64 bit 键。
def _edge_bits_key(mesh, edge):
    return tuple(sorted(
        tuple(struct.pack(">d", float(value)).hex() for value in mesh.vertices[index].co)
        for index in edge.vertices
    ))


# node_group/geometry_socket/attribute_name/label: 在 FACE 域写 Index+1；返回输出 Geometry。
def _store_face_record(node_group, geometry_socket, attribute_name, label):
    index = node_group.nodes.new("GeometryNodeInputIndex")
    index.name = f"{label} Face Index"
    add = node_group.nodes.new("FunctionNodeIntegerMath")
    add.name = f"{label} Face Record Add One"
    add.operation = "ADD"
    add.inputs[1].default_value = 1
    node_group.links.new(index.outputs["Index"], add.inputs[0])
    store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store.name = f"{label} Face Record Carrier"
    store.data_type = "INT"
    store.domain = "FACE"
    store.inputs["Name"].default_value = attribute_name
    node_group.links.new(geometry_socket, store.inputs["Geometry"])
    node_group.links.new(add.outputs[0], store.inputs["Value"])
    return store.outputs["Geometry"]


# node_group: 在 source 与 Cutter 输入安装两个独立固定载体；返回 cutter 输出 socket。
def _install_input_carriers(node_group):
    boolean_node = node_group.nodes["Boolean Pro"]
    switch_node = node_group.nodes["HST Boolean Result or Cutter"]
    source_links = [link for link in tuple(node_group.links) if link.to_node == boolean_node and link.to_socket.name == "Geometry"]
    cutter_links = [link for link in tuple(node_group.links) if link.to_node == boolean_node and link.to_socket.name == "Geometry B"]
    switch_links = [link for link in tuple(node_group.links) if link.to_node == switch_node and link.to_socket.name == "True"]
    if len(source_links) != 1 or len(cutter_links) != 1 or len(switch_links) != 1:
        raise RuntimeError("Preview source/Cutter seam 不唯一")
    source_socket = source_links[0].from_socket
    cutter_socket = cutter_links[0].from_socket
    for link in source_links + cutter_links + switch_links:
        node_group.links.remove(link)
    source_record_socket = _store_face_record(
        node_group,
        source_socket,
        SOURCE_RECORD_ATTRIBUTE,
        "HST Source",
    )
    cutter_record_socket = _store_face_record(
        node_group,
        cutter_socket,
        CUTTER_RECORD_ATTRIBUTE,
        "HST Cutter",
    )
    node_group.links.new(source_record_socket, boolean_node.inputs["Geometry"])
    node_group.links.new(cutter_record_socket, boolean_node.inputs["Geometry B"])
    node_group.links.new(cutter_record_socket, switch_node.inputs["True"])
    return source_record_socket, cutter_record_socket


# boolean_node: 在 active Manifold Difference 输出将两个整数 field 物化到相交 Edge。
def _install_edge_exports(boolean_node, source_field, cutter_field):
    boolean_tree = boolean_node.node_tree
    solver_select = boolean_tree.nodes["Group.007"]
    geometry_target = boolean_tree.nodes["Reroute.037"]
    geometry_links = [link for link in tuple(boolean_tree.links) if link.to_node == geometry_target and link.to_socket.name == "Input"]
    if len(geometry_links) != 1:
        raise RuntimeError("Boolean active output seam 不唯一")
    current_socket = geometry_links[0].from_socket
    boolean_tree.links.remove(geometry_links[0])
    for input_field, output_name in (
        (cutter_field, CUTTER_EDGE_RECORD_ATTRIBUTE),
        (source_field, SOURCE_EDGE_RECORD_ATTRIBUTE),
    ):
        store = boolean_tree.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type = "INT"
        store.domain = "EDGE"
        store.inputs["Name"].default_value = output_name
        boolean_tree.links.new(current_socket, store.inputs["Geometry"])
        boolean_tree.links.new(solver_select.outputs["Intersection Edges"], store.inputs["Selection"])
        boolean_tree.links.new(input_field, store.inputs["Value"])
        current_socket = store.outputs["Geometry"]
    boolean_tree.links.new(current_socket, geometry_target.inputs["Input"])
    return {
        "input_node_delta": 6,
        "input_link_delta": 8,
        "edge_export_node_delta": 2,
        "edge_export_link_delta": 6,
        "mesh_attribute_count": 4,
        "record_domain_before": "FACE",
        "record_domain_after": "EDGE",
        "record_type": "INT",
    }


# source_object/node_group/geometry_socket: 临时从正式输出复制指定 pre-Boolean Mesh。
def _evaluate_input(source_object, node_group, geometry_socket):
    output = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupOutput" and node.is_active_output)
    geometry_input = output.inputs["Geometry"]
    previous_link = next(link for link in tuple(node_group.links) if link.to_socket == geometry_input)
    previous_socket = previous_link.from_socket
    node_group.links.remove(previous_link)
    node_group.links.new(geometry_socket, geometry_input)
    node_group.update_tag()
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    mesh = bpy.data.meshes.new_from_object(source_object.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
    node_group.links.remove(next(link for link in tuple(node_group.links) if link.to_socket == geometry_input))
    node_group.links.new(previous_socket, geometry_input)
    node_group.update_tag()
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    return mesh


# source_object: 复制 post-Boolean evaluated Mesh。
def _evaluate_boolean(source_object):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return bpy.data.meshes.new_from_object(source_object.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)


# node_group/boolean_node/socket_name/field_socket: 把 wrapper 输入侧匿名 Face field 传入 Boolean group interface。
def _expose_boolean_field(node_group, boolean_node, socket_name, field_socket):
    interface_socket = boolean_node.node_tree.interface.new_socket(
        name=socket_name,
        in_out="INPUT",
        socket_type="NodeSocketInt",
    )
    interface_socket.attribute_domain = "FACE"
    group_input = next(
        node for node in boolean_node.node_tree.nodes
        if node.bl_idname == "NodeGroupInput"
    )
    node_group.links.new(field_socket, boolean_node.inputs[socket_name])
    return group_input.outputs[socket_name]


# mesh/face_index: 从旧动态属性读取 Cutter Face 的完整身份事实。
def _cutter_face_facts(mesh, face_index):
    pipe_ids = sorted(
        int(attribute.name.removeprefix(PIPE_PREFIX))
        for attribute in mesh.attributes
        if attribute.domain == "FACE" and attribute.name.startswith(PIPE_PREFIX) and bool(attribute.data[face_index].value)
    )
    segments = []
    for attribute in mesh.attributes:
        if attribute.domain != "FACE" or not attribute.name.startswith(SEGMENT_PREFIX):
            continue
        membership = float(attribute.data[face_index].value)
        if membership <= 1.0e-6:
            continue
        segment_id = int(attribute.name.removeprefix(SEGMENT_PREFIX))
        segments.append({
            "segment_id": segment_id,
            "membership": membership,
            "station_weighted": float(mesh.attributes[f"{STATION_PREFIX}{segment_id}"].data[face_index].value),
            "station_squared_weighted": float(mesh.attributes[f"{STATION_SQUARED_PREFIX}{segment_id}"].data[face_index].value),
        })
    segments.sort(key=lambda item: item["segment_id"])
    return {"pipe_ids": pipe_ids, "segments": segments}


# mesh: 构建 record_id→完整 Cutter Face facts 的 Python ledger。
def _build_cutter_ledger(mesh):
    attribute = mesh.attributes.get(CUTTER_RECORD_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
        raise RuntimeError("pre-Boolean Cutter 缺少 INT/FACE 记录号")
    ledger = {}
    for polygon in mesh.polygons:
        record_id = int(attribute.data[polygon.index].value)
        if record_id <= 0 or record_id in ledger:
            raise RuntimeError(f"pre-Boolean Cutter 记录号不唯一: {record_id}")
        ledger[record_id] = {
            "input_face_index": polygon.index,
            "vertex_indices": list(polygon.vertices),
            "coordinates": [list(_coordinate_key(mesh.vertices[index].co)) for index in polygon.vertices],
            **_cutter_face_facts(mesh, polygon.index),
        }
    return ledger


# mesh/ledger: 统计相交 Edge 上的整数记录号是否精确对应输入 Cutter Face。
def _audit_edge_records(mesh, ledger):
    boundary = mesh.attributes.get(FIXED_BOUNDARY_ATTRIBUTE)
    cutter_records = mesh.attributes.get(CUTTER_EDGE_RECORD_ATTRIBUTE)
    source_records = mesh.attributes.get(SOURCE_EDGE_RECORD_ATTRIBUTE)
    if boundary is None or cutter_records is None or source_records is None:
        raise RuntimeError("post-Boolean 缺少 Boundary 或 Edge record 属性")
    selected = []
    unknown = []
    zero = []
    witness = None
    identity_mismatches = []
    for edge in mesh.edges:
        if not bool(boundary.data[edge.index].value):
            continue
        cutter_record_id = int(cutter_records.data[edge.index].value)
        source_record_id = int(source_records.data[edge.index].value)
        row = {
            "output_edge_index": edge.index,
            "quantized_endpoint_key": [list(item) for item in _edge_key(mesh, edge)],
            "float64_endpoint_bits": [list(item) for item in _edge_bits_key(mesh, edge)],
            "cutter_record_id_after_boolean": cutter_record_id,
            "source_record_id_after_boolean": source_record_id,
            "candidate_input_cutter_record_ids": [cutter_record_id] if cutter_record_id in ledger else [],
            "cutter_ledger_facts": ledger.get(cutter_record_id),
        }
        selected.append(row)
        if cutter_record_id == 0:
            zero.append(row)
        elif cutter_record_id not in ledger:
            unknown.append(row)
        else:
            expected = ledger[cutter_record_id]
            oracle_pipe_ids = sorted(
                int(attribute.name.removeprefix(ORACLE_PIPE_PREFIX))
                for attribute in mesh.attributes
                if attribute.domain == "EDGE"
                and attribute.name.startswith(ORACLE_PIPE_PREFIX)
                and bool(attribute.data[edge.index].value)
            )
            oracle_segment_ids = sorted(
                int(attribute.name.removeprefix(ORACLE_SEGMENT_PREFIX))
                for attribute in mesh.attributes
                if attribute.domain == "EDGE"
                and attribute.name.startswith(ORACLE_SEGMENT_PREFIX)
                and float(attribute.data[edge.index].value) > 1.0e-6
            )
            expected_segment_ids = [item["segment_id"] for item in expected["segments"]]
            if oracle_pipe_ids != expected["pipe_ids"] or oracle_segment_ids != expected_segment_ids:
                identity_mismatches.append({
                    "output_edge_index": edge.index,
                    "endpoint_key": row["quantized_endpoint_key"],
                    "record_id": cutter_record_id,
                    "oracle_pipe_ids": oracle_pipe_ids,
                    "record_pipe_ids": expected["pipe_ids"],
                    "oracle_segment_ids": oracle_segment_ids,
                    "record_segment_ids": expected_segment_ids,
                })
        if _edge_key(mesh, edge) == WITNESS_ENDPOINTS:
            witness = row
            witness["oracle_pipe_ids"] = oracle_pipe_ids if cutter_record_id in ledger else []
            witness["oracle_segment_ids"] = oracle_segment_ids if cutter_record_id in ledger else []
            witness["record_matches_oracle"] = bool(
                cutter_record_id in ledger
                and oracle_pipe_ids == ledger[cutter_record_id]["pipe_ids"]
                and oracle_segment_ids == [
                    item["segment_id"] for item in ledger[cutter_record_id]["segments"]
                ]
            )
    return selected, {
        "selected_edge_record_count": len(selected),
        "known_cutter_record_count": len(selected) - len(unknown) - len(zero),
        "zero_cutter_record_count": len(zero),
        "unknown_cutter_record_count": len(unknown),
        "identity_mismatch_count": len(identity_mismatches),
        "first_zero_cutter_record": zero[0] if zero else None,
        "first_unknown_cutter_record": unknown[0] if unknown else None,
        "first_identity_mismatch": identity_mismatches[0] if identity_mismatches else None,
        "witness_pipe_5": witness,
    }


# 无参数；执行固定载体的 pre/post 对比。
def main():
    started_at = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=str(INPUT_BLEND))
    source_object = bpy.data.objects[SOURCE_OBJECT_NAME]
    modifier = next(item for item in source_object.modifiers if item.type == "NODES")
    node_group = modifier.node_group
    source_socket, cutter_socket = _install_input_carriers(node_group)
    cutter_mesh = _evaluate_input(source_object, node_group, cutter_socket)
    ledger = _build_cutter_ledger(cutter_mesh)
    ledger_started_at = time.perf_counter()
    ledger = _build_cutter_ledger(cutter_mesh)
    source_mesh = _evaluate_input(source_object, node_group, source_socket)
    if source_mesh.attributes.get(SOURCE_RECORD_ATTRIBUTE) is None:
        raise RuntimeError("pre-Boolean source 缺少 Face 记录号")
    boolean_node = node_group.nodes["Boolean Pro"]
    cutter_input_link = next(
        link for link in tuple(node_group.links)
        if link.to_node == boolean_node and link.to_socket.name == "Geometry B"
    )
    source_input_link = next(
        link for link in tuple(node_group.links)
        if link.to_node == boolean_node and link.to_socket.name == "Geometry"
    )
    cutter_named = node_group.nodes.new("GeometryNodeInputNamedAttribute")
    cutter_named.data_type = "INT"
    cutter_named.inputs["Name"].default_value = CUTTER_RECORD_ATTRIBUTE
    cutter_capture = node_group.nodes.new("GeometryNodeCaptureAttribute")
    cutter_capture.domain = "FACE"
    cutter_capture.capture_items.clear()
    cutter_item = cutter_capture.capture_items.new("INT", "HST Cutter Record Field")
    cutter_upstream_socket = cutter_input_link.from_socket
    node_group.links.remove(cutter_input_link)
    node_group.links.new(cutter_upstream_socket, cutter_capture.inputs["Geometry"])
    node_group.links.new(cutter_named.outputs["Attribute"], cutter_capture.inputs[cutter_item.name])
    node_group.links.new(cutter_capture.outputs["Geometry"], boolean_node.inputs["Geometry B"])
    source_named = node_group.nodes.new("GeometryNodeInputNamedAttribute")
    source_named.data_type = "INT"
    source_named.inputs["Name"].default_value = SOURCE_RECORD_ATTRIBUTE
    source_capture = node_group.nodes.new("GeometryNodeCaptureAttribute")
    source_capture.domain = "FACE"
    source_capture.capture_items.clear()
    source_item = source_capture.capture_items.new("INT", "HST Source Record Field")
    source_upstream_socket = source_input_link.from_socket
    node_group.links.remove(source_input_link)
    node_group.links.new(source_upstream_socket, source_capture.inputs["Geometry"])
    node_group.links.new(source_named.outputs["Attribute"], source_capture.inputs[source_item.name])
    node_group.links.new(source_capture.outputs["Geometry"], boolean_node.inputs["Geometry"])
    cutter_field = _expose_boolean_field(
        node_group,
        boolean_node,
        "HST Cutter Face Record",
        cutter_capture.outputs[cutter_item.name],
    )
    source_field = _expose_boolean_field(
        node_group,
        boolean_node,
        "HST Source Face Record",
        source_capture.outputs[source_item.name],
    )
    carrier_contract = _install_edge_exports(boolean_node, source_field, cutter_field)
    cutter_seconds = time.perf_counter() - ledger_started_at
    boolean_started_at = time.perf_counter()
    boolean_mesh = _evaluate_boolean(source_object)
    boolean_seconds = time.perf_counter() - boolean_started_at
    selected, audit = _audit_edge_records(boolean_mesh, ledger)
    compact_records = [
        {
            "output_edge_index": row["output_edge_index"],
            "quantized_endpoint_key": row["quantized_endpoint_key"],
            "float64_endpoint_bits": row["float64_endpoint_bits"],
            "cutter_record_id_after_boolean": row["cutter_record_id_after_boolean"],
            "source_record_id_after_boolean": row["source_record_id_after_boolean"],
            "record_pipe_ids": (
                row["cutter_ledger_facts"]["pipe_ids"]
                if row["cutter_ledger_facts"] is not None else []
            ),
            "record_segment_ids": (
                [item["segment_id"] for item in row["cutter_ledger_facts"]["segments"]]
                if row["cutter_ledger_facts"] is not None else []
            ),
        }
        for row in selected
    ]
    passed = (
        audit["zero_cutter_record_count"] == 0
        and audit["unknown_cutter_record_count"] == 0
        and audit["identity_mismatch_count"] == 0
    )
    result = {
        "schema_version": 1,
        "status": "PASS" if passed else "STOP",
        "stage": "FACE_RECORD_EDGE_EXPORT",
        "scope": {
            "input_blend": str(INPUT_BLEND),
            "blender_version": bpy.app.version_string,
            "prototype_only": True,
            "formal_entry_modified": False,
            "bridge_fill_run": False,
        },
        "carrier_contract": carrier_contract,
        "pre_boolean_cutter": {
            "face_count": len(cutter_mesh.polygons),
            "ledger_record_count": len(ledger),
            "record_min": min(ledger),
            "record_max": max(ledger),
            "multi_pipe_face_count": sum(len(item["pipe_ids"]) > 1 for item in ledger.values()),
            "multi_segment_face_count": sum(len(item["segments"]) > 1 for item in ledger.values()),
        },
        "post_boolean_edge_audit": audit,
        "edge_records": compact_records,
        "timings": {
            "pre_boolean_cutter_and_ledger_seconds": cutter_seconds,
            "boolean_evaluate_seconds": boolean_seconds,
            "total_seconds": time.perf_counter() - started_at,
        },
        "forbidden_recovery": {
            "nearest_or_bvh": False,
            "single_owner": False,
            "fixed_slots": False,
            "fixed_bitmask": False,
            "station_clamp": False,
            "fixture_name_or_edge_id_special_case": False,
        },
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[HST_FACE_RECORD_EDGE_EXPORT]" + json.dumps({
        "status": result["status"],
        "carrier_contract": carrier_contract,
        "pre_boolean_cutter": result["pre_boolean_cutter"],
        "post_boolean_edge_audit": audit,
        "timings": result["timings"],
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
