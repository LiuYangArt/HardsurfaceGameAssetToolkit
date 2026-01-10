# -*- coding: utf-8 -*-
"""
Viewport 操作工具函数
====================

包含视口管理、着色模式等功能。
"""

import bpy


def check_screen_area(area_type: str) -> bpy.types.Area:
    """
    检查是否存在某种类型的 screen area

    Args:
        area_type: 区域类型 (VIEW_3D, IMAGE_EDITOR 等)

    Returns:
        找到的区域或 None
    """
    screen_area = None
    screen = bpy.context.window.screen
    for area in screen.areas:
        if area.type == area_type:
            screen_area = area
            break
    return screen_area


def new_screen_area(
    area_type: str, direction: str = "VERTICAL", size: float = 0.5
) -> bpy.types.Area:
    """
    创建新的 screen area

    Args:
        area_type: 区域类型 (VIEW_3D, IMAGE_EDITOR 等)
        direction: 分割方向 (VERTICAL, HORIZONTAL)
        size: 分割比例 (0.0 - 1.0)

    Returns:
        新创建的区域
    """
    area_num = len(bpy.context.window.screen.areas)
    bpy.ops.screen.area_split(direction=direction, factor=size)
    new_area = bpy.context.window.screen.areas[area_num]
    new_area.type = area_type
    return new_area


def viewport_shading_mode(area_type: str, shading_type: str, mode: str = "CONTEXT") -> list:
    """
    设置视口渲染模式

    Args:
        area_type: 区域类型 (VIEW_3D 等)
        shading_type: 着色类型 (SOLID, MATERIAL, RENDERED 等)
        mode: CONTEXT 只设置当前 viewport，ALL 设置所有同类型 viewport

    Returns:
        设置的 viewport space 列表
    """
    viewport_spaces = []
    match mode:
        case "CONTEXT":
            viewport = bpy.context.area
            if viewport.type == area_type:
                viewport_spaces.append(bpy.context.area.spaces[0])
        case "ALL":
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == area_type:
                        for space in area.spaces:
                            if space.type == area_type:
                                viewport_spaces.append(space)
    print(viewport_spaces)

    for viewport_space in viewport_spaces:
        viewport_space.shading.type = shading_type

    return viewport_spaces


class Viewport:
    """Viewport 操作工具类"""

    @staticmethod
    def is_local_view() -> bool:
        """
        检查是否在 Local View 模式

        Returns:
            是否在 Local View
        """
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        return space.local_view is not None
        return False

    @staticmethod
    def get_3dview_space():
        """
        获取 3D View 的 Space

        Returns:
            View3D Space 或 None
        """
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        return space
        return None
