import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup
from .Const import *


def axis_check_toggle(self, context):
    """当在UI中点击按钮时，调用axischeck操作"""
    bpy.ops.hst.axischeck()


class UIParams(PropertyGroup):
    """UI参数"""

    vertexcolor: FloatVectorProperty(
        name="Bake Color Picker",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )

    set_bevel_width: FloatProperty(
        description="设置  HSTBevel 宽度，单位与场景单位一致",
        default=0.5,
        min=0.0,
        max=10.0,
    )

    set_bevel_segments: IntProperty(
        description="设置 HSTBevel 段数", default=1, min=0, max=12
    )

    socket_name: StringProperty(
        description="Socket Name",
        default="Snap",
        maxlen=24,
    )

    texture_density: IntProperty(
        description="Texture Density",
        default=DEFAULT_TEX_DENSITY,
        min=1,
        max=8192,
    )

    texture_size: EnumProperty(
        items=[
            ("512", "512", "Texture Size 512x512"),
            ("1024", "1024", "Texture Size 1024x1024"),
            ("2048", "2048", "Texture Size 2048x2048"),
            ("4096", "4096", "Texture Size 4096x4096"),
            ("8192", "8192", "Texture Size 8192x8192"),
        ],
        default=str(DEFAULT_TEX_SIZE),
    )

    axis_toggle: BoolProperty(
        description="查看Unreal引擎中的前方向",
        default=False,
        update=axis_check_toggle,
    )

    export_path: StringProperty(
        name="Export Path",
        description="fbx导出的路径",
        default="",
        maxlen=1024,
        subtype="DIR_PATH",
    )

    unreal_path: StringProperty(
        name="UE Path",
        description="导入到UE 项目中的路径, 例如 /Game/Level/Props\n /Game=Content目录下的路径",
        default="/Game/Blender",
        maxlen=1024,
        # subtype="DIR_PATH",
    )


class HST_PT_BAKETOOL(bpy.types.Panel):
    bl_idname = "HST_PT_BAKETOOL"
    bl_label = "Bake Prep Tool"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    # @classmethod
    # def poll(cls, context):
    #     return context.object is not None

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()
        box_column.label(text="Group Tools")
        group_row = box_column.row(align=True)
        group_row.operator(
            "hst.setbakecollectionlow",
            text="Set LowPoly",
            icon="OUTLINER_COLLECTION",
        )
        group_row.operator(
            "hst.setbakecollectionhigh",
            text="Set HighPoly",
            icon="OUTLINER_COLLECTION",
        )
        box_column.separator()
        box_column.operator(
            "hst.setobjectvertexcolor", text="Batch Set Color ID", icon="COLOR"
        )
        box_column.prop(context.scene.hst_params, "vertexcolor", text="Color ID Picker")


class HST_PT_HST(bpy.types.Panel):
    bl_idname = "HST_PT_HST"
    bl_label = "Hard Surface Prop Toolkit"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        parameters = context.scene.hst_params
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.label(text="Bevel Tool")
        box_column.operator("hst.hstbevelmods", text="Batch Bevel", icon="MOD_BEVEL")
        box_column.operator(
            "hst.hstbeveltransfernormal",
            text="Bevel & Transfer Normal",
            icon="MOD_DATA_TRANSFER",
        )
        # box_column.separator()
        bevel_setting_row = box_column.row(align=True)
        bevel_setting_row.prop(parameters, "set_bevel_width", text="Width")
        bevel_setting_row.prop(parameters, "set_bevel_segments", text="Segments")
        # box_column.operator("hst.hstbevelsetparam", text="Modify Bevel Parameters")

        box_column.separator()
        box_column.label(text="Vertex Color Bake")
        box_column.operator(
            "hst.hst_addtransvertcolorproxy",
            text="Make Transfer Vertex Color Proxy",
            icon="GROUP_VERTEX",
        )
        box_column.operator(
            "hst.hst_bakeproxyvertcolrao",
            text="Bake Vertex Color AO",
            icon="RESTRICT_RENDER_OFF",
        )

        box_column.separator()
        box_column.operator("hst.cleanhstobject", text="Clean HST Object", icon="TRASH")

        box_column.separator()
        box_column.label(text="Workflow")

        box_column.operator(
            "hst.prepspaceclaimcadmesh", text="Prepare CAD Mesh", icon="CHECKMARK"
        )
        uv_mode_row = box_column.row(align=True)
        uv_mode_row.operator("hst.swatchmatsetup", text="Set Swatch", icon="MATERIAL")
        uv_mode_row.operator("hst.baseuveditmode", text="BaseUV", icon="UV")
        box_column.operator(
            "hst.setbaseuvtexeldensity",
            icon="TEXTURE_DATA",
        )
        td_row = box_column.row(align=True)

        td_row.prop(parameters, "texture_density", text="TD")
        td_row.separator()
        td_row.label(text="px/m")
        td_row.prop(parameters, "texture_size", text="Tex", icon="TEXTURE_DATA")

        box_column.separator()
        box_column.operator("object.adduecollision", icon="MESH_ICOSPHERE")
        box_column.operator("hst.addsnapsocket", icon="OUTLINER_DATA_EMPTY")
        box_column.prop(parameters, "socket_name", text="Name")
        box_column.separator()

        box_column.label(text="View Modes")
        view_row = box_column.row(align=True)
        view_row.operator(
            "hst.setuplookdevenv", text="LookDev View", icon="SHADING_RENDERED"
        )
        view_row.operator(
            "hst.previewwearmask", text="WearMask View", icon="SHADING_WIRE"
        )
        box_column.prop(
            parameters, "axis_toggle", text="Check UE Front Axis", icon="EMPTY_ARROWS"
        )

        box_column.separator()

        box_column.label(text="Export Tools")
        mark_type_row = box_column.row(align=True)
        mark_type_row.operator(
            "hst.markpropcollection", text="Set Prop", icon="OUTLINER_COLLECTION"
        )
        mark_type_row.operator(
            "hst.markdecalcollection", text="Set Decal", icon="OUTLINER_COLLECTION"
        )
        fbx_io_row = box_column.row(align=True)
        # fbx_io_row.operator("hst.importcadfbx", text="Import FBX", icon="IMPORT")
        fbx_io_row.operator(
            "hst.staticmeshexport", text="Export StaticMesh FBX", icon="EXPORT"
        )
        box_column.prop(parameters, "export_path", text="Path")
        # box_column.separator()
        box_column.operator("hst.sendprops_ue", icon="EXPORT")
        box_column.prop(parameters, "unreal_path")

        # box_column.operator("hst.checkassets", text="Check Assets", icon="ERROR")


class HST_PT_TOOLS(bpy.types.Panel):
    bl_idname = "HST_PT_TOOLS"
    bl_label = "Utilities"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        parameters = context.scene.hst_params
        layout = self.layout
        box = layout.box()
        box_column = box.column()
        # box_column.label(text="Utilities")
        box_column.operator(
            "hst.setsceneunits", text="Set Scene Units", icon="SCENE_DATA"
        )
        box_column.operator("hst.cleanvert", text="Clean Verts", icon="VERTEXSEL")
        box_column.operator("hst.sepmultiuser", text="Clean Multi Users", icon="USER")
        box_column.operator(
            "hst.fixspaceclaimobj", text="Fix SpaceClaim Obj", icon="MESH_CUBE"
        )
        box_column.operator(
            "hst.fixduplicatedmaterial", text="Fix Duplicated Mat", icon="MATERIAL"
        )
