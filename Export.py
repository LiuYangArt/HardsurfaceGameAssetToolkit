import bpy
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *

GROUPPRO_SUFFIX = "_coll" #hack for group pro addon
CAT_GROUP_MOD = "CAT_MeshGroup"
GPRO_MOD = "GPro_Instance"


# ... existing code ...

def find_gpro_insts(objs):
    """
    在给定对象列表中查找具有“GPro_Instance”几何节点修改器的对象，
    并返回这些修改器中“Instanced Collection”输入所引用的集合中的所有对象。
    参数：
        objs (list[bpy.types.Object]): 需要检查的对象列表
    返回：
        list[bpy.types.Object]: 从Geometry Nodes修改器中“Instanced Collection”获取的所有对象
    """
    gpro_instances = []
    for obj in objs:
        if obj.modifiers:
            for mod in obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    node_name=mod.node_group.name
                    if node_name == GPRO_MOD or node_name == CAT_GROUP_MOD:
                        # 查找名为 "Instanced Collection" 的输入
                        for input_socket in mod.node_group.inputs:
                            if input_socket.name == "Instanced Collection" and input_socket.type == 'COLLECTION':
                                # 获取引用的集合
                                if input_socket.default_value:
                                    collection = input_socket.default_value
                                    gpro_instances.extend(collection.all_objects)
    return gpro_instances



def filter_instance_collection(objects):
    """筛选instance collection的父collection"""
    instance_collections = []
    for obj in objects:
        visibility=obj.visible_get()
        if visibility is True:
            if obj.instance_collection:
                if not obj.instance_collection.name.startswith("_"):
                    if obj.instance_collection not in instance_collections: #避免重复添加
                        instance_collections.append(obj.instance_collection)
    return instance_collections

def add_instance_collection_to_scene(collections):
    """添加instance collection到场景"""
    for collection in collections:
        if collection.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(collection)
        for obj in collection.objects:
            if obj.instance_collection:
                add_instance_collection_to_scene(obj.instance_collection)

    #     # Select the collection
    # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[collection.name]
def remove_instance_collection_from_scene(collections):
    """从场景中移除instance collection"""
    for collection in collections:
        if collection.name in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.unlink(collection)
        for obj in collection.objects:
            if obj.instance_collection:
                remove_instance_collection_from_scene(obj.instance_collection)

def filter_visible_objects(objects):
    """筛选可见的物体"""
    visible_objects = []
    for obj in objects:
        if obj.visible_get():
            visible_objects.append(obj)
    return visible_objects

def filter_instance_coll_objs(collections):
    """筛选Instance Collection对应的场景中的instance"""
    instance_objects = []
    for collection in collections:
        instance_objs = collection.users_dupli_group
        if instance_objs:
            #add first one to instance_objects
            if instance_objs[0] not in instance_objects:
                instance_objects.append(instance_objs[0])
    return instance_objects

def export_instance_collection(target, export_path, file_prefix):
    """导出实例化的collection"""
    new_name = target.name.removeprefix(Const.SKELETAL_MESH_PREFIX)
    new_name = target.name.removesuffix(GROUPPRO_SUFFIX)
    new_name = Const.STATICMESH_PREFIX + file_prefix + new_name
    file_path = export_path + new_name + ".fbx"
    print(f"exporting instance: {target.name} to {file_path}")
    FBXExport.instance_collection(target, file_path,reset_transform=True)


class StaticMeshExportOperator(bpy.types.Operator):
    bl_idname = "hst.staticmeshexport"
    bl_label = "HST StaticMesh Export UE"
    bl_description = "根据Collection分组导出Unreal Engine使用的静态模型fbx\
        只导出已被标记且可见的Collection，不导出隐藏的Collection,不导出隐藏的物体，不导出“_”开头的Collection\
        在outliner中显示器符号作为是否导出的标记，与眼睛符号无关"

#TODO: 增加对GPro Instance的支持， 增加对MeshGroupInstance的支持

    def execute(self, context):
        all_objects = bpy.data.objects #blender文件内的所有物体
        parameters = context.scene.hst_params
        export_path = parameters.export_path.replace("\\", "/")
        file_prefix = parameters.file_prefix
        export_count = 0
        blend_file_path = (bpy.path.abspath("//"))
        if export_path == "": #未设置保存路径时
            if blend_file_path =="": #未保存.blend文件时
                self.report(
                    {"ERROR"},
                    "No export path set and .blend file did not saved, please set export path and retry | "
                    + "没有设置导出路径且.blend文件未保存，请设置导出路径后重试",
                )
                return {"CANCELLED"}

            export_path = str(bpy.path.abspath("//")) + "Meshes/" #未设置保存路径时使用.blend文件路径/Meshes作为默认导出路径
            print(f"use default path when export path is not set: {export_path}")


        if export_path.endswith("/") is False: #修正路径
            export_path = export_path + "/"
        make_dir(export_path) #建立目标路径

        visible_objects= filter_visible_objects(all_objects) #筛选可见的物体
        instance_collections = filter_instance_collection(visible_objects) #筛选实例化的collection

        add_instance_collection_to_scene(instance_collections) #添加实例化的collection到场景中

        # print(f"instance colls: {instance_collections}")
        
        visible_collections = filter_collection_by_visibility(type="VISIBLE") #筛选可见的collection
        # print(f"visible_colls: {visible_collections}")
        # selected_objects = bpy.context.selected_objects
        store_mode = prep_select_mode()
        bpy.ops.hst.setsceneunits()  # 设置场景单位为厘米
        bpy.ops.object.select_all(action="DESELECT")
        
        #collection类型筛查
        (
            bake_collections,
            decal_collections,
            prop_collections,
            sm_collections,
            skm_collections,
            rig_collections,
        ) = Collection.sort_hst_types(visible_collections)

        #筛查 bake collection， 只要最上层的
        bake_export_collections=[]
        for collection in bake_collections:
            parent_collection=Collection.find_parent(collection)
            if parent_collection is None:
                bake_export_collections.append(collection)
        
        target_collections = (
            bake_export_collections + decal_collections + prop_collections + sm_collections
        )

        if len(skm_collections) == 0:
            if len(target_collections) == 0:
                restore_select_mode(store_mode)
                remove_instance_collection_from_scene(instance_collections)
                self.report(
                    {"ERROR"},
                    "No available collection for export. Please check visibility "
                    + "and ensure objects are placed in collections，"
                    + "set collection in correct type\n"
                    + "没有可导出的collection，请检查collection可见性，把要导出的资产放在collection中，并设置正确的类型后重试",
                )
                return {"CANCELLED"}

        # check_collections(self, bake_collections, prop_collections, decal_collections)


        if len(target_collections) > 0:
            # save origin objects transform and move to world origin
            origin_transform = {}
            invisible_origin_colls=[]
            for collection in target_collections:
                origin_objects=Object.filter_hst_type(objects=collection.all_objects,type="ORIGIN",mode="INCLUDE")

                if origin_objects:
                    origin_obj=origin_objects[0]
                    origin_visibility=origin_obj.visible_get()
                    # print(f"{collection.name} origin {origin_obj} vis: {origin_visibility}")
                    origin_transform[origin_obj] = origin_obj.matrix_world.copy()
                    origin_obj.matrix_world=Const.WORLD_ORIGIN_MATRIX
                    
                    if origin_visibility is False:
                        if collection.children:
                            for child_coll in collection.children:
                                invisible_origin_colls.append(child_coll)
                        invisible_origin_colls.append(collection)

            for collection in invisible_origin_colls:
                if collection in target_collections:
                    target_collections.remove(collection)

            for collection in target_collections:

                new_name = collection.name.removeprefix(Const.SKELETAL_MESH_PREFIX)
                new_name = Const.STATICMESH_PREFIX + file_prefix + new_name
                file_path = export_path + new_name + ".fbx"
                print(f"exporting {collection.name} to {file_path}")
                FBXExport.staticmesh(collection, file_path)
                export_count += 1


            if len(origin_transform)>0: #reset origin transform
                for origin_obj in origin_transform:
                    origin_obj.matrix_world=origin_transform[origin_obj]

        skm_count=0
        if len(skm_collections) > 0:
            for collection in skm_collections:
                # new_name = collection.name.removeprefix("SKM_")
                # new_name = "SKM_" + new_name
                for mesh in collection.objects:
                    new_name = mesh.name.removeprefix(Const.STATICMESH_PREFIX)
                    new_name = Const.STATICMESH_PREFIX + file_prefix + new_name
                    file_path = export_path + new_name + ".fbx"
                    skm_count += 1
                    FBXExport.staticmesh(mesh, file_path,reset_transform=True)
                    # mesh.select_set(True)
        if len(rig_collections) > 0:
            for collection in rig_collections:
                # for armature in collection.objects:
                new_name = collection.name.removeprefix(Const.SKELETAL_MESH_PREFIX)
                new_name = Const.SKELETAL_MESH_PREFIX + new_name
                file_path = export_path + new_name + ".fbx"
                use_armature_as_root = parameters.use_armature_as_root
                FBXExport.skeletal(collection, file_path, use_armature_as_root)

        restore_select_mode(store_mode)

        remove_instance_collection_from_scene(instance_collections) #移除实例化的collection

        export_count = (
            export_count + skm_count + len(rig_collections)
        )
        self.report(
            {"INFO"},
            f"{export_count} Meshes exported to {export_path}",
        )
        return {"FINISHED"}

class OpenFileExplorer(bpy.types.Operator):
    bl_idname = "hst.open_file_explorer"
    bl_label = "Open Explorer"

    def execute(self, context):
        parameters = context.scene.hst_params
        export_path = parameters.export_path.replace("\\", "/")
        blend_file_path = (bpy.path.abspath("//"))
        if export_path == "": #未设置保存路径时
            if blend_file_path =="": #未保存.blend文件时
                self.report(
                    {"ERROR"},
                    "No export path set and .blend file did not saved, please set export path and retry | "
                    + "没有设置导出路径且.blend文件未保存，请设置导出路径后重试",
                )
                return {"CANCELLED"}

            export_path = str(bpy.path.abspath("//")) + "Meshes/" #未设置保存路径时使用.blend文件路径/Meshes作为默认导出路径
        if export_path.endswith("/") is False:
            export_path = export_path + "/"

        #先检查export_path是否存在
        if not FilePath.is_path_exists(export_path):
            self.report(
                    {"ERROR"},
                    "目标路径不存在",
                )
            return {"CANCELLED"}
        FilePath.open_os_path(export_path)


        return {"FINISHED"}


class TestFuncOperator(bpy.types.Operator):
    bl_idname = "hst.testfunc"
    bl_label = "TestFunc"

    def execute(self, context):
        print("Test Func")
        print(Paths.ADDON_DIR)
        print(Addon.get_install_path())
        selected_objects = bpy.context.selected_objects
        active_object=bpy.context.active_object 
        dim_x=active_object.dimensions.x
        dim_y=active_object.dimensions.y
        dim_z=active_object.dimensions.z
        
        length_unit = get_scene_length_unit()
        dim_x=convert_length(dim_x)
        dim_y=convert_length(dim_y)
        dim_z=convert_length(dim_z)
        print(f"dimensions: {active_object.dimensions}")
        print(f"dimensions: {dim_x} {dim_y} {dim_z} {length_unit}")

        for obj in selected_objects:
            if obj.instance_collection:
                print(f"{obj.name} is instance of {obj.instance_collection.name}")


        return {"FINISHED"}
def get_scene_length_unit():
    current_scene = bpy.context.object.users_scene[0].name
    length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
    return length_unit
    
def convert_length(length: float) -> float:
    """根据场景单位设置转换长度"""
    length_unit = get_scene_length_unit()
    match length_unit:
        case "METERS":
            new_length = length * 1
        case "CENTIMETERS":
            new_length = length * 100
        case "MILLIMETERS":
            new_length = length * 1000

    return new_length