# -*- coding: utf-8 -*-
"""
UI 工具函数
==========

包含消息框、渲染引擎切换等 UI 相关功能。
"""

import bpy
from ..Const import BL_VERSION


def message_box(text: str = "", title: str = "WARNING", icon: str = "ERROR") -> None:
    """
    弹出消息框

    Args:
        text: 消息内容
        title: 标题
        icon: 图标类型 (ERROR, WARNING, INFO 等)
    """

    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def switch_to_eevee() -> None:
    """
    切换到 EEVEE 渲染引擎
    
    根据 Blender 版本自动选择正确的引擎名称：
    - 5.0+: BLENDER_EEVEE
    - 4.2-4.9: BLENDER_EEVEE_NEXT
    - <4.2: BLENDER_EEVEE
    """
    if BL_VERSION >= 5.0:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
    elif BL_VERSION >= 4.2:
        bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
