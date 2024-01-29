import bpy

# from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
#                        FloatProperty, IntProperty, PointerProperty,
#                        StringProperty)
from bpy.types import AddonPreferences, PropertyGroup

# from bpy.utils import register_class, unregister_class


class BTM_AddonPreferences(AddonPreferences):
    bl_idname = __package__


"""     toolbag_app_path: StringProperty(
        name="Marmoset Path",
        description="Path to executable file(toolbag.exe) for Marmoset Toolbag",
        default="C:\Program Files (x86)\Steam\steamapps\common\Toolbag 3\toolbag_steam.exe",
        subtype='FILE_PATH',
    )
    moi_app_path: StringProperty(
        name="Moi 3D Path",
        description="Path to executable file(toolbag.exe) for Moi Toolbag",
        default="C:\Program Files\MoI 4.0\MoI.exe",
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
 """


# box = col.box()
# col = box.column(align=True)


# def invoke(self, context, event):
#     return context.window_manager.invoke_confirm(self, event)


classes = BTM_AddonPreferences

""" def register():
    global classes
    register_class(classes)
    # for cls in classes:
        # register_class(cls)

def unregister():
    global classes
    unregister_class(classes)
    # for cls in classes:
        # unregister_class(cls) """
