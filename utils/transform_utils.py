# -*- coding: utf-8 -*-
"""
变换操作工具函数
===============

包含旋转、缩放、矩阵操作等功能。
"""

import bpy
import math
from mathutils import Vector, Matrix, Quaternion


def rotate_quaternion(quaternion, angle: float, axis: str = "Z") -> Quaternion:
    """
    旋转四元数

    Args:
        quaternion: 原始四元数
        angle: 旋转角度（度）
        axis: 旋转轴 (X, Y, Z)

    Returns:
        旋转后的四元数
    """
    angle_rad = math.radians(angle)
    
    match axis:
        case "X":
            rotation_quat = Quaternion((1, 0, 0), angle_rad)
        case "Y":
            rotation_quat = Quaternion((0, 1, 0), angle_rad)
        case "Z":
            rotation_quat = Quaternion((0, 0, 1), angle_rad)
        case _:
            rotation_quat = Quaternion((0, 0, 1), angle_rad)
    
    return quaternion @ rotation_quat


def get_selected_rotation_quat() -> Quaternion:
    """
    在编辑模式中获取选中元素的位置与旋转

    Returns:
        选中元素的旋转四元数
    """
    scene = bpy.context.scene
    orientation_slots = scene.transform_orientation_slots

    bpy.ops.transform.create_orientation(
        name="3Points", use_view=False, use=True, overwrite=True
    )
    orientation_slots[0].custom_orientation.matrix.copy()
    custom_matrix = orientation_slots[0].custom_orientation.matrix.copy()
    bpy.ops.transform.delete_orientation()

    loc, rotation, scale = custom_matrix.to_4x4().decompose()
    return rotation


class Transform:
    """变换操作工具类"""

    @staticmethod
    def rotate_quat(quaternion, angle: float, axis: str = "Z") -> Quaternion:
        """
        旋转四元数

        Args:
            quaternion: 原始四元数
            angle: 旋转角度（度）
            axis: 旋转轴 (X, Y, Z)

        Returns:
            旋转后的四元数
        """
        return rotate_quaternion(quaternion, angle, axis)

    @staticmethod
    def scale_matrix(matrix, scale_factor: float, size: int = 4) -> Matrix:
        """
        Scale a matrix by a specified factor

        Args:
            matrix: 原始矩阵
            scale_factor: 缩放因子
            size: 矩阵大小 (3 或 4)

        Returns:
            缩放后的矩阵
        """
        scale_matrix = Matrix.Scale(scale_factor, size)
        return matrix @ scale_matrix

    @staticmethod
    def rotate_matrix(matrix, angle: float, axis: str = "Z") -> Matrix:
        """
        Rotate a matrix by a specified angle around a specified axis

        Args:
            matrix: 原始矩阵
            angle: 旋转角度（度）
            axis: 旋转轴 (X, Y, Z)

        Returns:
            旋转后的矩阵
        """
        angle_rad = math.radians(angle)
        
        match axis:
            case "X":
                rotation_matrix = Matrix.Rotation(angle_rad, 4, 'X')
            case "Y":
                rotation_matrix = Matrix.Rotation(angle_rad, 4, 'Y')
            case "Z":
                rotation_matrix = Matrix.Rotation(angle_rad, 4, 'Z')
            case _:
                rotation_matrix = Matrix.Rotation(angle_rad, 4, 'Z')
        
        return matrix @ rotation_matrix

    @staticmethod
    def apply_scale(object):
        """
        应用缩放变换

        Args:
            object: 目标对象
        """
        bpy.context.view_layer.objects.active = object
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    @staticmethod
    def apply(object, location: bool = True, rotation: bool = True, scale: bool = True):
        """
        应用变换

        Args:
            object: 目标对象
            location: 是否应用位置
            rotation: 是否应用旋转
            scale: 是否应用缩放
        """
        # 保存当前选择
        original_active = bpy.context.active_object
        original_selected = bpy.context.selected_objects.copy()
        
        # 取消所有选择
        bpy.ops.object.select_all(action='DESELECT')
        
        # 选择目标对象
        object.select_set(True)
        bpy.context.view_layer.objects.active = object
        
        # 应用变换
        bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)
        
        # 恢复选择
        object.select_set(False)
        for obj in original_selected:
            obj.select_set(True)
        if original_active:
            bpy.context.view_layer.objects.active = original_active

    @staticmethod
    def ops_apply(object, location: bool = True, rotation: bool = True, scale: bool = True):
        """
        Apply transformation to object (使用 ops)

        Args:
            object: 目标对象
            location: 是否应用位置
            rotation: 是否应用旋转
            scale: 是否应用缩放
        """
        Transform.apply(object, location, rotation, scale)
