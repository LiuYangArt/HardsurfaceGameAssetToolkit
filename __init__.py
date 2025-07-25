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
from .UIPanel import UIParams


auto_load.init()


def register():
    auto_load.register()
    bpy.types.Scene.hst_params = PointerProperty(type=UIParams)



def unregister():
    auto_load.unregister()
    del bpy.types.Scene.hst_params

