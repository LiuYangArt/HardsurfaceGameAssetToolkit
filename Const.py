import bpy
import addon_utils
from pathlib import Path
import os
# from mathutils import Matrix

class Addon:
    NAME = "Hardsurface GameAsset Toolkit"

    def get_install_path():
        filepath = None
        for mod in addon_utils.modules():
            if mod.bl_info['name'] == Addon.NAME:
                filepath = mod.__file__
                filepath = filepath.split("\__init__.py")[0]
                filepath = filepath.replace("\\", "/")
                break
        if filepath is None:
            raise RuntimeError(f"未找到名为 {Addon.NAME} 的插件模块")
        filepath = Path(filepath)
        return filepath
    
    def get_blender_version()->float:
            blver=bpy.app.version
            bl_version_num=f"{blver[0]}.{blver[1]}"
            bl_version_num=float(bl_version_num)
            return bl_version_num
    
#TBD: 自动匹配不同的场景单位设置
# def get_scene_unit():
#     current_scene = bpy.context.object.users_scene[0].name
#     scene_length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
#     unit_scale = bpy.data.scenes[current_scene].unit_settings.scale_length
#     return scene_length_unit, unit_scale
                

BL_VERSION=Addon.get_blender_version()

# bake groups
LOW_SUFFIX = "_Low"
HIGH_SUFFIX = "_High"
LOWB_SUFFIX = "_low"
HIGHB_SUFFIX = "_high"
LOW_COLLECTION_COLOR = "05"
HIGH_COLLECTION_COLOR = "06"
BAKECOLOR_ATTR = "VertexColor"
UCX_PREFIX = "UCX_"


# hard surface asset
UV_BASE = "UV0_Base"
UV_SWATCH = "UV1_Swatch"
WEARMASK_ATTR = "00_WearMask"
CURVATURE_ATTR="01_Curvature"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
PROP_COLLECTION_COLOR = "04"
DECAL_COLLECTION_COLOR = "03"
PROXY_COLLECTION_COLOR = "02"
DECAL_SUFFIX = "_Decal"
DECAL_PREFIX = "Decal_"
INFODECAL_SUFFIX = "_InfoDecal"
MESHDECAL_SUFFIX = "_MeshDecal"
# hst modifiers
MODIFIER_PREFIX = "HST"
BEVEL_MODIFIER = "HSTBevel"
NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX + "NormalTransfer"
WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX + "WeightedNormal"
TRIANGULAR_MODIFIER = MODIFIER_PREFIX + "Triangulate"
COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX + "VertexColorTransfer"
COLOR_GNODE_MODIFIER = MODIFIER_PREFIX + "GNWearMask"
BLUR_GNODE_MODIFIER = MODIFIER_PREFIX + "GNBlurVertexColor"
SUBD_MODIFIER = MODIFIER_PREFIX + "Subdivision"
SHRINKWRAP_MODIFIER = MODIFIER_PREFIX + "Shrinkwrap"


# material
MATERIAL_PREFIX = "MI_"
SWATCH_MATERIAL = MATERIAL_PREFIX + "HSPropSwatch"
PATTERN_MATERIAL= MATERIAL_PREFIX + "TilePattern"

# import asset
ADDON_NAME = "Hardsurface GameAsset Toolkit"

# ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"

addon_path= Addon.get_install_path()
ASSET_PATH = addon_path / ASSET_DIR
PRESET_FILE_PATH = ASSET_PATH / "Presets.blend"

WEARMASK_NODE = "GN_HSTWearmaskVertColor"
VERTEXCOLORBLUR_NODE = "GN_HSTVertexColorBlur"
LOOKDEV_HDR = "HDR_LookDev_Mid"

# socket
SOCKET_PREFIX = "SOCKET_"
SOCKET_SIZE = 0.2
ORIGIN_PREFIX = "SM_"

# texel density
DEFAULT_TEX_DENSITY = 1024
DEFAULT_TEX_SIZE = 2048

# unreal axis visualizer
AXIS_COLLECTION = "_UE_AXIS_"
AXIS_OBJECT_PREFIX = "__HST_AXIS_"
AXIS_UP_ARROW = AXIS_OBJECT_PREFIX + "UpArrow"
AXIS_FRONT_ARROW = AXIS_OBJECT_PREFIX + "FrontArrow"
AXIS_ORIGIN = AXIS_OBJECT_PREFIX + "Origin"
AXIS_EMPTY = AXIS_OBJECT_PREFIX + "FrontDirection"
AXIS_ARROW = AXIS_OBJECT_PREFIX + "Arrows"

# asset check
CHECK_OK = "OK"

#ue connect
USER_PROFILE_PATH=os.environ['USERPROFILE']
TEMP_PATH=os.path.join(USER_PROFILE_PATH,"AppData\Local\Temp\BlenderHST\\")
UE_SCRIPT = "HardsurfacePropImport"
UE_SCRIPT_CMD = "batch_import_hs_props"
# UE_MESH_DIR = "/Meshes"

BAD_MESHES_COLLECTION="_BadMeshes"

NORMAL_TYPE_ATTRIBUTE="NormalType"
SPEC_TYPE_ATTRIBUTE="SpecType"
NORMAL_TYPE_NUM=5
SPEC_TYPE_NUM=3



class Paths:
    
    """ 文件和路径 """
    ASSET_DIR = "PresetFiles"
    # BLENDER_DIR = Path(resource_path("USER"))
    # ADDON_DIR = BLENDER_DIR / "scripts/addons/" / Addon.NAME
    ADDON_DIR = Addon.get_install_path()
    PRESETS_DIR = ADDON_DIR / ASSET_DIR
    # NODE_FILE = PRESETS_DIR / "GN_WearMaskVertexColor.blend"
    PRESET_FILE = PRESETS_DIR / "Presets.blend"
    CONFIG_FILE= ADDON_DIR / "prefs.json"
    OS_USER_DIR=os.environ['USERPROFILE']
    TEMP_DIR=os.path.join(OS_USER_DIR,"AppData\Local\Temp\BlenderHST\\")

class Names:
    PREVIEW_CAM = "AssetPreviewCamera"
    PREVIEW_IMAGE = "TempAssetPreview.png"
class Const:
    SKM_COLLECTION_COLOR= "07"
    RIG_COLLECTION_COLOR= "07"
    SKM_SUFFIX="_SKM"
    RIG_SUFFIX = "_Rig"
    STATICMESH_PREFIX="SM_"
    SKELETAL_MESH_PREFIX="SK_"
    WORLD_ORIGIN_MATRIX=[[1, 0, 0, 0],[0, 1, 0, 0],[0, 0, 1, 0],[0, 0, 0, 1]]


    #Custom property - HST Custom Type
    CUSTOM_TYPE = "HST_CustomType"
    TYPE_SKM_COLLECTION = "SKM_Collection"
    TYPE_RIG_COLLECTION = "Rig_Collection"
    TYPE_PROP_COLLECTION="Prop_Collection"
    TYPE_DECAL_COLLECTION="Decal_Collection"
    TYPE_BAKE_LOW_COLLECTION="BakeLow_Collection"
    TYPE_BAKE_HIGH_COLLECTION="BakeHigh_Collection"
    TYPE_PROXY_COLLECTION="Proxy_Collection"

    TYPE_STATIC_MESH = "StaticMesh"
    TYPE_SKELETAL_MESH = "SkeletalMesh"
    TYPE_SKELETAL = "Skeletal"
    TYPE_SPLITSKEL = "SplitSkeletal"
    TYPE_PROXY = "Proxy"
    TYPE_DECAL = "Decal"
    TYPE_SOCKET = "Socket"
    TYPE_UCX = "UCX"
    TYPE_BAKE_LOW = "BakeLow"
    TYPE_BAKE_HIGH = "BakeHigh"
    TYPE_PLACEHOLDER = "Placeholder"
    TYPE_SKM = "SKM"
    TYPE_ORIGIN = "Asset_Origin"

    UV_PATTERN = "UV1_Pattern"

    TINT_ATTRIBUTE = "TintMask"
    SPEC_ATTRIBUTE = "SpecMask"

    WORK_VIEWLAYER="HST_WorkViewLayer"