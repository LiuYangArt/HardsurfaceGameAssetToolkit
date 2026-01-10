# -*- coding: utf-8 -*-
"""
材质操作工具函数
===============

包含材质获取、导入、赋值等功能。
"""

import bpy


def get_materials(target_object: bpy.types.Object) -> list:
    """
    获取所选物体的材质列表

    Args:
        target_object: 目标对象

    Returns:
        材质列表
    """
    materials = []
    for slot in target_object.material_slots:
        materials.append(slot.material)
    return materials


def get_object_material(target_object, material_name: str) -> bpy.types.Material:
    """
    获取所选物体的指定材质

    Args:
        target_object: 目标对象
        material_name: 材质名称

    Returns:
        材质对象或 None
    """
    material = None
    if target_object.material_slots is not None:
        for slot in target_object.material_slots:
            if slot.material is not None and slot.material.name == material_name:
                material = slot.material
                break
    return material


def get_object_material_slots(target_object) -> list:
    """
    获取所选物体的材质槽列表

    Args:
        target_object: 目标对象

    Returns:
        材质槽列表
    """
    material_slots = []
    if target_object.material_slots is not None:
        for slot in target_object.material_slots:
            material_slots.append(slot)
    return material_slots


def get_material_color_texture(material) -> bpy.types.Image:
    """
    获取材质的颜色纹理

    Args:
        material: 材质对象

    Returns:
        纹理图像或 None
    """
    color_texture = None
    if material.node_tree is not None:
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                color_texture = node.image
                break
    return color_texture


def get_scene_material(material_name: str) -> bpy.types.Material:
    """
    获取场景中的材质

    Args:
        material_name: 材质名称

    Returns:
        材质对象或 None
    """
    material = None
    for mat in bpy.data.materials:
        if mat.name == material_name:
            material = mat
            break
    return material


def find_scene_materials(material_name: str) -> list:
    """
    按名称关键字查找场景中的材质

    Args:
        material_name: 材质名称关键字

    Returns:
        匹配的材质列表
    """
    materials = []
    for mat in bpy.data.materials:
        if material_name in mat.name:
            materials.append(mat)
    return materials


def import_material(file_path, material_name: str) -> bpy.types.Material:
    """
    从文件载入 Material

    Args:
        file_path: 文件路径
        material_name: 材质名称

    Returns:
        导入的材质对象
    """
    INNER_PATH = "Material"
    exist = False
    material_import = None
    
    for mat in bpy.data.materials:
        if material_name not in mat.name:
            exist = False
        else:
            exist = True
            material_import = mat
            break

    if exist is False:
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=material_name,
        )

    for mat in bpy.data.materials:
        if mat.name == material_name:
            material_import = mat
            break

    return material_import


class Material:
    """材质操作工具类"""

    @staticmethod
    def assign_to_mesh(mesh, target_mat) -> bpy.types.Material:
        """
        assign material to mesh

        Args:
            mesh: 目标 mesh 对象
            target_mat: 要赋值的材质

        Returns:
            赋值后的材质
        """
        if mesh.data.materials:
            mesh.data.materials[0] = target_mat
        else:
            mesh.data.materials.append(target_mat)
        return target_mat

    @staticmethod
    def create_mat(mat_name: str) -> bpy.types.Material:
        """
        add material

        Args:
            mat_name: 材质名称

        Returns:
            新创建的材质
        """
        # 检查是否已存在
        existing_mat = bpy.data.materials.get(mat_name)
        if existing_mat:
            return existing_mat
        
        # 创建新材质
        new_mat = bpy.data.materials.new(name=mat_name)
        new_mat.use_nodes = True
        return new_mat

    @staticmethod
    def remove_duplicated_mats_ops(object):
        """
        移除对象上的重复材质（如 MI_Mat.001 替换为 MI_Mat）

        Args:
            object: 目标对象
        """
        import re
        
        for slot in object.material_slots:
            if slot.material is None:
                continue
            
            mat_name = slot.material.name
            # 检查是否有 .001 等后缀
            match = re.match(r"(.+)\.\d{3}$", mat_name)
            if match:
                base_name = match.group(1)
                # 查找原始材质
                original_mat = bpy.data.materials.get(base_name)
                if original_mat:
                    slot.material = original_mat
