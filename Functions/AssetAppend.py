import bpy

from bpy.utils import resource_path
from pathlib import Path

USER = Path(resource_path('USER'))
src = USER / "scripts/addons" / "myaddon" / "PresetFiles"

file_path = src / "GN_WearMaskVertexColor.blend"
inner_path = "NodeTree"
object_name = "GN_HSTWearmaskVertColor"

bpy.ops.wm.append(
    filepath=str(file_path / inner_path / object_name),
    directory=str(file_path / inner_path),
    filename=object_name
)