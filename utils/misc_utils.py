# -*- coding: utf-8 -*-
"""
其他工具函数
===========

包含场景单位、文本处理、模式切换等杂项功能。
"""

import bpy


def set_default_scene_units():
    """
    设置默认场景单位（厘米）
    """
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.01
    scene.unit_settings.length_unit = 'CENTIMETERS'


def convert_length_by_scene_unit(length: float) -> float:
    """
    根据场景单位设置转换长度

    Args:
        length: 原始长度（毫米）

    Returns:
        转换后的长度
    """
    current_scene = bpy.context.object.users_scene[0].name
    length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
    
    match length_unit:
        case "METERS":
            new_length = length * 0.001
        case "CENTIMETERS":
            new_length = length * 0.01
        case "MILLIMETERS":
            new_length = length * 0.1
        case _:
            new_length = length * 0.01
    
    return new_length


def text_capitalize(text: str) -> str:
    """
    首字母大写，去除特殊字符

    Args:
        text: 原始文本

    Returns:
        处理后的文本
    """
    return text.replace("_", " ").title().replace(" ", "")


def clean_collection_name(collection_name: str) -> str:
    """
    清理 collection 名字

    Args:
        collection_name: 原始名称

    Returns:
        清理后的名称
    """
    # 移除常见后缀
    suffixes = ["_low", "_high", "_LOD0", "_LOD1", "_LOD2"]
    result = collection_name
    
    for suffix in suffixes:
        if result.endswith(suffix):
            result = result[:-len(suffix)]
    
    return result


def rename_alt(target_object, new_name: str, mark: str = "_", num: int = 3) -> str:
    """
    重命名物体，如果名字已存在则在后面加编号

    Args:
        target_object: 目标对象
        new_name: 新名称
        mark: 分隔符
        num: 编号位数

    Returns:
        最终的名称
    """
    # 检查是否存在同名对象
    existing_names = [obj.name for obj in bpy.data.objects]
    
    if new_name not in existing_names:
        target_object.name = new_name
        return new_name
    
    # 查找可用编号
    counter = 1
    while True:
        numbered_name = f"{new_name}{mark}{str(counter).zfill(num)}"
        if numbered_name not in existing_names:
            target_object.name = numbered_name
            return numbered_name
        counter += 1


def find_largest_digit(list1: list) -> int:
    """
    找出列表中最大的数字

    Args:
        list1: 数字列表

    Returns:
        最大值
    """
    if not list1:
        return 0
    return max(list1)


def reset_transform(target_object: bpy.types.Object):
    """
    重置物体的位置，旋转，缩放

    Args:
        target_object: 目标对象
    """
    target_object.location = (0, 0, 0)
    target_object.rotation_euler = (0, 0, 0)
    target_object.scale = (1, 1, 1)


def prep_select_mode():
    """
    存储当前模式，并切换到 OBJECT 模式

    Returns:
        存储的模式信息
    """
    store_mode = {
        "mode": bpy.context.active_object.mode if bpy.context.active_object else "OBJECT",
        "selected_objects": bpy.context.selected_objects.copy(),
        "active_object": bpy.context.active_object,
    }
    
    if bpy.context.active_object and bpy.context.active_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    
    return store_mode


def restore_select_mode(store_mode: dict):
    """
    恢复之前的模式

    Args:
        store_mode: prep_select_mode 返回的模式信息
    """
    if not store_mode:
        return
    
    # 恢复选择
    bpy.ops.object.select_all(action='DESELECT')
    for obj in store_mode.get("selected_objects", []):
        if obj.name in bpy.data.objects:
            obj.select_set(True)
    
    # 恢复激活对象
    active = store_mode.get("active_object")
    if active and active.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = active
    
    # 恢复模式
    mode = store_mode.get("mode", "OBJECT")
    if bpy.context.active_object and mode != "OBJECT":
        bpy.ops.object.mode_set(mode=mode)


def set_collision_object(target_object, new_name: str):
    """
    设置碰撞物体

    Args:
        target_object: 目标对象
        new_name: 新名称
    """
    from .object_utils import Object
    
    target_object.name = new_name
    target_object.display_type = 'WIRE'
    target_object.hide_render = True
    Object.mark_hst_type(target_object, "UCX")


def name_remove_digits(name: str, parts: int = 3, mark: str = "_") -> str:
    """
    去除名称后的数字后缀

    Args:
        name: 原始名称
        mark: 分隔符
        parts: 保留的部分数量

    Returns:
        处理后的名称
    """
    split_parts = name.split(mark)
    
    # 检查最后一部分是否是数字
    if split_parts and split_parts[-1].isdigit():
        return mark.join(split_parts[:-1])
    
    return name


def rename_prop_meshes(objects):
    """
    重命名 prop mesh

    Args:
        objects: 对象列表
    """
    from .collection_utils import get_collection
    
    for obj in objects:
        if obj.type != 'MESH':
            continue
        
        collection = get_collection(obj)
        if collection:
            # 使用 collection 名称作为基础名称
            base_name = collection.name
            rename_alt(obj, base_name)


def check_vertex_color(mesh) -> bool:
    """
    检查是否存在顶点色

    Args:
        mesh: 目标 mesh 对象

    Returns:
        顶点色层或 False
    """
    if mesh.type != 'MESH':
        return False
    
    if mesh.data.color_attributes:
        return mesh.data.color_attributes[0]
    
    return False


def filter_collection_by_visibility(type: str = "VISIBLE", filter_instance: bool = False):
    """
    筛选可见或不可见的 collection

    Args:
        type: VISIBLE 或 HIDDEN
        filter_instance: 是否过滤实例化的 collection

    Returns:
        符合条件的 Collection 列表
    """
    from .collection_utils import Collection
    
    visible_collections = []
    hidden_collections = []
    
    def check_visibility(layer_collection):
        """递归检查 layer_collection 的可见性"""
        if not layer_collection.exclude and not layer_collection.hide_viewport:
            if layer_collection.collection.name != "Scene Collection":
                visible_collections.append(layer_collection.collection)
        else:
            if layer_collection.collection.name != "Scene Collection":
                hidden_collections.append(layer_collection.collection)
        
        for child in layer_collection.children:
            check_visibility(child)
    
    # 从根 layer_collection 开始遍历
    check_visibility(bpy.context.view_layer.layer_collection)
    
    # 过滤实例化的 collection
    if filter_instance:
        # 获取所有被实例化的 collection
        instanced_collections = set()
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and obj.instance_collection:
                instanced_collections.add(obj.instance_collection)
        
        visible_collections = [c for c in visible_collections if c not in instanced_collections]
        hidden_collections = [c for c in hidden_collections if c not in instanced_collections]
    
    match type:
        case "VISIBLE":
            return visible_collections
        case "HIDDEN":
            return hidden_collections
        case _:
            return visible_collections
