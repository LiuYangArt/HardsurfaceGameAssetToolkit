# -*- coding: utf-8 -*-
"""验证 fixture Boolean Pro 的 selection outputs 能否保存为 evaluated Face attributes。"""

import json
import os
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "feature-chamfer-gn-junction-safe.blend"


# 把 Boolean Pro 的 Face selection 输出存成 Named Attribute。
# node_group: fixture 的 pipecut GeometryNodeTree；output_name/attribute_name: 输出和属性名称。
def _store_boolean_output(node_group, output_name, attribute_name, domain="FACE"):
    boolean_node = node_group.nodes["Boolean Pro"]
    group_output = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupOutput")
    geometry_link = next(
        link
        for link in node_group.links
        if link.to_node == group_output and link.to_socket.name == "Geometry"
    )
    node_group.links.remove(geometry_link)
    store_attribute = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_attribute.data_type = "BOOLEAN"
    store_attribute.domain = domain
    store_attribute.inputs["Name"].default_value = attribute_name
    node_group.links.new(boolean_node.outputs["Geometry"], store_attribute.inputs["Geometry"])
    node_group.links.new(boolean_node.outputs[output_name], store_attribute.inputs["Value"])
    node_group.links.new(store_attribute.outputs["Geometry"], group_output.inputs["Geometry"])


# 在 Boolean Pro 前给全部 source Faces 写 true，验证结果是否保留原面来源。
# node_group/attribute_name: fixture pipecut 与测试属性名。
def _store_source_faces_before_boolean(node_group, attribute_name):
    boolean_node = node_group.nodes["Boolean Pro"]
    source_link = next(
        link
        for link in node_group.links
        if link.to_node == boolean_node and link.to_socket.name == "Geometry"
    )
    source_socket = source_link.from_socket
    node_group.links.remove(source_link)
    store_attribute = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_attribute.data_type = "BOOLEAN"
    store_attribute.domain = "FACE"
    store_attribute.inputs["Name"].default_value = attribute_name
    store_attribute.inputs["Value"].default_value = True
    node_group.links.new(source_socket, store_attribute.inputs["Geometry"])
    node_group.links.new(store_attribute.outputs["Geometry"], boolean_node.inputs["Geometry"])


# 返回 evaluated Mesh 中指定 FACE Boolean attribute 的统计。
# source_object: fixture source；attribute_name: 待读取属性。
def _evaluate_attribute(source_object, attribute_name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    mesh = bpy.data.meshes.new_from_object(source_object.evaluated_get(depsgraph), depsgraph=depsgraph)
    attribute = mesh.attributes.get(attribute_name)
    result = {
        "face_count": len(mesh.polygons),
        "attribute_present": attribute is not None,
        "domain": attribute.domain if attribute is not None else None,
        "selected_count": (
            sum(1 for value in attribute.data if bool(value.value)) if attribute is not None else 0
        ),
    }
    bpy.data.meshes.remove(mesh)
    return result


# 统计删除 loose Vert/Edge 后的真实 Surface Boundary。
# source_object: fixture source。
def _clean_surface_risks(source_object):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    mesh = bpy.data.meshes.new_from_object(source_object.evaluated_get(depsgraph), depsgraph=depsgraph)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    loose_edges = [edge for edge in bm.edges if not edge.link_faces]
    loose_vertices = [vertex for vertex in bm.verts if not vertex.link_edges]
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
    result = {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
    }
    bm.free()
    bpy.data.meshes.remove(mesh)
    return result


report = {"blender_version": bpy.app.version_string, "outputs": {}}
bpy.ops.wm.open_mainfile(filepath=str(FIXTURE_PATH))
source = bpy.data.objects["Extruded.002"]
source_attribute_name = "hst_probe_original_face"
_store_source_faces_before_boolean(source.modifiers[0].node_group, source_attribute_name)
report["original_face_propagation"] = _evaluate_attribute(source, source_attribute_name)
report["surface_after_loose_cleanup"] = _clean_surface_risks(source)
for output_name, domains in (
    ("New Faces", ("FACE",)),
    ("Slice Faces", ("FACE",)),
    ("Boundary Edges", ("FACE", "EDGE")),
):
    for domain in domains:
        bpy.ops.wm.open_mainfile(filepath=str(FIXTURE_PATH))
        source = bpy.data.objects["Extruded.002"]
        key = output_name if domain == "FACE" else f"{output_name} ({domain})"
        attribute_name = "hst_probe_" + key.lower().replace(" ", "_").replace("(", "").replace(")", "")
        _store_boolean_output(source.modifiers[0].node_group, output_name, attribute_name, domain)
        report["outputs"][key] = _evaluate_attribute(source, attribute_name)

print("[HST_BOOLEAN_PRO_PROVENANCE]" + json.dumps(report, separators=(",", ":")))
