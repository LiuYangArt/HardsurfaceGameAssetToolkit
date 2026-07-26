# -*- coding: utf-8 -*-
"""恢复 Feature Chamfer 新面法线，并沿用 source Custom Normal Transfer。"""

import bpy

from .experimental_pipe_chamfer_utils import CHAMFER_FACE_ATTRIBUTE
from .experimental_pipe_chamfer_utils import _add_source_normal_transfer


# 先把 Bridge/Fill 新面的 Custom Normal 设为 Face Normal，再沿用旧工具的 source 法线传递。
# output/source_object: 正式 Finalize 输出与原始 source Mesh；返回新面与传递器摘要。
def restore_feature_chamfer_normals(output, source_object):
    chamfer_attribute = output.data.attributes.get(CHAMFER_FACE_ATTRIBUTE)
    if chamfer_attribute is None:
        raise RuntimeError("Feature Chamfer output is missing Chamfer Face provenance")
    selected_face_count = sum(bool(item.value) for item in chamfer_attribute.data)
    if selected_face_count <= 0:
        raise RuntimeError("Feature Chamfer output has no Bridge/Fill Faces")
    chamfer_face_indices = {
        index
        for index, item in enumerate(chamfer_attribute.data)
        if bool(item.value)
    }

    active_object_before = bpy.context.view_layer.objects.active
    selected_objects_before = tuple(bpy.context.selected_objects)
    mode_before = bpy.context.mode
    try:
        if mode_before != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected_object in tuple(bpy.context.selected_objects):
            selected_object.select_set(False)
        output.hide_set(False)
        output.select_set(True)
        bpy.context.view_layer.objects.active = output
        for polygon in output.data.polygons:
            polygon.select = polygon.index in chamfer_face_indices
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.set_normals_from_faces()
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected_object in tuple(bpy.context.selected_objects):
            selected_object.select_set(False)
        for selected_object in selected_objects_before:
            if bpy.data.objects.get(selected_object.name) == selected_object:
                selected_object.select_set(True)
        if (
            active_object_before is not None
            and bpy.data.objects.get(active_object_before.name) == active_object_before
        ):
            bpy.context.view_layer.objects.active = active_object_before

    normal_transfer = _add_source_normal_transfer(output, source_object)
    normal_transfer.vertex_group = ""
    normal_transfer.invert_vertex_group = False
    normal_transfer.show_viewport = True
    normal_transfer.show_render = True
    return {
        "face_normals_restored": selected_face_count,
        "source_normal_transfer": normal_transfer.name,
    }
