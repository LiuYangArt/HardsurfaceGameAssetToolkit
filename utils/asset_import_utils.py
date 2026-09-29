# -*- coding: utf-8 -*-
"""
Asset 导入数据复用
=================

Blender 5.0 移除了 Append (Reuse Data)。开启 Decal Mode 后，每次 Append 完成时，
把新带入的 Material / Node Group / Image 副本替换为文件中已有的同名本地数据，
使 Object 与 Mesh 仍为独立可编辑，而共享数据只保留一份。
"""

import bpy
from bpy.app.handlers import persistent

REUSABLE_ID_COLLECTIONS = {
    "MATERIAL": "materials",
    "NODETREE": "node_groups",
    "IMAGE": "images",
}


def find_reusable_import_pairs(import_items) -> list:
    """
    找出本次导入中可被已有本地数据替代的副本。

    Args:
        import_items: BlendImportContext.import_items，本次 Append 带入的所有 ID。

    Returns:
        (新导入副本, 文件中已有的同名本地 ID) 列表
    """
    pairs = []
    for item in import_items:
        collection_name = REUSABLE_ID_COLLECTIONS.get(item.id_type)
        imported_id = item.id
        if collection_name is None or imported_id is None:
            continue
        if item.append_action != "MAKE_LOCAL" or imported_id.library is not None:
            continue
        existing_id = getattr(bpy.data, collection_name).get((item.name, None))
        if existing_id is not None and existing_id != imported_id:
            pairs.append((imported_id, existing_id, collection_name))
    return pairs


def reuse_imported_data(import_items) -> int:
    """
    把新导入的共享数据副本重定向到已有本地数据并删除副本。

    Args:
        import_items: BlendImportContext.import_items

    Returns:
        被合并掉的副本数量
    """
    pairs = find_reusable_import_pairs(import_items)
    # 先全部重定向再删除，避免删除 Material 后其引用的 Node Group / Image 失效
    for imported_id, existing_id, _collection_name in pairs:
        imported_id.user_remap(existing_id)
    for imported_id, _existing_id, collection_name in pairs:
        getattr(bpy.data, collection_name).remove(imported_id)
    return len(pairs)


@persistent
def on_blend_import_post(import_context):
    """
    blend_import_post handler：Decal Mode 开启时复用导入数据。

    Args:
        import_context: bpy.types.BlendImportContext
    """
    scene = bpy.context.scene
    params = getattr(scene, "hst_params", None) if scene else None
    if params is None or not params.decal_reuse_imported_data:
        return
    reuse_imported_data(import_context.import_items)


def register_import_handler():
    """注册 blend_import_post handler；重复调用不会重复注册。"""
    unregister_import_handler()
    bpy.app.handlers.blend_import_post.append(on_blend_import_post)


def unregister_import_handler():
    """移除本模块注册的 blend_import_post handler（按名称匹配，兼容重载后的旧函数对象）。"""
    handlers = bpy.app.handlers.blend_import_post
    for handler in list(handlers):
        if getattr(handler, "__name__", "") == on_blend_import_post.__name__:
            handlers.remove(handler)
