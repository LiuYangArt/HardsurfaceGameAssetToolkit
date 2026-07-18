# -*- coding: utf-8 -*-
"""Blender-side regression test driver."""

import importlib.util
import inspect
import json
import os
import sys
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
    ensure(hasattr(bpy.ops.hst, "hst_addtransvertcolorproxy"), "Proxy operator missing")
    ensure(hasattr(bpy.ops.hst, "hst_bakeproxyvertcolrao"), "AO bake operator missing")
    result.add_detail(f"Blender version: {bpy.app.version_string}")
    result.add_detail(f"Registered hst operators: {len(operator_idnames)}")


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
    try:
        run_pipe_chamfer_operator(source, "PATCHED")
    except RuntimeError as error:
        ensure("no_sharp_edges" in str(error), f"Unexpected early failure: {error}")
    else:
        raise TestFailure("Mesh without Sharp Edges unexpectedly finished")
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


def test_experimental_pipe_chamfer_two_pipe_junction_fails_closed_regression(test_context: TestContext, result: TestCaseResult):
    """验证核心 two-Pipe junction 未完成分区时稳定失败，不输出伪 PATCHED 成功。

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
    try:
        run_pipe_chamfer_operator(source, "REGULAR_PATCHED", radius=0.08, keep_debug_objects=True)
    except RuntimeError as error:
        ensure(
            any(
                error_code in str(error)
                for error_code in (
                    "junction_region_unresolved",
                    "ambiguous_boundary",
                    "boolean_no_cutter_faces",
                )
            ),
            f"Unexpected two-Pipe junction failure: {error}",
        )
    else:
        raise TestFailure("Unresolved two-Pipe junction reported REGULAR_PATCHED success")
    ensure(mesh_topology_hash(source) == source_hash, "Rejected two-Pipe junction changed source Mesh")
    ensure(source.hide_get(), "Failed junction with debug artifacts did not hide the source Mesh")
    result.add_detail("Unresolved junction failed closed without Bevel fallback")


def test_experimental_pipe_chamfer_union_difference_smoke(test_context: TestContext, result: TestCaseResult):
    """验证 independent Pipe Cutter Collection 的 Exact Difference 与清理行为。

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
    marker = bpy.data.materials.get("HST_PipeChamfer_Marker")
    ensure(output is not None and marker in output.data.materials[:], "BOOLEAN_CUT marker provenance missing")
    output_face_count = len(output.data.polygons)
    marker_index = list(output.data.materials).index(marker)
    ensure(any(face.material_index == marker_index for face in output.data.polygons), "No cutter-derived Faces were marked")
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

    source.hide_set(False)
    cleanup_result = run_pipe_chamfer_operator(
        source,
        "BOOLEAN_CUT",
        radius=0.08,
        keep_debug_objects=False,
    )
    ensure("FINISHED" in cleanup_result, "BOOLEAN_CUT cleanup run did not finish")
    ensure(
        bpy.data.collections.get("UnionDifferenceSource_PipeCutters_TEST") is None,
        "keep_debug_objects=False left the Cutter Collection behind",
    )
    ensure(
        not any(obj.get("hst_pipe_chamfer_pipe") for obj in bpy.data.objects),
        "keep_debug_objects=False left Pipe cutter objects behind",
    )
    ensure(mesh_topology_hash(source) == source_hash, "Repeated BOOLEAN_CUT changed source Mesh")
    result.add_detail(f"Boolean output Faces: {output_face_count}; repeated run and cleanup passed")


def test_experimental_pipe_chamfer_endpoint_extension_regression(test_context: TestContext, result: TestCaseResult):
    """验证 open Pipe 只在 topology junction 端延长，并受相邻 segment 长度约束。

    Args:
        test_context: 已注册 add-on 的测试上下文。
        result: 当前测试结果记录器。
    """
    collection = make_collection("EndpointExtensionCase")
    source = make_test_mesh("EndpointExtensionSource", collection)
    top_edges = cube_top_loop_edge_indices(source)
    branch_edge = next(
        edge.index
        for edge in source.data.edges
        if edge.index not in top_edges and any(source.data.vertices[index].co.z > 0.0 for index in edge.vertices)
    )
    mark_edge_indices_sharp(source, top_edges + [branch_edge])
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, 10.0, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    open_group = next(group for group in groups if not group["is_cyclic"])
    extensions = utils._pipe_endpoint_extensions(open_group, 10.0)
    segment_length = (open_group["points"][1] - open_group["points"][0]).length
    ensure(min(extensions) <= 1.0e-4, f"Degree-1 endpoint was overextended: {extensions}")
    ensure(max(extensions) <= segment_length * 0.45 + 1.0e-6, f"Junction extension exceeded local segment clamp: {extensions}")
    result.add_detail(f"Endpoint extensions: {extensions}")


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


def main():
    addon_module = load_addon_module()
    addon_module.register()

    context = TestContext(addon_module)
    context.run_case("addon_registers", test_addon_registers)
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
    context.run_case("experimental_pipe_chamfer_two_pipe_junction_fails_closed_regression", test_experimental_pipe_chamfer_two_pipe_junction_fails_closed_regression)
    context.run_case("experimental_pipe_chamfer_union_difference_smoke", test_experimental_pipe_chamfer_union_difference_smoke)
    context.run_case("experimental_pipe_chamfer_endpoint_extension_regression", test_experimental_pipe_chamfer_endpoint_extension_regression)
    context.run_case("grouping_curved_chain_regression", test_grouping_curved_chain_regression)
    context.run_case("grouping_true_corner_regression", test_grouping_true_corner_regression)

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
