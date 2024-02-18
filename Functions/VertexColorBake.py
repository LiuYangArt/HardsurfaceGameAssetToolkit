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


