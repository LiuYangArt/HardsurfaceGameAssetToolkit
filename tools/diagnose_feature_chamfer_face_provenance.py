# -*- coding: utf-8 -*-
"""导出 Feature Chamfer 新面 provenance 的可见诊断材质。"""

import os
from pathlib import Path

import bpy


output_name = os.environ.get(
    "HST_PRODUCT_OBJECT_NAME",
    "Extruded.002_FeatureChamfer",
)
output = bpy.data.objects.get(output_name)
if output is None or output.type != "MESH":
    raise RuntimeError(f"Feature Chamfer output missing: {output_name}")
attribute = output.data.attributes.get("hst_feature_chamfer_face")
if attribute is None:
    raise RuntimeError("Feature Chamfer face attribute missing")
source_material = bpy.data.materials.new("HST_Source")
source_material.diffuse_color = (0.18, 0.18, 0.18, 1.0)
chamfer_material = bpy.data.materials.new("HST_Chamfer")
chamfer_material.diffuse_color = (0.8, 0.03, 0.03, 1.0)
output.data.materials.clear()
output.data.materials.append(source_material)
output.data.materials.append(chamfer_material)
for polygon, value in zip(output.data.polygons, attribute.data, strict=True):
    polygon.material_index = 1 if value.value else 0
for modifier in output.modifiers:
    if modifier.type == "DATA_TRANSFER":
        modifier.show_viewport = False
        modifier.show_render = False
diagnostic_path = Path(os.environ["HST_PROVENANCE_BLEND_PATH"])
bpy.ops.wm.save_as_mainfile(filepath=str(diagnostic_path))
