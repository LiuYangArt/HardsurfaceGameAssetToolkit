import bpy
import json
import os
from pathlib import Path
from .Const import AddonPath
from .Functions.CommonFunctions import write_json
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import AddonPreferences, PropertyGroup

def write_prefs_to_file(prop, value):
    prefs = bpy.context.preferences.addons[__package__].preferences
    prefs_file = Path(AddonPath.SETTING_DIR).joinpath(AddonPath.CONFIG_FILE)
    prefs_dict = {}
    for i in dir(prefs):
        if i.startswith("pref_"):
            prefs_dict[i] = getattr(prefs, i)
            print(f"{i}: {getattr(prefs, i)}")
    write_json(prefs_file, prefs_dict)
    print(f"write addon prefs to file: {prefs_file}")
    

class AddonPref(AddonPreferences):
    bl_idname = __package__


    pref_ue_multicast_group_endpoint: StringProperty(
        name="UE Multicast Group Endpoint",
        description="UE Multicast Group Endpoint",
        default="239.0.0.1:6766",
        maxlen=24,
        update=write_prefs_to_file,)

    pref_ue_multicast_bind_address: StringProperty(
        name="UE Remote IP",
        description="UE Remote IP",
        default="0.0.0.0",
        maxlen=15,
        update=write_prefs_to_file,)
    
    pref_ue_mesh_dir: StringProperty(
        name="UE Mesh Directory",
        description="UE Mesh Directory",
        default="/Meshes",
        maxlen=24,
        update=write_prefs_to_file,)


    def draw(self, context):
        layout: bpy.types.UILayout
        

        layout = self.layout
        column = layout.column(align=True)
        box_column = column.box()
        # pref_row = box_column.column(align=True)
        # box_column.label(text="Unreal Remote Settings")
        box_column.label(text="Use the same IP settings in your UE project settings>Python>Remote Execution")
        box_column.prop(self, "pref_ue_multicast_group_endpoint")
        box_column.prop(self, "pref_ue_multicast_bind_address")
        box_column.prop(self, "pref_ue_mesh_dir")
        # col_app.prop(self, "ue_remote_port")
