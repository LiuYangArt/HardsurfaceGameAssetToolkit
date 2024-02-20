from bpy.utils import resource_path
from pathlib import Path

#hard surface props
UV_BASE = "UV0_Base"
UV_SWATCH = "UV1_Swatch"
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

#import asset
ADDON_DIR = "HardsurfaceGameAssetToolkit"
ASSET_DIR = "PresetFiles"
USER = Path(resource_path("USER"))
ASSET_PATH = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
NODE_FILE_PATH = ASSET_PATH / "GN_WearMaskVertexColor.blend"
PRESET_FILE_PATH = ASSET_PATH / "Presets.blend"

SWATCH_MATERIAL = "MI_HSPropSwatch"
LOOKDEV_HDR = "HDR_LookDev_Mid"
WEARMASK_NODE = "GN_HSTWearmaskVertColor"

