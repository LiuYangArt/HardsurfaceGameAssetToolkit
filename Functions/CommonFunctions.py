import bpy
import bmesh
import math
import subprocess

import os
import platform
import json
# import mathutils

from mathutils import Vector, Matrix, Quaternion, Euler, Color, geometry
from ..Const import *
""" 通用functions """


def message_box(text="", title="WARNING", icon="ERROR") -> None:
    """弹出消息框"""

    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

def switch_to_eevee()->None:
    """切换到EEVEE渲染引擎,4.2以上切换为EEVEE Next"""

    if BL_VERSION>=4.2:
            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"


def rename_meshes(target_objects, new_name) -> None:
    """重命名mesh"""
    for index, object in enumerate(target_objects):
        if object.type == "MESH":  # 检测对象是否为mesh
            object.name = new_name + "_" + str(index + 1).zfill(3)


def filter_type(target_objects: bpy.types.Object, type: str) -> bpy.types.Object:
    """筛选某种类型的object"""
    filtered_objects = []
    type = str.upper(type)
    if target_objects:
        for object in target_objects:
            if object.type == type:
                filtered_objects.append(object)

    if len(filtered_objects) == 0: 
        return None
    else:
        return filtered_objects


def filter_name(
    target_objects: bpy.types.Object, name: str, type="INCLUDE"
) -> bpy.types.Object:
    """筛选某种名称的object, type为INCLUDE时包含，为EXCLUDE时排除"""
    filtered_objets = []
    match type:
        case "INCLUDE":
            for object in target_objects:
                if name in object.name:
                    filtered_objets.append(object)
        case "EXCLUDE":
            for object in target_objects:
                if name not in object.name:
                    filtered_objets.append(object)
    return filtered_objets


def get_collection(target_object: bpy.types.Object) -> bpy.types.Collection:
    """获取所选object所在的collection"""
    target_collection = None
    collection = target_object.users_collection[0]
    if collection.name != "Scene Collection":
        target_collection = collection
    # for collection in bpy.data.collections:
    #     for object in collection.objects:
    #         if object == target_object:
    #             target_collection = collection
    #             break
    return target_collection


def check_collection_exist(collection_name: str) -> bool:
    """检查collection是否存在"""
    collection_exist = False

    for collection in bpy.data.collections:
        if collection.name == collection_name:
            collection_exist = True
            break
    return collection_exist



def clean_user(target_object: bpy.types.Object) -> None:
    """如果所选object有多个user，转为single user"""
    if target_object.users > 1:
        target_object.data = target_object.data.copy()


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


def remove_modifier(object, modifier_name: str, has_subobject: bool = False):
    """删除某个modifier,返回modifier对应的子object"""
    modifier_objects = []
    # 有 transfer修改器时
    for modifier in object.modifiers:
        if modifier.name == modifier_name:
            # 如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
            if has_subobject is True and modifier.object is not None:
                modifier_objects.append(modifier.object)
            object.modifiers.remove(modifier)

    if len(modifier_objects) > 0:
        for modifier_object in modifier_objects:
            if modifier_object.parent.name == object.name:
                old_mesh = modifier_object.data
                old_mesh.name = "OldTP_" + old_mesh.name
                print("remove modifier object: " + modifier_object.name)
                bpy.data.objects.remove(modifier_object)
                bpy.data.meshes.remove(old_mesh)

    return


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

    if target_object.data.color_attributes is not None:
        color_attributes = target_object.data.color_attributes
        for r in range(len(color_attributes) - 1, -1, -1):
            color_attributes.remove(color_attributes[r])
        success = True
    return success


def add_vertexcolor_attribute(
    target_object: bpy.types.Object, vertexcolor_name: str
) -> bpy.types.Object:
    """为选中的物体添加顶点色属性，返回顶点色属性"""
    if target_object.type == "MESH":
        if vertexcolor_name in target_object.data.color_attributes:
            color_attribute = target_object.data.color_attributes.get(vertexcolor_name)
        else:
            color_attribute = target_object.data.color_attributes.new(
                name=vertexcolor_name,
                type="BYTE_COLOR",
                domain="CORNER",
            )
    else:
        print(target_object + " is not mesh object")
    return color_attribute


def set_active_color_attribute(target_object, vertexcolor_name: str) -> None:
    """设置顶点色属性为激活状态"""
    color_attribute = None
    if target_object.type == "MESH":
        if vertexcolor_name in target_object.data.color_attributes:
            color_attribute = target_object.data.color_attributes.get(vertexcolor_name)
            target_object.data.attributes.active_color = color_attribute
    #     else:
    #         print("No vertex color attribute named " + vertexcolor_name)
    # else:
    #     print(target_object + " is not mesh object")
    return color_attribute


def vertexcolor_to_vertices(target_mesh, color_attribute, color):
    mesh = target_mesh.data
    bm = bmesh.from_edit_mesh(mesh)

    if color_attribute.domain == "POINT":
        point_color_attribute = color_attribute
        point_color_layer = bm.verts.layers.color[point_color_attribute.name]
        point_colors = []
        for vert in bm.verts:
            if vert.select == True:
                vert[point_color_layer] = color

    elif color_attribute.domain == "CORNER":
        corner_color_attribute = color_attribute
        corner_color_layer = bm.loops.layers.color[corner_color_attribute.name]

        for face in bm.faces:
            if face.select == True:
                for loop in face.loops:
                    loop[corner_color_layer] = color

    bmesh.update_edit_mesh(mesh)

    # old api
    # bpy.ops.object.mode_set(mode = 'VERTEX_PAINT')
    # selected_verts = []
    # for vert in mesh.vertices:
    #     if vert.select == True:
    #         selected_verts.append(vert)

    # for polygon in mesh.polygons:
    #     for selected_vert in selected_verts:
    #         for i, index in enumerate(polygon.vertices):
    #             if selected_vert.index == index:
    #                 loop_index = polygon.loop_indices[i]
    #                 mesh.vertex_colors.active.data[loop_index].color = color
    # bpy.ops.object.mode_set(mode = 'EDIT')


def set_object_vertexcolor(target_object, color: tuple, vertexcolor_name: str) -> None:
    """设置顶点色"""
    color = tuple(color)
    current_mode = bpy.context.active_object.mode
    # print(current_mode)
    if target_object.type == "MESH":
        mesh = target_object.data
        if vertexcolor_name in mesh.color_attributes:
            color_attribute = mesh.color_attributes.get(vertexcolor_name)
            if current_mode == "OBJECT":
                # if vertexcolor_name in mesh.color_attributes:
                #     color_attribute = mesh.color_attributes.get(vertexcolor_name)
                color_attribute.data.foreach_set(
                    "color_srgb", color * len(mesh.loops) * 4
                )
                # else:
                #     print("No vertex color attribute named " + vertexcolor_name)
            elif current_mode == "EDIT":
                vertexcolor_to_vertices(target_object, color_attribute, color)
    #     else:
    #         print("No vertex color attribute named " + vertexcolor_name)

    # else:
    #     print(target_object + " is not mesh object")


def get_color_data(color):
    convert_color = [color[0], color[1], color[2], color[3]]
    return convert_color


def make_transfer_proxy_mesh(mesh, proxy_prefix, proxy_collection) -> bpy.types.Object:
    """建立传递模型"""

    # 检查是否存在传递模型
    proxy_mesh_exist = False
    for proxy_mesh in proxy_collection.all_objects:
        if proxy_mesh.name == proxy_prefix + mesh.name:
            proxy_mesh_exist = True
            break

    if proxy_mesh_exist is False:

        proxy_mesh = mesh.copy()
        proxy_mesh.data = mesh.data.copy()
        proxy_mesh.name = proxy_prefix + mesh.name
        proxy_mesh.parent = mesh
        proxy_collection.objects.link(proxy_mesh)
        proxy_mesh.hide_render = True
        Object.mark_hst_type(proxy_mesh, "PROXY")

        proxy_mesh = apply_modifiers(proxy_mesh)

    proxy_mesh.hide_viewport = True
    proxy_mesh.hide_render = True
    proxy_mesh.select_set(False)
    return proxy_mesh


def remove_node(name):
    node_exist = False
    for node in bpy.data.node_groups:
        if name not in node.name:
            node_exist = False
        else:
            node_exist = True
            node_import = node
            break
    if node_exist:
        #remove node
        bpy.data.node_groups.remove(node_import)

def import_node_group(file_path, node_name) -> bpy.types.NodeGroup:
    """从文件载入NodeGroup"""

    INNER_PATH = "NodeTree"
    node_exist = False
    for node in bpy.data.node_groups:
        if node_name not in node.name:
            node_exist = False
        else:
            node_exist = True
            node_import = node
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


def import_world(file_path, world_name) -> bpy.types.World:
    """从文件载入World Shader"""

    INNER_PATH = "World"
    world_exist = False
    for world in bpy.data.worlds:
        if world_name not in world.name:
            world_exist = False
        else:
            world_exist = True
            world_import = world
            break

    if world_exist is False:  # 如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=world_name,
        )

    for world in bpy.data.worlds:
        if world.name == world_name:
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
            material_import = mat
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


def import_object(file_path, object_name):
    """从文件载入World Shader"""

    INNER_PATH = "Object"
    object_exist = False
    for object in bpy.data.objects:
        if object_name not in object.name:
            object_exist = False
        else:
            object_exist = True
            object_import = object
            break

    if object_exist is False:  # 如果没有导入，导入
        bpy.ops.wm.append(
            filepath=str(file_path),
            directory=str(file_path / INNER_PATH),
            filename=object_name,
        )

    for object in bpy.data.objects:
        if object.name == object_name:
            object_import = object
            break

    return object_import


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


def check_uv_layer(mesh, uv_name) -> bpy.types.Object:
    """检查是否存在uv_layer，返回uv_layer"""
    uv_layer = None
    uv_layer = mesh.data.uv_layers.get(uv_name)
    return uv_layer


def has_uv_attribute(mesh) -> bool:
    """检查是否存在uv属性，返回bool"""
    has_uv = False
    for attributes in mesh.data.attributes:
        if attributes.domain == "CORNER" and attributes.data_type == "FLOAT2":
            has_uv = True
            break
    return has_uv


def scale_uv(mesh, uv_layer, scale=(1, 1), pivot=(0.5, 0.5)) -> None:
    """缩放UV,输入参数为uv_layer,缩放比例，缩放中心点"""

    pivot = Vector(pivot)
    scale = Vector(scale)

    with bpy.context.temp_override(active_object=mesh):

        for uv_index in range(len(uv_layer.data)):  # 根据缩放参数重新计算uv每个点的位置
            v = uv_layer.data[uv_index].uv
            s = scale
            p = pivot
            x = p[0] + s[0] * (v[0] - p[0])
            y = p[1] + s[1] * (v[1] - p[1])
            uv_layer.data[uv_index].uv = x, y


def mark_sharp_edges_by_split_normal(obj) -> None:
    """ 根据SplitNormal标记锐边 """

    bm = bmesh.new()
    mesh = obj.data
    bm.from_mesh(mesh)

    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    loops = mesh.loops



    split_edges = set()

    for vert in bm.verts:
        for edge in vert.link_edges:
            loops_for_vert_and_edge = []
            for face in edge.link_faces:
                for loop in face.loops:
                    if loop.vert == vert:
                        loops_for_vert_and_edge.append(loop)
            if len(loops_for_vert_and_edge) != 2:
                continue
            loop1, loop2 = loops_for_vert_and_edge
            normal1 = loops[loop1.index].normal
            normal2 = loops[loop2.index].normal

            if are_normals_different(normal1, normal2):
                split_edges.add(edge)

    for edge in bm.edges:
        if edge in split_edges:
            edge.smooth = False
            edge.seam = True

    bm.to_mesh(obj.data)
    bm.free()

def are_normals_different(normal_a, normal_b, threshold_angle_degrees=5.0):
    """ 计算法线是否朝向一致 """
    threshold_cosine = math.cos(math.radians(threshold_angle_degrees))
    dot_product = normal_a.dot(normal_b)
    return dot_product < threshold_cosine


def mark_sharp_edge_by_angle(mesh, sharp_angle=0.08) -> None:
    """根据角度标记锐边"""
    bm = bmesh.new()
    mesh = mesh.data
    bm.from_mesh(mesh)

    to_mark_sharp = []
    has_sharp_edge = False

    for edge in bm.edges:  # get sharp edge index by angle
        if edge.calc_face_angle() >= sharp_angle:
            to_mark_sharp.append(edge.index)

    for attributes in mesh.attributes:  # add sharp edge attribute
        if "sharp_edge" in attributes.name:
            has_sharp_edge = True
            break
    # print("has_sharp_edge: " + str(has_sharp_edge))

    if has_sharp_edge is False:  # if no sharp edge attribute, add it
        mesh.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
        # print("add sharp edge attribute")
    for edge in mesh.edges:  # mark sharp edge
        if edge.index in to_mark_sharp:
            edge.use_edge_sharp = True
        else:
            edge.use_edge_sharp = False

    bm.clear()
    bm.free()

def mark_convex_edges(mesh)->None:
    convex_attribute_name="convex_edge"
    convex_attr=MeshAttributes.add(mesh,attribute_name=convex_attribute_name,data_type="FLOAT",domain="EDGE")
    bm=BMesh.init(mesh)

    convex_layer=bm.edges.layers.float[convex_attr.name]
    for edge in bm.edges:  # get sharp edge index by angle
        if edge.is_convex is True:
            edge[convex_layer]=1
        else:
            edge[convex_layer]=0
    BMesh.finished(bm,mesh)

def get_selected_rotation_quat() -> Quaternion:
    """在编辑模式中获取选中元素的位置与旋转"""
    scene = bpy.context.scene
    orientation_slots = scene.transform_orientation_slots

    bpy.ops.transform.create_orientation(
        name="3Points", use_view=False, use=True, overwrite=True
    )
    orientation_slots[0].custom_orientation.matrix.copy()
    custom_matrix = orientation_slots[0].custom_orientation.matrix.copy()
    bpy.ops.transform.delete_orientation()

    loc, rotation, scale = custom_matrix.to_4x4().decompose()
    return rotation


def get_materials(target_object: bpy.types.Object) -> bpy.types.Material:
    """获取所选物体的材质列表"""

    materials = []
    for slot in target_object.material_slots:
        materials.append(slot.material)
    return materials


def get_object_material(target_object, material_name: str) -> bpy.types.Material:
    """获取所选物体的材质"""

    material = None
    if target_object.material_slots is not None:
        for slot in target_object.material_slots:
            if slot.material is not None and slot.material.name == material_name:
                material = slot.material
                break
    return material


def get_object_material_slots(target_object) -> list:
    """获取所选物体的材质槽列表"""
    material_slots = []
    if target_object.material_slots is not None:
        for slot in target_object.material_slots:
            material_slots.append(slot)
    return material_slots


def get_material_color_texture(material) -> bpy.types.Image:
    """获取材质的颜色纹理"""

    color_texture = None
    for node in material.node_tree.nodes.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            color_texture = node.image
            break
    return color_texture


def get_scene_material(material_name) -> bpy.types.Material:
    """获取场景中的材质"""

    material = None
    for mat in bpy.data.materials:
        if mat.name == material_name:
            material = mat
            break
    return material


def find_scene_materials(material_name) -> bpy.types.Material:
    """按名称关键字查找场景中的材质"""

    material = None
    for mat in bpy.data.materials:
        if material_name in mat.name:
            material.append(mat)
    return material


def check_screen_area(area_type: str) -> bpy.types.Area:
    """检查是否存在某种类型的screen area"""

    screen_area = None
    screen = bpy.context.window.screen
    for area in screen.areas:
        if area.type == area_type:
            screen_area = area
            break
    return screen_area


def new_screen_area(
    area_type: str, direction: str = "VERTICAL", size=0.5
) -> bpy.types.Area:
    """创建新的screen area"""

    area_num = len(bpy.context.window.screen.areas)
    bpy.ops.screen.area_split(direction=direction, factor=size)
    new_area = bpy.context.window.screen.areas[area_num]
    new_area.type = area_type
    return new_area


def viewport_shading_mode(area_type: str, shading_type: str, mode="CONTEXT") -> list:
    """设置视口渲染模式,mode为CONTEXT时只设置当前viewport，ALL时设置所有同类型viewport，返回viewport area列表"""
    viewport_spaces = []
    match mode:
        case "CONTEXT":
            viewport = bpy.context.area
            if viewport.type == area_type:
                viewport_spaces.append(bpy.context.area.spaces[0])
        case "ALL":
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == area_type:
                        for space in area.spaces:
                            if space.type == area_type:
                                viewport_spaces.append(space)
    print(viewport_spaces)

    for viewport_space in viewport_spaces:
        viewport_space.shading.type = shading_type

    return viewport_spaces


def apply_modifiers(object: bpy.types.Object) -> bpy.types.Object:
    """应用所有修改器，删除原mesh并替换为新mesh"""

    old_mesh = object.data

    deps_graph = bpy.context.view_layer.depsgraph
    deps_graph.update()
    object_evaluated = object.evaluated_get(deps_graph)
    mesh_evaluated = bpy.data.meshes.new_from_object(
        object_evaluated, depsgraph=deps_graph
    )

    object.data = mesh_evaluated
    for modifier in object.modifiers:
        object.modifiers.remove(modifier)
    new_object = object

    old_mesh.name = "Old_" + old_mesh.name
    old_mesh.user_clear()
    bpy.data.meshes.remove(old_mesh)

    return new_object


def convert_length_by_scene_unit(length: float) -> float:
    """根据场景单位设置转换长度"""
    current_scene = bpy.context.object.users_scene[0].name
    length_unit = bpy.data.scenes[current_scene].unit_settings.length_unit
    match length_unit:
        case "METERS":
            new_length = length * 0.001
        case "CENTIMETERS":
            new_length = length * 0.01
        case "MILLIMETERS":
            new_length = length * 0.1

    return new_length


def uv_editor_fit_view(area):
    """缩放uv视图填充窗口"""
    context = bpy.context
    if area.type == "IMAGE_EDITOR":
        for region in area.regions:
            if region.type == "WINDOW":
                with context.temp_override(area=area, region=region):
                    bpy.ops.image.view_all(fit_view=True)
    else:
        print("No Image Editor")


def uv_unwrap(target_objects, method="ANGLE_BASED", margin=0.005, correct_aspect=True):
    """UV展开"""

    bpy.ops.object.select_all(action="DESELECT")
    for object in target_objects:
        if object.type == "MESH":
            object.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(
        method=method, fill_holes=False, correct_aspect=correct_aspect, margin=margin
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    return


def uv_average_scale(target_objects, uv_layer_name="UVMap"):
    """UV平均缩放"""

    bpy.ops.object.select_all(action="DESELECT")
    for object in target_objects:
        if object.type == "MESH":
            object.select_set(True)
            object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

    store_area_type = bpy.context.screen.areas[0].type

    for area in bpy.context.screen.areas:
        if area.type == "IMAGE_EDITOR":
            area.ui_type = "UV"
            break
        else:
            bpy.context.screen.areas[0].type = "IMAGE_EDITOR"
            bpy.context.screen.areas[0].ui_type = "UV"

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.context.screen.areas[0].type = store_area_type


def culculate_td_areas(mesh, texture_size_x, texture_size_y) -> list:
    """计算TD每个面的大小，输出列表"""
    calculated_obj_td_area = []
    scale_length = bpy.context.scene.unit_settings.scale_length
    face_count = len(mesh.faces)
    texture_size_x = int(texture_size_x)
    texture_size_y = int(texture_size_y)
    aspect_ratio = texture_size_x / texture_size_y
    largest_side = texture_size_x if texture_size_x > texture_size_y else texture_size_y
    # print("unit: " + str(unit_leghth) + " face_count: " + str(face_count) + " texture_size_cur_x: " + str(texture_size_cur_x) + " texture_size_cur_y: " + str(texture_size_cur_y) + " aspect_ratio: " + str(aspect_ratio) + " largest_side: " + str(largest_side))

    for x in range(0, face_count):
        area = 0

        # Calculate total UV area
        loops = []
        for loop in mesh.faces[x].loops:
            loops.append(loop[mesh.loops.layers.uv.active].uv)

        loops_count = len(loops)
        a = loops_count - 1

        for b in range(0, loops_count):
            area += (loops[a].x + loops[b].x) * (loops[a].y - loops[b].y)
            a = b

        area = abs(0.5 * area)

        # Geometry Area
        face_area = mesh.faces[x].calc_area()
        # TexelDensity calculating from selected in panel texture size
        if face_area > 0 and area > 0:
            texel_density = (
                ((largest_side / math.sqrt(aspect_ratio)) * math.sqrt(area))
                / (math.sqrt(face_area) * 100)
                / scale_length
            )
        else:
            texel_density = 0.0001

        td_area_list = [texel_density, area]
        calculated_obj_td_area.append(td_area_list)

    return calculated_obj_td_area


def get_texel_density(target_object, texture_size_x=1024, texture_size_y=1024):
    """获取UV的Texel Density"""
    texture_size_x = int(texture_size_x)
    texture_size_y = int(texture_size_y)
    area = 0
    texel_density = 0
    local_area_list = []
    local_td_list = []

    # Calculate the total area of the UVs
    bm = bmesh.new()
    bm.from_mesh(target_object.data)
    bm.faces.ensure_lookup_table()
    selected_faces = []
    face_count = len(bm.faces)

    for face_id in range(0, face_count):
        selected_faces.append(face_id)

    for face_id in range(face_count):
        face_td_area_list = culculate_td_areas(bm, texture_size_x, texture_size_y)
        local_area = 0
        local_texel_density = 0

        # Calculate UV area and TD per object
        for face_id in selected_faces:
            local_area += face_td_area_list[face_id][1]

        for face_id in selected_faces:
            local_texel_density += (
                face_td_area_list[face_id][0]
                * face_td_area_list[face_id][1]
                / local_area
            )
        # Store local Area and local TD to lists
        local_area_list.append(local_area)
        local_td_list.append(local_texel_density)
        # Calculate Total UV Area
        area += local_area
    # Calculate Final TD
    if area > 0:
        # and finally calculate total TD
        for local_area, local_texel_density in zip(local_area_list, local_td_list):
            texel_density += local_texel_density * local_area / area

    #     uv_space = "%.4f" % round(area * 100, 4) + " %"
    #     density = "%.3f" % round(texel_density, 3)

    # print("texel_density: " + str(texel_density))
    # print("density: " + str(density))
    return texel_density


def set_default_scene_units():
    """设置默认场景单位"""
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1
    bpy.context.scene.unit_settings.length_unit = "CENTIMETERS"


def rename_alt(target_object, new_name, mark="_", num=3):
    """重命名物体，如果名字已存在则在后面加_数字"""
    name_set = {object.name for object in bpy.data.objects}
    if new_name in name_set:
        name_objects_num = []
        for object in bpy.data.objects:
            if object.name.startswith(new_name + mark):
                object_num = object.name.split(mark)[-1]
                object_num = object_num.split(".")[0]
                name_objects_num.append(int(object_num))
        find_largest_digit(name_objects_num)
        new_new_name = (
            new_name + "_" + str(find_largest_digit(name_objects_num) + 1).zfill(num)
        )
    else:
        new_new_name = new_name

    target_object.name = new_new_name

    return new_new_name


def find_largest_digit(list1):
    """找出列表中最大的数字"""
    max_digit = 0  # 初始化最大数字为0
    for num in list1:
        if num > max_digit:
            max_digit = num
    return max_digit


def text_capitalize(text: str) -> str:
    """首字母大写，去除特殊字符"""
    output = "".join(x for x in text.title() if x.isalnum())
    return output


def clean_collection_name(collection_name: str) -> str:
    """清理collection名字"""
    clean_name = (
        collection_name.replace(".", "")
        .replace(" ", "")
        .split(LOW_SUFFIX)[0]
        .split(HIGH_SUFFIX)[0]
        .split(LOWB_SUFFIX)[0]
        .split(HIGHB_SUFFIX)[0]
        .split(DECAL_SUFFIX)[0]
    )
    return clean_name


def filter_collection_by_visibility(type="VISIBLE"):
    """筛选可见或不可见的collection"""
    all_collections = []
    for collection in bpy.data.collections:
        all_collections.append(collection)
    visible_collections = []
    hidden_collections = []
    for collection in all_collections:
        layer_coll = Collection.find_layer_collection_coll(collection)
        if layer_coll:
            if layer_coll.exclude == True:
                hidden_collections.append(collection)

        if collection.hide_viewport == True:
            if collection not in hidden_collections:
                hidden_collections.append(collection)
            if collection.children is not None:
                for child in collection.children:
                    hidden_collections.append(child)
    for collection in all_collections:
        if collection not in hidden_collections:
            visible_collections.append(collection)
    match type:
        case "VISIBLE":
            return visible_collections
        case "HIDDEN":
            return hidden_collections


def reset_transform(target_object: bpy.types.Object) -> None:
    """重置物体的位置，旋转，缩放"""
    target_object.location = (0, 0, 0)
    target_object.rotation_euler = (0, 0, 0)
    target_object.scale = (1, 1, 1)


class FBXExport:
    def staticmesh(target, file_path: str, reset_transform=False):
        """导出staticmesh fbx"""
        bpy.ops.object.select_all(action="DESELECT")
        export_objects = []
        hidden_objects = []
        if target.type == "COLLECTION":
            for object in target.objects:
                export_objects.append(object)
                if object.hide_get() is True:
                    hidden_objects.append(object)
                    object.hide_set(False)

        elif target.type == "MESH":
            export_objects.append(target)
            if target.hide_get() is True:
                hidden_objects.append(target)
                target.hide_set(False)

        obj_transform = {}

        for obj in export_objects:
            obj.hide_set(False)
            obj.select_set(True)
            if obj.type=="MESH":
                Modifier.add_triangulate(obj)

            if reset_transform is True:
                obj_transform[obj] = obj.matrix_world.copy()
                obj.location = (0, 0, 0)
                obj.rotation_euler = (0, 0, 0)
                obj.rotation_quaternion = Quaternion((1, 0, 0, 0))

        bpy.ops.export_scene.fbx(
            filepath=file_path,
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="-Z",
            axis_up="Y",
            global_scale=1.0,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH", "EMPTY"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            # use_batch_own_dir=True,
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=False,
            bake_anim=False,
        )
        for object in hidden_objects:
            object.hide_set(True)

        if reset_transform is True:
            for obj in obj_transform:
                obj.matrix_world = obj_transform[obj]

    def skeletal(target, file_path: str, armature_as_root=False):
        """导出骨骼 fbx"""
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = 0.01
        bpy.context.scene.unit_settings.length_unit = "METERS"

        bpy.ops.object.select_all(action="DESELECT")
        hide_objects = []

        export_objects = []
        armature_names = {}
        if target.type == "COLLECTION":
            for object in target.all_objects:
                if object.hide_get() is True:
                    hide_objects.append(object)
                    # object.hide_set(False)
                if object.type == "ARMATURE":
                    armature_names[object] = object.name
                    if armature_as_root is False:
                        print("Remove Armature as root")
                        object.name = (
                            "Armature"  # fix armature export as redundant root bone
                        )
                    else:
                        print("Export Armature as root")
                    Armature.ops_scale_bones(object, (100, 100, 100))
                if object.type == "MESH" or object.type == "ARMATURE":
                    export_objects.append(object)
                # object.select_set(True)
        elif target.type == "MESH":
            if target.hide_get() is True:
                hide_objects.append(target)
                # target.hide_set(False)
            export_objects.append(target)
            # target.select_set(True)

        obj_transform = {}
        for obj in export_objects:
            obj.hide_set(False)
            obj.select_set(True)
            obj_transform[obj] = obj.matrix_world.copy()

            obj.location = (0, 0, 0)
            obj.rotation_euler = (0, 0, 0)
            # obj.scale = (100, 100, 100)
            obj.rotation_quaternion = Quaternion((1, 0, 0, 0))

        # print(f"obj_transform: {obj_transform}")
        bpy.ops.export_scene.fbx(
            filepath=file_path,
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="Y",
            axis_up="Z",
            global_scale=1,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH", "ARMATURE"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            # use_batch_own_dir=True,
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            use_metadata=False,
            use_custom_props=False,
            add_leaf_bones=False,
            use_armature_deform_only=True,
            armature_nodetype="NULL",
            bake_anim=False,
        )
        # print(f"obj_transform: {obj_transform}")

        for object in hide_objects:
            object.hide_set(True)
        for obj in obj_transform:
            obj.matrix_world = obj_transform[obj]
        for obj in export_objects:
            if obj.type == "ARMATURE":
                obj.name = armature_names[obj]
                Armature.ops_scale_bones(obj, (0.01, 0.01, 0.01))

        set_default_scene_units()


def filter_collections_selection(target_objects):
    """筛选所选物体所在的collection"""
    filtered_collections = []
    SCENE = "Scene Collection"
    if target_objects:
        if len(target_objects) != 0:
            processed_collections = set()
            for obj in target_objects:
                for collection in obj.users_collection:
                    if (
                        collection is not None
                        and collection.name != "Scene Collection"
                        and collection not in processed_collections
                        and not collection.name.startswith("_")
                    ):
                        filtered_collections.append(collection)
                        processed_collections.add(collection)
    else:
        a = bpy.context.view_layer.active_layer_collection.collection
        col = bpy.data.collections.get(a.name)
        filtered_collections.append(col)


    if len(filtered_collections)==0:
        return None
    else:
        return filtered_collections



def filter_collection_types(collections):
    """筛选collection类型，返回筛选后的collection列表，包括decal,prop,low,high"""
    bake_collections = []
    decal_collections = []
    prop_collections = []
    sm_collections = []
    skm_collections = []
    rig_collections = []

    for collection in collections:
        if len(collection.objects) > 0:
            collection_color = str(collection.color_tag)
            if (
                collection.name.startswith("_")
                and PROXY_COLLECTION_COLOR in collection_color
            ):
                continue
            elif collection.name.endswith(LOW_SUFFIX) or collection.name.endswith(
                HIGH_SUFFIX
            ):
                if LOW_COLLECTION_COLOR or HIGH_COLLECTION_COLOR in collection_color:
                    bake_collections.append(collection)
                continue
            elif (
                "_Decal" in collection.name
                and DECAL_COLLECTION_COLOR in collection_color
            ):
                decal_collections.append(collection)
                continue
            elif PROP_COLLECTION_COLOR in collection_color:
                prop_collections.append(collection)
                continue
            elif (
                Const.SKM_COLLECTION_COLOR in collection_color
                and collection.name.endswith(Const.SKM_SUFFIX)
            ):
                skm_collections.append(collection)
                continue
            elif (
                Const.SKM_COLLECTION_COLOR in collection_color
                and collection.name.endswith(Const.RIG_SUFFIX)
            ):
                rig_collections.append(collection)
                continue
            else:
                sm_collections.append(collection)

    return (
        bake_collections,
        decal_collections,
        prop_collections,
        sm_collections,
        skm_collections,
        rig_collections,
    )


# def check_open_bondary(mesh) -> bool:
#     """检查是否存在开放边"""
#     bm = bmesh.new()
#     bm.from_mesh(mesh.data)
#     check_result = False
#     for edge in bm.edges:
#         if edge.is_boundary:
#             print("open edge")
#             check_result = True
#             break
#     bm.clear()
#     bm.free()

#     return check_result


def prep_select_mode() -> tuple:
    """存储当前模式,并切换到OBJECT模式. EXAMPLE: store_mode = prep_select_mode()"""

    active_object = bpy.context.active_object
    if active_object is not None:
        current_mode = bpy.context.active_object.mode
    else:
        current_mode = "OBJECT"
    selected_objects = bpy.context.selected_objects
    store_mode = current_mode, active_object, selected_objects
    if active_object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")

    return store_mode


def restore_select_mode(store_mode) -> None:
    """恢复之前的模式. EXAMPLE: restore_select_mode(store_mode)"""

    current_mode, active_object, selected_objects = store_mode
    if selected_objects is not None:
        bpy.ops.object.select_all(action="DESELECT")
        for object in selected_objects:
            object.select_set(True)
    if active_object is not None:
        bpy.context.view_layer.objects.active = active_object
        active_object.select_set(True)
        bpy.ops.object.mode_set(mode=current_mode)


def set_collision_object(target_object, new_name) -> None:
    """设置碰撞物体"""
    target_object.show_name = True
    target_object.display_type = "WIRE"
    target_object.visible_shadow = False
    target_object.hide_render = True
    for modifier in target_object.modifiers:
        target_object.modifiers.remove(modifier)
    for material_slot in target_object.material_slots:
        target_object.data.materials.clear()
    for attribute in target_object.data.attributes:
        if attribute.data_type == "COLOR" or attribute.data_type == "BYTE_COLOR":
            target_object.data.attributes.remove(attribute)
    for uv_layer in target_object.data.uv_layers:
        target_object.data.uv_layers.remove(uv_layer)
    # set naming
    if new_name is None:
        new_name = target_object.name
    Object.mark_hst_type(target_object, "UCX")
    # target_object.name = UCX_PREFIX + new_name
    rename_alt(target_object, UCX_PREFIX + new_name, mark="_", num=2)


def filter_static_meshes(collection) -> tuple:
    """筛选collection中的mesh,返回staticmeshes,ucx_meshes"""
    staticmeshes = []
    ucx_meshes = []

    collection_meshes = [obj for obj in collection.all_objects if obj.type == "MESH"]
    decal_meshes = Object.filter_hst_type(objects=collection_meshes, type="DECAL")
    if decal_meshes is None:
        decal_meshes = []
    ucx_meshes = [obj for obj in collection_meshes if obj.name.startswith(UCX_PREFIX)]
    for obj in collection_meshes:
        if obj not in ucx_meshes and obj not in decal_meshes:
            staticmeshes.append(obj)

    return staticmeshes, ucx_meshes


def name_remove_digits(name, parts=3, mark="_") -> str:
    """去除名称后的数字"""
    parts = int(parts)
    new_name = name
    name_split = name.split("_")
    if len(name_split) > parts:
        new_name = name.rsplit(mark, 1)[0]
    return new_name


def rename_prop_meshes(objects) -> tuple:
    """重命名prop mesh"""
    selected_collections = filter_collections_selection(objects)
    for collection in selected_collections:
        static_meshes, ucx_meshes = filter_static_meshes(collection)
        rename_meshes(static_meshes, collection.name)
        for ucx_mesh in ucx_meshes:
            Object.mark_hst_type(ucx_mesh, "UCX")
        for static_mesh in static_meshes:
            Object.mark_hst_type(static_mesh, "STATICMESH")

        if len(ucx_meshes) > 0:
            if len(static_meshes) > 0:
                ucx_name = UCX_PREFIX + static_meshes[0].name
            else:
                ucx_name = name_remove_digits(ucx_meshes[0].name)
            rename_meshes(ucx_meshes, ucx_name)
    return static_meshes, ucx_meshes


def check_vertex_color(mesh):
    """检查是否存在顶点色，如有，返回顶点色层"""
    vertex_color_layer = None
    if len(mesh.data.color_attributes) > 0:
        vertex_color_layer = mesh.data.attributes.active_color
    return vertex_color_layer


def make_dir(path):
    """创建文件夹"""
    if not os.path.exists(path):
        os.makedirs(path)


def normalize_path(path: str):
    """规范化路径"""
    path = str(path)
    path = path.replace("\\", "/")
    path = path.replace(" ", "")
    if path.endswith("/"):
        path = path[:-1]
    # if path.startswith("/"):
    #     path = path[1:]
    return path


def fix_ue_game_path(path: str):
    """修复UE路径"""
    path = str(path)
    path = normalize_path(path)
    if not path.startswith("/"):
        path = "/" + path
    return path


def fix_ip_input(ip_address: str):
    ip_address = str(ip_address)
    ip_address = ip_address.replace(" ", "")
    ip_address = ip_address.replace("http://", "")
    ip_address = ip_address.replace("https://", "")
    ip_address = ip_address.replace("/", "")
    ip_address = ip_address.replace("：", ":")
    ip_address = ip_address.replace(",", ":")
    ip_address = ip_address.replace("。", ".")
    ip_address = ip_address.replace("，", ":")
    return ip_address


def make_ue_python_script_command(file_name, command):
    command_lines = [
        f"import {file_name}",
        "from importlib import reload",
        f"reload({file_name})",
        'print("hey!")',
        f"{file_name}.{command}",
        'print("command executed")',
    ]
    return command_lines


def write_json(file_path, data):
    """写入json"""
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def read_json_from_file(file_path):
    """从文件读取json"""
    json_dict = {}
    if file_path.exists():
        with open(file_path, "r") as json_file:
            json_dict = json.load(json_file)
    return json_dict


class BMesh:
    def init(mesh, mode="CONTEXT"):
        """初始化bmesh"""
        current_mode = bpy.context.active_object.mode
        if mode == "CONTEXT":
            if current_mode == "EDIT":
                bm = bmesh.from_edit_mesh(mesh.data)
            else:
                bm = bmesh.new()
                bm.from_mesh(mesh.data)
        elif mode == "OBJECT":
            bm = bmesh.new()
            bm.from_mesh(mesh.data)
        return bm

    def finished(bm, mesh, mode="CONTEXT"):
        """结束bmesh"""
        current_mode = bpy.context.active_object.mode
        if mode == "CONTEXT":
            if current_mode == "EDIT":
                bm.update_edit_mesh(mesh.data)
            else:
                bm.to_mesh(mesh.data)
        elif mode == "OBJECT":
            bm.to_mesh(mesh.data)

        mesh.data.update()
        bm.clear()
        bm.free()

import time
class Material:
    def assign_to_mesh(mesh, target_mat) -> bpy.types.Material:
        """assign material to mesh, return assigned material"""
        has_mat = False
        for mat in mesh.data.materials:
            if mat.name == target_mat.name:
                has_mat = True
                assign_mat = mat
        if not has_mat:
            assign_mat = mesh.data.materials.append(target_mat)
        return assign_mat

    def create_mat(mat_name) -> bpy.types.Material:
        """add material"""
        has_mat = False
        new_mat = None
        for mat in bpy.data.materials:
            if mat.name == mat_name:
                has_mat = True
                new_mat = mat
                break
        if not has_mat:
            placeholder_mat_ = bpy.data.materials.new(name=mat_name)
        return new_mat
    
    def remove_duplicated_mats_ops(object):
        bpy.ops.object.select_all(action="DESELECT")
        object.select_set(True)
        bpy.context.view_layer.objects.active=object
        bpy.ops.object.mode_set(mode="EDIT")
        # bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type="MATERIAL")
        bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.join()




def rotate_quaternion(quaternion, angle, axis="Z") -> Quaternion:
    """旋转四元数，输入角度与轴，返回旋转后的四元数，轴为X,Y,Z"""
    match axis:
        case "X":
            axis = (1, 0, 0)
        case "Y":
            axis = (0, 1, 0)
        case "Z":
            axis = (0, 0, 1)

    angle = angle / 180 * 3.1415926
    rotation = Quaternion(axis, angle)
    return quaternion @ rotation


class Object:
    def get_selected():
        selected_objects = bpy.context.selected_objects
        outliner_objs=Outliner.get_selected_objects()
        if outliner_objs:
            for obj in outliner_objs:
                if obj not in selected_objects:
                    selected_objects.append(obj)
        if len(selected_objects)==0:
            return None
        else:
            return selected_objects

        
    def set_pivot_to_matrix(obj, matrix):
        if obj.type not in ["EMPTY", "FONT"]:
            deltamx = matrix.inverted_safe() @ obj.matrix_world
            obj.matrix_world = matrix
            obj.data.transform(deltamx)

    def move_to_world_origin(obj):
        world_origin_matrix = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        obj.matrix_world = world_origin_matrix

    def add_custom_property(obj: bpy.types.Object, prop_name: str, prop_value: str):
        obj[prop_name] = prop_value

    def read_custom_property(obj, prop_name):
        return obj.get(prop_name)

    def get_hst_type(object: bpy.types.Object):
        return Object.read_custom_property(object, Const.CUSTOM_TYPE)

    def mark_hst_type(object: bpy.types.Object, type: str):
        r"""Mark object type as custom property, types:
        STATICMESH, DECAL, HIGH, SKELETALMESH, SKELETAL, UCX, SOCKET,
        PLACEHOLDER, PROXY"""
        type = type.upper()
        match type:
            case "STATICMESH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_STATIC_MESH
                )
            case "DECAL":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_DECAL)
            case "LOW":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_BAKE_LOW
                )
            case "HIGH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_BAKE_HIGH
                )
            case "SKELETALMESH":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SKELETAL_MESH
                )
            case "SKELETAL":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SKELETAL
                )
            case "SPLITSKEL":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_SPLITSKEL
                )
            case "SKM":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_SKM)
            case "UCX":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_UCX)
            case "SOCKET":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_SOCKET)
            case "PLACEHOLDER":
                Object.add_custom_property(
                    object, Const.CUSTOM_TYPE, Const.TYPE_PLACEHOLDER
                )
            case "PROXY":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_PROXY)
            case "ORIGIN":
                Object.add_custom_property(object, Const.CUSTOM_TYPE, Const.TYPE_ORIGIN)

    def filter_hst_type(objects, type, mode="INCLUDE"):
        """Filter objects by type"""
        type = type.upper()
        mode = mode.upper()
        filtered_objects = []
        include_objects = []
        # exclude_objects = []
        for object in objects:
            object_type = Object.read_custom_property(object, Const.CUSTOM_TYPE)
            match type:
                case "STATICMESH":
                    if object_type == Const.TYPE_STATIC_MESH:
                        include_objects.append(object)
                case "DECAL":
                    if object_type == Const.TYPE_DECAL:
                        include_objects.append(object)
                case "BAKE_HIGH":
                    if object_type == Const.TYPE_BAKE_HIGH:
                        include_objects.append(object)
                case "SKELETALMESH":
                    if object_type == Const.TYPE_SKELETAL_MESH:
                        include_objects.append(object)
                case "RIG":
                    if object_type == Const.TYPE_SKELETAL:
                        include_objects.append(object)
                case "UCX":
                    if object_type == Const.TYPE_UCX:
                        include_objects.append(object)
                case "SOCKET":
                    if object_type == Const.TYPE_SOCKET:
                        include_objects.append(object)
                case "PLACEHOLDER":
                    if object_type == Const.TYPE_PLACEHOLDER:
                        include_objects.append(object)
                case "ORIGIN":
                    if object_type == Const.TYPE_ORIGIN:
                        include_objects.append(object)
                case "PROXY":
                    if object_type == Const.TYPE_PROXY:
                        include_objects.append(object)

        if mode == "INCLUDE":
            filtered_objects = include_objects
        elif mode == "EXCLUDE":
            for object in objects:
                if object not in include_objects:
                    filtered_objects.append(object)
        if len(filtered_objects) == 0:
            return None
        return filtered_objects

    def sort_types(objects):
        sorted_objects = {}
        for object in objects:
            object_type = object.get(Const.CUSTOM_TYPE)
            if object_type not in sorted_objects:
                sorted_objects[object_type] = []
            sorted_objects[object_type].append(object)
        return sorted_objects

    def check_empty_mesh(object):
        if object.type == "MESH":
            if len(object.data.vertices) == 0:
                return True
            else:
                return False
    def break_link_from_assetlib(object):
        obj_collection = object.users_collection[0]
        unlinked_mesh =object.copy()
        unlinked_mesh.data = object.data.copy()
        obj_collection.objects.link(unlinked_mesh)
        mesh_data=object.data
        mesh_name=object.name
        bpy.data.objects.remove(object)
        bpy.data.meshes.remove(mesh_data)
        unlinked_mesh.name = mesh_name
        return unlinked_mesh


class Transform:
    def rotate_quat(quaternion, angle, axis="Z") -> Quaternion:
        """旋转四元数，输入角度与轴，返回旋转后的四元数，轴为X,Y,Z"""
        match axis:
            case "X":
                axis = (1, 0, 0)
            case "Y":
                axis = (0, 1, 0)
            case "Z":
                axis = (0, 0, 1)

        angle = angle / 180 * 3.1415926
        rotation = Quaternion(axis, angle)
        return quaternion @ rotation

    def scale_matrix(matrix, scale_factor, size=4):
        """Scale a matrix by a specified factor"""
        # Create a scale matrix
        scale_matrix = Matrix.Scale(scale_factor, size)

        # Multiply the original matrix by the scale matrix
        scaled_matrix = matrix @ scale_matrix

        return scaled_matrix

    def rotate_matrix(matrix, angle, axis="Z"):
        """Rotate a matrix by a specified angle around a specified axis"""
        # Create a rotation matrix for a 90 degree rotation around the X-axis
        rotation_matrix = Matrix.Rotation(math.radians(angle), 4, axis)

        # Multiply the original matrix by the rotation matrix
        rotated_matrix = matrix @ rotation_matrix

        return rotated_matrix

    def apply_scale(object):
        obj_matrix = object.matrix_local
        location, rotation, scale = obj_matrix.decompose()
        mat_scale = Matrix.LocRotScale(None, None, scale)
        object.data.transform(mat_scale)
        object.scale = 1, 1, 1

    def apply(object, location=True, rotation=True, scale=True):
        """应用变换"""
        # matrix_basis = object.matrix_basis.copy()
        matrix_basis = object.matrix_basis
        matrix = Matrix()
        loc, rot, scale = matrix_basis.decompose()

        translation = Matrix.Translation(loc)
        rotation = matrix_basis.to_3x3().normalized().to_4x4()
        scale = Matrix.Diagonal(scale).to_4x4()

        transform = [matrix, matrix, matrix]
        basis = [translation, rotation, scale]

        def swap(i):
            transform[i], basis[i] = basis[i], transform[i]

        if location:
            swap(0)
        if rotation:
            swap(1)
        if scale:
            swap(2)

        new_matrix = transform[0] @ transform[1] @ transform[2]
        if hasattr(object.data, "transform"):
            object.data.transform(new_matrix)
        for child in object.children:
            child.matrix_local = new_matrix @ child.matrix_local

        object.matrix_basis = basis[0] @ basis[1] @ basis[2]

    def ops_apply(object, location=True, rotation=True, scale=True):
        """Apply transformation to object"""
        object.select_set(True)
        bpy.context.view_layer.objects.active = object
        bpy.ops.object.transform_apply(
            location=location, rotation=rotation, scale=scale
        )
        object.select_set(False)


# class Files:
#     def make_dir(path: str):
#         """检查路径是否存在，不存在则创建"""
#         if not os.path.exists(path):
#             os.makedirs(path)
#         return path


class Armature:
    def set_bone_roll(armature, roll=0):
        for bone in armature.data.bones:
            bone.roll = roll

    def set_display(obj):
        """Set display settings for an armature object"""
        obj.data.display_type = "WIRE"
        obj.data.show_names = True
        obj.data.show_axes = True
        obj.show_in_front = True
        # obj.relation_line_position = 'HEAD'

    def scale_bones(armature, scale_factor):
        """Scale bones of an armature"""
        for bone in armature.data.bones:
            bone.head = bone.head * scale_factor
            bone.tail = bone.tail * scale_factor

    def ops_scale_bones(armature, scale=(1, 1, 1)):
        """Scale bones of an armature"""
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.armature.select_all(action="SELECT")
        bpy.ops.transform.resize(
            value=scale,
            orient_type="GLOBAL",
            orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            orient_matrix_type="GLOBAL",
            mirror=False,
            snap=False,
            snap_elements={"INCREMENT"},
            use_snap_project=False,
            snap_target="CLOSEST",
            use_snap_self=True,
            use_snap_edit=True,
            use_snap_nonedit=True,
            use_snap_selectable=False,
            alt_navigation=True,
        )
        bpy.ops.object.mode_set(mode="OBJECT")


class Collection:
    def sort_order(collection, case_sensitive=False):

        if collection.children is None:
            return

        children = sorted(
            collection.children,
            key=lambda c: c.name if case_sensitive else c.name.lower(),
        )

        for child in children:
            collection.children.unlink(child)
            collection.children.link(child)
            Collection.sort_order(child)

        # for scene in bpy.data.scenes:
        #     sort_order(scene.collection, case_sensitive=True)

    def get_selected():
        selected_objects = Object.get_selected()
        selected_collections=[]
        if selected_objects:
            for obj in selected_objects:
                for collection in obj.users_collection:

                    if (
                        collection is not None
                        and collection.name != "Scene Collection"
                        and collection not in selected_collections
                        and not collection.name.startswith("_")
                    ):
                        selected_collections.append(collection)


        

        if len(selected_collections)==0:
            outliner_collections = Outliner.get_selected_collections()
            if outliner_collections is not None:
                for collection in outliner_collections:
                    if collection not in selected_collections:
                        selected_collections.append(collection)
        
        if len(selected_collections)==0:
            return None
        else:
            return selected_collections


    def mark_hst_type(collection: bpy.types.Collection, type: str = "PROP"):
        r"""Mark collection type,types:
        PROP, DECAL, BAKE_LOW, BAKE_HIGH, SKM, RIG, PROXY"""
        type = type.upper()
        match type:
            case "PROP":
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_PROP_COLLECTION
                )
                collection.color_tag = "COLOR_" + PROP_COLLECTION_COLOR
            case "DECAL":
                collection.color_tag = "COLOR_" + DECAL_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_DECAL_COLLECTION
                )
            case "LOW":
                collection.color_tag = "COLOR_" + LOW_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_BAKE_LOW_COLLECTION
                )
            case "HIGH":
                collection.color_tag = "COLOR_" + HIGH_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_BAKE_HIGH_COLLECTION
                )
            case "SKM":
                collection.color_tag = "COLOR_" + Const.SKM_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_SKM_COLLECTION
                )
            case "RIG":
                collection.color_tag = "COLOR_" + Const.RIG_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_RIG_COLLECTION
                )
            case "PROXY":
                collection.color_tag = "COLOR_" + PROXY_COLLECTION_COLOR
                Object.add_custom_property(
                    collection, Const.CUSTOM_TYPE, Const.TYPE_PROXY_COLLECTION
                )
            case "MISC":
                collection.color_tag = "COLOR_" + PROXY_COLLECTION_COLOR

    def create(name: str, type: str = "PROP") -> bpy.types.Collection:
        """创建collection,type为PROP,DECAL,BAKE_LOW,BAKE_HIGH,SKM,RIG,PROXY"""
        type = type.upper()
        collection = None
        collection_exist = False

        for collection in bpy.data.collections:  # 有则返回，无则创建
            if collection.name == name:
                collection_exist = True
                collection = bpy.data.collections[name]
                break
        if collection_exist == False:  # 创建collection,并添加到scene
            collection = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(collection)

        Collection.mark_hst_type(collection, type)

        return collection

    def get_hst_type(collection: bpy.types.Collection) -> str:
        """获取collection类型"""
        collection_type = Object.read_custom_property(collection, Const.CUSTOM_TYPE)
        return collection_type

    def filter_hst_type(collections, type, mode="INCLUDE"):
        """Filter collections by type"""
        type = type.upper()
        mode = mode.upper()
        filtered_collections = []
        include_collections = []
        # exclude_objects = []
        for collection in collections:
            collection_type = Collection.get_hst_type(collection)
            match type:
                case "PROXY":
                    if collection_type == Const.TYPE_PROXY_COLLECTION:
                        include_collections.append(collection)
                case "BAKE_LOW":
                    if collection_type == Const.TYPE_BAKE_LOW_COLLECTION:
                        include_collections.append(collection)
                case "BAKE_HIGH":
                    if collection_type == Const.TYPE_BAKE_HIGH_COLLECTION:
                        include_collections.append(collection)
                case "DECAL":
                    if collection_type == Const.TYPE_DECAL_COLLECTION:
                        include_collections.append(collection)
                case "PROP":
                    if collection_type == Const.TYPE_PROP_COLLECTION:
                        include_collections.append(collection)
                case "SKM":
                    if collection_type == Const.TYPE_SKM_COLLECTION:
                        include_collections.append(collection)
                case "RIG":
                    if collection_type == Const.TYPE_RIG_COLLECTION:
                        include_collections.append(collection)
                case _:
                    if collection_type == None:
                        include_collections.append(collection)

        if mode == "INCLUDE":
            filtered_collections = include_collections
        elif mode == "EXCLUDE":
            for collection in collections:
                if collection not in include_collections:
                    filtered_collections.append(collection)
        if len(filtered_collections) == 0:
            return None
        return filtered_collections

    def sort_hst_types(collections: list):
        """筛选collection类型，返回筛选后的collection列表，包括bake,decal,prop,sm,skm,rig"""
        bake_collections = []
        decal_collections = []
        prop_collections = []
        sm_collections = []
        skm_collections = []
        rig_collections = []

        for collection in collections:
            if len(collection.objects) > 0:
                collection_type = Object.read_custom_property(
                    collection, Const.CUSTOM_TYPE
                )
                match collection_type:

                    case Const.TYPE_PROXY_COLLECTION:
                        continue
                    case Const.TYPE_BAKE_LOW_COLLECTION:
                        bake_collections.append(collection)
                    case Const.TYPE_BAKE_HIGH_COLLECTION:
                        bake_collections.append(collection)
                    case Const.TYPE_DECAL_COLLECTION:
                        decal_collections.append(collection)
                    case Const.TYPE_PROP_COLLECTION:
                        prop_collections.append(collection)
                    case Const.TYPE_SKM_COLLECTION:
                        skm_collections.append(collection)
                    case Const.TYPE_RIG_COLLECTION:
                        rig_collections.append(collection)
                    case _:
                        sm_collections.append(collection)
        return (
            bake_collections,
            decal_collections,
            prop_collections,
            sm_collections,
            skm_collections,
            rig_collections,
        )

    def find_parent(collection):
        parent = dict()

        all_collections = bpy.data.collections
        for c in all_collections:
            parent[c] = None
        for c in all_collections:
            for ch in c.children:
                parent[ch] = c

        parent_collection = parent[collection]

        return parent_collection
    
    def find_parent_recur(collection:bpy.types.Collection,type:str):
        parent_c=Collection.find_parent(collection)
        if parent_c == None:
            return None
        else:
            # if type == "NONE":
            #     return parent_c
            # else:
            parent_c_type=Collection.get_hst_type(parent_c)
            if parent_c_type != type:
                parent_c=Collection.find_parent_recur(parent_c,type)
                if parent_c:
                    return parent_c
            else:
                return parent_c

    def active(collection):
        """激活collection"""
        layer_collection = Collection.find_layer_collection(collection)
        # layer_collection=Collection.find_layer_collection_coll(collection)
        bpy.context.view_layer.active_layer_collection = layer_collection

    def find_layer_collection_all(collection_name):
        """递归查找collection对应的layer_collection"""

        for i in bpy.data.collections:
            layer_collection = bpy.context.view_layer.layer_collection
            layer_collection = Collection.layer_recur_find_parent(layer_collection, i.name)
        return layer_collection

    def find_layer_collection_coll(collection):
        """递归查找collection对应的layer_collection"""
        collection_name = collection.name
        if collection.objects:
            object = collection.objects[0]

            for i in object.users_collection:
                layer_collection = bpy.context.view_layer.layer_collection
                layer_collection = Collection.layer_recur_find_parent(
                    layer_collection, i.name
                )
            return layer_collection
        else:
            return None

    def find_layer_collection(collection):
        """递归查找collection对应的layer_collection"""

        layer_collection = bpy.context.view_layer.layer_collection
        layer_collection = Collection.layer_recur_find_parent(
            layer_collection, collection.name
        )

        return layer_collection

    def find_layer_collection_by_name(collection_name):
        """递归查找collection对应的layer_collection"""
        for collection in bpy.data.collections:
            if collection.name == collection_name:
                object = collection.objects[0]
                break
        # obj = bpy.context.object
        for i in object.users_collection:
            layer_collection = bpy.context.view_layer.layer_collection
            layer_collection = Collection.layer_recur_find_parent(layer_collection, i.name)
        return layer_collection

    def layer_recur_find_parent(layer_collection, collection_name):
        found = None
        if layer_collection.name == collection_name:
            return layer_collection
        for layer in layer_collection.children:
            found = Collection.layer_recur_find_parent(layer, collection_name)
            if found:
                return found
            
    def get_by_name(collection_name: str) -> bool:
        """检查collection是否存在"""
        target_collection=None

        for collection in bpy.data.collections:
            if collection.name == collection_name:
                target_collection=collection
                break
        return target_collection


class VertexColor:


    def add(
    target_object: bpy.types.Object, vertexcolor_name: str
    ) -> bpy.types.Object:
        """为选中的物体添加顶点色属性，返回顶点色属性"""
        if target_object.type == "MESH":
            if vertexcolor_name in target_object.data.color_attributes:
                color_attribute = target_object.data.color_attributes.get(vertexcolor_name)
            else:
                color_attribute = target_object.data.color_attributes.new(
                    name=vertexcolor_name,
                    type="BYTE_COLOR",
                    domain="CORNER",
                )
            print(f"{target_object} has vertexcolor {color_attribute.name}")
            return color_attribute
        else:
            print(target_object + " is not mesh object")
            return None
        

    def remove_all(mesh: bpy.types.Object) -> bool:
        """为选中的物体删除所有顶点色属性"""
        success = False

        if mesh.data.color_attributes is not None:
            color_attributes = mesh.data.color_attributes
            for r in range(len(color_attributes) - 1, -1, -1):
                color_attributes.remove(color_attributes[r])
            success = True
        return success

    def remove_attr_by_name(mesh: bpy.types.Object, name: str, mode: str = "INCLUDE"):

        for attr in mesh.data.color_attributes:

            match mode:
                case "INCLUDE":
                    if attr.name == name:
                        mesh.data.color_attributes.remove(attr)
                        break
                case "EXCLUDE":
                    if attr.name is not None:
                        if attr.name != name:
                            mesh.data.color_attributes.remove(attr)

    def add_curvature(mesh):
        """为选中的mesh添加curvature vertex color层"""
        visibility = mesh.visible_get()
        if visibility is False:
            mesh.hide_viewport = False
        bpy.context.view_layer.objects.active = mesh
        current_mode = bpy.context.object.mode

        if CURVATURE_ATTR in mesh.data.color_attributes:
            color_attribute = mesh.data.color_attributes.get(CURVATURE_ATTR)
            mesh.data.color_attributes.remove(color_attribute)

        vertex_color_layer = mesh.data.color_attributes.new(
            name=CURVATURE_ATTR,
            type="BYTE_COLOR",
            domain="CORNER",
        )

        mesh.data.attributes.active_color = vertex_color_layer

        if current_mode != "VERTEX_PAINT":
            bpy.ops.object.mode_set(mode="VERTEX_PAINT")

        bpy.ops.paint.vertex_color_dirt(
            blur_strength=1,
            blur_iterations=1,
            clean_angle=3.14159,
            dirt_angle=0,
            dirt_only=False,
            normalize=True,
        )
        bpy.ops.object.mode_set(mode=current_mode)
        if visibility is False:
            mesh.hide_viewport = True

    def set_alpha(mesh, alpha_value, vertexcolor_name: str):

        visibility = mesh.visible_get()
        if visibility is False:
            mesh.hide_viewport = False
        bpy.context.view_layer.objects.active = mesh
        current_mode = bpy.context.object.mode
        if current_mode != "VERTEX_PAINT":
            bpy.ops.object.mode_set(mode="VERTEX_PAINT")

        if vertexcolor_name in mesh.data.color_attributes:
            color_attribute = mesh.data.color_attributes.get(vertexcolor_name)
        mesh.data.attributes.active_color = color_attribute

        mesh = mesh.data
        ca = mesh.attributes.active_color
        if ca.domain == "POINT":
            for vi, v in enumerate(mesh.vertices):
                if v.select:
                    ca.data[vi].color[3] = alpha_value
        elif ca.domain == "CORNER":
            for li, l in enumerate(mesh.loops):
                if mesh.vertices[l.vertex_index].select:
                    ca.data[li].color[3] = alpha_value

        bpy.ops.object.mode_set(mode=current_mode)
        if visibility is False:
            mesh.hide_viewport = True


class MeshAttributes:
    def add(mesh:bpy.types.Object, attribute_name: str, data_type: str, domain: str):

        if attribute_name not in mesh.data.attributes:
            target_attribute = mesh.data.attributes.new(
                attribute_name, data_type, domain
            )
        else:
            target_attribute = mesh.data.attributes[attribute_name]
    
        return target_attribute

    def fill_points(mesh:bpy.types.Object, attribute, value: float):
        value = float(value)
        attribute_values = [value for i in range(len(mesh.data.vertices))]
        attribute.data.foreach_set("value", attribute_values)
        mesh.data.update()


class Viewport:
    def is_local_view():
        is_local_view = False
        view3d_space=Viewport.get_3dview_space()
        # if bpy.context.space_data.local_view:
        if view3d_space.local_view:
            is_local_view = True
        return is_local_view

    def get_3dview_space():
        target_space = None
        area = check_screen_area("VIEW_3D")
        if area:
            for space in area.spaces:
                if "View3D" in str(space):
                    target_space = space
                    break
        return target_space


def copy_to_clip(txt: str):
    """copy text string to clipboard"""
    cmd = "echo " + txt.strip() + "|clip"
    return subprocess.check_call(cmd, shell=True)


class Outliner:
    def get_selected_object_ids():
        area = next(
            area for area in bpy.context.window.screen.areas if area.type == "OUTLINER"
        )

        with bpy.context.temp_override(
            window=bpy.context.window,
            area=area,
            region=next(region for region in area.regions if region.type == "WINDOW"),
            screen=bpy.context.window.screen,
        ):
            ids = bpy.context.selected_ids
            objects_in_selection = []
            for item in ids:
                if item.bl_rna.identifier == "Object":
                    objects_in_selection.append(item.name)

        if len(objects_in_selection) == 0:
            return None
        else:  # Print the dict to the console
            return objects_in_selection

    def get_selected_collection_ids():
        area = next(
            area for area in bpy.context.window.screen.areas if area.type == "OUTLINER"
        )

        with bpy.context.temp_override(
            window=bpy.context.window,
            area=area,
            region=next(region for region in area.regions if region.type == "WINDOW"),
            screen=bpy.context.window.screen,
        ):
            ids = bpy.context.selected_ids
            objects_in_selection = []
            for item in ids:
                if item.bl_rna.identifier == "Collection":
                    objects_in_selection.append(item.name)

        if len(objects_in_selection) == 0:
            return None
        else:  # Print the dict to the console
            return objects_in_selection

    def get_selected_objects():
        """return selected outliner objects"""
        selection_ids = Outliner.get_selected_object_ids()
        objects = []
        if selection_ids is not None:
            for id in selection_ids:
                if bpy.context.scene.objects[id]:
                    objects.append(bpy.context.scene.objects[id])
        if len(objects) == 0:
            return None
        else:
            return objects

    def get_selected_collections():
        """
        return selected outliner collections
        """
        # print_selected_collections()
        selection_ids = Outliner.get_selected_collection_ids()
        objects = []
        if selection_ids is not None:
            for id in selection_ids:
                if bpy.data.collections[id]:
                    objects.append(bpy.data.collections[id])
        if len(objects) == 0:
            return None
        else:
            return objects


class FilePath:
    
    
    def open_os_path(path:str):
        
        # os.startfile(path) 
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            opener = "open" if platform.system() == "Darwin" else "xdg-open"
            subprocess.call([opener, path])

class Mesh:

    def check_open_bondary(mesh:bpy.types.Object) -> bool:
        """检查是否存在开放边"""
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        check_result = False
        for edge in bm.edges:
            if edge.is_boundary:
                check_result = True
                break
        bm.clear()
        bm.free()

        return check_result
    
    def clean_lonely_verts(mesh:bpy.types.Object) -> None:
        """清理孤立顶点"""
        lonely_verts_list = []
        if mesh.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        for vertex in bm.verts:  # 遍历顶点，如果顶点不隐藏且连接边数为2，添加到删除列表
            if vertex.hide is False and len(vertex.link_edges) == 2:
                lonely_verts_list.append(vertex)

        bmesh.ops.dissolve_verts(
            bm, verts=lonely_verts_list, use_face_split=False, use_boundary_tear=False
        )

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()


    def clean_mid_verts(mesh:bpy.types.Object) -> None:
        """清理直线中的孤立顶点"""
        mid_verts_list = []

        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        # bm.verts.ensure_lookup_table()
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


    def clean_loose_verts(mesh:bpy.types.Object) -> None:
        """清理松散顶点"""
        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)
        # verts with no linked faces
        verts = [v for v in bm.verts if not v.link_faces]
        for vert in verts:
            bm.verts.remove(vert)

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()


    def merge_verts_by_distance(mesh:bpy.types.Object, merge_distance:float=0.01) -> None:
        """清理重复顶点"""
        bm = bmesh.new()
        mesh = mesh.data
        bm.from_mesh(mesh)

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

        bm.to_mesh(mesh)
        mesh.update()
        bm.clear()
        bm.free()

    def merge_verts_ops(meshes:list) -> None:
        for obj in bpy.data.objects:
            obj.select_set(False)
        
        for mesh in meshes:
            mesh.select_set(True)

        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001,use_unselected=True,use_sharp_edge_from_normals=True)
        bpy.ops.object.mode_set(mode="OBJECT")

class Modifier:
    def add_triangulate(mesh):
        """添加Triangulate Modifier"""
        if TRIANGULAR_MODIFIER in mesh.modifiers:
            triangulate_modifier = mesh.modifiers[TRIANGULAR_MODIFIER]

        else:
            triangulate_modifier = mesh.modifiers.new(
                name=TRIANGULAR_MODIFIER, type="TRIANGULATE"
            )

        # if BL_VERSION<4.2:
        triangulate_modifier.keep_custom_normals = True
        triangulate_modifier.min_vertices = 4
        triangulate_modifier.quad_method = "SHORTEST_DIAGONAL"
        return triangulate_modifier

    def add_geometrynode(mesh,modifier_name,node):
        """添加Geometry Nodes WearMask Modifier"""

        check_modifier = False

        for modifier in mesh.modifiers:
            if modifier.name == modifier_name:
                check_modifier = True
                break

        if check_modifier is False:
            geo_node_modifier = mesh.modifiers.new(
                name=modifier_name, type="NODES"
            )
            # geo_node_modifier.node_group = bpy.data.node_groups[node.name]
            geo_node_modifier.node_group = node
        else:
            geo_node_modifier = mesh.modifiers[modifier_name]
            geo_node_modifier.node_group = node
        return geo_node_modifier

    def remove(object, modifier_name: str, has_subobject: bool = False):
        """删除某个modifier,返回modifier对应的子object"""

        modifier_objects = []
        # bad_modifier_objects=[]
        if object.modifiers:
            for modifier in object.modifiers:
                if modifier is not None:
                    if modifier.name == modifier_name:
                        # 如果修改器parent是当前物体并且不为空，把修改器对应的物体添加到删除列表
                        if has_subobject is True and modifier.object is not None:
                            if modifier.object not in modifier_objects:
                                modifier_objects.append(modifier.object)
                        object.modifiers.remove(modifier)

        if len(modifier_objects) > 0:
            for modifier_object in modifier_objects:
                to_remove=True
                # parent_name=modifier_object.name.removeprefix(TRANSFERPROXY_PREFIX)
                # if modifier_object.parent:
                #     if modifier_object.parent.name == parent_name:
                #         to_remove=True
                # else:
                #     to_remove=True

                if to_remove is True:
                    old_mesh = modifier_object.data
                    old_mesh.name = "OldTP_" + old_mesh.name
                    bpy.data.objects.remove(modifier_object)
                    bpy.data.meshes.remove(old_mesh)



    def move_to_bottom(object,modifier_name):
        target_modifier = object.modifiers[modifier_name]
        modifier_count=len(object.modifiers)-1

        while object.modifiers[modifier_count] != target_modifier:
            bpy.ops.object.modifier_move_down(modifier=target_modifier.name)

    def move_to_top(object,modifier_name):
        target_modifier = object.modifiers[modifier_name]
        modifier_count=len(object.modifiers)

        while object.modifiers[0] != target_modifier:
            bpy.ops.object.modifier_move_up(modifier=target_modifier.name)