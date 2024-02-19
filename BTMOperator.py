import bpy
import subprocess
import configparser
from bpy_extras.io_utils import ImportHelper
# import bmesh


# Functions
from .Functions.BTMFunctions import *
# from .Functions.VertexColorBake import *
# from .Functions.TransferBevelNormal import *
from .Functions.CommonFunctions import *

# from .UIPanel import BTMPropGroup
# from .BTMPreferences import BTM_AddonPreferences

# Constants
# VERTEXCOLOR = "VertColor"
# TRANSFER_COLLECTION = "_TransferNormal"
# TRANSFER_MESH_PREFIX = "Raw_"
# TRANSFER_PROXY_COLLECTION = "_TransferProxy"
# TRANSFERPROXY_PREFIX = "TRNSP_"
# MODIFIER_PREFIX = "HST"
# BEVEL_MODIFIER = "HSTBevel"
# NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX+"NormalTransfer"
# WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX+"WeightedNormal"
# TRIANGULAR_MODIFIER = MODIFIER_PREFIX+"Triangulate"
# COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX+"VertexColorTransfer"
# COLOR_GEOMETRYNODE_MODIFIER = MODIFIER_PREFIX+"GNWearMask"
# WEARMASK_NODE = "GN_HSTWearmaskVertColor"
# ADDON_DIR = "HardsurfaceGameAssetToolkit"
# ASSET_DIR = "PresetFiles"


class BTMLowOperator(bpy.types.Operator):
    bl_idname = "object.btmlow"
    bl_label = "Low Poly Group"
    bl_description = "设置选中模型的整个Collection为LowPoly组，根据Collection名字修改命名"

    def execute(self, context):
        is_low = None
        is_high = None

        actobj = bpy.context.active_object
        coll = getCollection(actobj)
        collobj = coll.all_objects

        is_low = 1
        coll.color_tag = "NONE"
        collname = cleanaffix(self, actobj)
        cleanmatslot(self, coll.all_objects)
        collname = editcollandmat(self, is_low, is_high, collname, collobj)
        rename_meshes(list(collobj), collname)

        return {"FINISHED"}


class BTMHighOperator(bpy.types.Operator):
    bl_idname = "object.btmhigh"
    bl_label = "High Poly Group"
    bl_description = "设置选中模型的整个Collection为HighPoly组，根据Collection名字修改命名"

    def execute(self, context):
        is_low = None
        is_high = None

        actobj = bpy.context.active_object
        coll = getCollection(actobj)
        collobj = coll.all_objects

        is_high = 1
        coll.color_tag = "NONE"
        collname = cleanaffix(self, actobj)
        cleanmatslot(self, coll.all_objects)
        collname = editcollandmat(self, is_low, is_high, collname, collobj)
        renamemesh(self, list(collobj), collname)

        return {"FINISHED"}


class OrgaCollOperator(bpy.types.Operator):
    bl_idname = "object.orgacoll"
    bl_label = "Organize Collections"

    def Fix_Coll_Name(coll):
        fix_coll_name = coll.name.split("_")
        fix_coll_name.pop()
        fix_coll_name.pop()
        fix_coll_name = "_".join(fix_coll_name)
        return fix_coll_name

    def Get_High_Coll_List(colllist):
        high_coll_list = []

        for coll in colllist:
            if coll.name.split("_")[-1] == "high":
                high_coll_list.append(coll)
        return high_coll_list

    def Get_Low_Coll_List(colllist):
        low_coll_list = []

        for coll in colllist:
            if coll.name.split("_")[-1] == "low":
                low_coll_list.append(coll)
        return low_coll_list

    def Check_Base_Coll(colllist, high_coll):
        coll: bpy.types.Collection
        have_base_coll = 0
        base_coll_list = []

        for coll in colllist:
            if coll.name == OrgaCollOperator.Fix_Coll_Name(high_coll):
                base_coll_list.append(coll)
                have_base_coll += 1
        return have_base_coll, base_coll_list

    def Clean_Color_Tag(colllist):
        coll: bpy.types.Collection
        for coll in colllist:
            if "high" or "low" in coll.name:
                coll.color_tag = "NONE"

    def execute(self, context):
        high_coll: bpy.types.Collection
        low_coll: bpy.types.Collection
        base_coll: bpy.types.Collection

        colllist = bpy.data.collections
        high_coll_list = OrgaCollOperator.Get_High_Coll_List(colllist)
        low_coll_list = OrgaCollOperator.Get_Low_Coll_List(colllist)

        OrgaCollOperator.Clean_Color_Tag(colllist)
        for high_coll in high_coll_list:
            for low_coll in low_coll_list:
                if OrgaCollOperator.Fix_Coll_Name(
                    high_coll
                ) == OrgaCollOperator.Fix_Coll_Name(low_coll):
                    have_base_coll = OrgaCollOperator.Check_Base_Coll(
                        colllist, high_coll
                    )[0]
                    base_coll_list = OrgaCollOperator.Check_Base_Coll(
                        colllist, high_coll
                    )[1]
                    if have_base_coll:
                        for base_coll in base_coll_list:
                            if high_coll not in list(base_coll.children):
                                base_coll.children.link(high_coll)
                                bpy.context.scene.collection.children.unlink(high_coll)
                            if low_coll not in list(base_coll.children):
                                base_coll.children.link(low_coll)
                                bpy.context.scene.collection.children.unlink(low_coll)
                            base_coll.color_tag = "COLOR_02"
                    else:
                        basecoll = bpy.data.collections.new(
                            name=OrgaCollOperator.Fix_Coll_Name(high_coll)
                        )
                        bpy.context.scene.collection.children.link(basecoll)
                        basecoll.children.link(high_coll)
                        basecoll.children.link(low_coll)
                        bpy.context.scene.collection.children.unlink(high_coll)
                        bpy.context.scene.collection.children.unlink(low_coll)
                        basecoll.color_tag = "COLOR_02"
        return {"FINISHED"}


class ExportFBXOperator(bpy.types.Operator):
    bl_idname = "object.exportfbx"
    bl_label = "Export FBX"

    def Get_Bakers():
        coll: bpy.types.Collection

        colllist = bpy.data.collections
        base_colllist = []
        for coll in colllist:
            if coll.color_tag == "COLOR_02":
                base_colllist.append(coll)
        return base_colllist

    def Set_Obj_Active(self, active, objectlist):
        obj: bpy.types.Object

        for obj in objectlist:
            obj.select_set(state=active)

    def execute(self, context):
        base_coll: bpy.types.Collection
        base_obj: bpy.types.Object

        props = bpy.context.scene.hst_params
        filename = bpy.path.basename(bpy.data.filepath).split(".")[0]

        get_export_path = BTM_Export_Path()
        base_colllist = ExportFBXOperator.Get_Bakers()
        if bpy.data.is_saved:
            for base_coll in base_colllist:
                self.Set_Obj_Active(1, base_coll.all_objects)
                export_FBX(get_export_path, base_coll.name, True, False)
                self.Set_Obj_Active(0, base_coll.all_objects)
            create_baker_file(base_colllist)
        else:
            message_box(text="Please save blender file")

        return {"FINISHED"}


class OpenmMrmosetOperator(bpy.types.Operator):
    bl_idname = "object.openmarmoset"
    bl_label = "Open Marmoset"

    def execute(self, context):
        btb_run_toolbag()
        return {"FINISHED"}


# =========================================================================================






class MoiTransStepOperator(bpy.types.Operator, ImportHelper):
    bl_idname = "object.moitransfile"
    bl_label = "Use Moi Transform Step"

    def execute(self, context):
        obj_prop: bpy.types.Property
        act_obj = bpy.context.active_object

        sel_filepath = self.filepath
        moi_config_filepath = (
            os.path.expanduser("~") + "\\AppData\\Roaming\\Moi\\moi.ini"
        )

        config = configparser.ConfigParser()
        config.read(moi_config_filepath)
        if config.get("Settings", "LastFileDialogDirectory"):
            config.set("Settings", "LastFileDialogDirectory", sel_filepath)

            cfgfile = open(moi_config_filepath, "w")
            config.write(cfgfile, space_around_delimiters=False)
            cfgfile.close()

        moi_path = bpy.context.preferences.addons[
            "Hard Surface Tool"
        ].preferences.moi_app_path
        if moi_path:
            p = subprocess.Popen([moi_path, sel_filepath])
            returncode = p.wait()
        else:
            message_box("No moi software execution file selected")
        if sel_filepath.endswith("step"):
            obj_filepath = sel_filepath.replace("step", "obj")
        elif sel_filepath.endswith("stp"):
            obj_filepath = sel_filepath.replace("stp", "obj")

        import_obj_function(obj_filepath)

        # bpy.ops.wm.properties_add(data_path="object.data")

        print(sel_filepath)
        print(obj_filepath)
        print(moi_path)

        return {"FINISHED"}


class ReloadObjOperator(bpy.types.Operator):
    bl_idname = "object.reloadobj"
    bl_label = "Reload Object"

    def execute(self, context):
        act_obj = bpy.context.active_object

        obj_filepath = act_obj["import_path"]
        bpy.data.objects.remove(act_obj)

        import_obj_function(obj_filepath)

        return {"FINISHED"}


class GetVerColOperator(bpy.types.Operator):
    bl_idname = "object.getvercol"
    bl_label = "Get Vertex Color"
    bl_description = "采样选中物体的顶点色"

    def execute(self, context):
        act_obj = bpy.context.active_object

        verR = (
            bpy.data.meshes[act_obj.to_mesh().name]
            .sculpt_vertex_colors["ID_Color"]
            .data[0]
            .color[0]
        )
        verG = (
            bpy.data.meshes[act_obj.to_mesh().name]
            .sculpt_vertex_colors["ID_Color"]
            .data[0]
            .color[1]
        )
        verB = (
            bpy.data.meshes[act_obj.to_mesh().name]
            .sculpt_vertex_colors["ID_Color"]
            .data[0]
            .color[2]
        )

        bpy.data.brushes["TexDraw"].color = mathutils.Vector((verR, verG, verB))

        return {"FINISHED"}


class BatchSetVerColOperator(bpy.types.Operator):
    bl_idname = "object.setvercol"
    bl_label = "Batch Set Vertex Color"
    bl_description = "为选中的物体赋予顶点色,用于烘焙ID Mask"

    def execute(self, context):
        obj: bpy.types.Object
        sel_obj = bpy.context.selected_objects
        act_obj = bpy.context.active_object
        ver_col = bpy.data.brushes["TexDraw"].color

        for obj in sel_obj:
            if "ID_Color" in obj.data.color_attributes:
                colattr = obj.data.color_attributes[0]
            else:
                colattr = obj.data.color_attributes.new(
                    name="ID_Color",
                    type="BYTE_COLOR",
                    domain="CORNER",
                )

        # Create Palette
        pal = bpy.data.palettes.get("ID_Palette")
        if pal is None:
            pal = bpy.data.palettes.new("ID_Palette")
            # add a color to that palette
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)

        elif len(pal.colors) <= 15:
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)
        else:
            pal.colors.remove(pal.colors[0])
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)

        ts = bpy.context.tool_settings
        ts.image_paint.palette = pal

        return {"FINISHED"}


class TestButtonOperator(bpy.types.Operator):
    bl_idname = "object.testbutton"
    bl_label = "Open Stp File"

    def execute(self, context):
        print(bpy.data.palettes)
        for pal in bpy.data.palettes:
            print(pal)
        # context.tool_settings.image_paint.palette = "Palette"
        # print(context.tool_settings.image_paint.palette)

        return {"FINISHED"}


##顶点色烘焙Operator

# #Make Transfer VertexBakeProxy Operator
# class HST_CreateTransferVertColorProxy(bpy.types.Operator):
#     bl_idname = "object.hst_addtransvertcolorproxy"
#     bl_label = "Make Transfer VertexColor Proxy"
#     bl_description ="为选中的物体建立用于烘焙顶点色的代理模型，代理模型通过DataTransfer修改器将顶点色传递回原始模型。如果原始模型有造型修改，请重新建立代理。注意其修改器顺序必须存在于Bevel修改器之后。"

#     def execute(self, context):
#         obj: bpy.types.Object
#         selected_objects = bpy.context.selected_objects
#         active_object = bpy.context.active_object
#         collection = get_collection(active_object)
#         #objects = selobj

#         selected_meshes=filter_type(selected_objects, type="MESH")


#         if collection is not None:
#             cleanuser(selected_objects)
#             collobjs = collection.all_objects
#             batchsetvertcolorattr(selected_objects)
#             bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
#             #bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
#             renamemesh(self, collobjs, collection.name)
#             transp_coll = create_transproxy_coll()
#             make_transpproxy_object(transp_coll)
#             add_proxydatatransfer_modifier(selected_objects)
#             importgnwearmask()
#             add_gnwmvc_modifier(selected_objects)
#             bpy.ops.object.select_all(action='DESELECT')

#             #还原选择状态
#             for obj in selected_objects:
#                 obj.select_set(True)
#             bpy.context.view_layer.objects.active = bpy.data.objects[active_object.name]
#         else:
#             message_box(text="Not in collection, please put selected objects in collections and retry | 所选物体需要在Collections中，注意需要在有Bevel修改器之后使用", title="WARNING", icon='ERROR')

#         return{'FINISHED'}


# #烘焙ProxyMesh的顶点色AO Operator
# class HST_BakeProxyVertexColorAO(bpy.types.Operator):
#     bl_idname = "object.hst_bakeproxyvertcolrao"
#     bl_label = "Bake Proxy VertexColor AO"
#     bl_description = "烘焙代理模型的AO，需要先建立Proxy。场景中如存在其它可渲染的物体会对AO造成影响，建议手动关闭其它物体的可渲染开关。"

#     def execute(self, context):
#         selected_objects = bpy.context.selected_objects
#         active_object = bpy.context.active_object

#         current_render_engine = bpy.context.scene.render.engine

#         proxy_list = []
#         collection = get_collection(active_object)
#         selected_meshes = filter_type(selected_objects, "MESH")
#         if collection is not None:
#             bpy.context.scene.render.engine = "CYCLES"
#             transfer_proxy_collection = bpy.data.collections[TRANSFER_PROXY_COLLECTION]
#             set_visibility(target_object=transfer_proxy_collection, hide=False)

#             for object in selected_objects:
#                 clean_user(object)
#                 object.hide_render = True
#                 object.select_set(False)

#             for mesh in selected_meshes:
#                 bpy.context.view_layer.objects.active = mesh
#                 if check_modifier_exist(mesh, COLOR_TRANSFER_MODIFIER) is True:
#                     # 检查是否有modifier，如果有则添加到proxy_list
#                     for modifier in mesh.modifiers:
#                         if modifier.name == COLOR_TRANSFER_MODIFIER:
#                             if modifier.object is not None:
#                                 proxy_list.append(modifier.object)
#                             else:
#                                 print("modifier target object missing")
#                                 break
#                 else:
#                     print("modifier missing")
#                     break

#             # 隐藏不必要烘焙的物体
#             for proxy_object in transfer_proxy_collection.objects:
#                 proxy_object.hide_render = True
#             # 显示需要烘焙的物体
#             for proxy_object in proxy_list:
#                 proxy_object.select_set(True)
#                 proxy_object.hide_render = False

#             # bake vertex ao
#             bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
#             print("baked AO to vertexcolor")
#             # reset visibility
#             set_visibility(target_object=transfer_proxy_collection, hide=True)
#             bpy.context.scene.render.engine = current_render_engine

#         else:
#             message_box(
#                 text="Not in collection, please put selected objects in collections and create transfer proxy then retry | 所选物体需要在Collections中，并先建立TransferProxy",
#                 title="WARNING",
#                 icon="ERROR",
#             )

#         return {"FINISHED"}

classes = (
    # HSTPanel,
    # BTMPanel,
    BTMLowOperator,
    BTMHighOperator,
    OrgaCollOperator,
    ExportFBXOperator,
    OpenmMrmosetOperator,

    MoiTransStepOperator,
    ReloadObjOperator,
    BatchSetVerColOperator,
    GetVerColOperator,
    TestButtonOperator,
    # HST_BatchBevel,
    # HST_BevelTransferNormal,
    # HST_CleanHSTObjects,
    # HST_SetBevelParameters_Operator,
    # HST_CreateTransferVertColorProxy,
    # HST_BakeProxyVertexColorAO,
)
