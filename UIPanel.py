from ctypes import alignment
import operator
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

# from .Functions.CommonFunctions import *
# from .Const import *

# def switch_wearkmask_preview(self, context):
#     print(self.b_wearmask_preview)
#     selected_objects = bpy.context.selected_objects
#     selected_meshes = filter_type(selected_objects, "MESH")

#     for mesh in selected_meshes:
#         set_active_color_attribute(mesh, VERTEXCOLOR)

#     current_viewport=bpy.context.area.spaces
#     current_shading_type=current_viewport[0].shading.type
#     current_color_type=current_viewport[0].shading.color_type
#     print(current_shading_type)
#     print(current_color_type)


#     if self.b_wearmask_preview is False:
#         print("Close Wear Mask Preview")
#         current_viewport[0].shading.type=current_shading_type
#         current_viewport[0].shading.color_type=current_color_type

#     if self.b_wearmask_preview is True:
#         print("Preview Wear Mask")
#         viewports=viewport_shading_mode("VIEW_3D", "SOLID",mode="CONTEXT")
#         for viewport in viewports:
#             viewport.shading.color_type = "VERTEX"


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
        default="Box",
        maxlen=24,
    )

    # b_wearmask_preview: BoolProperty(
    #     description="Preview Wear Mask",
    #     default=False,
    #     update=switch_wearkmask_preview,
    # )


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
        # scene=bpy.context.scene
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

        box_column.separator()
        box_column.operator("object.addsnapsocket", text="Add Snap Socket")
        box_column.prop(parameters, "socket_name", text="Name")

        box_column.separator()
        box_column.label(text="View Modes")
        view_row = box_column.row(align=True)
        view_row.operator("object.setuplookdevenv", text="LookDev View")
        view_row.operator("object.previewwearmask", text="Wear Mask View")

        box_column.separator()
        box_column.label(text="Utilities")
        box_column.operator("object.cleanvert", text="Clean Vert")
        box_column.operator("object.sepmultiuser", text="Separate Multi User")
        box_column.operator("object.fixspaceclaimobj", text="Fix SpaceClaim Obj")


classes = (HSTPanel, BTMPanel, UIParams)
