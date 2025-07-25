# pyright: reportInvalidTypeForm=false   
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

def run_set_vertex_color_ops(self, context):
    """当在UI中点击按钮时，调用set_vertex_color操作"""
    bpy.ops.hst.setobjectvertexcolor()



class UIParams(PropertyGroup):
    """UI参数"""

    vertexcolor: FloatVectorProperty(
        name="Bake Color Picker",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        update=run_set_vertex_color_ops,
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

    normal_type: IntProperty(
        description="Normal Type",
        default=0,
        min=0,
        max=NORMAL_TYPE_NUM,
    )

    spec_type: IntProperty(
        description="Spec Type",
        default=0,
        min=0,
        max=SPEC_TYPE_NUM,
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

    file_prefix: StringProperty(
        name="File Prefix",
        description="文件名前缀，例如AAA，则导出的文件名是SM_AAACollectionName.fbx",
        default="",
        maxlen=24,
    )

    unreal_path: StringProperty(
        name="UE Path",
        description="导入到UE 项目中的路径, 例如 /Game/Level/Props\n /Game=Content目录下的路径",
        default="/Game/Blender",
        maxlen=1024,
        # subtype="DIR_PATH",
    )

    use_armature_as_root: BoolProperty(
        name="Use Armature as RootBone",
        description="导出骨骼作为root bone\n使用blender的fbx导入时勾选\n使用betterfbx导入的不勾选",
        default=True,
    )


class HST_PT_BAKETOOL(bpy.types.Panel):
    bl_idname = "HST_PT_BAKETOOL"
    bl_label = "Bake Prep Tool"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 0



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
        box_column.operator(
                "hst.copy_vertex_color_from_active", text="Copy Vertex Color", icon="COPY_ID"
            )
        box_column.operator(
            "hst.blur_vertexcolor", icon="PROP_OFF"
        )
        



class HST_PT_HST(bpy.types.Panel):
    bl_idname = "HST_PT_HST"
    bl_label = "Hard Surface Prop Toolkit"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 1

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
            "hst.prepcadmesh", text="Prepare CAD Mesh", icon="CHECKMARK"
        )
        box_column.operator(
            "hst.fixcadobj", text="Fix CAD Obj", icon="MESH_CUBE"
        )
        uv_mode_row = box_column.row(align=True)
        uv_mode_row.operator("hst.swatchmatsetup", text="Set Swatch", icon="MATERIAL")
        uv_mode_row.operator("hst.baseuveditmode", text="BaseUV", icon="UV")
        box_column.operator("hst.patternmatsetup", icon="LIGHTPROBE_VOLUME")
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
        
        # box_column.operator("hst.redo_operator", icon="EMPTY_AXIS")
        # box_column.operator("hst.add_asset_origin", icon="EMPTY_AXIS")
        box_column.operator("hst.batch_add_asset_origin", icon="OUTLINER_OB_EMPTY")
        box_column.operator("hst.reset_prop_transform_to_origin", icon="FILE_REFRESH")
        box_column.operator("hst.addsnapsocket", icon="OUTLINER_DATA_EMPTY")
        box_column.prop(parameters, "socket_name", text="Name")
        box_column.separator()
        box_column.label(text="Mark Assets")
        mark_type_row = box_column.row(align=True)
        mark_type_row.operator(
            "hst.markpropcollection", text="Set Prop", icon="OUTLINER_COLLECTION"
        )
        mark_type_row.operator(
            "hst.markdecalcollection", text="Set Decal", icon="OUTLINER_COLLECTION"
        )
        box_column.operator("hst.make_decal_collection", icon="COLLECTION_NEW")
        box_column.operator("hst.mark_tint_object", icon="COLOR")

        box_column.operator("hst.mark_normal_type", icon="NODE_TEXTURE")
        box_column.prop(parameters, "normal_type", text="Normal Type")

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

        

        


class HST_PT_TOOLS(bpy.types.Panel):
    bl_idname = "HST_PT_TOOLS"
    bl_label = "Utilities"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9

    def draw(self, context):
        parameters = context.scene.hst_params
        layout = self.layout
        box = layout.box()
        box_column = box.column()

        box_column.operator(
            "hst.setsceneunits", text="Set Scene Units", icon="SCENE_DATA"
        )
        box_column.operator("hst.cleanvert", text="Clean Verts", icon="VERTEXSEL")
        box_column.operator("hst.sepmultiuser", text="Clean Multi Users", icon="USER")

        box_column.operator(
            "hst.fixduplicatedmaterial", text="Fix Duplicated Mat", icon="MATERIAL"
        )
        box_column.operator("hst.makeassetpreview", icon="RENDERLAYERS")
        box.operator("hst.fill_weight", icon="WPAINT_HLT")
        box.operator("hst.fix_splitmesh", icon="FACE_MAPS")
        box.operator("hst.apply_mirror_modifier", icon="MOD_MIRROR")
        box.operator("hst.remove_empty_mesh", icon="OUTLINER_DATA_MESH")
        box.operator("hst.active_current_collection", icon="OUTLINER_COLLECTION")
        box.operator("hst.sort_collections", icon="SORTALPHA")
        box.operator("hst.isolate_collections_alt", icon="HIDE_OFF")
        box.operator("hst.break_link_from_library", icon="UNLINKED")
        box.operator("hst.reimportwearmasknode", icon="FILE_REFRESH")
        box.operator("hst.mark_attribute", icon="COLOR")
        box.operator("hst.mark_spec_type", icon="NODE_TEXTURE")
        box.prop(parameters, "spec_type", text="Spec Type")
        box.operator("hst.projectdecal", icon="MOD_SHRINKWRAP")
        box.operator("hst.marksharp", icon="SHARPCURVE")

        box.operator("hst.extractucx", icon="MESH_CUBE")
        box.operator("hst.snap_transform", icon="SNAP_GRID")
        
        
        
        

class HST_PT_EXPORT(bpy.types.Panel):
    bl_idname = "HST_PT_Export"
    bl_label = "Export Tools"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 2

    def draw(self, context):
        parameters = context.scene.hst_params
        layout = self.layout
        box = layout.box()
        box_column = box.column()


        box_column.operator(
            "hst.staticmeshexport", text="Export StaticMesh FBX", icon="EXPORT"
        )
        box_column.prop(parameters, "export_path", text="Path")
        box_column.prop(parameters, "file_prefix", text="Prefix")
        box_column.prop(parameters, "use_armature_as_root")
        box_column.operator(
            "hst.open_file_explorer", icon="FILEBROWSER"
        )
        


class HST_PT_Skeletel(bpy.types.Panel):
    bl_idname = "HST_PT_Skeletel"
    bl_label = "Skeletel Tools"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 3

    def draw(self, context):

        layout = self.layout
        box = layout.box()
        box = box.column()


        box.operator(
            "hst.set_scene_unit_for_unreal_rig", icon="HIDE_OFF")
        # box.operator(
        #     "hst.mark_skm_collection", icon="COLLECTION_NEW")
        box.operator(
            "hst.cleanup_ue_skm", icon="ARMATURE_DATA")
        box.operator(
            "hst.quickweight", icon="MOD_VERTEX_WEIGHT")
        box.operator(
            "hst.rename_bones", icon="SORTALPHA")
        box.operator(
            "hst.rename_tree_bones", icon="SORTSIZE")
        box.operator(
            "hst.bone_display_settings", icon="BONE_DATA")
        box.operator(
            "hst.fix_root_bone_for_ue", icon="EMPTY_ARROWS")
        
        # box.operator(
        #     "hst.show_bone_weight", icon="EMPTY_ARROWS")
        
        # box.operator(
        #     "hst.skeletel_separator", icon="ARMATURE_DATA"
        # )
        # box.operator(
        #     "hst.isolate_selected_bones", icon="BONE_DATA"
        # )

