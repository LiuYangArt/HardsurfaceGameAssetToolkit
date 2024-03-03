import bpy
from pathlib import Path
from .Const import AddonPath
from .Functions.CommonFunctions import write_json,fix_ip_input,read_json_from_file
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
    # return prefs_dict

def read_ue_ip_settings_from_pref():
    """ 从addon_prefs读取配置,转换为group_endpoint, bind_address, command_endpoint """
    prefs_file = Path(AddonPath.SETTING_DIR).joinpath(AddonPath.CONFIG_FILE)
    prefs_dict = read_json_from_file(prefs_file)
    # print(f"set ue remote ip from pref file")
    ue_multicast_group_endpoint = ("239.0.0.1:6766")
    bind_address = "0.0.0.0"
    for key in prefs_dict:
        if "ue_multicast_group_endpoint" in key:
            ue_multicast_group_endpoint = fix_ip_input(prefs_dict[key])
        if "ue_multicast_bind_address" in key:
            bind_address = fix_ip_input(prefs_dict[key])

    endpoint_port = int(ue_multicast_group_endpoint.split(":")[1]) #6766
    group_endpoint = ue_multicast_group_endpoint.split(":")[0], endpoint_port #('239.0.0.1', 6766)
    command_endpoint = bind_address, endpoint_port # ('0.0.0.0', 6776)

    return group_endpoint, bind_address, command_endpoint

def set_prefs(pref_dict):
    prefs = bpy.context.preferences.addons[__package__].preferences
    for i in dir(prefs):
        if i in pref_dict:
            setattr(prefs, i, pref_dict[i])
            print(f"set {i} to {pref_dict[i]}")

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
