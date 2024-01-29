import bpy

""" 通用functions """


def message_box(text="", title="WARNING", icon="ERROR"):
    """弹出消息框"""

    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def rename_meshes(objects, name):
    """重命名mesh"""
    for index, object in enumerate(objects):
        if object.type == "MESH":  # 检测对象是否为mesh
            object.name = name + "_" + str(index + 1).zfill(2)


def filter_type(target_objects: bpy.types.Object, type: str):
    """筛选某种类型的object"""
    filtered_objets = []
    type = str.upper(type)

    for object in target_objects:
        if object.type == type:
            filtered_objets.append(object)
    return filtered_objets


def filter_name(target_objects: bpy.types.Object, name: str):
    """筛选某种名称的object"""
    filtered_objets = []

    for object in target_objects:
        if object.name == name:
            filtered_objets.append(object)
    return filtered_objets


def get_collection(target_object: bpy.types.Object) -> bpy.types.Collection:
    """获取所选object所在的collection"""
    target_collection = None

    for collection in bpy.data.collections:
        for object in collection.objects:
            if object == target_object:
                target_collection = collection
                break
    return target_collection


def check_collection_exist(collection_name: str) -> bool:
    """检查collection是否存在"""
    collection_exist = False

    for collection in bpy.data.collections:
        if collection.name == collection_name:
            collection_exist = True
            break
    return collection_exist


def create_collection(
    collection_name: str, color_num: str = "01"
) -> bpy.types.Collection:
    """创建collection"""
    collection = None
    collection_exist = False

    for collection in bpy.data.collections:
        if collection.name == collection_name:
            collection = bpy.data.collections[collection_name]
            collection_exist = True
            break
    if collection_exist == False:
        collection = bpy.data.collections.new(collection_name)
        collection.color_tag = "COLOR_" + color_num
        bpy.context.scene.collection.children.link(collection)

    return collection


def clean_user(target_object: bpy.types.Object):
    """如果所选object有多个user，转为single user"""
    if target_object.users > 1:
        target_object.data = target_object.data.copy()
    return target_object


def set_visibility(target_object: bpy.types.Object, visible=bool) -> bool:
    """设置object在outliner中的可见性"""
    if visible is True:
        target_object.hide_viewport = False
        target_object.hide_render = False
    else:
        target_object.hide_viewport = True
        target_object.hide_render = True
    return visible


def check_modifier_exist(target_object: bpy.types.Object, modifier_name: str) -> bool:
    """检查是否存在某个modifier名，返回bool"""
    modifier_exist = False
    for modifier in target_object.modifiers:
        if modifier.name == modifier_name:
            modifier_exist = True
            break
    return modifier_exist


def remove_modifier(
    object, modifier_name: str, has_subobject: bool = False
) -> bpy.types.Object:
    """删除某个modifier,返回modifier对应的子object"""
    modifier_object = None
    # 有 transfer修改器时
    for modifier in object.modifiers:
        if modifier.name == modifier_name:
            # 如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
            if has_subobject is True and modifier.object is not None:
                # if modifier.object is not None:
                modifier_object = modifier.object
            object.modifiers.remove(modifier)

    return modifier_object


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


def cleanup_color_attributes(target_object: bpy.types.Object) -> bool:
    """为选中的物体删除所有顶点色属性"""
    success = False
    if target_object.data.color_attributes:
        colorAtrributes = target_object.data.color_attributes
        for r in range(len(colorAtrributes) - 1, -1, -1):
            colorAtrributes.remove(colorAtrributes[r])
        success = True
    return success


def add_vertexcolor_attribute(target_object: bpy.types.Object, vertexcolor_name: str):
    """为选中的物体添加顶点色属性，返回顶点色属性"""
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


def make_transfer_proxy_mesh(
    object, proxy_prefix, proxy_collection
) -> bpy.types.Object:
    """建立传递模型"""

    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    object.hide_render = True

    # 检查是否存在传递模型
    proxy_mesh_exist = False
    for proxy_mesh in proxy_collection.all_objects:
        if proxy_mesh.name == proxy_prefix + object.name:
            proxy_mesh_exist = True
            break

    if proxy_mesh_exist is False:
        # 复制模型并修改命名
        proxy_mesh = object.copy()
        proxy_mesh.data = object.data.copy()
        proxy_mesh.name = proxy_prefix + object.name
        proxy_mesh.parent = object

        proxy_collection.objects.link(proxy_mesh)

        proxy_mesh.select_set(True)
        proxy_mesh.hide_render = True
        
        bpy.context.view_layer.objects.active = bpy.data.objects[proxy_mesh.name]
        bpy.ops.object.convert(target="MESH")#应用修改器

    return proxy_mesh


def set_active_color_attribute(colorattribute_name: str):
    """设置顶点色属性为激活状态"""
    context = bpy.context
    named_color_attributes = context.object.data.color_attributes
    active_vertexcolor = named_color_attributes.get(colorattribute_name)
    context.object.data.attributes.active_color = active_vertexcolor


def import_node_group(file_path, node_name):
    """从文件载入nodegroup
    Example:
    from bpy.utils import resource_path
    from pathlib import Path
    USER = Path(resource_path('USER'))
    ASSET_PATH = USER / "scripts/addons/" / ADDON_DIR / ASSET_DIR
    NODE_FILE_PATH = ASSET_PATH / "your_file.blend"
    import_node_group(NODE_FILE_PATH,node_name)
    """

    INNER_PATH = "NodeTree"
    has_node = False
    for node in bpy.data.node_groups:#检查是否已经导入
        if node_name not in node.name:
            has_node = False
            print("geomery node not exist,import")
        else:
            has_node = True
            print("geomery node exist,skip")
            break

    if has_node is False:#如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path / INNER_PATH / node_name),
            directory=str(file_path / INNER_PATH),
            filename=node_name,
        )
        
    return has_node


def set_edge_bevel_weight_from_sharp(target_object: bpy.types.Object):
    """根据边缘是否为sharp设置bevel权重"""
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
