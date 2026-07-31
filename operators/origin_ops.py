# -*- coding: utf-8 -*-
"""
Origin 和 Socket 管理 Operators
==============================

包含 Asset Origin 添加、批量管理、Snap Socket 创建等功能。
"""

import bpy
import json
from mathutils import Vector
from ..const import *
from ..functions.common_functions import *


def find_objs_bb_center(objs) -> Vector:
    """
    计算所有对象边界框的中心点

    Args:
        objs: 对象列表

    Returns:
        中心点 Vector
    """
    all_coords = []
    for o in objs:
        bb = o.bound_box
        mat = o.matrix_world
        for vert in bb:
            coord = mat @ Vector(vert)
            all_coords.append(coord)

    if not all_coords:
        return Vector((0, 0, 0))

    center = sum(all_coords, Vector((0, 0, 0))) / len(all_coords)
    return center


def find_objs_bb_lowest_center(objs) -> Vector:
    """
    计算所有对象边界框的最低点中心

    Args:
        objs: 对象列表

    Returns:
        最低点中心 Vector
    """
    all_coords = []
    for o in objs:
        bb = o.bound_box
        mat = o.matrix_world
        for vert in bb:
            coord = mat @ Vector(vert)
            all_coords.append(coord)

    if not all_coords:
        return Vector((0, 0, 0))

    lowest_z = min(coord.z for coord in all_coords)
    center_xy = sum(
        (Vector((coord.x, coord.y, 0)) for coord in all_coords), Vector((0, 0, 0))
    ) / len(all_coords)
    center = Vector((center_xy.x, center_xy.y, lowest_z))
    return center


def find_selected_element_center() -> Vector:
    """
    获取选中元素的中心点
    
    Object Mode: 返回选中对象边界框中心
    Edit Mode: 返回选中顶点的中心
    """
    selected_objects = bpy.context.selected_objects
    if len(selected_objects) == 0:
        return None

    edit_mode_meshes = [
        obj for obj in selected_objects if obj.type == "MESH" and obj.mode == "EDIT"
    ]
    if edit_mode_meshes:
        all_selected_verts = []
        for obj in edit_mode_meshes:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="OBJECT")
            all_selected_verts.extend(
                [obj.matrix_world @ v.co for v in obj.data.vertices if v.select]
            )
        bpy.context.view_layer.objects.active = edit_mode_meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        if not all_selected_verts:
            return None
        center = sum(all_selected_verts, Vector((0, 0, 0))) / len(all_selected_verts)
        return center
    else:
        center = find_objs_bb_center(selected_objects)
        return center


class HST_OT_AddSnapSocket(bpy.types.Operator):
    """添加 UE Modular Snap System 的 Socket"""
    bl_idname = "hst.addsnapsocket"
    bl_label = "Add Snap Socket"
    bl_description = "添加用于UE Modular Snap System的Socket，\
        在编辑模式下使用时，先选中用于Snap的面，会自动创建朝向正确的Socket\
        有多个同名Socket时，编号需使用下划线分割，如SOCKET_SNAP_01，SOCKET_SNAP_02"

    def execute(self, context):
        cursor = bpy.context.scene.cursor
        cursor_current_transform = cursor.matrix.copy()
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params

        if not selected_meshes:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        collection = selected_objects[0].users_collection[0]

        if bpy.context.mode == "EDIT_MESH":
            self.report({"INFO"}, "In edit mode, create socket from selected faces")
            rotation = get_selected_rotation_quat()
            rotation = rotate_quaternion(rotation, -90, "Y")
            bpy.ops.view3d.snap_cursor_to_selected()
            bpy.context.scene.cursor.rotation_mode = "QUATERNION"
            bpy.context.scene.cursor.rotation_quaternion = rotation
            bpy.ops.object.mode_set(mode="OBJECT")
        else:
            bpy.ops.view3d.snap_cursor_to_selected()
            rotation = cursor.rotation_quaternion
            rotation = rotate_quaternion(rotation, 90, "Y")
            bpy.context.scene.cursor.rotation_mode = "QUATERNION"
            bpy.context.scene.cursor.rotation_quaternion = rotation
            self.report({"INFO"}, "In object mode, create socket from selected objects")

        socket_name = SOCKET_PREFIX + text_capitalize(parameters.socket_name)
        socket_object = bpy.data.objects.new(name=SOCKET_PREFIX, object_data=None)
        rename_alt(socket_object, socket_name, num=2)
        socket_object.location = cursor.location
        socket_object.rotation_mode = "QUATERNION"
        socket_object.rotation_quaternion = cursor.rotation_quaternion
        socket_object.empty_display_type = "ARROWS"
        socket_object.empty_display_size = SOCKET_SIZE
        socket_object.show_name = True
        collection.objects.link(socket_object)
        Object.mark_hst_type(socket_object, "SOCKET")

        bpy.context.scene.cursor.matrix = cursor_current_transform

        for object in selected_objects:
            object.select_set(False)
        socket_object.select_set(True)

        return {"FINISHED"}


class HST_OT_AddAssetOrigin(bpy.types.Operator):
    """为 Collection 添加 Asset Origin"""
    bl_idname = "hst.add_asset_origin"
    bl_label = "Add Asset Origin"
    bl_description = "选中Collection中任意模型，为此Collection添加Asset Origin"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        collection = active_object.users_collection[0]
        mesh_objs = [obj for obj in collection.all_objects if obj.type == "MESH"]
        pivots = [obj.matrix_world.translation for obj in mesh_objs]
        all_same = all((pivots[0] - p).length < 1e-6 for p in pivots) if pivots else False

        if all_same and pivots:
            origin_location = pivots[0].copy()
        elif pivots:
            origin_location = sum(pivots, Vector((0, 0, 0))) / len(pivots)
        else:
            origin_location = active_object.location.copy()

        origin_name = ORIGIN_PREFIX + collection.name
        origin_object = bpy.data.objects.new(name=origin_name, object_data=None)
        origin_object.location = origin_location
        origin_object.empty_display_type = "ARROWS"
        origin_object.empty_display_size = 0.4
        origin_object.show_name = True
        origin_object.show_in_front = True
        collection.objects.link(origin_object)
        Object.mark_hst_type(origin_object, "ORIGIN")

        for object in collection.all_objects:
            if object.type == "MESH":
                obj_loc_raw = object.location.copy()
                obj_loc = obj_loc_raw - origin_object.location
                object.parent = origin_object
                object.location = obj_loc
        for object in selected_objects:
            object.select_set(False)
        origin_object.select_set(True)

        return {"FINISHED"}

    def invoke(self, context, event):
        selected_objects = bpy.context.selected_objects
        if not selected_objects:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}
        active_object = bpy.context.active_object
        if not active_object:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
        collection = active_object.users_collection[0]
        existing_origin_objects = Object.filter_hst_type(
            objects=collection.all_objects, type="ORIGIN", mode="INCLUDE"
        )
        if existing_origin_objects is not None and len(existing_origin_objects) > 0:
            existing_origin_objects[0].name = ORIGIN_PREFIX + collection.name
            self.report({"INFO"}, "Asset Origin already exists")
            return {"CANCELLED"}
        mesh_objs = [obj for obj in collection.all_objects if obj.type == "MESH"]
        if not mesh_objs:
            self.report({"ERROR"}, "No mesh objects in collection")
            return {"CANCELLED"}
        pivots = [obj.matrix_world.translation for obj in mesh_objs]
        all_same = all((pivots[0] - p).length < 1e-6 for p in pivots)
        if all_same:
            return self.execute(context)
        else:
            return context.window_manager.invoke_confirm(self, event)


class HST_OT_BatchAddAssetOrigin(bpy.types.Operator):
    """为 Prop Collection 批量添加 Asset Origin"""
    bl_idname = "hst.batch_add_asset_origin"
    bl_label = "Add All Prop Asset Origins"
    bl_description = "为 Prop Collection 添加 Asset Origin"
    bl_options = {"REGISTER", "UNDO"}

    origin_mode: bpy.props.EnumProperty(
        name="Origin Mode",
        description="选择 Origin 的位置",
        items=[
            ("WORLD_CENTER", "World Center", "使用世界中心作为 Origin"),
            ("COLLECTION_CENTER", "Collection Pivots Center", "使用 Collection 所有 Mesh Pivots 的中心"),
            ("ACTIVE_BOUNDS_CENTER", "Active Object Bounds Center", "使用首次 Active Object 的 Bounding Box 世界中心"),
        ],
        default="COLLECTION_CENTER",
    )
    parent_objects_to_origin: bpy.props.BoolProperty(
        name="Parent Objects to Origin",
        description="将 Prop Collection 中的 Mesh 设为 Origin 的 Child；关闭时仅添加 Origin",
        default=True,
    )
    active_bounds_source_name: bpy.props.StringProperty(
        name="Active Bounds Source",
        description="首次调用时锁定的 Active Object",
        default="",
        options={"HIDDEN"},
    )
    active_bounds_collection_name: bpy.props.StringProperty(
        name="Active Bounds Collection",
        description="首次调用时锁定的 Prop Collection",
        default="",
        options={"HIDDEN"},
    )
    active_bounds_center: bpy.props.FloatVectorProperty(
        name="Active Bounds Center",
        description="首次调用时锁定的 Active Object Bounding Box 世界中心",
        size=3,
        default=(0.0, 0.0, 0.0),
        options={"HIDDEN"},
    )
    active_bounds_snapshot_valid: bpy.props.BoolProperty(
        name="Active Bounds Snapshot Valid",
        description="Adjust Last Operation 是否已有可复用的 Active Object 快照",
        default=False,
        options={"HIDDEN"},
    )
    created_origin_collection_names: bpy.props.StringProperty(
        name="Created Origin Collections",
        description="本次 Operator 创建过 Origin 的 Collection，用于安全重做",
        default="[]",
        options={"HIDDEN"},
    )

    # 清空 Blender 从上一次独立调用恢复的隐藏状态；Adjust Last Operation 只调用 execute，不受影响。
    # 参数:
    #     无；仅重置当前 Operator 实例的新调用状态。
    def _reset_run_state(self):
        self.active_bounds_source_name = ""
        self.active_bounds_collection_name = ""
        self.active_bounds_center = (0.0, 0.0, 0.0)
        self.active_bounds_snapshot_valid = False
        self.created_origin_collection_names = "[]"
    # 返回锁定源 Object 所直接归属的 Prop Collection。
    # 参数:
    #     active_object: 首次调用时锁定的 Blender Object。
    def _get_active_object_prop_collections(self, active_object):
        if active_object is None or active_object.type != "MESH":
            return []
        return [
            collection
            for collection in active_object.users_collection
            if Collection.get_hst_type(collection) == "PROP"
        ]

    # 首次调用时保存 Active Mesh 的 Bounds 中心和唯一 Prop Collection。
    # 参数:
    #     context: 当前 Blender Context，只在首次调用时读取 Active Object。
    def _capture_active_bounds_snapshot(self, context):
        if self.active_bounds_snapshot_valid:
            return

        active_object = context.active_object
        if active_object is None or active_object.type != "MESH":
            return
        prop_collections = self._get_active_object_prop_collections(active_object)
        if len(prop_collections) != 1:
            return

        self.active_bounds_source_name = active_object.name
        self.active_bounds_collection_name = prop_collections[0].name
        self.active_bounds_center = find_objs_bb_center([active_object])
        self.active_bounds_snapshot_valid = True

    # 返回本次 Operator 已创建过 Origin 的 Collection 名称集合。
    # 参数:
    #     无；数据来自隐藏 Operator 参数。
    def _get_created_origin_collection_names(self):
        return set(json.loads(self.created_origin_collection_names))

    # 记录本次 Operator 新创建 Origin 的 Collection。
    # 参数:
    #     collection: 新建 Origin 所属的 Blender Collection。
    def _mark_origin_created(self, collection):
        collection_names = self._get_created_origin_collection_names()
        collection_names.add(collection.name)
        self.created_origin_collection_names = json.dumps(sorted(collection_names))

    # 判断已有 Origin 是否属于本次 Operator 的重做结果。
    # 参数:
    #     collection: 待判断的 Blender Collection。
    def _was_origin_created_by_this_run(self, collection):
        return collection.name in self._get_created_origin_collection_names()

    # 返回本次需要处理的 Prop Collection。
    # 参数:
    #     context: 当前 Blender Context，仅在快照尚未建立时读取。
    def _get_target_collections(self, context):
        if self.origin_mode != "ACTIVE_BOUNDS_CENTER":
            return Collection.filter_hst_type(
                collections=bpy.data.collections, type="PROP", mode="INCLUDE"
            ) or []

        self._capture_active_bounds_snapshot(context)
        if not self.active_bounds_snapshot_valid:
            self.report({"ERROR"}, "Active Object must be a Mesh in exactly one Prop Collection")
            return []

        target_collection = bpy.data.collections.get(self.active_bounds_collection_name)
        if target_collection is None or Collection.get_hst_type(target_collection) != "PROP":
            self.report({"ERROR"}, "Saved Active Object Prop Collection is no longer available")
            return []
        return [target_collection]

    # 根据选定模式计算新 Origin 的世界位置。
    # 参数:
    #     context: 当前 Blender Context，仅在快照尚未建立时读取。
    #     mesh_objects: 当前 Prop Collection 内用于计算中心的 Mesh 列表。
    def _get_origin_location(self, context, mesh_objects):
        if self.origin_mode == "WORLD_CENTER":
            return Vector((0.0, 0.0, 0.0))
        if self.origin_mode == "ACTIVE_BOUNDS_CENTER":
            self._capture_active_bounds_snapshot(context)
            return Vector(self.active_bounds_center)

        pivots = [obj.matrix_world.translation for obj in mesh_objects]
        return (
            sum(pivots, Vector((0.0, 0.0, 0.0))) / len(pivots)
            if pivots
            else Vector((0.0, 0.0, 0.0))
        )

    # 将尚未归属当前 Origin 的 Mesh 设为 Child，同时保持世界变换不变。
    # 参数:
    #     mesh_objects: 当前 Prop Collection 内的 Mesh 列表。
    #     origin_object: 作为 Parent 的 Asset Origin。
    def _parent_mesh_objects(self, mesh_objects, origin_object):
        for obj in mesh_objects:
            if obj.parent == origin_object:
                continue
            original_world_matrix = obj.matrix_world.copy()
            obj.parent = origin_object
            obj.matrix_world = original_world_matrix

    def execute(self, context):
        self._capture_active_bounds_snapshot(context)
        prop_collections = self._get_target_collections(context)
        if not prop_collections:
            return {"CANCELLED"}

        is_local_view = Viewport.is_local_view()
        store_mode = prep_select_mode()
        selected_objects = Object.get_selected()
        new_origins_count = 0
        skipped_origins_count = 0

        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)

        for collection in prop_collections:
            direct_objects = list(collection.objects)
            mesh_objects = [obj for obj in collection.objects if obj.type == "MESH"]
            if not mesh_objects:
                continue

            existing_origin_objects = Object.filter_hst_type(
                objects=direct_objects, type="ORIGIN", mode="INCLUDE"
            ) or []
            if existing_origin_objects:
                origin_object = existing_origin_objects[0]
                origin_object.name = ORIGIN_PREFIX + collection.name
                origin_object.empty_display_type = "ARROWS"
                origin_object.show_in_front = True
                if self._was_origin_created_by_this_run(collection):
                    origin_object.location = self._get_origin_location(context, mesh_objects)
                else:
                    skipped_origins_count += 1
                    self.report({"INFO"}, f"{collection.name} already has Asset Origin")
                if self.parent_objects_to_origin:
                    self._parent_mesh_objects(mesh_objects, origin_object)
                continue

            origin_object = bpy.data.objects.new(
                name=ORIGIN_PREFIX + collection.name,
                object_data=None,
            )
            origin_object.location = self._get_origin_location(context, mesh_objects)
            origin_object.empty_display_type = "ARROWS"
            origin_object.empty_display_size = 0.4
            origin_object.show_name = True
            origin_object.show_in_front = True
            collection.objects.link(origin_object)
            Object.mark_hst_type(origin_object, "ORIGIN")
            self._mark_origin_created(collection)
            new_origins_count += 1

            if self.parent_objects_to_origin:
                if is_local_view:
                    bpy.ops.view3d.localview(frame_selected=False)
                    is_local_view = False
                self._parent_mesh_objects(mesh_objects, origin_object)

        restore_select_mode(store_mode)
        self.report(
            {"INFO"},
            f"Added {new_origins_count} Asset Origins; skipped {skipped_origins_count} existing",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        self._reset_run_state()
        self._capture_active_bounds_snapshot(context)
        prop_collections = self._get_target_collections(context)
        if not prop_collections:
            if self.origin_mode != "ACTIVE_BOUNDS_CENTER":
                self.report({"ERROR"}, "No Prop Collections, mark prop collections with 'Mark Prop' first")
            return {"CANCELLED"}

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()
        box_column.label(text="Choose Origin Location")
        box_column.prop(self, "origin_mode", expand=True)
        box_column.prop(self, "parent_objects_to_origin")
