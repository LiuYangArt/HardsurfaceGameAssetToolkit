# -*- coding: utf-8 -*-
"""Blender-side Feature Chamfer batched Phase A/B 产品矩阵。"""

import hashlib
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
ARTIFACT_DIRECTORY = Path(
    os.environ["HST_FEATURE_CHAMFER_BATCHED_MATRIX_ARTIFACT_DIR"]
)
REPETITIONS = int(os.environ["HST_FEATURE_CHAMFER_BATCHED_MATRIX_REPETITIONS"])
DEBUG_STAGE = os.environ.get(
    "HST_FEATURE_CHAMFER_BATCHED_MATRIX_STAGE",
    "PHASE_B_BATCH_PROBE",
)
RESULTS_PATH = ARTIFACT_DIRECTORY / "results.json"
PACKAGE_NAME = "hst_feature_chamfer_batched_matrix_addon"
FIXTURE_DIRECTORY = REPO_ROOT / "tests" / "fixtures"
FIXTURE_HASHES = {
    "feature-chamfer-product-simple.blend": (
        "1cbab4c83c4d9f77bd2b0799257953aaec32aa416994a1d8810425f3c2b94d8c"
    ),
    "feature-chamfer-product-tricky.blend": (
        "c7f57a54837a04f7e52b535bb47af0abeb05fca4193dac714fb3667efb426f02"
    ),
    "feature-chamfer-product-tricky-b.blend": (
        "a4c121b6bbbfff58b94c3b7ed11bd82fe59c88a92569389fd27593ed65be9a35"
    ),
    "feature-chamfer-topology-defect-mixed.blend": (
        "80da3ee4144ba83cab4e9bed980c8829d846369f22a694abfe1aa513c3a3d1b8"
    ),
}
MATRIX_SOURCES = (
    ("simple", "feature-chamfer-product-simple.blend", "Extruded.002"),
    ("simple", "feature-chamfer-product-simple.blend", "Solid 44"),
    ("tricky", "feature-chamfer-product-tricky.blend", "Solid.004"),
    ("tricky", "feature-chamfer-product-tricky.blend", "Solid.016"),
    ("tricky_b", "feature-chamfer-product-tricky-b.blend", "Extruded.003"),
    ("tricky_b", "feature-chamfer-product-tricky-b.blend", "Extruded.002"),
    ("mixed", "feature-chamfer-topology-defect-mixed.blend", "Extruded.002"),
)
MATRIX_RADII = (0.01, 0.03)
CASE_FILTER = {
    case_name.strip()
    for case_name in os.environ.get("HST_FEATURE_CHAMFER_BATCHED_MATRIX_CASES", "").split(",")
    if case_name.strip()
}


# 从 __init__.py 载入插件模块，使 matrix 与正式注册使用同一 package。
# 无参数；返回已载入但尚未 register 的模块。
def load_addon_module():
    init_path = REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        init_path,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


# 返回 fixture 文件 SHA-256，验证测试输入未被覆盖。
# path: repo fixture 路径；返回十六进制 SHA-256。
def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as fixture_file:
        for chunk in iter(lambda: fixture_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 将 source 设为唯一选择和 active Object，确保 Operator invoke context 真实。
# source_object: 当前 fixture 中的 Mesh Object；无返回值。
def activate_source(source_object):
    for selected_object in tuple(bpy.context.selected_objects):
        selected_object.select_set(False)
    source_object.hide_set(False)
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.context.view_layer.update()


# 把当前 .blend 保存为 copy，不覆盖 immutable fixture。
# artifact_path: 目标 artifact 路径；无返回值。
def save_artifact_copy(artifact_path):
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.wm.save_as_mainfile(
        filepath=str(artifact_path),
        check_existing=False,
        compress=True,
        copy=True,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"Failed to save artifact copy: {artifact_path}")


# 从 Phase C regular records 创建可见 Faces，并从 setback ports 创建红色有序 Edge artifacts。
# source_object/diagnostics/collection: fixture source、batched result 与临时 Collection；返回创建的 Objects。
def create_phase_c_debug_objects(source_object, diagnostics, collection):
    regular_records = [
        record
        for record in diagnostics.get("batch_records", [])
        if record.get("faces")
    ]
    regular_coordinates = []
    regular_faces = []
    coordinate_index = {}
    for record in regular_records:
        for face in record["faces"]:
            face_indices = []
            for coordinate in face:
                key = tuple(round(float(value), 8) for value in coordinate)
                if key not in coordinate_index:
                    coordinate_index[key] = len(regular_coordinates)
                    regular_coordinates.append(key)
                face_indices.append(coordinate_index[key])
            regular_faces.append(face_indices)
    regular_mesh = bpy.data.meshes.new("HST_PhaseC_RegularStrips_Mesh")
    regular_mesh.from_pydata(regular_coordinates, [], regular_faces)
    regular_mesh.update()
    regular_object = bpy.data.objects.new("HST_PhaseC_RegularStrips", regular_mesh)
    regular_object.matrix_world = source_object.matrix_world.copy()
    collection.objects.link(regular_object)
    regular_material = bpy.data.materials.new("HST_PhaseC_Regular_Orange")
    regular_material.diffuse_color = (1.0, 0.22, 0.02, 1.0)
    regular_material.diffuse_color = (1.0, 0.22, 0.02, 1.0)
    regular_material.metallic = 0.0
    regular_material.roughness = 0.35
    regular_object.data.materials.append(regular_material)

    port_coordinates = []
    port_edges = []
    for port in diagnostics.get("junction_regions", []):
        coordinates = [tuple(float(value) for value in point) for point in port["ordered_coordinates"]]
        offset = len(port_coordinates)
        port_coordinates.extend(coordinates)
        port_edges.extend(
            (offset + index, offset + index + 1)
            for index in range(len(coordinates) - 1)
        )
        if port.get("is_cyclic") and len(coordinates) > 2:
            port_edges.append((offset + len(coordinates) - 1, offset))
    port_mesh = bpy.data.meshes.new("HST_PhaseC_SetbackPorts_Mesh")
    port_mesh.from_pydata(port_coordinates, port_edges, [])
    port_mesh.update()
    port_object = bpy.data.objects.new("HST_PhaseC_SetbackPorts", port_mesh)
    port_object.matrix_world = source_object.matrix_world.copy()
    port_object.display_type = "WIRE"
    port_object.show_in_front = True
    port_object.color = (1.0, 0.0, 0.0, 1.0)
    collection.objects.link(port_object)
    port_material = bpy.data.materials.new("HST_PhaseC_Setback_Red")
    port_material.diffuse_color = (1.0, 0.0, 0.0, 1.0)
    port_object.data.materials.append(port_material)
    return regular_object, port_object


# 创建固定正交相机并渲染 Phase C overview 或 setback closeup。
# source_object/debug_objects/output_path/focus_points/radius: artifact 几何、输出路径、可选近景点与半径；返回 Camera/Light。
def render_phase_c_artifact(
    source_object,
    debug_objects,
    output_path,
    focus_points=None,
    radius=0.01,
):
    scene = bpy.context.scene
    if focus_points:
        world_points = [source_object.matrix_world @ Vector(point) for point in focus_points]
    else:
        world_points = [
            obj.matrix_world @ Vector(corner)
            for obj in (source_object, *debug_objects)
            for corner in obj.bound_box
        ]
    minimum = Vector(tuple(min(point[axis] for point in world_points) for axis in range(3)))
    maximum = Vector(tuple(max(point[axis] for point in world_points) for axis in range(3)))
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    scale = max(max(extent), radius * 8.0, 0.01)
    camera_data = bpy.data.cameras.new("HST_PhaseC_ArtifactCamera")
    camera = bpy.data.objects.new("HST_PhaseC_ArtifactCamera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale * 1.35
    direction = Vector((1.0, -1.0, 0.8)).normalized()
    camera.location = center + direction * scale * 2.5
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    light_data = bpy.data.lights.new("HST_PhaseC_ArtifactLight", type="AREA")
    light_data.energy = 1200.0
    light_data.shape = "DISK"
    light_data.size = scale * 2.0
    light = bpy.data.objects.new("HST_PhaseC_ArtifactLight", light_data)
    scene.collection.objects.link(light)
    light.location = camera.location
    light.rotation_euler = camera.rotation_euler
    scene.render.engine = "BLENDER_EEVEE"
    source_object.hide_render = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_path)
    scene.world.color = (0.035, 0.035, 0.035)
    bpy.ops.render.render(write_still=True)
    return camera, light


# 删除 Phase C artifact 临时 Objects、Mesh、Material、Camera 与 Light，避免污染 repetition 检查。
# objects: create/render helpers 创建的 ID Objects；无返回值。
def cleanup_phase_c_debug_objects(objects):
    for obj in objects:
        data = obj.data
        object_type = obj.type
        if bpy.data.objects.get(obj.name) == obj:
            bpy.data.objects.remove(obj, do_unlink=True)
        if data.users:
            continue
        if object_type == "MESH":
            bpy.data.meshes.remove(data)
        elif object_type == "CAMERA":
            bpy.data.cameras.remove(data)
        elif object_type == "LIGHT":
            bpy.data.lights.remove(data)


# 生成稳定 case ID，供目录与汇总引用。
# fixture_label/object_name/radius: matrix cell 三个维度；返回可作目录名的字符串。
def case_id(fixture_label, object_name, radius):
    safe_object_name = object_name.lower().replace(" ", "_").replace(".", "_")
    radius_token = f"{radius:.3f}".replace(".", "p")
    return f"{fixture_label}__{safe_object_name}__r{radius_token}"


# 原子刷新 matrix summary，Blender 异常退出前保留已完成证据。
# summary: 当前 matrix 完整状态；无返回值。
def write_summary(summary):
    ARTIFACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 把 Preview Pipe contract 或 owned Curve points 规范化为方向无关 signature。
# entries/points_key/cyclic_key: pipe/spline records 与字段名；返回稳定 tuple。
def curve_contract_signature(entries, points_key, cyclic_key):
    signatures = []
    for entry in entries:
        raw_points = tuple(entry[points_key])
        points = tuple(
            tuple(round(float(component), 6) for component in point[:3])
            for point in raw_points
        )
        signatures.append((min(points, tuple(reversed(points))), bool(entry[cyclic_key])))
    return tuple(sorted(signatures))


# 从正式 PREVIEW Operator 运行隐藏 batched Adapter，并读取 scene diagnostics。
# addon_module/fixture/object/radius/case/repetition: matrix cell 上下文；返回稳定 repetition 记录。
def run_repetition(
    addon_module,
    fixture_path,
    object_name,
    radius,
    case_directory,
    repetition_index,
):
    open_result = bpy.ops.wm.open_mainfile(
        filepath=str(fixture_path),
        load_ui=False,
        use_scripts=False,
    )
    if open_result != {"FINISHED"}:
        raise RuntimeError(f"Failed to open fixture: {fixture_path}")
    source_object = bpy.data.objects.get(object_name)
    if source_object is None or source_object.type != "MESH":
        raise RuntimeError(f"Fixture Object missing or not Mesh: {object_name}")
    fingerprint_before = addon_module.utils.feature_chamfer_gn_utils.source_fingerprint(
        source_object
    )
    activate_source(source_object)
    preview_result = sorted(
        bpy.ops.hst.feature_chamfer_gn(
            "INVOKE_DEFAULT",
            action="PREVIEW",
            radius=radius,
        )
    )
    if preview_result != ["FINISHED"]:
        raise RuntimeError(f"Preview failed: {preview_result}")
    preview_modifier = source_object.modifiers.get("HST Feature Chamfer GN Preview")
    preview_plan = addon_module.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        preview_modifier
    )
    preview_utils = addon_module.utils.feature_chamfer_gn_utils
    owned_curve = preview_utils.owned_preview_curve(source_object)
    if owned_curve is None:
        raise RuntimeError("Preview did not retain its owned Curve")
    contract = json.loads(
        owned_curve[addon_module.const.FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG]
    )
    curve_entries = [
        {
            "points": [tuple(point.co[:3]) for point in spline.points],
            "cyclic": spline.use_cyclic_u,
        }
        for spline in owned_curve.data.splines
    ]
    contract_matches_curve = (
        contract.get("contract") == "GN_PREVIEW_PIPE_V1"
        and contract.get("plan_id") == preview_plan.plan_id
        and contract.get("source_fingerprint") == fingerprint_before
        and curve_contract_signature(contract.get("pipes", []), "points", "is_cyclic")
        == curve_contract_signature(curve_entries, "points", "cyclic")
    )
    if repetition_index == 0:
        save_artifact_copy(case_directory / "preview.blend")
    batched_module = addon_module.utils.feature_chamfer_batched_finalize_utils
    if hasattr(batched_module, "_build_preview_feature_graph"):
        raise RuntimeError("Batched backend still imports secondary Preview grouping")
    activate_source(source_object)
    adapter_result = sorted(
        bpy.ops.hst.experimental_feature_chamfer_batched_finalize(
            "INVOKE_DEFAULT",
            debug_stage=DEBUG_STAGE,
        )
    )
    diagnostics = json.loads(
        bpy.context.scene.get("hst_feature_chamfer_batched_last_result", "{}")
    )
    if DEBUG_STAGE == "PHASE_C_REGULAR_CORE" and repetition_index == 0:
        case_directory.mkdir(parents=True, exist_ok=True)
        debug_collection = bpy.data.collections.new("HST_PhaseC_DebugArtifacts")
        bpy.context.scene.collection.children.link(debug_collection)
        debug_objects = create_phase_c_debug_objects(
            source_object,
            diagnostics,
            debug_collection,
        )
        camera = None
        light = None
        try:
            ledger_artifact = {
                "contract": "HST_PHASE_C_LEDGER_V1",
                "plan_id": diagnostics.get("plan_id"),
                "boundary_edge_ledger": diagnostics.get("boundary_edge_ledger", []),
                "setback_ports": diagnostics.get("junction_regions", []),
                "forward_geometry_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_geometry_fingerprint"),
                "reverse_geometry_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_reverse_geometry_fingerprint"),
                "forward_ledger_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_ledger_fingerprint"),
                "reverse_ledger_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_reverse_ledger_fingerprint"),
                "forward_port_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_port_fingerprint"),
                "reverse_port_fingerprint": diagnostics.get(
                    "topology_diagnostics", {}
                ).get("phase_c_reverse_port_fingerprint"),
            }
            (case_directory / "ledger.json").write_text(
                json.dumps(ledger_artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            camera, light = render_phase_c_artifact(
                source_object,
                debug_objects,
                case_directory / "phase_c_regular_core_overview.png",
                radius=radius,
            )
            camera_data = camera.data
            light_data = light.data
            bpy.data.objects.remove(camera, do_unlink=True)
            if camera_data.users == 0:
                bpy.data.cameras.remove(camera_data)
            bpy.data.objects.remove(light, do_unlink=True)
            if light_data.users == 0:
                bpy.data.lights.remove(light_data)
            camera = None
            light = None
            setback_ports = diagnostics.get("junction_regions", [])
            if setback_ports:
                focus_port = sorted(
                    setback_ports,
                    key=lambda item: (
                        item.get("reason") != "PIPE_OVERLAP_SETBACK",
                        item.get("port_id", ""),
                    ),
                )[0]
                camera, light = render_phase_c_artifact(
                    source_object,
                    debug_objects,
                    case_directory / "phase_c_setback_closeup.png",
                    focus_points=focus_port["ordered_coordinates"],
                    radius=radius,
                )
                diagnostics.setdefault("topology_diagnostics", {})[
                    "artifact_closeup_port_id"
                ] = focus_port["port_id"]
            save_artifact_copy(case_directory / "phase_c_regular_core.blend")
        finally:
            cleanup_phase_c_debug_objects(
                (*debug_objects, *(obj for obj in (camera, light) if obj is not None))
            )
            if bpy.data.collections.get(debug_collection.name) == debug_collection:
                bpy.data.collections.remove(debug_collection)
    fingerprint_after = addon_module.utils.feature_chamfer_gn_utils.source_fingerprint(
        source_object
    )
    source_unchanged = fingerprint_before == fingerprint_after
    pipe_ids = [spec["pipe_id"] for spec in diagnostics.get("pipe_specs", [])]
    colored_pipe_ids = [
        pipe_id
        for batch in diagnostics.get("color_batches", [])
        for pipe_id in batch
    ]
    topology_diagnostics = diagnostics.get("topology_diagnostics", {})
    real_cut_invariant = (
        topology_diagnostics.get("real_cut_probe") is True
        and topology_diagnostics.get("cut_strategy") == "INDEPENDENT_STAGING"
        and topology_diagnostics.get("batch_order_invariant") is True
        and topology_diagnostics.get("forward_reverse_built_independently") is True
        and topology_diagnostics.get("forward_cut_signature")
        == topology_diagnostics.get("reverse_cut_signature")
        and topology_diagnostics.get("forward_cut_signature")
        != diagnostics.get("batch_order_invariance_fingerprint")
        and topology_diagnostics.get("forward_cut_batch_count")
        == len(diagnostics.get("color_batches", []))
        and topology_diagnostics.get("reverse_cut_batch_count")
        == len(diagnostics.get("color_batches", []))
    )
    phase_c_diagnostics = diagnostics.get("topology_diagnostics", {})
    # 按 correspondence/component 统计 unresolved，避免左右两侧诊断重复计数。
    # phase_c_diagnostics: backend Phase C diagnostics；返回值用于严格门禁。
    unresolved_remote_component_ids = {
        (
            attempt["correspondence_id"],
            unresolved.get("component_id")
            or unresolved.get("atom_id")
            or hashlib.sha256(
                json.dumps(
                    {
                        "left": unresolved.get("left_run_ids", ()),
                        "right": unresolved.get("right_run_ids", ()),
                        "reason": unresolved.get("reason"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20],
        )
        for attempt in phase_c_diagnostics.get("strip_attempts", [])
        for unresolved in attempt.get("unresolved_components", [])
    }
    unresolved_remote_component_count = len(unresolved_remote_component_ids)
    deferred_attempt_count = sum(
        attempt.get("status") == "DEFERRED"
        for attempt in phase_c_diagnostics.get("strip_attempts", [])
    )
    phase_c_pass = (
        phase_c_diagnostics.get("regular_core_count", 0) > 0
        and phase_c_diagnostics.get("real_regular_strip_face_count", 0) > 0
        and phase_c_diagnostics.get("unresolved_span_count") == 0
        and phase_c_diagnostics.get("all_ledger_edges_consumed_once") is True
        and phase_c_diagnostics.get("unclassified_boundary_edge_count") == 0
        and phase_c_diagnostics.get("invalid_ledger_classification_count") == 0
        and phase_c_diagnostics.get("orphan_ledger_consumer_count") == 0
        and phase_c_diagnostics.get("consumer_edge_mismatch_count") == 0
        and phase_c_diagnostics.get("outside_plan_regular_edge_count") == 0
        and phase_c_diagnostics.get("outside_plan_wrong_reason_count") == 0
        and phase_c_diagnostics.get("phase_c_boundary_order_invariant") is True
        and phase_c_diagnostics.get("phase_c_regular_order_invariant") is True
        and phase_c_diagnostics.get("strip_geometry_guard", {}).get("status")
        == "PASS"
        and phase_c_diagnostics.get("phase_c_geometry_fingerprint")
        == phase_c_diagnostics.get("phase_c_reverse_geometry_fingerprint")
        and phase_c_diagnostics.get("phase_c_ledger_fingerprint")
        == phase_c_diagnostics.get("phase_c_reverse_ledger_fingerprint")
        and phase_c_diagnostics.get("phase_c_port_fingerprint")
        == phase_c_diagnostics.get("phase_c_reverse_port_fingerprint")
        and phase_c_diagnostics.get("cross_pipe_owner_guessing") is False
        and phase_c_diagnostics.get("global_fill") is False
        and unresolved_remote_component_count == 0
        and deferred_attempt_count == 0
        and bool(diagnostics.get("boundary_edge_ledger"))
    )
    valid = (
        adapter_result == ["FINISHED"]
        and diagnostics.get("backend_id") == "BATCHED_CUT_FILL_V1"
        and diagnostics.get("plan_id") == preview_plan.plan_id
        and diagnostics.get("topology_diagnostics", {}).get(
            "all_pipes_colored_once"
        )
        and diagnostics.get("topology_diagnostics", {}).get(
            "batch_internal_overlap_count"
        )
        == 0
        and sorted(colored_pipe_ids) == sorted(pipe_ids)
        and len(colored_pipe_ids) == len(set(colored_pipe_ids))
        and contract_matches_curve
        and real_cut_invariant
        and source_unchanged
        and not diagnostics.get("failure_code")
        and (
            DEBUG_STAGE != "PHASE_C_REGULAR_CORE"
            or phase_c_pass
        )
    )
    return {
        "repetition": repetition_index + 1,
        "status": "PASS" if valid else "FAIL",
        "preview_result": preview_result,
        "adapter_result": adapter_result,
        "failure_code": diagnostics.get("failure_code"),
        "failure_message": diagnostics.get("message"),
        "source_unchanged": source_unchanged,
        "preview_contract_matches_owned_curve": contract_matches_curve,
        "plan_id": preview_plan.plan_id,
        "preview_pipe_contract_fingerprint": diagnostics.get(
            "preview_pipe_contract_fingerprint"
        ),
        "phase_a_pass": (
            contract_matches_curve
            and source_unchanged
            and contract.get("contract") == "GN_PREVIEW_PIPE_V1"
            and contract.get("plan_id") == preview_plan.plan_id
            and contract.get("source_fingerprint") == fingerprint_before
            and bool(contract.get("pipes"))
        ),
        "phase_b_pass": real_cut_invariant,
        "phase_c_pass": phase_c_pass if DEBUG_STAGE == "PHASE_C_REGULAR_CORE" else None,
        "pipe_ids": pipe_ids,
        "overlap_pairs": diagnostics.get("overlap_pairs", []),
        "color_batches": diagnostics.get("color_batches", []),
        "batch_order_invariance_fingerprint": diagnostics.get(
            "batch_order_invariance_fingerprint"
        ),
        "phase_c_boundary_universe_fingerprint": phase_c_diagnostics.get(
            "phase_c_boundary_universe_fingerprint"
        ),
        "phase_c_rail_chain_fingerprint": phase_c_diagnostics.get(
            "phase_c_rail_chain_fingerprint"
        ),
        "phase_c_geometry_fingerprint": phase_c_diagnostics.get(
            "phase_c_geometry_fingerprint"
        ),
        "phase_c_ledger_fingerprint": phase_c_diagnostics.get(
            "phase_c_ledger_fingerprint"
        ),
        "phase_c_port_fingerprint": phase_c_diagnostics.get(
            "phase_c_port_fingerprint"
        ),
        "topology_diagnostics": diagnostics.get("topology_diagnostics", {}),
        "debug_object_names": [
            obj.name
            for obj in bpy.data.objects
            if "FeatureChamferBatchedProbe" in obj.name
            or obj.name.startswith(f"{source_object.name}_Pipe_")
        ],
    }


# 执行 14 cells×3 repetitions 的 Phase A/B matrix 并强制稳定性门槛。
# 无参数；配置通过 host runner 环境变量传入。
def main():
    if REPETITIONS < 1:
        raise RuntimeError("Batched matrix requires at least one repetition")
    full_gate_eligible = not CASE_FILTER and REPETITIONS >= 3
    actual_hashes = {
        fixture_name: file_sha256(FIXTURE_DIRECTORY / fixture_name)
        for fixture_name in FIXTURE_HASHES
    }
    if actual_hashes != FIXTURE_HASHES:
        raise RuntimeError(
            f"Feature Chamfer fixture SHA mismatch: {actual_hashes}"
        )
    addon_module = load_addon_module()
    addon_module.register()
    cases = [
        {
            "case_id": case_id(fixture_label, object_name, radius),
            "fixture": fixture_name,
            "object_name": object_name,
            "radius": radius,
            "repetitions": [],
        }
        for fixture_label, fixture_name, object_name in MATRIX_SOURCES
        for radius in MATRIX_RADII
    ]
    if CASE_FILTER:
        cases = [case for case in cases if case["case_id"] in CASE_FILTER]
        unknown_cases = CASE_FILTER - {case["case_id"] for case in cases}
        if unknown_cases:
            raise RuntimeError(f"Unknown batched matrix cases: {sorted(unknown_cases)}")
    summary = {
        "status": "running",
        "phase": "C" if DEBUG_STAGE == "PHASE_C_REGULAR_CORE" else "A_B",
        "run_scope": "PHASE_GATE_FULL" if full_gate_eligible else "DIAGNOSTIC_PARTIAL",
        "gate_eligible": full_gate_eligible,
        "blender_version": bpy.app.version_string,
        "requested_repetitions": REPETITIONS,
        "case_count": len(cases),
        "fixture_hashes": actual_hashes,
        "runtime_contract": (
            "hst.feature_chamfer_gn(PREVIEW) -> "
            f"hst.experimental_feature_chamfer_batched_finalize({DEBUG_STAGE})"
        ),
        "cases": cases,
    }
    write_summary(summary)
    for case in cases:
        case_directory = ARTIFACT_DIRECTORY / case["case_id"]
        case_started_ns = time.time_ns()
        fixture_path = FIXTURE_DIRECTORY / case["fixture"]
        for repetition_index in range(REPETITIONS):
            try:
                repetition = run_repetition(
                    addon_module,
                    fixture_path,
                    case["object_name"],
                    case["radius"],
                    case_directory,
                    repetition_index,
                )
            except Exception as error:
                repetition = {
                    "repetition": repetition_index + 1,
                    "status": "FAIL",
                    "error": "".join(
                        traceback.format_exception(
                            type(error), error, error.__traceback__
                        )
                    ),
                }
            case["repetitions"].append(repetition)
            case_directory.mkdir(parents=True, exist_ok=True)
            (case_directory / "diagnostics.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            write_summary(summary)
        stable_fields = (
            "plan_id",
            "preview_pipe_contract_fingerprint",
            "preview_contract_matches_owned_curve",
            "pipe_ids",
            "overlap_pairs",
            "color_batches",
            "batch_order_invariance_fingerprint",
            "phase_c_boundary_universe_fingerprint",
            "phase_c_rail_chain_fingerprint",
            "phase_c_geometry_fingerprint",
            "phase_c_ledger_fingerprint",
            "phase_c_port_fingerprint",
        )
        signatures = [
            tuple(json.dumps(item.get(field), sort_keys=True) for field in stable_fields)
            for item in case["repetitions"]
        ]
        case["stable"] = len(set(signatures)) == 1
        expected_phase_c_artifacts = (
            "phase_c_regular_core.blend",
            "ledger.json",
            "phase_c_regular_core_overview.png",
            "phase_c_setback_closeup.png",
        )
        case["phase_c_artifacts_present"] = (
            DEBUG_STAGE != "PHASE_C_REGULAR_CORE"
            or all(
                (case_directory / artifact_name).is_file()
                and (case_directory / artifact_name).stat().st_size > 0
                and (case_directory / artifact_name).stat().st_mtime_ns
                >= case_started_ns
                for artifact_name in expected_phase_c_artifacts
            )
        )
        case["status"] = (
            "PASS"
            if case["stable"]
            and all(item.get("status") == "PASS" for item in case["repetitions"])
            and all(not item.get("debug_object_names") for item in case["repetitions"])
            and case["phase_c_artifacts_present"]
            else "FAIL"
        )
        (case_directory / "diagnostics.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_summary(summary)
    summary.update(
        status="finished",
        passed_case_count=sum(case["status"] == "PASS" for case in cases),
        failed_case_count=sum(case["status"] != "PASS" for case in cases),
        phase_a_go=full_gate_eligible and all(
            case["stable"]
            and all(item.get("phase_a_pass") is True for item in case["repetitions"])
            for case in cases
        ),
        phase_b_go=full_gate_eligible and all(
            case["stable"]
            and all(item.get("phase_b_pass") is True for item in case["repetitions"])
            for case in cases
        ),
        phase_c_go=(
            DEBUG_STAGE == "PHASE_C_REGULAR_CORE"
            and full_gate_eligible
            and len(cases) == 14
            and all(
                case["stable"]
                and case["phase_c_artifacts_present"]
                and all(item.get("phase_c_pass") is True for item in case["repetitions"])
                for case in cases
            )
        ),
    )
    write_summary(summary)
    print(
        "[HST_FEATURE_CHAMFER_BATCHED_MATRIX] "
        + json.dumps(
            {
                "phase_a_go": summary["phase_a_go"],
                "phase_b_go": summary["phase_b_go"],
                "phase_c_go": summary["phase_c_go"],
                "passed_case_count": summary["passed_case_count"],
                "failed_case_count": summary["failed_case_count"],
            },
            ensure_ascii=False,
        )
    )
    try:
        addon_module.unregister()
    except Exception:
        traceback.print_exc()
    diagnostic_pass = all(case["status"] == "PASS" for case in cases)
    if (
        DEBUG_STAGE == "PHASE_C_REGULAR_CORE"
        and full_gate_eligible
        and not summary["phase_c_go"]
    ):
        raise SystemExit(1)
    if not full_gate_eligible and not diagnostic_pass:
        raise SystemExit(1)
    if DEBUG_STAGE != "PHASE_C_REGULAR_CORE" and not summary["phase_b_go"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
