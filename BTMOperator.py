import bpy
import subprocess
import configparser
from bpy_extras.io_utils import ImportHelper
from bpy.utils import register_class, unregister_class

from .BTMFunctions import *
from .VertColorBakeFunctions import *
from .BTMProps import BTMPropGroup
from .BTMPreferences import BTM_AddonPreferences


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
        box3colu = box3.column()
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

        box3colu.operator('object.exportfbx', text="Export Bake Files")
        box3colu.operator('object.openmarmoset', text="Send To Marmoset")
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

        boxcol1.operator('object.moitransfile', text="Use Moi Import")
        boxcol1.operator('object.reloadobj', text="Reload Object")
        boxcol1.prop(btmprops, "add_triangulate", text='Add Triangulate')
        boxcol1.operator('object.bevelpoly', text='Create Transfer Object')
        boxcol1.prop(btmprops, "clean_all_mod", text='Clear all modifiers')
        boxcol1.operator('object.renamehstobject', text='Clean HST Object')
        boxcol1.operator('object.hst_addtransvertcolorproxy', text='Add Transfer Vertex Color Proxy')
        boxcol1.operator('object.hst_bakeproxyvertcolrao', text='Bake Vertex Color AO')

        boxcol2.label(text='Set Parameters')
        boxcol2row = boxcol2.row(align=True)
        # boxcol2row.operator('object.lessbevel', text='Less Bevel')
        # boxcol2row.operator('object.addbevel', text='Add Bevel')
        boxcol2row.prop(btmprops, "sel_bevel_width", text='Width')
        boxcol2row.prop(btmprops, "sel_bevel_segments", text='Segments')    
        boxcol2.operator('object.setparam', text='Set Parameters')
        boxcol2.operator('object.cleanvert', text="Clean Vert")





class BTMLowOperator(bpy.types.Operator):
    bl_idname = "object.btmlow"
    bl_label = "Low Poly"
    
    def execute(self, context):
        is_low = None
        is_high = None
        
        actobj = bpy.context.active_object
        coll = getCollection(actobj)
        collobj = coll.all_objects

        is_low = 1
        coll.color_tag = 'NONE'
        collname = cleanaffix(self, actobj)
        cleanmatslot(self, coll.all_objects)
        collname = editcollandmat(self, is_low, is_high, collname, collobj)
        renamemesh(self, list(collobj), collname)

        return{'FINISHED'}

class BTMHighOperator(bpy.types.Operator):
    bl_idname = "object.btmhigh"
    bl_label = "high Poly"


    def execute(self, context):
        is_low = None
        is_high = None

        actobj = bpy.context.active_object
        coll = getCollection(actobj)
        collobj = coll.all_objects

        is_high = 1
        coll.color_tag = 'NONE'
        collname = cleanaffix(self, actobj)
        cleanmatslot(self, coll.all_objects)
        collname = editcollandmat(self, is_low, is_high, collname, collobj)
        renamemesh(self, list(collobj), collname)

        
        return{'FINISHED'}

class OrgaCollOperator(bpy.types.Operator):
    bl_idname = "object.orgacoll"
    bl_label = "Organize Collections"

    def Fix_Coll_Name(coll):
        fix_coll_name = coll.name.split('_')
        fix_coll_name.pop()
        fix_coll_name.pop()
        fix_coll_name = '_'.join(fix_coll_name)
        return fix_coll_name

    def Get_High_Coll_List(colllist):
        high_coll_list = []

        for coll in colllist:
            if coll.name.split('_')[-1] == 'high':
                high_coll_list.append(coll)
        return high_coll_list
            
    def Get_Low_Coll_List(colllist):
        low_coll_list = []

        for coll in colllist:
            if coll.name.split('_')[-1] == 'low':
                low_coll_list.append(coll)
        return low_coll_list

    def Check_Base_Coll(colllist, high_coll):
        coll: bpy.types.Collection
        have_base_coll = 0
        base_coll_list = []

        for coll in colllist:
            if coll.name == OrgaCollOperator.Fix_Coll_Name(high_coll):
                base_coll_list.append(coll)
                have_base_coll += 1
        return have_base_coll, base_coll_list

    def Clean_Color_Tag(colllist):
        coll: bpy.types.Collection
        for coll in colllist:
            if 'high' or 'low' in coll.name:
                coll.color_tag = 'NONE'

    def execute(self, context):
        high_coll: bpy.types.Collection
        low_coll: bpy.types.Collection
        base_coll: bpy.types.Collection

        colllist = bpy.data.collections
        high_coll_list = OrgaCollOperator.Get_High_Coll_List(colllist)
        low_coll_list = OrgaCollOperator.Get_Low_Coll_List(colllist)

        OrgaCollOperator.Clean_Color_Tag(colllist)
        for high_coll in high_coll_list:
            for low_coll in low_coll_list:
                if OrgaCollOperator.Fix_Coll_Name(high_coll) == OrgaCollOperator.Fix_Coll_Name(low_coll):
                    have_base_coll = OrgaCollOperator.Check_Base_Coll(colllist, high_coll)[0]
                    base_coll_list = OrgaCollOperator.Check_Base_Coll(colllist, high_coll)[1]
                    if have_base_coll:
                        for base_coll in base_coll_list:
                            if high_coll not in list(base_coll.children):
                                base_coll.children.link(high_coll)
                                bpy.context.scene.collection.children.unlink(high_coll)
                            if low_coll not in list(base_coll.children):
                                base_coll.children.link(low_coll)
                                bpy.context.scene.collection.children.unlink(low_coll)
                            base_coll.color_tag = 'COLOR_02'
                    else:
                        basecoll = bpy.data.collections.new(name=OrgaCollOperator.Fix_Coll_Name(high_coll))
                        bpy.context.scene.collection.children.link(basecoll)
                        basecoll.children.link(high_coll)
                        basecoll.children.link(low_coll)
                        bpy.context.scene.collection.children.unlink(high_coll)
                        bpy.context.scene.collection.children.unlink(low_coll)
                        basecoll.color_tag = 'COLOR_02'
        return{'FINISHED'}

class ExportFBXOperator(bpy.types.Operator):
    bl_idname = "object.exportfbx"
    bl_label = "Export FBX"

    def Get_Bakers():
        coll: bpy.types.Collection

        colllist = bpy.data.collections
        base_colllist = []
        for coll in colllist:
            if coll.color_tag == 'COLOR_02':
                base_colllist.append(coll)
        return base_colllist
    
    def Set_Obj_Active(self, active, objectlist):
        obj: bpy.types.Object

        for obj in objectlist:
            obj.select_set(state=active)

    def execute(self, context):
        base_coll: bpy.types.Collection
        base_obj: bpy.types.Object

        props = bpy.context.scene.btmprops
        filename = bpy.path.basename(bpy.data.filepath).split('.')[0]

        get_export_path = BTM_Export_Path()
        base_colllist = ExportFBXOperator.Get_Bakers()
        if bpy.data.is_saved:
            for base_coll in base_colllist:
                self.Set_Obj_Active(1, base_coll.all_objects)
                export_FBX(get_export_path, base_coll.name, True, False)
                self.Set_Obj_Active(0, base_coll.all_objects)
            create_baker_file(base_colllist)
        else:
            MessageBox(text='Please save blender file')

        return{'FINISHED'}

class OpenmMrmosetOperator(bpy.types.Operator):
    bl_idname = "object.openmarmoset"
    bl_label = "Open Marmoset"

    def execute(self, context):
        btb_run_toolbag()
        return{'FINISHED'}

#=========================================================================================
class Rename_Objects(bpy.types.Operator):
    bl_idname = "object.renamehstobject"
    bl_label = "Transform Bevel Poly"

    def execute(self, context): 
        check_coll_object_name()
        return{'FINISHED'}

class Transform_Bevel_Poly(bpy.types.Operator):
    bl_idname = "object.bevelpoly"
    bl_label = "Transform Bevel Poly"
    
    def execute(self, context):
        obj: bpy.types.Object
        bevelmod: bpy.types.BevelModifier

        selobj = bpy.context.selected_objects
        actobj = bpy.context.active_object
        coll = getCollection(actobj)
        if coll:
            collobjs = coll.all_objects
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            renamemesh(self, collobjs, coll.name)
            base_coll = create_base_normal_coll()
            move_backup_base_object(base_coll)
            add_bevel_modifier(selobj)
            add_triangulate_modifier(selobj)
            add_datatransfer_modifier(selobj)
        else:
            MessageBox(text="There is no collection, please put the objects into the collection and continue", title="WARNING", icon='ERROR')
        return{'FINISHED'}

# class Add_Bevel_Operator(bpy.types.Operator):
#     bl_idname = "object.addbevel"
#     bl_label = "Add Bevel"


#     def execute(self, context):
#         batch_edit_bevel()
#         return{'FINISHED'}

# class Less_Bevel_Operator(bpy.types.Operator):
#     bl_idname = "object.lessbevel"
#     bl_label = "Less Bevel"


#     def execute(self, context):
#         batch_edit_bevel()
#         return{'FINISHED'}

class Set_Parameters_Operator(bpy.types.Operator):
    bl_idname = "object.setparam"
    bl_label = "Set Parameters"

    def execute(self, context):
        props = context.scene.btmprops
        # act_scene_name = bpy.context.object.users_scene[0].name
        # length_unit = bpy.data.scenes[act_scene_name].unit_settings.length_unit
        # print(length_unit)

        sel_objs = bpy.context.selected_objects
        for obj in sel_objs:
            for mod in obj.modifiers:
                if mod.name == 'HST Bevel':
                    mod.segments = props.sel_bevel_segments
                    mod.width = props.sel_bevel_width

                    # if length_unit == 'CENTIMETERS':
                    #     mod.width = props.sel_bevel_width*0.1
                    # if length_unit == 'MILLIMETERS':
                    #     mod.width = props.sel_bevel_width*0.1
        return{'FINISHED'}


class Clean_Vertex_Operator(bpy.types.Operator):
    bl_idname = "object.cleanvert"
    bl_label = "clean vert"

    def execute(self, context):
        selobj = bpy.context.selected_objects
        actobj = bpy.context.active_object


        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action='DESELECT')


        for o in selobj:
            along_vert_list = []
            mismatch_vert_list = []

            avc = []
            mvc = []
            mfc = []

            mesh = o.data
            bm = bmesh.from_edit_mesh(mesh)

            bm.verts.ensure_lookup_table()

            along_vert_cand = [v for v in bm.verts if v.hide == False and len(v.link_edges) == 2]
            # mismatch_vert_cand = [v for v in bm.verts if v.hide == False and len(v.link_edges) == 3]
            # mismatch_face_cand = [f for f in bm.faces if f.hide == False and len(f.calc_area) == 5]

            for v in along_vert_cand :
                along_vert_list.append(v)
                avc.append(v.index)

            # for v in mismatch_vert_cand:
            #     mismatch_vert_list.append(v)
            #     mvc.append(v.index)

            # for f in mismatch_face_cand:
            #     mismatch_vert_list.append(f)
            #     mfc.append(f.index)

            # for f in bm.faces:
            #     print(f.calc_area)

            bmesh.ops.dissolve_verts(bm, verts=along_vert_list, use_face_split=False, use_boundary_tear=False)
            bmesh.update_edit_mesh(mesh)

            bm.free()

            bpy.ops.object.mode_set(mode='OBJECT')

            # [v for v in o.data.vertices if v.index in mvc]
            # for v in o.data.vertices:
            #     if v.index in mvc:
            #         v.select = True

            # [v for v in o.data.vertices if v.index in avc]
            # for v in o.data.vertices:
            #     if v.index in avc:
            #         v.select = True

            # [f for f in o.data.polygons if f.index in mfc]
            # for f in o.data.polygons:
            #     if f.index in mfc:
            #         f.select = True
            # # print(vert_index)

        return{'FINISHED'}


class MoiTransStepOperator(bpy.types.Operator, ImportHelper):
    bl_idname = "object.moitransfile"
    bl_label = "Use Moi Transform Step"


    def execute(self, context):
        obj_prop: bpy.types.Property
        act_obj = bpy.context.active_object

        sel_filepath = self.filepath
        moi_config_filepath = os.path.expanduser('~')+"\\AppData\\Roaming\\Moi\\moi.ini"

        config = configparser.ConfigParser()
        config.read(moi_config_filepath)
        if config.get("Settings", "LastFileDialogDirectory"):
            config.set("Settings", "LastFileDialogDirectory", sel_filepath)

            cfgfile = open(moi_config_filepath,'w')
            config.write(cfgfile, space_around_delimiters=False)
            cfgfile.close()
        
        moi_path = bpy.context.preferences.addons["Hard Surface Tool"].preferences.moi_app_path
        if moi_path:
            p = subprocess.Popen([moi_path, sel_filepath])
            returncode = p.wait()
        else:
            MessageBox("No moi software execution file selected")
        if sel_filepath.endswith("step"):
            obj_filepath = sel_filepath.replace("step", "obj")
        elif sel_filepath.endswith("stp"):
            obj_filepath = sel_filepath.replace("stp", "obj")

        import_obj_function(obj_filepath)
        

        # bpy.ops.wm.properties_add(data_path="object.data")

        print(sel_filepath)
        print(obj_filepath)
        print(moi_path)

        return{'FINISHED'}

class ReloadObjOperator(bpy.types.Operator):
    bl_idname = "object.reloadobj"
    bl_label = "Reload Object"

    def execute(self, context):
        act_obj = bpy.context.active_object

        obj_filepath = act_obj["import_path"]
        bpy.data.objects.remove(act_obj)

        import_obj_function(obj_filepath)

        return{'FINISHED'}

class GetVerColOperator(bpy.types.Operator):
    bl_idname = "object.getvercol"
    bl_label = "Get Vertex Color"

    def execute(self, context):
        act_obj = bpy.context.active_object

        verR = bpy.data.meshes[act_obj.to_mesh().name].sculpt_vertex_colors["ID_Color"].data[0].color[0]
        verG = bpy.data.meshes[act_obj.to_mesh().name].sculpt_vertex_colors["ID_Color"].data[0].color[1]
        verB = bpy.data.meshes[act_obj.to_mesh().name].sculpt_vertex_colors["ID_Color"].data[0].color[2]

        bpy.data.brushes["TexDraw"].color = mathutils.Vector((verR, verG, verB))

        return{'FINISHED'}


class BatchSetVerColOperator(bpy.types.Operator):
    bl_idname = "object.setvercol"
    bl_label = "Batch Set Vertex Color"

    def execute(self, context):
        obj: bpy.types.Object
        sel_obj = bpy.context.selected_objects
        act_obj = bpy.context.active_object
        ver_col = bpy.data.brushes["TexDraw"].color

        for obj in sel_obj:
            if "ID_Color" in obj.data.color_attributes:
                colattr = obj.data.color_attributes[0]
            else:
                colattr = obj.data.color_attributes.new(
                    name="ID_Color",
                    type='BYTE_COLOR',
                    domain='CORNER',
                )

        # Create Palette
        pal = bpy.data.palettes.get("ID_Palette")
        if pal is None:
            pal = bpy.data.palettes.new("ID_Palette")
            # add a color to that palette
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)

        elif len(pal.colors) <= 15:
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)
        else:
            pal.colors.remove(pal.colors[0])
            create_palettes_color(pal, ver_col)
            set_all_vertex_color(sel_obj, colattr, ver_col)

        ts = bpy.context.tool_settings   
        ts.image_paint.palette = pal

        return{'FINISHED'}



class TestButtonOperator(bpy.types.Operator):
    bl_idname = "object.testbutton"
    bl_label = "Open Stp File"


    def execute(self, context):
        print(bpy.data.palettes)
        for pal in bpy.data.palettes:
            print(pal)
        # context.tool_settings.image_paint.palette = "Palette"
        # print(context.tool_settings.image_paint.palette)

        return{'FINISHED'}
    

##顶点色烘焙Operator    

#Make Transfer VertexBakeProxy Operator
class HST_CreateTransferVertColorProxy(bpy.types.Operator):
    bl_idname = "object.hst_addtransvertcolorproxy"
    bl_label = "Create Transfer VertexColor Proxy"
    
    def execute(self, context):
        obj: bpy.types.Object

        selobj = bpy.context.selected_objects
        actobj = bpy.context.active_object
        coll = getCollection(actobj)


        if coll:
            collobjs = coll.all_objects
            batchsetvertcolor(selobj)
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            renamemesh(self, collobjs, coll.name)
            transp_coll = create_transproxy_coll()
            make_transpproxy_object(transp_coll)
            add_proxydatatransfer_modifier(selobj)
            bpy.ops.object.select_all(action='DESELECT')
            
            #还原选择状态
            for obj in selobj:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[actobj.name]
        else:
            MessageBox(text="Not in collection, please put selected objects in collections and retry | 所选物体需要在collections中", title="WARNING", icon='ERROR')
        
        return{'FINISHED'}


#烘焙ProxyMesh的顶点色AO Operator
class HST_BakeProxyVertexColorAO(bpy.types.Operator):
    bl_idname = "object.hst_bakeproxyvertcolrao"
    bl_label = "Bake Proxy VertexColor AO"
    
    def execute(self, context):

        obj: bpy.types.Object
        mod: bpy.types.Modifier
        selobj = bpy.context.selected_objects
        transp_coll: bpy.types.Collection
        transp_coll = bpy.data.collections[tvcpcollname]
        proxy_list = []


        for obj in selobj:


        #显示Proxy Collection以便进行烘焙渲染
                
            transp_coll.hide_viewport = False
            transp_coll.hide_render = False


        #find transferproxy from selectd objects' datatranfer modifier, make a list
        for obj in selobj:


            named_color_attributes = bpy.context.object.data.color_attributes
            set_actcolor = named_color_attributes.get(vertcolorname)
            obj.data.attributes.active_color = set_actcolor

        #hide selected list from rendering
            obj.hide_render = True
            obj.select_set(False)    
            for mod in obj.modifiers:
                if mod.name == tvcpmod:
                    proxy_list.append(mod.object)
                    
        #selecte target proxy meshes and make renderable
            for proxy_obj in proxy_list:
                proxy_obj.select_set(True)
                proxy_obj.hide_render = False

        #bake vertex ao        
        bpy.ops.object.bake(type='AO', target='VERTEX_COLORS')


        #reset visibility
        transp_coll.hide_viewport = True
        transp_coll.hide_render = True
        for obj in selobj:
            obj.hide_render = False  
        
        return{'FINISHED'}

classes = (
    HSTPanel,
    BTMPanel,
    BTMLowOperator,
    BTMHighOperator,
    OrgaCollOperator,
    ExportFBXOperator,
    OpenmMrmosetOperator,
    Clean_Vertex_Operator,
    MoiTransStepOperator,
    ReloadObjOperator,
    BatchSetVerColOperator,
    GetVerColOperator,
    TestButtonOperator,
    
    

    Transform_Bevel_Poly,
    Rename_Objects,
    Set_Parameters_Operator,

    HST_CreateTransferVertColorProxy,
    HST_BakeProxyVertexColorAO,
            )

""" def register():
    global classes
    for cls in classes:
        register_class(cls)

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls) """