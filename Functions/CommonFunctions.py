import bpy
import bmesh
import math
import subprocess

import os
import platform
import json
# import mathutils

from mathutils import Vector, Matrix, Quaternion
from ..Const import *

# ============================================================================
# 从 utils 包导入工具（渐进式迁移）
# 这些导入将逐步替换本文件中的本地定义
# ============================================================================
from ..utils.ui_utils import message_box, switch_to_eevee
from ..utils.object_utils import (
    filter_type, filter_name, clean_user, set_visibility, rename_meshes, Object
)
from ..utils.collection_utils import (
    get_collection, check_collection_exist, Collection
)
from ..utils.modifier_utils import (
    check_modifier_exist, remove_modifier, get_objects_with_modifier, apply_modifiers, Modifier
)
from ..utils.vertex_color_utils import (
    cleanup_color_attributes, add_vertexcolor_attribute, set_active_color_attribute,
    get_vertex_color_from_obj, vertexcolor_to_vertices, set_object_vertexcolor,
    get_color_data, VertexColor
)
from ..utils.uv_utils import (
    rename_uv_layers, add_uv_layers, check_uv_layer, has_uv_attribute,
    scale_uv, uv_unwrap, uv_average_scale, uv_editor_fit_view,
    culculate_td_areas, get_texel_density, UV
)
from ..utils.material_utils import (
    get_materials, get_object_material, get_object_material_slots,
    get_material_color_texture, get_scene_material, find_scene_materials,
    import_material, Material
)
from ..utils.mesh_utils import (
    mark_sharp_edges_by_split_normal, are_normals_different, mark_sharp_edge_by_angle,
    mark_convex_edges, set_edge_bevel_weight_from_sharp, Mesh
)
from ..utils.transform_utils import rotate_quaternion, get_selected_rotation_quat, Transform
from ..utils.import_utils import import_node_group, import_world, import_object, remove_node, make_transfer_proxy_mesh
from ..utils.bmesh_utils import BMesh
from ..utils.viewport_utils import check_screen_area, new_screen_area, viewport_shading_mode, Viewport
from ..utils.outliner_utils import Outliner
from ..utils.mesh_attributes_utils import MeshAttributes
from ..utils.file_utils import make_dir, normalize_path, copy_to_clip, FilePath
from ..utils.armature_utils import Armature
from ..utils.misc_utils import (
    set_default_scene_units, convert_length_by_scene_unit, text_capitalize,
    clean_collection_name, rename_alt, find_largest_digit, reset_transform,
    prep_select_mode, restore_select_mode
)

""" 通用functions """

# ============================================================================
# 以下函数已从 utils 包导入，无需本地定义:
# message_box, switch_to_eevee, rename_meshes, filter_type, filter_name,
# get_collection, check_collection_exist, clean_user, set_visibility,
# check_modifier_exist, remove_modifier, get_objects_with_modifier,
# cleanup_color_attributes, add_vertexcolor_attribute, set_active_color_attribute,
# get_vertex_color_from_obj, vertexcolor_to_vertices, set_object_vertexcolor,
# get_color_data, import_node_group, import_world, remove_node
# ============================================================================

# 以下函数也已从 utils 包导入：
# clean_user, set_visibility, check_modifier_exist, remove_modifier,
# get_objects_with_modifier, cleanup_color_attributes, add_vertexcolor_attribute,
# set_active_color_attribute, get_vertex_color_from_obj, vertexcolor_to_vertices,
# set_object_vertexcolor, get_color_data
# make_transfer_proxy_mesh, remove_node, import_node_group, import_world
# import_material, import_object, set_edge_bevel_weight_from_sharp
# rename_uv_layers, add_uv_layers, check_uv_layer, has_uv_attribute, scale_uv
# mark_sharp_edges_by_split_normal, are_normals_different, mark_sharp_edge_by_angle
# mark_convex_edges
# mark_sharp_edge_by_angle, mark_convex_edges
# get_selected_rotation_quat, get_materials, get_object_material
# get_object_material_slots, get_material_color_texture, get_scene_material
# find_scene_materials
# check_screen_area, new_screen_area, viewport_shading_mode
# apply_modifiers, convert_length_by_scene_unit
# uv_editor_fit_view, uv_unwrap, uv_average_scale
# culculate_td_areas, get_texel_density


# 以下是尚未迁移到 utils 的本地函数
# ============================================================================
# 以下函数已从 utils 导入: culculate_td_areas, get_texel_density
# set_default_scene_units, rename_alt, find_largest_digit, text_capitalize
# clean_collection_name


def filter_collection_by_visibility(type="VISIBLE", filter_instance=False) -> list:
    """筛选可见或不可见的collection"""
    all_collections = []
    for collection in bpy.data.collections:
        all_collections.append(collection)
    visible_collections = []
    hidden_collections = []
    skip_collections = []
    #find collection parent
    all_instance_coll_obj = []
    for obj in bpy.data.objects:
        if obj.instance_collection:
            all_instance_coll_obj.append(obj)

    for collection in all_collections: # 过滤掉隐藏的collection
        if collection.name.startswith("_"):
            # print(collection.children)
            
            for child in collection.children:
                skip_collections.append(child)
            for obj in collection.all_objects:
                if obj.instance_collection:
                    skip_collections.append(obj.instance_collection)

        layer_coll = Collection.find_layer_collection_coll(collection)
        if layer_coll:
            if layer_coll.exclude:
                hidden_collections.append(collection)

        if collection.hide_viewport:
            if collection not in hidden_collections:
                hidden_collections.append(collection)
            if collection.children is not None:
                for child in collection.children:
                    hidden_collections.append(child)

    visible_instance_colls=[]
    for obj in all_instance_coll_obj:
        visibility=obj.visible_get()
        coll=obj.instance_collection
        if obj.name.startswith("_"):
            continue
        if coll.name.startswith("_"):
            continue
        if visibility is False:
            if coll not in hidden_collections:
                hidden_collections.append(coll)
        else:
            if coll not in visible_collections:
                visible_instance_colls.append(coll)

    for collection in all_collections:
        if collection in skip_collections:
            continue
        if filter_instance:
            if collection.users_dupli_group: # 过滤掉instance collection
                continue
        if collection not in hidden_collections: #只导出可见的collection
            if not collection.name.startswith("_"):
                visible_collections.append(collection)
    for collection in visible_instance_colls:
        if collection not in visible_collections:
            visible_collections.append(collection)
    
    
    match type:
        case "VISIBLE":
            return visible_collections
        case "HIDDEN":
            return hidden_collections


# reset_transform 已从 utils.misc_utils 导入


class FBXExport:
    def instance_collection(target, file_path: str, reset_transform=False):
        """导出staticmesh fbx"""
        bpy.ops.object.select_all(action="DESELECT")

        obj_transform = {}
        if target.type == "EMPTY":
            target.select_set(True) #for use_selection=True
            if reset_transform is True:
                obj_transform[target] = target.matrix_world.copy()
                target.location = (0, 0, 0)
                target.rotation_euler = (0, 0, 0)
                target.rotation_quaternion = Quaternion((1, 0, 0, 0))

        if isinstance(target, bpy.types.Collection):
            #add collection.objects to view layer
            bpy.context.view_layer.active_layer_collection.exclude = False

        bpy.ops.export_scene.fbx(
            filepath=file_path,
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="-Z",
            axis_up="Y",
            global_scale=1.0,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH", "EMPTY"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            # use_batch_own_dir=True,
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=False,
            bake_anim=False,
        )


        if reset_transform is True:
            for target in obj_transform:
                target.matrix_world = obj_transform[target]


    def staticmesh(target, file_path: str, reset_transform=False):
        """导出staticmesh fbx"""
        bpy.ops.object.select_all(action="DESELECT")
        export_objects = []
        hidden_objects = []

        if isinstance(target, bpy.types.Collection):
            collection_type = Object.read_custom_property(
                target, Const.CUSTOM_TYPE)
            
            if target.all_objects is None:
                return

            for object in target.objects:
                if object.hide_get() is True:
                    hidden_objects.append(object)
                    object.hide_set(False)

            for object in target.objects:
                if object not in export_objects:
                    export_objects.append(object)
            
            #对Bake Collection进行处理
            if collection_type == Const.TYPE_BAKE_LOW_COLLECTION or collection_type == Const.TYPE_BAKE_HIGH_COLLECTION:
                for object in target.all_objects:
                    if object not in export_objects:
                        export_objects.append(object)


        elif target.type == "MESH":
            export_objects.append(target)
            if target.hide_get() is True:
                hidden_objects.append(target)
                target.hide_set(False)

        obj_transform = {}

        for obj in export_objects:
            obj.hide_set(False)
            obj.select_set(True) #for use_selection=True
            if obj.type=="MESH":
                Modifier.add_triangulate(obj)

            if reset_transform is True:
                obj_transform[obj] = obj.matrix_world.copy()
                obj.location = (0, 0, 0)
                obj.rotation_euler = (0, 0, 0)
                obj.rotation_quaternion = Quaternion((1, 0, 0, 0))

        bpy.ops.export_scene.fbx(
            filepath=file_path,
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="-Z",
            axis_up="Y",
            global_scale=1.0,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH", "EMPTY"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            # use_batch_own_dir=True,
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=False,
            bake_anim=False,
        )
        for object in hidden_objects:
            object.hide_set(True)

        if reset_transform is True:
            for obj in obj_transform:
                obj.matrix_world = obj_transform[obj]

    def skeletal(target, file_path: str, armature_as_root=False):
        """导出骨骼 fbx"""
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = 0.01
        bpy.context.scene.unit_settings.length_unit = "METERS"

        bpy.ops.object.select_all(action="DESELECT")
        hide_objects = []

        export_objects = []
        armature_names = {}
        if isinstance(target, bpy.types.Collection):
            for object in target.all_objects:
                if object.hide_get() is True:
                    hide_objects.append(object)
                    # object.hide_set(False)
                if object.type == "ARMATURE":
                    armature_names[object] = object.name
                    if armature_as_root is False:
                        print("Remove Armature as root")
                        object.name = (
                            "Armature"  # fix armature export as redundant root bone
                        )
                    else:
                        print("Export Armature as root")
                    Armature.ops_scale_bones(object, (100, 100, 100))
                if object.type == "MESH" or object.type == "ARMATURE":
                    export_objects.append(object)
                # object.select_set(True)
        elif target.type == "MESH":
            if target.hide_get() is True:
                hide_objects.append(target)
                # target.hide_set(False)
            export_objects.append(target)
            # target.select_set(True)

        obj_transform = {}
        for obj in export_objects:
            obj.hide_set(False)
            obj.select_set(True)
            obj_transform[obj] = obj.matrix_world.copy()

            obj.location = (0, 0, 0)
            obj.rotation_euler = (0, 0, 0)
            # obj.scale = (100, 100, 100)
            obj.rotation_quaternion = Quaternion((1, 0, 0, 0))

        # print(f"obj_transform: {obj_transform}")
        bpy.ops.export_scene.fbx(
            filepath=file_path,
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="Y",
            axis_up="Z",
            global_scale=1,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH", "ARMATURE"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            # use_batch_own_dir=True,
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=True,
            armature_nodetype="NULL",
            bake_anim=False,
        )
        # print(f"obj_transform: {obj_transform}")

        for object in hide_objects:
            object.hide_set(True)
        for obj in obj_transform:
            obj.matrix_world = obj_transform[obj]
        for obj in export_objects:
            if obj.type == "ARMATURE":
                obj.name = armature_names[obj]
                Armature.ops_scale_bones(obj, (0.01, 0.01, 0.01))

        set_default_scene_units()


def filter_collections_selection(target_objects):
    """筛选所选物体所在的collection"""
    filtered_collections = []
    if target_objects:
        if len(target_objects) != 0:
            processed_collections = set()
            for obj in target_objects:
                for collection in obj.users_collection:
                    if (
                        collection is not None
                        and collection.name != "Scene Collection"
                        and collection not in processed_collections
                        and not collection.name.startswith("_")
                    ):
                        filtered_collections.append(collection)
                        processed_collections.add(collection)
    else:
        a = bpy.context.view_layer.active_layer_collection.collection
        col = bpy.data.collections.get(a.name)
        filtered_collections.append(col)


    if len(filtered_collections)==0:
        return None
    else:
        return filtered_collections



def filter_collection_types(collections):
    """筛选collection类型，返回筛选后的collection列表，包括decal,prop,low,high"""
    bake_collections = []
    decal_collections = []
    prop_collections = []
    sm_collections = []
    skm_collections = []
    rig_collections = []

    for collection in collections:
        if len(collection.objects) > 0:
            collection_color = str(collection.color_tag)
            if (
                collection.name.startswith("_")
                and PROXY_COLLECTION_COLOR in collection_color
            ):
                continue
            elif collection.name.endswith(LOW_SUFFIX) or collection.name.endswith(
                HIGH_SUFFIX
            ):
                if LOW_COLLECTION_COLOR or HIGH_COLLECTION_COLOR in collection_color:
                    bake_collections.append(collection)
                continue
            elif (
                "_Decal" in collection.name
                and DECAL_COLLECTION_COLOR in collection_color
            ):
                decal_collections.append(collection)
                continue
            elif PROP_COLLECTION_COLOR in collection_color:
                prop_collections.append(collection)
                continue
            elif (
                Const.SKM_COLLECTION_COLOR in collection_color
                and collection.name.endswith(Const.SKM_SUFFIX)
            ):
                skm_collections.append(collection)
                continue
            elif (
                Const.SKM_COLLECTION_COLOR in collection_color
                and collection.name.endswith(Const.RIG_SUFFIX)
            ):
                rig_collections.append(collection)
                continue
            else:
                sm_collections.append(collection)

    return (
        bake_collections,
        decal_collections,
        prop_collections,
        sm_collections,
        skm_collections,
        rig_collections,
    )


# def check_open_bondary(mesh) -> bool:
#     """检查是否存在开放边"""
#     bm = bmesh.new()
#     bm.from_mesh(mesh.data)
#     check_result = False
#     for edge in bm.edges:
#         if edge.is_boundary:
#             print("open edge")
#             check_result = True
#             break
#     bm.clear()
#     bm.free()

#     return check_result


def prep_select_mode() -> tuple:
    """存储当前模式,并切换到OBJECT模式. EXAMPLE: store_mode = prep_select_mode()"""

    active_object = bpy.context.active_object
    if active_object is not None:
        current_mode = bpy.context.active_object.mode
    else:
        current_mode = "OBJECT"
    selected_objects = bpy.context.selected_objects
    store_mode = current_mode, active_object, selected_objects
    if active_object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")

    return store_mode


def restore_select_mode(store_mode) -> None:
    """恢复之前的模式. EXAMPLE: restore_select_mode(store_mode)"""

    current_mode, active_object, selected_objects = store_mode
    if selected_objects is not None:
        bpy.ops.object.select_all(action="DESELECT")
        for object in selected_objects:
            object.select_set(True)
    if active_object is not None:
        bpy.context.view_layer.objects.active = active_object
        active_object.select_set(True)
        bpy.ops.object.mode_set(mode=current_mode)


def set_collision_object(target_object, new_name) -> None:
    """设置碰撞物体"""
    target_object.show_name = True
    target_object.display_type = "WIRE"
    target_object.visible_shadow = False
    target_object.hide_render = True
    for modifier in target_object.modifiers:
        target_object.modifiers.remove(modifier)
    for material_slot in target_object.material_slots:
        target_object.data.materials.clear()
    for attribute in target_object.data.attributes:
        if attribute.data_type == "COLOR" or attribute.data_type == "BYTE_COLOR":
            target_object.data.attributes.remove(attribute)
    for uv_layer in target_object.data.uv_layers:
        target_object.data.uv_layers.remove(uv_layer)
    # set naming
    if new_name is None:
        new_name = target_object.name
    Object.mark_hst_type(target_object, "UCX")
    # target_object.name = UCX_PREFIX + new_name
    rename_alt(target_object, UCX_PREFIX + new_name, mark="_", num=2)


def filter_static_meshes(collection) -> tuple:
    """筛选collection中的mesh,返回staticmeshes,ucx_meshes,剔除掉decal"""
    staticmeshes = []
    ucx_meshes = []

    collection_meshes = [obj for obj in collection.all_objects if obj.type == "MESH"]
    decal_meshes = Object.filter_hst_type(objects=collection_meshes, type="DECAL")
    if decal_meshes is None:
        decal_meshes = []
    ucx_meshes = [obj for obj in collection_meshes if obj.name.startswith(UCX_PREFIX)]
    for obj in collection_meshes:
        if obj not in ucx_meshes and obj not in decal_meshes:
            staticmeshes.append(obj)

    return staticmeshes, ucx_meshes


def name_remove_digits(name, parts=3, mark="_") -> str:
    """去除名称后的数字"""
    parts = int(parts)
    new_name = name
    name_split = name.split("_")
    if len(name_split) > parts:
        new_name = name.rsplit(mark, 1)[0]
    return new_name


def rename_prop_meshes(objects) -> tuple:
    """重命名prop mesh"""
    selected_collections = filter_collections_selection(objects)
    for collection in selected_collections:
        static_meshes, ucx_meshes = filter_static_meshes(collection)
        rename_meshes(static_meshes, collection.name)
        for ucx_mesh in ucx_meshes:
            Object.mark_hst_type(ucx_mesh, "UCX")
        for static_mesh in static_meshes:
            Object.mark_hst_type(static_mesh, "STATICMESH")

        if len(ucx_meshes) > 0:
            if len(static_meshes) > 0:
                ucx_name = UCX_PREFIX + static_meshes[0].name
            else:
                ucx_name = name_remove_digits(ucx_meshes[0].name)
            rename_meshes(ucx_meshes, ucx_name)
    return static_meshes, ucx_meshes


def check_vertex_color(mesh):
    """检查是否存在顶点色，如有，返回顶点色层"""
    vertex_color_layer = None
    if len(mesh.data.color_attributes) > 0:
        vertex_color_layer = mesh.data.attributes.active_color
    return vertex_color_layer


def make_dir(path):
    """创建文件夹"""
    if not os.path.exists(path):
        os.makedirs(path)


def normalize_path(path: str):
    """规范化路径"""
    path = str(path)
    path = path.replace("\\", "/")
    path = path.replace(" ", "")
    if path.endswith("/"):
        path = path[:-1]
    # if path.startswith("/"):
    #     path = path[1:]
    return path


def fix_ue_game_path(path: str):
    """修复UE路径"""
    path = str(path)
    path = normalize_path(path)
    if not path.startswith("/"):
        path = "/" + path
    return path


def fix_ip_input(ip_address: str):
    ip_address = str(ip_address)
    ip_address = ip_address.replace(" ", "")
    ip_address = ip_address.replace("http://", "")
    ip_address = ip_address.replace("https://", "")
    ip_address = ip_address.replace("/", "")
    ip_address = ip_address.replace("：", ":")
    ip_address = ip_address.replace(",", ":")
    ip_address = ip_address.replace("。", ".")
    ip_address = ip_address.replace("，", ":")
    return ip_address


def make_ue_python_script_command(file_name, command):
    command_lines = [
        f"import {file_name}",
        "from importlib import reload",
        f"reload({file_name})",
        'print("hey!")',
        f"{file_name}.{command}",
        'print("command executed")',
    ]
    return command_lines


def write_json(file_path, data):
    """写入json"""
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def read_json_from_file(file_path):
    """从文件读取json"""
    json_dict = {}
    if file_path.exists():
        with open(file_path, "r") as json_file:
            json_dict = json.load(json_file)
    return json_dict


class BMesh:
    def init(mesh, mode="CONTEXT"):
        """初始化bmesh"""
        current_mode = bpy.context.active_object.mode
        if mode == "CONTEXT":
            if current_mode == "EDIT":
                bm = bmesh.from_edit_mesh(mesh.data)
            else:
                bm = bmesh.new()
                bm.from_mesh(mesh.data)
        elif mode == "OBJECT":
            bm = bmesh.new()
            bm.from_mesh(mesh.data)
        return bm

    def finished(bm, mesh, mode="CONTEXT"):
        """结束bmesh"""
        current_mode = bpy.context.active_object.mode
        if mode == "CONTEXT":
            if current_mode == "EDIT":
                bm.update_edit_mesh(mesh.data)
            else:
                bm.to_mesh(mesh.data)
        elif mode == "OBJECT":
            bm.to_mesh(mesh.data)

        mesh.data.update()
        bm.clear()
        bm.free()


class Material:
    def assign_to_mesh(mesh, target_mat) -> bpy.types.Material:
        """assign material to mesh, return assigned material"""
        has_mat = False
        for mat in mesh.data.materials:
            if mat.name == target_mat.name:
                has_mat = True
                assign_mat = mat
        if not has_mat:
            assign_mat = mesh.data.materials.append(target_mat)
        return assign_mat

    def create_mat(mat_name) -> bpy.types.Material:
        """add material"""
        has_mat = False
        new_mat = None
        for mat in bpy.data.materials:
            if mat.name == mat_name:
                has_mat = True
                new_mat = mat
                break
        if not has_mat:
            bpy.data.materials.new(name=mat_name)
        return new_mat
    
    def remove_duplicated_mats_ops(object):
        bpy.ops.object.select_all(action="DESELECT")
        object.select_set(True)
        bpy.context.view_layer.objects.active=object
        bpy.ops.object.mode_set(mode="EDIT")
        # bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type="MATERIAL")
        bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.join()




def rotate_quaternion(quaternion, angle, axis="Z") -> Quaternion:
    """旋转四元数，输入角度与轴，返回旋转后的四元数，轴为X,Y,Z"""
    match axis:
        case "X":
            axis = (1, 0, 0)
        case "Y":
            axis = (0, 1, 0)
        case "Z":
            axis = (0, 0, 1)

    angle = angle / 180 * 3.1415926
    rotation = Quaternion(axis, angle)
    return quaternion @ rotation


class Object:
    
    def get_selected():
        selected_objects = bpy.context.selected_objects
        outliner_objs=Outliner.get_selected_objects()
        if outliner_objs:
            for obj in outliner_objs:
                if obj not in selected_objects:
                    selected_objects.append(obj)
        if len(selected_objects)==0:
            return None
        else:
            return selected_objects

        
    def set_pivot_to_matrix(obj, matrix):
        if obj.type not in ["EMPTY", "FONT"]:
            deltamx = matrix.inverted_safe() @ obj.matrix_world
            obj.matrix_world = matrix
            obj.data.transform(deltamx)

    def set_pivot_location(obj, location: Vector):
        """
        Set the object's origin (pivot) to the specified world location.
        """

        offset = location - obj.location
        obj.location += offset
        # Move all vertices in the opposite direction to keep the mesh in place
        if obj.type == "MESH":
            mesh = obj.data
            for v in mesh.vertices:
                v.co -= offset

    def move_to_world_origin(obj):
        world_origin_matrix = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        obj.matrix_world = world_origin_matrix

    def add_custom_property(obj: bpy.types.Object, prop_name: str, prop_value: str):
        obj[prop_name] = prop_value

    def read_custom_property(obj, prop_name):
        return obj.get(prop_name)

    def get_hst_type(object: bpy.types.Object):
        return Object.read_custom_property(object, Const.CUSTOM_TYPE)

    def mark_hst_type(object: bpy.types.Object, type: str):
        r"""Mark object type as custom property, types:
        STATICMESH, DECAL, HIGH, SKELETALMESH, SKELETAL, UCX, SOCKET,
        PLACEHOLDER, PROXY"""
        type = type.upper()
        match type:
            case "STATICMESH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_STATIC_MESH
                )
            case "DECAL":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_DECAL)
            case "LOW":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_BAKE_LOW
                )
            case "HIGH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_BAKE_HIGH
                )
            case "SKELETALMESH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SKELETAL_MESH
                )
            case "SKELETAL":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SKELETAL
                )
            case "SPLITSKEL":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SPLITSKEL
                )
            case "SKM":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_SKM)
            case "UCX":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_UCX)
            case "SOCKET":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_SOCKET)
            case "PLACEHOLDER":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_PLACEHOLDER
                )
            case "PROXY":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_PROXY)
            case "ORIGIN":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_ORIGIN)

    def filter_hst_type(objects, type, mode="INCLUDE"):
        """Filter objects by type"""
        type = type.upper()
        mode = mode.upper()
        filtered_objects = []
        include_objects = []
        # exclude_objects = []
        for object in objects:
            object_type = Object.read_custom_property(object, Const.CUSTOM_TYPE)
            match type:
                case "STATICMESH":
                    if object_type == Const.TYPE_STATIC_MESH:
                        include_objects.append(object)
                case "DECAL":
                    if object_type == Const.TYPE_DECAL:
                        include_objects.append(object)
                case "BAKE_HIGH":
                    if object_type == Const.TYPE_BAKE_HIGH:
                        include_objects.append(object)
                case "SKELETALMESH":
                    if object_type == Const.TYPE_SKELETAL_MESH:
                        include_objects.append(object)
                case "RIG":
                    if object_type == Const.TYPE_SKELETAL:
                        include_objects.append(object)
                case "UCX":
                    if object_type == Const.TYPE_UCX:
                        include_objects.append(object)
                case "SOCKET":
                    if object_type == Const.TYPE_SOCKET:
                        include_objects.append(object)
                case "PLACEHOLDER":
                    if object_type == Const.TYPE_PLACEHOLDER:
                        include_objects.append(object)
                case "ORIGIN":
                    if object_type == Const.TYPE_ORIGIN:
                        include_objects.append(object)
                case "PROXY":
                    if object_type == Const.TYPE_PROXY:
                        include_objects.append(object)

        if mode == "INCLUDE":
            filtered_objects = include_objects
        elif mode == "EXCLUDE":
            for object in objects:
                if object not in include_objects:
                    filtered_objects.append(object)
        if len(filtered_objects) == 0:
            return None
        return filtered_objects

    def sort_types(objects):
        sorted_objects = {}
        for object in objects:
            object_type = object.get(Const.CUSTOM_TYPE)
            if object_type not in sorted_objects:
                sorted_objects[object_type] = []
            sorted_objects[object_type].append(object)
        return sorted_objects

    def check_empty_mesh(object):
        if object.type == "MESH":
            if len(object.data.vertices) == 0:
                return True
            else:
                return False
    def break_link_from_assetlib(object):
        obj_collection = object.users_collection[0]
        unlinked_mesh =object.copy()
        unlinked_mesh.data = object.data.copy()
        obj_collection.objects.link(unlinked_mesh)
        mesh_data=object.data
        mesh_name=object.name
        bpy.data.objects.remove(object)
        bpy.data.meshes.remove(mesh_data)
        unlinked_mesh.name = mesh_name
        return unlinked_mesh


class UV:
    def show_uv_in_object_mode():
        """显示UV编辑器"""

        uv_area = None
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                uv_area = area

                break
        if uv_area:
            with bpy.context.temp_override(
                window=bpy.context.window,
                area=uv_area,
                region=next(region for region in area.regions if region.type == "WINDOW"),
                screen=bpy.context.window.screen,
            ):
                bpy.context.space_data.uv_editor.show_uv = True
                bpy.context.space_data.uv_editor.uv_face_opacity = 1
        return uv_area



class Transform:
    def rotate_quat(quaternion, angle, axis="Z") -> Quaternion:
        """旋转四元数，输入角度与轴，返回旋转后的四元数，轴为X,Y,Z"""
        match axis:
            case "X":
                axis = (1, 0, 0)
            case "Y":
                axis = (0, 1, 0)
            case "Z":
                axis = (0, 0, 1)

        angle = angle / 180 * 3.1415926
        rotation = Quaternion(axis, angle)
        return quaternion @ rotation

    def scale_matrix(matrix, scale_factor, size=4):
        """Scale a matrix by a specified factor"""
        # Create a scale matrix
        scale_matrix = Matrix.Scale(scale_factor, size)

        # Multiply the original matrix by the scale matrix
        scaled_matrix = matrix @ scale_matrix

        return scaled_matrix

    def rotate_matrix(matrix, angle, axis="Z"):
        """Rotate a matrix by a specified angle around a specified axis"""
        # Create a rotation matrix for a 90 degree rotation around the X-axis
        rotation_matrix = Matrix.Rotation(math.radians(angle), 4, axis)

        # Multiply the original matrix by the rotation matrix
        rotated_matrix = matrix @ rotation_matrix

        return rotated_matrix

    def apply_scale(object):
        obj_matrix = object.matrix_local
        location, rotation, scale = obj_matrix.decompose()
        mat_scale = Matrix.LocRotScale(None, None, scale)
        object.data.transform(mat_scale)
        object.scale = 1, 1, 1

    def apply(object, location=True, rotation=True, scale=True):
        """应用变换"""
        # matrix_basis = object.matrix_basis.copy()
        matrix_basis = object.matrix_basis
        matrix = Matrix()
        loc, rot, scale = matrix_basis.decompose()

        translation = Matrix.Translation(loc)
        rotation = matrix_basis.to_3x3().normalized().to_4x4()
        scale = Matrix.Diagonal(scale).to_4x4()

        transform = [matrix, matrix, matrix]
        basis = [translation, rotation, scale]

        def swap(i):
            transform[i], basis[i] = basis[i], transform[i]

        if location:
            swap(0)
        if rotation:
            swap(1)
        if scale:
            swap(2)

        new_matrix = transform[0] @ transform[1] @ transform[2]
        if hasattr(object.data, "transform"):
            object.data.transform(new_matrix)
        for child in object.children:
            child.matrix_local = new_matrix @ child.matrix_local

        object.matrix_basis = basis[0] @ basis[1] @ basis[2]

    def ops_apply(object, location=True, rotation=True, scale=True):
        """Apply transformation to object"""
        object.select_set(True)
        bpy.context.view_layer.objects.active = object
        bpy.ops.object.transform_apply(
            location=location, rotation=rotation, scale=scale
        )
        object.select_set(False)


# class Files:
#     def make_dir(path: str):
#         """检查路径是否存在，不存在则创建"""
#         if not os.path.exists(path):
#             os.makedirs(path)
#         return path


class Armature:
    def set_bone_roll(armature, roll=0):
        for bone in armature.data.bones:
            bone.roll = roll

    def set_display(obj):
        """Set display settings for an armature object"""
        obj.data.display_type = "WIRE"
        obj.data.show_names = True
        obj.data.show_axes = True
        obj.show_in_front = True
        # obj.relation_line_position = 'HEAD'

    def scale_bones(armature, scale_factor):
        """Scale bones of an armature"""
        for bone in armature.data.bones:
            bone.head = bone.head * scale_factor
            bone.tail = bone.tail * scale_factor

    def ops_scale_bones(armature, scale=(1, 1, 1)):
        """Scale bones of an armature"""
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.armature.select_all(action="SELECT")
        bpy.ops.transform.resize(
            value=scale,
            orient_type="GLOBAL",
            orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            orient_matrix_type="GLOBAL",
            mirror=False,
            snap=False,
            snap_elements={"INCREMENT"},
            use_snap_project=False,
            snap_target="CLOSEST",
            use_snap_self=True,
            use_snap_edit=True,
            use_snap_nonedit=True,
            use_snap_selectable=False,
        )
        bpy.ops.object.mode_set(mode="OBJECT")


class Collection:
    def sort_order(collection, case_sensitive=False):

        if collection.children is None:
            return

        children = sorted(
            collection.children,
            key=lambda c: c.name if case_sensitive else c.name.lower(),
        )

        for child in children:
            collection.children.unlink(child)
            collection.children.link(child)
            Collection.sort_order(child)

        # for scene in bpy.data.scenes:
        #     sort_order(scene.collection, case_sensitive=True)

    def get_selected():
        selected_objects = Object.get_selected()
        selected_collections=[]
        if selected_objects:
            for obj in selected_objects:
                for collection in obj.users_collection:

                    if (
                        collection is not None
                        and collection.name != "Scene Collection"
                        and collection not in selected_collections
                        and not collection.name.startswith("_")
                    ):
                        selected_collections.append(collection)


        

        if len(selected_collections)==0:
            outliner_collections = Outliner.get_selected_collections()
            if outliner_collections is not None:
                for collection in outliner_collections:
                    if collection not in selected_collections:
                        selected_collections.append(collection)
        
        if len(selected_collections)==0:
            return None
        else:
            return selected_collections


    def mark_hst_type(collection: bpy.types.Collection, type: str = "PROP"):
        r"""Mark collection type,types:
        PROP, DECAL, BAKE_LOW, BAKE_HIGH, SKM, RIG, PROXY"""
        type = type.upper()
        match type:
            case "PROP":
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_PROP_COLLECTION
                )
                collection.color_tag = "COLOR_" + PROP_COLLECTION_COLOR
            case "DECAL":
                collection.color_tag = "COLOR_" + DECAL_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_DECAL_COLLECTION
                )
            case "LOW":
                collection.color_tag = "COLOR_" + LOW_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_BAKE_LOW_COLLECTION
                )
            case "HIGH":
                collection.color_tag = "COLOR_" + HIGH_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_BAKE_HIGH_COLLECTION
                )
            case "SKM":
                collection.color_tag = "COLOR_" + Const.SKM_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_SKM_COLLECTION
                )
            case "RIG":
                collection.color_tag = "COLOR_" + Const.RIG_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_RIG_COLLECTION
                )
            case "PROXY":
                collection.color_tag = "COLOR_" + PROXY_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_PROXY_COLLECTION
                )
            case "MISC":
                collection.color_tag = "COLOR_" + PROXY_COLLECTION_COLOR

    def create(name: str, type: str = "PROP") -> bpy.types.Collection:
        """创建collection,type为PROP,DECAL,BAKE_LOW,BAKE_HIGH,SKM,RIG,PROXY"""
        type = type.upper()
        collection = None
        collection_exist = False

        for collection in bpy.data.collections:  # 有则返回，无则创建
            if collection.name == name:
                collection_exist = True
                collection = bpy.data.collections[name]
                break
        if not collection_exist:  # 创建collection,并添加到scene
            collection = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(collection)

        Collection.mark_hst_type(collection, type)

        return collection

    def get_hst_type(collection: bpy.types.Collection) -> str:
        """获取collection类型"""
        collection_type = Object.read_custom_property(collection, Const.CUSTOM_TYPE)
        return collection_type

    def filter_hst_type(collections, type, mode="INCLUDE"):
        """Filter collections by type"""
        type = type.upper()
        mode = mode.upper()
        filtered_collections = []
        include_collections = []
        # exclude_objects = []
        for collection in collections:
            collection_type = Collection.get_hst_type(collection)
            match type:
                case "PROXY":
                    if collection_type == Const.TYPE_PROXY_COLLECTION:
                        include_collections.append(collection)
                case "BAKE_LOW":
                    if collection_type == Const.TYPE_BAKE_LOW_COLLECTION:
                        include_collections.append(collection)
                case "BAKE_HIGH":
                    if collection_type == Const.TYPE_BAKE_HIGH_COLLECTION:
                        include_collections.append(collection)
                case "DECAL":
                    if collection_type == Const.TYPE_DECAL_COLLECTION:
                        include_collections.append(collection)
                case "PROP":
                    if collection_type == Const.TYPE_PROP_COLLECTION:
                        include_collections.append(collection)
                case "SKM":
                    if collection_type == Const.TYPE_SKM_COLLECTION:
                        include_collections.append(collection)
                case "RIG":
                    if collection_type == Const.TYPE_RIG_COLLECTION:
                        include_collections.append(collection)
                case _:
                    if collection_type is None:
                        include_collections.append(collection)

        if mode == "INCLUDE":
            filtered_collections = include_collections
        elif mode == "EXCLUDE":
            for collection in collections:
                if collection not in include_collections:
                    filtered_collections.append(collection)
        if len(filtered_collections) == 0:
            return None
        return filtered_collections

    def sort_hst_types(collections: list):
        """筛选collection类型，返回筛选后的collection列表，包括bake,decal,prop,sm,skm,rig"""
        bake_collections = []
        decal_collections = []
        prop_collections = []
        sm_collections = []
        skm_collections = []
        rig_collections = []

        for collection in collections:
            # if len(collection.objects) > 0:
            collection_type = Object.read_custom_property(
                collection, Const.CUSTOM_TYPE
            )
            if len(collection.objects) > 0:
                match collection_type:
                    case Const.TYPE_PROXY_COLLECTION:
                        continue
                    case Const.TYPE_BAKE_LOW_COLLECTION:
                        bake_collections.append(collection)
                    case Const.TYPE_BAKE_HIGH_COLLECTION:
                        bake_collections.append(collection)
                    case Const.TYPE_DECAL_COLLECTION:
                        decal_collections.append(collection)
                    case Const.TYPE_PROP_COLLECTION:
                        prop_collections.append(collection)
                    case Const.TYPE_SKM_COLLECTION:
                        skm_collections.append(collection)
                    case Const.TYPE_RIG_COLLECTION:
                        rig_collections.append(collection)
                    case _:
                        sm_collections.append(collection)
                        
            if len(collection.all_objects) > 0:
                match collection_type:
                    case Const.TYPE_BAKE_LOW_COLLECTION:
                        if collection not in bake_collections:
                            bake_collections.append(collection)
                    case Const.TYPE_BAKE_HIGH_COLLECTION:
                        if collection not in bake_collections:
                            bake_collections.append(collection)

        return (
            bake_collections,
            decal_collections,
            prop_collections,
            sm_collections,
            skm_collections,
            rig_collections,
        )

    def find_parent(collection):
        parent = dict()

        all_collections = bpy.data.collections
        for c in all_collections:
            parent[c] = None
        for c in all_collections:
            for ch in c.children:
                parent[ch] = c

        parent_collection = parent[collection]

        return parent_collection
    
    def find_parent_recur_by_type(collection:bpy.types.Collection,type:str):
        parent_c=Collection.find_parent(collection)
        if parent_c is None:
            return None
        else:
            # if type == "NONE":
            #     return parent_c
            # else:
            parent_c_type=Collection.get_hst_type(parent_c)
            if parent_c_type != type:
                parent_c=Collection.find_parent_recur_by_type(parent_c,type)
                if parent_c:
                    return parent_c
            else:
                return parent_c

    def active(collection):
        """激活collection"""
        layer_collection = Collection.find_layer_collection(collection)
        # layer_collection=Collection.find_layer_collection_coll(collection)
        bpy.context.view_layer.active_layer_collection = layer_collection

    def find_layer_collection_all(collection_name):
        """递归查找collection对应的layer_collection"""

        for i in bpy.data.collections:
            layer_collection = bpy.context.view_layer.layer_collection
            layer_collection = Collection.layer_recur_find_parent(layer_collection, i.name)
        return layer_collection

    def find_layer_collection_coll(collection):
        """递归查找collection对应的layer_collection"""
        if collection.objects:
            object = collection.objects[0]

            for i in object.users_collection:
                layer_collection = bpy.context.view_layer.layer_collection
                layer_collection = Collection.layer_recur_find_parent(
                    layer_collection, i.name
                )
            return layer_collection
        else:
            return None

    def find_layer_collection(collection):
        """递归查找collection对应的layer_collection"""

        layer_collection = bpy.context.view_layer.layer_collection
        layer_collection = Collection.layer_recur_find_parent(
            layer_collection, collection.name
        )

        return layer_collection

    def find_layer_collection_by_name(collection_name):
        """递归查找collection对应的layer_collection"""
        for collection in bpy.data.collections:
            if collection.name == collection_name:
                object = collection.objects[0]
                break
        # obj = bpy.context.object
        for i in object.users_collection:
            layer_collection = bpy.context.view_layer.layer_collection
            layer_collection = Collection.layer_recur_find_parent(layer_collection, i.name)
        return layer_collection

    def layer_recur_find_parent(layer_collection, collection_name):
        found = None
        if layer_collection.name == collection_name:
            return layer_collection
        for layer in layer_collection.children:
            found = Collection.layer_recur_find_parent(layer, collection_name)
            if found:
                return found
            
    def get_by_name(collection_name: str) -> bool:
        """检查collection是否存在"""
        target_collection=None

        for collection in bpy.data.collections:
            if collection.name == collection_name:
                target_collection=collection
                break
        return target_collection


class VertexColor:


    def add(
    target_object: bpy.types.Object, vertexcolor_name: str
    ) -> bpy.types.Object:
        """为选中的物体添加顶点色属性，返回顶点色属性
        注意：Blender 5.0+ 要求 mesh 必须有顶点才能创建 color attribute
        """
        if target_object.type == "MESH":
            mesh = target_object.data
            # Blender 5.0+: 空 mesh 无法添加 color attribute
            if len(mesh.vertices) == 0:
                print(f"{target_object.name} has no vertices, cannot add color attribute")
                return None
            if vertexcolor_name in mesh.color_attributes:
                color_attribute = mesh.color_attributes.get(vertexcolor_name)
            else:
                color_attribute = mesh.color_attributes.new(
                    name=vertexcolor_name,
                    type="BYTE_COLOR",
                    domain="CORNER",
                )
            print(f"{target_object} has vertexcolor {color_attribute.name}")
            return color_attribute
        else:
            print(target_object.name + " is not mesh object")
            return None
        

    def remove_all(mesh: bpy.types.Object) -> bool:
        """为选中的物体删除所有顶点色属性"""
        success = False

        if mesh.data.color_attributes is not None:
            color_attributes = mesh.data.color_attributes
            for r in range(len(color_attributes) - 1, -1, -1):
                color_attributes.remove(color_attributes[r])
            success = True
        return success

    def remove_attr_by_name(mesh: bpy.types.Object, name: str, mode: str = "INCLUDE"):

        for attr in mesh.data.color_attributes:

            match mode:
                case "INCLUDE":
                    if attr.name == name:
                        mesh.data.color_attributes.remove(attr)
                        break
                case "EXCLUDE":
                    if attr.name is not None:
                        if attr.name != name:
                            mesh.data.color_attributes.remove(attr)

    def add_curvature(mesh):
        """为选中的mesh添加curvature vertex color层
        注意：Blender 5.0+ 要求 mesh 必须有顶点才能创建 color attribute
        """
        # Blender 5.0+: 空 mesh 无法添加 color attribute
        if len(mesh.data.vertices) == 0:
            print(f"{mesh.name} has no vertices, cannot add curvature color attribute")
            return None

        visibility = mesh.visible_get()
        if visibility is False:
            mesh.hide_viewport = False
        bpy.context.view_layer.objects.active = mesh
        current_mode = bpy.context.object.mode

        if CURVATURE_ATTR in mesh.data.color_attributes:
            color_attribute = mesh.data.color_attributes.get(CURVATURE_ATTR)
            mesh.data.color_attributes.remove(color_attribute)

        vertex_color_layer = mesh.data.color_attributes.new(
            name=CURVATURE_ATTR,
            type="BYTE_COLOR",
            domain="CORNER",
        )

        mesh.data.attributes.active_color = vertex_color_layer

        if current_mode != "VERTEX_PAINT":
            bpy.ops.object.mode_set(mode="VERTEX_PAINT")

        bpy.ops.paint.vertex_color_dirt(
            blur_strength=1,
            blur_iterations=1,
            clean_angle=3.14159,
            dirt_angle=0,
            dirt_only=False,
            normalize=True,
        )
        bpy.ops.object.mode_set(mode=current_mode)
        if visibility is False:
            mesh.hide_viewport = True

    def set_alpha(mesh, alpha_value, vertexcolor_name: str):

        visibility = mesh.visible_get()
        if visibility is False:
            mesh.hide_viewport = False
        bpy.context.view_layer.objects.active = mesh
        current_mode = bpy.context.object.mode
        if current_mode != "VERTEX_PAINT":
            bpy.ops.object.mode_set(mode="VERTEX_PAINT")

        if vertexcolor_name in mesh.data.color_attributes:
            color_attribute = mesh.data.color_attributes.get(vertexcolor_name)
        mesh.data.attributes.active_color = color_attribute

        mesh = mesh.data
        ca = mesh.attributes.active_color
        if ca.domain == "POINT":
            for vi, v in enumerate(mesh.vertices):
                if v.select:
                    ca.data[vi].color[3] = alpha_value
        elif ca.domain == "CORNER":
            for li, l in enumerate(mesh.loops):
                if mesh.vertices[l.vertex_index].select:
                    ca.data[li].color[3] = alpha_value

        bpy.ops.object.mode_set(mode=current_mode)
        if visibility is False:
            mesh.hide_viewport = True


class MeshAttributes:
    def add(mesh:bpy.types.Object, attribute_name: str, data_type: str, domain: str):

        if attribute_name not in mesh.data.attributes:
            target_attribute = mesh.data.attributes.new(
                attribute_name, data_type, domain
            )
        else:
            target_attribute = mesh.data.attributes[attribute_name]
    
        return target_attribute

    def fill_points(mesh:bpy.types.Object, attribute, value: float):
        value = float(value)
        attribute_values = [value for i in range(len(mesh.data.vertices))]
        attribute.data.foreach_set("value", attribute_values)
        mesh.data.update()


class Viewport:
    def is_local_view():
        is_local_view = False
        view3d_space=Viewport.get_3dview_space()
        # if bpy.context.space_data.local_view:
        if view3d_space.local_view:
            is_local_view = True
        return is_local_view

    def get_3dview_space():
        target_space = None
        area = check_screen_area("VIEW_3D")
        if area:
            for space in area.spaces:
                if "View3D" in str(space):
                    target_space = space
                    break
        return target_space


def copy_to_clip(txt: str):
    """copy text string to clipboard"""
    cmd = "echo " + txt.strip() + "|clip"
    return subprocess.check_call(cmd, shell=True)


class Outliner:
    def get_selected_object_ids():
        area = next(
            area for area in bpy.context.window.screen.areas if area.type == "OUTLINER"
        )

        with bpy.context.temp_override(
            window=bpy.context.window,
            area=area,
            region=next(region for region in area.regions if region.type == "WINDOW"),
            screen=bpy.context.window.screen,
        ):
            ids = bpy.context.selected_ids
            objects_in_selection = []
            for item in ids:
                if item.bl_rna.identifier == "Object":
                    objects_in_selection.append(item.name)

        if len(objects_in_selection) == 0:
            return None
        else:  # Print the dict to the console
            return objects_in_selection

    def get_selected_collection_ids():
        area = next(
            area for area in bpy.context.window.screen.areas if area.type == "OUTLINER"
        )

        with bpy.context.temp_override(
            window=bpy.context.window,
            area=area,
            region=next(region for region in area.regions if region.type == "WINDOW"),
            screen=bpy.context.window.screen,
        ):
            ids = bpy.context.selected_ids
            objects_in_selection = []
            for item in ids:
                if item.bl_rna.identifier == "Collection":
                    objects_in_selection.append(item.name)

        if len(objects_in_selection) == 0:
            return None
        else:  # Print the dict to the console
            return objects_in_selection

    def get_selected_objects():
        """return selected outliner objects"""
        selection_ids = Outliner.get_selected_object_ids()
        objects = []
        if selection_ids is not None:
            for id in selection_ids:
                if bpy.context.scene.objects[id]:
                    objects.append(bpy.context.scene.objects[id])
        if len(objects) == 0:
            return None
        else:
            return objects

    def get_selected_collections():
        """
        return selected outliner collections
        """
        # print_selected_collections()
        selection_ids = Outliner.get_selected_collection_ids()
        objects = []
        if selection_ids is not None:
            for id in selection_ids:
                if bpy.data.collections[id]:
                    objects.append(bpy.data.collections[id])
        if len(objects) == 0:
            return None
        else:
            return objects


class FilePath:
    
    
    def open_os_path(path:str):
        
        # os.startfile(path) 
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            opener = "open" if platform.system() == "Darwin" else "xdg-open"
            subprocess.call([opener, path])
    
    def is_path_exists(path:str) -> bool:
        return os.path.exists(path)

class Mesh:

    def check_open_bondary(mesh:bpy.types.Object) -> bool:
        """检查是否存在开放边"""
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        check_result = False
        for edge in bm.edges:
            if edge.is_boundary:
                check_result = True
                break
        bm.clear()
        bm.free()

        return check_result
    
    def clean_lonely_verts(mesh:bpy.types.Object) -> None:
        """清理孤立顶点"""
        lonely_verts_list = []
        if mesh.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        for vertex in bm.verts:  # 遍历顶点，如果顶点不隐藏且连接边数为2，添加到删除列表
            if vertex.hide is False and len(vertex.link_edges) == 2:
                lonely_verts_list.append(vertex)

        bmesh.ops.dissolve_verts(
            bm, verts=lonely_verts_list, use_face_split=False, use_boundary_tear=False
        )

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()


    def clean_mid_verts(mesh:bpy.types.Object) -> None:
        """清理直线中的孤立顶点"""
        mid_verts_list = []

        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        # bm.verts.ensure_lookup_table()
        for vertex in bm.verts:  # 遍历顶点，如果顶点不隐藏且连接边数为2，添加到删除列表
            if vertex.hide is False and len(vertex.link_edges) == 2:
                mid_verts_list.append(vertex)
        bmesh.ops.dissolve_verts(
            bm, verts=mid_verts_list, use_face_split=False, use_boundary_tear=False
        )

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()


    def clean_loose_verts(mesh:bpy.types.Object) -> None:
        """清理松散顶点"""
        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)
        # verts with no linked faces
        verts = [v for v in bm.verts if not v.link_faces]
        for vert in verts:
            bm.verts.remove(vert)

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()


    def merge_verts_by_distance(mesh:bpy.types.Object, merge_distance:float=0.01) -> None:
        """清理重复顶点"""
        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()

    def merge_verts_ops(meshes:list) -> None:
        for obj in bpy.data.objects:
            obj.select_set(False)
        
        for mesh in meshes:
            mesh.select_set(True)

        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001,use_unselected=True,use_sharp_edge_from_normals=True)
        bpy.ops.object.mode_set(mode="OBJECT")


    def dissolve_flat_edges(mesh: bpy.types.Object):
        """
        溶解平面区域的内部支撑边 (support edges)。
        只保留平面区域的外轮廓边，避免 UV Seam 被标记到这些无意义的边上。
        
        定义"内部边"：
        - 边的两个相邻面法线方向基本相同（在同一平面上）
        - 边不是边界边 (is_boundary = False)
        """
        current_mode = mesh.mode
        if current_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        FLAT_THRESHOLD = 0.02  # ~1.1 degrees in radians
        
        edges_to_dissolve = []
        
        for edge in bm.edges:
            # Skip boundary edges (they are always important)
            if edge.is_boundary:
                continue
            
            # Must have exactly 2 linked faces
            if len(edge.link_faces) != 2:
                continue
            
            # Check dihedral angle
            try:
                face_angle = abs(edge.calc_face_angle_signed())
            except ValueError:
                continue
            
            # If edge is flat (angle close to 0 or Pi), it's a support edge
            if face_angle < FLAT_THRESHOLD or abs(face_angle - 3.14159) < FLAT_THRESHOLD:
                edges_to_dissolve.append(edge)
        
        # Dissolve the internal edges
        if edges_to_dissolve:
            bmesh.ops.dissolve_edges(bm, edges=edges_to_dissolve, use_verts=True, use_face_split=False)
        
        bm.to_mesh(mesh.data)
        mesh.data.update()
        bm.free()
        
        if current_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')


    def find_revolve_cap_boundaries(island_faces: set, island_edges: set) -> tuple[set, int]:
        """
        找到回转体/双盖模型的侧面边界环（使用极性分数选轴 + 严格侧面判定）
        
        参数：
            island_faces: 当前 island 的所有面
            island_edges: 当前 island 的所有边
            
        返回：
            (boundary_edges, axis_idx)
            boundary_edges: set[BMEdge] - 侧面与盖子的分界边
            axis_idx: int - 判定出的主轴索引 (0=X, 1=Y, 2=Z)
        """
        from mathutils import Vector
        
        # 1. 确定主轴：使用“极性分数”
        axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
        axis_scores = [0.0, 0.0, 0.0]

        POLARITY_TOLERANCE_SIDE = 0.1  # 视为侧面的 dot 阈值
        POLARITY_TOLERANCE_CAP = 0.9   # 视为盖面的 dot 阈值

        for face in island_faces:
            area = face.calc_area()
            for i, axis in enumerate(axis_vectors):
                dot = abs(face.normal.dot(axis))
                # 如果 dot 落在两极区间，加分
                if dot < POLARITY_TOLERANCE_SIDE or dot > POLARITY_TOLERANCE_CAP:
                    axis_scores[i] += area

        axis_idx = max(range(3), key=lambda i: axis_scores[i])
        axis_vec = axis_vectors[axis_idx]
        
        # 2. 严格定义 Side Face
        # 使用非常严格的阈值提取侧面 (STRICT_SIDE_THRESHOLD = 0.05)
        STRICT_SIDE_THRESHOLD = 0.05 
        
        strict_side_faces = set()
        for face in island_faces:
            dot = abs(face.normal.dot(axis_vec))
            if dot < STRICT_SIDE_THRESHOLD:
                strict_side_faces.add(face)
                
        # 3. 找出 Strict Side Region 的边界边
        boundary_edges = set()
        for edge in island_edges:
            if edge.is_boundary:
                continue
                
            linked = [f for f in edge.link_faces if f in island_faces]
            if len(linked) == 2:
                f0_is_side = linked[0] in strict_side_faces
                f1_is_side = linked[1] in strict_side_faces
                
                # XOR: 只有一侧是 strict side，说明这是侧面与倒角/盖面的分界线
                if f0_is_side != f1_is_side:
                    boundary_edges.add(edge)
                    
        return boundary_edges, axis_idx


    def auto_seam(mesh: bpy.types.Object, mode: str = 'STANDARD'):
        """
        Automatically mark seams for closed shapes
        
        参数：
            mesh: Mesh 对象
            mode: 'STANDARD' - 标准模式（两端开口的圆柱/管道）
                  'CAPPED' - 带盖模式（单端封闭的环形模型）
        """
        from mathutils import Vector

        # Ensure we are in object mode to access data correctly or use bmesh from object
        current_mode = mesh.mode
        if current_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 读取 sharp_edge attribute
        mesh_data = mesh.data
        sharp_edge_attr = mesh_data.attributes.get("sharp_edge")
        if sharp_edge_attr:
            sharp_edge_values = [d.value for d in sharp_edge_attr.data]
        else:
            # fallback: 用 edge.use_edge_sharp
            sharp_edge_values = [e.use_edge_sharp for e in mesh_data.edges]

        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # ============================================================
        # CAPPED 模式预处理：在分 island 之前，对整个 mesh 找 cap boundaries
        # ============================================================
        cap_faces = set()  # 存储盖子区域的面
        global_axis_idx = 2  # 默认 Z 轴
        
        if mode == 'CAPPED':
            all_faces = set(bm.faces)
            all_edges = set(bm.edges)
            
            # 对整个 mesh 调用 find_revolve_cap_boundaries
            cap_boundary_edges, global_axis_idx = Mesh.find_revolve_cap_boundaries(all_faces, all_edges)
            
            print(f"[auto_seam CAPPED] Found {len(cap_boundary_edges)} cap boundary edges on entire mesh")
            
            if cap_boundary_edges:
                # 标记 cap boundary edges 为 seam
                for edge in cap_boundary_edges:
                    edge.seam = True
                
                # 识别 cap_faces（法线平行于主轴的面）
                axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
                axis_vec = axis_vectors[global_axis_idx]
                CAP_FACE_THRESHOLD = 0.9  # dot > 0.9 算作盖面
                
                for face in all_faces:
                    if abs(face.normal.dot(axis_vec)) > CAP_FACE_THRESHOLD:
                        cap_faces.add(face)
                
                print(f"[auto_seam CAPPED] Identified {len(cap_faces)} cap faces (axis: {['X', 'Y', 'Z'][global_axis_idx]})")

        # 1. Identify Islands (connected faces not separated by seams)
        total_faces = set(bm.faces)
        visited_faces = set()
        
        islands = []

        while len(visited_faces) < len(total_faces):
            seed_face = next(iter(total_faces - visited_faces))
            island = set()
            stack = [seed_face]
            
            while stack:
                f = stack.pop()
                if f in visited_faces:
                    continue
                visited_faces.add(f)
                island.add(f)
                
                for edge in f.edges:
                    if not edge.seam: 
                        for neighbor_face in edge.link_faces:
                            if neighbor_face not in visited_faces:
                                stack.append(neighbor_face)
            islands.append(island)

        # 2. Process each island
        for island in islands:
            # ============================================================
            # CAPPED 模式：跳过盖子 island（只包含 cap faces 的 island）
            # ============================================================
            if mode == 'CAPPED' and cap_faces:
                # 判断是否是 cap island（大部分面都是 cap faces）
                cap_face_count = sum(1 for face in island if face in cap_faces)
                cap_ratio = cap_face_count / len(island) if island else 0
                
                if cap_ratio > 0.8:  # 80% 以上是盖面，视为 cap island
                    print(f"[auto_seam CAPPED] Skipping cap island ({len(island)} faces, {cap_ratio:.1%} cap faces)")
                    continue
            
            # Find boundary edges for this island
            boundary_edges = set()
            island_verts = set()

            for face in island:
                for v in face.verts:
                    island_verts.add(v)
                for edge in face.edges:
                    if edge.seam or edge.is_boundary:
                        boundary_edges.add(edge)
                    else:
                        # Check if edge connects to a face NOT in this island (should be covered by seam check strictly speaking, but for safety)
                        # If edge.seam is False, it implies all linked faces are in island (per flood fill logic)
                        pass
            
            # Group boundary edges into Loops
            loops = []
            if boundary_edges:
                edge_pool = set(boundary_edges)
                while edge_pool:
                    # Trace a loop
                    seed_edge = next(iter(edge_pool))
                    edge_pool.remove(seed_edge)
                    
                    # This is simple grouping, might not be perfectly ordered loops, but enough to identify separate holes
                    current_loop = {seed_edge}
                    
                    # Grow loop
                    # A better way: Find connected components of edges in the graph of 'boundary_edges'
                    # Vertices involved in boundary edges
                    loop_stack = [seed_edge]
                    while loop_stack:
                        e = loop_stack.pop()
                        # Find connected edges in pool
                        # Edges share a vertex
                        v1, v2 = e.verts
                        
                        connected_neighbors = []
                        for check_e in list(edge_pool): # Check copy to allow removal
                            if check_e in edge_pool: # double check
                                if check_e.verts[0] == v1 or check_e.verts[0] == v2 or check_e.verts[1] == v1 or check_e.verts[1] == v2:
                                    connected_neighbors.append(check_e)
                        
                        for ne in connected_neighbors:
                            edge_pool.remove(ne)
                            current_loop.add(ne)
                            loop_stack.append(ne)
                    
                    loops.append(current_loop)

            # Analyze Topology
            num_loops = len(loops)
            
            print(f"[auto_seam DEBUG] ========== Island Analysis ==========")
            print(f"[auto_seam DEBUG] Mode: {mode}, num_loops: {num_loops}")
            
            if num_loops == 0:
                print(f"[auto_seam DEBUG] Entering num_loops == 0 branch (closed surface)")
                # Closed Surface (Sphere, Torus) or Double-capped model
                # Get all island edges and faces for processing
                island_edges = set()
                for face in island:
                    for edge in face.edges:
                        island_edges.add(edge)
                island_faces = set(island)
                
                verts_list = list(island_verts)
                if not verts_list: continue

                # Calculate bounding box to find dominant axis
                min_bb = Vector((float('inf'), float('inf'), float('inf')))
                max_bb = Vector((float('-inf'), float('-inf'), float('-inf')))
                
                for v in verts_list:
                    for i in range(3):
                        min_bb[i] = min(min_bb[i], v.co[i])
                        max_bb[i] = max(max_bb[i], v.co[i])
                
                size = max_bb - min_bb
                axis_idx = 0
                if size.y > size.x and size.y > size.z:
                    axis_idx = 1
                elif size.z > size.x and size.z > size.y:
                    axis_idx = 2
                
                # ============================================================
                # CAPPED 模式：对于封闭的双盖模型，使用 find_revolve_cap_boundaries
                # ============================================================
                if mode == 'CAPPED':
                    # 用 Revolve Cap 算法找盖子边界边
                    cap_boundary_edges, precise_axis_idx = Mesh.find_revolve_cap_boundaries(island_faces, island_edges)
                    
                    print(f"[auto_seam DEBUG] num_loops=0, CAPPED mode: found {len(cap_boundary_edges)} cap boundary edges")
                    
                    if cap_boundary_edges:
                        # 标记盖子边界为 seam
                        for edge in cap_boundary_edges:
                            edge.seam = True
                        print(f"[auto_seam DEBUG] Marked {len(cap_boundary_edges)} cap boundary edges as seam")
                        
                        # 获取边界边的顶点，用于找垂直连接路径
                        cap_boundary_verts = set()
                        for edge in cap_boundary_edges:
                            cap_boundary_verts.add(edge.verts[0])
                            cap_boundary_verts.add(edge.verts[1])
                        
                        # 将边界边按高度分成上下两组
                        edge_heights = []
                        for edge in cap_boundary_edges:
                            mid = (edge.verts[0].co + edge.verts[1].co) / 2
                            edge_heights.append((edge, mid[precise_axis_idx]))
                        
                        if edge_heights:
                            min_height = min(h for _, h in edge_heights)
                            max_height = max(h for _, h in edge_heights)
                            mid_height = (min_height + max_height) / 2
                            
                            lower_verts = set()
                            upper_verts = set()
                            for edge, h in edge_heights:
                                if h < mid_height:
                                    lower_verts.add(edge.verts[0])
                                    lower_verts.add(edge.verts[1])
                                else:
                                    upper_verts.add(edge.verts[0])
                                    upper_verts.add(edge.verts[1])
                            
                            print(f"[auto_seam DEBUG] lower_verts: {len(lower_verts)}, upper_verts: {len(upper_verts)}")
                            
                            # 找 bevel edges 用于路径搜索
                            ANGLE_THRESHOLD = 0.98
                            bevel_edges = set()
                            for edge in island_edges:
                                if edge.is_boundary or edge.seam:
                                    continue
                                if sharp_edge_values[edge.index]:
                                    continue
                                linked_faces = [f for f in edge.link_faces if f in island_faces]
                                if len(linked_faces) == 2:
                                    dot = linked_faces[0].normal.dot(linked_faces[1].normal)
                                    if dot < ANGLE_THRESHOLD:
                                        bevel_edges.add(edge)
                            
                            # 在两个边界环之间找 bevel path
                            if lower_verts and upper_verts and bevel_edges:
                                import heapq
                                
                                def find_bevel_path(start_verts, target_verts, valid_edges):
                                    all_verts = set()
                                    for e in valid_edges:
                                        all_verts.add(e.verts[0])
                                        all_verts.add(e.verts[1])
                                    
                                    dist = {v: float('inf') for v in all_verts}
                                    prev_edge = {}
                                    pq = []
                                    
                                    for v in start_verts:
                                        if v in dist:
                                            dist[v] = 0
                                            heapq.heappush(pq, (0, id(v), v))
                                    
                                    while pq:
                                        d, _, v = heapq.heappop(pq)
                                        if d > dist[v]:
                                            continue
                                        if v in target_verts:
                                            path = []
                                            current = v
                                            while current in prev_edge:
                                                edge = prev_edge[current]
                                                path.append(edge)
                                                current = edge.other_vert(current)
                                            return path
                                        for e in v.link_edges:
                                            if e in valid_edges:
                                                other = e.other_vert(v)
                                                new_dist = d + e.calc_length()
                                                if new_dist < dist.get(other, float('inf')):
                                                    dist[other] = new_dist
                                                    prev_edge[other] = e
                                                    heapq.heappush(pq, (new_dist, id(other), other))
                                    return []
                                
                                path_edges = find_bevel_path(lower_verts, upper_verts, bevel_edges)
                                if path_edges:
                                    for e in path_edges:
                                        e.seam = True
                                    print(f"[auto_seam DEBUG] Marked {len(path_edges)} vertical seam edges")
                                else:
                                    print(f"[auto_seam DEBUG] No bevel path found between cap boundaries")
                    else:
                        print(f"[auto_seam DEBUG] No cap boundary edges found, using default path")
                        # Fallback: 使用默认的 shortest path
                        verts_list.sort(key=lambda v: v.co[axis_idx])
                        min_v = verts_list[0]
                        max_v = verts_list[-1]
                        bias_vector = Vector((0.0, 0.0, 0.0))
                        bias_vector[axis_idx] = 1.0
                        path_edges, _ = Mesh.find_shortest_path(bm, min_v, max_v, island, bias_vector=bias_vector)
                        if path_edges:
                            for e in path_edges:
                                e.seam = True
                else:
                    # STANDARD 模式: 原来的逻辑
                    verts_list.sort(key=lambda v: v.co[axis_idx])
                    min_v = verts_list[0]
                    max_v = verts_list[-1]
                    
                    # Create bias vector for pathfinding (dominant axis)
                    bias_vector = Vector((0.0, 0.0, 0.0))
                    bias_vector[axis_idx] = 1.0
                    
                    # Find shortest path edges
                    path_edges, _ = Mesh.find_shortest_path(bm, min_v, max_v, island, bias_vector=bias_vector)
                    if path_edges:
                        for e in path_edges:
                            e.seam = True

            elif num_loops >= 1:
                print(f"[auto_seam DEBUG] Entering num_loops >= 1 branch (has boundary loops)")
                # Cylinder-like (Side wall) with one or more boundary loops (holes/openings)
                # For num_loops == 1: single opening (like a cup or hollow cylinder)
                # For num_loops >= 2: multiple holes or a tube

                # 1. Calculate Center of each loop first
                loop_info = []
                for idx, loop in enumerate(loops):
                    center = Vector((0.0, 0.0, 0.0))
                    count = 0
                    for edge in loop:
                        for v in edge.verts:
                            center += v.co
                            count += 1
                    if count > 0:
                        center /= count
                    loop_info.append({'index': idx, 'center': center, 'edge_count': len(loop)})

                # 2. Determine dominant axis by loop spread (not bounding box)
                centers = [li['center'] for li in loop_info]
                spread_x = max(c.x for c in centers) - min(c.x for c in centers)
                spread_y = max(c.y for c in centers) - min(c.y for c in centers)
                spread_z = max(c.z for c in centers) - min(c.z for c in centers)

                if spread_z >= spread_x and spread_z >= spread_y:
                    axis_idx = 2
                elif spread_y >= spread_x and spread_y >= spread_z:
                    axis_idx = 1
                else:
                    axis_idx = 0

                # 3. Sort loops by position on dominant axis
                loop_centers = []
                for li in loop_info:
                    li['measure'] = li['center'][axis_idx]
                    loop_centers.append(li)
                loop_centers.sort(key=lambda x: x['measure'])

                # First, get all island edges
                island_edges = set()
                for face in island:
                    for edge in face.edges:
                        island_edges.add(edge)

                island_faces = set(island)
                ANGLE_THRESHOLD = 0.98  # dot < 0.98 means angle > ~11°

                # ============================================================
                # 方法：sharp_edge attribute + bevel edges 连通性检测
                # 1. 外轮廓边 = sharp edges（直接从 attribute）
                # 2. Bevel edges = 法线角度法选中 + 非 sharp
                # 3. 用 bevel edges 做连通性检测区分内外 boundary loops
                # ============================================================

                # 1. 找出所有 sharp edges（外轮廓边）
                sharp_edges_in_island = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    if sharp_edge_values[edge.index]:
                        sharp_edges_in_island.add(edge)

                # 2. 法线角度法找 bevel edges（用于连通性检测）
                bevel_edges = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    if sharp_edge_values[edge.index]:
                        continue  # 跳过 sharp edges
                    linked_faces = [f for f in edge.link_faces if f in island_faces]
                    if len(linked_faces) == 2:
                        dot = linked_faces[0].normal.dot(linked_faces[1].normal)
                        if dot < ANGLE_THRESHOLD:
                            bevel_edges.add(edge)

                # 3. 用 bevel edges 做连通性检测
                # 获取每个 loop 的顶点集合
                loop_verts_list = []
                for loop in loops:
                    verts = set()
                    for edge in loop:
                        verts.add(edge.verts[0])
                        verts.add(edge.verts[1])
                    loop_verts_list.append(verts)

                def find_reachable_verts(start_verts, valid_edges):
                    """从 start_verts 出发，沿着 valid_edges 能到达的所有顶点"""
                    visited = set(start_verts)
                    stack = list(start_verts)
                    while stack:
                        v = stack.pop()
                        for e in v.link_edges:
                            if e in valid_edges:
                                other_v = e.other_vert(v)
                                if other_v not in visited:
                                    visited.add(other_v)
                                    stack.append(other_v)
                    return visited

                # 4. 找出通过 bevel edges 连通的 loops
                connected_groups = []
                visited_loops = set()

                for start_idx in range(len(loops)):
                    if start_idx in visited_loops:
                        continue

                    # 从这个 loop 的顶点开始 flood fill（沿着 bevel edges）
                    reachable = find_reachable_verts(loop_verts_list[start_idx], bevel_edges)

                    # 检查哪些其他 loops 的顶点在 reachable 中
                    connected_group = {start_idx}
                    for other_idx in range(len(loops)):
                        if other_idx != start_idx:
                            if loop_verts_list[other_idx] & reachable:
                                connected_group.add(other_idx)

                    connected_groups.append(connected_group)
                    visited_loops |= connected_group

                # 5. 选最大的连通组作为外轮廓
                def calc_loop_perimeter(loop_idx):
                    return sum(e.calc_length() for e in loops[loop_idx])

                best_group = None
                best_score = (-1, -1)

                for group in connected_groups:
                    size = len(group)
                    total_perimeter = sum(calc_loop_perimeter(idx) for idx in group)
                    score = (size, total_perimeter)
                    if score > best_score:
                        best_score = score
                        best_group = group

                outer_loops = list(best_group) if best_group else []

                # 6. 从外轮廓 loops 中选首尾两个（按主轴排序）
                outer_loop_centers = [lc for lc in loop_centers if lc['index'] in outer_loops]
                if len(outer_loop_centers) >= 2:
                    start_loop_idx = outer_loop_centers[0]['index']
                    end_loop_idx = outer_loop_centers[-1]['index']
                else:
                    # fallback: 用所有 loops 的首尾
                    start_loop_idx = loop_centers[0]['index']
                    end_loop_idx = loop_centers[-1]['index']

                l1_edges = list(loops[start_loop_idx])
                l2_edges = list(loops[end_loop_idx])

                # 7. 外轮廓 boundary edges
                outer_boundary_edges = set()
                for idx in outer_loops:
                    outer_boundary_edges |= loops[idx]

                # Classify edges - use sharp_edge attribute
                silhouette_edges = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        # Only include if it's part of outer loops
                        if edge in outer_boundary_edges:
                            silhouette_edges.add(edge)
                        continue
                    if edge.seam:
                        silhouette_edges.add(edge)
                        continue
                    # Use sharp_edge attribute instead of coplanar region detection
                    if sharp_edge_values[edge.index]:
                        silhouette_edges.add(edge)

                # ============================================================
                # Dijkstra 路径搜索：在 bevel edges 上找连接两个外轮廓 loops 的最短路径
                # ============================================================
                import heapq

                def find_bevel_edge_path(start_verts, target_verts, valid_edges):
                    """在 bevel edges 上搜索连接两组顶点的最短路径"""
                    # 初始化：收集所有 valid_edges 涉及的顶点
                    all_verts = set()
                    for e in valid_edges:
                        all_verts.add(e.verts[0])
                        all_verts.add(e.verts[1])

                    dist = {v: float('inf') for v in all_verts}
                    prev_edge = {}  # 记录到达每个顶点的边

                    pq = []
                    for v in start_verts:
                        if v in dist:
                            dist[v] = 0
                            heapq.heappush(pq, (0, id(v), v))

                    while pq:
                        d, _, v = heapq.heappop(pq)
                        if d > dist[v]:
                            continue

                        # 检查是否到达目标
                        if v in target_verts:
                            # 回溯路径
                            path = []
                            current = v
                            while current in prev_edge:
                                edge = prev_edge[current]
                                path.append(edge)
                                current = edge.other_vert(current)
                            return path, d

                        # 遍历邻边
                        for e in v.link_edges:
                            if e in valid_edges:
                                other = e.other_vert(v)
                                new_dist = d + e.calc_length()
                                if new_dist < dist.get(other, float('inf')):
                                    dist[other] = new_dist
                                    prev_edge[other] = e
                                    heapq.heappush(pq, (new_dist, id(other), other))

                    return [], float('inf')

                print(f"[auto_seam DEBUG] Island has {len(island)} faces, {len(island_edges)} edges")
                print(f"[auto_seam DEBUG] Sharp edges: {len(sharp_edges_in_island)}, Bevel edges: {len(bevel_edges)}")
                print(f"[auto_seam DEBUG] Outer loops: {outer_loops}, Mode: {mode}")

                # ============================================================
                # STANDARD 模式处理：在两个 outer loops 之间找 bevel path
                # (CAPPED 模式的 cap boundaries 已在预处理阶段完成，
                #  cap islands 已被跳过，这里只处理 side islands)
                # ============================================================
                if len(outer_loops) >= 2:
                    outer_loop_indices = sorted(outer_loops, key=lambda i: loop_centers[i]['center'][axis_idx])
                    loop1_verts = set(v for e in loops[outer_loop_indices[0]] for v in e.verts)
                    loop2_verts = set(v for e in loops[outer_loop_indices[-1]] for v in e.verts)

                    # Dijkstra 搜索
                    path_edges, path_cost = find_bevel_edge_path(loop1_verts, loop2_verts, bevel_edges)

                    print(f"[auto_seam DEBUG] loop1_verts: {len(loop1_verts)}, loop2_verts: {len(loop2_verts)}")
                    print(f"[auto_seam DEBUG] path found: {len(path_edges)} edges, cost: {path_cost:.4f}")

                    if path_edges:
                        for e in path_edges:
                            e.seam = True
                        print(f"[auto_seam DEBUG] Marked {len(path_edges)} bevel edges as seam")
                    else:
                        print(f"[auto_seam DEBUG] No path found on bevel edges!")
                elif len(outer_loops) < 2 and mode != 'CAPPED':
                    print(f"[auto_seam DEBUG] Not enough outer loops: {len(outer_loops)}")

        bm.to_mesh(mesh.data)
        bm.free()
        
        if current_mode == 'EDIT':
             bpy.ops.object.mode_set(mode='EDIT')

    def find_shortest_path(bm, start_vert, end_vert, valid_faces_set, bias_vector=None, allow_flat_edges=False, silhouette_edges_override=None, end_verts_set=None):
        """Dijkstra pathfinder. Flat edges are excluded unless allow_flat_edges=True.

        Args:
            end_vert: Single target vertex (used if end_verts_set is None)
            end_verts_set: Set of target vertices - path ends when ANY is reached
            silhouette_edges_override: If provided, use this set as silhouette edges instead of computing
        """
        import heapq

        # Determine target vertices
        if end_verts_set is not None:
            target_verts = end_verts_set
        else:
            target_verts = {end_vert}

        # Convert valid_faces to valid_edges set
        all_edges = set()
        for f in valid_faces_set:
            for e in f.edges:
                all_edges.add(e)

        # Use override if provided, otherwise compute
        if silhouette_edges_override is not None:
            silhouette_edges = silhouette_edges_override & all_edges
            print(f"[find_shortest_path DEBUG] Override provided: {len(silhouette_edges_override)}, all_edges: {len(all_edges)}, intersection: {len(silhouette_edges)}")
        else:
            # ============================================================
            # Identify Coplanar Regions using flood fill
            # ============================================================
            PLANE_DIST_THRESHOLD = 0.01  # 1cm threshold

            face_to_region = {}
            region_id = 0
            all_faces = set(valid_faces_set)
            region_visited = set()

            while len(region_visited) < len(all_faces):
                seed_face = next(iter(all_faces - region_visited))
                ref_normal = seed_face.normal.copy()
                ref_point = seed_face.verts[0].co.copy()

                stack = [seed_face]

                while stack:
                    f = stack.pop()
                    if f in region_visited:
                        continue

                    # Check if ALL vertices of this face lie on the reference plane
                    all_verts_on_plane = True
                    for v in f.verts:
                        dist = abs((v.co - ref_point).dot(ref_normal))
                        if dist > PLANE_DIST_THRESHOLD:
                            all_verts_on_plane = False
                            break

                    if all_verts_on_plane:
                        region_visited.add(f)
                        face_to_region[f] = region_id

                        # Add neighbors through non-seam, non-boundary edges
                        for edge in f.edges:
                            if not edge.seam and not edge.is_boundary:
                                for neighbor in edge.link_faces:
                                    if neighbor in all_faces and neighbor not in region_visited:
                                        stack.append(neighbor)

                region_id += 1

            # Classify edges as silhouette or flat
            silhouette_edges = set()

            for edge in all_edges:
                if edge.is_boundary:
                    silhouette_edges.add(edge)
                    continue

                if edge.seam:
                    silhouette_edges.add(edge)
                    continue

                linked_faces = [f for f in edge.link_faces if f in all_faces]
                if len(linked_faces) != 2:
                    silhouette_edges.add(edge)
                    continue

                f1, f2 = linked_faces
                region1 = face_to_region.get(f1, -1)
                region2 = face_to_region.get(f2, -2)

                if region1 != region2:
                    silhouette_edges.add(edge)

        # ============================================================
        # Dijkstra with edge filtering
        # ============================================================
        # When allow_flat_edges=False, COMPLETELY EXCLUDE flat edges
        valid_edges_for_path = all_edges if allow_flat_edges else silhouette_edges
        print(f"[find_shortest_path DEBUG] valid_edges_for_path: {len(valid_edges_for_path)}, target_verts: {len(target_verts)}")

        # Check if start_vert connects to any valid edge
        start_valid_edges = [e for e in start_vert.link_edges if e in valid_edges_for_path]
        print(f"[find_shortest_path DEBUG] start_vert has {len(start_valid_edges)} valid edges out of {len(start_vert.link_edges)} total")

        queue = [(0.0, id(start_vert), start_vert, [])]
        visited = {start_vert: 0.0}

        while queue:
            cost, _, current_v, path = heapq.heappop(queue)

            # Check if reached ANY target vertex
            if current_v in target_verts:
                return path, cost

            if cost > visited.get(current_v, float('inf')):
                continue

            for edge in current_v.link_edges:
                if edge not in valid_edges_for_path:
                    continue

                other_v = edge.other_vert(current_v)

                # Calculate Cost
                length = edge.calc_length()
                penalty_multiplier = 1.0

                # Directional bias penalty
                if bias_vector:
                    v_diff = (other_v.co - current_v.co)
                    if v_diff.length_squared > 0:
                        v_dir = v_diff.normalized()
                        dot = abs(v_dir.dot(bias_vector))
                        direction_penalty = (1.0 - dot) * 5.0
                        penalty_multiplier += direction_penalty

                new_cost = cost + (length * penalty_multiplier)

                if new_cost < visited.get(other_v, float('inf')):
                    visited[other_v] = new_cost
                    new_path = path + [edge]
                    heapq.heappush(queue, (new_cost, id(other_v), other_v, new_path))

        return None, float('inf')

class Modifier:
    def add_triangulate(mesh):
        """添加Triangulate Modifier"""
        if TRIANGULAR_MODIFIER in mesh.modifiers:
            triangulate_modifier = mesh.modifiers[TRIANGULAR_MODIFIER]

        else:
            triangulate_modifier = mesh.modifiers.new(
                name=TRIANGULAR_MODIFIER, type="TRIANGULATE"
            )

        # if BL_VERSION<4.2:
        triangulate_modifier.keep_custom_normals = True
        triangulate_modifier.min_vertices = 4
        triangulate_modifier.quad_method = "SHORTEST_DIAGONAL"
        return triangulate_modifier

    def add_geometrynode(mesh,modifier_name,node):
        """添加Geometry Nodes WearMask Modifier"""

        check_modifier = False

        for modifier in mesh.modifiers:
            if modifier.name == modifier_name:
                check_modifier = True
                break

        if check_modifier is False:
            geo_node_modifier = mesh.modifiers.new(
                name=modifier_name, type="NODES"
            )
            # geo_node_modifier.node_group = bpy.data.node_groups[node.name]
            geo_node_modifier.node_group = node
        else:
            geo_node_modifier = mesh.modifiers[modifier_name]
            geo_node_modifier.node_group = node
        return geo_node_modifier

    def remove(object, modifier_name: str, has_subobject: bool = False):
        """删除某个modifier,返回modifier对应的子object"""

        modifier_objects = []
        # bad_modifier_objects=[]
        if object.modifiers:
            for modifier in object.modifiers:
                if modifier is not None:
                    if modifier.name == modifier_name:
                        # 如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
                        if has_subobject is True and modifier.object is not None:
                            if modifier.object not in modifier_objects:
                                modifier_objects.append(modifier.object)
                        object.modifiers.remove(modifier)

        if len(modifier_objects) > 0:
            for modifier_object in modifier_objects:
                to_remove=True
                # parent_name=modifier_object.name.removeprefix(TRANSFERPROXY_PREFIX)
                # if modifier_object.parent:
                #     if modifier_object.parent.name == parent_name:
                #         to_remove=True
                # else:
                #     to_remove=True

                if to_remove is True:
                    old_mesh = modifier_object.data
                    old_mesh.name = "OldTP_" + old_mesh.name
                    bpy.data.objects.remove(modifier_object)
                    bpy.data.meshes.remove(old_mesh)



    def move_to_bottom(object,modifier_name):
        target_modifier = object.modifiers[modifier_name]
        modifier_count=len(object.modifiers)-1

        while object.modifiers[modifier_count] != target_modifier:
            bpy.ops.object.modifier_move_down(modifier=target_modifier.name)

    def move_to_top(object,modifier_name):
        target_modifier = object.modifiers[modifier_name]

        while object.modifiers[0] != target_modifier:
            bpy.ops.object.modifier_move_up(modifier=target_modifier.name)