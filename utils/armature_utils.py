# -*- coding: utf-8 -*-
"""
Armature 操作工具函数
====================

包含骨骼操作、显示设置等功能。
"""

import bpy


class Armature:
    """Armature 操作工具类"""

    @staticmethod
    def set_bone_roll(armature, roll: float = 0):
        """
        设置骨骼滚动角度

        Args:
            armature: Armature 对象
            roll: 滚动角度
        """
        if armature.type != 'ARMATURE':
            return
        
        # 进入编辑模式
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')
        
        for bone in armature.data.edit_bones:
            bone.roll = roll
        
        bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def set_display(obj):
        """
        Set display settings for an armature object

        Args:
            obj: Armature 对象
        """
        if obj.type != 'ARMATURE':
            return
        
        obj.data.display_type = 'WIRE'
        obj.show_in_front = True

    @staticmethod
    def scale_bones(armature, scale_factor: float):
        """
        Scale bones of an armature

        Args:
            armature: Armature 对象
            scale_factor: 缩放因子
        """
        if armature.type != 'ARMATURE':
            return
        
        # 进入编辑模式
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')
        
        for bone in armature.data.edit_bones:
            # 计算新的骨骼长度
            bone.head = bone.head * scale_factor
            bone.tail = bone.tail * scale_factor
        
        bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def ops_scale_bones(armature, scale: tuple = (1, 1, 1)):
        """
        Scale bones of an armature using ops

        Args:
            armature: Armature 对象
            scale: 缩放值 (x, y, z)
        """
        if armature.type != 'ARMATURE':
            return
        
        # 保存当前选择
        original_active = bpy.context.active_object
        
        # 进入编辑模式
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')
        
        # 选择所有骨骼
        bpy.ops.armature.select_all(action='SELECT')
        
        # 缩放
        bpy.ops.transform.resize(value=scale)
        
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # 恢复选择
        if original_active:
            bpy.context.view_layer.objects.active = original_active
