# pyright: reportInvalidTypeForm=false
import bpy
from bpy.props import StringProperty


DEFAULT_TOOLBAG_APP_PATH = r"C:\Program Files\Marmoset\Toolbag 5\Toolbag.exe"


class HST_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    toolbag_app_path: StringProperty(
        name="Toolbag Path",
        description="Marmoset Toolbag 5 executable path or install directory",
        default=DEFAULT_TOOLBAG_APP_PATH,
        subtype="FILE_PATH",
        maxlen=1024,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "toolbag_app_path")
