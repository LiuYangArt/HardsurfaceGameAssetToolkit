import bpy
from bpy.utils import resource_path
from pathlib import Path

from .Functions.HSTFunctions import *
from .Functions.CommonFunctions import *


# Constants
VERTEXCOLOR = "WearMask"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
MODIFIER_PREFIX = "HST"
BEVEL_MODIFIER = "HSTBevel"
NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX + "NormalTransfer"
WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX + "WeightedNormal"
TRIANGULAR_MODIFIER = MODIFIER_PREFIX + "Triangulate"
COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX + "VertexColorTransfer"
COLOR_GEOMETRYNODE_MODIFIER = MODIFIER_PREFIX + "GNWearMask"
WEARMASK_NODE = "GN_HSTWearmaskVertColor"
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"
USER = Path(resource_path("USER"))
ASSET_PATH = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
NODE_FILE_PATH = ASSET_PATH / "GN_WearMaskVertexColor.blend"


class HST_BevelTransferNormal(bpy.types.Operator):
    bl_idname = "object.hstbeveltransfernormal"
    bl_label = "Bevel And Transfer Normal"
    bl_description = "添加倒角并从原模型传递法线到倒角后的模型，解决复杂曲面法线问题"

    def execute(self, context):
        parameters = context.scene.hst_params
        current_scene = bpy.context.object.users_scene[0].name
        length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        collection_objects = collection.all_objects

        for object in selected_objects:
            clean_user(object)

        apply_transfrom(object)

        rename_meshes(collection_objects, collection.name)

        transfer_collection = create_collection(TRANSFER_COLLECTION, "08")
        set_visibility(transfer_collection, True)
        transfer_object_list = []
        for mesh in selected_meshes:
            transfer_object_list.append(
                make_transfer_proxy_mesh(
                    mesh, TRANSFER_MESH_PREFIX, transfer_collection
                )
            )
            add_bevel_modifier(
                mesh,
                parameters.set_bevel_width,
                parameters.set_bevel_segments,
                length_unit,
            )
            add_triangulate_modifier(mesh)
            add_datatransfer_modifier(mesh)
            mesh.select_set(True)

        set_visibility(transfer_collection, False)
        self.report(
            {"INFO"},
            "Added Bevel and Transfer Normal to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}


class HST_BatchBevel(bpy.types.Operator):
    bl_idname = "object.hstbevelmods"
    bl_label = "Batch Add Bevel Mods"
    bl_description = "批量添加Bevel和WeightedNormal"

    def execute(self, context):
        parameters = context.scene.hst_params
        current_scene = bpy.context.object.users_scene[0].name
        length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        for object in selected_objects:
            clean_user(object)
            apply_transfrom(object)

        collection_objects = collection.all_objects
        rename_meshes(collection_objects, collection.name)

        for mesh in selected_meshes:
            add_bevel_modifier(
                mesh,
                parameters.set_bevel_width,
                parameters.set_bevel_segments,
                length_unit,
            )
            add_weightednormal_modifier(mesh)
            add_triangulate_modifier(mesh)
            mesh.select_set(True)

        self.report(
            {"INFO"},
            "Added Bevel and WeightedNormal modifier to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}


class HST_SetBevelParameters_Operator(bpy.types.Operator):
    bl_idname = "object.hstbevelsetparam"
    bl_label = "Set HSTBevel Parameters"
    bl_description = "修改HST Bevel修改器参数"

    def execute(self, context):
        parameters = context.scene.hst_params
        selected_objects = bpy.context.selected_objects
        # 获取当前场景的单位
        current_scene = bpy.context.object.users_scene[0].name
        length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
        # 根据单位设置bevel宽度scale
        match length_unit:
            case "METERS":
                bevel_width = parameters.set_bevel_width * 0.001
            case "CENTIMETERS":
                bevel_width = parameters.set_bevel_width * 0.01
            case "MILLIMETERS":
                bevel_width = parameters.set_bevel_width * 0.1

        success_count = 0
        for object in selected_objects:
            for modifier in object.modifiers:
                if modifier.name == BEVEL_MODIFIER:
                    modifier.segments = parameters.set_bevel_segments
                    modifier.width = bevel_width
                    success_count += 1
                    continue
        self.report(
            {"INFO"},
            "Set Bevel Modifier Parameters to "
            + str(parameters.set_bevel_segments)
            + " segments and "
            + str(parameters.set_bevel_width)
            + " "
            + str(length_unit)
            + " width"
            + " for "
            + str(success_count)
            + " objects",
        )
        return {"FINISHED"}


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
        selected_meshes = filter_type(selected_objects, type="MESH")

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        collection_objects = collection.all_objects
        import_node_group(NODE_FILE_PATH, WEARMASK_NODE)  # 导入wearmask nodegroup
        for object in selected_objects:
            clean_user(object)  # 清理multiuser
            apply_transfrom(object, location=True, rotation=True, scale=True)
        proxy_object_list = []
        proxy_collection = create_collection(TRANSFER_PROXY_COLLECTION, "08")
        rename_meshes(collection_objects, collection.name)  # 重命名mesh
        set_visibility(proxy_collection, True)
        for mesh in selected_meshes:
            add_vertexcolor_attribute(mesh, VERTEXCOLOR)  # 添加顶点色
            remove_modifier(mesh, COLOR_GEOMETRYNODE_MODIFIER)  # 清理modifier
            remove_modifier(mesh, COLOR_TRANSFER_MODIFIER, has_subobject=True)  # 清理modifier的对象

            proxy_mesh = make_transfer_proxy_mesh(
                mesh, TRANSFERPROXY_PREFIX, proxy_collection
            )
            proxy_object_list.append(proxy_mesh)

            # 添加attribute __mod_weightednormals_faceweight  Face | INTEGER ，默认值为1，以便在没有bevel修改器的物体上得到效果正确的wearmask g通道
            if "__mod_weightednormals_faceweight" not in mesh.data.attributes:
                mesh.data.attributes.new(
                    "__mod_weightednormals_faceweight", "INT", "FACE"
                )
                mesh.data.attributes[
                    "__mod_weightednormals_faceweight"
                ].data.foreach_set("value", [1] * len(mesh.data.polygons))
                mesh.data.update()

            # 添加modifier
            add_color_transfer_modifier(mesh)
            add_gn_wearmask_modifier(mesh)
            mesh.hide_render = True

        # 处理proxy模型
        for proxy_object in proxy_object_list:
            cleanup_color_attributes(proxy_object)
            add_vertexcolor_attribute(proxy_object, VERTEXCOLOR)

        # 还原状态
        set_visibility(proxy_collection, False)
        for object in selected_objects:
            object.select_set(False)

        self.report(
            {"INFO"},
            "Created "
            + str(len(selected_meshes))
            + " transfer vertex color proxy objects",
        )

        return {"FINISHED"}


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
        bake_list = []
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        bpy.context.scene.render.engine = "CYCLES"
        transfer_proxy_collection = bpy.data.collections[TRANSFER_PROXY_COLLECTION]
        set_visibility(transfer_proxy_collection, True)

        for object in selected_objects:
            clean_user(object)
            object.hide_render = True
            object.select_set(False)

        for mesh in selected_meshes:
            # bpy.context.view_layer.objects.active = mesh
            if check_modifier_exist(mesh, COLOR_TRANSFER_MODIFIER) is True:
                # 检查是否有modifier，如果有则添加到proxy_list
                for modifier in mesh.modifiers:
                    if modifier.name == COLOR_TRANSFER_MODIFIER:
                        if modifier.object is not None:
                            bake_list.append(modifier.object)
                        else:
                            print("modifier target object missing")
                            break
            else:
                print("modifier missing")
                break

        # 隐藏不必要烘焙的物体
        for proxy_object in transfer_proxy_collection.objects:
            set_visibility(proxy_object, False)
        # 显示需要烘焙的物体，并设置为选中
        for proxy_bake_object in bake_list:
            set_visibility(proxy_bake_object, True)
            bpy.context.view_layer.objects.active = proxy_bake_object
            proxy_bake_object.select_set(True)

        # 烘焙AO到顶点色
        bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
        self.report(
            {"INFO"}, "Baked " + str(len(bake_list)) + " objects' AO to vertex color"
        )
        # # 重置可见性和渲染引擎
        set_visibility(transfer_proxy_collection, False)
        bpy.context.scene.render.engine = current_render_engine
        for object in selected_objects:
            object.select_set(False)

        return {"FINISHED"}


class HST_CleanHSTObjects(bpy.types.Operator):
    bl_idname = "object.cleanhstobject"
    bl_label = "Clean HST Objects"
    bl_description = "清理所选物体对应的HST修改器和传递模型"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        delete_list = []
        selected_meshes = filter_type(selected_objects, type="MESH")
        for mesh in selected_meshes:
            for modifier in mesh.modifiers:
                if (
                    modifier.name == NORMALTRANSFER_MODIFIER
                    and modifier.object is not None
                ):
                    delete_list.append(modifier.object)

                if (
                    modifier.name == COLOR_TRANSFER_MODIFIER
                    and modifier.object is not None
                ):
                    delete_list.append(modifier.object)

                if "HST" in modifier.name:
                    mesh.modifiers.remove(modifier)
            mesh.select_set(False)
        for delete_object in delete_list:
            if delete_object is not None:
                bpy.data.objects.remove(delete_object)

        self.report(
            {"INFO"},
            "Cleaned "
            + str(len(selected_meshes))
            + " objects' HST modifiers， removed "
            + str(len(delete_list))
            + " modifier objects",
        )

        return {"FINISHED"}


classes = (
    HST_BatchBevel,
    HST_BevelTransferNormal,
    HST_CleanHSTObjects,
    HST_SetBevelParameters_Operator,
    HST_CreateTransferVertColorProxy,
    HST_BakeProxyVertexColorAO,
)
