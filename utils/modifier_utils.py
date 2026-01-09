# -*- coding: utf-8 -*-
"""
Modifier 操作工具函数
===================

包含 Modifier 检查、添加、删除等功能。
"""

import bpy
from ..Const import TRIANGULAR_MODIFIER


def check_modifier_exist(target_object: bpy.types.Object, modifier_name: str) -> bool:
    """
    检查是否存在某个 modifier 名

    Args:
        target_object: 目标对象
        modifier_name: Modifier 名称

    Returns:
        是否存在
    """
    modifier_exist = False
    for modifier in target_object.modifiers:
        if modifier.name == modifier_name:
            modifier_exist = True
            break
    return modifier_exist


def remove_modifier(object, modifier_name: str, has_subobject: bool = False):
    """
    删除某个 modifier

    Args:
        object: 目标对象
        modifier_name: Modifier 名称
        has_subobject: 是否有关联的子对象需要一并删除

    Returns:
        被删除的 modifier 对应的子对象列表（如果有）
    """
    modifier_objects = []
    for modifier in object.modifiers:
        if modifier.name == modifier_name:
            if has_subobject is True and modifier.object is not None:
                modifier_objects.append(modifier.object)
            object.modifiers.remove(modifier)

    if len(modifier_objects) > 0:
        for modifier_object in modifier_objects:
            if modifier_object.parent.name == object.name:
                old_mesh = modifier_object.data
                old_mesh.name = "OldTP_" + old_mesh.name
                print("remove modifier object: " + modifier_object.name)
                bpy.data.objects.remove(modifier_object)
                bpy.data.meshes.remove(old_mesh)

    return


def get_objects_with_modifier(
    target_objects: bpy.types.Object, modifier_name: str
) -> bpy.types.Object:
    """
    获取有某种 modifier 的 object 列表

    Args:
        target_objects: 目标对象列表
        modifier_name: Modifier 名称

    Returns:
        包含该 Modifier 的对象列表
    """
    objects = []
    for object in target_objects:
        for modifier in object.modifiers:
            if modifier is not None and modifier.name == modifier_name:
                if modifier.object is None:
                    objects.append(object)
            else:
                objects.append(object)
    return objects


def apply_modifiers(object: bpy.types.Object) -> bpy.types.Object:
    """
    应用所有修改器，删除原 mesh 并替换为新 mesh

    Args:
        object: 目标对象

    Returns:
        应用修改器后的对象
    """
    old_mesh = object.data

    deps_graph = bpy.context.evaluated_depsgraph_get()
    deps_graph.update()
    object_evaluated = object.evaluated_get(deps_graph)
    mesh_evaluated = bpy.data.meshes.new_from_object(
        object_evaluated, depsgraph=deps_graph
    )

    object.data = mesh_evaluated
    for modifier in object.modifiers:
        object.modifiers.remove(modifier)
    new_object = object

    old_mesh.name = "Old_" + old_mesh.name
    old_mesh.user_clear()
    bpy.data.meshes.remove(old_mesh)

    return new_object


class Modifier:
    """Modifier 操作工具类"""

    @staticmethod
    def add_triangulate(mesh):
        """
        添加 Triangulate Modifier

        Args:
            mesh: 目标 mesh 对象
        """
        if TRIANGULAR_MODIFIER in mesh.modifiers:
            triangulate_modifier = mesh.modifiers[TRIANGULAR_MODIFIER]
        else:
            triangulate_modifier = mesh.modifiers.new(
                name=TRIANGULAR_MODIFIER, type="TRIANGULATE"
            )

        triangulate_modifier.keep_custom_normals = True
        triangulate_modifier.min_vertices = 4
        triangulate_modifier.quad_method = "SHORTEST_DIAGONAL"

    @staticmethod
    def add_geometrynode(mesh, modifier_name: str, node):
        """
        添加 Geometry Nodes Modifier

        Args:
            mesh: 目标 mesh 对象
            modifier_name: Modifier 名称
            node: Node Group
        """
        check_modifier = False

        for modifier in mesh.modifiers:
            if modifier.name == modifier_name:
                check_modifier = True
                break

        if check_modifier is False:
            geo_node_modifier = mesh.modifiers.new(name=modifier_name, type="NODES")
            geo_node_modifier.node_group = node
        else:
            geo_node_modifier = mesh.modifiers[modifier_name]
            geo_node_modifier.node_group = node

    @staticmethod
    def remove(object, modifier_name: str, has_subobject: bool = False):
        """
        删除某个 modifier

        Args:
            object: 目标对象
            modifier_name: Modifier 名称
            has_subobject: 是否有关联的子对象
        """
        modifier_objects = []
        for modifier in object.modifiers:
            if modifier.name == modifier_name:
                if has_subobject is True and hasattr(modifier, 'object') and modifier.object is not None:
                    modifier_objects.append(modifier.object)
                object.modifiers.remove(modifier)

        if len(modifier_objects) > 0:
            for modifier_object in modifier_objects:
                if modifier_object.parent and modifier_object.parent.name == object.name:
                    old_mesh = modifier_object.data
                    old_mesh.name = "OldTP_" + old_mesh.name
                    print("remove modifier object: " + modifier_object.name)
                    bpy.data.objects.remove(modifier_object)
                    bpy.data.meshes.remove(old_mesh)

    @staticmethod
    def move_to_bottom(object, modifier_name: str):
        """
        将 Modifier 移动到堆栈底部

        Args:
            object: 目标对象
            modifier_name: Modifier 名称
        """
        if modifier_name in object.modifiers:
            modifier = object.modifiers[modifier_name]
            while object.modifiers[-1] != modifier:
                bpy.ops.object.modifier_move_down(modifier=modifier_name)

    @staticmethod
    def move_to_top(object, modifier_name: str):
        """
        将 Modifier 移动到堆栈顶部

        Args:
            object: 目标对象
            modifier_name: Modifier 名称
        """
        if modifier_name in object.modifiers:
            modifier = object.modifiers[modifier_name]
            while object.modifiers[0] != modifier:
                bpy.ops.object.modifier_move_up(modifier=modifier_name)
