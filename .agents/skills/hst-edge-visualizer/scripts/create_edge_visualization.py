# -*- coding: utf-8 -*-
"""为 HST diagnostics 中的 Edge 创建可手工判断的 Blender 可视化。"""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


# 从 argv 读取源 blend、diagnostics 与输出 blend 路径。
# 无参数；返回三个 Path。
def parse_arguments():
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected: source.blend diagnostics.json output.blend")
    return tuple(Path(argument).resolve() for argument in arguments)


# 创建带发光材质的粗 Curve，用于覆盖原始 Boundary Edge。
# name/endpoints/color/radius: 对象名、局部坐标端点、RGBA 与线宽；返回 Curve Object。
def create_edge_marker(name, endpoints, color, radius):
    curve_data = bpy.data.curves.new(f"{name}_Curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 2
    curve_data.bevel_depth = radius
    curve_data.bevel_resolution = 4
    spline = curve_data.splines.new(type="POLY")
    spline.points.add(1)
    for point, coordinate in zip(spline.points, endpoints):
        point.co = (*coordinate, 1.0)
    marker = bpy.data.objects.new(name, curve_data)
    material = bpy.data.materials.new(f"{name}_Material")
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Emission Color"].default_value = color
    principled.inputs["Emission Strength"].default_value = 2.0
    marker.data.materials.append(material)
    marker.show_in_front = True
    return marker


# 创建位于边中点附近的编号文字。
# label/location/color/size: 文本、局部坐标、RGBA 与字号；返回 Text Object。
def create_label(label, location, color, size):
    font_data = bpy.data.curves.new(f"HST_Residual_Label_{label}", type="FONT")
    font_data.body = label
    font_data.align_x = "CENTER"
    font_data.align_y = "CENTER"
    font_data.size = size
    font_data.extrude = size * 0.025
    label_object = bpy.data.objects.new(f"HST_Residual_Label_{label}", font_data)
    label_object.location = location
    material = bpy.data.materials.new(f"HST_Residual_Label_{label}_Material")
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Emission Color"].default_value = color
    principled.inputs["Emission Strength"].default_value = 1.5
    font_data.materials.append(material)
    label_object.show_in_front = True
    return label_object


# 载入诊断结果并生成三色边、编号和可继续检查的 blend。
# 无参数；无返回值。
def main():
    source_blend, diagnostics_path, output_blend = parse_arguments()
    bpy.ops.wm.open_mainfile(filepath=str(source_blend), load_ui=False, use_scripts=False)
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    repetition = diagnostics["repetitions"][0]
    edge_entries = repetition["topology_diagnostics"]["edge_endpoints"]
    edge_lengths = dict(
        zip(
            repetition["topology_diagnostics"]["edge_ids"],
            repetition["topology_diagnostics"]["edge_lengths"],
        )
    )
    source_object = bpy.data.objects[diagnostics["object_name"]]
    source_object.hide_set(False)
    source_object.hide_render = False
    source_object.display_type = "SOLID"
    source_object.color = (0.17, 0.19, 0.23, 1.0)
    source_matrix = source_object.matrix_world.copy()
    for scene_object in bpy.context.scene.objects:
        if scene_object != source_object:
            scene_object.hide_set(True)
    source_material = bpy.data.materials.new("HST_Residual_Source_Dark")
    source_material.diffuse_color = (0.055, 0.07, 0.09, 1.0)
    source_material.use_nodes = True
    source_principled = source_material.node_tree.nodes.get("Principled BSDF")
    source_principled.inputs["Base Color"].default_value = (0.055, 0.07, 0.09, 1.0)
    source_principled.inputs["Roughness"].default_value = 0.72
    source_object.data.materials.clear()
    source_object.data.materials.append(source_material)
    collection = bpy.data.collections.new("HST_Residual_Edge_Visualization")
    bpy.context.scene.collection.children.link(collection)
    colors = (
        (1.0, 0.08, 0.03, 1.0),
        (0.08, 1.0, 0.08, 1.0),
        (0.05, 0.3, 1.0, 1.0),
    )
    ordered_entries = sorted(
        edge_entries,
        key=lambda entry: edge_lengths[entry["edge_id"]],
        reverse=True,
    )
    radius = float(diagnostics["radius"])
    for index, (entry, color) in enumerate(zip(ordered_entries, colors), start=1):
        surface_offset = Vector((0.0, 0.0, max(radius * 0.3, 0.008)))
        endpoints = [Vector(point) + surface_offset for point in entry["endpoints"]]
        marker = create_edge_marker(
            f"HST_Residual_Edge_{index}",
            endpoints,
            color,
            max(radius * 0.14, 0.0035),
        )
        marker.matrix_world = source_matrix
        collection.objects.link(marker)
        midpoint = (endpoints[0] + endpoints[1]) * 0.5
        label_offsets = (
            Vector((0.0, 0.045, 0.012)),
            Vector((0.0, -0.045, 0.012)),
            Vector((0.025, 0.055, 0.012)),
        )
        label = create_label(
            str(index),
            midpoint + label_offsets[index - 1],
            color,
            max(radius * 1.25, 0.038),
        )
        label.matrix_world = source_matrix
        collection.objects.link(label)
    bpy.context.view_layer.update()
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), check_existing=False, compress=True)


if __name__ == "__main__":
    main()
