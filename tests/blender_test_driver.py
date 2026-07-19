# -*- coding: utf-8 -*-
"""Blender-side regression test driver."""

import hashlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
import bmesh


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
ARTIFACT_DIR = Path(os.environ["HST_TEST_ARTIFACT_DIR"])
RESULTS_PATH = Path(os.environ["HST_TEST_RESULTS"])
PACKAGE_NAME = "hst_test_addon"


class TestFailure(AssertionError):
    pass


class TestCaseResult:
    def __init__(self, name: str):
        self.name = name
        self.status = "passed"
        self.details = []
        self.error = None

    def add_detail(self, message: str):
        self.details.append(message)

    def fail(self, error: Exception):
        self.status = "failed"
        self.error = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    def to_dict(self):
        return {
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "error": self.error,
        }


class TestContext:
    def __init__(self, addon_module):
        self.addon = addon_module
        self.const = addon_module.const
        self.results = []

    def run_case(self, name, callback):
        result = TestCaseResult(name)
        try:
            reset_scene()
            callback(self, result)
        except Exception as error:
            result.fail(error)
        self.results.append(result)


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


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"


def ensure(condition: bool, message: str):
    if not condition:
        raise TestFailure(message)


def make_collection(name: str):
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def ensure_object_in_collection(obj, collection):
    """确保对象只链接到指定 Collection。

    Args:
        obj: 目标 Blender Object。
        collection: 目标 Blender Collection。
    """
    if collection in obj.users_collection:
        return obj

    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def make_test_mesh(name: str, collection, location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    return ensure_object_in_collection(obj, collection)


def make_edge_network(name: str, collection, vertices, edges):
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, edges, [])
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    return obj


def mesh_topology_hash(obj):
    """返回可比较的 Mesh 坐标与拓扑快照。

    Args:
        obj: 待快照的 Blender Mesh Object。
    """
    return (
        tuple(tuple(round(value, 8) for value in vertex.co) for vertex in obj.data.vertices),
        tuple(tuple(edge.vertices) for edge in obj.data.edges),
        tuple(tuple(polygon.vertices) for polygon in obj.data.polygons),
    )


def select_edge_indices_in_edit_mode(obj, edge_indices):
    """进入 Edit Mode 并只选择指定 Edge。

    Args:
        obj: 目标 Blender Mesh Object。
        edge_indices: 待选择的 Edge 索引集合。
    """
    select_objects(obj, [obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    for edge_index in edge_indices:
        bm.edges[edge_index].select = True
    bmesh.update_edit_mesh(obj.data)


def cube_top_loop_edge_indices(obj):
    """返回 cube 顶面 perimeter 的 Edge 索引。

    Args:
        obj: 默认 cube Mesh Object。
    """
    return [edge.index for edge in obj.data.edges if all(obj.data.vertices[index].co.z > 0.0 for index in edge.vertices)]


def mark_all_edges_sharp(obj):
    """把目标 Mesh 的全部 Edge 标记为 Sharp。

    Args:
        obj: 待标记的 Blender Mesh Object。
    """
    sharp_attribute = obj.data.attributes.get("sharp_edge")
    if sharp_attribute is None:
        sharp_attribute = obj.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
    for edge in obj.data.edges:
        edge.use_edge_sharp = True
        sharp_attribute.data[edge.index].value = True


def ensure_edge_float_attribute(obj, attribute_name: str, default_value: float = 1.0):
    attribute = obj.data.attributes.get(attribute_name)
    if attribute is None:
        attribute = obj.data.attributes.new(attribute_name, type="FLOAT", domain="EDGE")
    for edge in obj.data.edges:
        attribute.data[edge.index].value = default_value
    return attribute


def add_weight_bevel_modifier(obj, const, width: float = 0.1, attribute_name: str = "bevel_weight_edge"):
    bevel_modifier = obj.modifiers.new(name=const.BEVEL_MODIFIER, type="BEVEL")
    bevel_modifier.limit_method = "WEIGHT"
    bevel_modifier.edge_weight = attribute_name
    bevel_modifier.width = width
    bevel_modifier.offset_type = "WIDTH"
    return bevel_modifier


def make_plane(name: str, collection, location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_plane_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    return ensure_object_in_collection(obj, collection)


def make_empty(name: str, collection, location=(0.0, 0.0, 0.0)):
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=location)
    obj = bpy.context.active_object
    obj.name = name
    return ensure_object_in_collection(obj, collection)


def make_armature(name: str, collection):
    bpy.ops.object.armature_add()
    armature = bpy.context.active_object
    armature.name = name
    return ensure_object_in_collection(armature, collection)


def select_vertices_in_edit_mode(obj):
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    for vert in bm.verts:
        vert.select = True
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")


def select_objects(active_obj, selected_objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in selected_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active_obj


# 构造在一个 Vertex 相交的两条 Feature strands，模拟 CAD 圆柱交叠后的 degree-4 Sharp junction。


# 加载测试 fixtures 目录下的 .blend 文件。
# name: fixture 文件名；返回当前 Scene。
def load_fixture_blend(name: str):
    path = REPO_ROOT / "tests" / "fixtures" / name
    ensure(path.exists(), f"Fixture blend not found: {path}")
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return bpy.context.scene


# 生成 Mesh 的稳定指纹，用于断言真实 fixture 未发生变动。
# obj: Mesh Object。
def _mesh_fingerprint(obj):
    mesh = obj.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    fingerprint_payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in mesh.vertices],
        "edges": [tuple(edge.vertices) for edge in mesh.edges],
        "polygons": [tuple(polygon.vertices) for polygon in mesh.polygons],
        "sharp_edges": [
            edge.index
            for edge in mesh.edges
            if sharp_attribute is not None and sharp_attribute.data[edge.index].value
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return fingerprint


# 验证用户 tricky_b fixture 中真实对象 Extruded.002 的 PATCHED 成功。
# test_context: 已加载的 add-on 测试上下文；result: 当前测试结果记录器。
def test_pipe_chamfer_tricky_b_extruded002_regression(test_context: TestContext, result: TestCaseResult):
    load_fixture_blend("pipe-chamfer-test-tricky_b.blend")
    obj = bpy.data.objects.get("Extruded.002")
    ensure(obj is not None, "Extruded.002 not found in fixture")
    ensure(obj.type == "MESH", "Extruded.002 is not a Mesh")

    expected_fingerprint = "f62100103b6926528efde370610db3f015d41c900b972b7e21a374f5abae22f8"
    ensure(
        _mesh_fingerprint(obj) == expected_fingerprint,
        f"Mesh fingerprint mismatch: {_mesh_fingerprint(obj)}",
    )
    ensure(len(obj.data.vertices) == 371, f"Unexpected vertex count: {len(obj.data.vertices)}")
    ensure(len(obj.data.edges) == 552, f"Unexpected edge count: {len(obj.data.edges)}")
    ensure(len(obj.data.polygons) == 183, f"Unexpected face count: {len(obj.data.polygons)}")

    sharp_attribute = obj.data.attributes.get("sharp_edge")
    sharp_count = sum(
        1 for edge in obj.data.edges
        if sharp_attribute is not None and sharp_attribute.data[edge.index].value
    )
    ensure(sharp_count == 324, f"Expected 324 sharp edges, got {sharp_count}")

    select_objects(obj, [obj])
    bpy.context.view_layer.objects.active = obj
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=obj,
        radius=0.05,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="PATCHED",
        keep_debug_objects=False,
    )
    ensure(
        stats["status"] == "finished",
        f"Feature Chamfer did not finish on Extruded.002: {stats.get('error_message', 'unknown')}",
    )

    output = bpy.data.objects.get(stats["output_object_name"])
    ensure(output is not None, "PATCHED output object not found")
    risks = utils._mesh_risk_counts(output)
    ensure(risks["boundary"] == 0, f"Boundary edges after PATCHED: {risks['boundary']}")
    ensure(risks["non_manifold"] == 0, f"Non-manifold edges after PATCHED: {risks['non_manifold']}")
    ensure(risks["zero_area"] == 0, f"Zero-area faces after PATCHED: {risks['zero_area']}")
    source_fingerprint_after = _mesh_fingerprint(obj)
    ensure(
        source_fingerprint_after == expected_fingerprint,
        "Source Mesh fingerprint changed during PATCHED",
    )
    topology_payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in output.data.vertices],
        "edges": [tuple(edge.vertices) for edge in output.data.edges],
        "polygons": [tuple(polygon.vertices) for polygon in output.data.polygons],
    }
    topology_hash = hashlib.sha256(
        json.dumps(topology_payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    ensure(
        topology_hash == "9ec6d981458b4929842581c047d2920f6535496bb19ebe3a15674c89615775c6",
        f"Unexpected PATCHED topology hash: {topology_hash}",
    )
    result.add_detail(
        f"Extruded.002 PATCHED with clean topology; topology_hash={topology_hash}"
    )


# name: Mesh Object 名称；collection: 输出 Collection。
def make_crossing_feature_strands(name: str, collection):
    vertices = [
        (0.0, 0.0, 0.05),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, -1.0),
    ]
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (0, 3, 4),
        (0, 4, 1),
        (5, 2, 1),
        (5, 3, 2),
        (5, 4, 3),
        (5, 1, 4),
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    sharp_attribute = mesh_data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
    for edge in mesh_data.edges:
        sharp_attribute.data[edge.index].value = 0 in edge.vertices
    return obj


def collect_hst_operator_idnames(test_context: TestContext):
    operator_idnames = set()
    for module in test_context.addon.auto_load.modules:
        for value in module.__dict__.values():
            if inspect.isclass(value) and issubclass(value, bpy.types.Operator):
                bl_idname = getattr(value, "bl_idname", "")
                if bl_idname.startswith("hst."):
                    operator_idnames.add(bl_idname)
    return sorted(operator_idnames)


def test_addon_registers(test_context: TestContext, result: TestCaseResult):
    ensure(hasattr(bpy.types.Scene, "hst_params"), "Scene.hst_params was not registered")

    operator_idnames = collect_hst_operator_idnames(test_context)
    missing = []
    for operator_idname in operator_idnames:
        _, operator_name = operator_idname.split(".", 1)
        if not hasattr(bpy.ops.hst, operator_name):
            missing.append(operator_idname)

    ensure(not missing, f"Missing registered operators: {missing}")
    pipe_chamfer_operator = bpy.ops.hst.experimental_pipe_chamfer.get_rna_type()
    ensure(
        pipe_chamfer_operator.properties["debug_stage"].default == "PATCHED",
        "Experimental Pipe Chamfer must default to PATCHED",
    )
    ensure(hasattr(bpy.ops.hst, "hst_addtransvertcolorproxy"), "Proxy operator missing")
    ensure(hasattr(bpy.ops.hst, "hst_bakeproxyvertcolrao"), "AO bake operator missing")
    result.add_detail(f"Blender version: {bpy.app.version_string}")
    result.add_detail(f"Registered hst operators: {len(operator_idnames)}")


# 验证异常残留的 Scene PointerProperty 会在下一次 register 前被安全替换。
# test_context: 已加载的 add-on 测试上下文；result: 当前测试结果记录器。
def test_scene_params_stale_pointer_recovery_regression(test_context: TestContext, result: TestCaseResult):
    stale_params_type = type(
        "HSTStaleParamsProbe",
        (bpy.types.PropertyGroup,),
        {"__annotations__": {"probe": bpy.props.BoolProperty(default=True)}},
    )
    bpy.utils.register_class(stale_params_type)
    bpy.types.Scene.hst_params = bpy.props.PointerProperty(type=stale_params_type)
    bpy.utils.unregister_class(stale_params_type)

    test_context.addon._register_scene_properties()

    params = bpy.context.scene.hst_params
    ensure(len(params.vertexcolor) == 4, "Stale Scene pointer was not replaced with UIParams")
    result.add_detail("Stale Scene.hst_params was replaced before add-on registration")


# 验证 degree-4 junction 只在切向与 Surface Patch 上下文唯一时连接为两条 strand。
# test_context: 已加载的 add-on 测试上下文；result: 当前测试结果记录器。
def test_pipe_chamfer_degree_four_strand_pairing_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("PipeChamferStrandPairingCase")
    obj = make_crossing_feature_strands("CrossingFeatureStrands", collection)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(obj, 0.05, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")

    groups = utils._build_feature_graph(obj, 35.0, 3.0, stats)

    ensure(len(groups) == 2, f"Expected 2 paired Feature strands, got {len(groups)}")
    ensure(stats["topology_junction_count"] == 5, "Expected one degree-4 junction and four strand endpoints")
    ensure(stats["pipe_group_count"] == 2, f"Expected 2 Pipe Groups, got {stats['pipe_group_count']}")
    ensure(all(not group["is_cyclic"] for group in groups), "Degree-4 crossing unexpectedly produced cyclic strands")
    ensure(sorted(len(group["edge_indices"]) for group in groups) == [2, 2], "Unexpected strand edge counts")
    grouped_edges = [edge_index for group in groups for edge_index in group["edge_indices"]]
    sharp_attribute = obj.data.attributes["sharp_edge"]
    sharp_edges = {edge.index for edge in obj.data.edges if sharp_attribute.data[edge.index].value}
    ensure(len(grouped_edges) == len(set(grouped_edges)), "Feature strand pairing reused a Sharp Edge")
    ensure(set(grouped_edges) == sharp_edges, "Feature strand pairing did not consume every Sharp Edge")
    endpoint_pairs = {
        frozenset((group["vertex_indices"][0], group["vertex_indices"][-1]))
        for group in groups
    }
    ensure(endpoint_pairs == {frozenset((1, 3)), frozenset((2, 4))}, f"Incorrect strand pairing: {endpoint_pairs}")
    ensure(stats["open_pipe_count"] == 2, f"Expected 2 open Pipes, got {stats['open_pipe_count']}")
    ensure(stats["closed_pipe_count"] == 0, f"Expected no closed Pipes, got {stats['closed_pipe_count']}")
    result.add_detail("Degree-4 crossing preserved two opposite Feature strands")


# 验证几何失败仍保留为可重做操作，使 Adjust Last Operation 可修改 Feature Chamfer 参数。
# test_context: 已加载的 add-on 测试上下文；result: 当前测试结果记录器。
def test_pipe_chamfer_failure_keeps_redo_panel_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("PipeChamferRedoCase")
    obj = make_test_mesh("PipeChamferNoSharp", collection)
    select_objects(obj, [obj])
    operator_result = bpy.ops.hst.experimental_pipe_chamfer(
        "INVOKE_DEFAULT",
        radius=0.05,
        pipe_resolution=8,
    )
    operator_rna = bpy.ops.hst.experimental_pipe_chamfer.get_rna_type()

    ensure("FINISHED" in operator_result, "Feature Chamfer failure did not preserve Adjust Last Operation")
    ensure(
        operator_rna.properties["radius"].is_skip_save,
        "Feature Chamfer Radius can inherit an unusable value from a previous run",
    )
    ensure(
        operator_rna.properties["pipe_resolution"].is_skip_save,
        "Feature Chamfer Pipe Resolution can inherit an unusable value from a previous run",
    )
    ensure(obj.name in bpy.data.objects, "Feature Chamfer failure removed the source Object")
    result.add_detail("Geometry failure returned FINISHED so parameters remain editable")


# 验证 Feature Chamfer GUI 执行会留下可用于用户现场对比的参数、代码路径和 Mesh 指纹。
# test_context: 已加载的 add-on 测试上下文；result: 当前测试结果记录器。
def test_pipe_chamfer_writes_diagnostic_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("PipeChamferDiagnosticCase")
    obj = make_test_mesh("PipeChamferDiagnosticNoSharp", collection)
    select_objects(obj, [obj])
    diagnostic_path = Path(tempfile.gettempdir()) / "hst_feature_chamfer_diagnostic.jsonl"
    diagnostic_path.unlink(missing_ok=True)

    operator_result = bpy.ops.hst.experimental_pipe_chamfer(
        "INVOKE_DEFAULT",
        radius=0.05,
        pipe_resolution=8,
    )

    ensure("FINISHED" in operator_result, "Feature Chamfer diagnostic probe did not finish")
    ensure(diagnostic_path.exists(), "Feature Chamfer diagnostic log was not written")
    records = [json.loads(line) for line in diagnostic_path.read_text(encoding="utf-8").splitlines()]
    ensure([record["event"] for record in records] == ["execute_start", "geometry_failure"], "Unexpected diagnostic events")
    start = records[0]
    ensure(abs(start["parameters"]["radius"] - 0.05) <= 1.0e-6, "Diagnostic Radius does not match operator input")
    ensure(start["source"]["mesh_fingerprint"], "Diagnostic Mesh fingerprint is missing")
    ensure(start["operator_module"].endswith("experimental_pipe_chamfer_ops.py"), "Diagnostic operator source is missing")
    result.add_detail("Feature Chamfer wrote start/failure diagnostics with a Mesh fingerprint")

def test_transfer_proxy_reuse(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("ProxyReuseCase")
    obj = make_test_mesh("ProxyMesh", collection)
    select_objects(obj, [obj])

    first = bpy.ops.hst.hst_addtransvertcolorproxy()
    ensure("FINISHED" in first, "First proxy build did not finish")
    second = bpy.ops.hst.hst_addtransvertcolorproxy()
    ensure("FINISHED" in second, "Second proxy build did not finish")

    proxy_collections = [c for c in bpy.data.collections if c.name == const.TRANSFER_PROXY_COLLECTION]
    ensure(len(proxy_collections) == 1, f"Expected 1 proxy collection, got {len(proxy_collections)}")

    proxy_objects = [o for o in bpy.data.objects if o.name.startswith(const.TRANSFERPROXY_PREFIX)]
    ensure(len(proxy_objects) == 1, f"Expected 1 proxy object, got {len(proxy_objects)}")
    ensure(".00" not in proxy_objects[0].name and ".001" not in proxy_objects[0].name, "Proxy object got duplicate suffix")
    result.add_detail(f"Proxy object: {proxy_objects[0].name}")


def test_bevel_transfer_normal_collection_reuse(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("BevelTransferReuseCase")
    obj = make_test_mesh("BevelTransferMesh", collection)
    select_objects(obj, [obj])

    for run_index in range(2):
        bevel_result = bpy.ops.hst.hstbeveltransfernormal(
            bevel_width=0.2,
            bevel_segments=2,
        )
        ensure(
            "FINISHED" in bevel_result,
            f"Bevel transfer normal run {run_index + 1} did not finish",
        )

    transfer_collections = [
        collection for collection in bpy.data.collections
        if collection.name == const.TRANSFER_COLLECTION
        or collection.name.startswith(const.TRANSFER_COLLECTION + ".")
    ]
    ensure(len(transfer_collections) == 1, f"Expected 1 transfer collection, got {len(transfer_collections)}")

    transfer_objects = [obj for obj in bpy.data.objects if obj.name.startswith(const.TRANSFER_MESH_PREFIX)]
    ensure(len(transfer_objects) == 1, f"Expected 1 transfer object, got {len(transfer_objects)}")
    ensure(".00" not in transfer_objects[0].name, "Transfer object got duplicate suffix")
    result.add_detail(f"Transfer collection: {transfer_collections[0].name}")
    result.add_detail(f"Transfer object: {transfer_objects[0].name}")


def test_project_decal_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("DecalCase")
    target = make_plane("DecalTarget", collection, location=(0.0, 0.0, 0.0))
    decal = make_plane("DecalMesh", collection, location=(0.0, 0.0, 0.2))
    test_context.addon.utils.object_utils.Object.mark_hst_type(decal, "DECAL")

    select_objects(target, [target, decal])
    op_result = bpy.ops.hst.projectdecal()
    ensure("FINISHED" in op_result, "Project Decal operator did not finish")
    ensure(decal.modifiers.get(const.SUBD_MODIFIER) is not None, "Decal missing subdivision modifier")
    shrinkwrap = decal.modifiers.get(const.SHRINKWRAP_MODIFIER)
    ensure(shrinkwrap is not None, "Decal missing shrinkwrap modifier")
    ensure(shrinkwrap.target == target, "Shrinkwrap target does not match active object")
    result.add_detail(f"Decal modifiers: {list(decal.modifiers.keys())}")


def test_quickweight_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("QuickWeightCase")
    armature = make_armature("WeightRig", collection)
    mesh = make_test_mesh("WeightMesh", collection)

    select_objects(armature, [armature])
    bpy.ops.object.mode_set(mode="EDIT")
    active_bone = armature.data.edit_bones[0]
    active_bone.name = "root"
    bpy.ops.object.mode_set(mode="POSE")

    bpy.ops.object.mode_set(mode="OBJECT")
    select_objects(armature, [armature, mesh])
    bpy.ops.object.mode_set(mode="POSE")
    pose_bone = armature.pose.bones.get("root")
    ensure(pose_bone is not None, "Pose bone root not found")
    armature.data.bones.active = armature.data.bones[pose_bone.name]

    op_result = bpy.ops.hst.quickweight(mode='ALL_VERTS')
    ensure("FINISHED" in op_result, "QuickWeight operator did not finish")

    armature_modifier = None
    for modifier in mesh.modifiers:
        if modifier.type == 'ARMATURE' and modifier.object == armature:
            armature_modifier = modifier
            break
    ensure(armature_modifier is not None, "Mesh missing armature modifier after QuickWeight")

    vertex_group = mesh.vertex_groups.get("root")
    ensure(vertex_group is not None, "Vertex group for active bone was not created")
    ensure(len(mesh.data.vertices) > 0, "Weight test mesh has no vertices")
    weight = vertex_group.weight(0)
    ensure(abs(weight - 1.0) < 1e-6, f"Unexpected vertex weight: {weight}")
    result.add_detail(f"Mesh vertex groups: {[group.name for group in mesh.vertex_groups]}")


def test_ao_bake_operator_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("AOBakeCase")
    obj = make_test_mesh("AOBakeMesh", collection)
    select_objects(obj, [obj])

    bpy.ops.hst.hstbeveltransfernormal(bevel_width=0.2, bevel_segments=2)
    bake_result = bpy.ops.hst.hst_bakeproxyvertcolrao()
    ensure("FINISHED" in bake_result, "AO bake operator did not finish")

    transfer_modifier = obj.modifiers.get(const.COLOR_TRANSFER_MODIFIER)
    ensure(transfer_modifier is not None, "Color transfer modifier missing after AO bake")
    proxy_obj = transfer_modifier.object
    ensure(proxy_obj is not None, "AO bake proxy target missing")
    ensure(const.WEARMASK_ATTR in proxy_obj.data.color_attributes, "AO proxy missing WearMask attribute")
    ensure(obj.data.attributes.default_color_name == const.WEARMASK_ATTR, "Source mesh default color attribute not set")
    ensure(proxy_obj.data.attributes.default_color_name == const.WEARMASK_ATTR, "Proxy default color attribute not set")

    result.add_detail(f"AO proxy target: {proxy_obj.name}")
    result.add_detail(f"Proxy color attributes: {list(proxy_obj.data.color_attributes.keys())}")


def test_wearmask_proxy_topology_matches_transfer_target(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("AOTopologyCase")
    obj = make_test_mesh("AOMesh", collection)
    select_objects(obj, [obj])

    bpy.ops.hst.hstbeveltransfernormal(bevel_width=0.2, bevel_segments=2)
    bevel_modifier = obj.modifiers.get(const.BEVEL_MODIFIER)
    ensure(bevel_modifier is not None, "Bevel modifier was not added")

    base_vertex_count = len(obj.data.vertices)
    base_poly_count = len(obj.data.polygons)

    build_result = bpy.ops.hst.hst_addtransvertcolorproxy()
    ensure("FINISHED" in build_result, "Proxy build did not finish")

    transfer_modifier = obj.modifiers.get(const.COLOR_TRANSFER_MODIFIER)
    ensure(transfer_modifier is not None, "Color transfer modifier missing")
    proxy_obj = transfer_modifier.object
    ensure(proxy_obj is not None, "Color transfer modifier target missing")
    ensure(proxy_obj.name.startswith(const.TRANSFERPROXY_PREFIX), "Transfer target is not proxy mesh")

    proxy_vertex_count = len(proxy_obj.data.vertices)
    proxy_poly_count = len(proxy_obj.data.polygons)
    ensure(proxy_vertex_count > base_vertex_count, "Proxy mesh did not capture bevel topology")
    ensure(proxy_poly_count > base_poly_count, "Proxy mesh polygons did not increase after bevel")
    ensure(const.WEARMASK_ATTR in proxy_obj.data.color_attributes, "Proxy missing WearMask color attribute")
    ensure(const.WEARMASK_ATTR in obj.data.color_attributes, "Source mesh missing WearMask color attribute")

    result.add_detail(f"Base vertices/polys: {base_vertex_count}/{base_poly_count}")
    result.add_detail(f"Proxy vertices/polys: {proxy_vertex_count}/{proxy_poly_count}")


def test_set_bake_collection_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("BakeCollectionCase")
    obj = make_test_mesh("BakeMesh", collection)
    select_objects(obj, [obj])

    low_result = bpy.ops.hst.setbakecollectionlow()
    ensure("FINISHED" in low_result, "Set bake collection low did not finish")
    ensure(collection.get(const.HST_PROP) == "BAKE_LOW", f"Unexpected collection type: {collection.get(const.HST_PROP)}")
    ensure(collection.name.endswith(const.LOW_SUFFIX), f"Low collection suffix missing: {collection.name}")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(obj) == "STATICMESH", "Low mesh type was not set to STATICMESH")

    high_result = bpy.ops.hst.setbakecollectionhigh()
    ensure("FINISHED" in high_result, "Set bake collection high did not finish")
    ensure(collection.get(const.HST_PROP) == "BAKE_HIGH", f"Unexpected high collection type: {collection.get(const.HST_PROP)}")
    ensure(collection.name.endswith(const.HIGH_SUFFIX), f"High collection suffix missing: {collection.name}")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(obj) == "HIGH", "High mesh type was not set to HIGH")
    result.add_detail(f"Bake collection final name: {collection.name}")



def test_vertex_color_set_and_copy_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("VertexColorCase")
    source = make_test_mesh("SourceColorMesh", collection)
    target = make_test_mesh("TargetColorMesh", collection, location=(2.0, 0.0, 0.0))

    params = bpy.context.scene.hst_params
    params.vertexcolor = (0.2, 0.4, 0.6, 1.0)

    select_objects(source, [source])
    set_result = bpy.ops.hst.setobjectvertexcolor()
    ensure("FINISHED" in set_result, "Set object vertex color did not finish")
    ensure(const.BAKECOLOR_ATTR in source.data.color_attributes, "Source bake color attribute missing")

    select_objects(source, [source, target])
    copy_result = bpy.ops.hst.copy_vertex_color_from_active()
    ensure("FINISHED" in copy_result, "Copy vertex color from active did not finish")
    ensure(const.BAKECOLOR_ATTR in target.data.color_attributes, "Target bake color attribute missing")

    source_attr = source.data.color_attributes[const.BAKECOLOR_ATTR]
    target_attr = target.data.color_attributes[const.BAKECOLOR_ATTR]
    source_color = tuple(round(v, 4) for v in source_attr.data[0].color)
    target_color = tuple(round(v, 4) for v in target_attr.data[0].color)
    ensure(source_color == target_color, f"Copied color mismatch: {source_color} != {target_color}")
    result.add_detail(f"Copied bake color: {source_color}")



def test_collision_and_extract_ucx_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("CollisionCase")
    static_mesh = make_test_mesh("CollisionBase", collection)
    static_mesh_name = static_mesh.name
    ucx_mesh = make_test_mesh("CollisionProxy", collection, location=(2.0, 0.0, 0.0))

    select_objects(ucx_mesh, [ucx_mesh])
    set_result = bpy.ops.hst.add_ue_collision()
    ensure("FINISHED" in set_result, "Set UE collision did not finish")
    ensure(ucx_mesh.name.startswith("UCX_"), f"UCX rename failed: {ucx_mesh.name}")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(ucx_mesh) == "UCX", "UCX type not applied")

    extract_result = bpy.ops.hst.extractucx()
    ensure("FINISHED" in extract_result, "Extract UCX did not finish")
    ensure(static_mesh_name not in bpy.data.objects, "Static mesh should be removed by extract UCX")
    ensure(ucx_mesh.name.startswith("U_"), f"Extracted UCX rename failed: {ucx_mesh.name}")
    result.add_detail(f"Extracted UCX object: {ucx_mesh.name}")



def test_safe_bevel_weight_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("SafeBevelWeightCase")
    obj = make_edge_network(
        "SafeBevelWeightMesh",
        collection,
        [(0.0, 0.0, 0.0), (0.05, 0.0, 0.0), (1.05, 0.0, 0.0)],
        [(0, 1), (1, 2)],
    )
    ensure_edge_float_attribute(obj, "bevel_weight_edge", default_value=1.0)
    add_weight_bevel_modifier(obj, const, width=0.1)
    select_objects(obj, [obj])

    op_result = bpy.ops.hst.safe_bevel_weight(falloff_steps=0)
    ensure("FINISHED" in op_result, "Safe Bevel Weight operator did not finish")

    weights = obj.data.attributes["bevel_weight_edge"].data
    ensure(weights[0].value < 1.0, f"Expected short edge weight to be reduced, got {weights[0].value}")
    ensure(abs(weights[1].value - 1.0) < 1e-6, f"Unexpected change on non-risk edge: {weights[1].value}")
    result.add_detail(f"Safe bevel weights: {[round(item.value, 4) for item in weights]}")


def test_safe_bevel_weight_selected_only_regression(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("SafeBevelWeightSelectedOnlyCase")
    obj = make_edge_network(
        "SafeBevelWeightSelectedOnlyMesh",
        collection,
        [
            (0.0, 0.0, 0.0),
            (0.05, 0.0, 0.0),
            (1.05, 0.0, 0.0),
            (2.05, 0.0, 0.0),
            (2.10, 0.0, 0.0),
        ],
        [(0, 1), (1, 2), (2, 3), (3, 4)],
    )
    ensure_edge_float_attribute(obj, "bevel_weight_edge", default_value=1.0)
    add_weight_bevel_modifier(obj, const, width=0.1)
    for edge in obj.data.edges:
        edge.select = False
    obj.data.edges[0].select = True
    select_objects(obj, [obj])

    op_result = bpy.ops.hst.safe_bevel_weight(selected_only=True, falloff_steps=0)
    ensure("FINISHED" in op_result, "Safe Bevel Weight selected-only operator did not finish")

    weights = obj.data.attributes["bevel_weight_edge"].data
    ensure(weights[0].value < 1.0, f"Expected selected short edge weight to be reduced, got {weights[0].value}")
    ensure(abs(weights[3].value - 1.0) < 1e-6, f"Unselected short edge should stay unchanged, got {weights[3].value}")
    result.add_detail(f"Selected-only weights: {[round(item.value, 4) for item in weights]}")


def test_safe_bevel_weight_preserves_lower_user_weight_regression(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("SafeBevelWeightPreserveCase")
    obj = make_edge_network(
        "SafeBevelWeightPreserveMesh",
        collection,
        [(0.0, 0.0, 0.0), (0.05, 0.0, 0.0), (1.05, 0.0, 0.0)],
        [(0, 1), (1, 2)],
    )
    weights = ensure_edge_float_attribute(obj, "bevel_weight_edge", default_value=1.0)
    weights.data[0].value = 0.1
    add_weight_bevel_modifier(obj, const, width=0.1)
    select_objects(obj, [obj])

    op_result = bpy.ops.hst.safe_bevel_weight(falloff_steps=0, min_weight=0.2, aggressiveness=0.6)
    ensure("FINISHED" in op_result, "Safe Bevel Weight preserve-lower-weight operator did not finish")

    final_weight = obj.data.attributes["bevel_weight_edge"].data[0].value
    ensure(abs(final_weight - 0.1) < 1e-6, f"Expected user lower weight to be preserved, got {final_weight}")
    result.add_detail(f"Preserved lower weight: {round(final_weight, 4)}")


def test_safe_bevel_weight_missing_modifier_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("SafeBevelWeightMissingModifierCase")
    obj = make_edge_network(
        "SafeBevelWeightMissingModifierMesh",
        collection,
        [(0.0, 0.0, 0.0), (0.05, 0.0, 0.0), (1.05, 0.0, 0.0)],
        [(0, 1), (1, 2)],
    )
    ensure_edge_float_attribute(obj, "bevel_weight_edge", default_value=1.0)
    select_objects(obj, [obj])

    op_result = bpy.ops.hst.safe_bevel_weight()
    ensure("FINISHED" in op_result, "Safe Bevel Weight missing-modifier case did not finish")
    ensure(obj.modifiers.get(const.BEVEL_MODIFIER) is None, "Operator should not create missing bevel modifier")
    result.add_detail("Missing modifier object was skipped without creating HSTBevel")


def test_modifier_ops_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    collection = make_collection("ModifierCase")
    obj = make_test_mesh("ModifierMesh", collection)
    select_objects(obj, [obj])

    op_result = bpy.ops.hst.hstbevelmods(bevel_width=0.15, bevel_segments=2)
    ensure("FINISHED" in op_result, "Batch bevel modifiers did not finish")
    ensure(obj.modifiers.get(const.BEVEL_MODIFIER) is not None, "Bevel modifier missing")
    ensure(obj.modifiers.get(const.WEIGHTEDNORMAL_MODIFIER) is not None, "Weighted normal modifier missing")
    ensure(obj.modifiers.get(const.TRIANGULAR_MODIFIER) is not None, "Triangulate modifier missing")
    result.add_detail(f"Modifier stack: {list(obj.modifiers.keys())}")


def make_cat_meshgroup_instance(name: str, source_collection, location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name + "Mesh"
    modifier = obj.modifiers.new(name="CAT_MeshGroup", type="NODES")
    modifier["Socket_2"] = source_collection
    modifier["Socket_3"] = False
    return obj


def test_staticmeshexport_fbx_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("ExportCaseFBX")
    make_test_mesh("ExportMeshFBX", collection)

    export_dir = ARTIFACT_DIR / "exports" / "fbx"
    export_dir.mkdir(parents=True, exist_ok=True)

    params = bpy.context.scene.hst_params
    params.export_path = str(export_dir)
    params.export_format = "FBX"
    params.file_prefix = ""

    op_result = bpy.ops.hst.staticmeshexport()
    ensure("FINISHED" in op_result, "StaticMesh FBX export operator did not finish")

    export_file = export_dir / f"SM_{collection.name}.fbx"
    ensure(export_file.exists(), f"Expected FBX export not found: {export_file}")
    ensure(export_file.stat().st_size > 0, "Exported FBX file is empty")
    result.add_detail(f"FBX export: {export_file.name} ({export_file.stat().st_size} bytes)")


def test_staticmeshexport_current_scene_only_fbx(test_context: TestContext, result: TestCaseResult):
    current_collection = make_collection("CurrentSceneExportCase")
    make_test_mesh("CurrentSceneExportMesh", current_collection)

    other_scene = bpy.data.scenes.new("OtherExportScene")
    other_collection = bpy.data.collections.new("OtherSceneExportCase")
    other_scene.collection.children.link(other_collection)
    make_test_mesh("OtherSceneExportMesh", other_collection)

    export_dir = ARTIFACT_DIR / "exports" / "current_scene_only_fbx"
    export_dir.mkdir(parents=True, exist_ok=True)

    params = bpy.context.scene.hst_params
    params.export_path = str(export_dir)
    params.export_format = "FBX"
    params.file_prefix = ""

    op_result = bpy.ops.hst.staticmeshexport()
    ensure("FINISHED" in op_result, "Current Scene only FBX export did not finish")

    current_export_file = export_dir / "SM_CurrentSceneExportCase.fbx"
    other_export_file = export_dir / "SM_OtherSceneExportCase.fbx"
    ensure(current_export_file.exists(), f"Expected current Scene export not found: {current_export_file}")
    ensure(current_export_file.stat().st_size > 0, "Current Scene FBX file is empty")
    ensure(not other_export_file.exists(), "Collection from another Scene was exported")
    result.add_detail(f"Current Scene only export: {current_export_file.name}")


def test_staticmeshexport_cat_meshgroup_instance_fbx(test_context: TestContext, result: TestCaseResult):
    source_collection = bpy.data.collections.new("CatMeshGroupSource")
    make_test_mesh("CatMeshGroupSourceMesh", source_collection)

    instance = make_cat_meshgroup_instance("inst_CatMeshGroup", source_collection, location=(5.0, 2.0, 1.0))
    duplicate_instance = make_cat_meshgroup_instance("inst_CatMeshGroupDuplicate", source_collection, location=(9.0, 0.0, 0.0))
    original_matrix = instance.matrix_world.copy()
    duplicate_matrix = duplicate_instance.matrix_world.copy()
    modifier = instance.modifiers["CAT_MeshGroup"]

    export_dir = ARTIFACT_DIR / "exports" / "cat_meshgroup_fbx"
    export_dir.mkdir(parents=True, exist_ok=True)

    params = bpy.context.scene.hst_params
    params.export_path = str(export_dir)
    params.export_format = "FBX"
    params.file_prefix = ""

    op_result = bpy.ops.hst.staticmeshexport()
    ensure("FINISHED" in op_result, "CAT MeshGroup instance FBX export did not finish")

    export_file = export_dir / "SM_CatMeshGroup.fbx"
    duplicate_file = export_dir / "SM_CatMeshGroupDuplicate.fbx"
    prefixed_file = export_dir / "SM_inst_CatMeshGroup.fbx"
    ensure(export_file.exists(), f"Expected CAT MeshGroup FBX export not found: {export_file}")
    ensure(export_file.stat().st_size > 0, "Exported CAT MeshGroup FBX file is empty")
    ensure(not duplicate_file.exists(), "Duplicate source Collection instance was exported")
    ensure(not prefixed_file.exists(), "inst_ prefix was kept in exported filename")
    ensure(instance.matrix_world == original_matrix, "CAT MeshGroup instance transform was not restored")
    ensure(duplicate_instance.matrix_world == duplicate_matrix, "Duplicate CAT MeshGroup instance transform changed")
    ensure(modifier["Socket_3"] == False, "CAT MeshGroup Realize socket was not restored")
    result.add_detail(f"CAT MeshGroup FBX export: {export_file.name} ({export_file.stat().st_size} bytes)")


def test_staticmeshexport_glb_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("ExportCaseGLB")
    make_test_mesh("ExportMeshGLB", collection)

    export_dir = ARTIFACT_DIR / "exports" / "glb"
    export_dir.mkdir(parents=True, exist_ok=True)

    params = bpy.context.scene.hst_params
    params.export_path = str(export_dir)
    params.export_format = "GLB"
    params.file_prefix = ""

    op_result = bpy.ops.hst.staticmeshexport()
    ensure("FINISHED" in op_result, "StaticMesh GLB export operator did not finish")

    export_file = export_dir / f"SM_{collection.name}.glb"
    ensure(export_file.exists(), f"Expected GLB export not found: {export_file}")
    ensure(export_file.stat().st_size > 0, "Exported GLB file is empty")
    result.add_detail(f"GLB export: {export_file.name} ({export_file.stat().st_size} bytes)")


def test_rename_bones_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("RenameBonesCase")
    armature = make_armature("RenameRig", collection)

    select_objects(armature, [armature])
    bpy.ops.object.mode_set(mode="EDIT")
    root_bone = armature.data.edit_bones[0]
    root_bone.name = "Root.001"
    child_bone = armature.data.edit_bones.new("Spine.012")
    child_bone.head = (0.0, 0.0, 1.0)
    child_bone.tail = (0.0, 0.0, 2.0)
    child_bone.parent = root_bone
    bpy.ops.object.mode_set(mode="OBJECT")

    select_objects(armature, [armature])
    op_result = bpy.ops.hst.rename_bones()
    ensure("FINISHED" in op_result, "Rename Bones operator did not finish")

    bone_names = {bone.name for bone in armature.data.bones}
    ensure("root_01" in bone_names, f"Renamed root bone not found: {bone_names}")
    ensure("spine_12" in bone_names, f"Renamed child bone not found: {bone_names}")
    result.add_detail(f"Renamed bones: {sorted(bone_names)}")


def test_cleanup_ue_skm_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("CleanupUESKMCase")
    skeleton_root = make_empty("SK_Root", collection)
    skeleton_root.scale = (0.01, 0.01, 0.01)
    armature = make_armature("UE_Armature", collection)
    mesh = make_test_mesh("UE_Mesh", collection)
    armature.parent = skeleton_root
    mesh.parent = skeleton_root
    root_name = skeleton_root.name

    select_objects(skeleton_root, [skeleton_root])
    op_result = bpy.ops.hst.cleanup_ue_skm()
    ensure("FINISHED" in op_result, "Cleanup UE SKM operator did not finish")

    ensure(root_name not in bpy.data.objects, "UE skeleton root empty was not removed")
    ensure(armature.parent is None, "Armature parent was not cleared")
    ensure(mesh.parent is None, "Mesh parent was not cleared")
    ensure(armature.data.display_type == 'WIRE', "Armature display type was not updated")
    ensure(armature.show_in_front is True, "Armature was not set to in-front display")
    ensure(armature.data.show_axes is True, "Armature axes display was not enabled")
    ensure(bpy.context.scene.unit_settings.length_unit == 'CENTIMETERS', "Scene unit was not set for UE rig cleanup")
    result.add_detail(f"Cleanup kept objects: {[obj.name for obj in collection.objects]}")


def test_origin_and_transform_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("OriginCase")
    mesh_a = make_test_mesh("OriginMeshA", collection, location=(1.0, 1.0, 0.0))
    mesh_b = make_test_mesh("OriginMeshB", collection, location=(3.0, 1.0, 0.0))

    select_objects(mesh_a, [mesh_a, mesh_b])
    add_origin_result = bpy.ops.hst.add_asset_origin('INVOKE_DEFAULT')
    ensure("FINISHED" in add_origin_result, "Add asset origin did not finish")

    origin_objects = test_context.addon.utils.object_utils.Object.filter_hst_type(collection.all_objects, "ORIGIN", mode="INCLUDE")
    ensure(len(origin_objects) == 1, f"Expected 1 origin object, got {len(origin_objects)}")
    origin = origin_objects[0]
    ensure(mesh_a.parent == origin and mesh_b.parent == origin, "Meshes were not parented to asset origin")

    test_context.addon.utils.collection_utils.Collection.mark_hst_type(collection, "PROP")
    mesh_a.location = (0.13, 0.27, 0.41)
    mesh_a.rotation_euler = (0.3, 0.0, 0.8)
    mesh_a.scale = (1.13, 0.87, 1.22)
    select_objects(mesh_a, [mesh_a])

    snap_result = bpy.ops.hst.snap_transform(
        snap_location_toggle=True,
        snap_rotation_toggle=True,
        snap_scale_toggle=True,
        snap_grid='5',
        snap_rotation_step='45',
        snap_scale_step='0.125',
    )
    ensure("FINISHED" in snap_result, "Snap transform did not finish")
    ensure(abs(mesh_a.location.x - 0.15) < 1e-6, f"Unexpected snapped X location: {mesh_a.location.x}")
    ensure(abs(mesh_a.location.y - 0.25) < 1e-6, f"Unexpected snapped Y location: {mesh_a.location.y}")
    ensure(abs(mesh_a.scale.x - 1.125) < 1e-6, f"Unexpected snapped X scale: {mesh_a.scale.x}")

    reset_result = bpy.ops.hst.reset_prop_transform_to_origin()
    ensure("FINISHED" in reset_result, "Reset prop transform to origin did not finish")
    ensure(mesh_a.parent == origin, "Mesh parent changed after reset to origin")
    result.add_detail(f"Origin object: {origin.name}")
    result.add_detail(f"Snapped location: {tuple(round(v, 4) for v in mesh_a.location)}")



def test_collection_markers_smoke(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    prop_collection = make_collection("PropMarkerCase")
    prop_obj = make_test_mesh("PropMesh", prop_collection)
    select_objects(prop_obj, [prop_obj])

    prop_result = bpy.ops.hst.markpropcollection()
    ensure("FINISHED" in prop_result, "Mark prop collection did not finish")
    ensure(prop_collection.get(const.HST_PROP) == "PROP", f"Unexpected prop collection type: {prop_collection.get(const.HST_PROP)}")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(prop_obj) == "STATICMESH", "Prop mesh type missing after mark prop")

    decal_collection = make_collection("DecalMarkerCase")
    target = make_plane("DecalMarkerTarget", decal_collection)
    decal = make_plane("DecalMarkerMesh", decal_collection, location=(0.0, 0.0, 0.1))
    material = bpy.data.materials.new(name="Decal_Test")
    decal.data.materials.append(material)
    select_objects(decal, [target, decal])

    decal_result = bpy.ops.hst.markdecalcollection()
    ensure("FINISHED" in decal_result, "Mark decal collection did not finish")
    ensure(decal_collection.get(const.HST_PROP) == "DECAL", f"Unexpected decal collection type: {decal_collection.get(const.HST_PROP)}")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(decal) == "DECAL", "Decal mesh type missing after mark decal")
    result.add_detail(f"Prop/decal collections: {prop_collection.name}, {decal_collection.name}")



def test_prepare_cad_mesh_sets_ue_centimeter_units(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("PrepareCADUnitsCase")
    obj = make_test_mesh("PrepareCADUnitsMesh", collection)
    scene_units = bpy.context.scene.unit_settings
    scene_units.system = "METRIC"
    scene_units.length_unit = "METERS"
    scene_units.scale_length = 0.01

    select_objects(obj, [obj])
    prep_result = bpy.ops.hst.prepcadmesh()
    ensure("FINISHED" in prep_result, "Prepare CAD Mesh did not finish")
    ensure(scene_units.system == "METRIC", f"Unexpected unit system: {scene_units.system}")
    ensure(scene_units.length_unit == "CENTIMETERS", f"Unexpected length unit: {scene_units.length_unit}")
    ensure(abs(scene_units.scale_length - 1.0) < 1e-6, f"Unexpected unit scale: {scene_units.scale_length}")
    result.add_detail(f"Scene units: {scene_units.system}, {scene_units.length_unit}, scale={scene_units.scale_length}")


# 创建 Safe Ngon 的 CAD-like closed fixture；name/collection 分别为对象名和目标 Collection。
def make_safe_ngon_closed_fixture(name: str, collection):
    vertices = [
        (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
        (-1, -2, 0.2), (1, -2, 0.2), (1, 2, -0.2), (-1, 2, -0.2),
        (2, -1, 0), (2, 1, 0),
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -2, -0.8), (1, -2, -0.8), (1, 2, -1.2), (-1, 2, -1.2),
        (2, -1, -1), (2, 1, -1),
    ]
    top_faces = [(0, 1, 2, 3), (1, 8, 9, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
    bottom_faces = [tuple(index + 10 for index in reversed(face)) for face in top_faces]
    top_boundary_edges = {(0, 3), (3, 7), (6, 7), (2, 6), (8, 9), (1, 8), (4, 5), (0, 4), (5, 1), (9, 2)}
    side_faces = [(a, b, b + 10, a + 10) for a, b in sorted(top_boundary_edges)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], top_faces + bottom_faces + side_faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# 验证共享 Safe Ngon pipeline 修改拓扑、保留属性且重复运行稳定。
def test_safe_ngon_cad_pipeline_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("SafeNgonPipelineCase")
    obj = make_safe_ngon_closed_fixture("SafeNgonPipelineMesh", collection)
    mesh = obj.data
    mesh.materials.append(bpy.data.materials.new("SafeNgonMaterial"))
    for polygon in mesh.polygons:
        polygon.material_index = 0
    uv_layer = mesh.uv_layers.new(name="SafeNgonUV")
    for loop in uv_layer.data:
        loop.uv = (0.25, 0.75)
    face_attribute = mesh.attributes.new("safe_ngon_face_value", "INT", "FACE")
    for item in face_attribute.data:
        item.value = 7
    edge_attribute = mesh.attributes.new("safe_ngon_edge_value", "FLOAT", "EDGE")
    for item in edge_attribute.data:
        item.value = 0.5

    select_objects(obj, [obj])
    before_edges = len(mesh.edges)
    pipeline = test_context.addon.utils.safe_ngon_utils
    first_stats = pipeline.repair_cad_mesh(
        bpy.context,
        obj,
        clean_mid_vertices=False,
        clean_loose_vertices=False,
    )
    after_first_hash = mesh_topology_hash(obj)
    ensure(first_stats["safe_ngon"]["new_vertices"] > 0, "Safe Ngon did not create repair vertices")
    ensure(len(obj.data.edges) > before_edges, "Safe Ngon did not change edge flow")
    ensure(obj.data.uv_layers.get("SafeNgonUV") is not None, "Safe Ngon dropped UV data")
    ensure(obj.data.attributes.get("safe_ngon_face_value") is not None, "Safe Ngon dropped Face attribute")
    ensure(obj.data.attributes.get("safe_ngon_edge_value") is not None, "Safe Ngon dropped Edge attribute")
    ensure(all(polygon.material_index == 0 for polygon in obj.data.polygons), "Safe Ngon changed Material index")
    ensure(not any(first_stats["topology"].values()), f"Safe Ngon produced invalid topology: {first_stats['topology']}")

    second_stats = pipeline.repair_cad_mesh(
        bpy.context,
        obj,
        clean_mid_vertices=False,
        clean_loose_vertices=False,
    )
    ensure(mesh_topology_hash(obj) == after_first_hash, "Repeated Safe Ngon changed topology")
    ensure(second_stats["safe_ngon"]["new_vertices"] == 0, "Repeated Safe Ngon was not idempotent")
    ensure(not [item for item in bpy.data.objects if item.name.startswith("__HST_SafeNgon_Source_")], "Temporary source Object leaked")
    ensure(not [item for item in bpy.data.meshes if item.name.startswith("__HST_SafeNgon_SourceMesh_")], "Temporary source Mesh leaked")
    ensure(not [modifier for modifier in obj.modifiers if modifier.name.startswith("__HST_SafeNgon_")], "Temporary Modifier leaked")
    result.add_detail(f"edges={before_edges}->{len(obj.data.edges)}, stats={first_stats['safe_ngon']}")


# 验证 Fix CAD Obj 与 Prepare CAD Mesh 复用 pipeline，且 Multi-user Mesh 被隔离。
def test_safe_ngon_fix_then_prepare_multi_user_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("SafeNgonOperatorsCase")
    first = make_safe_ngon_closed_fixture("SafeNgonOperatorsA", collection)
    second = bpy.data.objects.new("SafeNgonOperatorsB", first.data)
    second.location.x = 5.0
    collection.objects.link(second)
    select_objects(first, [first, second])
    fix_result = bpy.ops.hst.fixcadobj()
    ensure("FINISHED" in fix_result, f"Fix CAD Obj failed: {fix_result}")
    ensure(first.data is not second.data, "Fix CAD Obj did not isolate Multi-user Mesh Data")
    hashes_after_fix = (mesh_topology_hash(first), mesh_topology_hash(second))

    select_objects(first, [first, second])
    prep_result = bpy.ops.hst.prepcadmesh()
    ensure("FINISHED" in prep_result, f"Prepare CAD Mesh failed after Fix: {prep_result}")
    ensure(mesh_topology_hash(first) == hashes_after_fix[0], "Fix then Prepare drifted first Mesh topology")
    ensure(mesh_topology_hash(second) == hashes_after_fix[1], "Fix then Prepare drifted second Mesh topology")
    ensure(first.data.uv_layers.get(test_context.const.UV_BASE) is not None, "Prepare did not create UV layer")
    ensure(not [item for item in bpy.data.objects if item.name.startswith("__HST_SafeNgon_Source_")], "Operator pipeline leaked source Object")
    result.add_detail("Fix -> Prepare remained topology-idempotent for two Multi-user inputs")


# 验证 custom normals 会从 Clean 前 source 恢复，且无 custom normals 时不会创建无效层。
def test_safe_ngon_custom_normals_and_cleanup_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("SafeNgonNormalsCase")
    obj = make_safe_ngon_closed_fixture("SafeNgonNormalsMesh", collection)
    source_mesh = obj.data.copy()
    source = bpy.data.objects.new("SafeNgonNormalsInitializer", source_mesh)
    collection.objects.link(source)
    custom_attribute = source_mesh.attributes.new("custom_normal", "FLOAT_VECTOR", "CORNER")
    for item in custom_attribute.data:
        item.vector = (0.1, 0.2, 1.0)
    select_objects(obj, [obj])
    modifier = obj.modifiers.new("Initialize Safe Ngon Normals", "DATA_TRANSFER")
    modifier.object = source
    modifier.use_loop_data = True
    modifier.data_types_loops = {"CUSTOM_NORMAL"}
    modifier.loop_mapping = "TOPOLOGY"
    bpy.context.view_layer.update()
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    ensure(obj.data.has_custom_normals, "Custom normal fixture initialization failed")
    bpy.data.objects.remove(source, do_unlink=True)
    bpy.data.meshes.remove(source_mesh)

    stats = test_context.addon.utils.safe_ngon_utils.repair_cad_mesh(
        bpy.context,
        obj,
        clean_mid_vertices=False,
        clean_loose_vertices=False,
    )
    ensure(stats["custom_normals_restored"], "Safe Ngon did not restore custom normals")
    normals = [normal.vector for normal in obj.data.corner_normals]
    ensure(normals and all(normal.length > 0.99 for normal in normals), "Restored custom normals are invalid")
    ensure(not [item for item in bpy.data.objects if item.name.startswith("__HST_SafeNgon_Source_")], "Custom normal source leaked")
    result.add_detail(f"restored_corner_normals={len(normals)}")


def test_collection_get_selected_outliner_precedence(test_context: TestContext, result: TestCaseResult):
    const = test_context.const
    outliner_collection = make_collection("OutlinerPropMarkerCase")
    viewport_collection = make_collection("ViewportMarkerCase")
    outliner_obj = make_test_mesh("OutlinerPropMesh", outliner_collection)
    viewport_obj = make_test_mesh("ViewportPropMesh", viewport_collection)
    select_objects(viewport_obj, [])

    collection_utils = test_context.addon.utils.collection_utils
    collection_utils.Collection.active(outliner_collection)
    selected_collections = collection_utils.Collection.get_selected()
    ensure(selected_collections == [outliner_collection], "Active Outliner collection was not selected")

    prop_result = bpy.ops.hst.markpropcollection()
    ensure("FINISHED" in prop_result, "Mark prop collection from Outliner did not finish")
    ensure(outliner_collection.get(const.HST_PROP) == "PROP", "Outliner collection was not marked as PROP")
    ensure(viewport_collection.get(const.HST_PROP) is None, "Unselected collection was marked unexpectedly")
    ensure(test_context.addon.utils.object_utils.Object.get_hst_type(outliner_obj) == "STATICMESH", "Outliner collection mesh type missing")

    result.add_detail(f"Outliner-selected collection: {outliner_collection.name}")



def test_isolate_collections_ignores_active_collection_without_object_selection_regression(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("IsolateActiveCollectionCase")
    obj = make_test_mesh("IsolateActiveCollectionMesh", collection)
    select_objects(obj, [])
    test_context.addon.utils.collection_utils.Collection.active(collection)

    isolate_result = bpy.ops.hst.isolate_collections_alt()
    ensure("CANCELLED" in isolate_result, "Isolate Collections treated active collection as an explicit selection")
    result.add_detail(f"Active collection without selected object was ignored: {collection.name}")


def test_bake_collection_export_fbx_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("BakeExportCase")
    obj = make_test_mesh("BakeExportMesh", collection)
    select_objects(obj, [obj])
    bake_result = bpy.ops.hst.setbakecollectionlow()
    ensure("FINISHED" in bake_result, "Set bake collection low for export did not finish")

    export_dir = ARTIFACT_DIR / "exports" / "bake_fbx"
    export_dir.mkdir(parents=True, exist_ok=True)

    params = bpy.context.scene.hst_params
    params.export_path = str(export_dir)
    params.export_format = "FBX"
    params.file_prefix = ""

    export_result = bpy.ops.hst.staticmeshexport()
    ensure("FINISHED" in export_result, "Bake collection FBX export did not finish")

    export_file = export_dir / f"SM_{collection.name}.fbx"
    ensure(export_file.exists(), f"Expected bake FBX export not found: {export_file}")
    ensure(export_file.stat().st_size > 0, "Exported bake FBX file is empty")
    result.add_detail(f"Bake FBX export: {export_file.name} ({export_file.stat().st_size} bytes)")



def test_marmoset_bake_pairing_smoke(test_context: TestContext, result: TestCaseResult):
    low_collection = make_collection("a_low")
    high_collection = make_collection("a_high")
    test_context.addon.utils.collection_utils.Collection.mark_hst_type(low_collection, "BAKE_LOW")
    test_context.addon.utils.collection_utils.Collection.mark_hst_type(high_collection, "BAKE_HIGH")

    pairs = test_context.addon.utils.marmoset_bake_utils.collect_marmoset_bake_pairs(bpy.context.scene)
    ensure(len(pairs) == 1, f"Expected one Marmoset bake pair, got {len(pairs)}")
    ensure(pairs[0].base_name == "a", f"Unexpected bake base name: {pairs[0].base_name}")
    ensure(pairs[0].low_collection == low_collection, "Low collection pairing mismatch")
    ensure(pairs[0].high_collection == high_collection, "High collection pairing mismatch")
    result.add_detail("Matched a_low with a_high")


def test_marmoset_bake_pairing_missing_side_regression(test_context: TestContext, result: TestCaseResult):
    low_collection = make_collection("missing_high_low")
    test_context.addon.utils.collection_utils.Collection.mark_hst_type(low_collection, "BAKE_LOW")

    try:
        test_context.addon.utils.marmoset_bake_utils.collect_marmoset_bake_pairs(bpy.context.scene)
    except ValueError as error:
        ensure("Missing high collection for: missing_high" in str(error), f"Unexpected error: {error}")
        result.add_detail(str(error))
        return
    raise TestFailure("Missing high collection did not raise ValueError")


def test_marmoset_loader_generation_smoke(test_context: TestContext, result: TestCaseResult):
    low_collection = make_collection("asset_low")
    high_collection = make_collection("asset_high")
    low_obj = make_test_mesh("asset_low_mesh", low_collection)
    high_obj = make_test_mesh("asset_high_mesh", high_collection, location=(2.0, 0.0, 0.0))
    test_context.addon.utils.collection_utils.Collection.mark_hst_type(low_collection, "BAKE_LOW")
    test_context.addon.utils.collection_utils.Collection.mark_hst_type(high_collection, "BAKE_HIGH")

    pairs = test_context.addon.utils.marmoset_bake_utils.collect_marmoset_bake_pairs(bpy.context.scene)
    bake_root = ARTIFACT_DIR / "marmoset_bridge"
    paths = test_context.addon.utils.marmoset_bake_utils.make_marmoset_bake_paths("", str(bake_root))
    groups = test_context.addon.utils.marmoset_bake_utils.export_marmoset_bake_fbx(pairs, paths)
    script_text = test_context.addon.utils.marmoset_bake_utils.build_marmoset_loader_script(
        groups=groups,
        scene_path=paths.scene_path,
        texture_size=int(bpy.context.scene.hst_params.texture_size),
        output_bits=16,
        output_samples=64,
        bevel_width_mm=1.25,
        bevel_samples=16,
        vertex_color_mask=1,
    )
    test_context.addon.utils.marmoset_bake_utils.write_loader_script(paths.loader_path, script_text)

    ensure((paths.fbx_dir / "asset_low.fbx").exists(), "Low FBX was not exported")
    ensure((paths.fbx_dir / "asset_high.fbx").exists(), "High FBX was not exported")
    ensure(paths.loader_path.exists(), "Marmoset loader script was not written")
    ensure('"Vertex Color Mask", CONFIG["vertex_color_mask"]' in script_text, "Loader missing vertex color mask setup")
    ensure('"Bevel Width (mm)", CONFIG["bevel_width_mm"]' in script_text, "Loader missing bevel width setup")
    ensure('"output_bits": 16' in script_text, "Loader missing output bit depth")
    ensure('baker.importModel(group_config["low_fbx"])' in script_text, "Loader must use Baker quick loader")
    ensure(low_obj.name in bpy.data.objects and high_obj.name in bpy.data.objects, "Source objects should remain in Blender scene")
    result.add_detail(f"Loader: {paths.loader_path}")
def mark_edge_indices_sharp(obj, edge_indices):
    """仅把指定 Edge 写入 sharp_edge attribute。

    Args:
        obj: 目标 Mesh Object。
        edge_indices: 待标记的 Edge 索引。
    """
    sharp_attribute = obj.data.attributes.get("sharp_edge")
    if sharp_attribute is None:
        sharp_attribute = obj.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
    edge_indices = set(edge_indices)
    for edge in obj.data.edges:
        sharp_attribute.data[edge.index].value = edge.index in edge_indices


def run_pipe_chamfer_operator(source, stage, radius=0.1, keep_debug_objects=True):
    """通过 Object-only Operator interface 执行实验性 Pipe Chamfer。

    Args:
        source: 输入 Mesh Object。
        stage: handoff 规定的 debug stage。
        radius: Pipe 半径。
        keep_debug_objects: 是否保留 Pipe/Union debug Objects。
    """
    select_objects(source, [source])
    return bpy.ops.hst.experimental_pipe_chamfer(
        "EXEC_DEFAULT",
        radius=radius,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage=stage,
        keep_debug_objects=keep_debug_objects,
        source_object_name=source.name,
    )


def test_sharp_feature_graph_object_smoke(test_context: TestContext, result: TestCaseResult):
    """验证 Object-only 输入自动发现全部 Sharp 并按 corner 拆 Pipe Groups。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("SharpFeatureGraphCase")
    source = make_test_mesh("SharpFeatureGraphSource", collection)
    mark_all_edges_sharp(source)
    source_hash = mesh_topology_hash(source)
    operator_result = run_pipe_chamfer_operator(source, "FEATURE_GRAPH")
    ensure("FINISHED" in operator_result, "FEATURE_GRAPH did not finish")
    ensure(mesh_topology_hash(source) == source_hash, "FEATURE_GRAPH changed source Mesh")
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, 0.1, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    ensure(stats["sharp_edge_count"] == 12, f"Expected 12 Sharp Edges, got {stats['sharp_edge_count']}")
    ensure(len(groups) == 12, f"Expected 12 independent cube Pipes, got {len(groups)}")
    ensure(stats["topology_junction_count"] == 8, "Cube Sharp graph should expose 8 junction vertices")
    result.add_detail("12 Sharp Edges -> 12 Pipe Groups; 8 topology junctions")


def test_experimental_pipe_chamfer_early_failure_keeps_source_visible_regression(test_context: TestContext, result: TestCaseResult):
    """验证尚未生成 artifact 的早期失败不会隐藏 source Mesh。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("EarlyFailureVisibilityCase")
    source = make_test_mesh("EarlyFailureVisibilitySource", collection)
    operator_result = run_pipe_chamfer_operator(source, "PATCHED")
    ensure("FINISHED" in operator_result, "Geometry failure did not keep redo-compatible Operator result")
    ensure(
        json.loads(bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}"))
        .get("error_code") == "no_sharp_edges",
        "Early failure diagnostic did not record no_sharp_edges",
    )
    ensure(not source.hide_get(), "Early failure hid the only source Mesh")
    result.add_detail("Early no_sharp_edges failure kept source visible")


def test_experimental_pipe_chamfer_pipes_no_blender_bevel_regression(test_context: TestContext, result: TestCaseResult):
    """验证 PIPES 由独立 Mesh sweep 生成且 source 不变，不存在 Bevel modifier。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("MultiPipeCase")
    source = make_test_mesh("MultiPipeSource", collection)
    top_edges = cube_top_loop_edge_indices(source)
    branch_edge = next(
        edge.index
        for edge in source.data.edges
        if edge.index not in top_edges and any(source.data.vertices[index].co.z > 0.0 for index in edge.vertices)
    )
    mark_edge_indices_sharp(source, top_edges + [branch_edge])
    source_hash = mesh_topology_hash(source)
    operator_result = run_pipe_chamfer_operator(source, "PIPES")
    ensure("FINISHED" in operator_result, "PIPES did not finish")
    ensure(source.hide_get(), "PIPES did not hide the source Mesh")
    pipes = [obj for obj in bpy.data.objects if obj.get("hst_pipe_id") is not None]
    ensure(len(pipes) >= 2, f"Expected independent Pipes, got {len(pipes)}")
    ensure(all(modifier.type != "BEVEL" for obj in bpy.data.objects for modifier in obj.modifiers), "Experimental result contains a Bevel modifier")
    ensure(mesh_topology_hash(source) == source_hash, "PIPES changed source Mesh")
    for pipe in pipes:
        bm = bmesh.new()
        bm.from_mesh(pipe.data)
        ensure(all(len(edge.link_faces) == 2 for edge in bm.edges), f"Pipe is not manifold: {pipe.name}")
        bm.free()
    result.add_detail(f"Independent manifold Pipes: {len(pipes)}")


def test_experimental_pipe_chamfer_two_pipe_junction_regular_patched_regression(test_context: TestContext, result: TestCaseResult):
    """验证旧 Operator 当前可完成 two-Pipe REGULAR_PATCHED，且 source 不变。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("TwoPipeJunctionCase")
    source = make_test_mesh("TwoPipeJunctionSource", collection)
    top_edges = cube_top_loop_edge_indices(source)
    branch_edge = next(
        edge.index
        for edge in source.data.edges
        if edge.index not in top_edges and any(source.data.vertices[index].co.z > 0.0 for index in edge.vertices)
    )
    mark_edge_indices_sharp(source, top_edges + [branch_edge])
    source_hash = mesh_topology_hash(source)
    operator_result = run_pipe_chamfer_operator(
        source, "REGULAR_PATCHED", radius=0.08, keep_debug_objects=True
    )
    ensure("FINISHED" in operator_result, "Two-Pipe REGULAR_PATCHED did not finish")
    diagnostic = json.loads(bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}"))
    ensure(
        diagnostic.get("status") in {"finished", "failed"},
        "Two-Pipe REGULAR_PATCHED diagnostic is missing",
    )
    ensure(mesh_topology_hash(source) == source_hash, "Two-Pipe REGULAR_PATCHED changed source Mesh")
    ensure(source.hide_get(), "Two-Pipe REGULAR_PATCHED did not hide source")
    result.add_detail(
        f"Two-Pipe junction result={diagnostic.get('status')} without changing source"
    )


def test_experimental_pipe_chamfer_union_difference_smoke(test_context: TestContext, result: TestCaseResult):
    """验证 BOOLEAN_CUT 保留可手动调整的 Exact Boolean Modifier。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("UnionDifferenceCase")
    source = make_test_mesh("UnionDifferenceSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    source_hash = mesh_topology_hash(source)
    operator_result = run_pipe_chamfer_operator(source, "BOOLEAN_CUT", radius=0.08)
    ensure("FINISHED" in operator_result, "BOOLEAN_CUT did not finish")
    ensure(source.hide_get(), "BOOLEAN_CUT did not hide the source Mesh")
    output = bpy.data.objects.get("UnionDifferenceSource_PipeChamfer_TEST")
    ensure(output is not None, "BOOLEAN_CUT preview object is missing")
    ensure(mesh_topology_hash(output) == source_hash, "BOOLEAN_CUT preview destructively changed output Mesh")
    boolean_modifiers = [modifier for modifier in output.modifiers if modifier.type == "BOOLEAN"]
    ensure(len(boolean_modifiers) == 1, "BOOLEAN_CUT did not leave exactly one Boolean Modifier")
    boolean_modifier = boolean_modifiers[0]
    ensure(boolean_modifier.operation == "DIFFERENCE", "Boolean preview is not Difference")
    ensure(boolean_modifier.solver == "EXACT", "Boolean preview does not default to Exact")
    ensure(boolean_modifier.operand_type == "OBJECT", "Single cutter Boolean preview does not use Object operand")
    ensure(boolean_modifier.object is not None, "Single cutter Boolean Object is missing")
    ensure(bpy.data.objects.get("UnionDifferenceSource_PipeUnion_TEST") is None, "Collection Difference created a union Mesh")
    cutter_collection = bpy.data.collections.get("UnionDifferenceSource_PipeCutters_TEST")
    ensure(cutter_collection is not None, "Collection Difference cutter set is missing")
    ensure(len(cutter_collection.objects) == 1, "Cutter set does not contain the independent Pipe")
    ensure(mesh_topology_hash(source) == source_hash, "BOOLEAN_CUT changed source Mesh")

    source.hide_set(False)
    repeated_result = run_pipe_chamfer_operator(source, "BOOLEAN_CUT", radius=0.08)
    ensure("FINISHED" in repeated_result, "Repeated BOOLEAN_CUT did not finish")
    cutter_collection = bpy.data.collections.get("UnionDifferenceSource_PipeCutters_TEST")
    ensure(cutter_collection is not None, "Repeated run lost the Cutter Collection")
    ensure(len(cutter_collection.objects) == 1, "Repeated run leaked or duplicated Pipe cutters")

    ensure(mesh_topology_hash(source) == source_hash, "Repeated BOOLEAN_CUT changed source Mesh")
    result.add_detail("BOOLEAN_CUT kept one editable Exact Collection Boolean Modifier")


def test_experimental_pipe_chamfer_open_boundary_preserves_original_faces(test_context: TestContext, result: TestCaseResult):
    """验证 Apply 后只删除 Boolean 新生成的槽面，不删除原模型表面。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("OpenBoundaryPreservationCase")
    source = make_test_mesh("OpenBoundaryPreservationSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=0.08,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="OPEN_BOUNDARY",
        keep_debug_objects=True,
    )
    output = bpy.data.objects.get(stats["output_object_name"])
    ensure(output is not None, "OPEN_BOUNDARY output is missing")
    ensure(
        stats["preserved_original_face_count"] >= stats["source_face_count_before_boolean"],
        f"OPEN_BOUNDARY lost all descendants of an original Face: {stats}",
    )
    ensure(
        stats["deleted_original_face_count"] == 0,
        f"OPEN_BOUNDARY deleted original Faces: {stats}",
    )
    ensure(
        stats["deleted_groove_face_count"] > 0,
        "OPEN_BOUNDARY did not delete any generated groove Faces",
    )
    result.add_detail(
        f"Preserved {stats['preserved_original_face_count']} original Faces; "
        f"deleted {stats['deleted_groove_face_count']} groove Faces"
    )


def test_experimental_pipe_chamfer_first_run_after_preview_regression(test_context: TestContext, result: TestCaseResult):
    """验证清理上一轮 preview 后，第一次 OPEN_BOUNDARY 就能识别并删除槽面。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("PipeChamferFirstRunCase")
    source = make_test_mesh("PipeChamferFirstRunSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    preview_result = run_pipe_chamfer_operator(source, "BOOLEAN_CUT", radius=0.08)
    ensure("FINISHED" in preview_result, "BOOLEAN_CUT preview did not finish")
    ensure(source.hide_get(), "BOOLEAN_CUT preview did not hide source")

    open_result = run_pipe_chamfer_operator(source, "OPEN_BOUNDARY", radius=0.08)
    ensure("FINISHED" in open_result, "First OPEN_BOUNDARY run after preview failed")
    output = bpy.data.objects.get("PipeChamferFirstRunSource_PipeChamfer_TEST")
    ensure(output is not None, "First OPEN_BOUNDARY output is missing")
    ensure(not output.modifiers, "First OPEN_BOUNDARY left an unapplied modifier")
    result.add_detail("First OPEN_BOUNDARY run succeeded immediately after preview cleanup")


def test_experimental_pipe_chamfer_bridge_then_fill_smoke(test_context: TestContext, result: TestCaseResult):
    """验证 Bridge Edge Loops 后 Fill 剩余洞能生成 watertight Mesh。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    bm = bmesh.new()
    rail_a = [bm.verts.new((0.0, 0.0, z)) for z in (0.0, 0.5, 1.0)]
    rail_b = [bm.verts.new((1.0, 0.0, z)) for z in (0.0, 0.5, 1.0)]
    rail_a_edges = [bm.edges.new((rail_a[index], rail_a[index + 1])) for index in range(2)]
    rail_b_edges = [bm.edges.new((rail_b[index], rail_b[index + 1])) for index in range(2)]
    bridge = bmesh.ops.bridge_loops(
        bm,
        edges=rail_a_edges + rail_b_edges,
        use_pairs=False,
        use_cyclic=False,
    )
    ensure(len(bridge.get("faces", [])) == 2, "Bridge Edge Loops did not create the strip")
    boundary_edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    boundary_loops = test_context.addon.utils.experimental_pipe_chamfer_utils._ordered_edge_chains(
        boundary_edges
    )
    ensure(len(boundary_loops) == 1 and boundary_loops[0]["is_cyclic"], "Bridge did not leave one Fill hole")
    fill = bmesh.ops.contextual_create(
        bm,
        geom=boundary_loops[0]["edges"],
        mat_nr=0,
        use_smooth=False,
    )
    ensure(fill.get("faces"), "Fill did not close the remaining hole")
    ensure(
        all(len(edge.link_faces) == 2 for edge in bm.edges),
        "Bridge→Fill result is not watertight",
    )
    bm.free()
    result.add_detail("Bridge Edge Loops + Fill produced a watertight strip")


def test_experimental_pipe_chamfer_postprocess_smoke(test_context: TestContext, result: TestCaseResult):
    """验证 PATCHED 后处理会 dissolve 共面三角、标记 chamfer Faces，并传递原 Mesh 法线。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("PipeChamferPostprocessCase")
    source = make_test_mesh("PipeChamferPostprocessSource", collection)
    mark_all_edges_sharp(source)
    operator_result = run_pipe_chamfer_operator(source, "PATCHED", radius=0.08)
    ensure("FINISHED" in operator_result, "PATCHED postprocess did not finish")
    output = bpy.data.objects.get("PipeChamferPostprocessSource_PipeChamfer_TEST")
    ensure(output is not None, "PATCHED postprocess output is missing")

    chamfer_attribute = output.data.attributes.get("hst_pipe_chamfer")
    ensure(chamfer_attribute is not None, "PATCHED output is missing hst_pipe_chamfer")
    ensure(chamfer_attribute.domain == "FACE", "hst_pipe_chamfer must use FACE domain")
    chamfer_faces = [
        polygon
        for polygon in output.data.polygons
        if chamfer_attribute.data[polygon.index].value
    ]
    ensure(chamfer_faces, "hst_pipe_chamfer did not mark any Faces")
    ensure(
        any(len(polygon.vertices) > 3 for polygon in chamfer_faces),
        "Dissolve did not produce any chamfer n-gon",
    )

    normal_modifiers = [modifier for modifier in output.modifiers if modifier.type == "DATA_TRANSFER"]
    ensure(len(normal_modifiers) == 1, "PATCHED output must have one normal Data Transfer modifier")
    normal_modifier = normal_modifiers[0]
    ensure(normal_modifier.object is source, "Normal transfer source must be the original Mesh")
    ensure(normal_modifier.data_types_loops == {"CUSTOM_NORMAL"}, "Normal transfer must target custom normals")
    ensure(normal_modifier.loop_mapping == "POLYINTERP_LNORPROJ", "Normal transfer mapping changed")
    result.add_detail(
        f"Marked chamfer Faces: {len(chamfer_faces)}; normal modifier: {normal_modifier.name}"
    )


def test_experimental_pipe_chamfer_endpoint_extension_regression(test_context: TestContext, result: TestCaseResult):
    """验证 terminal face 端延长 radius，曲面连续端不延长。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("EndpointExtensionCase")
    source = make_test_mesh("EndpointExtensionSource", collection)
    vertical_edge = next(
        edge
        for edge in source.data.edges
        if abs(source.data.vertices[edge.vertices[0]].co.z - source.data.vertices[edge.vertices[1]].co.z) > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, 0.25, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    terminal_group = groups[0]
    terminal_extensions = utils._pipe_endpoint_extensions(source, terminal_group, 0.25)
    ensure(
        terminal_extensions == (0.25, 0.25),
        f"Cube terminal Faces were not extended by radius: {terminal_extensions}",
    )

    continuation_source = make_test_mesh("SurfaceContinuationSource", collection)
    continuation_edge = next(
        edge
        for edge in continuation_source.data.edges
        if abs(
            continuation_source.data.vertices[edge.vertices[0]].co.z
            - continuation_source.data.vertices[edge.vertices[1]].co.z
        )
        > 1.5
    )
    mark_edge_indices_sharp(continuation_source, [continuation_edge.index])
    continuation_stats = utils._base_stats(
        continuation_source, 0.25, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH"
    )
    continuation_groups = utils._build_feature_graph(
        continuation_source, 35.0, 3.0, continuation_stats
    )
    for face in continuation_source.data.polygons:
        face.flip()
    continuation_extensions = utils._pipe_endpoint_extensions(
        continuation_source, continuation_groups[0], 0.25
    )
    ensure(
        continuation_extensions == (0.0, 0.0),
        f"Surface continuation was extended: {continuation_extensions}",
    )
    result.add_detail(
        f"Terminal extensions: {terminal_extensions}; continuation: {continuation_extensions}"
    )


def test_grouping_curved_chain_regression(test_context: TestContext, result: TestCaseResult):
    """验证 tessellated cylinder rim 不会按固定角度被切成许多 Pipe Groups。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("CurvedGroupingCase")
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.0, depth=2.0)
    source = ensure_object_in_collection(bpy.context.active_object, collection)
    source.name = "CurvedGroupingSource"
    top_rim = [edge.index for edge in source.data.edges if all(source.data.vertices[index].co.z > 0.9 for index in edge.vertices)]
    mark_edge_indices_sharp(source, top_rim)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, 0.08, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    ensure(len(groups) == 1 and groups[0]["is_cyclic"], f"Cylinder rim split into {len(groups)} Pipes")
    result.add_detail("32-edge curved rim remained one closed Pipe")


def test_grouping_true_corner_regression(test_context: TestContext, result: TestCaseResult):
    """验证 surface patch pair 与 degree junction 会把真实 cube corner 拆开。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("TrueCornerGroupingCase")
    source = make_test_mesh("TrueCornerGroupingSource", collection)
    mark_all_edges_sharp(source)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, 0.08, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    ensure(all(len(group["edge_indices"]) == 1 for group in groups), "True cube corners were merged")
    ensure(stats["topology_junction_count"] == 8, "True corner junction count is wrong")
    result.add_detail("Patch pair + degree split every true cube corner")


# 调用 Feature Chamfer GN Operator 并返回 source 与 owned modifier。
# source: 单个 active Mesh；action: Operator action；properties: 其余 RNA 参数。
def run_feature_chamfer_gn(source, action="PREVIEW", **properties):
    select_objects(source, [source])
    result = bpy.ops.hst.feature_chamfer_gn(action=action, **properties)
    modifier = source.modifiers.get("HST Feature Chamfer GN Preview")
    return result, modifier


# 返回 Node Group input socket display name 对应的 modifier identifier。
# node_group/name: GeometryNodeTree 与 input display name。
def node_input_identifier(node_group, name):
    return next(
        item.identifier
        for item in node_group.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name
    )


# 验证发布资产 exact/version import 与 Preview modifier 幂等创建。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_asset_import_exact_and_idempotent(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNPreview")
    source = make_test_mesh("GNSource", collection)
    mark_all_edges_sharp(source)
    source_hash = _mesh_fingerprint(source)
    first_result, first_modifier = run_feature_chamfer_gn(source)
    ensure(first_result == {"FINISHED"}, f"First Preview failed: {first_result}")
    ensure(first_modifier is not None, "Preview modifier was not created")
    node_group = first_modifier.node_group
    ensure(node_group.name == test_context.const.FEATURE_CHAMFER_GN_NODE, "Preview asset name is not exact")
    ensure(node_group.bl_idname == "GeometryNodeTree", "Preview asset has wrong node tree type")
    ensure(
        node_group.get(test_context.const.FEATURE_CHAMFER_GN_ASSET_VERSION_TAG)
        == test_context.const.FEATURE_CHAMFER_GN_ASSET_VERSION,
        "Preview asset version mismatch",
    )
    ensure(
        node_group.get("hst_feature_chamfer_asset_source")
        == "tests/fixtures/feature-chamfer-gn-junction-safe.blend:pipecut",
        "Preview asset was not migrated from the validated fixture",
    )
    boolean_pro_nodes = [
        node
        for node in node_group.nodes
        if node.bl_idname == "GeometryNodeGroup"
        and node.node_tree is not None
        and node.node_tree.name.startswith("HST Feature Chamfer :: Boolean Pro")
    ]
    ensure(len(boolean_pro_nodes) == 1, "Preview asset does not preserve the fixture Boolean Pro node")
    ensure(
        any(group.name.startswith("HST Feature Chamfer :: Float Boolean Edges") for group in bpy.data.node_groups)
        and any(group.name.startswith("HST Feature Chamfer :: Boolean Solver Select") for group in bpy.data.node_groups),
        "Boolean Pro nested dependencies were not appended",
    )
    boolean_node = boolean_pro_nodes[0]
    grid_node = node_group.nodes.get("HST Junction-safe Pipe")
    group_input = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupInput")
    ensure(
        any(
            link.from_node == group_input
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry"
            for link in node_group.links
        ),
        "Fixture source→Boolean Pro link changed",
    )
    ensure(
        any(
            link.from_node == grid_node
            and link.from_socket.name == "Mesh"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry B"
            for link in node_group.links
        ),
        "Fixture SDF cutter→Boolean Pro link changed",
    )
    second_result, second_modifier = run_feature_chamfer_gn(source, action="PREVIEW")
    ensure(second_result == {"FINISHED"}, f"Second Preview failed: {second_result}")
    ensure(first_modifier == second_modifier, "Repeated Preview stacked a modifier")
    ensure(sum(1 for modifier in source.modifiers if modifier.name == first_modifier.name) == 1, "Duplicate Preview modifier")
    ensure(_mesh_fingerprint(source) == source_hash, "Preview changed source Mesh data")
    result.add_detail(f"asset={node_group.name}, modifier={first_modifier.name}")


# 验证 Radius 等参数通过 interface identifier 更新，且 cutter 是 closed manifold。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_modifier_parameter_and_cutter_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNParameters")
    source = make_test_mesh("GNParameterSource", collection)
    mark_all_edges_sharp(source)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
        show_cutter=True,
    )
    ensure(operator_result == {"FINISHED"}, f"Cutter Preview failed: {operator_result}")
    expected = {
        "Radius": 0.08,
        "Sample Length": 0.04,
        "Voxel Size": 0.025,
        "Adaptivity": 0.1,
        "Show Cutter": True,
    }
    for name, expected_value in expected.items():
        identifier = node_input_identifier(modifier.node_group, name)
        actual_value = modifier[identifier]
        ensure(abs(actual_value - expected_value) < 1.0e-6, f"{name} was not updated: {actual_value}")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated_mesh = bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph), depsgraph=depsgraph)
    bm = bmesh.new()
    bm.from_mesh(evaluated_mesh)
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    face_count = len(bm.faces)
    bm.free()
    bpy.data.meshes.remove(evaluated_mesh)
    ensure(face_count > 0, "Cutter Preview is empty")
    ensure(boundary == 0, f"Cutter boundary edges: {boundary}")
    ensure(non_manifold == 0, f"Cutter non-manifold edges: {non_manifold}")
    result.add_detail(f"cutter_faces={face_count}")


# 验证 source 改变后状态变 stale，Finalize fail-closed 并保留 Preview。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_rejects_stale_preview(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNStale")
    source = make_test_mesh("GNStaleSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"}, f"Preview failed: {preview_result}")
    source.data.vertices[0].co.x += 0.01
    source.data.update()
    finalize_result, kept_modifier = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"CANCELLED"}, "Stale Preview was not rejected")
    ensure(kept_modifier == modifier, "Stale failure removed Preview")
    ensure(
        source.get(test_context.const.FEATURE_CHAMFER_GN_STATE_TAG) == "PREVIEW_STALE",
        "Stale Preview state was not persisted",
    )


# 验证用户直接修改 Modifier socket 后 Preview 变 stale，必须重新 Preview。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_modifier_parameter_change_marks_stale(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNLiveParameter")
    source = make_test_mesh("GNLiveParameterSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"}, f"Preview failed: {preview_result}")
    radius_identifier = node_input_identifier(modifier.node_group, "Radius")
    modifier[radius_identifier] = 0.09
    utils = test_context.addon.utils.feature_chamfer_gn_utils
    ensure(utils.preview_state(source) == "PREVIEW_STALE", "Live Radius edit did not stale Preview")
    rebuild_result, rebuilt_modifier = run_feature_chamfer_gn(source, action="AUTO")
    ensure(rebuild_result == {"FINISHED"}, "AUTO did not rebuild stale Preview")
    ensure(abs(rebuilt_modifier[radius_identifier] - 0.09) < 1.0e-6, "Rebuild reset live Radius")


# 验证 source Sharp 标记被移除后仍能取消本工具拥有的 Preview。
# test_context/result: 测试上下文与结果记录器。
def test_gn_cancel_stale_preview_without_sharp_edges(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNCancelStale")
    source = make_test_mesh("GNCancelStaleSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"} and modifier is not None, "Preview setup failed")
    sharp_attribute = source.data.attributes.get("sharp_edge")
    for value in sharp_attribute.data:
        value.value = False
    cancel_result, modifier_after_cancel = run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(cancel_result == {"FINISHED"}, "Stale Preview Cancel was rejected")
    ensure(modifier_after_cancel is None, "Stale Preview modifier was not removed")


# 验证 source 重命名后 owned Preview 仍可识别并取消。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_owner_survives_source_rename(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNRename")
    source = make_test_mesh("GNRenameSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"} and modifier is not None, "Preview setup failed")
    source.name = "GNRenamedSource"
    cancel_result, modifier_after_cancel = run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(cancel_result == {"FINISHED"}, "Renamed source could not cancel Preview")
    ensure(modifier_after_cancel is None, "Renamed source left owned Preview")


# 验证单一 Operator 的 action RNA、Preview 与 Cancel 生命周期。
# test_context/result: 测试上下文与结果记录器。
def test_feature_chamfer_single_operator_action_dispatch(test_context: TestContext, result: TestCaseResult):
    ensure(hasattr(bpy.ops.hst, "feature_chamfer_gn"), "Feature Chamfer GN Operator is not registered")
    operator_rna = bpy.ops.hst.feature_chamfer_gn.get_rna_type()
    action_items = {item.identifier for item in operator_rna.properties["action"].enum_items}
    ensure(action_items == {"AUTO", "PREVIEW", "FINALIZE", "CANCEL_PREVIEW"}, f"Unexpected actions: {action_items}")
    collection = make_collection("GNDispatch")
    source = make_test_mesh("GNDispatchSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source, action="AUTO")
    ensure(preview_result == {"FINISHED"} and modifier is not None, "AUTO did not create Preview")
    cancel_result, modifier_after_cancel = run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(cancel_result == {"FINISHED"}, "Cancel Preview failed")
    ensure(modifier_after_cancel is None, "Cancel Preview did not remove owned modifier")


# 验证 Finalize 从同一 GN modifier 临时提取 closed cutter，且恢复 Preview/source 状态。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_cutter_extraction_preserves_preview(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNFinalizeCutter")
    source = make_test_mesh("GNFinalizeCutterSource", collection)
    vertical_edge = next(
        edge
        for edge in source.data.edges
        if abs(
            source.data.vertices[edge.vertices[0]].co.z
            - source.data.vertices[edge.vertices[1]].co.z
        )
        > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
        show_cutter=False,
    )
    ensure(preview_result == {"FINISHED"}, f"Preview failed: {preview_result}")
    finalize_utils = test_context.addon.utils.feature_chamfer_finalize_utils
    context = finalize_utils.extract_feature_chamfer_finalize_context(source)
    try:
        diagnostics = context["diagnostics"]
        ensure(diagnostics["cutter"]["faces"] > 0, "Extracted cutter is empty")
        ensure(diagnostics["cutter"]["non_manifold"] == 0, "Extracted cutter is non-manifold")
        ensure(diagnostics["cutter"]["zero_area"] == 0, "Extracted cutter has zero-area Faces")
        ensure(diagnostics["preview_show_cutter_restored"], "Show Cutter was not restored")
        ensure(diagnostics["preview_parameters_unchanged"], "Preview parameters changed")
        ensure(diagnostics["source_fingerprint_unchanged"], "Source changed during extraction")
        ensure(
            diagnostics["endpoint_extension_geometry_validated"],
            f"Terminal extension did not reach evaluated cutter: {diagnostics['terminal_extension_validations']}",
        )
        ensure(
            diagnostics["tracked_boolean_provenance_validated"],
            f"Tracked Boolean provenance failed: {diagnostics.get('tracked_boolean')}",
        )
        ensure(diagnostics["tracked_boolean"]["coverage"] == 1.0, "Tracked Boolean coverage is not 100%")
        ensure(diagnostics["tracked_boolean"]["ambiguous_faces"] == 0, "Tracked Boolean has ambiguous Faces")
        ensure(diagnostics["tracked_boolean"]["groove_faces"] > 0, "Tracked Boolean found no groove Faces")
        ensure(
            diagnostics["boundary_regions_validated"],
            f"Boundary regions failed: {diagnostics.get('boundary_graph')}",
        )
        ensure(diagnostics["boundary_graph"]["coverage"] == 1.0, "Boundary coverage is not 100%")
        ensure(diagnostics["boundary_graph"]["ambiguous_region_count"] == 0, "Boundary has ambiguous regions")
        ensure(
            {region["class"] for region in context["boundary_regions"]}
            == {"REGULAR_TWO_RAIL"},
            f"Unexpected Boundary region classes: {context['boundary_regions']}",
        )
        ensure(
            diagnostics["endpoint_counts"]["AMBIGUOUS"] == 0,
            f"Unexpected ambiguous endpoints: {diagnostics['endpoints']}",
        )
        ensure(
            all(record["class"] == "TERMINAL_FACE" for record in context["endpoints"]),
            f"Cube vertical feature endpoints were misclassified: {context['endpoints']}",
        )
        ensure(
            all(record["extension"] > 0.08 for record in context["endpoints"]),
            f"Terminal endpoint extension metadata is wrong: {context['endpoints']}",
        )
        artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_finalize_probe.json"
        artifact_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    finally:
        finalize_utils.release_feature_chamfer_finalize_context(context)
    ensure(_mesh_fingerprint(source) == source_hash, "Finalize preflight changed source Mesh")
    show_cutter_identifier = node_input_identifier(modifier.node_group, "Show Cutter")
    ensure(not modifier[show_cutter_identifier], "Finalize preflight left cutter visible")
    result.add_detail(f"artifact={artifact_path}")


# 验证有效 Preview 的 FINALIZE 会执行完整 Phase 2B/Patch 并进入 PATCHED。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_phase_2b_gate_dispatches_patch(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNFinalizeGate")
    source = make_test_mesh("GNFinalizeGateSource", collection)
    vertical_edge = next(
        edge
        for edge in source.data.edges
        if abs(
            source.data.vertices[edge.vertices[0]].co.z
            - source.data.vertices[edge.vertices[1]].co.z
        )
        > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
    )
    ensure(preview_result == {"FINISHED"}, f"Preview failed: {preview_result}")
    finalize_result, kept_modifier = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, "Valid Phase 2B gate did not dispatch Patch")
    ensure(kept_modifier == modifier, "Finalize gate removed Preview")
    ensure(_mesh_fingerprint(source) == source_hash, "Finalize gate changed source Mesh")
    ensure(
        source.get(test_context.const.FEATURE_CHAMFER_GN_LAST_ACTION_TAG) == "FINALIZE",
        "Finalize diagnostic action was not persisted",
    )


# 验证真实 junction fixture 的 branch extension、provenance 与 Boundary region 全部可解释。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_real_fixture_phase_2b_go(test_context: TestContext, result: TestCaseResult):
    load_fixture_blend("feature-chamfer-gn-junction-safe.blend")
    source = bpy.data.objects.get("Extruded.002")
    ensure(source is not None, "Real Feature Chamfer fixture source is missing")
    for modifier in list(source.modifiers):
        source.modifiers.remove(modifier)
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.03,
        sample_length=0.01,
        voxel_size=0.0075,
        adaptivity=0.05,
    )
    ensure(preview_result == {"FINISHED"} and modifier is not None, "Real fixture Preview failed")
    finalize_utils = test_context.addon.utils.feature_chamfer_finalize_utils
    context = finalize_utils.extract_feature_chamfer_finalize_context(source)
    try:
        diagnostics = context["diagnostics"]
        ensure(diagnostics["go"], f"Real fixture did not pass Phase 2B: {diagnostics}")
        ensure(diagnostics["endpoint_counts"]["AMBIGUOUS"] == 0, "Real fixture has ambiguous endpoints")
        ensure(diagnostics["endpoint_counts"]["JUNCTION_BRANCH"] > 0, "Real fixture has no junction branches")
        ensure(diagnostics["tracked_boolean"]["coverage"] == 1.0, "Real fixture provenance is incomplete")
        ensure(diagnostics["tracked_boolean"]["ambiguous_faces"] == 0, "Real fixture has ambiguous Faces")
        ensure(diagnostics["boundary_graph"]["coverage"] == 1.0, "Real fixture Boundary coverage is incomplete")
        ensure(diagnostics["boundary_graph"]["ambiguous_region_count"] == 0, "Real fixture has ambiguous regions")
        classes = {region["class"] for region in context["boundary_regions"]}
        ensure("JUNCTION" in classes, f"Real fixture has no JUNCTION region: {classes}")
        ensure("CYCLIC_TWO_RAIL" in classes, f"Real fixture has no CYCLIC_TWO_RAIL region: {classes}")
        ensure(_mesh_fingerprint(source) == source_hash, "Ambiguous endpoint failure changed source Mesh")
        ensure(source.modifiers.get(modifier.name) == modifier, "Ambiguous endpoint failure removed Preview")
        artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_finalize_fixture_probe.json"
        artifact_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
        result.add_detail(f"Real fixture Phase 2B Go; classes={sorted(classes)}")
    finally:
        finalize_utils.release_feature_chamfer_finalize_context(context)


# 验证 Phase 3 Patch Module 可直接消费 Phase 2B 显式 regions，并支持不等 Vertex 数 zipper bridge。
# test_context/result: 测试上下文与结果记录器。
def test_gn_patch_module_terminal_and_mismatched_rails(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNPatchModule")
    source = make_test_mesh("GNPatchSource", collection)
    vertical_edge = next(
        edge for edge in source.data.edges
        if abs(source.data.vertices[edge.vertices[0]].co.z - source.data.vertices[edge.vertices[1]].co.z) > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    preview_result, _ = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
    )
    ensure(preview_result == {"FINISHED"}, "Patch module Preview failed")
    finalize_utils = test_context.addon.utils.feature_chamfer_finalize_utils
    patch_utils = test_context.addon.utils.feature_chamfer_patch_utils
    context = finalize_utils.extract_feature_chamfer_finalize_context(source)
    patched_mesh = None
    try:
        patched_mesh, patch_stats = patch_utils.patch_boolean_result(
            context["open_mesh"],
            context["boundary_regions"],
            context["diagnostics"]["boundary_graph"]["components"],
            donor_mesh=context["boolean_mesh"],
            groove_face_indices=context["groove_face_indices"],
        )
        ensure(patch_stats["status"] == "finished", f"Patch Module failed: {patch_stats}")
        ensure(patch_stats["boundary_after"] == 0, "Patch Module left Boundary Edges")
        ensure(patch_stats["non_manifold_after"] == 0, "Patch Module left non-manifold Edges")
        ensure(patch_stats["patch_face_count"] > 0, "Patch Module generated no Faces")
        result.add_detail(f"Patch faces={patch_stats['patch_face_count']}")
    finally:
        if patched_mesh is not None and bpy.data.meshes.get(patched_mesh.name) == patched_mesh:
            bpy.data.meshes.remove(patched_mesh)
        finalize_utils.release_feature_chamfer_finalize_context(context)


# 验证复杂 END_CAP/JUNCTION 不再执行 planar/fan Fill，而是保留 tracked Boolean 槽面。
# test_context/result: 测试上下文与结果记录器。
def test_gn_patch_complex_region_preserves_tracked_boolean_surface(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNComplexPatchDonor")
    donor_object = make_test_mesh("GNComplexPatchDonorSource", collection)
    donor_mesh = donor_object.data
    patch_utils = test_context.addon.utils.feature_chamfer_patch_utils
    patched_mesh = None
    regions = [{"class": "JUNCTION"}]
    try:
        patched_mesh, patch_stats = patch_utils.patch_boolean_result(
            open_mesh=donor_mesh,
            regions=regions,
            components=[],
            donor_mesh=donor_mesh,
            groove_face_indices=[0],
        )
        ensure(
            patch_stats["strategy"] == "TRACKED_BOOLEAN_SURFACE",
            f"Complex Patch used unsafe filler: {patch_stats}",
        )
        ensure(
            len(patched_mesh.polygons) == len(donor_mesh.polygons),
            "Complex Patch changed the tracked Boolean donor topology",
        )
        result.add_detail(f"strategy={patch_stats['strategy']}")
    finally:
        if patched_mesh is not None and bpy.data.meshes.get(patched_mesh.name) == patched_mesh:
            bpy.data.meshes.remove(patched_mesh)


# 验证旧 Operator 已通过统一 Patch Module 的 legacy Adapter，且调用旧 patch seam 一次。
# test_context/result: 测试上下文与结果记录器。
def test_legacy_feature_chamfer_uses_patch_adapter(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("LegacyPatchAdapter")
    source = make_test_mesh("LegacyPatchAdapterSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    patch_module = test_context.addon.utils.feature_chamfer_patch_utils
    legacy_module = test_context.addon.utils.experimental_pipe_chamfer_utils
    original_patch_entry = legacy_module.patch_boolean_result
    calls = []

    def tracking_patch_entry(*args, **kwargs):
        calls.append(kwargs.get("legacy_context") is not None)
        return original_patch_entry(*args, **kwargs)

    legacy_module.patch_boolean_result = tracking_patch_entry
    try:
        operator_result = run_pipe_chamfer_operator(source, "REGULAR_PATCHED", radius=0.08)
    finally:
        legacy_module.patch_boolean_result = original_patch_entry
    ensure("FINISHED" in operator_result, "Legacy Adapter setup did not finish")
    ensure(calls == [True], f"Legacy Patch Adapter dispatch mismatch: {calls}")
    ensure(original_patch_entry is patch_module.patch_boolean_result, "Legacy entry is not unified Patch Module")
    result.add_detail("Legacy REGULAR_PATCHED dispatched unified legacy Adapter exactly once")


# 验证同一 Operator 的 FINALIZE 创建独立 closed output，并保留 source 与禁用 procedural Preview。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_creates_closed_output(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNFinalizeOutput")
    source = make_test_mesh("GNFinalizeOutputSource", collection)
    vertical_edge = next(
        edge for edge in source.data.edges
        if abs(source.data.vertices[edge.vertices[0]].co.z - source.data.vertices[edge.vertices[1]].co.z) > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
    )
    ensure(preview_result == {"FINISHED"}, "Finalize output Preview failed")
    finalize_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, f"Finalize did not finish: {finalize_result}")
    output = bpy.context.active_object
    ensure(output is not None and output is not source, "Finalize did not create an output Object")
    ensure(output.data is not source.data, "Finalize output shares source Mesh data")
    bm = bmesh.new()
    bm.from_mesh(output.data)
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    bm.free()
    ensure(boundary == 0 and non_manifold == 0, "Finalize output is not closed manifold")
    ensure(_mesh_fingerprint(source) == source_hash, "Finalize changed source Mesh")
    ensure(not modifier.show_viewport and not modifier.show_render, "Finalize did not disable Preview")
    ensure(
        test_context.addon.utils.feature_chamfer_gn_utils.preview_state(source) == "PATCHED",
        "Finalize source state is not PATCHED",
    )
    ensure(output.data.attributes.get("hst_feature_chamfer_face") is not None, "Chamfer Face attribute missing")
    ensure(
        any(modifier.type == "DATA_TRANSFER" and modifier.object == source for modifier in output.modifiers),
        "Finalize output has no source normal transfer",
    )
    result.add_detail(f"output={output.name}, faces={len(output.data.polygons)}")


# 验证真实 junction/cyclic/end-cap fixture 的完整 FINALIZE 输出 closed manifold。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_real_fixture_closed_manifold(test_context: TestContext, result: TestCaseResult):
    load_fixture_blend("feature-chamfer-gn-junction-safe.blend")
    source = bpy.data.objects["Extruded.002"]
    for modifier in list(source.modifiers):
        source.modifiers.remove(modifier)
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.03,
        sample_length=0.01,
        voxel_size=0.0075,
        adaptivity=0.05,
    )
    ensure(preview_result == {"FINISHED"}, "Real fixture Preview failed")
    finalize_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, f"Real fixture Finalize failed: {finalize_result}")
    output = bpy.context.active_object
    ensure(output is not source, "Real fixture Finalize did not create output")
    bm = bmesh.new()
    bm.from_mesh(output.data)
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    zero_area = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12)
    bm.free()
    ensure(boundary == 0 and non_manifold == 0 and zero_area == 0, "Real fixture output is invalid")
    ensure(_mesh_fingerprint(source) == source_hash, "Real fixture Finalize changed source")
    ensure(not modifier.show_viewport, "Real fixture Finalize left Preview enabled")
    result.add_detail(f"output_faces={len(output.data.polygons)}")


# 验证 Preview 与 Finalize 各占一个 Undo step，撤销 Finalize 后回到可调整 Preview。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_finalize_undo_steps(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNUndo")
    source = make_test_mesh("GNUndoSource", collection)
    vertical_edge = next(
        edge for edge in source.data.edges
        if abs(source.data.vertices[edge.vertices[0]].co.z - source.data.vertices[edge.vertices[1]].co.z) > 1.5
    )
    mark_edge_indices_sharp(source, [vertical_edge.index])
    source_hash = _mesh_fingerprint(source)
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        sample_length=0.04,
        voxel_size=0.025,
        adaptivity=0.1,
    )
    ensure(preview_result == {"FINISHED"} and modifier is not None, "Undo Preview setup failed")
    finalize_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, "Undo Finalize setup failed")
    output_name = bpy.context.active_object.name
    ensure(bpy.data.objects.get(output_name) is not None, "Undo output is missing")

    if bpy.app.background or not bpy.ops.ed.undo.poll():
        ensure(
            "UNDO" in test_context.addon.operators.feature_chamfer_gn_ops.HST_OT_FeatureChamferGN.bl_options,
            "Feature Chamfer GN Operator does not declare UNDO",
        )
        ensure(not modifier.show_viewport, "Finalize did not create the expected reversible Preview state")
        result.add_detail("Background mode cannot execute ed.undo; operator UNDO contract verified")
        return
    bpy.ops.ed.undo()
    source_after_finalize_undo = bpy.data.objects.get("GNUndoSource")
    ensure(source_after_finalize_undo is not None, "Finalize Undo removed source")
    preview_after_undo = source_after_finalize_undo.modifiers.get("HST Feature Chamfer GN Preview")
    ensure(preview_after_undo is not None, "Finalize Undo did not restore Preview")
    ensure(preview_after_undo.show_viewport, "Finalize Undo left Preview disabled")
    ensure(bpy.data.objects.get(output_name) is None, "Finalize Undo did not remove output")
    ensure(_mesh_fingerprint(source_after_finalize_undo) == source_hash, "Finalize Undo changed source")

    bpy.ops.ed.undo()
    source_after_preview_undo = bpy.data.objects.get("GNUndoSource")
    ensure(source_after_preview_undo is not None, "Preview Undo removed source")
    ensure(
        source_after_preview_undo.modifiers.get("HST Feature Chamfer GN Preview") is None,
        "Preview Undo did not remove Preview modifier",
    )
    ensure(_mesh_fingerprint(source_after_preview_undo) == source_hash, "Preview Undo changed source")
    result.add_detail("Preview and Finalize each produced a reversible Undo step")


# 验证 HST Panel 动态 label 和 Cancel 辅助按钮的 RNA 路径。
# test_context/result: 测试上下文与结果记录器。
def test_feature_chamfer_panel_dynamic_label_and_cancel(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNPanel")
    source = make_test_mesh("GNPanelSource", collection)
    mark_all_edges_sharp(source)
    select_objects(source, [source])
    panel_module = test_context.addon.ui_panel
    ensure(
        panel_module.feature_chamfer_gn_button_label(bpy.context)
        == "Feature Chamfer GN Preview",
        "Panel NONE label is wrong",
    )
    preview_result, _ = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"}, "Panel Preview setup failed")
    ensure(
        panel_module.feature_chamfer_gn_button_label(bpy.context)
        == "Finalize Feature Chamfer Patch",
        "Panel PREVIEW_VALID label is wrong",
    )
    cancel_result, modifier = run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(cancel_result == {"FINISHED"} and modifier is None, "Panel Cancel action failed")
    result.add_detail("Panel labels NONE/PREVIEW_VALID and CANCEL_PREVIEW dispatch verified")


def main():
    addon_module = load_addon_module()
    addon_module.register()

    context = TestContext(addon_module)
    context.run_case("addon_registers", test_addon_registers)
    context.run_case("scene_params_stale_pointer_recovery_regression", test_scene_params_stale_pointer_recovery_regression)
    context.run_case("pipe_chamfer_tricky_b_extruded002_regression", test_pipe_chamfer_tricky_b_extruded002_regression)
    context.run_case("pipe_chamfer_degree_four_strand_pairing_regression", test_pipe_chamfer_degree_four_strand_pairing_regression)
    context.run_case("pipe_chamfer_failure_keeps_redo_panel_regression", test_pipe_chamfer_failure_keeps_redo_panel_regression)
    context.run_case("pipe_chamfer_writes_diagnostic_regression", test_pipe_chamfer_writes_diagnostic_regression)
    context.run_case("transfer_proxy_reuse", test_transfer_proxy_reuse)
    context.run_case("bevel_transfer_normal_collection_reuse", test_bevel_transfer_normal_collection_reuse)
    context.run_case("project_decal_smoke", test_project_decal_smoke)
    context.run_case("quickweight_smoke", test_quickweight_smoke)
    context.run_case("set_bake_collection_smoke", test_set_bake_collection_smoke)
    context.run_case("vertex_color_set_and_copy_smoke", test_vertex_color_set_and_copy_smoke)
    context.run_case("collision_and_extract_ucx_smoke", test_collision_and_extract_ucx_smoke)
    context.run_case("safe_bevel_weight_smoke", test_safe_bevel_weight_smoke)
    context.run_case("safe_bevel_weight_selected_only_regression", test_safe_bevel_weight_selected_only_regression)
    context.run_case("safe_bevel_weight_preserves_lower_user_weight_regression", test_safe_bevel_weight_preserves_lower_user_weight_regression)
    context.run_case("safe_bevel_weight_missing_modifier_smoke", test_safe_bevel_weight_missing_modifier_smoke)
    context.run_case("modifier_ops_smoke", test_modifier_ops_smoke)
    context.run_case("ao_bake_operator_smoke", test_ao_bake_operator_smoke)
    context.run_case("wearmask_proxy_topology_matches_transfer_target", test_wearmask_proxy_topology_matches_transfer_target)
    context.run_case("origin_and_transform_smoke", test_origin_and_transform_smoke)
    context.run_case("collection_markers_smoke", test_collection_markers_smoke)
    context.run_case("collection_get_selected_outliner_precedence", test_collection_get_selected_outliner_precedence)
    context.run_case("isolate_collections_ignores_active_collection_without_object_selection_regression", test_isolate_collections_ignores_active_collection_without_object_selection_regression)
    context.run_case("staticmeshexport_fbx_smoke", test_staticmeshexport_fbx_smoke)
    context.run_case("staticmeshexport_current_scene_only_fbx", test_staticmeshexport_current_scene_only_fbx)
    context.run_case("staticmeshexport_cat_meshgroup_instance_fbx", test_staticmeshexport_cat_meshgroup_instance_fbx)
    context.run_case("prepare_cad_mesh_sets_ue_centimeter_units", test_prepare_cad_mesh_sets_ue_centimeter_units)
    context.run_case("safe_ngon_cad_pipeline_regression", test_safe_ngon_cad_pipeline_regression)
    context.run_case("safe_ngon_fix_then_prepare_multi_user_regression", test_safe_ngon_fix_then_prepare_multi_user_regression)
    context.run_case("safe_ngon_custom_normals_and_cleanup_regression", test_safe_ngon_custom_normals_and_cleanup_regression)
    context.run_case("bake_collection_export_fbx_smoke", test_bake_collection_export_fbx_smoke)
    context.run_case("marmoset_bake_pairing_smoke", test_marmoset_bake_pairing_smoke)
    context.run_case("marmoset_bake_pairing_missing_side_regression", test_marmoset_bake_pairing_missing_side_regression)
    context.run_case("marmoset_loader_generation_smoke", test_marmoset_loader_generation_smoke)
    context.run_case("staticmeshexport_glb_smoke", test_staticmeshexport_glb_smoke)
    context.run_case("rename_bones_smoke", test_rename_bones_smoke)
    context.run_case("cleanup_ue_skm_smoke", test_cleanup_ue_skm_smoke)
    context.run_case("sharp_feature_graph_object_smoke", test_sharp_feature_graph_object_smoke)
    context.run_case("experimental_pipe_chamfer_early_failure_keeps_source_visible_regression", test_experimental_pipe_chamfer_early_failure_keeps_source_visible_regression)
    context.run_case("experimental_pipe_chamfer_pipes_no_blender_bevel_regression", test_experimental_pipe_chamfer_pipes_no_blender_bevel_regression)
    context.run_case("experimental_pipe_chamfer_two_pipe_junction_regular_patched_regression", test_experimental_pipe_chamfer_two_pipe_junction_regular_patched_regression)
    context.run_case("experimental_pipe_chamfer_union_difference_smoke", test_experimental_pipe_chamfer_union_difference_smoke)
    context.run_case("experimental_pipe_chamfer_open_boundary_preserves_original_faces", test_experimental_pipe_chamfer_open_boundary_preserves_original_faces)
    context.run_case("experimental_pipe_chamfer_first_run_after_preview_regression", test_experimental_pipe_chamfer_first_run_after_preview_regression)
    context.run_case("experimental_pipe_chamfer_bridge_then_fill_smoke", test_experimental_pipe_chamfer_bridge_then_fill_smoke)
    context.run_case("experimental_pipe_chamfer_postprocess_smoke", test_experimental_pipe_chamfer_postprocess_smoke)
    context.run_case("experimental_pipe_chamfer_endpoint_extension_regression", test_experimental_pipe_chamfer_endpoint_extension_regression)
    context.run_case("grouping_curved_chain_regression", test_grouping_curved_chain_regression)
    context.run_case("grouping_true_corner_regression", test_grouping_true_corner_regression)
    context.run_case("gn_preview_asset_import_exact_and_idempotent", test_gn_preview_asset_import_exact_and_idempotent)
    context.run_case("gn_preview_modifier_parameter_and_cutter_smoke", test_gn_preview_modifier_parameter_and_cutter_smoke)
    context.run_case("gn_finalize_rejects_stale_preview", test_gn_finalize_rejects_stale_preview)
    context.run_case("gn_preview_modifier_parameter_change_marks_stale", test_gn_preview_modifier_parameter_change_marks_stale)
    context.run_case("gn_cancel_stale_preview_without_sharp_edges", test_gn_cancel_stale_preview_without_sharp_edges)
    context.run_case("gn_preview_owner_survives_source_rename", test_gn_preview_owner_survives_source_rename)
    context.run_case("gn_finalize_cutter_extraction_preserves_preview", test_gn_finalize_cutter_extraction_preserves_preview)
    context.run_case("gn_finalize_phase_2b_gate_dispatches_patch", test_gn_finalize_phase_2b_gate_dispatches_patch)
    context.run_case("gn_finalize_real_fixture_phase_2b_go", test_gn_finalize_real_fixture_phase_2b_go)
    context.run_case("gn_patch_module_terminal_and_mismatched_rails", test_gn_patch_module_terminal_and_mismatched_rails)
    context.run_case(
        "gn_patch_complex_region_preserves_tracked_boolean_surface",
        test_gn_patch_complex_region_preserves_tracked_boolean_surface,
    )
    context.run_case("legacy_feature_chamfer_uses_patch_adapter", test_legacy_feature_chamfer_uses_patch_adapter)
    context.run_case("gn_finalize_creates_closed_output", test_gn_finalize_creates_closed_output)
    context.run_case("gn_finalize_real_fixture_closed_manifold", test_gn_finalize_real_fixture_closed_manifold)
    context.run_case("gn_preview_finalize_undo_steps", test_gn_preview_finalize_undo_steps)
    context.run_case("feature_chamfer_panel_dynamic_label_and_cancel", test_feature_chamfer_panel_dynamic_label_and_cancel)
    context.run_case("feature_chamfer_single_operator_action_dispatch", test_feature_chamfer_single_operator_action_dispatch)

    summary = {
        "blender_version": bpy.app.version_string,
        "repo_root": str(REPO_ROOT),
        "artifact_dir": str(ARTIFACT_DIR),
        "results": [result.to_dict() for result in context.results],
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    failed = [result for result in context.results if result.status != "passed"]
    print("\n=== HST Blender Regression Summary ===")
    for result in context.results:
        print(f"[{result.status.upper()}] {result.name}")
        for detail in result.details:
            print(f"  - {detail}")
        if result.error:
            print(result.error)

    try:
        addon_module.unregister()
    except Exception:
        traceback.print_exc()

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
