# -*- coding: utf-8 -*-
"""
Transform 和工具 Operators
=========================

包含 Transform 操作、场景设置、检查等工具。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *
from ..Functions.AssetCheckFunctions import *


class HST_OT_SnapTransform(bpy.types.Operator):
    """吸附 Transform 到网格"""
    bl_idname = "hst.snap_transform"
    bl_label = "Snap Transform"
    bl_description = "把物体的位置/角度/缩放吸附到格子上"
    bl_options = {'REGISTER', 'UNDO'}

    snap_location_toggle: bpy.props.BoolProperty(name="Snap Location", default=True)
    snap_rotation_toggle: bpy.props.BoolProperty(name="Snap Rotation", default=True)
    snap_scale_toggle: bpy.props.BoolProperty(name="Snap Scale", default=False)

    snap_grid: bpy.props.EnumProperty(
        name="Grid (cm)",
        items=[
            ("100", "100", "100"),
            ("50", "50", "50"),
            ("25", "25", "25"),
            ("10", "10", "10"),
            ("5", "5", "5"),
            ("2.5", "2.5", "2.5"),
            ("1.25", "1.25", "1.25"),
            ("0.625", "0.625", "0.625"),
        ],
        default="5"
    )

    snap_rotation_step: bpy.props.EnumProperty(
        name="Rotation Step",
        items=[
            ("90", "90", "90"),
            ("45", "45", "45"),
            ("22.5", "22.5", "22.5"),
            ("15", "15", "15"),
            ("5", "5", "5"),
            ("1", "1", "1"),
        ],
        default="45"
    )

    snap_scale_step: bpy.props.EnumProperty(
        name="Scale Step",
        items=[
            ("1", "1", "1"),
            ("0.5", "0.5", "0.5"),
            ("0.25", "0.25", "0.25"),
            ("0.125", "0.125", "0.125"),
            ("0.0625", "0.0625", "0.0625"),
        ],
        default="0.125"
    )

    def execute(self, context):
        import math
        selected_objs = Object.get_selected()
        if selected_objs is None:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}

        snap_grid = float(self.snap_grid) * 0.01
        snap_rotation_step = float(self.snap_rotation_step)
        snap_scale_step = float(self.snap_scale_step)

        for obj in selected_objs:
            if self.snap_location_toggle:
                obj.location.x = round(obj.location.x / snap_grid) * snap_grid
                obj.location.y = round(obj.location.y / snap_grid) * snap_grid
                obj.location.z = round(obj.location.z / snap_grid) * snap_grid
            if self.snap_rotation_toggle:
                obj.rotation_euler.x = math.radians(round(math.degrees(obj.rotation_euler.x) / snap_rotation_step) * snap_rotation_step)
                obj.rotation_euler.y = math.radians(round(math.degrees(obj.rotation_euler.y) / snap_rotation_step) * snap_rotation_step)
                obj.rotation_euler.z = math.radians(round(math.degrees(obj.rotation_euler.z) / snap_rotation_step) * snap_rotation_step)
            if self.snap_scale_toggle:
                obj.scale.x = round(obj.scale.x / snap_scale_step) * snap_scale_step
                obj.scale.y = round(obj.scale.y / snap_scale_step) * snap_scale_step
                obj.scale.z = round(obj.scale.z / snap_scale_step) * snap_scale_step

        return {"FINISHED"}

    def invoke(self, context, event):
        selected_objs = Object.get_selected()
        if selected_objs is None or len(selected_objs) == 0:
            return {"CANCELLED"}
        return self.execute(context)


class HST_OT_ResetPropTransformToOrigin(bpy.types.Operator):
    """重置 Prop Transform 到 Origin"""
    bl_idname = "hst.reset_prop_transform_to_origin"
    bl_label = "Reset Prop Transform To Origin"
    bl_description = "Reset Prop Transform To Origin"

    def execute(self, context):
        selected_objects = Object.get_selected()
        selected_collection = Collection.get_selected()
        prop_collections = []
        store_mode = prep_select_mode()
        origin_count = 0
        for collection in selected_collection:
            collection_type = Collection.get_hst_type(collection)
            if collection_type == Const.TYPE_PROP_COLLECTION:
                prop_collections.append(collection)
        if len(prop_collections) == 0:
            self.report({"ERROR"}, "No prop collections selected, please select prop collections and retry")
            return {'CANCELLED'}
        elif len(prop_collections) > 0:
            for object in selected_objects:
                object.select_set(False)
            for collection in prop_collections:
                origin_objects = Object.filter_hst_type(objects=collection.objects, type="ORIGIN", mode="INCLUDE")
                if origin_objects:
                    origin_count += 1
                    origin_object = origin_objects[0]

                    for object in collection.all_objects:
                        if object == origin_object:
                            continue
                        else:
                            object.select_set(True)
                            origin_object.select_set(True)
                            bpy.context.view_layer.objects.active = origin_object
                            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
                            Transform.apply(object)
                            object.select_set(False)
                            origin_object.select_set(False)
                else:
                    continue

        restore_select_mode(store_mode)
        self.report({"INFO"}, f"{origin_count} prop collections' objects reset transform to origin")
        return {'FINISHED'}


class HST_OT_SetSceneUnits(bpy.types.Operator):
    """设置场景单位为厘米"""
    bl_idname = "hst.setsceneunits"
    bl_label = "SetSceneUnits"
    bl_description = "设置场景单位为厘米"

    def execute(self, context):
        set_default_scene_units()
        self.report({"INFO"}, "Scene units set to centimeters")
        return {"FINISHED"}


class HST_OT_AxisCheck(bpy.types.Operator):
    """显示 UE 坐标轴参考"""
    bl_idname = "hst.axischeck"
    bl_label = "Check UE Front Axis"
    bl_description = "显示UE模型坐标轴参考"

    def execute(self, context):
        store_mode = prep_select_mode()
        properties = context.scene.hst_params
        axis_toggle = properties.axis_toggle
        axis_objects = []
        match axis_toggle:
            case False:
                for object in bpy.data.objects:
                    if AXIS_EMPTY in object.name:
                        bpy.data.objects.remove(object)

                for object in bpy.data.objects:
                    if object.name.startswith(AXIS_OBJECT_PREFIX):
                        axis_objects.append(object)

                if len(axis_objects) > 0:
                    for obj in axis_objects:
                        for material in obj.data.materials:
                            material.user_clear()
                            bpy.data.materials.remove(material)
                        old_mesh = obj.data
                        bpy.data.objects.remove(obj)
                        old_mesh.user_clear()
                        bpy.data.meshes.remove(old_mesh)

            case True:
                axis_arrow = import_object(PRESET_FILE_PATH, AXIS_ARROW)
                axis_objects.append(axis_arrow.parent)
                axis_objects.append(axis_arrow)
                for obj in axis_objects:
                    obj.show_in_front = True
                    obj.hide_render = True
                    obj.hide_viewport = False
                    obj.hide_select = True

        restore_select_mode(store_mode)
        return {"FINISHED"}


class HST_OT_CheckAssets(bpy.types.Operator):
    """检查资产"""
    bl_idname = "hst.checkassets"
    bl_label = "Check Assets"
    text = "CheckAssetsOperator"

    def draw(self, context):
        layout = self.layout
        box_column = layout.column()
        box_column.label(
            text="Scene Units: " + str(bpy.context.scene.unit_settings.system),
            icon="CHECKMARK",
        )
        box_column.label(
            text="Scene Scale: " + str(bpy.context.scene.unit_settings.scale_length),
            icon="ERROR",
        )
        box_column.label(
            text="Length Units: " + str(bpy.context.scene.unit_settings.length_unit),
            icon=show_reusult(scene_unit_check()),
        )

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
