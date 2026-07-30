# -*- coding: utf-8 -*-
"""保存正式一步式 Feature Chamfer 结果，供用户在 Blender 中手工验收。"""

import os
from pathlib import Path

import bpy


OUTPUT_PATH = Path(
    os.environ.get(
        "HST_FEATURE_CHAMFER_ACCEPTANCE_BLEND",
        "/private/tmp/feature_chamfer_one_step_acceptance.blend",
    )
)


# 返回当前文件中正式最终输出。
# 无参数；返回带 Feature Chamfer 标记的 Mesh Object。
def _acceptance_output():
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and obj.get("hst_feature_chamfer_source_object")
    ]
    if not candidates:
        raise RuntimeError("Acceptance blend contains no Feature Chamfer output")
    return max(candidates, key=lambda obj: len(obj.data.polygons))


# 准备最终输出的手工检查状态，不创建相机、灯光或图片。
# output: 待手工检查的正式最终 Mesh。
def _configure_scene(output):
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    output.hide_set(False)
    output.select_set(True)
    output.show_wire = True
    output.show_all_edges = True
    bpy.context.view_layer.objects.active = output


# 保存可手工检查的 Blend，失败时让 Blender 直接报错。
# 无参数；无返回值。
def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = _acceptance_output()
    _configure_scene(output)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(OUTPUT_PATH),
        check_existing=False,
        compress=True,
    )
    print(f"[HST_FEATURE_CHAMFER_ACCEPTANCE_BLEND]{OUTPUT_PATH}")


main()
