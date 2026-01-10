# -*- coding: utf-8 -*-
"""
导入工具函数
===========

包含从文件导入各种数据块的功能。
"""

import bpy


def remove_node(name: str):
    """
    删除指定名称的节点组

    Args:
        name: 节点组名称
    """
    node_exist = False
    node_import = None
    
    for node in bpy.data.node_groups:
        if name not in node.name:
            node_exist = False
        else:
            node_exist = True
            node_import = node
            break
    
    if node_exist and node_import:
        bpy.data.node_groups.remove(node_import)


def import_node_group(file_path, node_name: str) -> bpy.types.NodeGroup:
    """
    从文件载入 NodeGroup

    Args:
        file_path: 文件路径
        node_name: 节点组名称

    Returns:
        导入的节点组
    """
    INNER_PATH = "NodeTree"
    node_exist = False
    node_import = None
    
    for node in bpy.data.node_groups:
        if node_name not in node.name:
            node_exist = False
        else:
            node_exist = True
            node_import = node
            break

    if node_exist is False:
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=node_name,
        )

    for node in bpy.data.node_groups:
        if node.name == node_name:
            node_import = node
            break

    return node_import


def import_world(file_path, world_name: str) -> bpy.types.World:
    """
    从文件载入 World Shader

    Args:
        file_path: 文件路径
        world_name: World 名称

    Returns:
        导入的 World
    """
    INNER_PATH = "World"
    world_exist = False
    world_import = None
    
    for world in bpy.data.worlds:
        if world_name not in world.name:
            world_exist = False
        else:
            world_exist = True
            world_import = world
            break

    if world_exist is False:
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=world_name,
        )

    for world in bpy.data.worlds:
        if world.name == world_name:
            world_import = world
            break

    return world_import


def import_object(file_path, object_name: str):
    """
    从文件载入 Object

    Args:
        file_path: 文件路径
        object_name: 对象名称

    Returns:
        导入的对象
    """
    INNER_PATH = "Object"
    object_exist = False
    object_import = None
    
    for object in bpy.data.objects:
        if object_name not in object.name:
            object_exist = False
        else:
            object_exist = True
            object_import = object
            break

    if object_exist is False:
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=object_name,
        )

    for object in bpy.data.objects:
        if object.name == object_name:
            object_import = object
            break

    return object_import


def make_transfer_proxy_mesh(mesh, proxy_prefix: str, proxy_collection) -> bpy.types.Object:
    """
    建立传递模型

    Args:
        mesh: 源 mesh 对象
        proxy_prefix: 代理前缀
        proxy_collection: 代理所在的 Collection

    Returns:
        创建的代理 mesh 对象
    """
    from .object_utils import Object
    from .modifier_utils import apply_modifiers
    
    # 检查是否存在传递模型
    proxy_mesh_exist = False
    proxy_mesh = None
    
    for obj in proxy_collection.all_objects:
        if obj.name == proxy_prefix + mesh.name:
            proxy_mesh_exist = True
            proxy_mesh = obj
            break

    if proxy_mesh_exist is False:
        proxy_mesh = mesh.copy()
        proxy_mesh.data = mesh.data.copy()
        proxy_mesh.name = proxy_prefix + mesh.name
        proxy_mesh.parent = mesh
        proxy_collection.objects.link(proxy_mesh)
        proxy_mesh.hide_render = True
        Object.mark_hst_type(proxy_mesh, "PROXY")

        proxy_mesh = apply_modifiers(proxy_mesh)

    proxy_mesh.hide_viewport = True
    proxy_mesh.hide_render = True
    proxy_mesh.select_set(False)
    return proxy_mesh
