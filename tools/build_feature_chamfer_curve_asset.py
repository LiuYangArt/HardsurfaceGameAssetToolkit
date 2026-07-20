# -*- coding: utf-8 -*-
"""把 Even-Thickness Curve Pipe Node Groups 迁移到插件受控 Presets.blend。"""

import hashlib
import json
import os
from pathlib import Path

import bpy


ROOT_SOURCE_NAME = "Curve-To-Mesh Even-Thickness"
DEPENDENCY_SOURCE_NAME = "Poly-Curve Info"
ROOT_TARGET_NAME = "GN_HSTFeatureChamferCurvePipe"
DEPENDENCY_TARGET_NAME = "HST Feature Chamfer Curve :: Poly-Curve Info"
ASSET_VERSION = 1
ASSET_VERSION_TAG = "hst_feature_chamfer_curve_asset_version"
ASSET_SOURCE_TAG = "hst_feature_chamfer_curve_asset_source"
ASSET_FINGERPRINT_TAG = "hst_feature_chamfer_curve_asset_fingerprint"
ASSET_SOURCE = "geo-node.blend:Curve-To-Mesh Even-Thickness"


# 把 Blender RNA default 转成可稳定 JSON 序列化的值。
# value: socket default 或 RNA 值；返回基础类型、list 或字符串。
def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return [round(float(item), 9) for item in value]
    except (TypeError, ValueError):
        return str(value)


# 计算 Node Group interface、nodes、links 与 socket defaults 的结构指纹。
# node_group: 待冻结的 GeometryNodeTree；返回 SHA-256 字符串。
def _node_group_fingerprint(node_group):
    payload = {
        "interface": [
            {
                "name": item.name,
                "item_type": item.item_type,
                "in_out": getattr(item, "in_out", None),
                "socket_type": getattr(item, "socket_type", None),
                "default": _json_value(getattr(item, "default_value", None)),
            }
            for item in node_group.interface.items_tree
        ],
        "nodes": [
            {
                "name": node.name,
                "type": node.bl_idname,
                "operation": getattr(node, "operation", None),
                "data_type": getattr(node, "data_type", None),
                "domain": getattr(node, "domain", None),
                "node_tree": getattr(getattr(node, "node_tree", None), "name", None),
                "inputs": [
                    {
                        "name": socket.name,
                        "linked": socket.is_linked,
                        "default": _json_value(getattr(socket, "default_value", None)),
                    }
                    for socket in node.inputs
                ],
            }
            for node in sorted(node_group.nodes, key=lambda item: item.name)
        ],
        "links": sorted(
            (
                link.from_node.name,
                link.from_socket.name,
                link.to_node.name,
                link.to_socket.name,
            )
            for link in node_group.links
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# 删除插件拥有的旧 Curve asset，不触碰用户或其它插件同名数据。
# node_group_name: 受控 exact name。
def _remove_owned_node_group(node_group_name):
    node_group = bpy.data.node_groups.get(node_group_name)
    if node_group is None:
        return
    if node_group.get(ASSET_SOURCE_TAG) != ASSET_SOURCE:
        raise RuntimeError(f"Presets.blend 中存在非插件拥有的同名 Node Group: {node_group_name}")
    bpy.data.node_groups.remove(node_group)


# 从源 .blend append 主 Group 与依赖，重命名并写入版本/结构指纹。
# source_path/preset_path: 输入源文件与插件受控 Presets.blend。
def build_curve_asset(source_path, preset_path):
    bpy.ops.wm.open_mainfile(filepath=str(preset_path))
    _remove_owned_node_group(ROOT_TARGET_NAME)
    _remove_owned_node_group(DEPENDENCY_TARGET_NAME)

    bpy.ops.wm.append(
        filepath=str(source_path),
        directory=str(source_path / "NodeTree"),
        filename=ROOT_SOURCE_NAME,
    )
    root_group = bpy.data.node_groups.get(ROOT_SOURCE_NAME)
    if root_group is None:
        raise RuntimeError(f"源文件缺少 NodeTree: {ROOT_SOURCE_NAME}")
    dependency_group = bpy.data.node_groups.get(DEPENDENCY_SOURCE_NAME)
    if dependency_group is None:
        raise RuntimeError(f"源文件缺少依赖 NodeTree: {DEPENDENCY_SOURCE_NAME}")

    dependency_group.name = DEPENDENCY_TARGET_NAME
    root_group.name = ROOT_TARGET_NAME
    root_group.use_fake_user = True
    dependency_group.use_fake_user = True

    for node_group in (root_group, dependency_group):
        node_group[ASSET_VERSION_TAG] = ASSET_VERSION
        node_group[ASSET_SOURCE_TAG] = ASSET_SOURCE
        node_group[ASSET_FINGERPRINT_TAG] = _node_group_fingerprint(node_group)

    bpy.ops.wm.save_as_mainfile(filepath=str(preset_path))
    result = {
        "root": {
            "name": root_group.name,
            "fingerprint": root_group[ASSET_FINGERPRINT_TAG],
            "nodes": len(root_group.nodes),
            "links": len(root_group.links),
        },
        "dependency": {
            "name": dependency_group.name,
            "fingerprint": dependency_group[ASSET_FINGERPRINT_TAG],
            "nodes": len(dependency_group.nodes),
            "links": len(dependency_group.links),
        },
    }
    print("HST_CURVE_ASSET_BUILD=" + json.dumps(result, ensure_ascii=False))


repo_root = Path(os.environ.get("HST_ADDON_ROOT", Path(__file__).resolve().parent.parent))
source = Path(os.environ["HST_CURVE_ASSET_SOURCE"])
build_curve_asset(source, repo_root / "preset_files" / "Presets.blend")