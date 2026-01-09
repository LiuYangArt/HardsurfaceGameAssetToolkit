# -*- coding: utf-8 -*-
"""
Outliner 操作工具函数
====================

包含 Outliner 选择、获取等功能。
"""

import bpy


class Outliner:
    """Outliner 操作工具类"""

    @staticmethod
    def get_selected_object_ids() -> list:
        """
        获取在 Outliner 中选中的对象 ID 列表

        Returns:
            对象 ID 列表
        """
        selected_ids = []
        
        # 遍历所有区域查找 Outliner
        for area in bpy.context.screen.areas:
            if area.type == 'OUTLINER':
                with bpy.context.temp_override(area=area):
                    for obj in bpy.context.selected_ids:
                        if isinstance(obj, bpy.types.Object):
                            selected_ids.append(obj)
                break
        
        return selected_ids

    @staticmethod
    def get_selected_collection_ids() -> list:
        """
        获取在 Outliner 中选中的 Collection ID 列表

        Returns:
            Collection ID 列表
        """
        selected_ids = []
        
        # 遍历所有区域查找 Outliner
        for area in bpy.context.screen.areas:
            if area.type == 'OUTLINER':
                with bpy.context.temp_override(area=area):
                    for obj in bpy.context.selected_ids:
                        if isinstance(obj, bpy.types.Collection):
                            selected_ids.append(obj)
                break
        
        return selected_ids

    @staticmethod
    def get_selected_objects() -> list:
        """
        return selected outliner objects

        Returns:
            选中的对象列表
        """
        selected_objects = []
        ids = Outliner.get_selected_object_ids()
        
        for obj_id in ids:
            if obj_id.name in bpy.data.objects:
                selected_objects.append(bpy.data.objects[obj_id.name])
        
        return selected_objects

    @staticmethod
    def get_selected_collections() -> list:
        """
        return selected outliner collections

        Returns:
            选中的 Collection 列表
        """
        selected_collections = []
        ids = Outliner.get_selected_collection_ids()
        
        for coll_id in ids:
            if coll_id.name in bpy.data.collections:
                selected_collections.append(bpy.data.collections[coll_id.name])
        
        return selected_collections
