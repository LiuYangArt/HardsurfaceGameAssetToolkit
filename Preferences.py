import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import AddonPreferences, PropertyGroup
# from bpy.utils import register_class, unregister_class


class AddonPref(AddonPreferences):
    bl_idname = __package__



    ue_multicast_group_endpoint: StringProperty(
        name="UE Multicast Group Endpoint",
        description="UE Multicast Group Endpoint",
        default="239.0.0.1:6766",
        maxlen=24,)

    ue_multicast_bind_address: StringProperty(
        name="UE Remote IP",
        description="UE Remote IP",
        default="127.0.0.1",
        maxlen=15,)
    
    ue_mesh_dir: StringProperty(
        name="UE Mesh Directory",
        description="UE Mesh Directory",
        default="/Meshes",
        maxlen=24,)

    
    def draw(self, context):
        layout: bpy.types.UILayout
        

        layout = self.layout
        column = layout.column(align=True)
        box_column = column.box()
        # pref_row = box_column.column(align=True)
        # box_column.label(text="Unreal Remote Settings")
        box_column.label(text="Use the same IP settings in your UE project settings>Python>Remote Execution")
        box_column.prop(self, "ue_multicast_group_endpoint")
        box_column.prop(self, "ue_multicast_bind_address")
        box_column.prop(self, "ue_mesh_dir")
        # col_app.prop(self, "ue_remote_port")
