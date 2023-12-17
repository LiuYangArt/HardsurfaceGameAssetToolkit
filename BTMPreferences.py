'''
Author: Baka_Akari exwww2000@qq.com
Date: 2022-09-14 19:32:40
LastEditors: Baka_Akari exwww2000@qq.com
LastEditTime: 2023-01-29 12:58:45
FilePath: \BTM\BTMPreferences.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import AddonPreferences, PropertyGroup
from bpy.utils import register_class, unregister_class


class BTM_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    toolbag_app_path: StringProperty(
        name="Marmoset Path",
        description="Path to executable file(toolbag.exe) for Marmoset Toolbag",
        default="E:\SteamLibrary\steamapps\common\Toolbag 3\toolbag_steam.exe",
        subtype='FILE_PATH',
    )
    moi_app_path: StringProperty(
        name="Moi 3D Path",
        description="Path to executable file(toolbag.exe) for Moi Toolbag",
        default="D:\Program Files\MoI 4.0\MoI.exe",
        subtype='FILE_PATH',
    )
    
    def draw(self, context):
        layout: bpy.types.UILayout
        
        props = context.scene.btmprops
        layout = self.layout
        col1 = layout.column(align=True)
        box1 = col1.box()
        col_app = box1.column(align=True)
        col_app.prop(self, "toolbag_app_path")
        col1 = layout.column(align=True)

        col2 = layout.column(align=True)
        box2 = col2.box()
        col_moi = box2.column(align=True)
        col_moi.prop(self, "moi_app_path")



        # box = col.box()
        # col = box.column(align=True)


    # def invoke(self, context, event):
    #     return context.window_manager.invoke_confirm(self, event)



classes = (BTM_AddonPreferences)