import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty)
from bpy.types import PropertyGroup
# from bpy.utils import register_class, unregister_class

class BTMPropGroup(PropertyGroup):

    grouplist: EnumProperty(
        name="Group list",
        description="Apply Data to attribute.",
        items=[ ('_01', "Group 1", ""),
                ('_02', "Group 2", ""),
                ('_03', "Group 3", ""),
                ('_04', "Group 4", ""),
                ('_05', "Group 5", ""),
                ('_06', "Group 6", ""),
                ('_07', "Group 7", ""),
                ('_08', "Group 8", ""),
                ('_09', "Group 9", ""),
                ('_10', "Group 10", ""),
               ]
        )

    set_bevel_width: FloatProperty(
        description="设置  HSTBevel 宽度", 
        default=0.01,
        min=0.0, max=1.0
        )

    set_bevel_segments: IntProperty(
        description="设置 HSTBevel 段数", 
        default=1,
        min=0, max=12
        )

    add_triangulate: BoolProperty(
        description="是否同时添加三角化修改器", 
        default=True
        )

    clean_all_mod: BoolProperty(
        description="Clear all modifiers.", 
        default=True
        )

class BTMCollection (PropertyGroup):
    baker_id: IntProperty()





class BTMPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_BTM"
    bl_label = "Bake Prep Tool"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    @classmethod
    def poll(cls, context):
        return (context.object is not None)

    def draw(self, context):
        btmprops = context.scene.btmprops
        act_obj = bpy.context.active_object

        layout = self.layout
        box = layout.box()
        box1 = box.box()
        # box2 = box.box()
        # box2col = box2.column()
        # box3 = box.box()
        # box3col = box3.column()
        # boxrow = box1.row()
        boxcol = box1.column()

        boxcolrow = boxcol.row(align=True)
        #for what
        #boxrow.prop(btmprops, "grouplist")
        boxcolrow.operator('object.btmlow', text="Set LowPoly")
        boxcolrow.operator('object.btmhigh', text="Set HighPoly")
        #分类规则有待调整
        #boxcol.operator('object.orgacoll', text="Organize Collections")

        # box2col.prop(bpy.data.brushes["TexDraw"], "color", text="Vertex Color")
        # ts = context.tool_settings
        # if ts.image_paint.palette:
        #     box2col.template_palette(ts.image_paint, "palette", color=True)
        # box2col.operator('object.setvercol')
        # box2col.operator('object.getvercol')

        #buggy 后面找时间修
        #box3col.operator('object.exportfbx', text="Export Bake Files")
        #box3col.operator('object.openmarmoset', text="Send To Marmoset")
        #box3.operator('object.testbutton', text="Test Button")


class HSTPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_HST"
    bl_label = "Hard Surface Tool"
    bl_category = "HST"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):
        btmprops = context.scene.btmprops

        layout = self.layout
        box = layout.box()
        boxcol1 = box.column()
        boxcol2 = box.column()
        boxcol3 = box.column()
        boxcol4 = box.column()

        #boxcol1.operator('object.moitransfile', text="Use Moi Import")
        #boxcol1.operator('object.reloadobj', text="Reload Object")
        boxcol1.label(text='Bevel Tool')
        boxcol1.prop(btmprops, "add_triangulate", text='Add Triangulate Modifier')
        boxcol1.operator('object.hstbevelmods', text='Batch Bevel')
        boxcol1.operator('object.hstbeveltransfernormal', text='Bevel & Transfer Normal')
        



        boxcol2.label(text='Set HSTBevel Parameters')
        boxcol2row = boxcol2.row(align=True)
        # boxcol2row.operator('object.lessbevel', text='Less Bevel')
        # boxcol2row.operator('object.addbevel', text='Add Bevel')
        boxcol2row.prop(btmprops, "set_bevel_width", text='Width')
        boxcol2row.prop(btmprops, "set_bevel_segments", text='Segments')    
        boxcol2.operator('object.hstbevelsetparam', text='Set Bevel Parameters')
        

        boxcol3.label(text='Vertex Color Bake')
        boxcol3.operator('object.hst_addtransvertcolorproxy', text='Make Transfer Vertex Color Proxy')
        boxcol3.operator('object.hst_bakeproxyvertcolrao', text='Bake Vertex Color AO')



        boxcol4.label(text='Utilities') 
        boxcol4.operator('object.cleanhstobject', text='Clean HST Object')
        boxcol4.operator('object.cleanvert', text="Clean Vert")
classes = (
    HSTPanel,
    BTMPanel,
    BTMPropGroup,
BTMCollection)

