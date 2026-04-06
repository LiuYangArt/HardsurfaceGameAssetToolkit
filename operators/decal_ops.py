# -*- coding: utf-8 -*-
"""
Decal Collection 操作 Operators
==============================

包含 Decal Collection 创建和管理相关的操作。
"""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector
from uuid import uuid4
from ..const import *
from ..functions.common_functions import *
from ..utils.image_utils import find_alpha_regions, get_linked_image_texture_node

ALPHA_RECT_BATCH_PROP = "hst_alpha_rect_batch"
ALPHA_RECT_SOURCE_PROP = "hst_alpha_rect_source"


class HST_OT_ActiveCollection(bpy.types.Operator):
    """把所选物体所在的 Collection 设为 Active"""
    bl_idname = "hst.active_current_collection"
    bl_label = "Active Collection"
    bl_description = "把所选物体所在的Collection设为Active"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        outliner_coll = Outliner.get_selected_collections()
        if outliner_coll is None:
            if len(selected_objects) == 0:
                self.report(
                    {"ERROR"},
                    "No selected object, please select objects and retry | \n"
                    + "没有选中物体，请选中物体后重试",
                )
                return {"CANCELLED"}
            collection = get_collection(selected_objects[0])
            if collection is None:
                self.report(
                    {"ERROR"},
                    "Not in Collection | \n" + "所选物体不在Collection中",
                )
                return {"CANCELLED"}
            if collection is not None:
                Collection.active(collection)
        else:
            Collection.active(outliner_coll[0])

        return {"FINISHED"}


class HST_OT_MakeDecalCollection(bpy.types.Operator):
    """为 Prop 加对应的 Decal Collection"""
    bl_idname = "hst.make_decal_collection"
    bl_label = "Make Decal Collection"
    bl_description = "为Prop加对应的Decal Collection"

    def execute(self, context):
        target_collections = Collection.get_selected()
        if not target_collections:
            self.report(
                {"ERROR"},
                "No collection selected | \n" + "没有选中的Collection",
            )
            return {"CANCELLED"}

        selected_objects = Object.get_selected()
        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)

        for collection in target_collections:
            decal_collection = None
            current_state = None
            remove_exist_collection = False
            count_exist = 0
            count_create = 0
            origin_object = None

            # check selected collection's state:
            collection_type = Collection.get_hst_type(collection)
            parent_collection = Collection.find_parent_recur_by_type(
                collection, type=Const.TYPE_PROP_COLLECTION
            )
            if parent_collection:
                origin_objects = Object.filter_hst_type(
                    objects=parent_collection.objects, type="ORIGIN", mode="INCLUDE"
                )
                origin_object_name = Const.STATICMESH_PREFIX + parent_collection.name
            else:
                origin_objects = Object.filter_hst_type(
                    objects=collection.objects, type="ORIGIN", mode="INCLUDE"
                )
                origin_object_name = Const.STATICMESH_PREFIX + collection.name
            if origin_objects:
                origin_object = origin_objects[0]
                origin_object.name = origin_object_name

            match collection_type:
                case None:
                    if parent_collection:
                        current_state = "subobject_collection"
                    else:
                        current_state = "root_decal_collection"
                        self.report(
                            {"ERROR"},
                            f"{collection.name} is not prop collection, please check",
                        )
                        return {"CANCELLED"}

                case Const.TYPE_DECAL_COLLECTION:
                    if parent_collection:
                        current_state = "decal_collection"
                    else:
                        current_state = "root_decal_collection"
                        continue
                case Const.TYPE_PROP_COLLECTION:
                    if parent_collection:
                        self.report(
                            {"ERROR"},
                            f"{collection.name} is prop collection in prop collection, please check",
                        )
                        return {"CANCELLED"}
                    else:
                        if collection.children:
                            for child_collection in collection.children:
                                child_type = Collection.get_hst_type(child_collection)
                                if child_type == Const.TYPE_DECAL_COLLECTION:
                                    current_state = "prop_collection"
                        else:
                            current_state = "prop_collection_raw"
                case _:
                    self.report(
                        {"ERROR"},
                        f"{collection.name} has bad collection type, please check",
                    )
                    return {"CANCELLED"}

            match current_state:
                case "subobject_collection":
                    if parent_collection.children:
                        for child_collection in parent_collection.children:
                            child_type = Collection.get_hst_type(child_collection)
                            if child_type == Const.TYPE_DECAL_COLLECTION:
                                decal_collection = child_collection
                                break
                    decal_meshes = Object.filter_hst_type(
                        objects=parent_collection.all_objects,
                        type="DECAL",
                        mode="INCLUDE",
                    )
                    decal_collection_name = parent_collection.name + DECAL_SUFFIX

                case "prop_collection":
                    decal_collection = child_collection
                    decal_meshes = Object.filter_hst_type(
                        objects=collection.all_objects, type="DECAL", mode="INCLUDE"
                    )
                    decal_collection_name = collection.name + DECAL_SUFFIX
                case "prop_collection_raw":
                    decal_collection = None
                    decal_meshes = Object.filter_hst_type(
                        objects=collection.all_objects, type="DECAL", mode="INCLUDE"
                    )
                    decal_collection_name = collection.name + DECAL_SUFFIX
                case "decal_collection":
                    decal_collection = collection
                    decal_meshes = Object.filter_hst_type(
                        objects=parent_collection.all_objects,
                        type="DECAL",
                        mode="INCLUDE",
                    )
                    decal_collection_name = parent_collection.name + DECAL_SUFFIX
                case None:
                    self.report(
                        {"ERROR"},
                        f"{collection.name} has bad collection type, please check",
                    )
                    return {"CANCELLED"}

            for exist_collection in bpy.data.collections:  # collection 命名冲突时
                if (
                    exist_collection.name == decal_collection_name
                    and exist_collection is not decal_collection
                ):
                    file_c_parent = Collection.find_parent_recur_by_type(
                        exist_collection, type=Const.TYPE_PROP_COLLECTION
                    )
                    if file_c_parent:  # 有parent 时根据parent命名
                        exist_collection.name = file_c_parent.name + DECAL_SUFFIX
                    else:  # 无parent时删除并把包含的decal移入当前collection
                        ex_decal_meshes = Object.filter_hst_type(
                            objects=exist_collection.all_objects,
                            type="DECAL",
                            mode="INCLUDE",
                        )
                        if ex_decal_meshes:
                            if decal_meshes:
                                decal_meshes.extend(ex_decal_meshes)
                            else:
                                decal_meshes = ex_decal_meshes
                        exist_collection.name = "to_remove_" + exist_collection.name
                        remove_exist_collection = True
                    break

            if decal_collection:  # 修改命名
                decal_collection.name = decal_collection_name
                count_exist += 1

            elif decal_collection is None:  # 新建Decal Collection
                decal_collection = Collection.create(
                    name=decal_collection_name, type="DECAL"
                )
                collection.children.link(decal_collection)
                bpy.context.scene.collection.children.unlink(decal_collection)
                count_create += 1

            decal_collection.hide_render = True
            Collection.active(decal_collection)

            if decal_meshes:  # 将Decal添加到Decal Collection
                for decal_mesh in decal_meshes:
                    decal_mesh.users_collection[0].objects.unlink(decal_mesh)
                    decal_collection.objects.link(decal_mesh)
                    Transform.apply_scale(decal_mesh)
                    decal_mesh = Object.break_link_from_assetlib(decal_mesh)

                    if origin_object:
                        decal_mesh.select_set(True)
                        origin_object.select_set(True)
                        bpy.context.view_layer.objects.active = origin_object
                        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
                        decal_mesh.select_set(False)
                        origin_object.select_set(False)

            if remove_exist_collection:  # 删除重复Collection
                bpy.data.collections.remove(exist_collection)

            self.report(
                {"INFO"},
                f"{count_exist} Decal Collection(s) updated, {count_create} Decal Collection(s) created",
            )

        return {"FINISHED"}


def _get_plane_corner_map(source_object: bpy.types.Object, uv_tolerance: float = 0.01):
    """
    读取单 quad plane 的 UV 角点映射。

    仅支持 UV 覆盖完整 [0, 1] 区间的严格输入。
    """
    mesh = source_object.data
    if len(mesh.polygons) != 1 or len(mesh.vertices) != 4:
        raise ValueError("Source mesh must be a single quad plane")

    polygon = mesh.polygons[0]
    if polygon.loop_total != 4:
        raise ValueError("Source mesh polygon must have exactly 4 corners")

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise ValueError("Source mesh must have an active UV layer")

    loop_entries = []
    for loop_index in polygon.loop_indices:
        loop = mesh.loops[loop_index]
        uv = Vector(uv_layer.data[loop_index].uv)
        co = mesh.vertices[loop.vertex_index].co.copy()
        loop_entries.append({"uv": uv, "co": co})

    targets = {
        "ll": Vector((0.0, 0.0)),
        "lr": Vector((1.0, 0.0)),
        "ur": Vector((1.0, 1.0)),
        "ul": Vector((0.0, 1.0)),
    }
    corner_map = {}
    used_indices = set()

    for key, target_uv in targets.items():
        best_index = None
        best_distance = None
        for index, entry in enumerate(loop_entries):
            if index in used_indices:
                continue
            distance = (entry["uv"] - target_uv).length
            if best_distance is None or distance < best_distance:
                best_index = index
                best_distance = distance

        if best_index is None or best_distance is None or best_distance > uv_tolerance:
            raise ValueError("Source mesh UV must fill the full 0-1 range on a single quad")

        used_indices.add(best_index)
        corner_map[key] = loop_entries[best_index]["co"]

    return corner_map, uv_layer.name


def _local_point_from_uv(corner_map, u: float, v: float) -> Vector:
    """将 0-1 UV 坐标映射到 source plane 的局部坐标。"""
    lower_edge = corner_map["ll"].lerp(corner_map["lr"], u)
    upper_edge = corner_map["ul"].lerp(corner_map["ur"], u)
    return lower_edge.lerp(upper_edge, v)


def _bbox_to_uv_bounds(region: dict, image_width: int, image_height: int) -> tuple[float, float, float, float]:
    """把像素包围盒换算成 UV 边界。"""
    u0 = region["min_x"] / image_width
    u1 = (region["max_x"] + 1) / image_width
    v0 = region["min_y"] / image_height
    v1 = (region["max_y"] + 1) / image_height
    return u0, v0, u1, v1


def _create_rect_object(
    source_object: bpy.types.Object,
    output_collection: bpy.types.Collection,
    target_material: bpy.types.Material,
    uv_layer_name: str,
    object_name: str,
    corner_map,
    region: dict,
    image_width: int,
    image_height: int,
):
    """基于一个 alpha 矩形区域创建新的 quad 物体。"""
    u0, v0, u1, v1 = _bbox_to_uv_bounds(region, image_width, image_height)

    local_ll = _local_point_from_uv(corner_map, u0, v0)
    local_lr = _local_point_from_uv(corner_map, u1, v0)
    local_ur = _local_point_from_uv(corner_map, u1, v1)
    local_ul = _local_point_from_uv(corner_map, u0, v1)
    center_local = (local_ll + local_lr + local_ur + local_ul) / 4.0

    local_vertices = [
        local_ll - center_local,
        local_lr - center_local,
        local_ur - center_local,
        local_ul - center_local,
    ]

    mesh_data = bpy.data.meshes.new(object_name)
    mesh_data.from_pydata(local_vertices, [], [(0, 1, 2, 3)])
    mesh_data.update()

    if target_material is not None:
        mesh_data.materials.append(target_material)

    uv_layer = mesh_data.uv_layers.new(name=uv_layer_name)
    uv_data = (
        (u0, v0),
        (u1, v0),
        (u1, v1),
        (u0, v1),
    )
    for loop_index, uv in zip(mesh_data.polygons[0].loop_indices, uv_data):
        uv_layer.data[loop_index].uv = uv
    uv_layer.active = True

    rect_object = bpy.data.objects.new(object_name, mesh_data)
    rect_object.matrix_world = source_object.matrix_world @ Matrix.Translation(center_local)
    output_collection.objects.link(rect_object)
    Object.mark_hst_type(rect_object, "DECAL")
    return rect_object


def _ensure_object_mode(context) -> None:
    """保证当前处于对象模式。"""
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _get_valid_source_object(context):
    """校验并返回当前唯一合法的源 plane。"""
    source_object = context.active_object
    selected_objects = context.selected_objects

    if source_object is None or source_object.type != "MESH":
        raise ValueError("Active object must be a mesh plane")

    if len(selected_objects) != 1 or source_object not in selected_objects:
        raise ValueError("Select exactly one source plane object")

    return source_object


def _get_output_collection(source_object: bpy.types.Object) -> bpy.types.Collection:
    """获取生成 decal 的目标 collection。"""
    if source_object.users_collection:
        return source_object.users_collection[0]
    return bpy.context.scene.collection


def _remove_previous_batch_objects(
    output_collection: bpy.types.Collection,
    batch_id: str,
) -> None:
    """删除当前 batch 上一轮生成的对象，供 redo 使用。"""
    batch_objects = [
        obj
        for obj in output_collection.objects
        if obj.get(ALPHA_RECT_BATCH_PROP) == batch_id
    ]
    for obj in batch_objects:
        mesh_data = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh_data is not None and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)


def _set_source_visibility(source_object: bpy.types.Object, hidden: bool) -> None:
    """根据参数切换源 plane 显示状态。"""
    source_object.hide_set(hidden)
    source_object.hide_render = hidden


class HST_OT_SplitTrimsheetAlphaRects(bpy.types.Operator):
    """根据 alpha 连通域把 plane atlas 拆成独立矩形片"""

    bl_idname = "hst.split_trimsheet_alpha_rects"
    bl_label = "Split Alpha Rects"
    bl_description = (
        "选中一个带 alpha atlas 材质的单 quad plane，"
        "根据透明区域自动生成独立矩形 decal mesh"
    )
    bl_options = {"REGISTER", "UNDO"}

    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        description="alpha 大于此阈值的像素会被视为实体区域",
        default=0.1,
        min=0.0,
        max=1.0,
    )

    min_region_pixels: IntProperty(
        name="Min Region Pixels",
        description="小于该像素数量的连通域会被忽略",
        default=16,
        min=1,
        max=65535,
    )

    padding_pixels: IntProperty(
        name="Padding Pixels",
        description="给每个矩形包围盒向外扩展的像素数",
        default=1,
        min=0,
        max=64,
    )

    merge_gap_pixels: IntProperty(
        name="Merge Gap Pixels",
        description="把相距不超过该像素的碎小矩形合并成更大的矩形块",
        default=8,
        min=0,
        max=128,
    )

    hide_source_plane: BoolProperty(
        name="Hide Source Plane",
        description="生成成功后隐藏源 plane",
        default=False,
    )

    source_object_name: StringProperty(
        name="Source Object Name",
        default="",
        options={"HIDDEN"},
    )

    batch_id: StringProperty(
        name="Batch Id",
        default="",
        options={"HIDDEN"},
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        column = box.column()
        column.label(text="Split Alpha Rect Parameters")
        column.prop(self, "alpha_threshold")
        column.prop(self, "min_region_pixels")
        column.prop(self, "padding_pixels")
        column.prop(self, "merge_gap_pixels")
        column.prop(self, "hide_source_plane")

    def invoke(self, context, event):
        _ = event
        _ensure_object_mode(context)
        try:
            source_object = _get_valid_source_object(context)
        except ValueError as error:
            self.report({"ERROR"}, f"{error} | \n{error}")
            return {"CANCELLED"}

        self.source_object_name = source_object.name
        self.batch_id = uuid4().hex
        return self.execute(context)

    def execute(self, context):
        source_object = (
            bpy.data.objects.get(self.source_object_name)
            if self.source_object_name
            else context.active_object
        )

        if source_object is not None and not self.source_object_name:
            self.source_object_name = source_object.name
        if not self.batch_id:
            self.batch_id = uuid4().hex

        _ensure_object_mode(context)

        if source_object is None or source_object.type != "MESH":
            self.report(
                {"ERROR"},
                "Active object must be a mesh plane | \n活动对象必须是一个 Mesh plane",
            )
            return {"CANCELLED"}

        try:
            corner_map, uv_layer_name = _get_plane_corner_map(source_object)
        except ValueError as error:
            self.report({"ERROR"}, f"{error} | \n{error}")
            return {"CANCELLED"}

        target_material = source_object.active_material
        try:
            image_texture_node = get_linked_image_texture_node(target_material)
            analysis = find_alpha_regions(
                image=image_texture_node.image,
                alpha_threshold=self.alpha_threshold,
                min_region_pixels=self.min_region_pixels,
                padding_pixels=self.padding_pixels,
                merge_gap_pixels=self.merge_gap_pixels,
            )
        except ValueError as error:
            self.report({"ERROR"}, f"{error} | \n{error}")
            return {"CANCELLED"}

        regions = analysis["regions"]
        if not regions:
            self.report(
                {"ERROR"},
                "No valid alpha regions found after filtering | \n过滤后没有可生成的 alpha 区域",
            )
            return {"CANCELLED"}

        output_collection = _get_output_collection(source_object)
        _remove_previous_batch_objects(output_collection, self.batch_id)

        created_objects = []
        for index, region in enumerate(regions, start=1):
            object_name = f"{source_object.name}_decal_{str(index).zfill(3)}"
            rect_object = _create_rect_object(
                source_object=source_object,
                output_collection=output_collection,
                target_material=target_material,
                uv_layer_name=uv_layer_name,
                object_name=object_name,
                corner_map=corner_map,
                region=region,
                image_width=analysis["width"],
                image_height=analysis["height"],
            )
            rect_object[ALPHA_RECT_BATCH_PROP] = self.batch_id
            rect_object[ALPHA_RECT_SOURCE_PROP] = source_object.name
            created_objects.append(rect_object)

        bpy.ops.object.select_all(action="DESELECT")
        for obj in created_objects:
            obj.select_set(True)
        context.view_layer.objects.active = created_objects[0]

        _set_source_visibility(source_object, self.hide_source_plane)

        self.report(
            {"INFO"},
            (
                f"Created {len(created_objects)} rect decals, "
                f"ignored {analysis['ignored_small_regions']} small regions, "
                f"merge gap {self.merge_gap_pixels}px, "
                f"alpha>{self.alpha_threshold:.3f}, min pixels {self.min_region_pixels}"
            ),
        )
        return {"FINISHED"}
