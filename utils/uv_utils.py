# -*- coding: utf-8 -*-
"""
UV 操作工具函数
==============

包含 UV 层管理、展开、缩放等功能。
"""

import bpy
from mathutils import Vector


def rename_uv_layers(
    target_object: bpy.types.Object, new_name: str, uv_index: int = 0
) -> bpy.types.Object:
    """
    重命名 uv 层

    Args:
        target_object: 目标对象
        new_name: 新名称
        uv_index: UV 层索引

    Returns:
        UV 层对象
    """
    uv_layer = None
    for index, uv in enumerate(target_object.data.uv_layers):
        if index == uv_index:
            uv.name = new_name
            uv_layer = uv
            break
        else:
            print(target_object.name + " has no uv layer for index: " + str(uv_index))
    return uv_layer


def add_uv_layers(target_object: bpy.types.Object, uv_name: str) -> bpy.types.Object:
    """
    新建 uv 层

    Args:
        target_object: 目标对象
        uv_name: UV 层名称

    Returns:
        UV 层对象
    """
    uv_layer = target_object.data.uv_layers.get(
        uv_name
    ) or target_object.data.uv_layers.new(name=uv_name)
    return uv_layer


def check_uv_layer(mesh, uv_name: str) -> bpy.types.Object:
    """
    检查是否存在 uv_layer

    Args:
        mesh: 目标 mesh 对象
        uv_name: UV 层名称

    Returns:
        UV 层对象或 None
    """
    uv_layer = None
    uv_layer = mesh.data.uv_layers.get(uv_name)
    return uv_layer


def has_uv_attribute(mesh) -> bool:
    """
    检查是否存在 uv 属性

    Args:
        mesh: 目标 mesh 对象

    Returns:
        是否存在
    """
    has_uv = False
    for attributes in mesh.data.attributes:
        if attributes.domain == "CORNER" and attributes.data_type == "FLOAT2":
            has_uv = True
            break
    return has_uv


def scale_uv(mesh, uv_layer, scale=(1, 1), pivot=(0.5, 0.5)) -> None:
    """
    缩放 UV

    Args:
        mesh: 目标 mesh 对象
        uv_layer: UV 层
        scale: 缩放比例 (x, y)
        pivot: 缩放中心点 (x, y)
    """
    pivot = Vector(pivot)
    scale = Vector(scale)

    with bpy.context.temp_override(active_object=mesh):
        for uv_index in range(len(uv_layer.data)):
            v = uv_layer.data[uv_index].uv
            s = scale
            p = pivot
            x = p[0] + s[0] * (v[0] - p[0])
            y = p[1] + s[1] * (v[1] - p[1])
            uv_layer.data[uv_index].uv = x, y


def uv_editor_fit_view(area):
    """
    缩放 uv 视图填充窗口

    Args:
        area: UV 编辑器区域
    """
    if area.type == "IMAGE_EDITOR":
        for region in area.regions:
            if region.type == "WINDOW":
                with bpy.context.temp_override(area=area, region=region):
                    bpy.ops.image.view_all(fit_view=True)


def uv_unwrap(target_objects, method: str = "ANGLE_BASED", margin: float = 0.005, correct_aspect: bool = True):
    """
    UV 展开

    Args:
        target_objects: 目标对象列表
        method: 展开方法 (ANGLE_BASED, CONFORMAL)
        margin: 岛间距
        correct_aspect: 是否校正宽高比
    """
    # 保存当前选择
    original_selection = bpy.context.selected_objects.copy()
    original_active = bpy.context.active_object
    
    # 取消所有选择
    bpy.ops.object.select_all(action='DESELECT')
    
    for obj in target_objects:
        if obj.type == 'MESH':
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            
            # 进入编辑模式
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            
            # 执行 UV 展开
            bpy.ops.uv.unwrap(method=method, margin=margin, correct_aspect=correct_aspect)
            
            # 返回对象模式
            bpy.ops.object.mode_set(mode='OBJECT')
            obj.select_set(False)
    
    # 恢复原始选择
    for obj in original_selection:
        obj.select_set(True)
    if original_active:
        bpy.context.view_layer.objects.active = original_active


def uv_average_scale(target_objects, uv_layer_name: str = "UVMap"):
    """
    UV 平均缩放

    Args:
        target_objects: 目标对象列表
        uv_layer_name: UV 层名称
    """
    original_active = bpy.context.active_object
    
    for obj in target_objects:
        if obj.type == 'MESH':
            bpy.context.view_layer.objects.active = obj
            
            # 确保有指定的 UV 层
            if uv_layer_name not in obj.data.uv_layers:
                continue
                
            obj.data.uv_layers[uv_layer_name].active = True
            
            # 进入编辑模式
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            
            # 执行平均缩放
            bpy.ops.uv.average_islands_scale()
            
            # 返回对象模式
            bpy.ops.object.mode_set(mode='OBJECT')
    
    if original_active:
        bpy.context.view_layer.objects.active = original_active


def culculate_td_areas(mesh, texture_size_x: int, texture_size_y: int):
    """
    计算 TD 每个面的大小，输出列表

    Args:
        mesh: 目标 mesh 对象
        texture_size_x: 贴图宽度
        texture_size_y: 贴图高度

    Returns:
        TD 面积列表
    """
    import bmesh
    
    td_areas = []
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        bm.free()
        return td_areas
    
    for face in bm.faces:
        # 计算 3D 面积
        face_area_3d = face.calc_area()
        
        # 计算 UV 面积
        uvs = [loop[uv_layer].uv for loop in face.loops]
        uv_area = 0.0
        for i in range(len(uvs)):
            j = (i + 1) % len(uvs)
            uv_area += uvs[i].x * uvs[j].y
            uv_area -= uvs[j].x * uvs[i].y
        uv_area = abs(uv_area) / 2.0
        
        # 转换为像素面积
        uv_area_pixels = uv_area * texture_size_x * texture_size_y
        
        if face_area_3d > 0:
            td = (uv_area_pixels / face_area_3d) ** 0.5
            td_areas.append(td)
    
    bm.free()
    return td_areas


def get_texel_density(target_object, texture_size_x: int = 1024, texture_size_y: int = 1024):
    """
    获取 UV 的 Texel Density

    Args:
        target_object: 目标对象
        texture_size_x: 贴图宽度
        texture_size_y: 贴图高度

    Returns:
        平均 Texel Density
    """
    if target_object.type != 'MESH':
        return None
    
    td_areas = culculate_td_areas(target_object, texture_size_x, texture_size_y)
    
    if not td_areas:
        return None
    
    return sum(td_areas) / len(td_areas)


class UV:
    """UV 操作工具类"""

    @staticmethod
    def show_uv_in_object_mode():
        """
        显示 UV 编辑器（在对象模式下）
        """
        # 检查是否已有 UV 编辑器
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                return area
        
        # 如果没有，分割当前区域创建一个
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                with bpy.context.temp_override(area=area):
                    bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
                
                # 设置新区域为 UV 编辑器
                new_area = bpy.context.screen.areas[-1]
                new_area.type = 'IMAGE_EDITOR'
                return new_area
        
        return None
