import bpy

import json
import os
from pathlib import Path


# 收集当前 .blend 中 Mesh 对象的结构与 Feature Chamfer 状态。
# 参数 output_path: JSON 诊断文件的绝对路径。
def write_scene_probe(output_path):
    records = []
    for scene_object in bpy.context.scene.objects:
        if scene_object.type != "MESH":
            continue
        mesh = scene_object.data
        sharp_edges = sum(
            1
            for edge in mesh.edges
            if edge.use_edge_sharp
            or (
                mesh.attributes.get("sharp_edge") is not None
                and mesh.attributes["sharp_edge"].domain == "EDGE"
                and bool(mesh.attributes["sharp_edge"].data[edge.index].value)
            )
        )
        records.append(
            {
                "name": scene_object.name,
                "selected": scene_object.select_get(),
                "active": bpy.context.view_layer.objects.active == scene_object,
                "visible": scene_object.visible_get(),
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "faces": len(mesh.polygons),
                "sharp_edges": sharp_edges,
                "dimensions": [round(value, 6) for value in scene_object.dimensions],
                "scale": [round(value, 6) for value in scene_object.scale],
                "modifiers": [
                    {
                        "name": modifier.name,
                        "type": modifier.type,
                        "node_group": getattr(getattr(modifier, "node_group", None), "name", None),
                    }
                    for modifier in scene_object.modifiers
                ],
                "custom_properties": {
                    key: scene_object[key]
                    for key in scene_object.keys()
                    if key != "_RNA_UI" and isinstance(scene_object[key], (str, int, float, bool))
                },
            }
        )
    payload = {
        "blend_file": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "objects": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HST_USER_BLEND_PROBE={output_path}")


write_scene_probe(Path(os.environ["HST_USER_BLEND_PROBE_PATH"]))
