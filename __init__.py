# bl_info = {
#     "name": "HardsurfaceGameAssetToolkit",
#     "author": "LiuYang",
#     "description": "用于自定义流程游戏资产制作的blender插件",
#     "blender": (4, 2, 0),
#     "version": (2025, 2),
#     "location": "",
#     "warning": "插件开发中，会带有一些临时内容以及变动",
#     "category": "Generic",
#     "url": "https://github.com/LiuYangArt/HardsurfaceGameAssetToolkit",
# }

import bpy
from . import auto_load

from bpy.props import PointerProperty
from .ui_panel import UIParams
from .operators.uv_ops import HST_SwatchPickParams


auto_load.init()


# 注册 Scene / WindowManager 级 UI PointerProperty；先移除遗留定义，避免指向已注销的 PropertyGroup RNA。
# Swatch Pick 参数挂在 WindowManager 上，面板调参不产生 Undo 步骤。
def _register_scene_properties():
    _unregister_scene_properties()
    bpy.types.Scene.hst_params = PointerProperty(type=UIParams)
    bpy.types.WindowManager.hst_swatch_pick = PointerProperty(type=HST_SwatchPickParams)


# 在注销 PropertyGroup 前移除 PointerProperty，避免 Panel draw 访问失效 RNA。
def _unregister_scene_properties():
    if hasattr(bpy.types.Scene, "hst_params"):
        del bpy.types.Scene.hst_params
    if hasattr(bpy.types.WindowManager, "hst_swatch_pick"):
        del bpy.types.WindowManager.hst_swatch_pick


def register():
    _unregister_scene_properties()
    auto_load.register()
    _register_scene_properties()



def unregister():
    _unregister_scene_properties()
    auto_load.unregister()

