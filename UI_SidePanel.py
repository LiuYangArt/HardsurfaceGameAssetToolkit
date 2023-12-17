import bpy

class BTMPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_BTM"
    bl_label = "Marmoset Bake Tool"
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
        box2 = box.box()
        box2col = box2.column()
        box3 = box.box()
        box3col = box3.column()
        boxrow = box1.row()
        boxcol = box1.column()

        boxcolrow = boxcol.row(align=True)
        boxrow.prop(btmprops, "grouplist")
        boxcolrow.operator('object.btmlow', text="Set Lowpoly")
        boxcolrow.operator('object.btmhigh', text="Set Highpoly")
        boxcol.operator('object.orgacoll', text="Organize Collections")

        box2col.prop(bpy.data.brushes["TexDraw"], "color", text="Vertex Color")
        ts = context.tool_settings
        if ts.image_paint.palette:
            box2col.template_palette(ts.image_paint, "palette", color=True)
        box2col.operator('object.setvercol')
        box2col.operator('object.getvercol')

        box3col.operator('object.exportfbx', text="Export Bake Files")
        box3col.operator('object.openmarmoset', text="Send To Marmoset")
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

        #boxcol1.operator('object.moitransfile', text="Use Moi Import")
        #boxcol1.operator('object.reloadobj', text="Reload Object")
        boxcol1.label(text='Bevel Tool')
        boxcol1.prop(btmprops, "add_triangulate", text='Add Triangulate')
        boxcol1.operator('object.bevelpoly', text='Create Transfer Object')
        
        boxcol1.prop(btmprops, "clean_all_mod", text='Clear all modifiers')
        boxcol1.operator('object.renamehstobject', text='Clean HST Object')
        boxcol2.label(text='Vertex Color Bake')
        boxcol2.operator('object.hst_addtransvertcolorproxy', text='Add Transfer Vertex Color Proxy')
        boxcol2.operator('object.hst_bakeproxyvertcolrao', text='Bake Vertex Color AO')

        boxcol3.label(text='Set Parameters')
        boxcol3row = boxcol3.row(align=True)
        # boxcol2row.operator('object.lessbevel', text='Less Bevel')
        # boxcol2row.operator('object.addbevel', text='Add Bevel')
        boxcol3row.prop(btmprops, "set_bevel_width", text='Width')
        boxcol3row.prop(btmprops, "set_bevel_segments", text='Segments')    
        boxcol3.operator('object.setparam', text='Set Parameters')
        boxcol3.operator('object.cleanvert', text="Clean Vert")


classes = (
    HSTPanel,
    BTMPanel,
            )
