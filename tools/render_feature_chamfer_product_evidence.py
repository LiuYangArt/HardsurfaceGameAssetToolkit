# -*- coding: utf-8 -*-
"""渲染 Feature Chamfer 产品 overview 与固定 wireframe 近景。"""

import os
from pathlib import Path

import bpy
from mathutils import Vector


output_name = os.environ.get("HST_PRODUCT_OBJECT_NAME")
output = bpy.data.objects.get(output_name) if output_name else None
if output is None and output_name is None:
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.endswith("_FeatureChamfer")
    ]
    output = candidates[0] if len(candidates) == 1 else None
if output is None:
    raise RuntimeError(
        f"Feature Chamfer output missing or ambiguous: requested={output_name!r}"
    )
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not output
output.hide_render = False
for modifier in output.modifiers:
    if modifier.type == "DATA_TRANSFER":
        modifier.show_viewport = False
        modifier.show_render = False

camera_data = bpy.data.cameras.new("HST_Product_Evidence_Camera")
camera = bpy.data.objects.new("HST_Product_Evidence_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
bounds = [output.matrix_world @ Vector(corner) for corner in output.bound_box]
center = sum(bounds, Vector()) / len(bounds)
extent = Vector((
    max(point.x for point in bounds) - min(point.x for point in bounds),
    max(point.y for point in bounds) - min(point.y for point in bounds),
    max(point.z for point in bounds) - min(point.z for point in bounds),
))
size = max(extent)

scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.show_object_outline = True
scene.display.shading.show_specular_highlight = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

output_directory = Path(os.environ["HST_PRODUCT_EVIDENCE_DIR"])
output_directory.mkdir(parents=True, exist_ok=True)
views = (
    ("overview", Vector((1.35, -1.65, 1.15)), center, size * 1.55, False),
    (
        "closeup_wire",
        Vector((1.10, -1.30, 0.82)),
        center + Vector((extent.x * 0.18, -extent.y * 0.10, extent.z * 0.12)),
        size * 0.78,
        True,
    ),
)
for name, direction, target, scale, show_wire in views:
    camera.location = target + direction.normalized() * size * 1.8
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(scale, 1.0e-4)
    output.show_wire = show_wire
    output.show_all_edges = show_wire
    scene.render.filepath = str(output_directory / f"final_{name}.png")
    bpy.ops.render.render(write_still=True)
