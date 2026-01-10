# -*- coding: utf-8 -*-
"""
导出工具函数
===========

包含 FBX 导出和相关功能。
"""

import bpy
from ..const import HST_PROP


def filter_static_meshes(collection):
    """
    筛选 collection 中的 mesh

    Args:
        collection: 目标 Collection

    Returns:
        (staticmeshes, ucx_meshes) 元组
    """
    staticmeshes = []
    ucx_meshes = []
    
    for obj in collection.all_objects:
        if obj.type != 'MESH':
            continue
        
        obj_type = obj.get(HST_PROP)
        
        if obj_type == 'UCX':
            ucx_meshes.append(obj)
        elif obj_type == 'DECAL':
            continue  # 剔除 decal
        else:
            staticmeshes.append(obj)
    
    return staticmeshes, ucx_meshes


def filter_collections_selection(target_objects):
    """
    筛选所选物体所在的 collection

    Args:
        target_objects: 目标对象列表

    Returns:
        Collection 列表
    """
    collections = []
    
    if not target_objects:
        return collections
    
    for obj in target_objects:
        for coll in obj.users_collection:
            if coll not in collections and coll.name != "Scene Collection":
                collections.append(coll)
    
    return collections


def filter_collection_types(collections):
    """
    筛选 collection 类型

    Args:
        collections: Collection 列表

    Returns:
        按类型分组的字典 (decal, prop, low, high)
    """
    sorted_collections = {
        "decal": [],
        "prop": [],
        "low": [],
        "high": [],
    }
    
    for coll in collections:
        coll_type = coll.get(HST_PROP)
        
        if coll_type == "DECAL":
            sorted_collections["decal"].append(coll)
        elif coll_type == "PROP":
            sorted_collections["prop"].append(coll)
        elif coll_type == "BAKE_LOW":
            sorted_collections["low"].append(coll)
        elif coll_type == "BAKE_HIGH":
            sorted_collections["high"].append(coll)
    
    return sorted_collections


class FBXExport:
    """FBX 导出工具类"""

    @staticmethod
    def instance_collection(target, file_path: str, reset_transform: bool = False):
        """
        导出 instance collection 的 staticmesh fbx

        Args:
            target: 目标对象或 Collection
            file_path: 导出路径
            reset_transform: 是否重置变换
        """
        # 保存当前选择
        original_selection = bpy.context.selected_objects.copy()
        original_active = bpy.context.active_object
        
        bpy.ops.object.select_all(action='DESELECT')
        
        # 获取要导出的对象
        objects_to_export = []
        if hasattr(target, 'all_objects'):
            objects_to_export = [obj for obj in target.all_objects if obj.type == 'MESH']
        else:
            objects_to_export = [target] if target.type == 'MESH' else []
        
        for obj in objects_to_export:
            obj.select_set(True)
        
        if objects_to_export:
            bpy.context.view_layer.objects.active = objects_to_export[0]
            
            bpy.ops.export_scene.fbx(
                filepath=file_path,
                use_selection=True,
                object_types={'MESH'},
                mesh_smooth_type='FACE',
                use_mesh_modifiers=True,
                use_triangles=False,
                axis_forward='-Y',
                axis_up='Z',
            )
        
        # 恢复选择
        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selection:
            obj.select_set(True)
        if original_active:
            bpy.context.view_layer.objects.active = original_active

    @staticmethod
    def staticmesh(target, file_path: str, reset_transform: bool = False):
        """
        导出 staticmesh fbx

        Args:
            target: 目标对象或 Collection
            file_path: 导出路径
            reset_transform: 是否重置变换
        """
        # 保存当前选择
        original_selection = bpy.context.selected_objects.copy()
        original_active = bpy.context.active_object
        
        bpy.ops.object.select_all(action='DESELECT')
        
        # 获取要导出的对象
        objects_to_export = []
        if hasattr(target, 'all_objects'):
            objects_to_export = [obj for obj in target.all_objects if obj.type in {'MESH', 'EMPTY'}]
        else:
            objects_to_export = [target]
        
        for obj in objects_to_export:
            obj.select_set(True)
        
        if objects_to_export:
            bpy.context.view_layer.objects.active = objects_to_export[0]
            
            bpy.ops.export_scene.fbx(
                filepath=file_path,
                use_selection=True,
                object_types={'MESH', 'EMPTY'},
                mesh_smooth_type='FACE',
                use_mesh_modifiers=True,
                use_triangles=False,
                axis_forward='-Y',
                axis_up='Z',
            )
        
        # 恢复选择
        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selection:
            obj.select_set(True)
        if original_active:
            bpy.context.view_layer.objects.active = original_active

    @staticmethod
    def skeletal(target, file_path: str, armature_as_root: bool = False):
        """
        导出骨骼 fbx

        Args:
            target: 目标 Armature 或包含 Armature 的 Collection
            file_path: 导出路径
            armature_as_root: 是否使用 Armature 作为根骨骼
        """
        # 保存当前选择
        original_selection = bpy.context.selected_objects.copy()
        original_active = bpy.context.active_object
        
        bpy.ops.object.select_all(action='DESELECT')
        
        # 获取要导出的对象
        objects_to_export = []
        armature = None
        
        if hasattr(target, 'all_objects'):
            for obj in target.all_objects:
                if obj.type == 'ARMATURE':
                    armature = obj
                    objects_to_export.append(obj)
                elif obj.type == 'MESH':
                    objects_to_export.append(obj)
        else:
            if target.type == 'ARMATURE':
                armature = target
                objects_to_export = [target]
                # 添加子 mesh
                for child in target.children:
                    if child.type == 'MESH':
                        objects_to_export.append(child)
        
        for obj in objects_to_export:
            obj.select_set(True)
        
        if objects_to_export and armature:
            bpy.context.view_layer.objects.active = armature
            
            bpy.ops.export_scene.fbx(
                filepath=file_path,
                use_selection=True,
                object_types={'ARMATURE', 'MESH'},
                mesh_smooth_type='FACE',
                use_mesh_modifiers=True,
                add_leaf_bones=False,
                primary_bone_axis='Y',
                secondary_bone_axis='X',
                axis_forward='-Y',
                axis_up='Z',
                armature_nodetype='NULL' if armature_as_root else 'ROOT',
            )
        
        # 恢复选择
        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selection:
            obj.select_set(True)
        if original_active:
            bpy.context.view_layer.objects.active = original_active
