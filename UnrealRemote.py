import bpy

import threading
from .dependencies.unreal import *
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *

from .dependencies.rpc import blender_server


class SendPropsToUE(bpy.types.Operator):
    bl_idname = "hst.sendprops_ue"
    bl_label = "Send Props to UE"
    bl_description = "Send Collections to UE\
        直接发送Collection到UE中成为StaticMesh，规则和fbx导出一致\
        UE中需要在Project Settings中开启Python插件的Remote Execution\
        第一次使用需要先用Start Server连通UE RPC服务器\
        UE中FBX导入部分目前使用了UE中的Python脚本，因此需要特定的Python脚本支持\
        后续会把这部分集成到插件中，扩展通用性"

    def execute(self, context):

        preferences = context.preferences
        addon_prefs = preferences.addons[__package__].preferences

        properties = context.scene.hst_params
        ue_content_path = normalize_path(properties.unreal_path)
        ue_content_path = fix_ue_game_path(ue_content_path)
        fbx_export_path = normalize_path(TEMP_PATH)
        mesh_dir = normalize_path(addon_prefs.pref_ue_mesh_dir)

        ue_script = UE_SCRIPT
        ue_script_command = (
            f'{UE_SCRIPT_CMD}("{fbx_export_path}","{ue_content_path}","{mesh_dir}")'
        )
        ue_commands = make_ue_python_script_command(ue_script, ue_script_command)

        if is_connected() == False:
            self.report({"ERROR"}, "Failed to connect to UE")
            return {"CANCELLED"}


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
            FBXExport.staticmesh(collection, file_path)

        try:
            run_commands(ue_commands)

        except:
            self.report({"ERROR"}, "Failed to send props to UE")

        restore_select_mode(store_mode)

        self.report({"INFO"}, f"{(len(export_collections))} StaticMeshes sent to UE ")

        return {"FINISHED"}

class StartRPCServers(bpy.types.Operator):
    """Bootstraps unreal and blender with rpc server threads, so that they are ready for remote calls."""
    bl_idname = 'hst.start_rpc_servers'
    bl_label = 'Start UE RPC Server'
    bl_description = "Starts the RPC server for communication between Blender and UE\
        启动UE和Blender之间的RPC服务器"

    def execute(self, context):

        try:
            # bootstrap the unreal rpc server if it is not already running
            unreal.bootstrap_unreal_with_rpc_server()

        except ConnectionError:
            self.report({'ERROR'}, 'Failed to connect to UE')


        # start the blender rpc server if its not already running
        if 'BlenderRPCServer' not in [thread.name for thread in threading.enumerate()]:
            rpc_server = blender_server.RPCServer()
            rpc_server.start(threaded=True)
            self.report({'INFO'}, 'RPC Servers started')

        return {'FINISHED'}