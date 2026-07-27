# -*- coding: utf-8 -*-
"""从包围盒中心渲染 Feature Chamfer 八方向产品视图。"""

import math
import os
from pathlib import Path

import bpy
from mathutils import Vector


output_name = os.environ.get("HST_PRODUCT_OBJECT_NAME")
candidates = [
    obj
    for obj in bpy.data.objects
    if obj.type == "MESH" and obj.name.endswith("_FeatureChamfer")
]
output = bpy.data.objects.get(output_name) if output_name else (
    candidates[0] if len(candidates) == 1 else None
)
if output is None:
    raise RuntimeError("Feature Chamfer product output missing or ambiguous")
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not output
output.hide_render = False
bounds = [output.matrix_world @ Vector(corner) for corner in output.bound_box]
center = sum(bounds, Vector()) / len(bounds)
size = max((point - center).length for point in bounds)
camera_data = bpy.data.cameras.new("HST_Turntable_Camera")
camera = bpy.data.objects.new("HST_Turntable_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
camera_data.type = "ORTHO"
camera_data.ortho_scale = size * 2.1
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.show_object_outline = True
scene.render.resolution_x = 1000
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
output.show_wire = bool(int(os.environ.get("HST_PRODUCT_SHOW_WIRE", "0")))
output.show_all_edges = output.show_wire
output_directory = Path(os.environ["HST_PRODUCT_TURNTABLE_DIR"])
output_directory.mkdir(parents=True, exist_ok=True)
for view_index in range(8):
    angle = math.tau * view_index / 8.0
    direction = Vector((math.cos(angle), math.sin(angle), 0.72)).normalized()
    camera.location = center + direction * size * 2.8
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(output_directory / f"view_{view_index:02d}.png")
    bpy.ops.render.render(write_still=True)
