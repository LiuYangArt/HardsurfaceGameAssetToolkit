# -*- coding: utf-8 -*-
"""
Origin 和 Socket 管理 Operators
==============================

包含 Asset Origin 添加、批量管理、Snap Socket 创建等功能。
"""

import bpy
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

        if selected_meshes is None:
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
        origin_object.empty_display_type = "PLAIN_AXES"
        origin_object.empty_display_size = 0.4
        origin_object.show_name = True
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
    """为所有 Prop Collection 批量添加 Asset Origin"""
    bl_idname = "hst.batch_add_asset_origin"
    bl_label = "Add All Prop Asset Origins"
    bl_description = "为所有Prop Collection添加Asset Origin"
    bl_options = {"REGISTER", "UNDO"}

    origin_mode: bpy.props.EnumProperty(
        name="Origin Mode",
        description="选择Origin的位置",
        items=[
            ("WORLD_CENTER", "World Center", "使用世界中心作为Origin"),
            ("COLLECTION_CENTER", "Collection Pivots Center", "使用Collection所有对象Pivots的中心"),
        ],
        default="COLLECTION_CENTER",
    )

    def execute(self, context):
        is_local_view = Viewport.is_local_view()
        new_origins_count = 0
        store_mode = prep_select_mode()
        selected_objects = Object.get_selected()

        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)

        prop_collections = Collection.filter_hst_type(
            collections=bpy.data.collections, type="PROP", mode="INCLUDE"
        )
        if prop_collections is None:
            self.report({"ERROR"}, "No Prop Collections, mark prop collections with 'Mark Prop' first")
            return {"CANCELLED"}

        for collection in prop_collections:
            collection_objs = [obj for obj in collection.all_objects]
            if not collection_objs:
                continue

            existing_origin_objects = Object.filter_hst_type(
                objects=collection_objs, type="ORIGIN", mode="INCLUDE"
            )

            asset_objs = []
            if existing_origin_objects:  # 处理 None 和空列表
                for obj in collection_objs:
                    if obj not in existing_origin_objects:
                        asset_objs.append(obj)
            else:
                asset_objs = collection_objs

            pivots = [obj.matrix_world.translation for obj in asset_objs if obj.type == "MESH"]

            if existing_origin_objects:  # 处理 None 和空列表
                new_asset_objs = []
                for obj in asset_objs:
                    if obj.parent is None:
                        new_asset_objs.append(obj)
                    else:
                        if obj.parent != existing_origin_objects[0]:
                            new_asset_objs.append(obj)
                asset_objs = new_asset_objs
                existing_origin_objects[0].name = ORIGIN_PREFIX + collection.name
                origin_object = existing_origin_objects[0]
                self.report({"INFO"}, f"{collection.name} has Asset Origin already")
            else:
                origin_name = ORIGIN_PREFIX + collection.name
                origin_object = bpy.data.objects.new(name=origin_name, object_data=None)

                if self.origin_mode == "COLLECTION_CENTER":
                    origin_location = (
                        sum(pivots, Vector((0, 0, 0))) / len(pivots) if pivots else Vector((0, 0, 0))
                    )
                elif self.origin_mode == "WORLD_CENTER":
                    origin_location = Vector((0, 0, 0))

                origin_object.location = origin_location
                origin_object.empty_display_type = "PLAIN_AXES"
                origin_object.empty_display_size = 0.4
                origin_object.show_name = True
                collection.objects.link(origin_object)
                Object.mark_hst_type(origin_object, "ORIGIN")
                new_origins_count += 1

            for object in asset_objs:
                if is_local_view:
                    bpy.ops.view3d.localview(frame_selected=False)
                if object.type == "MESH":
                    obj_loc_raw = object.location.copy()
                    obj_loc = obj_loc_raw - origin_object.location
                    object.parent = origin_object
                    object.location = obj_loc

        restore_select_mode(store_mode)
        self.report({"INFO"}, f"Added {new_origins_count} Asset Origins")

        return {"FINISHED"}

    def invoke(self, context, event):
        prop_collections = Collection.filter_hst_type(
            collections=bpy.data.collections, type="PROP", mode="INCLUDE"
        )
        if prop_collections is None:
            self.report({"ERROR"}, "No Prop Collections, mark prop collections with 'Mark Prop' first")
            return {"CANCELLED"}

        all_has_origin = True
        for collection in prop_collections:
            collection_objs = [obj for obj in collection.objects]
            existing_origin_objects = Object.filter_hst_type(
                objects=collection_objs, type="ORIGIN", mode="INCLUDE"
            )
            if not existing_origin_objects:
                all_has_origin = False
                break

        if all_has_origin:
            self.report({"INFO"}, "All prop collections already have Asset Origin")
            return {"CANCELLED"}

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box_column = box.column()
        box_column.label(text="Choose Origin Location")
        box_column.prop(self, "origin_mode", expand=True)
