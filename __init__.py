# 硬表面游戏资产快捷处理工具包
# 基于卡林的硬表面插件修改

bl_info = {
    "name" : "HardsurfaceGameAssetToolkit",
    "author" : "Akari,LiuYang",
    "description" : "",
    "blender" : (4, 0, 0),
    "version" : (0, 4, 4, 5),
    "location" : "",
    "warning" : "插件开发中，会带有一些临时内容以及变动",
    "category" : "Generic"
}

import bpy
from bpy.props import CollectionProperty, PointerProperty
from .UIPanel import BTMCollection, BTMPropGroup

from . import auto_load

auto_load.init()

def register():   
    
    auto_load.register()
    # bpy.types.Scene.btmprops = PointerProperty(type=BTMPropGroup)

def unregister():
    
    auto_load.unregister()
    # del bpy.types.Scene.btmprops
