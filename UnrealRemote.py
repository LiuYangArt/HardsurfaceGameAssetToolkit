import bpy


from .dependencies.unreal import *
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *
from .dependencies import remote_execution as re

# from pathlib import Path
# import os


def read_ue_ip_settings_from_pref():
    context = bpy.context
    preferences = context.preferences
    addon_prefs = preferences.addons[__package__].preferences

    ue_multicast_group_endpoint = fix_ip_input(
        addon_prefs.ue_multicast_group_endpoint
    )  # 239.0.0.1:6766
    bind_address = fix_ip_input(addon_prefs.ue_multicast_bind_address)  #'127.0.0.1'
    endpoint_port = int(ue_multicast_group_endpoint.split(":")[1])  # 6766
    group_endpoint = (
        ue_multicast_group_endpoint.split(":")[0],
        endpoint_port,
    )  # ('239.0.0.1', 6766)
    command_endpoint = bind_address, endpoint_port  # ('127.0.0.1', 6776)

    return group_endpoint, bind_address, command_endpoint


class SendPropsToUE(bpy.types.Operator):
    bl_idname = "hst.sendprops_ue"
    bl_label = "Send Props to UE"
    bl_description = "Send Collections to UE\n直接发送Collection到UE中成为StaticMesh\n\
        规则和fbx导出一致\nUE中需要在Project Settings中开启Python插件的Remote Execution\n\
        Blender插件中设置端口对应UE设置\n\
        UE中FBX导入部分目前使用了UE中的Python脚本，因此需要特定的Python脚本支持\n\
        后续会把这部分集成到插件中，扩展通用性"

    def execute(self, context):
        # context = bpy.context
        # preferences = context.preferences
        # addon_prefs = preferences.addons["HardsurfaceGameAssetToolkit"].preferences
        # aa=addon_prefs.ue_multicast_group_endpoint
        # for i in dir(addon_prefs):
        #     print(i)

        ue_group_endpoint, ue_bind_address, ue_command_enepoint = (
            read_ue_ip_settings_from_pref()
        )
        print(f"ue_group_endpoint: {ue_group_endpoint}")
        preferences = context.preferences
        addon_prefs = preferences.addons[__package__].preferences

        properties = context.scene.hst_params
        ue_content_path = normalize_path(properties.unreal_path)
        ue_content_path = fix_ue_game_path(ue_content_path)
        fbx_export_path = normalize_path(TEMP_PATH)
        mesh_dir = normalize_path(addon_prefs.ue_mesh_dir)
        ue_script = UE_SCRIPT
        ue_file_dir = normalize_path(fbx_export_path)

        ue_script_command = (
            f'{UE_SCRIPT_CMD}("{ue_file_dir}","{ue_content_path}","{mesh_dir}")'
        )


        # if is_connected() == False:
        #     self.report({"ERROR"}, "Failed to connect to UE")
        #     return {"CANCELLED"}

        ue_commands = make_ue_python_script_command(ue_script, ue_script_command)
        # print(f"ue_commands: {ue_commands}")

        visible_collections = filter_collection_by_visibility(type="VISIBLE")
        store_mode = prep_select_mode()
        bpy.ops.hst.setsceneunits()  # 设置场景单位为厘米
        bake_collections, decal_collections, prop_collections, sm_collections = (
            filter_collection_types(visible_collections)
        )
        export_collections = (
            bake_collections + decal_collections + prop_collections + sm_collections
        )
        if len(export_collections) == 0:
            self.report(
                {"ERROR"},
                "No available collection for export. Please check visibility "
                + "and ensure objects are placed in collections，"
                + "set collection in correct type\n"
                + "没有可导出的collection，请检查collection可见性，把要导出的资产放在collection中，并设置正确的类型后重试",
            )

        check_collections(self, bake_collections, prop_collections, decal_collections)

        make_dir(TEMP_PATH)
        print(f"fbx export path: {fbx_export_path}")

        exported_files = []
        for collection in export_collections:
            new_name = collection.name.removeprefix("SM_")
            new_name = "SM_" + new_name
            file_path = fbx_export_path + "/" + new_name + ".fbx"
            exported_files.append(file_path)
            print(f"file_path: {file_path}")
            export_collection_staticmesh(collection, file_path)

        try:
            run_commands(ue_commands)

        except:
            self.report({"ERROR"}, "Failed to send props to UE")

        restore_select_mode(store_mode)

        # for file in exported_files:
        #     print(f"deleting file: {file}")
        #     os.remove(file)

        self.report({"INFO"}, f"{(len(export_collections))} StaticMeshes sent to UE ")

        return {"FINISHED"}
