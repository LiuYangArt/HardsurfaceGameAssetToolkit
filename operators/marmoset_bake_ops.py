# -*- coding: utf-8 -*-
"""Send Bake Prep collections to Marmoset Toolbag 5."""

import subprocess

import bpy

from ..preferences import DEFAULT_TOOLBAG_APP_PATH
from ..utils.marmoset_bake_utils import (
    build_marmoset_loader_script,
    collect_marmoset_bake_pairs,
    export_marmoset_bake_fbx,
    make_marmoset_bake_paths,
    resolve_toolbag_executable,
    resolve_vertex_color_mask,
    write_loader_script,
)


# 读取插件偏好中的 Toolbag 路径。
# 参数:
#     context: 当前 Blender context。
# 返回:
#     用户配置的 Toolbag.exe 路径或默认路径。
def get_toolbag_app_path(context) -> str:
    addon_name = __package__.split(".")[0]
    preferences = context.preferences.addons.get(addon_name)
    if preferences is None:
        return DEFAULT_TOOLBAG_APP_PATH
    return preferences.preferences.toolbag_app_path or DEFAULT_TOOLBAG_APP_PATH


class HST_OT_SendBakeToMarmoset(bpy.types.Operator):
    bl_idname = "hst.send_bake_to_marmoset"
    bl_label = "Send to Marmoset"
    bl_description = "导出已标记的 Bake Low/High collection 并在 Toolbag 5 创建 bake scene"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if context.scene is None:
            self.report({"ERROR"}, "No active scene")
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        parameters = context.scene.hst_params
        try:
            pairs = collect_marmoset_bake_pairs(context.scene)
            paths = make_marmoset_bake_paths(bpy.data.filepath)
            groups = export_marmoset_bake_fbx(pairs, paths)
            loader_script = build_marmoset_loader_script(
                groups=groups,
                scene_path=paths.scene_path,
                texture_size=int(parameters.texture_size),
                output_bits=parameters.marmoset_output_bits,
                output_samples=parameters.marmoset_output_samples,
                bevel_width_mm=parameters.marmoset_bevel_width_mm,
                bevel_samples=parameters.marmoset_bevel_samples,
                vertex_color_mask=resolve_vertex_color_mask(parameters.marmoset_vertex_color_mask_channel),
            )
            write_loader_script(paths.loader_path, loader_script)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        toolbag_exe = resolve_toolbag_executable(get_toolbag_app_path(context))
        if not toolbag_exe.exists():
            self.report({"ERROR"}, f"Toolbag.exe not found: {toolbag_exe}")
            return {"CANCELLED"}

        try:
            subprocess.Popen([str(toolbag_exe), str(paths.loader_path)])
        except (FileNotFoundError, OSError) as error:
            self.report({"ERROR"}, f"Failed to launch Toolbag: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Sent {len(pairs)} bake group(s) to Marmoset")
        return {"FINISHED"}
