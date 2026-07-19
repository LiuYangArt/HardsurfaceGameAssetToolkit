# -*- coding: utf-8 -*-
"""在真实 Blender GUI Context 中验证 Feature Chamfer Preview/Finalize 两步 Undo。"""

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


# 返回 Mesh topology/position/Sharp 的稳定 fingerprint。
# obj: 待检查 Mesh Object。
def _fingerprint(obj):
    sharp = obj.data.attributes.get("sharp_edge")
    payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in obj.data.vertices],
        "edges": [tuple(edge.vertices) for edge in obj.data.edges],
        "polygons": [tuple(polygon.vertices) for polygon in obj.data.polygons],
        "sharp": [
            edge.index
            for edge in obj.data.edges
            if sharp is not None and sharp.data[edge.index].value
        ],
    }
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


# 创建带单条 vertical Sharp Feature 的 cube。
# 无参数；返回 source Object。
def _make_source():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.active_object
    source.name = "GNUndoGuiSource"
    attribute = source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
    vertical_edge = next(
        edge
        for edge in source.data.edges
        if abs(
            source.data.vertices[edge.vertices[0]].co.z
            - source.data.vertices[edge.vertices[1]].co.z
        )
        > 1.5
    )
    attribute.data[vertical_edge.index].value = True
    return source


# 在 Window context 中执行 Preview/Finalize/Undo 并写入 artifact。
# 无参数；返回 None 让 timer 停止。
def _run():
    report = {"blender_version": bpy.app.version_string, "status": "running"}
    try:
        _load_addon()
        source = _make_source()
        bpy.context.preferences.edit.use_global_undo = True
        source_fingerprint = _fingerprint(source)
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
        region = next(region for region in area.regions if region.type == "WINDOW")
        preview = bpy.ops.hst.feature_chamfer_gn(
            "EXEC_DEFAULT",
            action="PREVIEW",
            radius=0.08,
            sample_length=0.04,
            voxel_size=0.025,
            adaptivity=0.1,
        )
        preview_modifier = source.modifiers.get("HST Feature Chamfer GN Preview")
        bpy.ops.object.select_all(action="DESELECT")
        source.select_set(True)
        bpy.context.view_layer.objects.active = source
        finalize = bpy.ops.hst.feature_chamfer_gn("EXEC_DEFAULT", action="FINALIZE")
        output = bpy.context.active_object
        output_name = output.name
        with bpy.context.temp_override(window=window, area=area, region=region):
            undo_finalize = bpy.ops.ed.undo()
        source_after_finalize_undo = bpy.data.objects.get("GNUndoGuiSource")
        preview_after_undo = source_after_finalize_undo.modifiers.get(
            "HST Feature Chamfer GN Preview"
        )
        finalize_undo_valid = (
            bpy.data.objects.get(output_name) is None
            and preview_after_undo is not None
            and preview_after_undo.show_viewport
            and _fingerprint(source_after_finalize_undo) == source_fingerprint
        )
        with bpy.context.temp_override(window=window, area=area, region=region):
            undo_preview = bpy.ops.ed.undo()
        source_after_preview_undo = bpy.data.objects.get("GNUndoGuiSource")
        preview_undo_valid = (
            source_after_preview_undo is not None
            and source_after_preview_undo.modifiers.get("HST Feature Chamfer GN Preview") is None
            and _fingerprint(source_after_preview_undo) == source_fingerprint
        )
        report.update(
            preview=sorted(preview),
            finalize=sorted(finalize),
            undo_finalize=sorted(undo_finalize),
            undo_preview=sorted(undo_preview),
            preview_modifier_created=preview_modifier is not None,
            finalize_undo_valid=finalize_undo_valid,
            preview_undo_valid=preview_undo_valid,
            status=(
                "passed"
                if preview == {"FINISHED"}
                and finalize == {"FINISHED"}
                and finalize_undo_valid
                and preview_undo_valid
                else "failed"
            ),
        )
    except Exception as error:
        report.update(status="failed", error=str(error), traceback=traceback.format_exc())
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("[HST_FEATURE_CHAMFER_GUI_UNDO]" + json.dumps(report, separators=(",", ":")))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=1.0)
