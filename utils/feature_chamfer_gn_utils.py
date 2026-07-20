# -*- coding: utf-8 -*-
"""Feature Chamfer Geometry Nodes 预览资产、状态与生命周期。"""

import hashlib
import json

import bpy

from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION
from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION_TAG
from ..const import FEATURE_CHAMFER_GN_ASSET_SOURCE
from ..const import FEATURE_CHAMFER_GN_ASSET_SOURCE_TAG
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
from ..const import FEATURE_CHAMFER_PATCHED
from ..const import FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_CURVE_NODE
from ..const import FEATURE_CHAMFER_CURVE_OBJECT_TAG
from ..const import FEATURE_CHAMFER_CURVE_OWNER_TAG
from ..const import PRESET_FILE_PATH
from .experimental_pipe_chamfer_utils import _base_stats
from .experimental_pipe_chamfer_utils import _build_preview_feature_graph
from .experimental_pipe_chamfer_utils import ensure_feature_chamfer_curve_pipe_asset


PREVIEW_NONE = FEATURE_CHAMFER_PREVIEW_NONE
PREVIEW_VALID = FEATURE_CHAMFER_PREVIEW_VALID
PREVIEW_STALE = FEATURE_CHAMFER_PREVIEW_STALE
OWNER_VALUE = "HST_FEATURE_CHAMFER_GN_V1"
CURVE_PREVIEW_BACKEND = "PYTHON_CURVE_PIPE"


class FeatureChamferPreviewError(RuntimeError):
    """可诊断的 Feature Chamfer Preview 失败。"""


# 验证发布资产保留 fixture Boolean Pro 主链和受控 nested dependencies。
# node_group: 待验证 GeometryNodeTree；返回是否满足正式 Preview 基线。
def _is_valid_feature_chamfer_asset(node_group):
    if node_group.get(FEATURE_CHAMFER_GN_ASSET_SOURCE_TAG) != FEATURE_CHAMFER_GN_ASSET_SOURCE:
        return False
    boolean_node = node_group.nodes.get("Boolean Pro")
    group_input = next(
        (node for node in node_group.nodes if node.bl_idname == "NodeGroupInput"),
        None,
    )
    if (
        boolean_node is None
        or boolean_node.bl_idname != "GeometryNodeGroup"
        or boolean_node.node_tree is None
        or not boolean_node.node_tree.name.startswith("HST Feature Chamfer :: Boolean Pro")
        or group_input is None
    ):
        return False
    return (
        any(
            link.from_node == group_input
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry"
            for link in node_group.links
        )
        and any(
            dependency.name.startswith("HST Feature Chamfer :: Float Boolean Edges")
            for dependency in bpy.data.node_groups
        )
        and any(
            dependency.name.startswith("HST Feature Chamfer :: Boolean Solver Select")
            for dependency in bpy.data.node_groups
        )
    )


# 按 exact name、版本与 Boolean Pro runtime contract 导入受控 Preview 资产。
# 无参数；返回只读基线 GeometryNodeTree，冲突时 fail-closed。
def ensure_feature_chamfer_preview_node_group():
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is None:
        if not PRESET_FILE_PATH.exists():
            raise FeatureChamferPreviewError(f"Preview 资产不存在：{PRESET_FILE_PATH}")
        bpy.ops.wm.append(
            filepath=str(PRESET_FILE_PATH),
            directory=str(PRESET_FILE_PATH / "NodeTree"),
            filename=FEATURE_CHAMFER_GN_NODE,
        )
        node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is None or node_group.bl_idname != "GeometryNodeTree":
        raise FeatureChamferPreviewError("无法导入受控 Feature Chamfer Preview 资产")
    if node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION:
        raise FeatureChamferPreviewError("Feature Chamfer Preview 资产版本不匹配")
    if not _is_valid_feature_chamfer_asset(node_group):
        raise FeatureChamferPreviewError("Feature Chamfer Preview 资产缺少受控 Boolean Pro 主链")
    return node_group


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


# 查找由 source Object 拥有的 Python Curve source。
# source_object: Feature Chamfer source Mesh；返回 owned Curve Object 或 None。
def owned_preview_curve(source_object):
    curve_object_name = source_object.get(FEATURE_CHAMFER_CURVE_OBJECT_TAG)
    curve_object = bpy.data.objects.get(curve_object_name) if curve_object_name else None
    if (
        curve_object is None
        or curve_object.type != "CURVE"
    ):
        return None
    modifier = owned_preview_modifier(source_object)
    if modifier is not None:
        object_info = (
            modifier.node_group.nodes.get("HST Python CutterStrands")
            if modifier.node_group is not None
            else None
        )
        if (
            object_info is None
            or object_info.inputs["Object"].default_value != curve_object
        ):
            return None
    return curve_object


# 删除 source 拥有的 Curve Object 与 Curve datablock。
# source_object: Feature Chamfer source Mesh；无返回值。
def _remove_owned_preview_curve(source_object):
    curve_object = owned_preview_curve(source_object)
    if curve_object is not None:
        _remove_preview_curve_object(curve_object)
    if FEATURE_CHAMFER_CURVE_OBJECT_TAG in source_object:
        del source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG]


# 删除指定 Preview Curve Object 与无用户 Curve datablock。
# curve_object: 待删除 Curve Object；无返回值。
def _remove_preview_curve_object(curve_object):
    if curve_object is None or bpy.data.objects.get(curve_object.name) != curve_object:
        return
    curve_data = curve_object.data
    bpy.data.objects.remove(curve_object, do_unlink=True)
    if curve_data.users == 0:
        bpy.data.curves.remove(curve_data)


# 从 FeatureGraph 的有序 strands 重建一个由 Operator 管理的多 spline Curve。
# source_object/radius: source Mesh 与 endpoint cap containment 的采样距离；返回 Curve 与 stats。
def _rebuild_owned_preview_curve(source_object, radius):
    stats = _base_stats(source_object, 0.0, 8, 35.0, 3.0, 1.5, "PREVIEW")
    groups = _build_preview_feature_graph(source_object, radius, stats)
    curve_data = bpy.data.curves.new(
        f"{source_object.name}_FeatureChamferPreviewCurve",
        type="CURVE",
    )
    curve_data.dimensions = "3D"
    for group in groups:
        spline = curve_data.splines.new("POLY")
        spline.points.add(len(group["points"]) - 1)
        for index, point in enumerate(group["points"]):
            spline.points[index].co = (point.x, point.y, point.z, 1.0)
        spline.use_cyclic_u = group["is_cyclic"]
    curve_object = bpy.data.objects.new(curve_data.name, curve_data)
    curve_object.matrix_world = source_object.matrix_world.copy()
    source_object.users_collection[0].objects.link(curve_object)
    curve_object.hide_set(True)
    curve_object.hide_render = True
    curve_object[FEATURE_CHAMFER_CURVE_OWNER_TAG] = source_object.name
    curve_object[FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG] = source_fingerprint(source_object)
    source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG] = curve_object.name
    return curve_object, stats


# 构建正式 Preview wrapper：复制受控资产，仅把 cutter seam 改为 Python Curve Pipe。
# curve_object/radius/show_cutter: owned Curve、倒角半径与 cutter 显示开关。
def _build_curve_preview_node_group(curve_object, radius, show_cutter):
    base_group = ensure_feature_chamfer_preview_node_group()
    curve_pipe_asset = ensure_feature_chamfer_curve_pipe_asset()
    node_group = base_group.copy()
    node_group.name = f"HST Feature Chamfer Curve Preview :: {curve_object.name}"
    node_group[FEATURE_CHAMFER_GN_ASSET_VERSION_TAG] = FEATURE_CHAMFER_GN_ASSET_VERSION
    node_group["hst_feature_chamfer_preview_backend"] = CURVE_PREVIEW_BACKEND
    group_input = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupInput")
    boolean_node = node_group.nodes.get("Boolean Pro")
    switch_node = node_group.nodes.get("HST Boolean Result or Cutter")
    old_cutter_node = node_group.nodes.get("HST Junction-safe Pipe")
    if boolean_node is None or switch_node is None or old_cutter_node is None:
        raise FeatureChamferPreviewError("受控 Preview 资产缺少 cutter seam nodes")
    object_info = node_group.nodes.new("GeometryNodeObjectInfo")
    object_info.name = "HST Python CutterStrands"
    object_info.inputs["Object"].default_value = curve_object
    curve_circle = node_group.nodes.new("GeometryNodeCurvePrimitiveCircle")
    curve_circle.name = "HST Four-sided Chamfer Profile"
    curve_circle.inputs["Resolution"].default_value = 4
    curve_pipe = node_group.nodes.new("GeometryNodeGroup")
    curve_pipe.name = "HST Even-Thickness Curve Pipe"
    curve_pipe.node_tree = curve_pipe_asset
    curve_pipe.inputs["Fill Caps"].default_value = True
    curve_pipe.inputs["Even-Thickness"].default_value = True
    for link in list(node_group.links):
        if (
            link.from_node == old_cutter_node
            and (
                (link.to_node == boolean_node and link.to_socket.name == "Geometry B")
                or (link.to_node == switch_node and link.to_socket.name == "True")
            )
        ):
            node_group.links.remove(link)
    node_group.links.new(group_input.outputs["Radius"], curve_circle.inputs["Radius"])
    node_group.links.new(object_info.outputs["Geometry"], curve_pipe.inputs["Curve"])
    node_group.links.new(curve_circle.outputs["Curve"], curve_pipe.inputs["Profile Curve"])
    node_group.links.new(curve_pipe.outputs["Geometry"], boolean_node.inputs["Geometry B"])
    node_group.links.new(curve_pipe.outputs["Geometry"], switch_node.inputs["True"])
    return node_group


# 删除本工具创建的 per-preview wrapper Node Group。
# modifier: owned Preview modifier；无返回值。
def _remove_owned_preview_node_group(modifier):
    node_group = modifier.node_group if modifier is not None else None
    if (
        node_group is not None
        and node_group.get("hst_feature_chamfer_preview_backend") == CURVE_PREVIEW_BACKEND
    ):
        modifier.node_group = None
        if node_group.users == 0:
            bpy.data.node_groups.remove(node_group)


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
        "adaptivity": 0.0,
        "radius": float(modifier[identifiers["Radius"]]),
        "sample_length": 0.0,
        "show_cutter": bool(modifier[identifiers["Show Cutter"]]),
        "voxel_size": 0.0,
    }


# 读取当前 Preview 状态，并把 source 或资产不一致归类为 stale。
# source_object: Preview 所属 Mesh；Modifier sockets 是 live 参数真源。
def preview_state(source_object):
    if source_object.get(FEATURE_CHAMFER_GN_STATE_TAG) == FEATURE_CHAMFER_PATCHED:
        return FEATURE_CHAMFER_PATCHED
    modifier = owned_preview_modifier(source_object)
    if modifier is None:
        return PREVIEW_NONE
    node_group = modifier.node_group
    stale = (
        node_group is None
        or node_group.get("hst_feature_chamfer_preview_backend") != CURVE_PREVIEW_BACKEND
        or node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_FINGERPRINT_TAG) != source_fingerprint(source_object)
        or modifier.get(FEATURE_CHAMFER_GN_PARAMETERS_TAG)
        != json.dumps(live_preview_parameters(modifier), sort_keys=True)
        or owned_preview_curve(source_object) is None
        or owned_preview_curve(source_object).get(FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG)
        != source_fingerprint(source_object)
    )
    state = PREVIEW_STALE if stale else PREVIEW_VALID
    source_object[FEATURE_CHAMFER_GN_STATE_TAG] = state
    return state


# 创建或幂等更新一个 procedural Feature Chamfer GN Preview。
# source_object: source Mesh；radius/sample_length/voxel_size/adaptivity: GN 参数；show_cutter: 是否显示 cutter。
def ensure_gn_feature_chamfer_preview(
    source_object,
    radius,
    show_cutter=False,
):
    modifier = source_object.modifiers.get(FEATURE_CHAMFER_GN_MODIFIER)
    if modifier is not None and (
        modifier.type != "NODES"
        or modifier.get(FEATURE_CHAMFER_GN_OWNER_TAG) != OWNER_VALUE
    ):
        raise FeatureChamferPreviewError(
            f"Modifier 名称冲突：{FEATURE_CHAMFER_GN_MODIFIER}"
        )
    curve_object = None
    node_group = None
    created_modifier = False
    old_curve_object = owned_preview_curve(source_object)
    old_node_group = modifier.node_group if modifier is not None else None
    try:
        curve_object, graph_stats = _rebuild_owned_preview_curve(source_object, radius)
        node_group = _build_curve_preview_node_group(curve_object, radius, show_cutter)
        identifiers = _input_identifiers(node_group)
        values = {
            "Radius": radius,
            "Show Cutter": show_cutter,
        }
        missing = [name for name in values if name not in identifiers]
        if missing:
            raise FeatureChamferPreviewError(
                f"Preview 资产缺少 interface sockets：{', '.join(missing)}"
            )
        if modifier is None:
            modifier = source_object.modifiers.new(FEATURE_CHAMFER_GN_MODIFIER, "NODES")
            created_modifier = True
        modifier.node_group = node_group
        modifier.show_viewport = True
        modifier.show_render = True
        for name, value in values.items():
            modifier[identifiers[name]] = value
    except Exception:
        if created_modifier and modifier is not None:
            source_object.modifiers.remove(modifier)
        elif modifier is not None:
            modifier.node_group = old_node_group
        if node_group is not None and node_group.users == 0:
            bpy.data.node_groups.remove(node_group)
        _remove_preview_curve_object(curve_object)
        if old_curve_object is not None:
            source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG] = old_curve_object.name
        elif FEATURE_CHAMFER_CURVE_OBJECT_TAG in source_object:
            del source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG]
        raise
    if (
        old_node_group is not None
        and old_node_group.get("hst_feature_chamfer_preview_backend") == CURVE_PREVIEW_BACKEND
        and old_node_group.users == 0
    ):
        bpy.data.node_groups.remove(old_node_group)
    if old_curve_object is not None and old_curve_object != curve_object:
        _remove_preview_curve_object(old_curve_object)
    parameters = live_preview_parameters(modifier)

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
        "curve_object": curve_object,
        "feature_graph": graph_stats,
    }


# 删除本工具拥有的 Preview modifier 与 source 状态 tags。
# source_object: Preview 所属 Mesh；返回是否实际删除了 modifier。
def cancel_gn_feature_chamfer_preview(source_object):
    modifier = owned_preview_modifier(source_object)
    removed = modifier is not None
    if modifier is not None:
        _remove_owned_preview_node_group(modifier)
        source_object.modifiers.remove(modifier)
    _remove_owned_preview_curve(source_object)
    for key in (FEATURE_CHAMFER_GN_STATE_TAG, FEATURE_CHAMFER_GN_LAST_ACTION_TAG):
        if key in source_object:
            del source_object[key]
    return removed
