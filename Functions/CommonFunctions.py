import bpy
from bpy.utils import register_class, unregister_class


def message_box(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def rename_meshes(objects, name):
    for index, object in enumerate(objects):
        if object.type == "MESH":  # 检测对象是否为mesh
            object.name = name + "_" + str(index + 1).zfill(2)


def filter_type(target_object: bpy.types.Object, type: str):
    """筛选某种类型的object"""
    filtered_objets = []
    type = str.upper(type)

    for object in target_object:
        if object.type == type:
            filtered_objets.append(object)
    return filtered_objets


def get_collection(target_object: bpy.types.Object):
    """获取所选object所在的collection"""
    target_collection = None
    collection: bpy.types.Collection
    object: bpy.types.Object

    for collection in bpy.data.collections:
        for object in collection.objects:
            if object == target_object:
                target_collection = collection
                break

    return target_collection


def clean_user(target_object: bpy.types.Object):
    """如果所选object有多个user，转为single user"""
    if target_object.users > 1:
        target_object.data = target_object.data.copy()
    return target_object


def set_visibility(target_object: bpy.types.Object, hide=bool):
    """设置object在outliner中的可见性"""
    target_object.hide_viewport = hide
    target_object.hide_render = hide


def check_modifier_exist(targetObjects: bpy.types.Object, modifierName: str):
    """检查是否存在某个modifier名，返回bool"""
    modifier_exist = False
    for modifier in targetObjects.modifiers:
        if modifier.name == modifierName:
            modifier_exist = True
    return modifier_exist


def get_objects_with_modifier(target_objects: bpy.types.Object, modifier_name: str):
    """获取有某种modifier的object列表，返回objectList"""
    objects = []
    for object in target_objects:
        for modifier in object.modifiers:
            if modifier is not None and modifier.name == modifier_name:
                if modifier.object is None:
                    objects.append(object)
            else:
                objects.append(object)
    return objects


def cleanup_vertexcolor_attr(target_object: bpy.types.Object):
    """为选中的物体删除所有顶点色属性"""
    success = False
    if target_object.data.color_attributes:
        colorAtrributes = target_object.data.color_attributes
        for r in range(len(colorAtrributes) - 1, -1, -1):
            colorAtrributes.remove(colorAtrributes[r])
        success = True
    return success


def add_vertexcolor_attr(target_object: bpy.types.Object, vertexcolor_name: str):
    """Add vertex color attribute to mesh object"""
    if target_object.type == "MESH":
        if vertexcolor_name in target_object.data.color_attributes:
            color_atrribute = target_object.data.color_attributes[0]
        else:
            color_atrribute = target_object.data.color_attributes.new(
                name=vertexcolor_name,
                type="BYTE_COLOR",
                domain="CORNER",
            )
    else:
        print(target_object + " is not mesh object")
    return color_atrribute


def set_active_vertexcolor_attr(vertexcolor_name: str):
    context = bpy.context
    named_color_attributes = context.object.data.color_attributes
    active_vertexcolor = named_color_attributes.get(vertexcolor_name)
    context.object.data.attributes.active_color = active_vertexcolor


def import_node_group(file_path, node_name):
    """从文件载入nodegroup
    Example:
    from bpy.utils import resource_path
    from pathlib import Path
    USER = Path(resource_path('USER'))
    src = USER / "scripts/addons/" / addondir / assetdir
    file_path = src / "your_file.blend"
    importNodeGroup(file_path,nodename)
    """

    innerPath = "NodeTree"

    for node in bpy.data.node_groups:
        if node_name not in node.name:
            has_node = 0
            print("have no gn")
        else:
            has_node = 1
            print("have gn")
            break

    if has_node == 0:
        bpy.ops.wm.append(
            filepath=str(file_path / innerPath / node_name),
            directory=str(file_path / innerPath),
            filename=node_name,
        )
    return has_node


def set_edge_bevel_weight_from_sharp(target_object: bpy.types.Object):
    has_sharp: bool = False
    if "sharp_edge" in target_object.data.attributes:
        has_sharp = True
        # 如果有倒角权重
        if "bevel_weight_edge" not in target_object.data.attributes:
            bevel_weight_attr = target_object.data.attributes.new(
                "bevel_weight_edge", "FLOAT", "EDGE"
            )
            for index, edge in enumerate(target_object.data.edges):
                bevel_weight_attr.data[index].value = (
                    1.0 if edge.use_edge_sharp else 0.0
                )
    return has_sharp
