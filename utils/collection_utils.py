# -*- coding: utf-8 -*-
"""
Collection 操作工具函数
=====================

包含 Collection 获取、创建、筛选等功能。
"""

import bpy
from ..Const import HST_PROP, COLLECTION_COLORS


def get_collection(target_object: bpy.types.Object) -> bpy.types.Collection:
    """
    获取所选 object 所在的 collection

    Args:
        target_object: 目标对象

    Returns:
        对象所在的 Collection，如果在 Scene Collection 则返回 None
    """
    if target_object is None:
        return None

    target_collection = None
    collection = target_object.users_collection[0]
    if collection.name != "Scene Collection":
        target_collection = collection

    return target_collection


def check_collection_exist(collection_name: str) -> bool:
    """
    检查 collection 是否存在

    Args:
        collection_name: Collection 名称

    Returns:
        是否存在
    """
    collection_exist = False

    for collection in bpy.data.collections:
        if collection.name == collection_name:
            collection_exist = True
            break
    return collection_exist


class Collection:
    """Collection 操作工具类"""

    @staticmethod
    def sort_order(collection, case_sensitive: bool = False):
        """
        对 Collection 中的子集合按字母排序

        Args:
            collection: 父 Collection
            case_sensitive: 是否区分大小写
        """
        children = list(collection.children)
        if not case_sensitive:
            children.sort(key=lambda c: c.name.lower())
        else:
            children.sort(key=lambda c: c.name)
        
        for child in children:
            collection.children.unlink(child)
        for child in children:
            collection.children.link(child)

    @staticmethod
    def get_selected():
        """
        获取选中对象所在的 Collection 列表

        Returns:
            Collection 列表
        """
        selected_objects = bpy.context.selected_objects
        collections = []
        
        if not selected_objects:
            return collections
            
        for obj in selected_objects:
            for coll in obj.users_collection:
                if coll not in collections and coll.name != "Scene Collection":
                    collections.append(coll)
        
        return collections

    @staticmethod
    def mark_hst_type(collection: bpy.types.Collection, type: str = "PROP"):
        """
        标记 Collection 类型

        可用类型：PROP, DECAL, BAKE_LOW, BAKE_HIGH, SKM, RIG, PROXY

        Args:
            collection: 目标 Collection
            type: 类型标识
        """
        collection[HST_PROP] = type

        # 根据类型设置颜色标签
        color_map = {
            "PROP": "COLOR_04",      # 绿色
            "DECAL": "COLOR_06",     # 紫色
            "BAKE_LOW": "COLOR_01",  # 红色
            "BAKE_HIGH": "COLOR_02", # 橙色
            "SKM": "COLOR_03",       # 黄色
            "RIG": "COLOR_05",       # 蓝色
            "PROXY": "COLOR_07",     # 灰色
        }
        
        if type in color_map:
            collection.color_tag = color_map[type]

    @staticmethod
    def create(name: str, type: str = "PROP") -> bpy.types.Collection:
        """
        创建 Collection

        Args:
            name: Collection 名称
            type: 类型标识 (PROP, DECAL, BAKE_LOW, BAKE_HIGH, SKM, RIG, PROXY)

        Returns:
            新创建的 Collection
        """
        new_collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(new_collection)
        Collection.mark_hst_type(new_collection, type)
        return new_collection

    @staticmethod
    def get_hst_type(collection: bpy.types.Collection):
        """
        获取 Collection 类型

        Args:
            collection: 目标 Collection

        Returns:
            类型标识
        """
        return collection.get(HST_PROP)

    @staticmethod
    def filter_hst_type(collections, type: str, mode: str = "INCLUDE"):
        """
        Filter collections by HST type

        Args:
            collections: Collection 列表
            type: 类型标识
            mode: INCLUDE 或 EXCLUDE

        Returns:
            筛选后的 Collection 列表
        """
        filtered_collections = []
        if collections is None:
            return filtered_collections

        match mode:
            case "INCLUDE":
                for coll in collections:
                    if coll.get(HST_PROP) == type:
                        filtered_collections.append(coll)
            case "EXCLUDE":
                for coll in collections:
                    if coll.get(HST_PROP) != type:
                        filtered_collections.append(coll)
        return filtered_collections

    @staticmethod
    def sort_hst_types(collections: list):
        """
        筛选 collection 类型，返回按类型分组的字典

        Args:
            collections: Collection 列表

        Returns:
            包含 bake, decal, prop, sm, skm, rig 分组的字典
        """
        sorted_collections = {
            "bake": [],
            "decal": [],
            "prop": [],
            "sm": [],
            "skm": [],
            "rig": [],
            "other": [],
        }
        
        for coll in collections:
            coll_type = coll.get(HST_PROP)
            if coll_type == "BAKE_LOW" or coll_type == "BAKE_HIGH":
                sorted_collections["bake"].append(coll)
            elif coll_type == "DECAL":
                sorted_collections["decal"].append(coll)
            elif coll_type == "PROP":
                sorted_collections["prop"].append(coll)
            elif coll_type == "SKM":
                sorted_collections["skm"].append(coll)
            elif coll_type == "RIG":
                sorted_collections["rig"].append(coll)
            else:
                sorted_collections["other"].append(coll)
        
        return sorted_collections

    @staticmethod
    def find_parent(collection):
        """
        查找 Collection 的父 Collection

        Args:
            collection: 目标 Collection

        Returns:
            父 Collection 或 None
        """
        for coll in bpy.data.collections:
            if collection.name in coll.children.keys():
                return coll
        return None

    @staticmethod
    def find_parent_recur_by_type(collection: bpy.types.Collection, type: str):
        """
        递归查找指定类型的父 Collection

        Args:
            collection: 起始 Collection
            type: 目标类型

        Returns:
            匹配类型的父 Collection 或 None
        """
        parent = Collection.find_parent(collection)
        if parent is None:
            return None
        if parent.get(HST_PROP) == type:
            return parent
        return Collection.find_parent_recur_by_type(parent, type)

    @staticmethod
    def active(collection):
        """
        激活 Collection（设置为活动 Collection）

        Args:
            collection: 目标 Collection
        """
        layer_collection = Collection.find_layer_collection(collection)
        if layer_collection:
            bpy.context.view_layer.active_layer_collection = layer_collection

    @staticmethod
    def find_layer_collection_all(collection_name: str):
        """
        递归查找 collection 对应的 layer_collection

        Args:
            collection_name: Collection 名称

        Returns:
            LayerCollection 或 None
        """
        def recurse(layer_collection):
            if layer_collection.name == collection_name:
                return layer_collection
            for child in layer_collection.children:
                found = recurse(child)
                if found:
                    return found
            return None
        
        return recurse(bpy.context.view_layer.layer_collection)

    @staticmethod
    def find_layer_collection_coll(collection):
        """
        递归查找 collection 对应的 layer_collection

        Args:
            collection: Collection 对象

        Returns:
            LayerCollection 或 None
        """
        return Collection.find_layer_collection_all(collection.name)

    @staticmethod
    def find_layer_collection(collection):
        """
        递归查找 collection 对应的 layer_collection

        Args:
            collection: Collection 对象

        Returns:
            LayerCollection 或 None
        """
        return Collection.find_layer_collection_coll(collection)

    @staticmethod
    def find_layer_collection_by_name(collection_name: str):
        """
        递归查找 collection 对应的 layer_collection

        Args:
            collection_name: Collection 名称

        Returns:
            LayerCollection 或 None
        """
        return Collection.find_layer_collection_all(collection_name)

    @staticmethod
    def layer_recur_find_parent(layer_collection, collection_name: str):
        """
        递归查找 LayerCollection 的父级

        Args:
            layer_collection: 起始 LayerCollection
            collection_name: 目标 Collection 名称

        Returns:
            父 LayerCollection 或 None
        """
        for child in layer_collection.children:
            if child.name == collection_name:
                return layer_collection
            found = Collection.layer_recur_find_parent(child, collection_name)
            if found:
                return found
        return None

    @staticmethod
    def get_by_name(collection_name: str):
        """
        检查 collection 是否存在并返回

        Args:
            collection_name: Collection 名称

        Returns:
            Collection 对象或 None
        """
        return bpy.data.collections.get(collection_name)
