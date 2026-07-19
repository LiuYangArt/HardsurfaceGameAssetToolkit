import bpy

import json
import os
from pathlib import Path


# 把 Blender RNA default 转为可写入 JSON 的基础类型。
# 参数 value: 任意 socket default；返回基础类型、list 或字符串。
def json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


# 读取目标 Geometry Nodes group 的接口、内部节点、依赖与 library 状态。
# 参数 group_name/output_path: Node Group 名称与 JSON 输出绝对路径。
def write_node_group_probe(group_name, output_path):
    node_group = bpy.data.node_groups.get(group_name)
    if node_group is None:
        candidates = [
            group
            for group in bpy.data.node_groups
            if "even" in group.name.lower() and "thick" in group.name.lower()
        ]
    else:
        candidates = [node_group]
    payload = {
        "blend_file": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "candidates": [],
    }
    dependencies = set()
    for candidate in candidates:
        dependencies.update(
            node.node_tree.name
            for node in candidate.nodes
            if getattr(node, "node_tree", None) is not None
        )
    candidates.extend(
        dependency
        for name in sorted(dependencies)
        if (dependency := bpy.data.node_groups.get(name)) is not None
        and dependency not in candidates
    )
    for candidate in candidates:
        payload["candidates"].append(
            {
                "name": candidate.name,
                "library": candidate.library.filepath if candidate.library else None,
                "asset": candidate.asset_data is not None,
                "interface": [
                    {
                        "name": item.name,
                        "identifier": getattr(item, "identifier", None),
                        "item_type": item.item_type,
                        "in_out": getattr(item, "in_out", None),
                        "socket_type": getattr(item, "socket_type", None),
                        "default": json_value(getattr(item, "default_value", None)),
                    }
                    for item in candidate.interface.items_tree
                ],
                "nodes": [
                    {
                        "name": node.name,
                        "label": node.label,
                        "type": node.bl_idname,
                        "node_tree": getattr(getattr(node, "node_tree", None), "name", None),
                        "operation": getattr(node, "operation", None),
                        "data_type": getattr(node, "data_type", None),
                        "domain": getattr(node, "domain", None),
                        "inputs": [
                            {
                                "name": socket.name,
                                "default": json_value(getattr(socket, "default_value", None)),
                                "linked": socket.is_linked,
                            }
                            for socket in node.inputs
                        ],
                    }
                    for node in candidate.nodes
                ],
                "links": [
                    {
                        "from_node": link.from_node.name,
                        "from_socket": link.from_socket.name,
                        "to_node": link.to_node.name,
                        "to_socket": link.to_socket.name,
                    }
                    for link in candidate.links
                ],
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HST_EVEN_THICKNESS_PROBE=" + json.dumps(payload, ensure_ascii=False))


write_node_group_probe(
    os.environ.get("HST_EVEN_THICKNESS_GROUP", "Curve-To-Mesh Even-Thickness"),
    Path(os.environ["HST_EVEN_THICKNESS_PROBE_PATH"]),
)
