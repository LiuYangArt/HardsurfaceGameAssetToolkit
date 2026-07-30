import colorsys
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


# 把捕获的每组真实左右链生成为编号 Curve 与可检查 Blend。
# 命令行参数: fixture、捕获 JSON、输出 Blend 与 manifest 路径。
def main():
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    source_blend = Path(arguments[0]).resolve()
    capture_path = Path(arguments[1]).resolve()
    output_blend = Path(arguments[2]).resolve()
    output_manifest = Path(arguments[3]).resolve()

    bpy.ops.wm.open_mainfile(
        filepath=str(source_blend),
        load_ui=False,
        use_scripts=False,
    )
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    source = bpy.data.objects[capture["object_name"]]
    source.hide_set(False)
    source.hide_render = False
    source.show_wire = True
    source.show_all_edges = True
    source_material = bpy.data.materials.new("HST_Runtime_Pairs_Source")
    source_material.diffuse_color = (0.025, 0.035, 0.05, 1.0)
    source.data.materials.clear()
    source.data.materials.append(source_material)

    for mesh_object in tuple(obj for obj in bpy.data.objects if obj.type == "MESH"):
        if mesh_object != source:
            mesh_object.hide_render = True
            mesh_object.hide_set(True)

    root_collection = bpy.data.collections.new("HST_Actual_Bridge_Pairs")
    bpy.context.scene.collection.children.link(root_collection)
    source_matrix = Matrix(capture["source_matrix_world"])
    manifest_groups = []

    for pair_index, pair in enumerate(capture["pairs"], start=1):
        if len(pair["sides"]) != 2:
            raise RuntimeError(
                f"Runtime pair {pair['runtime_index']} has "
                f"{len(pair['sides'])} components"
            )
        pair_collection = bpy.data.collections.new(f"Pair_{pair_index:02d}")
        root_collection.children.link(pair_collection)
        manifest_group = {
            "group": pair_index,
            "runtime_index": pair["runtime_index"],
            "sides": [],
        }
        for side_index, side in enumerate(pair["sides"]):
            suffix = "a" if side_index == 0 else "b"
            object_label = f"{pair_index}{suffix}"
            coordinates = [Vector(point) for point in side["coordinates"]]
            if len(coordinates) < 2:
                raise RuntimeError(f"{object_label} has fewer than two coordinates")

            hue = (
                (pair_index - 1) * 0.61803398875 + side_index * 0.075
            ) % 1.0
            color = (*colorsys.hsv_to_rgb(hue, 0.82, 1.0), 1.0)
            material = bpy.data.materials.new(f"{object_label}_Material")
            material.diffuse_color = color

            curve_data = bpy.data.curves.new(f"{object_label}_Curve", "CURVE")
            curve_data.dimensions = "3D"
            curve_data.bevel_depth = 0.006
            curve_data.bevel_resolution = 2
            spline = curve_data.splines.new("POLY")
            spline.points.add(len(coordinates) - 1)
            for point, coordinate in zip(spline.points, coordinates):
                point.co = (*coordinate, 1.0)
            spline.use_cyclic_u = len(coordinates) == int(side["edge_count"])
            marker = bpy.data.objects.new(object_label, curve_data)
            marker.matrix_world = source_matrix
            marker.show_in_front = True
            curve_data.materials.append(material)
            pair_collection.objects.link(marker)

            manifest_group["sides"].append(
                {
                    "name": object_label,
                    "edge_count": side["edge_count"],
                    "length": side["length"],
                    "cyclic": spline.use_cyclic_u,
                }
            )
        manifest_groups.append(manifest_group)

    bpy.ops.wm.save_as_mainfile(
        filepath=str(output_blend),
        check_existing=False,
        compress=True,
    )

    output_manifest.write_text(
        json.dumps(
            {
                "fixture": capture["fixture"],
                "radius": capture["radius"],
                "object_name": capture["object_name"],
                "pair_count": len(manifest_groups),
                "groups": manifest_groups,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
