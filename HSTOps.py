import bpy
from bpy.utils import resource_path
from pathlib import Path

from .Functions.BTMFunctions import *
from .Functions.VertexColorBake import *
from .Functions.CommonFunctions import *


# Constants
VERTEXCOLOR = "VertColor"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
MODIFIER_PREFIX = "HST"
BEVEL_MODIFIER = "HSTBevel"
NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX+"NormalTransfer"
WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX+"WeightedNormal"
TRIANGULAR_MODIFIER = MODIFIER_PREFIX+"Triangulate"
COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX+"VertexColorTransfer"
COLOR_GEOMETRYNODE_MODIFIER = MODIFIER_PREFIX+"GNWearMask"
WEARMASK_NODE = "GN_HSTWearmaskVertColor"
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"
USER = Path(resource_path("USER"))
ASSET_PATH = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
NODE_FILE_PATH = ASSET_PATH / "GN_WearMaskVertexColor.blend"


# Make Transfer VertexBakeProxy Operator
class HST_CreateTransferVertColorProxy(bpy.types.Operator):
    bl_idname = "object.hst_addtransvertcolorproxy"
    bl_label = "Make Transfer VertexColor Proxy"
    bl_description = "为选中的物体建立用于烘焙顶点色的代理模型，\
        代理模型通过DataTransfer修改器将顶点色传递回原始模型。\
        如果原始模型有造型修改，请重新建立代理。\
        注意其修改器顺序必须存在于Bevel修改器之后。"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object

        collection = get_collection(active_object)
        if collection is not None:
            selected_meshes = filter_type(selected_objects, type="MESH")#筛选mesh
            import_node_group(NODE_FILE_PATH, WEARMASK_NODE)  # 导入wearmask nodegroup
            for object in selected_objects:
                clean_user(object)  # 清理multiuser

            proxy_object_list = []
            proxy_collection = create_collection(TRANSFER_PROXY_COLLECTION, "08")

            set_visibility(proxy_collection, True)
            for mesh in selected_meshes:
                add_vertexcolor_attribute(mesh, VERTEXCOLOR)  # 添加顶点色
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
                # 清理修改器
                remove_modifier(mesh, COLOR_GEOMETRYNODE_MODIFIER)  # 清理modifier
                # 清理modifier的对象
                modifier_object = remove_modifier(
                    mesh, COLOR_TRANSFER_MODIFIER, has_subobject=True
                )
                if (
                    modifier_object is not None
                    and modifier_object.parent.name == mesh.name
                ):
                    bpy.data.objects.remove(modifier_object)

                proxy_object_list.append(
                    make_transfer_proxy_mesh(
                        mesh, TRANSFERPROXY_PREFIX, proxy_collection
                    )
                )  # 建立proxy模型

                # 添加modifier
                add_color_transfer_modifier(mesh)
                add_gn_wearmask_modifier(mesh)

                mesh.select_set(False)

            # 处理proxy模型
            for proxy_object in proxy_object_list:
                cleanup_color_attributes(proxy_object)
                add_vertexcolor_attribute(proxy_object, VERTEXCOLOR)

            set_visibility(proxy_collection, False)
            # 还原选择状态
            for object in selected_objects:
                object.select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[active_object.name]
        else:
            message_box(
                "Not in collection, please put selected objects in collections and retry | 所选物体需要在Collections中，注意需要在有Bevel修改器之后使用",
            )

        return {"FINISHED"}


# 烘焙ProxyMesh的顶点色AO Operator
class HST_BakeProxyVertexColorAO(bpy.types.Operator):
    bl_idname = "object.hst_bakeproxyvertcolrao"
    bl_label = "Bake Proxy VertexColor AO"
    bl_description = "烘焙代理模型的AO，需要先建立Proxy。\
        场景中如存在其它可渲染的物体会对AO造成影响。\
        建议手动关闭其它物体的可渲染开关。"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        current_render_engine = bpy.context.scene.render.engine  # 记录原渲染引擎
        proxy_list = []
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")

        if collection is not None:  # 检查是否在collection中
            bpy.context.scene.render.engine = "CYCLES"
            transfer_proxy_collection = bpy.data.collections[TRANSFER_PROXY_COLLECTION]
            set_visibility(transfer_proxy_collection, True)

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
            # 显示需要烘焙的物体，并设置为选中
            for proxy_object in proxy_list:
                proxy_object.select_set(True)
                proxy_object.hide_render = False

            # 烘焙AO到顶点色
            bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
            print("baked AO to vertexcolor")
            # 重置可见性和渲染引擎
            set_visibility(transfer_proxy_collection, False)
            bpy.context.scene.render.engine = current_render_engine

        else:
            message_box(
                text="Not in collection, please put selected objects in collections and create transfer proxy then retry | 所选物体需要在Collections中，并先建立TransferProxy",
            )

        return {"FINISHED"}


classes = (
    HST_CreateTransferVertColorProxy,
    HST_BakeProxyVertexColorAO,
)
