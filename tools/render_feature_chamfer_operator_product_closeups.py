# -*- coding: utf-8 -*-
"""渲染 Feature Chamfer Operator product 局部固定视角。"""

import os
from pathlib import Path

import bpy
from mathutils import Vector

output = bpy.data.objects["Extruded.002_FeatureChamfer"]
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not output
output.hide_render = False
camera_data = bpy.data.cameras.new("HST_Closeup_Camera")
camera = bpy.data.objects.new("HST_Closeup_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.show_object_outline = True
scene.render.resolution_x = 1400
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
base = Path(os.environ["HST_PRODUCT_CLOSEUP_DIR"])
views = [
    ("front_junction", Vector((0.7, -1.6, -0.2)), Vector((0.0, 0.0, -0.25)), 1.2),
    ("top_cylinder", Vector((1.2, -1.3, 1.2)), Vector((0.35, 0.0, 0.35)), 1.0),
]
for name, direction, target, scale in views:
    camera.location = target + direction
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale
    scene.render.filepath = str(base / f"feature_chamfer_operator_{name}.png")
    bpy.ops.render.render(write_still=True)