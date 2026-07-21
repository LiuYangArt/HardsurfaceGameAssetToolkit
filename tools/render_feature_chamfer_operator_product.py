# -*- coding: utf-8 -*-
"""渲染 Feature Chamfer Operator product artifact 固定视角。"""

import os
from pathlib import Path

import bpy
from mathutils import Vector

output = bpy.data.objects.get("Extruded.002_FeatureChamfer")
if output is None:
    raise RuntimeError("Feature Chamfer output missing")
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not output
output.hide_render = False
camera_data = bpy.data.cameras.new("HST_Product_Camera")
camera = bpy.data.objects.new("HST_Product_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
bounds = [output.matrix_world @ Vector(corner) for corner in output.bound_box]
center = sum(bounds, Vector()) / len(bounds)
size = max((point - center).length for point in bounds)
camera.location = center + Vector((size * 1.35, -size * 1.65, size * 1.15))
direction = center - camera.location
camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
camera_data.type = "ORTHO"
camera_data.ortho_scale = size * 2.3
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.render.resolution_x = 1600
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(Path(os.environ["HST_PRODUCT_RENDER_PATH"]))
bpy.ops.render.render(write_still=True)