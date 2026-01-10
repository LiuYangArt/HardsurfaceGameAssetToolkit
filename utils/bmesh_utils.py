# -*- coding: utf-8 -*-
"""
BMesh 工具函数
==============

包含 BMesh 初始化、结束等基础操作。
"""

import bpy
import bmesh


class BMesh:
    """BMesh 操作工具类"""

    @staticmethod
    def init(mesh, mode: str = "CONTEXT"):
        """
        初始化 bmesh

        Args:
            mesh: 目标 mesh 对象
            mode: 模式 (CONTEXT 使用编辑模式, OBJECT 使用对象模式)

        Returns:
            初始化后的 bmesh 对象
        """
        if mode == "CONTEXT":
            # 编辑模式：从编辑 mesh 获取
            bm = bmesh.from_edit_mesh(mesh.data)
        else:
            # 对象模式：创建新的 bmesh
            bm = bmesh.new()
            bm.from_mesh(mesh.data)
        
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        return bm

    @staticmethod
    def finished(bm, mesh, mode: str = "CONTEXT"):
        """
        结束 bmesh 操作，将更改写回 mesh

        Args:
            bm: bmesh 对象
            mesh: 目标 mesh 对象
            mode: 模式 (CONTEXT 使用编辑模式, OBJECT 使用对象模式)
        """
        if mode == "CONTEXT":
            # 编辑模式：更新编辑 mesh
            bmesh.update_edit_mesh(mesh.data)
        else:
            # 对象模式：写入 mesh 数据并释放
            bm.to_mesh(mesh.data)
            bm.free()
        
        mesh.data.update()
