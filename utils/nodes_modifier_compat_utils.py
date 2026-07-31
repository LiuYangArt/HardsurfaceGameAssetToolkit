# -*- coding: utf-8 -*-
"""Blender 5.1/5.2 Geometry Nodes modifier 属性兼容工具。"""

import bpy


# 返回可持久化工具元数据的 ID Property owner。
# modifier: Geometry Nodes modifier；返回 Blender 5.1 modifier 或 5.2 独占 Node Group。
def modifier_property_owner(modifier):
    if bpy.app.version >= (5, 2, 0):
        if modifier.node_group is None:
            raise RuntimeError("Geometry Nodes modifier has no Node Group metadata owner")
        return modifier.node_group
    return modifier


# 读取工具写入 Geometry Nodes modifier 的元数据。
# modifier/key/default: modifier、属性名与缺省值；返回已保存值或缺省值。
def modifier_property_get(modifier, key, default=None):
    return modifier_property_owner(modifier).get(key, default)


# 写入工具拥有的 Geometry Nodes modifier 元数据。
# modifier/key/value: modifier、属性名与属性值；无返回值。
def modifier_property_set(modifier, key, value):
    modifier_property_owner(modifier)[key] = value


# 判断 Geometry Nodes modifier 是否保存了指定工具元数据。
# modifier/key: modifier 与属性名；返回 bool。
def modifier_property_contains(modifier, key):
    return key in modifier_property_owner(modifier)


# 删除 Geometry Nodes modifier 上指定的工具元数据。
# modifier/key: modifier 与属性名；无返回值。
def modifier_property_delete(modifier, key):
    owner = modifier_property_owner(modifier)
    if key in owner:
        del owner[key]


# 读取 Geometry Nodes modifier 的 interface input 当前值。
# modifier/identifier: modifier 与 interface socket identifier；返回 socket 值。
def modifier_input_get(modifier, identifier):
    if bpy.app.version >= (5, 2, 0):
        return modifier.properties.inputs[identifier]["value"]
    return modifier[identifier]


# 设置 Geometry Nodes modifier 的 interface input 当前值。
# modifier/identifier/value: modifier、interface socket identifier 与新值；无返回值。
def modifier_input_set(modifier, identifier, value):
    if bpy.app.version >= (5, 2, 0):
        modifier.properties.inputs[identifier]["value"] = value
        return
    modifier[identifier] = value
