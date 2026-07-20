# -*- coding: utf-8 -*-
"""在真实 Feature Chamfer fixture 上输出 Phase 2B Finalize 诊断。"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
FIXTURE_PATH = Path(
    os.environ.get(
        "HST_FEATURE_CHAMFER_INPUT",
        REPO_ROOT / "tests" / "fixtures" / "feature-chamfer-gn-junction-safe.blend",
    )
)
OUTPUT_PATH = Path(
    os.environ.get(
        "HST_FEATURE_CHAMFER_FINALIZE_PROBE",
        REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_gn_finalize_fixture_probe.json",
    )
)
BLEND_OUTPUT_PATH = Path(
    os.environ.get(
        "HST_FEATURE_CHAMFER_BLEND_OUTPUT",
        REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_gn_finalize_fixture.blend",
    )
)
IMAGE_OUTPUT_PATH = Path(
    os.environ.get(
        "HST_FEATURE_CHAMFER_IMAGE_OUTPUT",
        REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_gn_finalize_fixture.png",
    )
)
PACKAGE_NAME = "hst_feature_chamfer_finalize_probe"


# 从当前工作区加载 add-on，避免调用 Blender 已安装副本。
# 无参数；返回工作区 add-on module。
def load_addon_module():
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


bpy.ops.wm.open_mainfile(filepath=str(FIXTURE_PATH))
addon = load_addon_module()
source = bpy.data.objects[os.environ.get("HST_FEATURE_CHAMFER_SOURCE", "Extruded.002")]
for modifier in list(source.modifiers):
    source.modifiers.remove(modifier)
preview_utils = addon.utils.feature_chamfer_gn_utils
preview_utils.ensure_gn_feature_chamfer_preview(
    source,
    radius=float(os.environ.get("HST_FEATURE_CHAMFER_RADIUS", "0.03")),
    show_cutter=False,
)
finalize_utils = addon.utils.feature_chamfer_finalize_utils
finalize_context = None
try:
    finalize_context = finalize_utils.extract_feature_chamfer_finalize_context(source)
    report = finalize_context["diagnostics"]
    patch_utils = addon.utils.feature_chamfer_patch_utils
    patched_mesh = None
    try:
        patched_mesh, patch_stats = patch_utils.patch_boolean_result(
            finalize_context["open_mesh"],
            finalize_context["boundary_regions"],
            report["boundary_graph"]["components"],
            donor_mesh=finalize_context["boolean_mesh"],
            groove_face_indices=finalize_context["groove_face_indices"],
        )
        report["patch"] = patch_stats
        output_object = bpy.data.objects.new(
            f"{source.name}_FeatureChamfer",
            patched_mesh,
        )
        source.users_collection[0].objects.link(output_object)
        output_object.matrix_world = source.matrix_world.copy()
        patched_mesh = None
        source.hide_set(True)
        output_object.select_set(True)
        bpy.context.view_layer.objects.active = output_object
        center = sum(
            (output_object.matrix_world @ vertex.co for vertex in output_object.data.vertices),
            output_object.location.copy() * 0.0,
        ) / len(output_object.data.vertices)
        size = max(output_object.dimensions)
        bpy.ops.object.camera_add(location=center + size * Vector((1.4, -1.4, 1.1)))
        camera = bpy.context.active_object
        camera.data.lens = 55.0
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.camera = camera
        bpy.ops.object.light_add(type="AREA", location=center + size * Vector((0.8, -0.6, 1.8)))
        key_light = bpy.context.active_object
        key_light.data.energy = 1800.0
        key_light.data.shape = "DISK"
        key_light.data.size = size * 1.5
        key_light.rotation_euler = (center - key_light.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        bpy.context.scene.render.resolution_x = 960
        bpy.context.scene.render.resolution_y = 720
        bpy.context.scene.render.resolution_percentage = 100
        bpy.context.scene.render.image_settings.file_format = "PNG"
        bpy.context.scene.render.filepath = str(IMAGE_OUTPUT_PATH)
        bpy.ops.render.render(write_still=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_OUTPUT_PATH), copy=True)
        report["patch"]["blend_artifact"] = str(BLEND_OUTPUT_PATH)
        report["patch"]["image_artifact"] = str(IMAGE_OUTPUT_PATH)
    except patch_utils.FeatureChamferPatchError as error:
        report["patch"] = error.diagnostics
    finally:
        if patched_mesh is not None and bpy.data.meshes.get(patched_mesh.name) == patched_mesh:
            bpy.data.meshes.remove(patched_mesh)
except finalize_utils.FeatureChamferFinalizeError as error:
    report = error.diagnostics
finally:
    finalize_utils.release_feature_chamfer_finalize_context(finalize_context)

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("[HST_FEATURE_CHAMFER_FINALIZE_PROBE]" + json.dumps(report, separators=(",", ":")))
