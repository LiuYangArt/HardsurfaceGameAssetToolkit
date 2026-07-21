# -*- coding: utf-8 -*-
"""渲染 Feature Chamfer 缺陷 terminal 的固定验收近景。"""

import os
from pathlib import Path

import bpy
from mathutils import Vector


OUTPUT = bpy.data.objects["Extruded.002_FeatureChamfer"]
OUTPUT_PATH = Path(os.environ["HST_VERIFIED_CLOSEUP_PATH"])
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not OUTPUT
OUTPUT.hide_render = False
OUTPUT.show_wire = True
OUTPUT.show_all_edges = True

camera_data = bpy.data.cameras.new("HST_Verified_Closeup_Camera")
camera = bpy.data.objects.new("HST_Verified_Closeup_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
target = Vector((0.616, 0.20, -0.64))
camera.location = target + Vector((-1.2, -1.6, 0.16))
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
camera_data.type = "ORTHO"
camera_data.ortho_scale = 1.65

scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = False
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.show_specular_highlight = False
scene.render.resolution_x = 900
scene.render.resolution_y = 1400
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(OUTPUT_PATH)
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.render.render(write_still=True)
