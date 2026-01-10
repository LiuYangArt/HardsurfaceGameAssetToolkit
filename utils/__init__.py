# -*- coding: utf-8 -*-
"""
HardsurfaceGameAssetToolkit Utils Package
=========================================

此包包含所有工具函数，按功能域组织为独立模块。

使用方式:
    from HardsurfaceGameAssetToolkit.utils.object_utils import Object
    from HardsurfaceGameAssetToolkit.utils.collection_utils import Collection
    或
    from ..utils.object_utils import Object  # 相对导入
"""

# 此包不在 __init__ 中进行子模块导入
# 以避免与 auto_load 机制产生冲突
# 每个需要使用工具函数的模块应该直接导入所需的子模块

__all__ = [
    'ui_utils',
    'object_utils',
    'collection_utils',
    'modifier_utils',
    'vertex_color_utils',
    'bmesh_utils',
    'uv_utils',
    'material_utils',
    'transform_utils',
    'file_utils',
    'viewport_utils',
    'outliner_utils',
    'mesh_attributes_utils',
    'armature_utils',
    'import_utils',
    'export_utils',
    'mesh_utils',
    'misc_utils',
]
