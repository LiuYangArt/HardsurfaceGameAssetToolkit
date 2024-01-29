import bpy


from .Functions.BTMFunctions import *
from .Functions.VertexColorBake import *

from .Functions.CommonFunctions import *

#     set_visibility,
#     get_collection,
#     check_modifier_exist,
#     rename_meshes,
#     get_objects_with_modifier,
#     add_vertexcolor_attr,
#     set_active_vertexcolor_attr,
#     clean_user,
#     filter_type,
#     message_box,
#     import_node_group,
#     set_edge_bevel_weight_from_sharp,
# )


# Constants
VERTEXCOLOR = "VertColor"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
BEVEL_MODIFIER = "HSTBevel"
NORMALTRANSFER_MODIFIER = "HSTNormalTransfer"
WEIGHTEDNORMAL_MODIFIER = "HSTWeightedNormal"
TRIANGULAR_MODIFIER = "HSTTriangulate"
VERTEXCOLORTRANSFER_MODIFIER = "HSTVertexColorTransfer"
COLOR_TRANSFER_MODIFIER = "HSTVertexColorTransfer"
COLOR_GEOMETRYNODE_MODIFIER = "HST_GNWMVertColor"
WEARMASK_NODE = "GN_HSTWearmaskVertColor"
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"


# Make Transfer VertexBakeProxy Operator
class HST_CreateTransferVertColorProxy(bpy.types.Operator):
    bl_idname = "object.hst_addtransvertcolorproxy"
    bl_label = "Make Transfer VertexColor Proxy"
    bl_description = "为选中的物体建立用于烘焙顶点色的代理模型，代理模型通过DataTransfer修改器将顶点色传递回原始模型。如果原始模型有造型修改，请重新建立代理。注意其修改器顺序必须存在于Bevel修改器之后。"

    def execute(self, context):
        obj: bpy.types.Object
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        collection = get_collection(active_object)

        selected_meshes = filter_type(selected_objects, type="MESH")

        if collection is not None:
            cleanuser(selected_objects)
            collobjs = collection.all_objects
            batchsetvertcolorattr(selected_objects)
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            # bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            renamemesh(self, collobjs, collection.name)
            transp_coll = create_transproxy_coll()
            make_transpproxy_object(transp_coll)
            add_proxydatatransfer_modifier(selected_objects)
            importgnwearmask()
            add_gnwmvc_modifier(selected_objects)
            bpy.ops.object.select_all(action="DESELECT")

            # 还原选择状态
            for obj in selected_objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[active_object.name]
        else:
            message_box(
                text="Not in collection, please put selected objects in collections and retry | 所选物体需要在Collections中，注意需要在有Bevel修改器之后使用",
                title="WARNING",
                icon="ERROR",
            )

        return {"FINISHED"}


# 烘焙ProxyMesh的顶点色AO Operator
class HST_BakeProxyVertexColorAO(bpy.types.Operator):
    bl_idname = "object.hst_bakeproxyvertcolrao"
    bl_label = "Bake Proxy VertexColor AO"
    bl_description = "烘焙代理模型的AO，需要先建立Proxy。场景中如存在其它可渲染的物体会对AO造成影响，建议手动关闭其它物体的可渲染开关。"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object

        current_render_engine = bpy.context.scene.render.engine

        proxy_list = []
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")
        if collection is not None:
            bpy.context.scene.render.engine = "CYCLES"
            transfer_proxy_collection = bpy.data.collections[TRANSFER_PROXY_COLLECTION]
            set_visibility(target_object=transfer_proxy_collection, hide=False)

            for object in selected_objects:
                clean_user(object)
                object.hide_render = True
                object.select_set(False)

            for mesh in selected_meshes:
                bpy.context.view_layer.objects.active = mesh
                if check_modifier_exist(mesh, COLOR_TRANSFER_MODIFIER) is True:
                    # 检查是否有modifier，如果有则添加到proxy_list
                    for modifier in mesh.modifiers:
                        if modifier.name == COLOR_TRANSFER_MODIFIER:
                            if modifier.object is not None:
                                proxy_list.append(modifier.object)
                            else:
                                print("modifier target object missing")
                                break
                else:
                    print("modifier missing")
                    break

            # 隐藏不必要烘焙的物体
            for proxy_object in transfer_proxy_collection.objects:
                proxy_object.hide_render = True
            # 显示需要烘焙的物体
            for proxy_object in proxy_list:
                proxy_object.select_set(True)
                proxy_object.hide_render = False

            # bake vertex ao
            bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
            print("baked AO to vertexcolor")
            # reset visibility
            set_visibility(target_object=transfer_proxy_collection, hide=True)
            bpy.context.scene.render.engine = current_render_engine

        else:
            message_box(
                text="Not in collection, please put selected objects in collections and create transfer proxy then retry | 所选物体需要在Collections中，并先建立TransferProxy",
                title="WARNING",
                icon="ERROR",
            )

        return {"FINISHED"}


classes = (
    HST_CreateTransferVertColorProxy,
    HST_BakeProxyVertexColorAO,
)
