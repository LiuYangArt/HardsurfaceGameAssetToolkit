# -*- coding: utf-8 -*-
"""渲染 Feature Chamfer topology 诊断的固定 wireframe 视角。"""

import json
import os
from pathlib import Path

import bpy
from mathutils import Vector


OUTPUT = bpy.data.objects[
    os.environ.get("HST_TOPOLOGY_DIAGNOSTIC_OBJECT", "Extruded.002_FeatureChamfer")
]
OUTPUT_PATH = Path(os.environ["HST_TOPOLOGY_DIAGNOSTIC_RENDER"])
for obj in bpy.context.scene.objects:
    obj.hide_render = obj is not OUTPUT
OUTPUT.hide_render = False
for modifier in OUTPUT.modifiers:
    if modifier.type == "DATA_TRANSFER":
        modifier.show_viewport = False
        modifier.show_render = False

camera_data = bpy.data.cameras.new("HST_Topology_Diagnostic_Camera")
camera = bpy.data.objects.new("HST_Topology_Diagnostic_Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.show_object_outline = True
scene.display.shading.show_specular_highlight = False
scene.render.resolution_x = 1400
scene.render.resolution_y = 1400
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
OUTPUT.show_wire = True
OUTPUT.show_all_edges = True
OUTPUT.display_type = "SOLID"

views = [
    {
        "name": "right_lower_overview",
        "target": Vector((0.616, 0.20, -1.05)),
        "direction": Vector((1.10, -1.35, 0.32)),
        "scale": 1.55,
    },
    {
        "name": "right_lower_terminal",
        "target": Vector((0.616, 0.20, -1.27)),
        "direction": Vector((1.10, -1.45, 0.18)),
        "scale": 0.58,
    },
    {
        "name": "right_lower_side",
        "target": Vector((0.616, 0.20, -1.18)),
        "direction": Vector((1.50, -0.20, 0.06)),
        "scale": 0.72,
    },
]
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
rendered = []
for view in views:
    camera.location = view["target"] + view["direction"]
    camera.rotation_euler = (
        view["target"] - camera.location
    ).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = view["scale"]
    render_path = OUTPUT_PATH.with_name(
        f"{OUTPUT_PATH.stem}_{view['name']}{OUTPUT_PATH.suffix}"
    )
    scene.render.filepath = str(render_path)
    bpy.ops.render.render(write_still=True)
    rendered.append(str(render_path))
print("HST_TOPOLOGY_DIAGNOSTIC_RENDERS=" + json.dumps(rendered, ensure_ascii=False))
