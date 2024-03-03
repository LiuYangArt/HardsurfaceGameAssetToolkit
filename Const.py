from bpy.utils import resource_path
from pathlib import Path
import os

# bake groups
LOW_SUFFIX = "_low"
HIGH_SUFFIX = "_high"
LOW_COLLECTION_COLOR = "05"
HIGH_COLLECTION_COLOR = "06"
BAKECOLOR_ATTR = "VertexColor"
UCX_PREFIX = "UCX_"

# hard surface asset
UV_BASE = "UV0_Base"
UV_SWATCH = "UV1_Swatch"
WEARMASK_ATTR = "WearMask"
TRANSFER_COLLECTION = "_TransferNormal"
TRANSFER_MESH_PREFIX = "Raw_"
TRANSFER_PROXY_COLLECTION = "_TransferProxy"
TRANSFERPROXY_PREFIX = "TRNSP_"
PROP_COLLECTION_COLOR = "04"
DECAL_COLLECTION_COLOR = "03"
PROXY_COLLECTION_COLOR = "02"
DECAL_SUFFIX = "_Decal"
INFODECAL_SUFFIX = "_InfoDecal"
MESHDECAL_SUFFIX = "_MeshDecal"
# hst modifiers
MODIFIER_PREFIX = "HST"
BEVEL_MODIFIER = "HSTBevel"
NORMALTRANSFER_MODIFIER = MODIFIER_PREFIX + "NormalTransfer"
WEIGHTEDNORMAL_MODIFIER = MODIFIER_PREFIX + "WeightedNormal"
TRIANGULAR_MODIFIER = MODIFIER_PREFIX + "Triangulate"
COLOR_TRANSFER_MODIFIER = MODIFIER_PREFIX + "VertexColorTransfer"
COLOR_GEOMETRYNODE_MODIFIER = MODIFIER_PREFIX + "GNWearMask"

# material
MATERIAL_PREFIX = "MI_"
SWATCH_MATERIAL = MATERIAL_PREFIX + "HSPropSwatch"

# import asset
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"
USER = Path(resource_path("USER"))
ASSET_PATH = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
NODE_FILE_PATH = ASSET_PATH / "GN_WearMaskVertexColor.blend"
PRESET_FILE_PATH = ASSET_PATH / "Presets.blend"

WEARMASK_NODE = "GN_HSTWearmaskVertColor"
LOOKDEV_HDR = "HDR_LookDev_Mid"

# socket
SOCKET_PREFIX = "SOCKET_"
SOCKET_SIZE = 0.2

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

class AddonPath:
    SETTING_DIR = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
    CONFIG_FILE= "prefs.json"
    USER_PROFILE_PATH=os.environ['USERPROFILE']
    TEMP_PATH=os.path.join(USER_PROFILE_PATH,"AppData\Local\Temp\BlenderHST\\")

class Addon:
    NAME = "HardsurfaceGameAssetToolkit"