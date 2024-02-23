import bpy
import bmesh
import math
from mathutils import Vector, Matrix, Quaternion, Euler, Color, geometry
from ..Const import *

""" 通用functions """


def message_box(text="", title="WARNING", icon="ERROR") -> None:
    """弹出消息框"""

    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def rename_meshes(target_objects, new_name) -> None:
    """重命名mesh"""
    for index, object in enumerate(target_objects):
        if object.type == "MESH":  # 检测对象是否为mesh
            object.name = new_name + "_" + str(index + 1).zfill(3)


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
    if target_object.type == "MESH":
        if vertexcolor_name in target_object.data.color_attributes:
            color_attribute = target_object.data.color_attributes.get(vertexcolor_name)
            target_object.data.attributes.active_color = color_attribute
        else:
            print("No vertex color attribute named " + vertexcolor_name)
    else:
        print(target_object + " is not mesh object")


def set_object_vertexcolor(target_object, color: tuple, vertexcolor_name: str) -> None:
    """设置顶点色"""
    color = tuple(color)
    if target_object.type == "MESH":
        mesh = target_object.data
        if vertexcolor_name in mesh.color_attributes:
            color_attribute = mesh.color_attributes.get(vertexcolor_name)
            color_attribute.data.foreach_set("color_srgb", color * len(mesh.loops) * 4)
        else:
            print("No vertex color attribute named " + vertexcolor_name)
    else:
        print(target_object + " is not mesh object")


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

        proxy_mesh = apply_modifiers(proxy_mesh)

    proxy_mesh.hide_viewport = True
    proxy_mesh.hide_render = True
    proxy_mesh.select_set(False)
    return proxy_mesh


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


def clean_lonely_verts(mesh) -> None:
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


def clean_mid_verts(mesh) -> None:
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


def clean_loose_verts(mesh) -> None:
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


def merge_vertes_by_distance(mesh, merge_distance=0.01) -> None:
    """清理重复顶点"""
    bm = bmesh.new()
    mesh = mesh.data
    bm.from_mesh(mesh)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

    bm.to_mesh(mesh)
    mesh.update()
    bm.clear()
    bm.free()


def mark_sharp_edge_by_angle(mesh, sharp_angle=0.08) -> None:
    """根据角度标记锐边"""
    bm = bmesh.new()
    mesh = mesh.data
    to_mark_sharp = []
    has_sharp_edge = False

    bm.from_mesh(mesh)

    for edge in bm.edges:  # get sharp edge index by angle
        if edge.calc_face_angle() >= sharp_angle:
            to_mark_sharp.append(edge.index)

    for attributes in mesh.attributes:  # add sharp edge attribute
        if "sharp_edge" in attributes.name:
            has_sharp_edge = True
            break

    if has_sharp_edge is False:  # if no sharp edge attribute, add it
        mesh.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")

    for edge in mesh.edges:  # mark sharp edge
        if edge.index in to_mark_sharp:
            edge.use_edge_sharp = True
        else:
            edge.use_edge_sharp = False

    bm.to_mesh(mesh)
    mesh.update()
    bm.clear()
    bm.free()


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
            print("viewport_context")
        case "ALL":
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == area_type:
                        for space in area.spaces:
                            if space.type == area_type:
                                viewport_spaces.append(space)
            print("viewport_all")
    print(viewport_spaces)

    for viewport_space in viewport_spaces:
        viewport_space.shading.type = shading_type

    return viewport_spaces


def apply_transfrom(object, location=True, rotation=True, scale=True):
    """应用变换"""

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
        method=method, fill_holes=True, correct_aspect=correct_aspect, margin=margin
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
    name_exist = False
    for object in bpy.data.objects:
        if object.name == new_name:
            name_exist = True
            break

    if name_exist is True:
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

    elif name_exist is False:
        new_new_name = new_name
    print(new_new_name)

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
    output = "".join(x for x in text.title() if x.isalnum())
    return output

def clean_collection_name(collection_name:str)->str:
    """清理collection名字"""
    clean_name = collection_name.replace(".", "").replace(" ", "").split(LOW_SUFFIX)[0].split(HIGH_SUFFIX)[0]
    return clean_name