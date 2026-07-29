import json
import sys
from pathlib import Path

import bmesh
import bpy


REPO_PARENT = str(Path(__file__).resolve().parents[5])
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

import HardsurfaceGameAssetToolkit


# 从正式 Feature Chamfer Operator runtime 捕获最终送入原生 Bridge 的全部左右链。
# 命令行参数: fixture 路径、source Mesh 名、Radius 与输出 JSON 路径。
def main():
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    fixture_path = Path(arguments[0]).resolve()
    object_name = arguments[1]
    radius = float(arguments[2])
    output_path = Path(arguments[3]).resolve()

    bpy.ops.wm.open_mainfile(
        filepath=str(fixture_path),
        load_ui=False,
        use_scripts=False,
    )
    try:
        HardsurfaceGameAssetToolkit.unregister()
    except Exception:
        pass
    HardsurfaceGameAssetToolkit.register()

    source = bpy.data.objects.get(object_name)
    if source is None or source.type != "MESH":
        raise RuntimeError(f"Source Mesh not found: {object_name}")
    source_matrix_world = [list(row) for row in source.matrix_world]
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    source.hide_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source

    preview_result = bpy.ops.hst.feature_chamfer_gn(
        "INVOKE_DEFAULT",
        action="PREVIEW",
        radius=radius,
    )
    if preview_result != {"FINISHED"}:
        raise RuntimeError(f"Preview failed: {sorted(preview_result)}")

    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    source.hide_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source

    bridge_utils = (
        HardsurfaceGameAssetToolkit.utils.feature_chamfer_direct_bridge_utils
    )
    original_bridge = bmesh.ops.bridge_loops
    pairs = []

    # 记录单次原生 Bridge 调用的真实 Edge 连通分量，并继续执行原操作。
    # args/kwargs: bmesh.ops.bridge_loops 的原始调用参数；返回原操作结果。
    def capture_bridge(*args, **kwargs):
        components = bridge_utils._edge_components(set(kwargs.get("edges", ())))
        pair = {
            "runtime_index": len(pairs) + 1,
            "component_count": len(components),
            "sides": [],
        }
        for side_index, component in enumerate(components):
            vertices = bridge_utils._ordered_chain_vertices(component)
            pair["sides"].append(
                {
                    "side": "a" if side_index == 0 else "b",
                    "edge_count": len(component),
                    "length": sum(edge.calc_length() for edge in component),
                    "coordinates": [
                        [float(value) for value in vertex.co]
                        for vertex in vertices
                    ],
                }
            )
        pairs.append(pair)
        return original_bridge(*args, **kwargs)

    bmesh.ops.bridge_loops = capture_bridge
    try:
        finalize_result = bpy.ops.hst.feature_chamfer_gn(
            "INVOKE_DEFAULT",
            action="FINALIZE",
        )
    finally:
        bmesh.ops.bridge_loops = original_bridge

    output = {
        "fixture": fixture_path.name,
        "fixture_path": str(fixture_path),
        "object_name": object_name,
        "radius": radius,
        "source_matrix_world": source_matrix_world,
        "preview_result": sorted(preview_result),
        "finalize_result": sorted(finalize_result),
        "pair_count": len(pairs),
        "pairs": pairs,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
