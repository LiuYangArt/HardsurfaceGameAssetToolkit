# -*- coding: utf-8 -*-
"""
UV 操作 Operators
================

包含 UV 编辑、Texel Density 设置等功能。
"""

import blf
import bpy
from ..const import *
from ..functions.common_functions import *
from ..utils.swatch_utils import (
    DEFAULT_SWATCH_CELL,
    SWATCH_COLOR_GROUPS,
    SWATCH_COLOR_STEPS,
    SWATCH_MATERIAL_TYPES,
    SWATCH_METAL_GROUPS,
    SWATCH_ROUGHNESS_STEPS,
    apply_swatch_uv,
    get_swatch_material,
    get_swatch_texture,
    is_swatch_object_ready,
    prepare_swatch_object,
    read_swatch_cell,
    restore_swatch_uv,
    setup_swatch_editor,
    snapshot_swatch_uv,
    swatch_cell_label,
    swatch_cell_to_uv,
    swatch_uv_to_cell,
)


class HST_OT_MakeSwatchUV(bpy.types.Operator):
    """为 CAD 模型添加 Swatch UV"""
    bl_idname = "hst.makeswatchuv"
    bl_label = "HST Make Swatch UV"
    bl_description = "为CAD模型添加Swatch UV"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        for mesh in selected_meshes:
            mesh.select_set(True)
            uv_swatch = add_uv_layers(mesh, uv_name=UV_SWATCH)
            uv_swatch.active = True
            apply_swatch_uv(mesh, swatch_cell_to_uv(DEFAULT_SWATCH_CELL))

        self.report({"INFO"}, "Swatch UV added")
        return {"FINISHED"}


PICK_SWATCH_CONFIRM_EVENTS = {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"}
PICK_SWATCH_CANCEL_EVENTS = {"ESC"}
PICK_SWATCH_PASS_EVENTS = {
    "MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "LEFTMOUSE", "MIDDLEMOUSE",
    "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM", "HOME",
    "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL", "LEFT_ALT", "RIGHT_ALT", "OSKEY",
    "WINDOW_DEACTIVATE",
}
PICK_SWATCH_PASS_PREFIXES = ("NUMPAD_", "NDOF_", "TIMER")
PICK_SWATCH_HINT = "Click a cell or edit the bar below  ·  Enter / Space / Right Click: Confirm  ·  Esc: Cancel"

# 正在运行的 Pick Swatch operator；面板参数的 update 回调和面板 poll 依赖它
_pick_swatch_session = None


def get_pick_swatch_session():
    """
    返回正在运行的 Pick Swatch operator；未运行或已被 Blender 释放时返回 None
    """
    global _pick_swatch_session
    if _pick_swatch_session is None:
        return None
    try:
        _pick_swatch_session.as_pointer()
    except ReferenceError:
        _pick_swatch_session = None
    return _pick_swatch_session


def swatch_params_to_cell(params) -> dict:
    """
    把面板参数组合为 Swatch 格子 dict

    Args:
        params: HST_SwatchPickParams
    """
    return {
        "material_type": params.material_type,
        "color_group": params.color_group,
        "metal_group": params.metal_group,
        "color": params.color,
        "roughness": params.roughness,
    }


def on_swatch_pick_params_changed(params, context):
    """
    面板参数变化时，把新格子应用到当前选中的物体（仅在 Pick Swatch 运行期间生效）

    Args:
        params: HST_SwatchPickParams
        context: Blender context
    """
    session = get_pick_swatch_session()
    if session is not None and not session.syncing:
        session.pick(context, swatch_params_to_cell(params))


class HST_SwatchPickParams(bpy.types.PropertyGroup):
    """Pick Swatch 面板参数；挂在 WindowManager 上，不进入 Undo 历史"""

    material_type: bpy.props.EnumProperty(
        name="Material", items=SWATCH_MATERIAL_TYPES,
        default=DEFAULT_SWATCH_CELL["material_type"], update=on_swatch_pick_params_changed,
    )
    color_group: bpy.props.EnumProperty(
        name="Group", items=SWATCH_COLOR_GROUPS,
        default=DEFAULT_SWATCH_CELL["color_group"], update=on_swatch_pick_params_changed,
    )
    metal_group: bpy.props.EnumProperty(
        name="Group", items=SWATCH_METAL_GROUPS,
        default=DEFAULT_SWATCH_CELL["metal_group"], update=on_swatch_pick_params_changed,
    )
    color: bpy.props.IntProperty(
        name="Color", min=1, max=SWATCH_COLOR_STEPS,
        default=DEFAULT_SWATCH_CELL["color"], update=on_swatch_pick_params_changed,
    )
    roughness: bpy.props.IntProperty(
        name="Roughness", min=1, max=SWATCH_ROUGHNESS_STEPS,
        default=DEFAULT_SWATCH_CELL["roughness"], description="1 is the smoothest",
        update=on_swatch_pick_params_changed,
    )


def get_pick_swatch_targets(context) -> list:
    """
    返回 Pick Swatch 的目标 Mesh 物体：Edit Mode 下为编辑中的物体，Object Mode 下为选中物体

    Args:
        context: Blender context
    """
    if context.mode == "EDIT_MESH":
        return [obj for obj in context.objects_in_mode_unique_data if obj.type == "MESH"]
    return filter_type(context.selected_objects, "MESH")


def prepare_pick_swatch_targets(context, target_objects: list) -> None:
    """
    为目标物体补齐 Swatch UV 与 Swatch 材质，并把 Swatch UV 设为 active；Edit Mode 下临时切回 Object Mode

    Args:
        context: Blender context
        target_objects: 目标 Mesh 物体列表
    """
    pending_objects = [obj for obj in target_objects if not is_swatch_object_ready(obj)]
    if pending_objects:
        in_edit_mode = context.mode == "EDIT_MESH"
        if in_edit_mode:
            bpy.ops.object.mode_set(mode="OBJECT")
        swatch_material = get_swatch_material()
        for obj in pending_objects:
            prepare_swatch_object(obj, swatch_material)
        if in_edit_mode:
            bpy.ops.object.mode_set(mode="EDIT")
    for obj in target_objects:
        obj.data.uv_layers[UV_SWATCH].active = True


def find_image_region_under_mouse(context, event):
    """
    返回鼠标所在的 Image Editor 主区域及对应的 UV 坐标；鼠标在侧栏、Header 等叠加区域上时视为不在贴图上

    Args:
        context: Blender context
        event: 当前事件
    Returns:
        (region, (u, v))；鼠标不在 Image Editor 主区域时返回 (None, None)
    """
    for area in context.window.screen.areas:
        if area.type != "IMAGE_EDITOR":
            continue
        main_region = None
        for region in area.regions:
            inside = (
                region.x <= event.mouse_x < region.x + region.width
                and region.y <= event.mouse_y < region.y + region.height
            )
            if not inside:
                continue
            if region.type != "WINDOW":
                return None, None
            main_region = region
        if main_region is not None:
            local_x = event.mouse_x - main_region.x
            local_y = event.mouse_y - main_region.y
            return main_region, tuple(main_region.view2d.region_to_view(local_x, local_y))
    return None, None


def draw_pick_swatch_bar(header, context) -> None:
    """
    IMAGE_HT_tool_header 的 prepend 绘制函数：点选期间在 Image Editor 底部参数条显示 Swatch 参数

    Args:
        header: IMAGE_HT_tool_header 实例
        context: Blender context
    """
    session = get_pick_swatch_session()
    if session is None:
        return
    params = context.window_manager.hst_swatch_pick
    row = header.layout.row(align=True)
    row.prop(params, "material_type", text="")
    row.prop(params, "metal_group" if params.material_type == "METAL" else "color_group", text="")
    row = header.layout.row(align=True)
    row.prop(params, "color")
    row.prop(params, "roughness")
    if session.current_label == "Mixed":
        header.layout.label(text="Current: Mixed", icon="INFO")
    header.layout.separator_spacer()


def draw_pick_swatch_overlay() -> None:
    """
    在 Image Editor 主区域左上角绘制 Pick Swatch 操作提示，字号与 Blender 界面文字一致
    """
    if get_pick_swatch_session() is None:
        return
    preferences = bpy.context.preferences
    ui_scale = preferences.system.ui_scale
    font_id = 0
    blf.size(font_id, preferences.ui_styles[0].widget.points * ui_scale)
    blf.enable(font_id, blf.SHADOW)
    blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 1.0)
    blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
    blf.position(font_id, 10 * ui_scale, bpy.context.region.height - 20 * ui_scale, 0)
    blf.draw(font_id, PICK_SWATCH_HINT)
    blf.disable(font_id, blf.SHADOW)


class HST_OT_PickSwatch(bpy.types.Operator):
    """在 Swatch 贴图上点选格子或在底部参数条调参数，把选中模型的 Swatch UV 缩成一点放到格子中心"""
    bl_idname = "hst.pickswatch"
    bl_label = "HST Pick Swatch"
    bl_description = (
        "Click a cell on the swatch texture, or edit the bar at the bottom of the image editor, "
        "to assign it to the selected meshes (selected faces in Edit Mode). "
        "Enter/Space/RMB to confirm, Esc to cancel"
    )
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}

    def execute(self, context):
        target_objects = get_pick_swatch_targets(context)
        if not target_objects:
            self.report({"ERROR"}, "No selected mesh object\n没有选中Mesh物体")
            return {"CANCELLED"}
        prepare_pick_swatch_targets(context, target_objects)
        uv = swatch_cell_to_uv(swatch_params_to_cell(context.window_manager.hst_swatch_pick))
        for obj in target_objects:
            apply_swatch_uv(obj, uv)
        return {"FINISHED"}

    def invoke(self, context, event):
        global _pick_swatch_session
        target_objects = get_pick_swatch_targets(context)
        if not target_objects:
            self.report({"ERROR"}, "No selected mesh object\n没有选中Mesh物体")
            return {"CANCELLED"}
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "Run Pick Swatch from the 3D Viewport\n请在3D视图中运行")
            return {"CANCELLED"}
        if get_pick_swatch_session() is not None:
            self.report({"WARNING"}, "Pick Swatch is already running")
            return {"CANCELLED"}

        prepare_pick_swatch_targets(context, target_objects)
        swatch_material = get_swatch_material()
        setup_swatch_editor(swatch_material)
        self.swatch_texture = get_swatch_texture(swatch_material)

        self.syncing = False
        active_object = context.active_object
        current_cell = read_swatch_cell(active_object) if active_object in target_objects else None
        if current_cell is not None:
            self.sync_params(context, current_cell)
        self.current_label = swatch_cell_label(current_cell)
        self.snapshots = {}
        self.window = context.window
        _pick_swatch_session = self
        self.show_bottom_bars(context)
        self.draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
            draw_pick_swatch_overlay, (), "WINDOW", "POST_PIXEL"
        )

        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(PICK_SWATCH_HINT)
        self.redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.value == "PRESS" and event.type in PICK_SWATCH_CANCEL_EVENTS:
            self.restore(context)
            self.finish(context)
            return {"CANCELLED"}
        if event.value == "PRESS" and event.type in PICK_SWATCH_CONFIRM_EVENTS:
            self.finish(context)
            return {"FINISHED"}

        if event.type == "LEFTMOUSE":
            region, uv = find_image_region_under_mouse(context, event)
            if region is not None:
                cell = swatch_uv_to_cell(*uv)
                if event.value == "PRESS" and cell is not None:
                    self.pick(context, cell)
                return {"RUNNING_MODAL"}

        if event.type in PICK_SWATCH_PASS_EVENTS or event.type.startswith(PICK_SWATCH_PASS_PREFIXES):
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def pick(self, context, cell: dict) -> None:
        """
        把格子应用到当前选中的物体并同步面板参数；首次改动的物体先记录原 UV，供取消时恢复

        Args:
            context: Blender context
            cell: 点中或面板设定的 Swatch 格子
        """
        target_objects = get_pick_swatch_targets(context)
        if not target_objects:
            return
        prepare_pick_swatch_targets(context, target_objects)
        for obj in target_objects:
            if obj.name not in self.snapshots:
                self.snapshots[obj.name] = snapshot_swatch_uv(obj)
        uv = swatch_cell_to_uv(cell)
        for obj in target_objects:
            apply_swatch_uv(obj, uv)
        self.sync_params(context, cell)
        self.current_label = swatch_cell_label(cell)
        self.redraw(context)

    def sync_params(self, context, cell: dict) -> None:
        """
        把格子写回面板参数，写入期间屏蔽 update 回调避免重复应用

        Args:
            context: Blender context
            cell: Swatch 格子 dict
        """
        params = context.window_manager.hst_swatch_pick
        self.syncing = True
        try:
            params.material_type = cell["material_type"]
            if cell["material_type"] == "METAL":
                params.metal_group = cell["metal_group"]
            else:
                params.color_group = cell["color_group"]
            params.color = cell["color"]
            params.roughness = cell["roughness"]
        finally:
            self.syncing = False

    def restore(self, context) -> None:
        """
        恢复本次点选改过的所有物体的 Swatch UV

        Args:
            context: Blender context
        """
        for object_name, snapshot in self.snapshots.items():
            obj = bpy.data.objects.get(object_name)
            if obj is not None:
                restore_swatch_uv(obj, snapshot)

    def show_bottom_bars(self, context) -> None:
        """
        在所有 Image Editor 显示 Tool Header 并临时翻到底部作为参数条，记录原状态供结束时恢复

        Args:
            context: Blender context
        """
        self.bar_states = []
        for area in context.window.screen.areas:
            if area.type != "IMAGE_EDITOR":
                continue
            space = area.spaces.active
            if space.image is None:
                space.image = self.swatch_texture
            tool_header = next(region for region in area.regions if region.type == "TOOL_HEADER")
            was_shown = space.show_region_tool_header
            was_flipped = tool_header.alignment != "BOTTOM"
            self.bar_states.append((area, was_shown, was_flipped))
            space.show_region_tool_header = True
            if was_flipped:
                self.flip_tool_header(area)
        bpy.types.IMAGE_HT_tool_header.prepend(draw_pick_swatch_bar)

    def restore_bottom_bars(self) -> None:
        """
        移除参数条内容，把 Tool Header 翻回原位置并恢复原显示状态
        """
        bpy.types.IMAGE_HT_tool_header.remove(draw_pick_swatch_bar)
        for area, was_shown, was_flipped in self.bar_states:
            if was_flipped:
                self.flip_tool_header(area)
            area.spaces.active.show_region_tool_header = was_shown

    def flip_tool_header(self, area) -> None:
        """
        把 Image Editor 的 Tool Header 在顶部与底部之间翻转

        Args:
            area: Image Editor area
        """
        tool_header = next(region for region in area.regions if region.type == "TOOL_HEADER")
        with bpy.context.temp_override(window=self.window, area=area, region=tool_header):
            bpy.ops.screen.region_flip()

    def redraw(self, context) -> None:
        """
        刷新所有区域，使提示文字、参数条与视口结果同步

        Args:
            context: Blender context
        """
        for area in context.window.screen.areas:
            area.tag_redraw()

    def finish(self, context) -> None:
        """
        结束点选：移除提示绘制、恢复参数条所在的 Tool Header、清除状态栏提示

        Args:
            context: Blender context
        """
        global _pick_swatch_session
        _pick_swatch_session = None
        bpy.types.SpaceImageEditor.draw_handler_remove(self.draw_handle, "WINDOW")
        self.restore_bottom_bars()
        context.workspace.status_text_set(None)
        self.redraw(context)


class HST_OT_BaseUVEditMode(bpy.types.Operator):
    """Base UV 编辑模式"""
    bl_idname = "hst.baseuveditmode"
    bl_label = "HST BaseUV Edit Mode"
    bl_description = "Base UV编辑环境"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if not selected_meshes:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"

        UV.show_uv_in_object_mode()

        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        for mesh in selected_meshes:
            mesh.select_set(True)
            has_uv = has_uv_attribute(mesh)
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

        uv_space.image = None
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        self.report({"INFO"}, "Base UV edit mode")
        return {"FINISHED"}


class HST_OT_SetTexelDensity(bpy.types.Operator):
    """设置 BaseUV 的 Texel Density"""
    bl_idname = "hst.setbaseuvtexeldensity"
    bl_label = "Set BaseUV TexelDensity"
    bl_description = "设置选中模型的BaseUV的Texel Density\
        选中模型后运行，可以设置模型的Texel Density\
        贴图大小和TD使用默认值即可，通常不需要设置"

    def execute(self, context):
        parameters = context.scene.hst_params
        texel_density = parameters.texture_density * 0.01
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if not selected_meshes:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        texture_size_x = parameters.texture_size
        texture_size_y = parameters.texture_size

        store_mode = prep_select_mode()

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            if uv_layer is None:
                self.report(
                    {"ERROR"},
                    "Selected mesh has no UV layer named 'UV0_Base', setup uv layer first\n"
                    + "选中的模型没有名为'UV0_Base'的UV，请先正确设置UV",
                )
                return {"CANCELLED"}

        uv_average_scale(selected_objects, uv_layer_name=UV_BASE)

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            old_td = get_texel_density(mesh, texture_size_x, texture_size_y)
            scale_factor = texel_density / old_td
            scale_uv(mesh, uv_layer, (scale_factor, scale_factor), (0.5, 0.5))

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Texel Density set to " + str(texel_density))
        return {"FINISHED"}
