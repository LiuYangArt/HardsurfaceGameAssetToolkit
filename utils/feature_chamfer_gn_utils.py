# -*- coding: utf-8 -*-
"""Feature Chamfer Geometry Nodes 预览资产、状态与生命周期。"""

import hashlib
import json

import bpy

from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION
from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION_TAG
from ..const import FEATURE_CHAMFER_GN_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_GN_LAST_ACTION_TAG
from ..const import FEATURE_CHAMFER_GN_MODIFIER
from ..const import FEATURE_CHAMFER_GN_NODE
from ..const import FEATURE_CHAMFER_GN_OWNER_TAG
from ..const import FEATURE_CHAMFER_GN_PARAMETERS_TAG
from ..const import FEATURE_CHAMFER_GN_STATE_TAG
from ..const import FEATURE_CHAMFER_PREVIEW_NONE
from ..const import FEATURE_CHAMFER_PREVIEW_STALE
from ..const import FEATURE_CHAMFER_PREVIEW_VALID
from ..const import PRESET_FILE_PATH


PREVIEW_NONE = FEATURE_CHAMFER_PREVIEW_NONE
PREVIEW_VALID = FEATURE_CHAMFER_PREVIEW_VALID
PREVIEW_STALE = FEATURE_CHAMFER_PREVIEW_STALE
OWNER_VALUE = "HST_FEATURE_CHAMFER_GN_V1"


class FeatureChamferPreviewError(RuntimeError):
    """可诊断的 Feature Chamfer Preview 失败。"""


# 计算 source Mesh topology、位置和 Sharp Edge 的稳定指纹。
# source_object: 单个 Mesh Object；返回 SHA-256 字符串。
def source_fingerprint(source_object):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in mesh.vertices],
        "edges": [tuple(edge.vertices) for edge in mesh.edges],
        "polygons": [tuple(polygon.vertices) for polygon in mesh.polygons],
        "sharp_edges": [
            edge.index
            for edge in mesh.edges
            if sharp_attribute is not None and bool(sharp_attribute.data[edge.index].value)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# 查找本工具拥有且名称稳定的 Geometry Nodes modifier。
# source_object: Preview 所属 Mesh Object；返回 modifier 或 None。
def owned_preview_modifier(source_object):
    modifier = source_object.modifiers.get(FEATURE_CHAMFER_GN_MODIFIER)
    if modifier is None or modifier.type != "NODES":
        return None
    if modifier.get(FEATURE_CHAMFER_GN_OWNER_TAG) != OWNER_VALUE:
        return None
    return modifier


# 返回 Node Group 输入 socket 的 identifier 映射，避免硬编码 Socket_N。
# node_group: GeometryNodeTree；返回 input display name 到 identifier 的字典。
def _input_identifiers(node_group):
    return {
        item.name: item.identifier
        for item in node_group.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT"
    }


# 返回 modifier live sockets 中的可调参数字典。
# modifier: 本工具拥有的 Geometry Nodes modifier。
def live_preview_parameters(modifier):
    identifiers = _input_identifiers(modifier.node_group)
    return {
        "adaptivity": float(modifier[identifiers["Adaptivity"]]),
        "radius": float(modifier[identifiers["Radius"]]),
        "sample_length": float(modifier[identifiers["Sample Length"]]),
        "show_cutter": bool(modifier[identifiers["Show Cutter"]]),
        "voxel_size": float(modifier[identifiers["Voxel Size"]]),
    }


# 按 exact name、类型与版本保证发布用 Node Group 可用。
# 无参数；返回受控的 GeometryNodeTree，冲突时 fail-closed。
def ensure_feature_chamfer_preview_node_group():
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is not None:
        if node_group.bl_idname != "GeometryNodeTree":
            raise FeatureChamferPreviewError(
                f"Node Group 名称冲突：{FEATURE_CHAMFER_GN_NODE} 不是 GeometryNodeTree"
            )
        if node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION:
            raise FeatureChamferPreviewError(
                f"Node Group 名称冲突或版本不匹配：{FEATURE_CHAMFER_GN_NODE}"
            )
        return node_group

    if not PRESET_FILE_PATH.exists():
        raise FeatureChamferPreviewError(f"Preview 资产不存在：{PRESET_FILE_PATH}")
    bpy.ops.wm.append(
        filepath=str(PRESET_FILE_PATH),
        directory=str(PRESET_FILE_PATH / "NodeTree"),
        filename=FEATURE_CHAMFER_GN_NODE,
    )
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is None:
        raise FeatureChamferPreviewError(
            f"无法从 Presets.blend 导入 {FEATURE_CHAMFER_GN_NODE}"
        )
    if node_group.bl_idname != "GeometryNodeTree":
        raise FeatureChamferPreviewError("导入的 Preview 资产不是 GeometryNodeTree")
    if node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION:
        raise FeatureChamferPreviewError("导入的 Preview 资产版本不匹配")
    return node_group


# 读取当前 Preview 状态，并把 source 或资产不一致归类为 stale。
# source_object: Preview 所属 Mesh；Modifier sockets 是 live 参数真源。
def preview_state(source_object):
    modifier = owned_preview_modifier(source_object)
    if modifier is None:
        return PREVIEW_NONE
    node_group = modifier.node_group
    stale = (
        node_group is None
        or node_group.name != FEATURE_CHAMFER_GN_NODE
        or node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_FINGERPRINT_TAG) != source_fingerprint(source_object)
        or modifier.get(FEATURE_CHAMFER_GN_PARAMETERS_TAG)
        != json.dumps(live_preview_parameters(modifier), sort_keys=True)
    )
    state = PREVIEW_STALE if stale else PREVIEW_VALID
    source_object[FEATURE_CHAMFER_GN_STATE_TAG] = state
    return state


# 创建或幂等更新一个 procedural Feature Chamfer GN Preview。
# source_object: source Mesh；radius/sample_length/voxel_size/adaptivity: GN 参数；show_cutter: 是否显示 cutter。
def ensure_gn_feature_chamfer_preview(
    source_object,
    radius,
    sample_length,
    voxel_size,
    adaptivity,
    show_cutter=False,
):
    node_group = ensure_feature_chamfer_preview_node_group()
    modifier = source_object.modifiers.get(FEATURE_CHAMFER_GN_MODIFIER)
    if modifier is not None and (
        modifier.type != "NODES"
        or modifier.get(FEATURE_CHAMFER_GN_OWNER_TAG) != OWNER_VALUE
    ):
        raise FeatureChamferPreviewError(
            f"Modifier 名称冲突：{FEATURE_CHAMFER_GN_MODIFIER}"
        )
    parameters = {
        "adaptivity": float(adaptivity),
        "radius": float(radius),
        "sample_length": float(sample_length),
        "show_cutter": bool(show_cutter),
        "voxel_size": float(voxel_size),
    }
    identifiers = _input_identifiers(node_group)
    values = {
        "Radius": radius,
        "Sample Length": sample_length,
        "Voxel Size": voxel_size,
        "Adaptivity": adaptivity,
        "Show Cutter": show_cutter,
    }
    missing = [name for name in values if name not in identifiers]
    if missing:
        raise FeatureChamferPreviewError(
            f"Preview 资产缺少 interface sockets：{', '.join(missing)}"
        )
    if modifier is None:
        modifier = source_object.modifiers.new(FEATURE_CHAMFER_GN_MODIFIER, "NODES")
    modifier.node_group = node_group
    for name, value in values.items():
        modifier[identifiers[name]] = value

    modifier[FEATURE_CHAMFER_GN_OWNER_TAG] = OWNER_VALUE
    modifier[FEATURE_CHAMFER_GN_FINGERPRINT_TAG] = source_fingerprint(source_object)
    modifier[FEATURE_CHAMFER_GN_ASSET_VERSION_TAG] = FEATURE_CHAMFER_GN_ASSET_VERSION
    modifier[FEATURE_CHAMFER_GN_PARAMETERS_TAG] = json.dumps(parameters, sort_keys=True)
    modifier[FEATURE_CHAMFER_GN_STATE_TAG] = PREVIEW_VALID
    modifier[FEATURE_CHAMFER_GN_LAST_ACTION_TAG] = "PREVIEW"
    source_object[FEATURE_CHAMFER_GN_STATE_TAG] = PREVIEW_VALID
    source_object[FEATURE_CHAMFER_GN_LAST_ACTION_TAG] = "PREVIEW"
    bpy.context.view_layer.update()
    return {
        "modifier": modifier,
        "node_group": node_group,
        "parameters": parameters,
        "state": PREVIEW_VALID,
    }


# 删除本工具拥有的 Preview modifier 与 source 状态 tags。
# source_object: Preview 所属 Mesh；返回是否实际删除了 modifier。
def cancel_gn_feature_chamfer_preview(source_object):
    modifier = owned_preview_modifier(source_object)
    removed = modifier is not None
    if modifier is not None:
        source_object.modifiers.remove(modifier)
    for key in (FEATURE_CHAMFER_GN_STATE_TAG, FEATURE_CHAMFER_GN_LAST_ACTION_TAG):
        if key in source_object:
            del source_object[key]
    return removed
