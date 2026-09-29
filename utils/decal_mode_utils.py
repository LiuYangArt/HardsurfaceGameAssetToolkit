# -*- coding: utf-8 -*-
"""
Decal Mode
==========

Decal Mode 是 Scene 级开关（hst_params.decal_mode）。开启时应用 Decal 摆放参数，
并让 Append 导入复用已有数据（见 asset_import_utils）；关闭时只停止复用。
"""

import bpy


def set_asset_browser_import_method(window_manager, import_method: str) -> int:
    """
    把所有已打开的 Asset Browser 的导入方式设为指定值。

    Args:
        window_manager: bpy.types.WindowManager，用于遍历所有 Window。
        import_method: Import Method 枚举值，如 "APPEND"。

    Returns:
        被修改的 Asset Browser 数量。
    """
    count = 0
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type != "FILE_BROWSER":
                continue
            space = area.spaces.active
            if space.browse_mode != "ASSETS":
                continue
            space.params.import_method = import_method
            count += 1
    return count


def apply_decal_snap_settings(scene):
    """
    按 Decal 摆放流程设置 Snap / Pivot / Transform Orientation。

    Args:
        scene: bpy.types.Scene，写入目标。Snap 开关本身保持不变。
    """
    tool_settings = scene.tool_settings
    # base 与 individual 共用同一存储，分开赋值会互相覆盖，必须一次写入并集
    tool_settings.snap_elements = {
        "VERTEX",
        "EDGE",
        "FACE",
        "EDGE_MIDPOINT",
        "FACE_PROJECT",
    }
    tool_settings.snap_target = "CENTER"
    tool_settings.use_snap_align_rotation = True
    tool_settings.use_snap_backface_culling = False
    tool_settings.use_snap_selectable = True
    tool_settings.use_snap_translate = True
    tool_settings.use_snap_rotate = False
    tool_settings.use_snap_scale = False
    tool_settings.transform_pivot_point = "MEDIAN_POINT"
    scene.transform_orientation_slots[0].type = "LOCAL"


def on_decal_mode_changed(self, context):
    """
    hst_params.decal_mode 的 update 回调：开启时应用 Decal 摆放参数。

    Args:
        self: UIParams，所属 Scene 通过 id_data 获取。
        context: Blender context。
    """
    if not self.decal_mode:
        return
    set_asset_browser_import_method(context.window_manager, "APPEND")
    apply_decal_snap_settings(self.id_data)
