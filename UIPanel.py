import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup
from .Const import *


def axis_check_toggle(self, context):
    """当在UI中点击按钮时，调用axischeck操作"""
    bpy.ops.object.axischeck()


class UIParams(PropertyGroup):
    """UI参数"""

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
        default="",
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


class BTMPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_BTM"
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
        group_column = box.column()
        group_column.label(text="Group Tools")
        group_row = group_column.row(align=True)
        group_row.operator("object.btmlow", text="Set LowPoly")
        group_row.operator("object.btmhigh", text="Set HighPoly")


class HSTPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_HST"
    bl_label = "Hard Surface Tool"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        parameters = context.scene.hst_params
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.label(text="Bevel Tool")
        box_column.operator("object.hstbevelmods", text="Batch Bevel")
        box_column.operator(
            "object.hstbeveltransfernormal", text="Bevel & Transfer Normal"
        )
        # box_column.separator()
        bevel_setting_row = box_column.row(align=True)
        bevel_setting_row.prop(parameters, "set_bevel_width", text="Width")
        bevel_setting_row.separator()
        bevel_setting_row.prop(parameters, "set_bevel_segments", text="Segments")
        # box_column.operator("object.hstbevelsetparam", text="Modify Bevel Parameters")

        box_column.separator()
        box_column.label(text="Vertex Color Bake")
        box_column.operator(
            "object.hst_addtransvertcolorproxy", text="Make Transfer Vertex Color Proxy"
        )
        box_column.operator(
            "object.hst_bakeproxyvertcolrao", text="Bake Vertex Color AO"
        )

        box_column.separator()
        box_column.operator("object.cleanhstobject", text="Clean HST Object")

        box_column.separator()
        box_column.label(text="Workflow")
        box_column.operator("object.prepspaceclaimcadmesh", text="Prepare CAD Mesh")
        uv_mode_row = box_column.row(align=True)
        uv_mode_row.operator("object.swatchmatsetup", text="SetSwatch")
        uv_mode_row.operator("object.baseuveditmode", text="BaseUV")
        box_column.operator(
            "object.setbaseuvtexeldensity", text="Set BaseUV Texel Density"
        )
        td_row = box_column.row(align=True)
        td_row.label(text="Texel Density")
        td_row.separator()
        td_row.prop(parameters, "texture_density", text="")
        td_row.separator()
        td_row.label(text="px/m")
        box_column.prop(
            parameters, "texture_size", text="Tex Size", icon="TEXTURE_DATA"
        )

        box_column.separator()
        box_column.operator("object.addsnapsocket", text="Add Snap Socket")
        box_column.prop(parameters, "socket_name", text="Name")

        box_column.separator()
        box_column.label(text="View Modes")
        view_row = box_column.row(align=True)
        view_row.operator(
            "object.setuplookdevenv", text="LookDev View", icon="SHADING_RENDERED"
        )
        view_row.separator()
        view_row.operator(
            "object.previewwearmask", text="WearMask View", icon="SHADING_SOLID"
        )
        box_column.prop(
            parameters, "axis_toggle", text="Check UE Front Axis", icon="EMPTY_AXIS"
        )

        box_column.separator()
        box_column.label(text="Utilities")
        box_column.operator("object.setsceneunits", text="Set Scene Units")
        box_column.operator("object.cleanvert", text="Clean Vert")
        box_column.operator("object.sepmultiuser", text="Separate Multi User")
        box_column.operator("object.fixspaceclaimobj", text="Fix SpaceClaim Obj")


classes = (HSTPanel, BTMPanel, UIParams)
