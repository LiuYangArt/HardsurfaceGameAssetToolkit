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



# 添加Bevel修改器
def add_bevel_modifier(mesh):

    check_sharp = False
    bpy.data.meshes[mesh.to_mesh().name].use_auto_smooth = True
    # 如果没有bevel修改器
    if BEVEL_MODIFIER not in mesh.modifiers:

        if "sharp_edge" in mesh.data.attributes:
            check_sharp = True
            # 如果有倒角权重
            if "bevel_weight_edge" not in mesh.data.attributes:
                bevel_weight_attribute = mesh.data.attributes.new(
                    "bevel_weight_edge", "FLOAT", "EDGE"
                )
                for index, edge in enumerate(mesh.data.edges):
                    bevel_weight_attribute.data[index].value = (
                        1.0 if edge.use_edge_sharp else 0.0
                    )
        else:
            check_sharp = False

        # print(check_sharp)
        if check_sharp is True:
            bevel_modifier = mesh.modifiers.new(name=BEVEL_MODIFIER, type="BEVEL")
            bevel_modifier.limit_method = "WEIGHT"


        elif check_sharp is False:
            bevel_modifier = mesh.modifiers.new(name=BEVEL_MODIFIER, type="BEVEL")
            bevel_modifier.limit_method = "ANGLE"
            bevel_modifier.angle_limit = 0.523599

        bevel_modifier.offset_type = "WIDTH"
        bevel_modifier.width = 0.005
        bevel_modifier.use_clamp_overlap = False
        bevel_modifier.harden_normals = True
        bevel_modifier.loop_slide = True
        bevel_modifier.segments = 1
        bevel_modifier.profile = 0.7
        bevel_modifier.face_strength_mode = "FSTR_ALL"


def add_datatransfer_modifier(mesh):

    transfer_source_mesh = bpy.data.objects[TRANSFER_MESH_PREFIX + mesh.name]
    if NORMALTRANSFER_MODIFIER in mesh.modifiers:
        datatransfermod = mesh.modifiers[NORMALTRANSFER_MODIFIER]

    else:
        datatransfermod = mesh.modifiers.new(
            name=NORMALTRANSFER_MODIFIER, type="DATA_TRANSFER"
        )

    datatransfermod.object = transfer_source_mesh
    datatransfermod.use_loop_data = True
    datatransfermod.data_types_loops = {"CUSTOM_NORMAL"}
    datatransfermod.loop_mapping = "POLYINTERP_LNORPROJ"


# 添加Triangulate修改器
def add_triangulate_modifier(mesh):

    if TRIANGULAR_MODIFIER in mesh.modifiers:
        triangulate_modifier = mesh.modifiers[TRIANGULAR_MODIFIER]

    else:
        triangulate_modifier = mesh.modifiers.new(name=TRIANGULAR_MODIFIER, type="TRIANGULATE")

    triangulate_modifier.keep_custom_normals = True
    triangulate_modifier.min_vertices = 4
    triangulate_modifier.quad_method = "SHORTEST_DIAGONAL"


def add_weightednormal_modifier(mesh):


    if WEIGHTEDNORMAL_MODIFIER in mesh.modifiers:
        weightpmod = mesh.modifiers[WEIGHTEDNORMAL_MODIFIER]

    else:
        weightpmod = mesh.modifiers.new(name=WEIGHTEDNORMAL_MODIFIER, type="WEIGHTED_NORMAL")
    
    weightpmod.mode = "FACE_AREA"
    weightpmod.use_face_influence = True
    weightpmod.thresh = 0.01
    weightpmod.keep_sharp = False
    weightpmod.weight = 100

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

