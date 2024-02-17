import re
import bpy
import bmesh

# import math
# import mathutils
from mathutils import Vector, Matrix, Quaternion, Euler, Color, geometry

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


def filter_type(target_objects: bpy.types.Object, type: str) -> bpy.types.Object:
    """筛选某种类型的object"""
    filtered_objets = []
    type = str.upper(type)

    for object in target_objects:
        if object.type == type:
            filtered_objets.append(object)
    return filtered_objets


def filter_name(target_objects: bpy.types.Object, name: str) -> bpy.types.Object:
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

    for collection in bpy.data.collections:  # 有则返回，无则创建
        if collection.name == collection_name:
            collection_exist = True
            collection = bpy.data.collections[collection_name]
            break
    if collection_exist == False:  # 创建collection,并添加到scene
        collection = bpy.data.collections.new(collection_name)
        collection.color_tag = "COLOR_" + color_num
        bpy.context.scene.collection.children.link(collection)

    return collection


def clean_user(target_object: bpy.types.Object) -> bpy.types.Object:
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


def get_objects_with_modifier(
    target_objects: bpy.types.Object, modifier_name: str
) -> bpy.types.Object:
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
        bpy.ops.object.convert(target="MESH")  # 应用修改器

    return proxy_mesh


def set_active_color_attribute(colorattribute_name: str) -> None:
    """设置顶点色属性为激活状态"""
    context = bpy.context
    named_color_attributes = context.object.data.color_attributes
    active_vertexcolor = named_color_attributes.get(colorattribute_name)
    context.object.data.attributes.active_color = active_vertexcolor


def import_node_group(file_path, node_name):
    """ 从文件载入NodeGroup """

    INNER_PATH = "NodeTree"
    node_exist = False
    for node in bpy.data.node_groups:
        if node_name not in node.name:
            node_exist = False
        else:
            node_exist = True
            break

    if node_exist is False:  # 如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=node_name,
        )

    for node in bpy.data.node_groups:
        if node.name == node_name:
            node_import = node
            break

    return node_import



def import_world(file_path, world_name):
    """从文件载入World Shader"""

    INNER_PATH = "World"
    world_exist = False
    for world in bpy.data.worlds:
        if world_name not in world.name:
            world_exist = False
        else:
            world_exist = True
            break

    if world_exist is False:  # 如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=world_name,
            link=False,
        )

    for world in bpy.data.worlds:
        if  world.name == world_name:
            world_import = world
            break

    return world_import

def import_material(file_path, material_name) -> bool:
    """从文件载入Material"""

    INNER_PATH = "Material"
    exist = False
    for mat in bpy.data.materials:
        if material_name not in mat.name:
            exist = False
        else:
            exist = True
            break

    if exist is False:  # 如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=material_name,
        )

    for mat in bpy.data.materials:
        if mat.name == material_name:
            material_import = mat
            break
        
    return material_import



def set_edge_bevel_weight_from_sharp(target_object: bpy.types.Object) -> bool:
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


def rename_uv_layers(
    target_object: bpy.types.Object, new_name: str, uv_index: int = 0
) -> bpy.types.Object:
    """重命名uv，返回uv_layer"""
    for index, uv_layer in enumerate(target_object.data.uv_layers):
        if index == uv_index:
            uv_layer.name = new_name
            break
        else:
            uv_layer = None
            print(target_object.name + " has no uv layer for index: " + str(uv_index))
    return uv_layer


def add_uv_layers(target_object: bpy.types.Object, uv_name: str) -> bpy.types.Object:
    """新建uv，返回uv_layer"""
    uv_layer = target_object.data.uv_layers.get(
        uv_name
    ) or target_object.data.uv_layers.new(name=uv_name)
    return uv_layer


def check_uv_layer(mesh, uv_name):
    uv_layer = mesh.data.uv_layers.get(uv_name)
    return uv_layer


def has_uv_attribute(mesh):
    has_uv = False
    for attributes in mesh.data.attributes:
        if attributes.domain == "CORNER" and attributes.data_type == "FLOAT2":
            has_uv = True
            break
    return has_uv


def scale_uv(uv_layer, scale=(1, 1), pivot=(0.5, 0.5)) -> None:
    """缩放UV,输入参数为uv_layer,缩放比例，缩放中心点"""
    pivot = Vector(pivot)
    scale = Vector(scale)
    for uv_index in range(len(uv_layer.data)):  # 根据缩放参数重新计算uv每个点的位置
        v = uv_layer.data[uv_index].uv
        s = scale
        p = pivot
        x = p[0] + s[0] * (v[0] - p[0])
        y = p[1] + s[1] * (v[1] - p[1])
        uv_layer.data[uv_index].uv = x, y


def clean_lonely_verts(mesh):
    """清理孤立顶点"""
    lonely_verts_list = []

    bm = bmesh.from_edit_mesh(mesh.data)
    bm.verts.ensure_lookup_table()

    for vertex in bm.verts:  # 遍历顶点，如果顶点不隐藏且连接边数为2，添加到删除列表
        if vertex.hide is False and len(vertex.link_edges) == 2:
            lonely_verts_list.append(vertex)

    bmesh.ops.dissolve_verts(
        bm, verts=lonely_verts_list, use_face_split=False, use_boundary_tear=False
    )

    bmesh.update_edit_mesh(mesh.data)
    bm.free()


def clean_mid_verts(meshes):
    """清理直线中的孤立顶点"""
    bm = bmesh.new()
    for mesh in meshes:
        mesh = mesh.data
        mid_verts_list = []

        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        for vertex in bm.verts:  # 遍历顶点，如果顶点不隐藏且连接边数为2，添加到删除列表
            if vertex.hide is False and len(vertex.link_edges) == 2:
                mid_verts_list.append(vertex)
        bmesh.ops.dissolve_verts(
            bm, verts=mid_verts_list, use_face_split=False, use_boundary_tear=False
        )
        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
    bm.free()


def clean_loose_verts(meshes):
    """清理松散顶点"""
    bm = bmesh.new()

    for mesh in meshes:
        mesh = mesh.data
        bm.from_mesh(mesh)
        # verts with no linked faces
        verts = [v for v in bm.verts if not v.link_faces]

        print(f"{mesh.name}: removed {len(verts)} verts")
        # equiv of bmesh.ops.delete(bm, geom=verts, context='VERTS')
        for vert in verts:
            bm.verts.remove(vert)

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
    bm.free()


def merge_vertes_by_distance(meshes, merge_distance=0.01):
    """清理重复顶点"""
    bm = bmesh.new()
    for mesh in meshes:
        mesh = mesh.data
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
    bm.free()


def mark_sharp_edge_by_angle(meshes, sharp_angle=0.08):
    """根据角度标记锐边"""
    bm = bmesh.new()
    for mesh in meshes:
        mesh = mesh.data
        to_mark_sharp = []
        has_sharp_edge = False
        # get sharp edge index by angle
        bm.from_mesh(mesh)
        for edge in bm.edges:
            if edge.calc_face_angle() >= sharp_angle:
                to_mark_sharp.append(edge.index)
        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        # add sharp edge attribute
        for attributes in mesh.attributes:
            if "sharp_edge" in attributes.name:
                has_sharp_edge = True
                break
        # if no sharp edge attribute, add it
        if has_sharp_edge is False:
            mesh.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
        # mark sharp edge
        for edge in mesh.edges:
            if edge.index in to_mark_sharp:
                edge.use_edge_sharp = True
            else:
                edge.use_edge_sharp = False

        bm.free()


# def get_selected_rotation_matrix():
#     bpy.context.object.update_from_editmode()
#     selected_verts = [vert for vert in bpy.context.object.data.vertices if vert.select]
#     if selected_verts:
#         try:
#             bpy.ops.transform.create_orientation(
#                 name="keTF", use_view=False, use=True, overwrite=True
#             )
#             rotation_matrix = bpy.context.scene.transform_orientation_slots[
#                 0
#             ].custom_orientation.matrix.copy()
#             bpy.ops.transform.delete_orientation()
#             # restore_transform(og)
#         except RuntimeError:
#             print("Fallback: Invalid selection for Orientation - Using Local")
#             # Normal O. with a entire cube selected will fail create_o.
#             bpy.ops.transform.select_orientation(orientation="LOCAL")
#             rotation_matrix = bpy.context.object.matrix_world.to_3x3()
#     return rotation_matrix


def get_selected_rotation_quat() -> Quaternion:
    # 在编辑模式中获取选中元素的位置与旋转

    bpy.ops.transform.create_orientation(
        name="3Points", use_view=False, use=True, overwrite=True
    )

    bpy.context.scene.transform_orientation_slots[0].custom_orientation.matrix.copy()

    custom_matrix = bpy.context.scene.transform_orientation_slots[
        0
    ].custom_orientation.matrix.copy()

    bpy.ops.transform.delete_orientation()

    loc, rot, scale = custom_matrix.to_4x4().decompose()
    return rot


def rotate_quaternion(quaternion, angle, axis) -> Quaternion:
    """旋转四元数，输入角度与轴，返回旋转后的四元数，轴为X,Y,Z"""
    if axis == "X":
        axis = (1, 0, 0)
    elif axis == "Y":
        axis = (0, 1, 0)
    elif axis == "Z":
        axis = (0, 0, 1)
    else:
        print("Invalid axis, use default axis: Z")
        axis = (0, 0, 1)

    angle = angle / 180 * 3.1415926

    rotation = Quaternion(axis, angle)

    return quaternion @ rotation


def get_materials(target_object: bpy.types.Object) -> bpy.types.Material:
    """获取所选物体的材质"""
    materials = []
    for slot in target_object.material_slots:
        materials.append(slot.material)
    return materials


def get_object_material(target_object, material_name: str):
    """检查材质是否存在"""

    material = None
    if target_object.material_slots is not None:
        for slot in target_object.material_slots:
            if slot.material is not None and slot.material.name == material_name:
                material = slot.material
                break
    return material


def get_material_color_texture(material) -> bpy.types.Image:
    """获取材质的颜色纹理"""
    color_texture = None
    for node in material.node_tree.nodes.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            color_texture = node.image
            break
    return color_texture


def get_scene_material(material_name):
    material = None
    for mat in bpy.data.materials:
        if mat.name == material_name:
            material = mat
            break
    return material


def find_scene_materials(material_name):
    material = None
    for mat in bpy.data.materials:
        if material_name in mat.name:
            material.append(mat)
    return material


def check_screen_area(area_type: str):
    screen_area = None
    screen = bpy.context.window.screen
    for area in screen.areas:
        if area.type == area_type:
            # print("has UV editor")
            screen_area = area
            break
    return screen_area


def new_screen_area(area_type: str, direction: str = "VERTICAL"):
    # Create a new area
    area_num = len(bpy.context.window.screen.areas)
    bpy.ops.screen.area_split(direction=direction)
    new_area = bpy.context.window.screen.areas[area_num]
    new_area.type = area_type
    return new_area


def viewport_shading_mode(area_type: str, shading_mode: str):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:  # iterate through areas in current screen
            if area.type == area_type:
                for (
                    space
                ) in area.spaces:  # iterate through spaces in current VIEW_3D area
                    if space.type == area_type:  # check if space is a 3D view
                        space.shading.type = shading_mode
