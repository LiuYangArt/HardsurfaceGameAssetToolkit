# -*- coding: utf-8 -*-
"""
Swatch UV 工具函数
=================

Swatch 贴图格子与 UV 坐标换算、Swatch UV 读取/写入/恢复，以及 Swatch 材质环境准备。

贴图布局：4×4 大格，每个大格横向 8 小格（颜色）、竖向 6 小格（粗糙度，越往下越粗糙）。
上三行大格为 Warm / Blue / Gray 三个色系，第 1、2 列为 Plastic，第 3、4 列为 Paint
（第 1 列对应第 3 列，第 2 列对应第 4 列）；最下一行为 4 种 Metal。
"""

import math

import bpy
import bmesh

from ..const import Const, PRESET_FILE_PATH, SWATCH_MATERIAL, UV_SWATCH
from .material_utils import (
    get_object_material,
    get_object_material_slots,
    get_scene_material,
    import_material,
)
from .ui_utils import switch_to_eevee
from .uv_utils import UV, add_uv_layers, check_uv_layer, uv_editor_fit_view
from .viewport_utils import check_screen_area, new_screen_area, viewport_shading_mode


SWATCH_BIG_COLUMNS = 4
SWATCH_BIG_ROWS = 4
SWATCH_COLOR_STEPS = 8
SWATCH_ROUGHNESS_STEPS = 6

SWATCH_MATERIAL_TYPES = (
    ("PLASTIC", "Plastic", "Plastic, left two columns of the upper three rows"),
    ("PAINT", "Paint", "Paint over metal, right two columns of the upper three rows"),
    ("METAL", "Metal", "Metal, bottom row"),
)
SWATCH_COLOR_GROUPS = (
    ("WARM_A", "Warm A", ""),
    ("WARM_B", "Warm B", ""),
    ("BLUE_A", "Blue A", ""),
    ("BLUE_B", "Blue B", ""),
    ("GRAY_A", "Gray A", ""),
    ("GRAY_B", "Gray B", ""),
)
SWATCH_METAL_GROUPS = (
    ("COOL_SATURATED", "Cool Saturated", ""),
    ("WARM_SATURATED", "Warm Saturated", ""),
    ("COOL_MUTED", "Cool Muted", ""),
    ("WARM_MUTED", "Warm Muted", ""),
)

DEFAULT_SWATCH_CELL = {
    "material_type": "PLASTIC",
    "color_group": "GRAY_A",
    "metal_group": "COOL_SATURATED",
    "color": 1,
    "roughness": 1,
}

SWATCH_TEXTURE_GROUP_LABEL = "BaseMat_Swatch"


def _enum_index(items, identifier: str) -> int:
    """
    返回 enum items 中 identifier 的序号

    Args:
        items: (identifier, name, description) 元组序列
        identifier: 要查找的 identifier
    """
    for index, item in enumerate(items):
        if item[0] == identifier:
            return index
    raise ValueError(f"Unknown swatch identifier: {identifier}")


def _enum_name(items, identifier: str) -> str:
    """
    返回 enum items 中 identifier 对应的显示名

    Args:
        items: (identifier, name, description) 元组序列
        identifier: 要查找的 identifier
    """
    return items[_enum_index(items, identifier)][1]


def swatch_cell_to_uv(cell: dict) -> tuple:
    """
    把 Swatch 格子换算为该小格中心的 UV 坐标

    Args:
        cell: 包含 material_type、color_group、metal_group、color(1-8)、roughness(1-6) 的 dict
    Returns:
        (u, v) 小格中心坐标，v=1 为贴图顶部
    """
    material_type = cell["material_type"]
    if material_type == "METAL":
        big_row = SWATCH_BIG_ROWS - 1
        big_column = _enum_index(SWATCH_METAL_GROUPS, cell["metal_group"])
    else:
        group_index = _enum_index(SWATCH_COLOR_GROUPS, cell["color_group"])
        big_row = group_index // 2
        big_column = group_index % 2 + (2 if material_type == "PAINT" else 0)

    column = big_column * SWATCH_COLOR_STEPS + (cell["color"] - 1)
    row_from_top = big_row * SWATCH_ROUGHNESS_STEPS + (cell["roughness"] - 1)
    u = (column + 0.5) / (SWATCH_BIG_COLUMNS * SWATCH_COLOR_STEPS)
    v = 1.0 - (row_from_top + 0.5) / (SWATCH_BIG_ROWS * SWATCH_ROUGHNESS_STEPS)
    return (u, v)


def swatch_uv_to_cell(u: float, v: float):
    """
    把 UV 坐标换算为所在的 Swatch 格子

    Args:
        u: UV 横坐标
        v: UV 纵坐标，v=1 为贴图顶部
    Returns:
        格子 dict（未用到的 color_group / metal_group 取默认值）；坐标在贴图外时返回 None
    """
    if not (0.0 <= u < 1.0 and 0.0 < v <= 1.0):
        return None
    column = math.floor(u * SWATCH_BIG_COLUMNS * SWATCH_COLOR_STEPS)
    row_from_top = math.floor((1.0 - v) * SWATCH_BIG_ROWS * SWATCH_ROUGHNESS_STEPS)
    big_column, color_index = divmod(column, SWATCH_COLOR_STEPS)
    big_row, roughness_index = divmod(row_from_top, SWATCH_ROUGHNESS_STEPS)

    cell = dict(DEFAULT_SWATCH_CELL)
    cell["color"] = color_index + 1
    cell["roughness"] = roughness_index + 1
    if big_row == SWATCH_BIG_ROWS - 1:
        cell["material_type"] = "METAL"
        cell["metal_group"] = SWATCH_METAL_GROUPS[big_column][0]
    else:
        cell["material_type"] = "PLASTIC" if big_column < 2 else "PAINT"
        cell["color_group"] = SWATCH_COLOR_GROUPS[big_row * 2 + big_column % 2][0]
    return cell


def swatch_cell_label(cell) -> str:
    """
    生成格子的英文说明文字，例如 "Paint · Blue A · Color 5 · Roughness 3"

    Args:
        cell: 格子 dict；None 表示无法确定（分布在多个格子或无选中面）
    """
    if cell is None:
        return "Mixed"
    material_name = _enum_name(SWATCH_MATERIAL_TYPES, cell["material_type"])
    if cell["material_type"] == "METAL":
        group_name = _enum_name(SWATCH_METAL_GROUPS, cell["metal_group"])
    else:
        group_name = _enum_name(SWATCH_COLOR_GROUPS, cell["color_group"])
    return f"{material_name} · {group_name} · Color {cell['color']} · Roughness {cell['roughness']}"


def _edit_swatch_loops(target_object, selected_only: bool):
    """
    返回 Edit Mode 下目标物体的 bmesh、Swatch UV layer 与需要处理的 loops

    Args:
        target_object: 处于 Edit Mode 的 Mesh 物体
        selected_only: True 时只返回选中面的 loops
    """
    bm = bmesh.from_edit_mesh(target_object.data)
    uv_layer = bm.loops.layers.uv.get(UV_SWATCH)
    loops = []
    if uv_layer is not None:
        for face in bm.faces:
            if selected_only and not face.select:
                continue
            loops.extend(face.loops)
    return bm, uv_layer, loops


def read_swatch_cell(target_object):
    """
    读取物体当前 Swatch UV 所在的格子（Edit Mode 下只读选中面）

    Args:
        target_object: Mesh 物体
    Returns:
        格子 dict；UV 分布在多个格子、在贴图外、无 Swatch UV 或无选中面时返回 None
    """
    if target_object.mode == "EDIT":
        _bm, uv_layer, loops = _edit_swatch_loops(target_object, selected_only=True)
        if uv_layer is None:
            return None
        coordinates = [tuple(loop[uv_layer].uv) for loop in loops]
    else:
        uv_layer = check_uv_layer(target_object, UV_SWATCH)
        if uv_layer is None:
            return None
        coordinates = [tuple(loop_uv.uv) for loop_uv in uv_layer.data]

    cells = {}
    for u, v in coordinates:
        cell = swatch_uv_to_cell(u, v)
        if cell is None:
            return None
        cells[tuple(sorted(cell.items()))] = cell
        if len(cells) > 1:
            return None
    return next(iter(cells.values()), None)


def apply_swatch_uv(target_object, uv: tuple) -> None:
    """
    把物体的 Swatch UV 缩成一点并放到指定坐标（Edit Mode 下只改选中面）

    Args:
        target_object: 已有 Swatch UV 的 Mesh 物体
        uv: 目标 (u, v) 坐标
    """
    if target_object.mode == "EDIT":
        bm, uv_layer, loops = _edit_swatch_loops(target_object, selected_only=True)
        if uv_layer is None:
            return
        for loop in loops:
            loop[uv_layer].uv = uv
        bmesh.update_edit_mesh(target_object.data, loop_triangles=False, destructive=False)
        return

    uv_layer = check_uv_layer(target_object, UV_SWATCH)
    if uv_layer is None:
        return
    uv_layer.data.foreach_set("uv", list(uv) * len(uv_layer.data))
    target_object.data.update()


def snapshot_swatch_uv(target_object) -> list:
    """
    记录物体全部 Swatch UV 坐标，用于取消时恢复

    Args:
        target_object: Mesh 物体
    Returns:
        按 loop 顺序排列的 (u, v) 列表；无 Swatch UV 时为空列表
    """
    if target_object.mode == "EDIT":
        _bm, uv_layer, loops = _edit_swatch_loops(target_object, selected_only=False)
        if uv_layer is None:
            return []
        return [tuple(loop[uv_layer].uv) for loop in loops]
    uv_layer = check_uv_layer(target_object, UV_SWATCH)
    if uv_layer is None:
        return []
    return [tuple(loop_uv.uv) for loop_uv in uv_layer.data]


def restore_swatch_uv(target_object, snapshot: list) -> None:
    """
    按 snapshot_swatch_uv 的结果恢复物体 Swatch UV

    Args:
        target_object: Mesh 物体，mode 与拓扑须与记录时一致
        snapshot: snapshot_swatch_uv 返回的坐标列表
    """
    if not snapshot:
        return
    if target_object.mode == "EDIT":
        _bm, uv_layer, loops = _edit_swatch_loops(target_object, selected_only=False)
        for loop, uv in zip(loops, snapshot):
            loop[uv_layer].uv = uv
        bmesh.update_edit_mesh(target_object.data, loop_triangles=False, destructive=False)
        return
    uv_layer = check_uv_layer(target_object, UV_SWATCH)
    uv_layer.data.foreach_set("uv", [value for uv in snapshot for value in uv])
    target_object.data.update()


def get_swatch_material() -> bpy.types.Material:
    """
    获取场景中的 Swatch 材质，不存在时从 Presets.blend 导入

    wm.append 会取消所有物体的选择，导入后须恢复原选择，点选过程依赖当前选择。
    """
    swatch_material = get_scene_material(SWATCH_MATERIAL)
    if swatch_material is None:
        view_layer = bpy.context.view_layer
        selected_objects = [obj for obj in view_layer.objects if obj.select_get()]
        active_object = view_layer.objects.active
        swatch_material = import_material(PRESET_FILE_PATH, SWATCH_MATERIAL)
        for obj in view_layer.objects:
            obj.select_set(obj in selected_objects)
        view_layer.objects.active = active_object
    return swatch_material


def prepare_swatch_object(target_object, swatch_material) -> None:
    """
    确保物体有 Swatch UV（新建时放到默认格子）并使用 Swatch 材质；已有的 Swatch UV 保持不动

    Args:
        target_object: Object Mode 下的 Mesh 物体
        swatch_material: Swatch 材质
    """
    pattern_uv = check_uv_layer(target_object, Const.UV_PATTERN)
    if pattern_uv is not None:
        pattern_uv.name = UV_SWATCH

    swatch_uv = check_uv_layer(target_object, UV_SWATCH)
    if swatch_uv is None:
        swatch_uv = add_uv_layers(target_object, uv_name=UV_SWATCH)
        swatch_uv.data.foreach_set(
            "uv", list(swatch_cell_to_uv(DEFAULT_SWATCH_CELL)) * len(swatch_uv.data)
        )
    swatch_uv.active = True

    if get_object_material(target_object, SWATCH_MATERIAL) is None:
        material_slots = get_object_material_slots(target_object)
        if len(material_slots) == 0:
            target_object.data.materials.append(swatch_material)
        else:
            material_slots[0].material = swatch_material


def is_swatch_object_ready(target_object) -> bool:
    """
    判断物体是否已有 Swatch UV 且使用 Swatch 材质

    Args:
        target_object: Mesh 物体
    """
    return (
        check_uv_layer(target_object, UV_SWATCH) is not None
        and get_object_material(target_object, SWATCH_MATERIAL) is not None
    )


def get_swatch_texture(swatch_material):
    """
    返回 Swatch 材质中 BaseMat_Swatch node group 使用的贴图

    Args:
        swatch_material: Swatch 材质
    """
    for node in swatch_material.node_tree.nodes:
        if node.type == "GROUP" and node.label == SWATCH_TEXTURE_GROUP_LABEL:
            for group_node in node.node_tree.nodes:
                if group_node.type == "TEX_IMAGE":
                    return group_node.image
    return None


def setup_swatch_editor(swatch_material) -> None:
    """
    准备 Swatch 编辑界面：找到或新建 UV 编辑器并显示 Swatch 贴图，切换到 EEVEE 渲染预览

    须在 3D Viewport 的 context 下调用。

    Args:
        swatch_material: Swatch 材质
    """
    uv_editor = check_screen_area("IMAGE_EDITOR")
    if uv_editor is None:
        uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
        uv_editor.ui_type = "UV"
    UV.show_uv_in_object_mode()

    uv_space = uv_editor.spaces.active
    uv_space.image = get_swatch_texture(swatch_material)
    uv_space.display_channels = "COLOR"
    uv_editor_fit_view(uv_editor)
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    switch_to_eevee()
    viewport_shading_mode("VIEW_3D", "RENDERED", mode="CONTEXT")
