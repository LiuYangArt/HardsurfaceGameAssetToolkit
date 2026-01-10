# -*- coding: utf-8 -*-
"""
顶点色操作工具函数
=================

包含顶点色属性的添加、设置、获取等功能。
"""

import bpy
import bmesh


def cleanup_color_attributes(target_object: bpy.types.Object) -> bool:
    """
    为选中的物体删除所有顶点色属性

    Args:
        target_object: 目标对象

    Returns:
        是否成功
    """
    success = False

    if target_object.data.color_attributes is not None:
        color_attributes = target_object.data.color_attributes
        for r in range(len(color_attributes) - 1, -1, -1):
            color_attributes.remove(color_attributes[r])
        success = True
    return success


def add_vertexcolor_attribute(
    target_object: bpy.types.Object, vertexcolor_name: str
) -> bpy.types.Object:
    """
    为选中的物体添加顶点色属性

    注意：Blender 5.0+ 要求 mesh 必须有顶点才能创建 color attribute

    Args:
        target_object: 目标对象
        vertexcolor_name: 顶点色属性名称

    Returns:
        顶点色属性对象
    """
    color_attribute = None
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
    else:
        print(target_object.name + " is not mesh object")
    return color_attribute


def set_active_color_attribute(target_object, vertexcolor_name: str) -> None:
    """
    设置顶点色属性为激活状态

    Args:
        target_object: 目标对象
        vertexcolor_name: 顶点色属性名称

    Returns:
        顶点色属性对象
    """
    color_attribute = None
    if target_object.type == "MESH":
        if vertexcolor_name in target_object.data.color_attributes:
            color_attribute = target_object.data.color_attributes.get(vertexcolor_name)
            target_object.data.attributes.active_color = color_attribute
    return color_attribute


def get_vertex_color_from_obj(obj) -> list:
    """
    获取对象的平均顶点色

    Args:
        obj: 目标对象

    Returns:
        平均颜色值列表 [R, G, B, A]
    """
    if obj.type == 'MESH':
        color_attr = None
        for attr in obj.data.color_attributes:
            print(attr.name, attr)
            if attr.domain in {'POINT', 'CORNER'}:
                color_attr = obj.data.attributes[attr.name]
            break
        if color_attr:
            color_data = color_attr.data
            color_list = []
            for i in color_data:
                if hasattr(i, "color_srgb"):
                    color_list.append(i.color_srgb)
                elif hasattr(i, "color"):
                    color_list.append(i.color)
                elif hasattr(i, "vertex_colors"):
                    color_list.append(i.color)
                else:
                    color_list.append(None)
            if color_list:
                color = [
                    sum(c[i] for c in color_list) / len(color_list)
                    for i in range(len(color_list[0]))
                ]
                return color
        else:
            return None


def vertexcolor_to_vertices(target_mesh, color_attribute, color):
    """
    在编辑模式下将颜色应用到选中的顶点

    Args:
        target_mesh: 目标 mesh 对象
        color_attribute: 顶点色属性
        color: 颜色值 (R, G, B, A)
    """
    mesh = target_mesh.data
    bm = bmesh.from_edit_mesh(mesh)

    if color_attribute.domain == "POINT":
        point_color_attribute = color_attribute
        point_color_layer = bm.verts.layers.color[point_color_attribute.name]
        for vert in bm.verts:
            if vert.select:
                vert[point_color_layer] = color

    elif color_attribute.domain == "CORNER":
        corner_color_attribute = color_attribute
        corner_color_layer = bm.loops.layers.color[corner_color_attribute.name]

        for face in bm.faces:
            if face.select:
                for loop in face.loops:
                    loop[corner_color_layer] = color

    bmesh.update_edit_mesh(mesh)


def set_object_vertexcolor(target_object, color: tuple, vertexcolor_name: str) -> None:
    """
    设置顶点色

    Args:
        target_object: 目标对象
        color: 颜色值 (R, G, B, A)
        vertexcolor_name: 顶点色属性名称
    """
    color = tuple(color)
    current_mode = bpy.context.active_object.mode
    if target_object.type == "MESH":
        mesh = target_object.data
        if vertexcolor_name in mesh.color_attributes:
            color_attribute = mesh.color_attributes.get(vertexcolor_name)
            if current_mode == "OBJECT":
                color_attribute.data.foreach_set(
                    "color_srgb", color * len(mesh.loops) * 4
                )
            elif current_mode == "EDIT":
                vertexcolor_to_vertices(target_object, color_attribute, color)


def get_color_data(color):
    """
    转换颜色数据格式

    Args:
        color: 颜色值

    Returns:
        转换后的颜色列表 [R, G, B, A]
    """
    convert_color = [color[0], color[1], color[2], color[3]]
    return convert_color


class VertexColor:
    """顶点色操作工具类"""

    @staticmethod
    def add(
        target_object: bpy.types.Object, 
        vertexcolor_name: str,
        type: str = "BYTE_COLOR",
        domain: str = "CORNER"
    ):
        """
        为选中的物体添加顶点色属性

        注意：Blender 5.0+ 要求 mesh 必须有顶点才能创建 color attribute

        Args:
            target_object: 目标对象
            vertexcolor_name: 顶点色属性名称
            type: 颜色类型 (BYTE_COLOR, FLOAT_COLOR)
            domain: 域 (CORNER, POINT)

        Returns:
            顶点色属性对象
        """
        color_attribute = None
        if target_object.type == "MESH":
            mesh = target_object.data
            if len(mesh.vertices) == 0:
                print(f"{target_object.name} has no vertices, cannot add color attribute")
                return None
            if vertexcolor_name in mesh.color_attributes:
                color_attribute = mesh.color_attributes.get(vertexcolor_name)
            else:
                color_attribute = mesh.color_attributes.new(
                    name=vertexcolor_name,
                    type=type,
                    domain=domain,
                )
        return color_attribute

    @staticmethod
    def add_curvature(mesh):
        """
        为选中的 mesh 添加 curvature vertex color 层

        注意：Blender 5.0+ 要求 mesh 必须有顶点才能创建 color attribute

        Args:
            mesh: 目标 mesh 对象
        """
        if mesh.type != "MESH":
            return None
        
        if len(mesh.data.vertices) == 0:
            print(f"{mesh.name} has no vertices, cannot add curvature")
            return None
            
        # 添加曲率顶点色
        color_attr = VertexColor.add(mesh, "Curvature", "FLOAT_COLOR", "POINT")
        return color_attr

    @staticmethod
    def set_alpha(mesh, alpha_value: float, vertexcolor_name: str):
        """
        设置顶点色的 Alpha 通道

        Args:
            mesh: 目标 mesh 对象
            alpha_value: Alpha 值 (0.0 - 1.0)
            vertexcolor_name: 顶点色属性名称
        """
        if mesh.type != "MESH":
            return
            
        mesh_data = mesh.data
        if vertexcolor_name not in mesh_data.color_attributes:
            return
            
        color_attr = mesh_data.color_attributes.get(vertexcolor_name)
        if color_attr is None:
            return
            
        for i in range(len(color_attr.data)):
            color = list(color_attr.data[i].color)
            color[3] = alpha_value
            color_attr.data[i].color = tuple(color)
