# -*- coding: utf-8 -*-
"""
材质操作工具函数
===============

包含材质获取、导入、赋值等功能。
"""

import re

import bpy

DUPLICATE_SUFFIX_PATTERN = re.compile(r"^(.+)\.(\d{3,})$")


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


def get_duplicate_base_name(material: bpy.types.Material):
    """
    获取重复材质的原始名称，例如 MI_Mat.010 -> MI_Mat。

    Args:
        material: 目标材质

    Returns:
        原始名称；非本地材质或名称无 .NNN 后缀时返回 None
    """
    if material is None or material.library is not None:
        return None
    match = DUPLICATE_SUFFIX_PATTERN.match(material.name)
    return match.group(1) if match else None


def resolve_original_material(material: bpy.types.Material) -> bpy.types.Material:
    """
    找到重复材质应合并到的原始材质；原始名称尚未被占用时，把该材质本身改回原始名称。

    Args:
        material: 带 .NNN 后缀的本地材质

    Returns:
        原始材质（可能就是传入材质改名后的结果）
    """
    base_name = get_duplicate_base_name(material)
    original_material = bpy.data.materials.get(base_name)
    if original_material is None:
        material.name = base_name
        return material
    return original_material


def fix_duplicated_materials(mesh_objects=None) -> int:
    """
    把 MI_Mat.001 这类重复材质合并回 MI_Mat。

    Args:
        mesh_objects: 只处理这些 Mesh 物体的材质槽（副本无人使用时才删除）；
            为 None 时处理整个文件：重定向所有使用者并删除重复材质。

    Returns:
        被合并（或改回原名）的重复材质数量
    """
    fixed_materials = set()
    if mesh_objects is not None:
        for mesh_object in mesh_objects:
            for slot in mesh_object.material_slots:
                material = slot.material
                if get_duplicate_base_name(material) is None:
                    continue
                fixed_materials.add(material.as_pointer())
                original_material = resolve_original_material(material)
                if original_material is not material:
                    slot.material = original_material
                    if material.users == 0:  # 已无人使用的副本直接清掉，避免残留 .001
                        bpy.data.materials.remove(material)
        return len(fixed_materials)

    duplicate_materials = [
        material
        for material in bpy.data.materials
        if get_duplicate_base_name(material) is not None
    ]
    # 按后缀数字升序，使最小后缀优先成为原始材质
    duplicate_materials.sort(
        key=lambda material: (
            get_duplicate_base_name(material),
            int(DUPLICATE_SUFFIX_PATTERN.match(material.name).group(2)),
        )
    )
    for material in duplicate_materials:
        original_material = resolve_original_material(material)
        if original_material is not material:
            material.user_remap(original_material)
            bpy.data.materials.remove(material)
    return len(duplicate_materials)


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

