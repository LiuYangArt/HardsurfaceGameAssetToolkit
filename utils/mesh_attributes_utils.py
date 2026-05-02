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
        添加 Mesh 属性。

        Args:
            mesh: 目标 mesh 对象
            attribute_name: 属性名称
            data_type: 数据类型 (FLOAT, INT, BOOLEAN, FLOAT_VECTOR 等)
            domain: 域 (POINT, EDGE, FACE, CORNER)

        Returns:
            创建或已存在的属性
        """
        if mesh.type != "MESH":
            return None

        mesh_data = mesh.data
        if attribute_name in mesh_data.attributes:
            return mesh_data.attributes[attribute_name]

        return mesh_data.attributes.new(
            name=attribute_name,
            type=data_type,
            domain=domain,
        )

    @staticmethod
    def fill(mesh: bpy.types.Object, attribute, value: float):
        """
        填充任意 domain 的标量属性值。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            value: 要填充的值
        """
        if mesh.type != "MESH" or attribute is None:
            return

        values = [value] * len(attribute.data)
        attribute.data.foreach_set("value", values)
        mesh.data.update()

    @staticmethod
    def fill_points(mesh: bpy.types.Object, attribute, value: float):
        """
        填充所有点的属性值。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            value: 要填充的值
        """
        MeshAttributes.fill(mesh, attribute, value)

    @staticmethod
    def fill_faces(mesh: bpy.types.Object, attribute, value: float):
        """
        填充所有面的属性值。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            value: 要填充的值
        """
        MeshAttributes.fill(mesh, attribute, value)

    @staticmethod
    def fill_corners(mesh: bpy.types.Object, attribute, value: float):
        """
        填充所有 corner 的属性值。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            value: 要填充的值
        """
        MeshAttributes.fill(mesh, attribute, value)

    @staticmethod
    def write_values(mesh: bpy.types.Object, attribute, values):
        """
        按顺序写入标量属性数组。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象或属性名称
            values: 与 attribute.data 等长的标量数组
        """
        if mesh.type != "MESH" or attribute is None:
            return

        attribute_name = None
        if isinstance(attribute, str):
            attribute_name = attribute
            attribute = mesh.data.attributes.get(attribute_name)
        else:
            try:
                attribute_name = getattr(attribute, "name", None)
            except UnicodeDecodeError:
                attribute_name = None

            if attribute_name and attribute_name in mesh.data.attributes:
                attribute = mesh.data.attributes[attribute_name]

        if attribute is None:
            raise ValueError("Target attribute not found")

        data_len = len(attribute.data)
        if data_len != len(values):
            raise ValueError(
                f"Attribute value count mismatch: expected {data_len}, got {len(values)}"
            )

        attribute.data.foreach_set("value", values)
        mesh.data.update()

    @staticmethod
    def set_indices(
        mesh: bpy.types.Object,
        attribute,
        indices,
        value: float,
        default_value=None,
    ):
        """
        按索引写入标量属性值。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            indices: 需要写入的索引集合
            value: 写入值
            default_value: 若不为 None，先用该值重置整个 attribute
        """
        if mesh.type != "MESH" or attribute is None:
            return

        attribute_name = getattr(attribute, "name", None)
        if attribute_name and attribute_name in mesh.data.attributes:
            attribute = mesh.data.attributes[attribute_name]

        data_len = len(attribute.data)
        if default_value is None:
            values = [0.0] * data_len
            attribute.data.foreach_get("value", values)
        else:
            values = [default_value] * data_len

        for index in indices:
            if 0 <= index < data_len:
                values[index] = value

        attribute.data.foreach_set("value", values)
        mesh.data.update()

    @staticmethod
    def fill_face_indices(
        mesh: bpy.types.Object,
        attribute,
        face_indices,
        value: float,
        default_value: float = 0.0,
    ):
        """
        按 face 索引集合写入 FACE 域 attribute。

        Args:
            mesh: 目标 mesh 对象
            attribute: 属性对象
            face_indices: 需要写入的面索引集合
            value: 命中索引写入的值
            default_value: 其他索引写入的默认值
        """
        if mesh.type != "MESH":
            return

        if attribute is None or attribute.domain != "FACE":
            return

        poly_count = len(mesh.data.polygons)
        values = [default_value] * poly_count

        for face_index in face_indices:
            if 0 <= face_index < poly_count:
                values[face_index] = value

        attribute.data.foreach_set("value", values)
        mesh.data.update()

    @staticmethod
    def ensure_float_face_attributes(
        mesh: bpy.types.Object,
        attribute_names,
        default_value=None,
    ):
        """
        确保多个 FLOAT/FACE attributes 存在，并返回属性对象列表。

        Args:
            mesh: 目标 mesh 对象
            attribute_names: 属性名称列表
            default_value: 若不为 None，创建后使用该值重置

        Returns:
            list[bpy.types.Attribute]
        """
        if mesh.type != "MESH":
            return []

        attributes = []
        for attribute_name in attribute_names:
            attribute = MeshAttributes.add(
                mesh,
                attribute_name=attribute_name,
                data_type="FLOAT",
                domain="FACE",
            )
            if default_value is not None:
                MeshAttributes.fill_faces(mesh, attribute, default_value)
            attributes.append(attribute)
        return attributes

    @staticmethod
    def ensure_float_corner_attributes(
        mesh: bpy.types.Object,
        attribute_names,
        default_value=None,
    ):
        """
        确保多个 FLOAT/CORNER attributes 存在，并返回属性对象列表。

        Args:
            mesh: 目标 mesh 对象
            attribute_names: 属性名称列表
            default_value: 若不为 None，创建后使用该值重置

        Returns:
            list[bpy.types.Attribute]
        """
        if mesh.type != "MESH":
            return []

        attributes = []
        for attribute_name in attribute_names:
            attribute = MeshAttributes.add(
                mesh,
                attribute_name=attribute_name,
                data_type="FLOAT",
                domain="CORNER",
            )
            if default_value is not None:
                MeshAttributes.fill_corners(mesh, attribute, default_value)
            attributes.append(attribute)
        return attributes

