import bpy
from pathlib import Path
import os
# from mathutils import Matrix

class Addon:
    NAME = "Hardsurface GameAsset Toolkit"

    def get_install_path():
        env_override = os.environ.get("HST_ADDON_ROOT")
        if env_override:
            return Path(env_override)
        return Path(__file__).resolve().parent
    
    def get_blender_version()->float:
            blver=bpy.app.version
            bl_version_num=f"{blver[0]}.{blver[1]}"
            bl_version_num=float(bl_version_num)
            return bl_version_num
    
#TBD: 自动匹配不同的场景单位设置
                

BL_VERSION=Addon.get_blender_version()

# HST 自定义属性名称 (utils 模块使用的别名)
HST_PROP = "HST_CustomType"

# Collection 颜色标签映射
COLLECTION_COLORS = {
    "PROP": "COLOR_04",      # 绿色
    "DECAL": "COLOR_06",     # 紫色
    "BAKE_LOW": "COLOR_01",  # 红色
    "BAKE_HIGH": "COLOR_02", # 橙色
    "SKM": "COLOR_03",       # 黄色
    "RIG": "COLOR_05",       # 蓝色
    "PROXY": "COLOR_07",     # 灰色
}

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
CURVATURE_SIGNED_RAW_ATTR = "02_CurvatureSignedRaw"
CURVATURE_MAGNITUDE_RAW_ATTR = "03_CurvatureMagnitudeRaw"
CURVATURE_CONVEX_RAW_ATTR = "04_CurvatureConvexRaw"
CURVATURE_CONCAVE_RAW_ATTR = "05_CurvatureConcaveRaw"
CURVATURE_SIGNED_ACCUM_RAW_ATTR = "06_CurvatureSignedAccumRaw"
CURVATURE_MAGNITUDE_ACCUM_RAW_ATTR = "07_CurvatureMagnitudeAccumRaw"
CURVATURE_CONVEX_ACCUM_RAW_ATTR = "08_CurvatureConvexAccumRaw"
CURVATURE_CONCAVE_ACCUM_RAW_ATTR = "09_CurvatureConcaveAccumRaw"
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
ASSET_DIR = "preset_files"

addon_path= Addon.get_install_path()
ASSET_PATH = addon_path / ASSET_DIR
PRESET_FILE_PATH = ASSET_PATH / "Presets.blend"

WEARMASK_NODE = "GN_HSTWearmaskVertColor"
VERTEXCOLORBLUR_NODE = "GN_HSTVertexColorBlur"
FEATURE_CHAMFER_GN_NODE = "GN_HSTFeatureChamferSDFPreview"
FEATURE_CHAMFER_GN_MODIFIER = "HST Feature Chamfer GN Preview"
FEATURE_CHAMFER_GN_ASSET_VERSION = 2
FEATURE_CHAMFER_GN_OWNER_TAG = "hst_feature_chamfer_preview_owner"
FEATURE_CHAMFER_GN_FINGERPRINT_TAG = "hst_feature_chamfer_source_fingerprint"
FEATURE_CHAMFER_GN_ASSET_VERSION_TAG = "hst_feature_chamfer_asset_version"
FEATURE_CHAMFER_GN_ASSET_SOURCE_TAG = "hst_feature_chamfer_asset_source"
FEATURE_CHAMFER_GN_ASSET_SOURCE = "tests/fixtures/feature-chamfer-gn-junction-safe.blend:pipecut"
FEATURE_CHAMFER_CURVE_NODE = "GN_HSTFeatureChamferCurvePipe"
FEATURE_CHAMFER_CURVE_DEPENDENCY = "HST Feature Chamfer Curve :: Poly-Curve Info"
FEATURE_CHAMFER_CURVE_ASSET_VERSION = 1
FEATURE_CHAMFER_CURVE_ASSET_VERSION_TAG = "hst_feature_chamfer_curve_asset_version"
FEATURE_CHAMFER_CURVE_ASSET_SOURCE_TAG = "hst_feature_chamfer_curve_asset_source"
FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG = "hst_feature_chamfer_curve_asset_fingerprint"
FEATURE_CHAMFER_CURVE_ASSET_SOURCE = "geo-node.blend:Curve-To-Mesh Even-Thickness"
FEATURE_CHAMFER_CURVE_FINGERPRINT = "e8e64cc6fe6bca15e35fd6ddd1479e7e4e850d09da6996a1734c5e5373b9c363"
FEATURE_CHAMFER_CURVE_DEPENDENCY_FINGERPRINT = "f9e8b8bfd0889a88afb88eea9b7fd48e0c87d68abdd9f60359ff658bd30dd671"
FEATURE_CHAMFER_CURVE_OWNER_TAG = "hst_feature_chamfer_curve_owner"
FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG = "hst_feature_chamfer_curve_source_fingerprint"
FEATURE_CHAMFER_CURVE_OBJECT_TAG = "hst_feature_chamfer_curve_object"
FEATURE_CHAMFER_GN_STATE_TAG = "hst_feature_chamfer_preview_state"
FEATURE_CHAMFER_GN_PARAMETERS_TAG = "hst_feature_chamfer_parameters"
FEATURE_CHAMFER_GN_LAST_ACTION_TAG = "hst_feature_chamfer_last_action"
FEATURE_CHAMFER_PREVIEW_NONE = "NONE"
FEATURE_CHAMFER_PREVIEW_VALID = "PREVIEW_VALID"
FEATURE_CHAMFER_PREVIEW_STALE = "PREVIEW_STALE"
FEATURE_CHAMFER_PATCHED = "PATCHED"
FEATURE_CHAMFER_SOURCE_OBJECT_TAG = "hst_feature_chamfer_source_object"
FEATURE_CHAMFER_ORIGINAL_FACE_ATTRIBUTE = "hst_feature_chamfer_original_face"
FEATURE_CHAMFER_SOURCE_PATCH_ATTRIBUTE = "hst_feature_chamfer_source_patch_id"
FEATURE_CHAMFER_GROOVE_FACE_ATTRIBUTE = "hst_feature_chamfer_groove_face"
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

# UE Connect
USER_PROFILE_PATH = os.environ['USERPROFILE']
TEMP_PATH = os.path.join(USER_PROFILE_PATH, "AppData", "Local", "Temp", "BlenderHST")
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
    ADDON_DIR = Addon.get_install_path()
    PRESETS_DIR = ADDON_DIR / ASSET_DIR  # 复用顶层 ASSET_DIR
    PRESET_FILE = PRESETS_DIR / "Presets.blend"
    CONFIG_FILE = ADDON_DIR / "prefs.json"
    OS_USER_DIR = os.environ['USERPROFILE']
    TEMP_DIR = os.path.join(OS_USER_DIR, "AppData", "Local", "Temp", "BlenderHST")

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
