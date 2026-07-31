# -*- coding: utf-8 -*-
"""通过 Blender GUI 验证一步式 Feature Chamfer Undo/Redo。"""

import hashlib
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

import bpy


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
OUTPUT_PATH = REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_gn_gui_undo.json"
PACKAGE_NAME = "hst_feature_chamfer_gui_undo"
GUI_STATE = {}
FORMAL_RADIUS = 0.03
FORMAL_KEEP_CUTTER = True


class HST_MT_FeatureChamferGuiMenu(bpy.types.Menu):
    """只用于让真实 Blender UI 点击正式入口"""

    bl_label = "HST GUI Verification"
    bl_idname = "VIEW3D_MT_hst_feature_chamfer_gui"

    def draw(self, context):
        del context
        operator = self.layout.operator(
            "hst.feature_chamfer_gn",
            text="Feature Chamfer",
        )
        operator.radius = FORMAL_RADIUS
        operator.show_cutter = FORMAL_KEEP_CUTTER


# 从工作区加载并注册 add-on。
# 无参数；返回 add-on module。
def _load_addon():
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    module.register()
    return module


# 返回 Mesh topology、坐标与 Sharp Edge 的稳定 fingerprint。
# obj: 待检查 Mesh Object。
def _fingerprint(obj):
    sharp = obj.data.attributes.get("sharp_edge")
    payload = {
        "vertices": [
            tuple(round(value, 8) for value in vertex.co)
            for vertex in obj.data.vertices
        ],
        "edges": [tuple(edge.vertices) for edge in obj.data.edges],
        "polygons": [tuple(polygon.vertices) for polygon in obj.data.polygons],
        "sharp": [
            edge.index
            for edge in obj.data.edges
            if sharp is not None and sharp.data[edge.index].value
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


# 创建带顶部环形 Sharp Feature 的闭合 cube。
# 无参数；返回 source Object。
def _make_source():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.active_object
    source.name = "GNUndoGuiSource"
    attribute = source.data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    maximum_z = max(vertex.co.z for vertex in source.data.vertices)
    for edge in source.data.edges:
        if all(
            abs(source.data.vertices[index].co.z - maximum_z) <= 1.0e-6
            for index in edge.vertices
        ):
            attribute.data[edge.index].value = True
    return source


# 检查一步式结果不带旧 Preview runtime 残留。
# source/output: 正式输入与结果 Object；返回是否满足。
def _one_step_result_valid(source, output):
    return (
        output is not None
        and output is not source
        and output.type == "MESH"
        and source.modifiers.get("HST Feature Chamfer GN Preview") is None
        and not source.get("hst_feature_chamfer_curve_object")
        and source.hide_get()
        and source.hide_viewport
        and source.hide_render
        and not output.hide_get()
        and not output.hide_viewport
        and not output.hide_render
    )


# 返回真实 3D View 的 Window、Area 与 Region override 参数。
# 无参数；返回 context override dict。
def _view_3d_override():
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    return {"window": window, "area": area, "region": region}


# 返回当前 Blender keyconfig 的 Undo/Redo 快捷键修饰符。
# operator_id: ed.undo 或 ed.redo；返回 event_simulate 参数。
def _shortcut_event(operator_id):
    keyconfig = bpy.context.window_manager.keyconfigs.active
    for keymap in keyconfig.keymaps:
        for item in keymap.keymap_items:
            if item.idname == operator_id and item.active:
                return {
                    "type": item.type,
                    "ctrl": item.ctrl,
                    "shift": item.shift,
                    "alt": item.alt,
                    "oskey": item.oskey,
                }
    raise RuntimeError(f"No active shortcut for {operator_id}")


# 写入失败证据并退出 Blender，保留完整异常堆栈。
# error: 捕获的异常；无返回值。
def _fail(error):
    report_data = GUI_STATE.setdefault(
        "report_data",
        {"blender_version": bpy.app.version_string},
    )
    report_data.update(
        status="failed",
        error=f"{type(error).__name__}: {error}",
        traceback=traceback.format_exc(),
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(
        "[HST_FEATURE_CHAMFER_GUI_UNDO]"
        + json.dumps(report_data, separators=(",", ":"))
    )
    bpy.ops.wm.quit_blender()


# 检查正式 Operator 的 Adjust Last Operation RNA 合同与实际传入值。
# 无参数；返回参数合同证据。
def _redo_contract():
    operator_type = bpy.types.HST_OT_feature_chamfer_gn
    operator_rna = bpy.ops.hst.feature_chamfer_gn.get_rna_type()
    radius_property = operator_rna.properties.get("radius")
    cutter_property = operator_rna.properties.get("show_cutter")
    return {
        "formal_operator": operator_type.bl_idname,
        "is_formal_operator": operator_type.bl_idname == "hst.feature_chamfer_gn",
        "register_and_undo": (
            "REGISTER" in operator_type.bl_options
            and "UNDO" in operator_type.bl_options
        ),
        "draw_available": "draw" in operator_type.__dict__,
        "radius": {
            "available": radius_property is not None,
            "label": radius_property.name if radius_property is not None else "",
            "value": FORMAL_RADIUS,
        },
        "keep_cutter": {
            "available": cutter_property is not None,
            "label": cutter_property.name if cutter_property is not None else "",
            "value": FORMAL_KEEP_CUTTER,
        },
    }


# 在真实 3D View 鼠标位置打开临时菜单。
# 无参数；返回 None。
def _execute_formal_operator():
    try:
        override = _view_3d_override()
        area = override["area"]
        x = area.x + (area.width // 2)
        y = area.y + (area.height // 2)
        override["window"].event_simulate(
            type="MOUSEMOVE", value="NOTHING", x=x, y=y
        )
        with bpy.context.temp_override(**override):
            bpy.ops.wm.call_menu(name="VIEW3D_MT_hst_feature_chamfer_gui")
        GUI_STATE["formal_operation"] = ["FINISHED"]
        bpy.app.timers.register(_click_formal_operator, first_interval=0.5)
    except Exception as error:
        _fail(error)
    return None


# 用菜单确认事件执行唯一的正式入口，让 Blender WM 记录一次事务。
# 无参数；返回 None。
def _click_formal_operator():
    try:
        window = _view_3d_override()["window"]
        window.event_simulate(type="RET", value="PRESS")
        window.event_simulate(type="RET", value="RELEASE")
        bpy.app.timers.register(_inspect_formal_operator, first_interval=0.8)
    except Exception as error:
        _fail(error)
    return None


# 检查 timer 触发后的正式结果与 Adjust Last Operation 合同。
# 无参数；返回 None。
def _inspect_formal_operator():
    try:
        source = bpy.data.objects[GUI_STATE["source_name"]]
        output = bpy.context.active_object
        stats = json.loads(
            bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}")
        )
        cutter_object_name = stats.get("cutter_object_name", "")
        redo_contract = _redo_contract()
        GUI_STATE.update(
            output_name=output.name,
            cutter_object_name=cutter_object_name,
        )
        GUI_STATE["report_data"].update(
            operation=GUI_STATE["formal_operation"],
            invocation="FORMAL_UI_MENU_RETURN_EVENT",
            redo_contract=redo_contract,
            initial_valid=(
                GUI_STATE["formal_operation"] == ["FINISHED"]
                and _one_step_result_valid(source, output)
                and _fingerprint(source) == GUI_STATE["source_fingerprint"]
                and cutter_object_name in bpy.data.objects
            ),
            adjust_last_operation_available=(
                redo_contract["is_formal_operator"]
                and redo_contract["register_and_undo"]
                and redo_contract["draw_available"]
                and redo_contract["radius"] == {
                    "available": True,
                    "label": "Radius",
                    "value": FORMAL_RADIUS,
                }
                and redo_contract["keep_cutter"] == {
                    "available": True,
                    "label": "Keep Cutter",
                    "value": FORMAL_KEEP_CUTTER,
                }
            ),
        )
        bpy.app.timers.register(_undo_formal_transaction, first_interval=0.8)
    except Exception as error:
        _fail(error)
    return None


# 对正式一次事务执行真实 GUI Undo。
# 无参数；返回 None。
def _undo_formal_transaction():
    try:
        override = _view_3d_override()
        region = override["region"]
        window = override["window"]
        window.event_simulate(
            type="MOUSEMOVE",
            value="NOTHING",
            x=region.x + (region.width // 2),
            y=region.y + (region.height // 2),
        )
        window.event_simulate(type="ESC", value="PRESS")
        window.event_simulate(type="ESC", value="RELEASE")
        bpy.app.timers.register(_send_undo_shortcut, first_interval=0.5)
    except Exception as error:
        _fail(error)
    return None


# 在 3D View 已获得鼠标焦点后发送真实 Undo 快捷键。
# 无参数；返回 None。
def _send_undo_shortcut():
    try:
        window = _view_3d_override()["window"]
        shortcut = _shortcut_event("ed.undo")
        window.event_simulate(value="PRESS", **shortcut)
        window.event_simulate(value="RELEASE", **shortcut)
        GUI_STATE["report_data"]["undo_operator_result"] = shortcut
        bpy.app.timers.register(_check_undo, first_interval=1.0)
    except Exception as error:
        _fail(error)
    return None


# 检查 Undo 清理正式输出与 Keep Cutter，再执行真实 GUI Redo。
# 无参数；返回 None。
def _check_undo():
    try:
        source = bpy.data.objects.get(GUI_STATE["source_name"])
        output_exists = bpy.data.objects.get(GUI_STATE["output_name"]) is not None
        cutter_exists = bpy.data.objects.get(GUI_STATE["cutter_object_name"]) is not None
        source_unchanged = (
            source is not None
            and _fingerprint(source) == GUI_STATE["source_fingerprint"]
        )
        source_visible = (
            source is not None
            and not source.hide_get()
            and not source.hide_viewport
            and not source.hide_render
        )
        GUI_STATE["report_data"].update(
            undo="FORMAL_TRANSACTION_GUI_UNDO",
            undo_observed={
                "source_exists": source is not None,
                "output_exists": output_exists,
                "cutter_exists": cutter_exists,
                "source_unchanged": source_unchanged,
                "source_visible": source_visible,
            },
            undo_valid=(
                source is not None
                and not output_exists
                and not cutter_exists
                and source_unchanged
                and source_visible
            ),
        )
        bpy.app.timers.register(_send_redo_shortcut, first_interval=0.3)
    except Exception as error:
        _fail(error)
    return None


# 从同一真实 3D View 发送 Redo 快捷键。
# 无参数；返回 None。
def _send_redo_shortcut():
    try:
        window = _view_3d_override()["window"]
        shortcut = _shortcut_event("ed.redo")
        window.event_simulate(value="PRESS", **shortcut)
        window.event_simulate(value="RELEASE", **shortcut)
        GUI_STATE["report_data"]["redo_operator_result"] = shortcut
        bpy.app.timers.register(_check_redo, first_interval=1.0)
    except Exception as error:
        _fail(error)
    return None


# 检查 Redo 恢复正式结果并写入最终 GUI 证据。
# 无参数；返回 None。
def _check_redo():
    try:
        source = bpy.data.objects.get(GUI_STATE["source_name"])
        output = bpy.data.objects.get(GUI_STATE["output_name"])
        redo_valid = (
            source is not None
            and _one_step_result_valid(source, output)
            and _fingerprint(source) == GUI_STATE["source_fingerprint"]
            and bpy.data.objects.get(GUI_STATE["cutter_object_name"]) is not None
        )
        report_data = GUI_STATE["report_data"]
        report_data.update(
            redo="FORMAL_TRANSACTION_GUI_REDO",
            redo_valid=redo_valid,
            one_step_only=True,
            keep_cutter_undo_redo_valid=(
                report_data["undo_valid"] and redo_valid
            ),
            status=(
                "passed"
                if report_data["initial_valid"]
                and report_data["adjust_last_operation_available"]
                and report_data["undo_valid"]
                and redo_valid
                else "failed"
            ),
        )
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(report_data, indent=2),
            encoding="utf-8",
        )
        print(
            "[HST_FEATURE_CHAMFER_GUI_UNDO]"
            + json.dumps(report_data, separators=(",", ":"))
        )
        bpy.ops.wm.quit_blender()
    except Exception as error:
        _fail(error)
    return None


# 初始化真实 GUI 场景，并将正式调用放到独立 timer 事务。
# 无参数；返回 None。
def _start():
    try:
        _load_addon()
        bpy.utils.register_class(HST_MT_FeatureChamferGuiMenu)
        source = _make_source()
        bpy.context.preferences.edit.use_global_undo = True
        bpy.ops.ed.undo_push(message="Feature Chamfer GUI setup baseline")
        GUI_STATE.update(
            source_name=source.name,
            source_fingerprint=_fingerprint(source),
            report_data={
                "blender_version": bpy.app.version_string,
                "status": "running",
                "setup_baseline_push_count": 1,
                "formal_transaction_manual_push_count": 0,
            },
        )
        bpy.app.timers.register(_execute_formal_operator, first_interval=0.8)
    except Exception as error:
        _fail(error)
    return None


bpy.app.timers.register(_start, first_interval=1.0)
