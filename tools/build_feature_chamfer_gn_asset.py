# -*- coding: utf-8 -*-
"""在 Presets.blend 中构建最小化 Feature Chamfer SDF Preview Node Group。"""

import bpy


NODE_GROUP_NAME = "GN_HSTFeatureChamferSDFPreview"
ASSET_VERSION_PROPERTY = "hst_feature_chamfer_asset_version"
ASSET_VERSION = 1
ORIGINAL_FACE_ATTRIBUTE = "hst_feature_chamfer_original_face"


# 创建一个 interface socket 并设置默认值与限制。
# node_group: 目标 GeometryNodeTree；name/in_out/socket_type: socket 描述；default/minimum: 可选数值约束。
def _new_socket(node_group, name, in_out, socket_type, default=None, minimum=None):
    socket = node_group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )
    if default is not None:
        socket.default_value = default
    if minimum is not None:
        socket.min_value = minimum
    return socket


# 使用 Blender 原生 nodes 构建 SDF cutter 与 Boolean/Cutter preview switch。
# 无参数；返回新 GeometryNodeTree。
def build_node_group():
    existing = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if existing is not None:
        bpy.data.node_groups.remove(existing)
    node_group = bpy.data.node_groups.new(NODE_GROUP_NAME, "GeometryNodeTree")
    node_group.use_fake_user = True
    node_group[ASSET_VERSION_PROPERTY] = ASSET_VERSION

    _new_socket(node_group, "Geometry", "INPUT", "NodeSocketGeometry")
    _new_socket(node_group, "Radius", "INPUT", "NodeSocketFloat", 0.03, 0.00001)
    _new_socket(node_group, "Sample Length", "INPUT", "NodeSocketFloat", 0.01, 0.00001)
    _new_socket(node_group, "Voxel Size", "INPUT", "NodeSocketFloat", 0.0075, 0.00001)
    _new_socket(node_group, "Adaptivity", "INPUT", "NodeSocketFloat", 0.05, 0.0)
    _new_socket(node_group, "Show Cutter", "INPUT", "NodeSocketBool", False)
    _new_socket(node_group, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nodes = node_group.nodes
    links = node_group.links
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    named_attribute = nodes.new("GeometryNodeInputNamedAttribute")
    named_attribute.data_type = "BOOLEAN"
    named_attribute.inputs["Name"].default_value = "sharp_edge"
    mesh_to_curve = nodes.new("GeometryNodeMeshToCurve")
    curve_to_points = nodes.new("GeometryNodeCurveToPoints")
    curve_to_points.mode = "LENGTH"
    points_to_sdf = nodes.new("GeometryNodePointsToSDFGrid")
    grid_to_mesh = nodes.new("GeometryNodeGridToMesh")
    grid_to_mesh.inputs["Threshold"].default_value = 0.0
    store_original_face = nodes.new("GeometryNodeStoreNamedAttribute")
    store_original_face.data_type = "BOOLEAN"
    store_original_face.domain = "FACE"
    store_original_face.inputs["Name"].default_value = ORIGINAL_FACE_ATTRIBUTE
    store_original_face.inputs["Value"].default_value = True
    mesh_boolean = nodes.new("GeometryNodeMeshBoolean")
    mesh_boolean.operation = "DIFFERENCE"
    preview_switch = nodes.new("GeometryNodeSwitch")
    preview_switch.input_type = "GEOMETRY"

    links.new(group_input.outputs["Geometry"], mesh_to_curve.inputs["Mesh"])
    links.new(named_attribute.outputs["Attribute"], mesh_to_curve.inputs["Selection"])
    links.new(mesh_to_curve.outputs["Curve"], curve_to_points.inputs["Curve"])
    links.new(group_input.outputs["Sample Length"], curve_to_points.inputs["Length"])
    links.new(curve_to_points.outputs["Points"], points_to_sdf.inputs["Points"])
    links.new(group_input.outputs["Radius"], points_to_sdf.inputs["Radius"])
    links.new(group_input.outputs["Voxel Size"], points_to_sdf.inputs["Voxel Size"])
    links.new(points_to_sdf.outputs["SDF Grid"], grid_to_mesh.inputs["Grid"])
    links.new(group_input.outputs["Adaptivity"], grid_to_mesh.inputs["Adaptivity"])
    links.new(group_input.outputs["Geometry"], store_original_face.inputs["Geometry"])
    links.new(store_original_face.outputs["Geometry"], mesh_boolean.inputs["Mesh 1"])
    links.new(grid_to_mesh.outputs["Mesh"], mesh_boolean.inputs["Mesh 2"])
    links.new(group_input.outputs["Show Cutter"], preview_switch.inputs["Switch"])
    links.new(mesh_boolean.outputs["Mesh"], preview_switch.inputs["False"])
    links.new(grid_to_mesh.outputs["Mesh"], preview_switch.inputs["True"])
    links.new(preview_switch.outputs["Output"], group_output.inputs["Geometry"])
    return node_group


build_node_group()
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
