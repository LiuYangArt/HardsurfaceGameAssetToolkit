import os
import subprocess
import tempfile
import mathutils

import bmesh
import bpy

from ..UIPanel import BTMPropGroup


#定义命名
btncollname = "_TransferNormal"
btnmesh = "Raw_"
btnbevelmod = "HSTBevel"
btntransferpmod = "HSTNormalTransfer"
btnweightpmod = "HSTWeightedNormal"
btntrimod = "HSTTriangulate"
tvcpmod = "HSTVertexColorTransfer"


#设置Proxy Collection可见性
def transferproxycol_show(btn_coll):
    btn_coll.hide_viewport = False
    btn_coll.hide_render = False

def transferproxycol_hide(btn_coll):
    btn_coll.hide_viewport = True
    btn_coll.hide_render = True


#建立法线传递模型存放的Collection
def create_base_normal_coll():
    base_normal_coll_exist = 0
    colls = bpy.data.collections

    for coll in bpy.data.collections:
        if btncollname in coll.name:
            base_normal_coll_exist += 1
            continue
    
    if base_normal_coll_exist == 1:
        for coll in colls:
            if coll.name == btncollname:
                btn_coll = coll
        return btn_coll
    else:
        btn_coll = bpy.data.collections.new(name=btncollname)

        transferproxycol_hide(btn_coll)
        # btn_coll.hide_select = True

        btn_coll.color_tag = 'COLOR_08'
        bpy.context.scene.collection.children.link(btn_coll)
        return btn_coll

#判断是否存在传递模型
def check_BTN_exist(btn_coll, obj):
    btn_coll: bpy.types.Collection
    obj: bpy.types.Object

    BTN_exist = 0

    for btn_obj in btn_coll.all_objects:
        if btn_obj.name == btnmesh + obj.name:
            BTN_exist += 1
            return  BTN_exist
    
#建立模型并移动到Collection
def move_backup_base_object(btn_coll):
    obj: bpy.types.Object
    copy_obj: bpy.types.Object
    btn_coll: bpy.types.Collection

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    bns_coll = None

    for obj in selobj:
        if obj.type == 'MESH':
            

            if check_BTN_exist(btn_coll, obj) != 1:

                copy_obj = bpy.data.objects[obj.name].copy()
                for coll in bpy.data.collections:
                    if coll.name == btncollname:
                        bns_coll = coll
                bns_coll.objects.link(copy_obj)
                copy_obj.name = btnmesh + obj.name

                copy_obj.parent = obj
                if copy_obj.modifiers:
                    for copy_mod in copy_obj.modifiers:
                        copy_obj.modifiers.remove(copy_mod)
        else:
            print('is not mesh')
            break
    bpy.ops.object.make_single_user(object=True, obdata=True, material=False, animation=False, obdata_animation=False)

        
            
#添加Bevel修改器    
def add_bevel_modifier(selobj):
    bevelmod: bpy.types.Modifier
    obj: bpy.types.Object

    check_sharp = 0

    for obj in selobj:

        bpy.data.meshes[obj.to_mesh().name].use_auto_smooth = True
        #如果没有bevel修改器
        if btnbevelmod not in obj.modifiers:

            if 'sharp_edge' in obj.data.attributes:
                check_sharp = 1
                #如果有倒角权重
                if 'bevel_weight_edge' not in obj.data.attributes:
                    bevel_weight_attr = obj.data.attributes.new("bevel_weight_edge", "FLOAT", "EDGE")
                    for idx, e in enumerate(obj.data.edges):
                        bevel_weight_attr.data[idx].value = 1.0 if e.use_edge_sharp else 0.0
            else:
                check_sharp = 0

            #print(check_sharp)
            if check_sharp == 1:
                bevelmod = obj.modifiers.new(name=btnbevelmod, type='BEVEL')
                bevelmod.limit_method = 'WEIGHT'
                bevelmod.offset_type = 'WIDTH'
                bevelmod.width = 0.005
                bevelmod.use_clamp_overlap = False
                bevelmod.harden_normals = True
                bevelmod.loop_slide = True
                bevelmod.segments = 1
                bevelmod.profile = 0.7
                bevelmod.face_strength_mode = 'FSTR_ALL'
                
            elif check_sharp == 0: 
                bevelmod = obj.modifiers.new(name=btnbevelmod, type='BEVEL')
                bevelmod.limit_method = 'ANGLE' 
                bevelmod.offset_type = 'WIDTH'
                bevelmod.width = 0.005
                bevelmod.angle_limit = 0.523599
                bevelmod.use_clamp_overlap = False
                bevelmod.harden_normals = True
                bevelmod.loop_slide = True
                bevelmod.segments = 1
                bevelmod.profile = 0.7
                bevelmod.face_strength_mode = 'FSTR_ALL'
                
            continue


#添加DataTransfer修改器 
def add_datatransfer_modifier(selobj):
    datatransfermod: bpy.types.Modifier


    for obj in selobj:
        targobj = bpy.data.objects[btnmesh + obj.name]
        if btntransferpmod in obj.modifiers:
            datatransfermod = obj.modifiers[btntransferpmod]
            datatransfermod.object = targobj
    
        
        else:
            datatransfermod = obj.modifiers.new(name=btntransferpmod, type='DATA_TRANSFER')
            datatransfermod.object = targobj
            datatransfermod.use_loop_data = True
            datatransfermod.data_types_loops = {'CUSTOM_NORMAL'}
            datatransfermod.loop_mapping = 'POLYINTERP_LNORPROJ'



#添加Triangulate修改器 
def add_triangulate_modifier(selobj):
    triangulatemod: bpy.types.Modifier



    for obj in selobj:
        if btntrimod in obj.modifiers:
            triangulatemod = obj.modifiers[btntrimod]
            triangulatemod.keep_custom_normals = True
            triangulatemod.min_vertices = 4
            triangulatemod.quad_method = 'SHORTEST_DIAGONAL'
    
    

        else:
            triangulatemod = obj.modifiers.new(name=btntrimod, type='TRIANGULATE')
            triangulatemod.keep_custom_normals = True
            triangulatemod.min_vertices = 5
            triangulatemod.quad_method = 'SHORTEST_DIAGONAL'
            


#添加WeightedNormal修改器 
def add_weightednormal_modifier(selobj):
    weightpmod: bpy.types.Modifier



    for obj in selobj:
        if btnweightpmod in obj.modifiers:
            weightpmod = obj.modifiers[btnweightpmod]
            weightpmod.mode = 'FACE_AREA'
            weightpmod.use_face_influence = True
            weightpmod.thresh = 0.01
            weightpmod.keep_sharp = False
            weightpmod.weight = 100
    
        else:
            weightpmod = obj.modifiers.new(name=btnweightpmod, type='WEIGHTED_NORMAL')
            weightpmod.mode = 'FACE_AREA'
            weightpmod.use_face_influence = True
            weightpmod.thresh = 0.01
            weightpmod.keep_sharp = False
            weightpmod.weight = 100




#清理HST模型 
def clean_hstbtnobject():
    obj: bpy.types.Object
    mod: bpy.types.Modifier
    copy_obj: bpy.types.Object
    btn_coll: bpy.types.Collection
    base_obj: bpy.types.Object

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    props = bpy.context.scene.btmprops
    keep_list = []
    delete_list = []
    deletemod_list = []
    bevel_dict = {}
    #btn_coll = bpy.data.collections[btncollname]

    #if props.clean_all_mod == True:
    for obj in selobj:
        for mod in obj.modifiers:
            if mod.name == btntransferpmod and mod.object is not None:
                delete_list.append(mod.object)
            if mod.name == tvcpmod and mod.object is not None:
                delete_list.append(mod.object)
            if 'HST' in mod.name:
                obj.modifiers.remove(mod)

    for delete_obj in delete_list:
        if delete_obj:
            bpy.data.objects.remove(delete_obj)



#批量修改Bevel修改器参数
def batch_edit_bevel():
    props = bpy.context.scene.btmprops

    selobj = bpy.context.selected_objects
    if props.set_bevel_width:
        for obj in selobj:
            for mod in obj.modifiers:
                if mod.name == btnbevelmod:
                    obj.modifiers[btnbevelmod].width = props.set_bevel_width
                    obj.modifiers[btnbevelmod].segments = props.set_bevel_segments
                    continue