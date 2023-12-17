import os
import subprocess
import tempfile
import mathutils

import bmesh
import bpy

from .UI_SidePanel import BTMPropGroup


def MessageBox(text="", title="WARNING", icon='ERROR'):
    def draw(self, context):
        self.layout.label(text=text)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

def editcleancollname(self, collname):
    if '.' in collname:
        cleancollname = collname.split('.')
        cleancollname.pop()
        cleancollname = '.'.join(cleancollname)
    else:
        cleancollname = collname
    if '_' in collname:
        cleancollname = collname.split('_')
        cleancollname.pop()
        cleancollname = '_'.join(cleancollname)
    else:
        cleancollname = collname
    return cleancollname

def setcollcountname(self, collname):
    countprop = bpy.context.scene.btmprops
    countcollname = collname+countprop.grouplist
    return countcollname

def getCollection(targetobj: bpy.types.Object):
    targetcollection = None

    item_collection:bpy.types.Collection
    for item_collection in bpy.data.collections:
        item_object: bpy.types.Object
        for item_object in item_collection.objects:
            if item_object == targetobj:
                targetcollection = item_collection
                break
            
    return targetcollection
    
#清理模型材质通道仅剩一个
def cleanmatslot(self, collectionobject):
    matcount = 0
    num = 0
    for i in collectionobject:
        matcount = len(i.material_slots)
        bpy.context.object.active_material_index = matcount - 1
        lastmatcount = matcount - 1

        while num < lastmatcount:
            bpy.ops.object.material_slot_remove()
            num = num + 1
            print('remove material')

def cleanaffix(self, actobj):
    isnumaffix = 0
    collname = None
    actobj = bpy.context.active_object
    for c in bpy.data.collections:
        for o in c.objects:
            if o.name == actobj.name:
                collname = c.name
    numlist = ['.001', '.002', '.003', '.004', '.005']

    if '_' in collname:
        for num in numlist:
            if num in collname:
                isnumaffix = 1

        if isnumaffix == 1:
            numcollname = collname.split('.')
            numcollname.pop()
            numcollname = '.'.join(numcollname)
        else:
            numcollname = collname
            
        fixcollname = numcollname.split('_')
        fixcollname.pop()
        fixcollname = '_'.join(fixcollname)

    else:
        for num in numlist:
            if num in collname:
                isnumaffix = 1

        if isnumaffix == 1:
            numcollname = collname.split('.')
            numcollname.pop()
            numcollname = '.'.join(numcollname)
        else:
            numcollname = collname
        fixcollname = numcollname

    bpy.data.collections[collname].name = fixcollname
    return fixcollname


#修改collection后缀为_low
def editcollname(self, collname, affix):
        getcoll: bpy.types.Collection
        actcoll: bpy.types.Collection

        actcoll = bpy.context.active_object.users_collection[0]
        for getcoll in bpy.data.collections:
            if actcoll.name == getcoll.name:
                getcoll.name = collname+affix
                collname = collname+affix
                break
        return collname


def editcollandmat(self, is_low, is_high, collname, collobj):        
    lowmatexist = None
    highmatexist = None
    cleancollname = None
    collcountname = None
    callname = ''
    affix = ''

    if is_low == 1:
        affix = '_low'
        cleancollname = editcleancollname(self, collname)
        collcountname = setcollcountname(self, cleancollname)
        collname = editcollname(self, collcountname, affix)
        targetmaterial: bpy.types.Material
        for targetmaterial in bpy.data.materials:
            if targetmaterial.name == callname:
                for i in collobj:
                    bpy.data.objects[i.name].active_material = bpy.data.materials[callname]
                    break
                lowmatexist = lowmatexist = 1
            break
        if lowmatexist == None:
            createmat(self, cleancollname, collobj)
        return collname
                
    if is_high == 1:
        affix = '_high'
        cleancollname = editcleancollname(self, collname)
        collcountname = setcollcountname(self, cleancollname)
        collname = editcollname(self, collcountname, affix)
        for m in bpy.data.materials:
            if m.name == collname:
                highmatexist = highmatexist = 1
                for i in collobj:
                    if i.type == 'MESH':
                        bpy.data.objects[i.name].active_material = bpy.data.materials[m.name]
                        break
                    break
            break
        if highmatexist == None:
            createmat(self, collname, collobj)
        return collname

def createmat(self, collname, collobj):
    new_mat = bpy.data.materials.new(name=collname)
    new_mat.use_nodes = True
    
    for i in collobj:
        bpy.data.objects[i.name].active_material = bpy.data.materials[collname]


#重命名模型类型的object
def renamemesh(self, collobjlist, collname):
    for i,o in enumerate(collobjlist):
        if o.type=='MESH':                                      #检测对象是否为mesh
                o.name = collname+'_'+str(i+1).zfill(2)



#=========================================================================================
def export_FBX(folder, filename, selected, activecollection):
    bpy.ops.export_scene.fbx(filepath=(folder + filename + ".fbx"),
                            check_existing=True,
                            filter_glob="*.fbx",
                            use_selection=selected,
                            use_active_collection=activecollection,
                            global_scale=1,
                            apply_unit_scale=True,
                            apply_scale_options='FBX_SCALE_NONE',
                            bake_space_transform=True,
                            object_types={'MESH'},
                            use_mesh_modifiers=True,
                            use_mesh_modifiers_render=True,
                            mesh_smooth_type='OFF',
                            use_mesh_edges=False,
                            use_tspace=False,
                            use_custom_props=False,
                            add_leaf_bones=False,
                            primary_bone_axis='Y',
                            secondary_bone_axis='X',
                            use_armature_deform_only=False,
                            armature_nodetype='NULL',
                            bake_anim=False,
                            bake_anim_use_all_bones=False,
                            bake_anim_use_nla_strips=False,
                            bake_anim_use_all_actions=False,
                            bake_anim_force_startend_keying=False,
                            bake_anim_step=1,
                            bake_anim_simplify_factor=1,
                            path_mode='AUTO',
                            embed_textures=False,
                            batch_mode='OFF',
                            use_batch_own_dir=True,
                            use_metadata=True,
                            axis_forward='-Y',
                            axis_up='Z',
                            )

def BTM_Export_Path():
    btm_export_path = None
    filepath = None
    bakedirpath = None

    if bpy.data.is_saved == True:
        filepath = bpy.path.abspath('//')
        bakedirpath = filepath+'Bake\\'
        if not os.path.exists(bakedirpath):
            os.mkdir(bakedirpath)
            btm_export_path = bakedirpath
        btm_export_path = bakedirpath
    else:
        MessageBox('Please Save File')
    return btm_export_path

def set_BTM_loader():
    path = "" + tempfile.gettempdir()
    path = '/'.join(path.split('\\'))
    marmoset_loader = path + "/bake_load_marmoset.py"
    return marmoset_loader

def create_baker_file(bakers):
    baker_list = create_baker_list()
    with open(baker_list, "w+") as list_file:
        print(bakers)
        for baker in bakers:
            baker_name = baker.name
            list_file.write("BaseGroup:%s\n" % (baker_name))
            
def create_baker_list():
    path = "" + tempfile.gettempdir()
    path = '/'.join(path.split('\\'))
    bake_list = path + "/bake_list.txt"
    return bake_list

def get_preset_path():
    preset_path = __file__.split('\\')
    preset_path.pop()
    preset_path = '/'.join(preset_path) + '/Preset File/Bake_Presets.tbbake'
    return preset_path

def Fix_Path(path):
    path = '/'.join(path.split('\\'))
    return path

def py_build_up(ExportFolderPath):
    marmoset_loader = set_BTM_loader()
    baker_list = create_baker_list()
    import_path = Fix_Path(BTM_Export_Path())
    preset_path = get_preset_path()
    texture_folder = Fix_Path(BTM_Export_Path() + 'Tex')

    # props = bpy.context.preferences.addons["BTM"].preferences
    # outputTextureFormat = props.toolbag_texture_format

    with open(marmoset_loader, "w+") as loader:
        loader.write("import mset\n")
        loader.write("import os\n")
        loader.write("import io\n")
        loader.write("\n")
        loader.write("\n")
        loader.write("""\
for ob in mset.getAllObjects():
    if isinstance(ob, mset.BakerObject): ob.destroy()""")
        loader.write("\n")
        loader.write("import_path = \"%s\"\n" % (str(import_path)))
        loader.write("import_list = \"%s\"\n" % (str(baker_list)))
        loader.write("preset_path = \"%s\"\n" % (str(preset_path)))
        loader.write("texture_folder = \"%s\"\n" % (str(texture_folder)))
        loader.write("outputTextureFormat = \"%s\"\n" % ('PSD'))
        loader.write("""\
if os.path.exists(import_list):
    with open(import_list) as bakers_list:
        for line in bakers_list:
            line = line.strip()
            split = line.split(":")
            if split[0] == "BaseGroup":
                quickload_fbx = import_path + split[-1] + ".fbx"
                print(quickload_fbx)
                baker = mset.BakerObject()
                baker.name = split[-1]
                baker.outputPath = str(texture_folder + "/" + split[-1] + "." + outputTextureFormat)""")
        loader.write("\n")
        # Bit depth of the output format; must be one of the following values: 8, 16, 32.
        loader.write("                baker.outputBits = %s\n" % ('16'))
        # Sample count of the bake output; must be one of the following values: 1, 4, 16.
        loader.write("                baker.outputSamples = %s\n" % ('64'))
        # Determines whether the baked maps will be stored inside a single PSD file, or multiple files.
        loader.write("                baker.outputSinglePsd = %s\n" % (False))
        # Determines how much the baked result will be softened; must be between 0.0 and 1.0.
        loader.write("                baker.outputSoften = %s\n" % (0.0))
        # The width in pixels of the baked textures.
        loader.write("                baker.outputWidth = %s\n" % ('2048'))
        loader.write("                baker.outputHeight = %s\n" % ('2048'))
        # The file path where the baked textures will be stored.
        # loader.write("                baker.outputPath = '%s'\n" % (import_path + '\\Tex'))
        loader.write("""
                baker.loadPreset(preset_path)
                baker.importModel(quickload_fbx)
                baker.addGroup(split[-1])
""")

def btb_run_toolbag():
    props = bpy.context.scene.btmprops 
    toolbag = bpy.context.preferences.addons["HardsurfaceGameAssetToolkit"].preferences.toolbag_app_path
    folder = BTM_Export_Path()
    if toolbag:
        if folder:
            py_build_up(folder)
            marmoset_loader = set_BTM_loader()
            print(toolbag)
            print(marmoset_loader)
            subprocess.Popen([toolbag, marmoset_loader])
        else:
            MessageBox("Export folder not defined!")
    else:
        MessageBox("Path to Marmoset Toolbag 3 is not defined!")

#=========================================================================================

def create_base_normal_coll():
    base_normal_coll_exist = 0
    colls = bpy.data.collections

    for coll in bpy.data.collections:
        if 'Base_Normal' in coll.name:
            base_normal_coll_exist += 1
            continue
    
    if base_normal_coll_exist == 1:
        for coll in colls:
            if coll.name == 'Base_Normal_Shape':
                base_coll = coll
        return base_coll
    else:
        base_coll = bpy.data.collections.new(name='Base_Normal_Shape')

        base_coll.hide_viewport = True
        base_coll.hide_render = True
        # base_coll.hide_select = True

        base_coll.color_tag = 'COLOR_08'
        bpy.context.scene.collection.children.link(base_coll)
        return base_coll

def check_BNS_exist(base_coll, obj):
    base_coll: bpy.types.Collection
    obj: bpy.types.Object

    BNS_exist = 0

    for base_obj in base_coll.all_objects:
        if base_obj.name == 'BNS_' + obj.name:
            BNS_exist += 1
            return  BNS_exist
    

def move_backup_base_object(base_coll):
    obj: bpy.types.Object
    copy_obj: bpy.types.Object
    base_coll: bpy.types.Collection

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    bns_coll = None

    for obj in selobj:
        if obj.type == 'MESH':
            if check_BNS_exist(base_coll, obj) != 1:

                copy_obj = bpy.data.objects[obj.name].copy()
                for coll in bpy.data.collections:
                    if coll.name == 'Base_Normal_Shape':
                        bns_coll = coll
                bns_coll.objects.link(copy_obj)
                copy_obj.name = 'BNS_' + obj.name

                copy_obj.parent = obj
                if copy_obj.modifiers:
                    for copy_mod in copy_obj.modifiers:
                        copy_obj.modifiers.remove(copy_mod)
        else:
            print('is not mesh')
            break
    bpy.ops.object.make_single_user(object=True, obdata=True, material=False, animation=False, obdata_animation=False)

        
            
    
def add_bevel_modifier(selobj):
    bevelmod: bpy.types.Modifier
    obj: bpy.types.Object

    check_modifier = 0
    check_sharp = 0
    check_bevel = 0
    mesh = bpy.context.object.data

    for obj in selobj:
        bpy.data.meshes[obj.to_mesh().name].use_auto_smooth = True
        for m in obj.modifiers:
            if m.name == 'HST Bevel':
                check_modifier += 1
                continue
        if check_modifier == 0:
            #check sharp edge, if yes, add bevel weight by sharp; if no, set bevel modifier type = angle
            if 'sharp_edge' in mesh.attributes:
                check_sharp += 1
                if 'bevel_weight_edge' in mesh.attributes:
                    check_bevel += 1
                else:
                    bevel_weight_attr = mesh.attributes.new("bevel_weight_edge", "FLOAT", "EDGE")
                    for idx, e in enumerate(mesh.edges):
                        bevel_weight_attr.data[idx].value = 1.0 if e.use_edge_sharp else 0.0

            else:
                check_sharp += 0
                bevel_weight_attr = mesh.attributes.new("bevel_weight_edge", "FLOAT", "EDGE")
                for idx, e in enumerate(mesh.edges):
                    bevel_weight_attr.data[idx].value = 1.0 if e.use_edge_sharp else 0.0
    
            if 'bevel_weight_edge' in mesh.attributes:
                check_bevel += 1
            else:
                check_bevel += 1

            print(check_sharp)
            if check_sharp:
                bevelmod = obj.modifiers.new(name='HST Bevel', type='BEVEL')
                bevelmod.limit_method = 'WEIGHT'
                bevelmod.offset_type = 'WIDTH'
                bevelmod.width = 0.005
                bevelmod.use_clamp_overlap = False
                bevelmod.harden_normals = True
                bevelmod.loop_slide = True
                bevelmod.segments = 1
                bevelmod.profile = 0.7
                continue
            else:
                bevelmod = obj.modifiers.new(name='HST Bevel', type='BEVEL')
                bevelmod.limit_method = 'ANGLE' 
                bevelmod.offset_type = 'WIDTH'
                bevelmod.width = 0.005
                bevelmod.angle_limit = 0.523599
                bevelmod.use_clamp_overlap = False
                bevelmod.harden_normals = True
                bevelmod.loop_slide = True
                bevelmod.segments = 1
                bevelmod.profile = 0.7
                continue

def add_datatransfer_modifier(selobj):
    datatransfermod: bpy.types.Modifier

    check_modifier = 0

    for obj in selobj:
        for m in obj.modifiers:
            if m.name == 'HST DataTransfer':
                check_modifier += 1
                continue
    
        targobj = bpy.data.objects['BNS_' + obj.name]
        print(targobj)
        if not check_modifier:
            datatransfermod = obj.modifiers.new(name='HST DataTransfer', type='DATA_TRANSFER')
            datatransfermod.object = targobj
            datatransfermod.use_loop_data = True
            datatransfermod.data_types_loops = {'CUSTOM_NORMAL'}
            datatransfermod.loop_mapping = 'POLYINTERP_NEAREST'
        else:
            datatransfermod = obj.modifiers['HST DataTransfer']
            datatransfermod.object = targobj
            continue

def add_triangulate_modifier(selobj):
    triangulatemod: bpy.types.Modifier

    check_modifier = 0

    for obj in selobj:
        for m in obj.modifiers:
            if m.name == 'HST Triangulate':
                check_modifier += 1
                continue
    
        targobj = bpy.data.objects['BNS_' + obj.name]
        print(targobj)
        if not check_modifier:
            triangulatemod = obj.modifiers.new(name='HST Triangulate', type='TRIANGULATE')
            triangulatemod.keep_custom_normals = True
            triangulatemod.min_vertices = 5
            triangulatemod.quad_method = 'SHORTEST_DIAGONAL'
            
        else:
            triangulatemod = obj.modifiers['HST Triangulate']
            triangulatemod.keep_custom_normals = True
            triangulatemod.min_vertices = 5
            triangulatemod.quad_method = 'SHORTEST_DIAGONAL'
            continue


def check_coll_object_name():
    obj: bpy.types.Object
    mod: bpy.types.Modifier
    copy_obj: bpy.types.Object
    base_coll: bpy.types.Collection
    base_obj: bpy.types.Object

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    props = bpy.context.scene.btmprops
    keep_list = []
    delete_list = []
    bevel_dict = {}
    base_coll = bpy.data.collections['Base_Normal_Shape']

    if props.clean_all_mod == True:
        for obj in selobj:
            for mod in obj.modifiers:
                if mod.name == 'HST DataTransfer':
                    delete_list.append(mod.object)
                if mod.name == 'HST Bevel':
                    if mod.width != 0.005:
                        bevel_dict[obj.name] = mod.width
                        print(mod)
            print(bevel_dict)
            obj.modifiers.clear()
        for delete_obj in delete_list:
            if delete_obj:
                bpy.data.objects.remove(delete_obj)

    else:
        base_coll.hide_viewport = False
        for obj in base_coll.all_objects:
            for coll in bpy.data.collections:
                if coll.name in obj.name:
                    keep_list.append(obj)
                    continue

        for obj in base_coll.all_objects:
            if obj in keep_list:
                print(obj.name)
            else:
                bpy.data.objects[obj.name].select_set(True)
        bpy.ops.object.delete(use_global=False)
        base_coll.hide_viewport = True

    return bevel_dict

def batch_edit_bevel():
    props = bpy.context.scene.btmprops

    selobj = bpy.context.selected_objects
    if props.set_bevel_width:
        for obj in selobj:
            for mod in obj.modifiers:
                if mod.name == 'HST Bevel':
                    obj.modifiers['HST Bevel'].width = props.set_bevel_width
                    obj.modifiers['HST Bevel'].segments = props.set_bevel_segments
                    continue

def import_obj_function(file_path):
    bpy.ops.wm.obj_import(filepath=file_path, clamp_size=0.1, up_axis='NEGATIVE_Z', forward_axis='Y')
    act_obj = bpy.context.active_object
    act_obj.name = "Moi_"+file_path.split("\\")[-1].split(".")[0]

    if "import_path" not in act_obj:
        act_obj["import_path"] = file_path

#==========================================================================================================================
# Vertex Color Function
#==========================================================================================================================
def create_palettes_color(pal, ver_col):
    pal_col = pal.colors.new()
    pal_col.color = ver_col
    pal_col.weight = 1.0

def set_all_vertex_color(sel_obj, colattr, ver_col):
    mesh: bpy.types.Mesh
    obj: bpy.types.Object
    for obj in sel_obj:
        for v in obj.data.vertices:
            v_index = v.index
            col_vec = mathutils.Vector(ver_col)
            bpy.data.meshes[obj.to_mesh().name].sculpt_vertex_colors[colattr.name].data[v_index].color = col_vec.to_4d()



