# -*- coding: utf-8 -*-
"""从已验证 fixture 迁移 Feature Chamfer GN 资产，保留 Boolean Pro 主链。"""

import os
from pathlib import Path

import bpy


NODE_GROUP_NAME = "GN_HSTFeatureChamferSDFPreview"
SOURCE_NODE_GROUP_NAME = "pipecut"
ASSET_VERSION_PROPERTY = "hst_feature_chamfer_asset_version"
ASSET_SOURCE_PROPERTY = "hst_feature_chamfer_asset_source"
ASSET_VERSION = 2
GROOVE_FACE_ATTRIBUTE = "hst_feature_chamfer_groove_face"
BOUNDARY_EDGE_ATTRIBUTE = "hst_feature_chamfer_boundary_edge"
DEPENDENCY_PREFIX = "HST Feature Chamfer :: "
FIXTURE_DEPENDENCY_NAMES = {
    "3 Plane Intersection",
    "Boolean Pro",
    "Boolean Solver Select",
    "Boundary Edge",
    "Curve Point Angle",
    "Float Boolean Edges",
    "Is Mesh Manifold",
    "MultiObjectInput",
    "Offset Face Corners",
    "Offset Mesh",
    "Opposite Face Corners",
    "Sharp Edges",
    "Vector Plane Intersection",
    "View Normals",
}


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


# 清空 fixture 只有 Geometry I/O 的 interface，改为正式公开参数。
# node_group: 从 fixture 载入的 pipecut GeometryNodeTree。
def _rebuild_interface(node_group):
    node_group.interface.clear()
    _new_socket(node_group, "Geometry", "INPUT", "NodeSocketGeometry")
    _new_socket(node_group, "Radius", "INPUT", "NodeSocketFloat", 0.03, 0.00001)
    _new_socket(node_group, "Sample Length", "INPUT", "NodeSocketFloat", 0.01, 0.00001)
    _new_socket(node_group, "Voxel Size", "INPUT", "NodeSocketFloat", 0.0075, 0.00001)
    _new_socket(node_group, "Adaptivity", "INPUT", "NodeSocketFloat", 0.05, 0.0)
    _new_socket(node_group, "Show Cutter", "INPUT", "NodeSocketBool", False)
    _new_socket(node_group, "Geometry", "OUTPUT", "NodeSocketGeometry")


# 在不改变 fixture SDF/Boolean Pro 主链的前提下，公开参数并保存诊断 selection。
# node_group: 从 fixture 迁移的 pipecut。
def _configure_node_group(node_group):
    nodes = node_group.nodes
    links = node_group.links
    group_input = next(node for node in nodes if node.bl_idname == "NodeGroupInput")
    group_output = next(node for node in nodes if node.bl_idname == "NodeGroupOutput")
    boolean_node = nodes["Boolean Pro"]
    sample_node = nodes["HST Pipe Samples"]
    sdf_node = nodes["HST Pipe SDF"]
    grid_node = nodes["HST Junction-safe Pipe"]

    source_geometry_targets = [
        link.to_socket
        for link in links
        if link.from_node == group_input and link.from_socket.name == "Geometry"
    ]
    _rebuild_interface(node_group)
    for target_socket in source_geometry_targets:
        links.new(group_input.outputs["Geometry"], target_socket)

    links.new(group_input.outputs["Sample Length"], sample_node.inputs["Length"])
    links.new(group_input.outputs["Radius"], sdf_node.inputs["Radius"])
    links.new(group_input.outputs["Voxel Size"], sdf_node.inputs["Voxel Size"])
    links.new(group_input.outputs["Adaptivity"], grid_node.inputs["Adaptivity"])

    store_groove = nodes.new("GeometryNodeStoreNamedAttribute")
    store_groove.name = "HST Groove Face Provenance"
    store_groove.data_type = "BOOLEAN"
    store_groove.domain = "FACE"
    store_groove.inputs["Name"].default_value = GROOVE_FACE_ATTRIBUTE
    store_boundary = nodes.new("GeometryNodeStoreNamedAttribute")
    store_boundary.name = "HST Boolean Boundary Evidence"
    store_boundary.data_type = "BOOLEAN"
    store_boundary.domain = "EDGE"
    store_boundary.inputs["Name"].default_value = BOUNDARY_EDGE_ATTRIBUTE
    preview_switch = nodes.new("GeometryNodeSwitch")
    preview_switch.name = "HST Boolean Result or Cutter"
    preview_switch.input_type = "GEOMETRY"

    links.new(boolean_node.outputs["Geometry"], store_groove.inputs["Geometry"])
    links.new(boolean_node.outputs["New Faces"], store_groove.inputs["Value"])
    links.new(store_groove.outputs["Geometry"], store_boundary.inputs["Geometry"])
    links.new(boolean_node.outputs["Boundary Edges"], store_boundary.inputs["Value"])
    links.new(group_input.outputs["Show Cutter"], preview_switch.inputs["Switch"])
    links.new(store_boundary.outputs["Geometry"], preview_switch.inputs["False"])
    links.new(grid_node.outputs["Mesh"], preview_switch.inputs["True"])
    links.new(preview_switch.outputs["Output"], group_output.inputs["Geometry"])

    node_group.name = NODE_GROUP_NAME
    node_group.use_fake_user = True
    node_group[ASSET_VERSION_PROPERTY] = ASSET_VERSION
    node_group[ASSET_SOURCE_PROPERTY] = "tests/fixtures/feature-chamfer-gn-junction-safe.blend:pipecut"


# 给 fixture 迁入的 nested Node Groups 加受控前缀，避免覆盖用户同名资产。
# root_group: 已配置的发布根 Node Group。
def _namespace_dependencies(root_group):
    pending = [root_group]
    dependencies = set()
    while pending:
        node_group = pending.pop()
        for node in node_group.nodes:
            dependency = getattr(node, "node_tree", None)
            if dependency is None or dependency == root_group or dependency in dependencies:
                continue
            dependencies.add(dependency)
            pending.append(dependency)
    for dependency in dependencies:
        base_name = dependency.name
        if base_name.startswith(DEPENDENCY_PREFIX):
            base_name = base_name.removeprefix(DEPENDENCY_PREFIX)
        if base_name.endswith(".001"):
            base_name = base_name[:-4]
        dependency.name = DEPENDENCY_PREFIX + base_name
        dependency.use_fake_user = True
        dependency[ASSET_SOURCE_PROPERTY] = (
            "tests/fixtures/feature-chamfer-gn-junction-safe.blend:pipecut"
        )


# 从 fixture append 已验证 pipecut，依赖的 Boolean Pro/nested groups 由 Blender 一并迁移。
# fixture_path/preset_path: 输入 fixture 与目标 Presets.blend。
def build_asset(fixture_path, preset_path):
    bpy.ops.wm.open_mainfile(filepath=str(preset_path))
    for existing in list(bpy.data.node_groups):
        base_name = existing.name.removeprefix(DEPENDENCY_PREFIX)
        if base_name.endswith(".001"):
            base_name = base_name[:-4]
        owned_dependency = existing.name.startswith(DEPENDENCY_PREFIX) and existing.get(
            ASSET_SOURCE_PROPERTY
        ) == "tests/fixtures/feature-chamfer-gn-junction-safe.blend:pipecut"
        legacy_migration_dependency = base_name in FIXTURE_DEPENDENCY_NAMES
        if owned_dependency or legacy_migration_dependency:
            bpy.data.node_groups.remove(existing)
    for node_group_name in (NODE_GROUP_NAME, SOURCE_NODE_GROUP_NAME):
        existing = bpy.data.node_groups.get(node_group_name)
        if existing is not None:
            bpy.data.node_groups.remove(existing)
    bpy.ops.wm.append(
        filepath=str(fixture_path),
        directory=str(fixture_path / "NodeTree"),
        filename=SOURCE_NODE_GROUP_NAME,
    )
    node_group = bpy.data.node_groups.get(SOURCE_NODE_GROUP_NAME)
    if node_group is None:
        raise RuntimeError(f"Fixture missing NodeTree: {SOURCE_NODE_GROUP_NAME}")
    _configure_node_group(node_group)
    _namespace_dependencies(node_group)
    bpy.ops.wm.save_as_mainfile(filepath=str(preset_path))


repo_root = Path(os.environ.get("HST_ADDON_ROOT", Path(__file__).resolve().parent.parent))
build_asset(
    repo_root / "tests" / "fixtures" / "feature-chamfer-gn-junction-safe.blend",
    repo_root / "preset_files" / "Presets.blend",
)
