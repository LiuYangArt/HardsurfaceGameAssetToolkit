import os
import subprocess
import tempfile
import mathutils

import bmesh
import bpy

from .BTMProps import BTMPropGroup


#定义命名
tvcpcollname = "_TransferProxy"
tvcproxy = "TRNSP_"
vertcolorname = "VertColor"
tvcpmod = "HSTProxy DataTransfer"



#添加顶点色属性
def batchsetvertcolor(selobj):
    ver_col = bpy.data.brushes["TexDraw"].color


    for obj in selobj:
        #删除所有color attributes
        #if obj.data.color_attributes:
            #attrs = obj.data.color_attributes
            #for r in range(len(obj.data.color_attributes)-1, -1, -1):
                #attrs.remove(attrs[r])

        if vertcolorname in obj.data.color_attributes:
            colattr = obj.data.color_attributes[0]
        else:
            colattr = obj.data.color_attributes.new(
                name=vertcolorname,
                type='BYTE_COLOR',
                domain='CORNER',
            )
    return

#存放传递模型的Collection
def create_transproxy_coll():
    transproxy_coll_exist = 0
    colls = bpy.data.collections

    for coll in bpy.data.collections:
        if tvcpcollname in coll.name:
            transproxy_coll_exist += 1
            continue
    
    if transproxy_coll_exist == 1:
        for coll in colls:
            if coll.name == tvcpcollname:
                transp_coll = coll
        return transp_coll
    else:
        transp_coll = bpy.data.collections.new(name=tvcpcollname)

        transp_coll.hide_viewport = True
        transp_coll.hide_render = True
        # transp_coll.hide_select = True

        transp_coll.color_tag = 'COLOR_08'
        bpy.context.scene.collection.children.link(transp_coll)
        return transp_coll

##检查是否存在Transfer模型
def check_TRNSP_exist(transp_coll, obj):
    transp_coll: bpy.types.Collection
    obj: bpy.types.Object

    TRNSP_exist = 0

    for transp_obj in transp_coll.all_objects:
        if transp_obj.name == tvcproxy + obj.name:
            TRNSP_exist += 1
            return  TRNSP_exist
        

##检查选中模型是否带有Transfer修改器
def check_TRNSPmod_exist(selobj):

    TRNSPmod_exist = 0
    for obj in selobj: 
        for mod in obj.modifiers:
          if mod.name == tvcpmod:
            TRNSPmod_exist += 1

        


##清理传递模型修改器   
def cleanuptransproxymods(selobj):
    from types import NoneType
    delete_list = []

    for obj in selobj:
        if obj.type == 'MESH':
            #有 transfer修改器时
            if check_TRNSPmod_exist(selobj) != 0:
                for mod in obj.modifiers:
                    if mod.name == tvcpmod:
                        #如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
                        if mod.object is not None and mod.object.parent.name == obj.name:
                            delete_list.append(mod.object)
                        obj.modifiers.remove(mod)
        else:
            print('is not mesh')
            break
    #删除list内的物体   
    for delete_obj in delete_list:
                if delete_obj:
                    bpy.data.objects.remove(delete_obj)
    

##创建Proxy模型，应用修改器
def make_transpproxy_object(transp_coll):
    obj: bpy.types.Object
    copy_obj: bpy.types.Object
    transp_coll: bpy.types.Collection

    selobj = bpy.context.selected_objects
    actobj = bpy.context.active_object
    copy_list = []
    bns_coll = None
    
    #显示_transfcoll以便处理模型
    transp_coll.hide_viewport = False
    transp_coll.hide_render = False
    
    #清理之前的传递模型
    cleanuptransproxymods(selobj)

    for obj in selobj:
        if obj.type == 'MESH':
            if check_TRNSP_exist(transp_coll, obj) != 1:
                #复制模型并修改命名
                copy_obj = obj.copy()
                copy_obj.data = obj.data.copy()
                copy_obj.name = tvcproxy + obj.name
                copy_obj.parent = obj
                #检查文件中是否存在_transfcoll 
                for coll in bpy.data.collections:
                    if coll.name == tvcpcollname:
                        bns_coll = coll
                #移动proxy模型到_transfcoll内
                bns_coll.objects.link(copy_obj)

                copy_list.append(copy_obj)             
        else:
            print('is not mesh')
            break
    #选择所有复制出来的模型，应用修改器            
    bpy.ops.object.select_all(action='DESELECT')
    for obj in copy_list:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects[copy_obj.name]    
    bpy.ops.object.convert(target='MESH')
                

    
    #隐藏_transfcoll
    transp_coll.hide_viewport = True
    transp_coll.hide_render = True

 
 
        
            
##添加DataTransfer Modifier传递顶点色
def add_proxydatatransfer_modifier(selobj):
    datatransfermod: bpy.types.Modifier

    check_modifier = 0

    for obj in selobj:
        for m in obj.modifiers:
            if m.name == tvcpmod:
                check_modifier += 1
                continue
    
        targobj = bpy.data.objects[tvcproxy + obj.name]
        print(targobj)
        if not check_modifier:
            datatransfermod = obj.modifiers.new(name=tvcpmod, type='DATA_TRANSFER')
            datatransfermod.object = targobj
            datatransfermod.use_loop_data = True
            datatransfermod.data_types_loops = {'COLOR_CORNER'}
            datatransfermod.loop_mapping = 'TOPOLOGY'
        else:
            datatransfermod = obj.modifiers['HSTProxy DataTransfer']
            datatransfermod.object = targobj
            continue


def checkhastvcpmodifier(selobj):

    check_modifier = 0
    addmod_list = []

    for obj in selobj:
        for m in obj.modifiers:
            if m is not None and m.name == tvcpmod:
                    check_modifier += 1
            else:
                addmod_list.append(obj)

def transferproxycol_show(transp_coll):
    transp_coll.hide_viewport = False
    transp_coll.hide_render = False

def transferproxycol_hide(transp_coll):
    transp_coll.hide_viewport = True
    transp_coll.hide_render = True