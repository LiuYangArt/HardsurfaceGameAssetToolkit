from enum import Flag
import bpy

# 定义命名
VERTEXCOLOR = "WearMask"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
MODIFIER_PREFIX = "HST"
BEVEL_MODIFIER = MODIFIER_PREFIX + "Bevel"
NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX + "NormalTransfer"
WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX + "WeightedNormal"
TRIANGULAR_MODIFIER = MODIFIER_PREFIX + "Triangulate"
COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX + "VertexColorTransfer"
COLOR_GEOMETRYNODE_MODIFIER = MODIFIER_PREFIX + "GNWearMask"
WEARMASK_NODE = "GN_HSTWearmaskVertColor"
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"


##添加DataTransfer Modifier传递顶点色
def add_color_transfer_modifier(mesh):
    """添加DataTransfer Modifier传递顶点色"""
    VERTEXCOLORTRANSFER_MODIFIER = "HSTVertexColorTransfer"
    TRANSFERPROXY_PREFIX = "TRNSP_"
    proxy_object = bpy.data.objects[TRANSFERPROXY_PREFIX + mesh.name]
    check_modifier = False

    for modifier in mesh.modifiers:  # 检查是否有modifier
        if modifier.name == VERTEXCOLORTRANSFER_MODIFIER:
            check_modifier = True
            break

    if check_modifier is False:  # 如果没有则添加
        transfer_modifier = mesh.modifiers.new(
            name=VERTEXCOLORTRANSFER_MODIFIER, type="DATA_TRANSFER"
        )
        transfer_modifier.object = proxy_object
        transfer_modifier.use_loop_data = True
        transfer_modifier.data_types_loops = {"COLOR_CORNER"}
        transfer_modifier.loop_mapping = "TOPOLOGY"
        print(mesh.name + " add color transfer modifier,assign " + proxy_object.name)
    else:  # 如果有则使用原有的
        transfer_modifier = mesh.modifiers[VERTEXCOLORTRANSFER_MODIFIER]
        transfer_modifier.object = proxy_object
        print(mesh.name + " use existing color transfer modifier")


##添加Geometry Nodes WearMask Modifier
def add_gn_wearmask_modifier(mesh):
    """添加Geometry Nodes WearMask Modifier"""

    check_modifier = False

    for modifier in mesh.modifiers:
        if modifier.name == COLOR_GEOMETRYNODE_MODIFIER:
            check_modifier = True
            break

    if check_modifier is False:
        wearmask_modifier = mesh.modifiers.new(
            name=COLOR_GEOMETRYNODE_MODIFIER, type="NODES"
        )
        wearmask_modifier.node_group = bpy.data.node_groups[WEARMASK_NODE]
        print(mesh.name + " add geometry node modifier " + wearmask_modifier.name)
    else:
        wearmask_modifier = mesh.modifiers[COLOR_GEOMETRYNODE_MODIFIER]
        wearmask_modifier.node_group = bpy.data.node_groups[WEARMASK_NODE]
        print(mesh.name + " use existing geometry node modifier")


# 设置Proxy Collection可见性
def transferproxycol_show(transp_coll):
    transp_coll.hide_viewport = False
    transp_coll.hide_render = False


def transferproxycol_hide(transp_coll):
    transp_coll.hide_viewport = True
    transp_coll.hide_render = True


# 添加顶点色属性
def batchsetvertcolorattr(selobj):
    ver_col = bpy.data.brushes["TexDraw"].color

    for obj in selobj:
        if VERTEXCOLOR in obj.data.color_attributes:
            colattr = obj.data.color_attributes[0]
        else:
            colattr = obj.data.color_attributes.new(
                name=VERTEXCOLOR,
                type="BYTE_COLOR",
                domain="CORNER",
            )
    return


# 清理顶点色属性
def batchcleanupcolorattr(objects):
    ver_col = bpy.data.brushes["TexDraw"].color

    for obj in objects:
        if obj.data.color_attributes:
            attrs = obj.data.color_attributes
            for r in range(len(obj.data.color_attributes) - 1, -1, -1):
                attrs.remove(attrs[r])

            colattr = obj.data.color_attributes.new(
                name=VERTEXCOLOR,
                type="BYTE_COLOR",
                domain="CORNER",
            )

        else:
            colattr = obj.data.color_attributes.new(
                name=VERTEXCOLOR,
                type="BYTE_COLOR",
                domain="CORNER",
            )
    return


# 存放传递模型的Collection
def create_transproxy_coll():
    transproxy_coll_exist = 0
    colls = bpy.data.collections

    for coll in bpy.data.collections:
        if TRANSFER_PROXY_COLLECTION in coll.name:
            transproxy_coll_exist += 1
            continue

    if transproxy_coll_exist == 1:
        for coll in colls:
            if coll.name == TRANSFER_PROXY_COLLECTION:
                transp_coll = coll
        return transp_coll
    else:
        transp_coll = bpy.data.collections.new(name=TRANSFER_PROXY_COLLECTION)

        transferproxycol_hide(transp_coll)
        # transp_coll.hide_select = True

        transp_coll.color_tag = "COLOR_08"
        bpy.context.scene.collection.children.link(transp_coll)
        return transp_coll


##检查是否存在Transfer模型
def check_TRNSP_exist(transp_coll, obj):
    transp_coll: bpy.types.Collection
    obj: bpy.types.Object

    TRNSP_exist = 0

    for transp_obj in transp_coll.all_objects:
        if transp_obj.name == TRANSFERPROXY_PREFIX + obj.name:
            TRNSP_exist += 1
            return TRNSP_exist


##检查选中模型是否带有Transfer修改器
def check_TRNSPmod_exist(selobj):
    TRNSPmod_exist = 0
    for obj in selobj:
        for mod in obj.modifiers:
            if mod.name == COLOR_TRANSFER_MODIFIER:
                TRNSPmod_exist += 1


##清理传递模型修改器
def cleanuptransproxymods(selobj):
    delete_list = []

    for obj in selobj:
        if obj.type == "MESH":
            # 有 transfer修改器时
            if check_TRNSPmod_exist(selobj) != 0:
                for mod in obj.modifiers:
                    if mod.name == COLOR_TRANSFER_MODIFIER:
                        # 如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
                        if (
                            mod.object is not None
                            and mod.object.parent.name == obj.name
                        ):
                            delete_list.append(mod.object)
                        obj.modifiers.remove(mod)
                    elif mod.name == COLOR_GEOMETRYNODE_MODIFIER:
                        obj.modifiers.remove(mod)

        else:
            print("is not mesh")
            break
    # 删除list内的物体
    for delete_obj in delete_list:
        if delete_obj:
            bpy.data.objects.remove(delete_obj)


##创建Proxy模型，应用修改器
def make_transpproxy_object(transp_coll):
    obj: bpy.types.Object
    copy_obj: bpy.types.Object
    transp_coll: bpy.types.Collection

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    copy_list = []
    bns_coll = None
    # 显示_transfcoll以便处理模型
    transp_coll.hide_viewport = False
    transp_coll.hide_render = False

    # 清理之前的传递模型

    # cleanuptransproxymods(selobj)

    for obj in selobj:
        if obj.type == "MESH":
            obj.hide_render = True
            if check_TRNSP_exist(transp_coll, obj) != 1:
                # 复制模型并修改命名
                copy_obj = obj.copy()
                copy_obj.data = obj.data.copy()
                copy_obj.name = TRANSFERPROXY_PREFIX + obj.name
                copy_obj.parent = obj
                # 检查文件中是否存在_transfcoll
                for coll in bpy.data.collections:
                    if coll.name == TRANSFER_PROXY_COLLECTION:
                        bns_coll = coll
                # 移动proxy模型到_transfcoll内
                bns_coll.objects.link(copy_obj)

                copy_list.append(copy_obj)
        else:
            print("is not mesh")
            break
    # 选择所有复制出来的模型，应用修改器
    objects = copy_list
    batchcleanupcolorattr(objects)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in copy_list:
        obj.select_set(True)
        obj.hide_render = True
    bpy.context.view_layer.objects.active = bpy.data.objects[copy_obj.name]
    bpy.ops.object.convert(target="MESH")

    # 隐藏_transfcoll
    transp_coll.hide_viewport = True
    transp_coll.hide_render = True


# 导入预设Geometry Nodes
def importgnwearmask():
    from bpy.utils import resource_path
    from pathlib import Path

    USER = Path(resource_path("USER"))
    src = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR

    file_path = src / "GN_WearMaskVertexColor.blend"
    inner_path = "NodeTree"
    gnode_name = WEARMASK_NODE

    for node in bpy.data.node_groups:
        if WEARMASK_NODE not in node.name:
            checkgn = 0
            print("have no gn")
        else:
            checkgn = 1
            print("have gn")
            break

    if checkgn == 0:
        bpy.ops.wm.append(
            filepath=str(file_path / inner_path / gnode_name),
            directory=str(file_path / inner_path),
            filename=gnode_name,
        )


def checkhastvcpmodifier(selobj):
    addmod_list = []

    for obj in selobj:
        for m in obj.modifiers:
            if m is not None and m.name == COLOR_TRANSFER_MODIFIER:
                if m.object is None:
                    addmod_list.append(obj)
            else:
                addmod_list.append(obj)

    selobj = addmod_list
