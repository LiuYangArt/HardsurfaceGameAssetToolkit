# -*- coding: utf-8 -*-
"""
对象操作工具函数
===============

包含对象筛选、可见性设置、重命名等功能。
"""

import bpy
from ..Const import HST_PROP


def filter_type(target_objects: bpy.types.Object, type: str) -> bpy.types.Object:
    """
    筛选某种类型的 object

    Args:
        target_objects: 目标对象列表
        type: 对象类型 (MESH, ARMATURE, EMPTY 等)

    Returns:
        筛选后的对象列表，如果没有匹配则返回 None
    """
    filtered_objects = []
    type = str.upper(type)
    if target_objects:
        for object in target_objects:
            if object.type == type:
                filtered_objects.append(object)

    if len(filtered_objects) == 0:
        return None
    else:
        return filtered_objects


def filter_name(
    target_objects: bpy.types.Object, name: str, type: str = "INCLUDE"
) -> bpy.types.Object:
    """
    筛选某种名称的 object

    Args:
        target_objects: 目标对象列表
        name: 名称关键字
        type: INCLUDE 时包含匹配项，EXCLUDE 时排除匹配项

    Returns:
        筛选后的对象列表
    """
    filtered_objets = []
    match type:
        case "INCLUDE":
            for object in target_objects:
                if name in object.name:
                    filtered_objets.append(object)
        case "EXCLUDE":
            for object in target_objects:
                if name not in object.name:
                    filtered_objets.append(object)
    return filtered_objets


def clean_user(target_object: bpy.types.Object) -> None:
    """
    如果所选 object 有多个 user，转为 single user

    Args:
        target_object: 目标对象
    """
    if target_object.users > 1:
        target_object.data = target_object.data.copy()


def set_visibility(target_object: bpy.types.Object, visible: bool = True) -> bool:
    """
    设置 object 在 outliner 中的可见性

    Args:
        target_object: 目标对象
        visible: True 为可见，False 为隐藏

    Returns:
        设置后的可见性状态
    """
    if visible is True:
        target_object.hide_viewport = False
        target_object.hide_render = False
    else:
        target_object.hide_viewport = True
        target_object.hide_render = True
    return visible


def rename_meshes(target_objects, new_name: str) -> None:
    """
    重命名 mesh 对象

    Args:
        target_objects: 目标对象列表
        new_name: 新名称前缀
    """
    for index, object in enumerate(target_objects):
        if object.type == "MESH":
            object.name = new_name + "_" + str(index + 1).zfill(3)


class Object:
    """对象操作工具类"""

    @staticmethod
    def get_selected():
        """获取选中的对象列表"""
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            return None
        active_object = bpy.context.active_object
        if active_object not in selected_objects:
            selected_objects.append(active_object)
        return selected_objects

    @staticmethod
    def set_pivot_to_matrix(obj, matrix):
        """设置对象的原点到指定矩阵位置"""
        obj.matrix_world = matrix

    @staticmethod
    def set_pivot_location(obj, location):
        """
        Set the object's origin (pivot) to the specified world location.

        Args:
            obj: 目标对象
            location: 世界坐标位置 (Vector)
        """
        from mathutils import Vector
        
        cursor = bpy.context.scene.cursor
        original_location = cursor.location.copy()
        cursor.location = location
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        cursor.location = original_location

    @staticmethod
    def move_to_world_origin(obj):
        """将对象移动到世界原点"""
        obj.location = (0, 0, 0)

    @staticmethod
    def add_custom_property(obj: bpy.types.Object, prop_name: str, prop_value: str):
        """添加自定义属性"""
        obj[prop_name] = prop_value

    @staticmethod
    def read_custom_property(obj, prop_name):
        """读取自定义属性"""
        return obj.get(prop_name)

    @staticmethod
    def get_hst_type(object: bpy.types.Object):
        """获取对象的 HST 类型"""
        return object.get(HST_PROP)

    @staticmethod
    def mark_hst_type(object: bpy.types.Object, type: str):
        """
        标记对象类型为自定义属性

        可用类型：
            STATICMESH, DECAL, HIGH, SKELETALMESH, SKELETAL, UCX, SOCKET,
            PLACEHOLDER, PROXY

        Args:
            object: 目标对象
            type: 类型标识
        """
        # 如果已有类型标记且相同，跳过
        if HST_PROP in object.keys() and object[HST_PROP] == type:
            return
        
        object[HST_PROP] = type

        # 根据类型设置对象的渲染和显示属性
        match type:
            case "STATICMESH":
                object.hide_render = False
                object.display_type = "TEXTURED"
            case "DECAL":
                object.hide_render = False
                object.display_type = "TEXTURED"
            case "HIGH":
                object.hide_render = True
                object.display_type = "TEXTURED"
            case "SKELETALMESH":
                object.hide_render = False
                object.display_type = "TEXTURED"
            case "SKELETAL":
                object.hide_render = False
                object.display_type = "TEXTURED"
            case "UCX":
                object.hide_render = True
                object.display_type = "WIRE"
            case "SOCKET":
                object.hide_render = True
                object.display_type = "WIRE"
            case "PLACEHOLDER":
                object.hide_render = True
                object.display_type = "WIRE"
            case "PROXY":
                object.hide_render = True
                object.hide_viewport = True
                object.display_type = "WIRE"

    @staticmethod
    def filter_hst_type(objects, type: str, mode: str = "INCLUDE"):
        """
        Filter objects by HST type

        Args:
            objects: 对象列表
            type: 类型标识
            mode: INCLUDE 或 EXCLUDE

        Returns:
            筛选后的对象列表
        """
        filtered_objects = []
        if objects is None:
            return filtered_objects

        match mode:
            case "INCLUDE":
                for obj in objects:
                    if obj.get(HST_PROP) == type:
                        filtered_objects.append(obj)
            case "EXCLUDE":
                for obj in objects:
                    if obj.get(HST_PROP) != type:
                        filtered_objects.append(obj)
        return filtered_objects

    @staticmethod
    def sort_types(objects):
        """对对象列表按 HST 类型排序"""
        sorted_objects = {
            "STATICMESH": [],
            "DECAL": [],
            "UCX": [],
            "SOCKET": [],
            "OTHER": [],
        }
        for obj in objects:
            obj_type = obj.get(HST_PROP)
            if obj_type in sorted_objects:
                sorted_objects[obj_type].append(obj)
            else:
                sorted_objects["OTHER"].append(obj)
        return sorted_objects

    @staticmethod
    def check_empty_mesh(object):
        """检查是否为空 mesh"""
        if object.type == "MESH":
            return len(object.data.vertices) == 0
        return False

    @staticmethod
    def break_link_from_assetlib(object):
        """断开与资产库的连接"""
        if object.data.library is not None:
            object.data = object.data.copy()
            object.data.library = None
