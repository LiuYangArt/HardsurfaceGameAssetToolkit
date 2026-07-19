# -*- coding: utf-8 -*-
"""输出 Feature Chamfer GN fixture 的 cutter 与 Boolean provenance 统计。"""

import json
import os
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "feature-chamfer-gn-junction-safe.blend"
PRESET_PATH = REPO_ROOT / "preset_files" / "Presets.blend"
NODE_GROUP_NAME = "GN_HSTFeatureChamferSDFPreview"
ORIGINAL_FACE_ATTRIBUTE = "hst_feature_chamfer_original_face"
GROOVE_FACE_ATTRIBUTE = "hst_feature_chamfer_groove_face"
BOUNDARY_EDGE_ATTRIBUTE = "hst_feature_chamfer_boundary_edge"


# 返回 Mesh 的 manifold 风险计数。
# mesh: evaluated Blender Mesh data。
def _risk_counts(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    result = {
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    return result


# 评估 source 的当前 GN modifier 并返回 Mesh data。
# source: 带 GN modifier 的 Mesh Object。
def _evaluated_mesh(source):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph), depsgraph=depsgraph)


# 直接读取指定 Show Cutter 值对应的 evaluated Mesh，避免同一 depsgraph 的缓存干扰。
# source/modifier/identifier/value: Preview Object、modifier、socket identifier 与模式值。
def _evaluated_mesh_for_mode(source, modifier, identifier, value):
    modifier[identifier] = value
    source.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph), depsgraph=depsgraph)


bpy.ops.wm.open_mainfile(filepath=str(FIXTURE_PATH))
source = bpy.data.objects["Extruded.002"]
old_modifier = source.modifiers.get("GeometryNodes")
if old_modifier is not None:
    source.modifiers.remove(old_modifier)
for existing_name in (NODE_GROUP_NAME, "pipecut"):
    existing_group = bpy.data.node_groups.get(existing_name)
    if existing_group is not None:
        bpy.data.node_groups.remove(existing_group)
bpy.ops.wm.append(
    filepath=str(PRESET_PATH),
    directory=str(PRESET_PATH / "NodeTree"),
    filename=NODE_GROUP_NAME,
)
node_group = bpy.data.node_groups[NODE_GROUP_NAME]
modifier = source.modifiers.new("HST Feature Chamfer GN Preview", "NODES")
modifier.node_group = node_group
inputs = {
    item.name: item.identifier
    for item in node_group.interface.items_tree
    if item.item_type == "SOCKET" and item.in_out == "INPUT"
}
modifier[inputs["Radius"]] = 0.03
modifier[inputs["Sample Length"]] = 0.01
modifier[inputs["Voxel Size"]] = 0.0075
modifier[inputs["Adaptivity"]] = 0.05
print("[HST_FEATURE_CHAMFER_GN_ASSET]" + json.dumps({
    "name": node_group.name,
    "version": node_group.get("hst_feature_chamfer_asset_version"),
    "source": node_group.get("hst_feature_chamfer_asset_source"),
}, separators=(",", ":")))

cutter_mesh = _evaluated_mesh_for_mode(source, modifier, inputs["Show Cutter"], True)
cutter_stats = {
    "vertices": len(cutter_mesh.vertices),
    "edges": len(cutter_mesh.edges),
    "faces": len(cutter_mesh.polygons),
    **_risk_counts(cutter_mesh),
}
bpy.data.meshes.remove(cutter_mesh)

boolean_mesh = _evaluated_mesh_for_mode(source, modifier, inputs["Show Cutter"], False)
attribute = boolean_mesh.attributes.get(GROOVE_FACE_ATTRIBUTE)
boundary_attribute = boolean_mesh.attributes.get(BOUNDARY_EDGE_ATTRIBUTE)
original_faces = 0
groove_faces = 0
if attribute is not None and attribute.domain == "FACE":
    groove_faces = sum(1 for value in attribute.data if bool(value.value))
    original_faces = len(boolean_mesh.polygons) - groove_faces
boolean_stats = {
    "vertices": len(boolean_mesh.vertices),
    "edges": len(boolean_mesh.edges),
    "faces": len(boolean_mesh.polygons),
    "groove_face_attribute": attribute is not None and attribute.domain == "FACE",
    "boundary_edge_attribute": boundary_attribute is not None and boundary_attribute.domain == "EDGE",
    "boundary_edge_count": (
        sum(1 for value in boundary_attribute.data if bool(value.value))
        if boundary_attribute is not None
        else 0
    ),
    "original_faces": original_faces,
    "groove_faces": groove_faces,
    "groove_selection_nonempty": attribute is not None and groove_faces > 0,
    **_risk_counts(boolean_mesh),
}
bpy.data.meshes.remove(boolean_mesh)

report = {
    "blender_version": bpy.app.version_string,
    "source": source.name,
    "cutter": cutter_stats,
    "boolean": boolean_stats,
    "go": (
        cutter_stats["non_manifold"] == 0
        and boolean_stats["groove_face_attribute"]
        and boolean_stats["groove_faces"] > 0
        and boolean_stats["groove_selection_nonempty"]
        and boolean_stats["boundary_edge_count"] > 0
        and False  # rail owner provenance 仍未实现，禁止误报 Go。
    ),
    "rail_owner_provenance": "unavailable",
}
output_path = Path(os.environ.get("HST_FEATURE_CHAMFER_PROBE", REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_gn_probe.json"))
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("[HST_FEATURE_CHAMFER_GN_PROBE]" + json.dumps(report, separators=(",", ":")))
