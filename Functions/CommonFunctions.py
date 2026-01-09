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
# 从 utils 包导入工具类和函数（兼容层）
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

""" 
通用Functions 模块

此模块作为兼容层，所有工具类和函数已迁移至 utils 包。
项目特定的业务逻辑函数保留在此文件中。
"""


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


class FBXExport:
    """
    FBX 导出工具类
    
    用于导出 StaticMesh、SkeletalMesh 等到 FBX 格式
    """
    
    def instance_collection(target, file_path: str, reset_transform=False):
        """导出 Instance Collection 为 FBX"""
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
        """导出 StaticMesh FBX"""
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
            
            # 对 Bake Collection 进行处理
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
            obj.select_set(True)
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
        """导出骨骼 FBX"""
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
                if object.type == "ARMATURE":
                    armature_names[object] = object.name
                    if armature_as_root is False:
                        print("Remove Armature as root")
                        object.name = "Armature"  # fix armature export as redundant root bone
                    else:
                        print("Export Armature as root")
                    Armature.ops_scale_bones(object, (100, 100, 100))
                if object.type == "MESH" or object.type == "ARMATURE":
                    export_objects.append(object)
        elif target.type == "MESH":
            if target.hide_get() is True:
                hide_objects.append(target)
            export_objects.append(target)

        obj_transform = {}
        for obj in export_objects:
            obj.hide_set(False)
            obj.select_set(True)
            obj_transform[obj] = obj.matrix_world.copy()

            obj.location = (0, 0, 0)
            obj.rotation_euler = (0, 0, 0)
            obj.rotation_quaternion = Quaternion((1, 0, 0, 0))

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
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=True,
            armature_nodetype="NULL",
            bake_anim=False,
        )

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
    """筛选所选物体所在的 collection"""
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
    """筛选 collection 类型，返回筛选后的 collection 列表"""
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
    rename_alt(target_object, UCX_PREFIX + new_name, mark="_", num=2)


def filter_static_meshes(collection) -> tuple:
    """筛选 collection 中的 mesh，返回 (staticmeshes, ucx_meshes)"""
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
    """重命名 prop mesh"""
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
    """检查是否存在顶点色，如有返回顶点色层"""
    vertex_color_layer = None
    if len(mesh.data.color_attributes) > 0:
        vertex_color_layer = mesh.data.attributes.active_color
    return vertex_color_layer


def fix_ue_game_path(path: str):
    """修复 UE 路径"""
    path = str(path)
    path = normalize_path(path)
    if not path.startswith("/"):
        path = "/" + path
    return path


def fix_ip_input(ip_address: str):
    """修复 IP 地址格式"""
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
    """生成 UE Python 脚本命令"""
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
    """写入 json"""
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def read_json_from_file(file_path):
    """从文件读取 json"""
    json_dict = {}
    if file_path.exists():
        with open(file_path, "r") as json_file:
            json_dict = json.load(json_file)
    return json_dict