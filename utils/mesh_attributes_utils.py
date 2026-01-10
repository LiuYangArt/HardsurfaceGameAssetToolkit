# -*- coding: utf-8 -*-
"""
Mesh 属性操作工具函数
===================

包含 Mesh 属性添加、填充等功能。
"""

import bpy


class MeshAttributes:
    """Mesh 属性操作工具类"""

    @staticmethod
    def add(mesh: bpy.types.Object, attribute_name: str, data_type: str, domain: str):
        """
        添加 Mesh 属性

        Args:
            mesh: 目标 mesh 对象
            attribute_name: 属性名称
            data_type: 数据类型 (FLOAT, INT, BOOLEAN, FLOAT_VECTOR 等)
            domain: 域 (POINT, EDGE, FACE, CORNER)

        Returns:
            创建的属性
        """
        if mesh.type != "MESH":
            return None
        
        mesh_data = mesh.data
        
        # 检查属性是否已存在
        if attribute_name in mesh_data.attributes:
            return mesh_data.attributes[attribute_name]
        
        # 创建新属性
        attribute = mesh_data.attributes.new(
            name=attribute_name,
            type=data_type,
            domain=domain
        )
        
        return attribute

    @staticmethod
    def fill_points(mesh: bpy.types.Object, attribute, value: float):
        """
        填充所有点的属性值

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            value: 要填充的值
        """
        if mesh.type != "MESH":
            return
        
        if attribute is None:
            return
        
        # 使用 foreach_set 高效填充
        values = [value] * len(attribute.data)
        attribute.data.foreach_set("value", values)
        mesh.data.update()
