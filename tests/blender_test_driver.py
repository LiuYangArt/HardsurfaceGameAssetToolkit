# -*- coding: utf-8 -*-
"""Blender-side regression test driver."""

import hashlib
import importlib.util
import inspect
import json
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree


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
        requested_cases = {
            case_name.strip()
            for case_name in os.environ.get("HST_TEST_CASES", "").split(",")
            if case_name.strip()
        }
        if requested_cases and name not in requested_cases:
            return
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


# mesh/decimal_places: 待比较的 Mesh 与坐标量化精度；返回不依赖临时 index、Face winding 与起点的 canonical 几何签名。
def canonical_mesh_geometry_signature(mesh, decimal_places=8):
    coordinates = tuple(
        tuple(round(float(value), decimal_places) for value in vertex.co)
        for vertex in mesh.vertices
    )
    vertices = tuple(sorted(coordinates))
    edges = tuple(sorted(
        tuple(sorted((coordinates[edge.vertices[0]], coordinates[edge.vertices[1]])))
        for edge in mesh.edges
    ))
    faces = tuple(sorted(
        tuple(sorted(coordinates[vertex_index] for vertex_index in polygon.vertices))
        for polygon in mesh.polygons
    ))
    return vertices, edges, faces


# mesh/decimal_places: Mesh 与坐标量化精度；返回忽略共线细分 Edge 的 Face 几何签名。
def canonical_mesh_face_signature(mesh, decimal_places=8):
    coordinates = tuple(
        tuple(round(float(value), decimal_places) for value in vertex.co)
        for vertex in mesh.vertices
    )
    return tuple(sorted(
        tuple(sorted(coordinates[vertex_index] for vertex_index in polygon.vertices))
        for polygon in mesh.polygons
    ))


# mesh: probe-only source Mesh；写入 source-local Vertex/Edge identity，验证 Exact Boolean 是否保留拓扑来源。
def mark_source_topology_identity(mesh):
    vertex_id_attribute = mesh.attributes.new(
        "hst_probe_source_vertex_id",
        type="INT",
        domain="POINT",
    )
    vertex_present_attribute = mesh.attributes.new(
        "hst_probe_source_vertex_present",
        type="BOOLEAN",
        domain="POINT",
    )
    edge_id_attribute = mesh.attributes.new(
        "hst_probe_source_edge_id",
        type="INT",
        domain="EDGE",
    )
    edge_present_attribute = mesh.attributes.new(
        "hst_probe_source_edge_present",
        type="BOOLEAN",
        domain="EDGE",
    )
    for vertex in mesh.vertices:
        vertex_id_attribute.data[vertex.index].value = vertex.index + 1
        vertex_present_attribute.data[vertex.index].value = True
    for edge in mesh.edges:
        edge_id_attribute.data[edge.index].value = edge.index + 1
        edge_present_attribute.data[edge.index].value = True


# mesh: 已完成 Exact Difference 的 closed Mesh；删除非 original Faces 后返回 BMesh 与原 EDGE witness layers。
# boundary_origin_records: 可选诊断字典；记录同一 BMEdge 在删除 groove Faces 前后的 Face/attribute provenance。
def open_boolean_mesh_with_witness_layers(
    mesh,
    original_attribute_name,
    boundary_origin_records=None,
):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    original_layer = (
        bm.faces.layers.int.get(original_attribute_name)
        or bm.faces.layers.bool.get(original_attribute_name)
    )
    ensure(original_layer is not None, "Sequential Boolean lost original Face provenance")
    closed_records_by_edge = {}
    if boundary_origin_records is not None:
        face_attribute_layers = tuple(
            (
                attribute.name,
                bm.faces.layers.int.get(attribute.name)
                or bm.faces.layers.bool.get(attribute.name),
            )
            for attribute in mesh.attributes
            if attribute.domain == "FACE" and attribute.name.startswith("hst_")
        )
        edge_attribute_layers = tuple(
            (
                attribute.name,
                bm.edges.layers.int.get(attribute.name)
                or bm.edges.layers.bool.get(attribute.name),
            )
            for attribute in mesh.attributes
            if attribute.domain == "EDGE" and attribute.name.startswith("hst_")
        )
        vertex_attribute_layers = tuple(
            (
                attribute.name,
                bm.verts.layers.int.get(attribute.name),
            )
            for attribute in mesh.attributes
            if attribute.domain == "POINT" and attribute.name.startswith("hst_")
        )
        for edge in bm.edges:
            closed_records_by_edge[edge] = {
                "closed_edge_index": edge.index,
                "vertex_coordinates": [
                    list(coordinate)
                    for coordinate in sorted(
                        tuple(round(float(value), 8) for value in vertex.co)
                        for vertex in edge.verts
                    )
                ],
                "closed_edge_attributes": sorted(
                    attribute_name
                    for attribute_name, layer in edge_attribute_layers
                    if layer is not None and bool(edge[layer])
                ),
                "closed_edge_attribute_values": {
                    attribute_name: int(edge[layer])
                    for attribute_name, layer in edge_attribute_layers
                    if layer is not None and int(edge[layer]) != 0
                },
                "closed_linked_faces": [
                    {
                        "face_index": face.index,
                        "is_original": bool(face[original_layer]),
                        "attributes": sorted(
                            attribute_name
                            for attribute_name, layer in face_attribute_layers
                            if layer is not None and bool(face[layer])
                        ),
                    }
                    for face in sorted(edge.link_faces, key=lambda item: item.index)
                ],
                "closed_vertices": [
                    {
                        "index": vertex.index,
                        "coordinate": [
                            round(float(value), 8) for value in vertex.co
                        ],
                        "attributes": {
                            attribute_name: int(vertex[layer])
                            for attribute_name, layer in vertex_attribute_layers
                            if layer is not None and int(vertex[layer]) != 0
                        },
                    }
                    for vertex in edge.verts
                ],
            }
    groove_faces = [face for face in bm.faces if not bool(face[original_layer])]
    ensure(groove_faces, "Sequential Boolean produced no groove Faces")
    bmesh.ops.delete(bm, geom=groove_faces, context="FACES_KEEP_BOUNDARY")
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    if boundary_origin_records is not None:
        boundary_origin_records.update({
            edge: {
                **closed_records_by_edge[edge],
                "open_edge_index": edge.index,
                "open_linked_face_count": len(edge.link_faces),
            }
            for edge in bm.edges
            if len(edge.link_faces) == 1 and edge in closed_records_by_edge
        })
    return bm


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


# 验证旧 tricky_b fixture 在新结构化 cutter 下不输出错误 PATCHED，并保持 source。
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
    try:
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
    except utils.PipeChamferError as error:
        stats = error.stats
    ensure(
        stats["status"] == "failed",
        "Legacy tricky_b unexpectedly produced a Finalize output before structured ports",
    )
    ensure(
        stats["error_code"] in {
            "result_not_manifold",
            "junction_region_unresolved",
            "complex_region_unsupported",
            "regular_patch_invalid",
            "regular_patch_shared_rail_invalid",
        },
        f"Legacy tricky_b failed for an unrelated reason: {stats['error_code']}",
    )
    source_fingerprint_after = _mesh_fingerprint(obj)
    ensure(
        source_fingerprint_after == expected_fingerprint,
        "Source Mesh fingerprint changed during PATCHED",
    )
    ensure(
        not any(
            obj.name.endswith("_PipeChamfer_TEST")
            and not obj.name.endswith("_FAILED")
            for obj in bpy.data.objects
        ),
        "Legacy tricky_b fail-closed path left a pseudo-success output",
    )
    result.add_detail(f"Extruded.002 failed closed: {stats['error_code']}")


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


# 构造 degree-3 Sharp junction：X 轴为主 strand，Y 轴 branch 保持 unmatched。
# name/collection: 目标 Mesh Object 名称与 Collection。
def make_degree_three_feature_junction(name: str, collection):
    vertices = [
        (0.0, 0.0, 0.05),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 0.0, -1.0),
    ]
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 2, 1),
        (4, 3, 2),
        (0, 3, 1),
        (4, 1, 3),
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    sharp_attribute = mesh_data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for edge in mesh_data.edges:
        sharp_attribute.data[edge.index].value = (
            0 in edge.vertices
            and any(vertex_index in {1, 2, 3} for vertex_index in edge.vertices)
        )
    return obj


# 构造 miter scale 超限的两条 Sharp Edge，Operator 必须拆成两个 splines。
# name/collection: 目标 Mesh Object 名称与 Collection。
def make_acute_feature_turn(name: str, collection):
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.15, 0.1, 0.0),
        (0.0, 0.0, 1.0),
    ]
    faces = [
        (0, 1, 3),
        (0, 3, 2),
        (0, 2, 1),
        (1, 2, 3),
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    sharp_attribute = mesh_data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for edge in mesh_data.edges:
        sharp_attribute.data[edge.index].value = 0 in edge.vertices and (
            1 in edge.vertices or 2 in edge.vertices
        )
    return obj


# 构造精确 90° 的两条 Sharp Edge；Even-Thickness miter 必须保持一个连续 spline。
# name/collection: 目标 Mesh Object 名称与 Collection。
def make_right_angle_feature_turn(name: str, collection):
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    faces = [
        (0, 1, 3),
        (0, 3, 2),
        (0, 2, 1),
        (1, 2, 3),
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    sharp_attribute = mesh_data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for edge in mesh_data.edges:
        sharp_attribute.data[edge.index].value = 0 in edge.vertices and (
            1 in edge.vertices or 2 in edge.vertices
        )
    return obj


# 构造三根彼此正交的 Sharp half-edges；junction 必须配对一组并保留一根 unmatched。
# name/collection: 目标 Mesh Object 名称与 Collection。
def make_orthogonal_degree_three_feature_junction(name: str, collection):
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    faces = [
        (0, 1, 2),
        (0, 3, 1),
        (0, 2, 3),
        (1, 3, 2),
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    sharp_attribute = mesh_data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for edge in mesh_data.edges:
        sharp_attribute.data[edge.index].value = 0 in edge.vertices
    return obj

# 构造 degree-2 平滑闭环，并故意让相邻 Edge 的 patch/convexity metadata 不兼容。
# name/collection: 目标 Mesh Object 名称与 Collection。
def make_smooth_cyclic_feature_ring(name: str, collection):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.0, depth=0.5)
    source = ensure_object_in_collection(bpy.context.active_object, collection)
    source.name = name
    top_rim = [
        edge.index
        for edge in source.data.edges
        if all(source.data.vertices[index].co.z > 0.2 for index in edge.vertices)
    ]
    mark_edge_indices_sharp(source, top_rim)
    return source

# 构造同一 cube 的不同拓扑创建顺序，用于验证配对不依赖 Edge ID。
# name/collection: 目标 Mesh Object 名称与 Collection；variant: 创建顺序变体。
def make_ordered_sharp_cube(name: str, collection, variant: int):
    positions = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    if variant == 0:
        vertex_order = list(range(8))
        face_order = list(range(6))
    else:
        vertex_order = list(range(8))
        face_order = list(range(6))
    new_index_by_old = {
        old_index: new_index
        for new_index, old_index in enumerate(vertex_order)
    }
    ordered_positions = [
        coplanar_fixture_point(positions[index], variant)
        for index in vertex_order
    ]
    ordered_faces = [
        tuple(new_index_by_old[index] for index in faces[face_index])
        for face_index in face_order
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(ordered_positions, [], ordered_faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(obj)
    mark_all_edges_sharp(obj)
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


# 验证 degree-3 junction 选择最直主 strand，并留下单个 unmatched branch。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_pipe_chamfer_degree_three_strand_matching_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("PipeChamferDegreeThreeMatching")
    source = make_degree_three_feature_junction(
        "DegreeThreeFeatureJunction",
        collection,
    )
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(
        source,
        0.05,
        8,
        35.0,
        3.0,
        1.5,
        "FEATURE_GRAPH",
    )
    groups = utils._build_feature_graph(source, 35.0, 3.0, stats)
    junction_record = next(
        record for record in stats["vertex_matching"]
        if len(record["incident_edge_ids"]) == 3
    )
    ensure(len(groups) == 2, f"Degree-3 junction produced {len(groups)} strands")
    ensure(
        sorted(len(group["edge_indices"]) for group in groups) == [1, 2],
        f"Degree-3 strand lengths are wrong: {stats['feature_groups']}",
    )
    ensure(
        len(junction_record["selected_pairs"]) == 1,
        f"Degree-3 junction did not choose one pair: {junction_record}",
    )
    ensure(
        len(junction_record["unmatched_edge_ids"]) == 1,
        f"Degree-3 junction did not preserve one branch: {junction_record}",
    )
    selected_pair = set(junction_record["selected_pairs"][0])
    selected_group = next(
        group for group in groups
        if set(group["edge_indices"]) == selected_pair
    )
    endpoint_pair = {
        selected_group["vertex_indices"][0],
        selected_group["vertex_indices"][-1],
    }
    ensure(
        endpoint_pair == {1, 3},
        f"Degree-3 matching did not keep the straight strand: {endpoint_pair}",
    )
    ensure(
        stats["cutter_strands"],
        "Degree-3 matching did not emit CutterStrandRecord diagnostics",
    )
    result.add_detail(
        f"selected={junction_record['selected_pairs']}, "
        f"unmatched={junction_record['unmatched_edge_ids']}"
    )

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


# 验证受控 Even-Thickness asset exact/version/fingerprint 导入，并由所有 strands 共用。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_curve_pipe_asset_import_and_backend_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    first_group = utils.ensure_feature_chamfer_curve_pipe_asset()
    second_group = utils.ensure_feature_chamfer_curve_pipe_asset()
    ensure(first_group is second_group, "Curve Pipe asset import is not idempotent")
    ensure(
        first_group.name == test_context.const.FEATURE_CHAMFER_CURVE_NODE,
        "Curve Pipe asset exact name changed",
    )
    ensure(
        first_group.get(test_context.const.FEATURE_CHAMFER_CURVE_ASSET_VERSION_TAG)
        == test_context.const.FEATURE_CHAMFER_CURVE_ASSET_VERSION,
        "Curve Pipe asset version mismatch",
    )
    ensure(
        first_group.get(
            test_context.const.FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG
        )
        == test_context.const.FEATURE_CHAMFER_CURVE_FINGERPRINT,
        "Curve Pipe asset fingerprint mismatch",
    )
    dependency = bpy.data.node_groups.get(
        test_context.const.FEATURE_CHAMFER_CURVE_DEPENDENCY
    )
    ensure(dependency is not None, "Poly-Curve Info dependency was not appended")
    ensure(
        dependency.get(
            test_context.const.FEATURE_CHAMFER_CURVE_ASSET_FINGERPRINT_TAG
        )
        == test_context.const.FEATURE_CHAMFER_CURVE_DEPENDENCY_FINGERPRINT,
        "Poly-Curve Info fingerprint mismatch",
    )

    collection = make_collection("CurvePipeBackend")
    source = make_degree_three_feature_junction(
        "CurvePipeBackendSource",
        collection,
    )
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=0.05,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="PIPES",
        keep_debug_objects=True,
    )
    ensure(stats["status"] == "finished", f"Curve Pipe backend failed: {stats}")
    ensure(
        all(
            strand["generation_backend"] == "EVEN_THICKNESS_GN"
            for strand in stats["cutter_strands"]
        ),
        f"Not every strand used Even-Thickness: {stats['cutter_strands']}",
    )
    ensure(
        all(
            strand["geometry_guard"]["status"] == "PASS"
            for strand in stats["cutter_strands"]
        ),
        f"Curve Pipe geometry guard failed: {stats['cutter_strands']}",
    )
    result.add_detail(
        f"asset={first_group.name}, strands={len(stats['cutter_strands'])}"
    )


# 验证 rail A/B seam 输出统一 RailPairRecord，并保持 source 不变。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_feature_chamfer_rail_oracle_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("RailOracleContract")
    source = make_test_mesh("RailOracleSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    source_hash = mesh_topology_hash(source)
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
    ensure(stats["status"] == "finished", f"Rail A/B extraction failed: {stats}")
    summaries = stats["rail_oracle_summary"]
    ensure(
        {"boolean", "source_surface"} == set(summaries),
        f"Rail A/B summary is incomplete: {summaries}",
    )
    records = (
        stats["boolean_rail_pairs"]
        + stats["surface_offset_rail_pairs"]
    )
    ensure(records, "Rail A/B extraction emitted no RailPairRecords")
    required_fields = {
        "backend",
        "group_id",
        "left_patch_id",
        "right_patch_id",
        "rail_left",
        "rail_right",
        "u",
        "width_error",
        "ownership_confidence",
        "geometry_guard",
    }
    ensure(
        all(required_fields <= set(record) for record in records),
        f"RailPairRecord contract is incomplete: {records[:1]}",
    )
    ensure(
        mesh_topology_hash(source) == source_hash,
        "Rail A/B extraction changed source Mesh",
    )
    ensure(
        all(
            "guarded_coverage" in summary
            and "guard_failures" in summary
            for summary in summaries.values()
        ),
        f"Rail geometry guard summary is incomplete: {summaries}",
    )
    ensure(
        all(
            record["geometry_guard"]["owner_group_id"] == record["group_id"]
            for record in records
        ),
        f"RailPairRecord owner guard mismatch: {records[:1]}",
    )
    ensure(
        summaries["boolean"].get("ownership_backend")
        == "FINAL_BOOLEAN_BOUNDARY_PIPE_SURFACE"
        and all(
            record.get("ownership_backend")
            == "FINAL_BOOLEAN_BOUNDARY_PIPE_SURFACE"
            for record in stats["boolean_rail_pairs"]
        ),
        f"Boolean Rail did not use final Boundary adjacency: {summaries['boolean']}",
    )
    topology = stats["boundary_rail_topology"]
    ensure(
        stats["boundary_degenerate_cleanup"]["zero_edge_count_before"] >= 0
        and stats["boundary_degenerate_cleanup"]["zero_edge_count_after"] == 0,
        f"Open Boundary degenerate cleanup failed: {stats['boundary_degenerate_cleanup']}",
    )
    ensure(
        topology["adjacency_guard"]["zero_length_edge_count"] == 0
        and topology["adjacency_guard"]["consumable_rail_guard"] == "PASS",
        f"Final Boundary contains non-consumable zero-length Rail edges: {topology}",
    )
    chain_owners_by_edge = {}
    for chain in topology["owned_chains"]:
        for edge_index in chain["edge_indices"]:
            chain_owners_by_edge.setdefault(edge_index, set()).add(
                (chain["pipe_id"], chain["patch_id"])
            )
    ensure(
        all(
            set(map(tuple, segment["owner_pairs"]))
            <= chain_owners_by_edge.get(segment["edge_index"], set())
            for segment in topology["shared_owner_rails"]
        ),
        f"Multi-owner Rail edges are not consumable by every owner chain: {topology}",
    )
    output = bpy.data.objects[stats["output_object_name"]]
    output_bmesh = bmesh.new()
    output_bmesh.from_mesh(output.data)
    boundary_edges = {
        tuple(
            sorted(
                (
                    tuple(round(value, 7) for value in edge.verts[0].co),
                    tuple(round(value, 7) for value in edge.verts[1].co),
                )
            )
        )
        for edge in output_bmesh.edges
        if len(edge.link_faces) == 1
    }
    output_bmesh.free()
    rail_edges = set()
    for chain in topology["owned_chains"]:
        points = chain["coordinates"]
        segment_count = len(points) if chain["is_cyclic"] else len(points) - 1
        for index in range(segment_count):
            rail_edges.add(
                tuple(
                    sorted(
                        (
                            tuple(round(value, 7) for value in points[index]),
                            tuple(
                                round(value, 7)
                                for value in points[(index + 1) % len(points)]
                            ),
                        )
                    )
                )
            )
    rail_edges.update(
        tuple(
            sorted(
                tuple(round(value, 7) for value in point)
                for point in segment["coordinates"]
            )
        )
        for segment in (
            topology["unowned_segments"]
            + topology["deferred_segments"]
            + topology["shared_owner_segments"]
        )
    )
    ensure(
        topology["adjacency_guard"]["status"] == "PASS",
        f"Final Boundary serialization lost edges: {topology}",
    )
    ensure(
        not topology["adjacency_guard"]["coordinate_reconstruction"]
        and not topology["adjacency_guard"]["centerline_sorting"],
        f"Final Boundary Rail reintroduced coordinate reconstruction: {topology}",
    )
    ensure(
        rail_edges == boundary_edges,
        (
            "Rail segments are not an exact partition of final Boolean Boundary Edges: "
            f"missing={len(boundary_edges - rail_edges)}, "
            f"extra={len(rail_edges - boundary_edges)}"
        ),
    )
    ensure(
        all(
            record["geometry_guard"].get("sampling_backend")
            == "FINAL_BOOLEAN_BOUNDARY_EDGES"
            and record["geometry_guard"].get("correspondence_error_percentile")
            == 0.95
            for record in stats["boolean_rail_pairs"]
        ),
        "Boolean Rail guard did not use Boundary correspondence semantics",
    )
    ensure(
        topology["unowned_edge_count"] == 0
        or all(
            segment["region_class"] == "REGULAR_UNOWNED"
            for segment in topology["unowned_segments"]
        ),
        f"Boundary ownership classes are inconsistent: {topology}",
    )
    ensure(
        all(
            segment["region_class"] == "JUNCTION_OR_TERMINAL_DEFERRED"
            for segment in topology["deferred_segments"]
        ),
        f"Deferred Boundary classes are inconsistent: {topology}",
    )
    ensure(
        topology["owned_edge_count"]
        + topology["unowned_edge_count"]
        + topology["deferred_edge_count"]
        == topology["boundary_edge_count"],
        f"Boundary ownership accounting is incomplete: {topology}",
    )
    ensure(
        topology["shared_owner_edge_count"]
        == len(topology["shared_owner_segments"])
        and all(
            segment["region_class"] == "MULTI_OWNER_RAIL"
            and len(segment["owner_pairs"]) >= 2
            for segment in topology["shared_owner_segments"]
        ),
        f"Shared Boundary Rail ownership is incomplete: {topology}",
    )
    boolean_summary = summaries["boolean"]
    consumption_guard = boolean_summary["boundary_consumption_guard"]
    ensure(
        consumption_guard["status"] == "PASS"
        and consumption_guard["consumed_edge_count"]
        == consumption_guard["boundary_edge_count"]
        and not consumption_guard["missing_edge_indices"]
        and not consumption_guard["extra_edge_indices"],
        f"Boundary Rail consumption is incomplete: {consumption_guard}",
    )

    ensure(
        not boolean_summary["unclassified_boundary_edge_indices"]
        and all(
            any(
                edge_index in chain["edge_indices"]
                and any(
                    vertex_index in {
                        vertex_index
                        for segment in topology["shared_owner_rails"]
                        for vertex_index in segment["vertex_indices"]
                    }
                    for vertex_index in chain["vertex_indices"]
                )
                for chain in topology["owned_chains"]
            )
            for edge_index in boolean_summary[
                "shared_seam_chain_component_indices"
            ]
        ),
        f"Overlap fragments lack shared-seam chain adjacency: {boolean_summary}",
    )
    ensure(
        set(boolean_summary["shared_overlap_edge_indices"])
        <= {
            segment["edge_index"]
            for segment in topology["shared_owner_rails"]
        },
        f"Shared overlap Rail consumption mismatch: {boolean_summary}",
    )
    ensure(
        boolean_summary["classified_span_count"]
        + boolean_summary["deferred_span_count"]
        == boolean_summary["span_count"],
        f"Rail span classification is incomplete: {boolean_summary}",
    )
    ensure(
        boolean_summary["owned_span_count"]
        == boolean_summary["pairable_span_count"]
        and boolean_summary["guard_valid_span_count"]
        == boolean_summary["valid_span_count"],
        f"Rail A/B ownership or guard accounting is dishonest: {boolean_summary}",
    )

    ensure(
        all(
            record["record_type"] == "OCCLUDED_RAIL_SPAN"
            and not record["pairing_required"]
            and record["boundary_edge_indices"]
            and record["occlusion_evidence"]["overlap_pipe_ids"]
            and set(record["occlusion_evidence"]["local_endpoint_occluders"])
            == set(record["occlusion_evidence"]["endpoint_sides"])
            and all(
                any(
                    occluder["point_inside_pipe"]
                    or occluder["surface_distance"] <= 0.08 * 1.10
                    for occluder in occluders
                )
                for occluders in record["occlusion_evidence"][
                    "local_endpoint_occluders"
                ].values()
            )
            and record["geometry_guard"]["status"] == "NOT_APPLICABLE"
            and record["geometry_guard"]["guard_type"]
            == "OCCLUDED_ENDPOINT_CLASSIFICATION"
            for record in boolean_summary["occluded_spans"]
        ),
        f"Occluded Rail span contract is incomplete: {boolean_summary}",
    )
    ensure(
        all(
            record["record_type"] == "DEFERRED_RAIL_REGION"
            and record["geometry_guard"]["status"] == "DEFERRED"
            for record in boolean_summary["deferred_spans"]
        ),
        f"Deferred RailRegionRecord contract is dishonest: {boolean_summary}",
    )
    result.add_detail(
        f"boolean={summaries['boolean']['coverage']:.3f}, "
        f"surface={summaries['source_surface']['coverage']:.3f}"
    )


# 验证 overlap endpoint outlier 只裁掉连续前缀，core 仍引用原始 BMesh Edge。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_feature_chamfer_rail_endpoint_core_trim_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    bm = bmesh.new()
    left_vertices = [
        bm.verts.new(coordinate)
        for coordinate in ((-0.03, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    ]
    right_vertices = [
        bm.verts.new(coordinate)
        for coordinate in ((0.0, 0.0141421356, 0.0), (1.0, 0.0141421356, 0.0))
    ]
    left_edges = [
        bm.edges.new((left_vertices[index], left_vertices[index + 1]))
        for index in range(2)
    ]
    right_edges = [bm.edges.new((right_vertices[0], right_vertices[1]))]
    trimmed = utils._trim_rail_pair_to_width_core(
        {"vertices": left_vertices, "edges": left_edges, "is_cyclic": False},
        {"vertices": right_vertices, "edges": right_edges, "is_cyclic": False},
        0.01,
    )
    ensure(trimmed is not None, "Rail endpoint core trim rejected a valid core")
    left_core, right_core, diagnostics = trimmed
    ensure(
        left_core["edges"] == [left_edges[1]]
        and right_core["edges"] == right_edges
        and diagnostics["left_trimmed_edge_count"] == 1,
        f"Rail endpoint core trim synthesized or reordered edges: {diagnostics}",
    )
    bm.free()
    result.add_detail("trimmed one endpoint edge; core kept original adjacency")


# 验证 source-surface Rail 使用 owner Face intrinsic offset，而非 3D 欧氏距离近似。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_source_surface_intrinsic_offset_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("RailIntrinsicOffset")
    source = make_test_mesh("RailIntrinsicOffsetSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=0.08,
        pipe_resolution=4,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="OPEN_BOUNDARY",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
    )
    records = stats["surface_offset_rail_pairs"]
    ensure(records, "Intrinsic source-surface rail extraction emitted no records")
    ensure(
        all(
            "intrinsic_offset_error" in record
            and "projection_distance" in record
            and "projection_continuity_error" in record
            for record in records
        ),
        f"Intrinsic projection diagnostics are missing: {records[:1]}",
    )
    ensure(
        stats["rail_oracle_summary"]["source_surface"]["guarded_coverage"] == 1.0,
        f"Planar owner-patch intrinsic rails did not pass: {stats['rail_oracle_summary']['source_surface']}",
    )
    result.add_detail(
        f"intrinsic source-surface coverage={stats['rail_oracle_summary']['source_surface']['guarded_coverage']:.3f}"
    )


# 验证曲面 owner-patch Rail 的累计 intrinsic distance 与 3D chord 明确可区分。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_folded_surface_walk_intrinsic_distance_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    segment_count = 32
    vertices = []
    for x in (-0.5, 0.5):
        vertices.extend(
            (x, math.cos(index * math.pi / segment_count), math.sin(index * math.pi / segment_count))
            for index in range(segment_count + 1)
        )
    polygons = [
        (
            index,
            index + 1,
            segment_count + 2 + index,
            segment_count + 1 + index,
        )
        for index in range(segment_count)
    ]
    mesh_data = bpy.data.meshes.new("RailFoldedSurfaceOwner")
    mesh_data.from_pydata(vertices, [], polygons)
    mesh_data.update()
    owner_bmesh = bmesh.new()
    owner_bmesh.from_mesh(mesh_data)
    owner_bmesh.edges.ensure_lookup_table()
    owner_bmesh.faces.ensure_lookup_table()
    owner_face = owner_bmesh.faces[0]
    owner_face_patch = {face: 0 for face in owner_bmesh.faces}
    radius = 1.2
    record = utils._offset_point_on_face(
        Vector((0.0, 1.0, 0.0)),
        Vector((-1.0, 0.0, 0.0)),
        owner_face,
        owner_face_patch,
        radius,
    )
    ensure(record is not None, "Folded owner-patch Surface walk failed")
    chord_length = (record["point"] - Vector((0.0, 1.0, 0.0))).length
    ensure(
        record["intrinsic_offset_error"] <= radius * 0.01
        and chord_length < radius - 0.05,
        f"Surface walk did not distinguish intrinsic distance from chord: record={record}, chord={chord_length}",
    )
    owner_bmesh.free()
    result.add_detail(
        f"folded intrinsic={radius:.3f}, chord={chord_length:.3f}"
    )


# 验证 owner Face walk 只通过 Surface Patch adjacency 前进，不会吸到同 Patch 的邻近非相邻 Face。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_owner_face_adjacency_walk_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    mesh_data = bpy.data.meshes.new("RailOwnerFaceAdjacency")
    mesh_data.from_pydata(
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 0.0, 0.01),
            (1.0, 0.0, 0.01),
            (0.0, 1.0, 0.01),
            (1.0, 1.0, 0.01),
        ],
        [],
        [(0, 1, 3, 2), (4, 6, 7, 5)],
    )
    mesh_data.update()
    owner_bmesh = bmesh.new()
    owner_bmesh.from_mesh(mesh_data)
    owner_bmesh.edges.ensure_lookup_table()
    owner_bmesh.faces.ensure_lookup_table()
    face_patch = {face: 0 for face in owner_bmesh.faces}
    record = utils._offset_point_on_face(
        Vector((0.5, 0.0, 0.0)),
        Vector((1.0, 0.0, 0.0)),
        owner_bmesh.faces[0],
        face_patch,
        0.25,
    )
    ensure(record is not None, "Planar owner Face adjacency walk failed")
    ensure(
        record["owner_face_path"] == [0]
        and abs(record["point"].z) <= 1.0e-8,
        f"Owner Face walk jumped to a non-adjacent Face: {record}",
    )
    owner_bmesh.free()
    result.add_detail(f"owner face path={record['owner_face_path']}")


# 验证 Regular Strip seam 在两条同向 Rail 上生成单调、无凹陷的连接。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_regular_strip_terminal_span_guard_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    left = [
        Vector((0.0, 0.0, 0.0)),
        Vector((0.0, 0.0, 0.04)),
        Vector((0.0, 0.0, 1.44)),
    ]
    right = [
        Vector((0.0, 0.014, 0.0)),
        Vector((0.0, 0.014, 0.02)),
        Vector((0.0, 0.014, 0.04)),
        Vector((0.0, 0.014, 1.44)),
    ]
    strip = utils.build_chamfer_strip(
        left,
        right,
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(len(left) - 1, len(right) - 1)],
            "expected_width": 0.014,
            "maximum_width_error": 0.001,
        },
    )
    ensure(strip["diagnostics"]["status"] == "PASS", f"Strip guard failed: {strip}")
    ensure(
        strip["diagnostics"]["monotonic"],
        f"Regular Strip created non-monotonic correspondence: {strip}",
    )
    ensure(
        strip["path"][0] == (0, 0)
        and strip["path"][-1] == (len(left) - 1, len(right) - 1),
        f"Terminal-to-port correspondence drifted: {strip['path']}",
    )
    ensure(
        strip["diagnostics"]["width_error_inlier_ratio"] >= 0.95,
        f"Regular Strip width guard drifted: {strip}",
    )
    ensure(
        strip["diagnostics"]["one_sided_step_count"] > 0,
        f"Fixture did not exercise unequal-density correspondence: {strip}",
    )
    scale = 100.0
    scaled_strip = utils.build_chamfer_strip(
        [coordinate * scale for coordinate in left],
        [coordinate * scale for coordinate in right],
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(len(left) - 1, len(right) - 1)],
            "expected_width": 0.014 * scale,
            "maximum_width_error": 0.001 * scale,
        },
    )
    ensure(
        scaled_strip["path"] == strip["path"]
        and scaled_strip["faces"] == strip["faces"],
        f"Regular Strip topology changed under uniform scale: {strip} / {scaled_strip}",
    )
    unsafe_strip = utils.build_chamfer_strip(
        [
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.2)),
            Vector((0.0, 0.0, 1.4)),
        ],
        [
            Vector((0.0, 0.014, 0.0)),
            Vector((0.0, 0.014, 1.4)),
        ],
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(2, 1)],
            "expected_width": 0.014,
            "maximum_width_error": 0.001,
        },
    )
    ensure(
        unsafe_strip["diagnostics"]["status"] == "FAIL"
        and unsafe_strip["diagnostics"]["maximum_relative_advance"]
        > unsafe_strip["diagnostics"]["maximum_relative_advance_limit"],
        f"Regular Strip accepted a single severe one-sided advance: {unsafe_strip}",
    )
    result.add_detail("Regular Strip preserved monotonic and scale-invariant terminal correspondence")


# 验证 Regular Strip DP 可绕开会生成零面积 Face 的重复 Rail 点，且无路径时结构化 fail-closed。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_regular_strip_zero_area_path_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    routable = utils.build_chamfer_strip(
        [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0))],
        [Vector((0.5, 0.0, 0.0)), Vector((0.5, 1.0, 0.0))],
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(1, 1)],
            "reject_zero_area_faces": True,
        },
    )
    ensure(
        routable["diagnostics"]["status"] == "PASS"
        and routable["path"] == [(0, 0), (0, 1), (1, 1)],
        f"Zero-area-aware DP did not route around an unreachable cell: {routable}",
    )
    left = [
        Vector((0.0, 0.0, 0.0)),
        Vector((0.0, 0.0, 0.05)),
        Vector((0.0, 0.0, 0.1)),
    ]
    right = [
        Vector((0.0141421356, 0.0, 0.0)),
        Vector((0.0141421356, 0.0, 0.0)),
        Vector((0.0141421356, 0.0, 0.1)),
    ]
    strip = utils.build_chamfer_strip(
        left,
        right,
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(len(left) - 1, len(right) - 1)],
            "expected_width": 0.0141421356,
            "maximum_width_error": 0.006,
            "reject_zero_area_faces": True,
        },
    )
    ensure(
        strip["diagnostics"]["status"] == "FAIL"
        and strip["diagnostics"]["reasons"]
        == ["NO_MONOTONIC_CORRESPONDENCE_PATH"],
        f"Zero-area-aware DP did not fail closed on a degenerate Rail: {strip}",
    )
    no_path = utils.build_chamfer_strip(
        [Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))],
        [Vector((0.014, 0.0, 0.0)), Vector((0.014, 0.0, 0.0))],
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(1, 1)],
            "expected_width": 0.014,
            "maximum_width_error": 0.006,
            "reject_zero_area_faces": True,
        },
    )
    ensure(
        no_path["diagnostics"]["status"] == "FAIL"
        and no_path["diagnostics"]["reasons"]
        == ["NO_MONOTONIC_CORRESPONDENCE_PATH"],
        f"No-path Strip did not fail closed: {no_path}",
    )
    result.add_detail("zero-area steps rejected; no-path results stayed structured")


# 验证 Phase C DP 优先选择满足既有 signed-width hard guard 的路径，不修改 guard 阈值。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_regular_strip_hard_guard_path_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    left = [
        Vector((0.0, 0.0, 0.0)),
        Vector((0.0, 0.0, 0.05)),
        Vector((0.0, 0.0, 0.10)),
    ]
    right = [
        Vector((0.014, 0.0, 0.0)),
        Vector((0.014, 0.0, 0.025)),
        Vector((0.014, 0.0, 0.075)),
        Vector((0.014, 0.0, 0.10)),
    ]
    strip = utils.build_chamfer_strip(
        left,
        right,
        terminal_constraints={
            "start_pairs": [(0, 0)],
            "end_pairs": [(2, 3)],
            "expected_width": 0.014,
            "maximum_width_error": 0.006,
            "reject_zero_area_faces": True,
            "prefer_hard_guard_path": True,
        },
    )
    ensure(
        strip["diagnostics"]["status"] == "PASS"
        and strip["diagnostics"]["maximum_relative_advance"]
        <= strip["diagnostics"]["maximum_relative_advance_limit"]
        and strip["diagnostics"]["width_error_inlier_ratio"] >= 0.95,
        f"Hard-guard-aware DP did not select a legal path: {strip}",
    )
    ensure(
        strip["diagnostics"]["relative_advance_violation_count"] == 0
        and strip["diagnostics"]["signed_width_violation_count"] == 0,
        f"Hard guards were not the primary DP objective: {strip}",
    )
    result.add_detail("DP path satisfied unchanged signed-width hard guards")


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
    ensure(
        boolean_modifier.operand_type in {"OBJECT", "COLLECTION"},
        "Boolean preview does not use a supported cutter operand",
    )
    if boolean_modifier.operand_type == "OBJECT":
        ensure(boolean_modifier.object is not None, "Boolean cutter Object is missing")
    else:
        ensure(boolean_modifier.collection is not None, "Boolean cutter Collection is missing")
    diagnostic = json.loads(
        bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}")
    )
    ensure(bpy.data.objects.get("UnionDifferenceSource_PipeUnion_TEST") is None, "Collection Difference created a union Mesh")
    cutter_collection = bpy.data.collections.get("UnionDifferenceSource_PipeCutters_TEST")
    ensure(cutter_collection is not None, "Collection Difference cutter set is missing")
    ensure(
        diagnostic["cutter_set_object_count"] == diagnostic["pipe_group_count"],
        "Cutter diagnostics did not count every structured strand",
    )
    ensure(
        len(cutter_collection.objects) > 0,
        "Cutter Collection contains no Boolean operand objects",
    )
    ensure(mesh_topology_hash(source) == source_hash, "BOOLEAN_CUT changed source Mesh")

    source.hide_set(False)
    repeated_result = run_pipe_chamfer_operator(source, "BOOLEAN_CUT", radius=0.08)
    ensure("FINISHED" in repeated_result, "Repeated BOOLEAN_CUT did not finish")
    cutter_collection = bpy.data.collections.get("UnionDifferenceSource_PipeCutters_TEST")
    ensure(cutter_collection is not None, "Repeated run lost the Cutter Collection")
    repeated_diagnostic = json.loads(
        bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}")
    )
    ensure(
        repeated_diagnostic["cutter_set_object_count"]
        == repeated_diagnostic["pipe_group_count"],
        "Repeated run lost structured strand diagnostics",
    )
    ensure(
        len(cutter_collection.objects) > 0,
        "Repeated run lost every Boolean operand object",
    )

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


# 验证目标 Operator 的 Preview 与 Finalize 共享 immutable ChamferPlan shadow contract。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_shared_chamfer_plan_shadow_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNSharedChamferPlan")
    source = make_test_mesh("GNSharedChamferPlanSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.08,
    )
    ensure(preview_result == {"FINISHED"}, "Shared ChamferPlan Preview failed")
    ensure(modifier is not None, "Shared ChamferPlan Preview modifier is missing")
    plan_module = test_context.addon.utils.feature_chamfer_plan_utils
    preview_plan = plan_module.read_chamfer_plan(modifier)
    ensure(preview_plan is not None, "Preview did not persist a ChamferPlan")
    ensure(preview_plan.is_complete, "Supported Preview plan is incomplete")
    ensure(preview_plan.feature_strands, "Preview plan has no FeatureStrands")
    ensure(
        len({port.port_id for port in preview_plan.junction_ports})
        == len(preview_plan.junction_ports),
        "Preview plan contains duplicate JunctionPort IDs",
    )
    ensure(preview_plan.rail_chains, "Preview plan has no RailChains")
    ensure(
        preview_plan.strip_correspondences,
        "Preview plan has no StripCorrespondences",
    )
    ensure(
        preview_plan.unsupported_regions == (),
        "Supported Preview plan unexpectedly contains UnsupportedRegions",
    )
    ensure(
        preview_plan.sharp_edge_count
        == sum(len(strand.ordered_edge_keys) for strand in preview_plan.feature_strands),
        "ChamferPlan Sharp Edge coverage ledger is incomplete",
    )
    ensure(
        all(
            correspondence.left_rail_id != correspondence.right_rail_id
            for correspondence in preview_plan.strip_correspondences
        ),
        "ChamferPlan StripCorrespondence reuses one rail for both sides",
    )
    ensure(
        preview_plan.plan_id == plan_module.chamfer_plan_fingerprint(preview_plan),
        "Preview plan ID does not match its immutable payload",
    )
    finalize_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, "Shared ChamferPlan Finalize failed")
    output = bpy.context.active_object
    finalize_plan = plan_module.read_chamfer_plan(output)
    ensure(finalize_plan is not None, "Finalize output did not persist a ChamferPlan")
    ensure(
        finalize_plan.plan_id == preview_plan.plan_id,
        "Preview and Finalize did not share the same ChamferPlan ID",
    )
    ensure(
        finalize_plan.provenance == preview_plan.provenance,
        "Preview and Finalize ChamferPlan provenance diverged",
    )
    boundary_binding = json.loads(
        bpy.context.scene.get("hst_pipe_chamfer_last_result", "{}")
    ).get("chamfer_plan_boundary_binding", {})
    ensure(
        boundary_binding.get("plan_id") == preview_plan.plan_id
        and boundary_binding.get("backend")
        == "FINAL_BOOLEAN_BOUNDARY_SHADOW_BINDING",
        f"Finalize did not emit shared-plan Boundary binding: {boundary_binding}",
    )
    ensure(
        boundary_binding.get("status") == "PASS"
        and boundary_binding.get("bound_rail_count", 0) > 0
        and boundary_binding.get("consumed_edge_count")
        == boundary_binding.get("boundary_edge_count")
        and not boundary_binding.get("missing_edge_indices")
        and not boundary_binding.get("extra_edge_indices")
        and not boundary_binding.get("unclassified_edge_indices")
        and not boundary_binding.get("missing_from_plan_binding")
        and not boundary_binding.get("extra_in_plan_binding")
        and not boundary_binding.get("missing_expected_rail_ids")
        and not boundary_binding.get("missing_correspondence_rail_ids")
        and boundary_binding.get("bound_expected_rail_count")
        == boundary_binding.get("expected_rail_count")
        and boundary_binding.get("bound_strip_correspondence_count")
        == boundary_binding.get("strip_correspondence_count")
        and boundary_binding.get("all_bound_ports_exist"),
        f"Shared-plan Boundary coverage is incomplete: {boundary_binding}",
    )
    ensure(
        not boundary_binding.get("coordinate_reconstruction")
        and not boundary_binding.get("centerline_sorting")
        and not boundary_binding.get("moves_boundary"),
        f"Boundary binding changed geometry semantics: {boundary_binding}",
    )
    result.add_detail(f"plan_id={preview_plan.plan_id}")


# 验证 ChamferPlan 会把穿过 strand 内部的 Feature junction 记录为显式 JunctionPort。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_chamfer_plan_internal_junction_port_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    fixtures = (
        ("DegreeThree", make_orthogonal_degree_three_feature_junction, 3, 2),
        ("DegreeFour", make_crossing_feature_strands, 4, 2),
    )
    plan_module = test_context.addon.utils.feature_chamfer_plan_utils
    for label, fixture_builder, expected_degree, expected_strand_count in fixtures:
        collection = make_collection(f"GNPlan{label}Junction")
        source = fixture_builder(f"GNPlan{label}JunctionSource", collection)
        preview_result, modifier = run_feature_chamfer_gn(
            source,
            action="PREVIEW",
            radius=0.05,
        )
        ensure(preview_result == {"FINISHED"}, f"{label} plan Preview failed")
        plan = plan_module.read_chamfer_plan(modifier)
        junction_port = max(
            plan.junction_ports,
            key=lambda port: port.feature_degree,
            default=None,
        )
        ensure(junction_port is not None, f"{label} internal junction port is missing")
        ensure(
            junction_port.feature_degree == expected_degree,
            f"{label} Feature degree is wrong: {junction_port}",
        )
        ensure(
            len(junction_port.incident_strand_ids) == expected_strand_count,
            f"{label} strand incidence is incomplete: {junction_port}",
        )
        ensure(
            all(
                junction_port.port_id in rail.endpoint_port_ids
                for rail in plan.rail_chains
                if rail.owner_strand_id in junction_port.incident_strand_ids
            ),
            f"{label} rail-to-junction coverage is incomplete: {junction_port}",
        )
    result.add_detail("degree-3/4 internal junction ports preserve Feature degree and incidence")


# 验证重合但未焊接的 Sharp vertices 不会被静默合并成同一个 JunctionPort。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_chamfer_plan_disconnected_coincident_ports_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNPlanCoincidentPorts")
    source = make_edge_network(
        "GNPlanCoincidentPortsSource",
        collection,
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        ((0, 1), (2, 3)),
    )
    sharp_attribute = source.data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for item in sharp_attribute.data:
        item.value = True
    groups = [
        {
            "edge_indices": [0],
            "vertex_indices": [0, 1],
            "is_cyclic": False,
            "patch_pair_by_edge": [(0, 1)],
            "convexity_by_edge": [1],
            "selected_pair_vertex_ids": [],
            "start_feature_degree": 1,
            "end_feature_degree": 1,
        },
        {
            "edge_indices": [1],
            "vertex_indices": [2, 3],
            "is_cyclic": False,
            "patch_pair_by_edge": [(2, 3)],
            "convexity_by_edge": [1],
            "selected_pair_vertex_ids": [],
            "start_feature_degree": 1,
            "end_feature_degree": 1,
        },
    ]
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        groups,
        0.05,
        "GN_PREVIEW_V1",
    )
    coincident_ports = [
        port
        for port in plan.junction_ports
        if port.vertex_key.startswith("0.00000000,0.00000000,0.00000000#")
    ]
    ensure(len(coincident_ports) == 2, f"Coincident ports were merged: {coincident_ports}")
    ensure(
        all(port.feature_degree == 1 for port in coincident_ports),
        f"Coincident terminal degrees were combined: {coincident_ports}",
    )
    result.add_detail("two disconnected coincident vertices remain distinct ports")


# 验证 endpoint Port 的相邻 Patch incidence 来自 source topology，并可生成 strand-local occluded witness。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_chamfer_plan_endpoint_patch_incidence_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNPlanEndpointPatchIncidence")
    mesh = bpy.data.meshes.new("GNPlanEndpointPatchIncidenceMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        (),
        ((0, 1, 2), (0, 3, 1)),
    )
    mesh.update()
    source = bpy.data.objects.new("GNPlanEndpointPatchIncidenceSource", mesh)
    collection.objects.link(source)
    sharp_attribute = mesh.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    feature_edge_index = next(
        edge.index for edge in mesh.edges if set(edge.vertices) == {0, 1}
    )
    sharp_attribute.data[feature_edge_index].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [feature_edge_index],
        "vertex_indices": [0, 1],
        "is_cyclic": False,
        "patch_pair": (0, 0),
        "patch_pair_by_edge": [(0, 0)],
        "convexity_by_edge": [1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 1,
        "end_feature_degree": 1,
    }
    plan_module = test_context.addon.utils.feature_chamfer_plan_utils
    plan = plan_module.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
        source_patch_ids=(0, 4),
    )
    strand = plan.feature_strands[0]
    start_incidence = next(
        incidence
        for incidence in plan.junction_port_patch_incidences
        if incidence.owner_strand_id == strand.strand_id
        and incidence.endpoint_role == "START"
    )
    ensure(
        start_incidence.junction_port_id == strand.start_port_id
        and start_incidence.source_patch_ids == (0, 4),
        f"Endpoint Patch incidence did not preserve source topology: {start_incidence}",
    )
    roundtrip = plan_module.chamfer_plan_from_json(
        plan_module.chamfer_plan_json(plan)
    )
    ensure(
        roundtrip == plan
        and plan_module.chamfer_plan_fingerprint(roundtrip) == plan.plan_id,
        "Endpoint Patch incidence was lost by plan JSON/fingerprint roundtrip",
    )
    witnesses = test_context.addon.utils.experimental_pipe_chamfer_utils._build_pipe_boundary_witnesses(
        plan,
        [group],
        source.data,
    )[7]
    occluded_witness = next(
        witness
        for witness in witnesses
        if witness.junction_port_id == strand.start_port_id
        and witness.source_patch_id == 4
    )
    validation = test_context.addon.utils.feature_chamfer_binding_utils.validate_boundary_witnesses(
        plan,
        1,
        (occluded_witness,),
        ((occluded_witness.witness_id,),),
    )
    ensure(
        validation.status == "PASS"
        and occluded_witness.owner_rail_ids
        == (f"rail:{strand.strand_id}:patch:0",),
        f"Port-local Patch incidence did not produce a valid strand witness: {validation}",
    )
    result.add_detail("source topology authorized one strand-local Port/Patch witness")


# 验证 cyclic canonicalization 保持每条 Edge 与相邻 Vertex segment 的 metadata 对齐。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_chamfer_plan_cyclic_metadata_alignment_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNPlanCyclicAlignment")
    source = make_edge_network(
        "GNPlanCyclicAlignmentSource",
        collection,
        ((2.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0, 1), (1, 2), (2, 0)),
    )
    sharp_attribute = source.data.attributes.new(
        "sharp_edge",
        type="BOOLEAN",
        domain="EDGE",
    )
    for item in sharp_attribute.data:
        item.value = True
    group = {
        "edge_indices": [0, 1, 2],
        "vertex_indices": [0, 1, 2],
        "is_cyclic": True,
        "patch_pair_by_edge": [(10, 11), (20, 21), (30, 31)],
        "convexity_by_edge": [1, -1, 1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 2,
        "end_feature_degree": 2,
    }
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    strand = plan.feature_strands[0]
    expected_owner_by_edge = {
        "|".join(
            sorted(
                ",".join(
                    f"{float(component):.8f}"
                    for component in source.data.vertices[vertex_index].co
                )
                for vertex_index in source.data.edges[edge_index].vertices
            )
        ): owner_pair
        for edge_index, owner_pair in enumerate(group["patch_pair_by_edge"])
    }
    ensure(
        all(
            expected_owner_by_edge[edge_key] == owner_pair
            for edge_key, owner_pair in zip(
                strand.ordered_edge_keys,
                strand.owner_surface_pairs,
            )
        ),
        f"Cyclic owner metadata drifted across canonicalization: {strand}",
    )
    result.add_detail("cyclic Edge/Vertex/owner metadata remained aligned")


# 从 literal Boundary graph 建 BMesh，调用 public binding seam 并返回 binding 与原坐标。
# module/vertices/edges/plan_id: binding module、literal topology 与 plan ID；返回 binding evidence。
def bind_literal_boundary_graph(module, vertices, edges, plan_id, *, update_indices=True):
    bm = bmesh.new()
    try:
        bm_vertices = [bm.verts.new(coordinate) for coordinate in vertices]
        bm.verts.ensure_lookup_table()
        for start_index, end_index in edges:
            bm.edges.new((bm_vertices[start_index], bm_vertices[end_index]))
        if update_indices:
            bm.edges.index_update()
            bm.verts.index_update()
        original_coordinates = tuple(tuple(vertex.co) for vertex in bm.verts)
        binding = module.bind_boundary_graph(plan_id, tuple(bm.edges))
        return binding, original_coordinates, tuple(tuple(vertex.co) for vertex in bm.verts)
    finally:
        bm.free()


# 验证 public BoundaryGraph decomposition 正确处理 open/cyclic/Y/T/X，且每条 Edge 恰好消费一次。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_boundary_graph_binding_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_binding_utils
    fixtures = (
        (
            "open",
            ((0, 0, 0), (1, 0, 0), (2, 0, 0)),
            ((0, 1), (1, 2)),
            (1, 1),
            1,
            2,
            0,
        ),
        (
            "cyclic",
            ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
            ((0, 1), (1, 2), (2, 0)),
            (),
            1,
            0,
            1,
        ),
        (
            "Y",
            ((0, 0, 0), (-1, 0, 0), (1, 0, 0), (0, 1, 0)),
            ((0, 1), (0, 2), (0, 3)),
            (1, 1, 1, 3),
            3,
            6,
            0,
        ),
        (
            "T",
            ((0, 0, 0), (-1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 2, 0)),
            ((0, 1), (0, 2), (0, 3), (3, 4)),
            (1, 1, 1, 3),
            3,
            6,
            0,
        ),
        (
            "X",
            ((0, 0, 0), (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)),
            ((0, 1), (0, 2), (0, 3), (0, 4)),
            (1, 1, 1, 1, 4),
            4,
            8,
            0,
        ),
    )
    records = []
    for label, vertices, edges, expected_degrees, expected_runs, expected_ports, expected_cyclic in fixtures:
        plan_id = f"synthetic:{label}"
        binding, coordinates_before, coordinates_after = bind_literal_boundary_graph(
            module,
            vertices,
            edges,
            plan_id,
        )
        consumed = [
            edge_index
            for strand in binding.rail_strands
            for edge_index in strand.ordered_edge_indices
        ]
        ensure(binding.plan_id == plan_id and binding.status == "PASS", f"{label} binding failed")
        ensure(
            binding.boundary_edge_count == len(edges)
            and binding.consumed_edge_count == len(edges)
            and sorted(consumed) == list(range(len(edges)))
            and len(set(consumed)) == len(edges)
            and not binding.missing_edge_indices
            and not binding.duplicate_edge_indices,
            f"{label} Boundary Edge consumption is incomplete: {binding}",
        )
        ensure(
            tuple(sorted(junction.boundary_degree for junction in binding.junctions))
            == expected_degrees,
            f"{label} junction degrees mismatch: {binding.junctions}",
        )
        ensure(
            len(binding.rail_strands) == expected_runs
            and len(binding.ports) == expected_ports
            and sum(strand.cyclic for strand in binding.rail_strands) == expected_cyclic,
            f"{label} maximal run/port decomposition mismatch: {binding}",
        )
        port_by_id = {port.port_id: port for port in binding.ports}
        junction_by_id = {
            junction.junction_id: junction for junction in binding.junctions
        }
        ensure(
            all(
                port.junction_id in junction_by_id
                and port.port_id in junction_by_id[port.junction_id].port_ids
                and port.rail_strand_id
                in {
                    strand.strand_id
                    for strand in binding.rail_strands
                    if port.junction_id in strand.endpoint_junction_ids
                }
                for port in binding.ports
            )
            and all(
                port_id in port_by_id
                and port_by_id[port_id].junction_id == junction.junction_id
                for junction in binding.junctions
                for port_id in junction.port_ids
            ),
            f"{label} Junction/Port/Rail references are not bidirectional: {binding}",
        )
        ensure(
            coordinates_before == coordinates_after
            and not binding.coordinate_reconstruction
            and not binding.centerline_sorting
            and not binding.moves_boundary,
            f"{label} binding changed Boundary coordinates or semantics",
        )
        records.append(
            {
                "fixture": label,
                "edge_count": binding.boundary_edge_count,
                "rail_count": len(binding.rail_strands),
                "junction_degrees": [
                    junction.boundary_degree for junction in binding.junctions
                ],
                "port_count": len(binding.ports),
            }
        )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_phase_3_boundary_graph_contract.json"
    artifact_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    result.add_detail(f"open/cyclic/Y/T/X binding contract artifact={artifact_path}")


# 验证 plan-local BoundaryWitness 合同可覆盖 JunctionPort multi-Rail seam，且逐 Edge 恰好消费一次。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_boundary_witness_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BoundaryWitnessContract")
    source = make_orthogonal_degree_three_feature_junction(
        "BoundaryWitnessContractSource",
        collection,
    )
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(preview_result == {"FINISHED"}, "BoundaryWitness plan Preview failed")
    plan = test_context.addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        modifier
    )
    module = test_context.addon.utils.feature_chamfer_binding_utils
    junction_port = max(plan.junction_ports, key=lambda port: port.feature_degree)
    owner_rail_ids = tuple(sorted(
        rail.rail_id
        for rail in plan.rail_chains
        if rail.owner_strand_id in junction_port.incident_strand_ids
        and junction_port.port_id in rail.endpoint_port_ids
    ))
    source_patch_id = next(
        patch_id
        for rail in plan.rail_chains
        if rail.rail_id in owner_rail_ids
        for strand in plan.feature_strands
        if strand.strand_id == rail.owner_strand_id
        for owner_pair in strand.owner_surface_pairs
        for patch_id in owner_pair
    )
    witnesses = tuple(
        module.BoundaryWitness(
            witness_id=f"junction-witness:{edge_index}",
            owner_rail_ids=owner_rail_ids,
            junction_port_id=junction_port.port_id,
            source_patch_id=source_patch_id,
        )
        for edge_index in range(3)
    )
    validation = module.validate_boundary_witnesses(
        plan,
        3,
        witnesses,
        tuple((witness.witness_id,) for witness in witnesses),
    )
    ensure(
        validation.status == "PASS"
        and validation.consumed_edge_count == 3
        and len(validation.assignments) == 3
        and not validation.missing_edge_indices
        and not validation.duplicate_edge_indices
        and not validation.conflicting_edge_indices,
        f"BoundaryWitness exactly-once contract failed: {validation}",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_boundary_witness_contract.json"
    artifact_path.write_text(
        json.dumps(
            {
                "plan_id": plan.plan_id,
                "junction_port_id": junction_port.port_id,
                "owner_rail_ids": owner_rail_ids,
                "source_patch_id": source_patch_id,
                "status": validation.status,
                "consumed_edge_count": validation.consumed_edge_count,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"BoundaryWitness consumed 3/3 Junction seam Edges; artifact={artifact_path}"
    )


# 验证缺失、重复、冲突或未知 BoundaryWitness 必须 fail-closed。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_boundary_witness_fail_closed_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BoundaryWitnessFailClosed")
    source = make_orthogonal_degree_three_feature_junction(
        "BoundaryWitnessFailClosedSource",
        collection,
    )
    preview_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(preview_result == {"FINISHED"}, "BoundaryWitness fail-closed Preview failed")
    plan = test_context.addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        modifier
    )
    module = test_context.addon.utils.feature_chamfer_binding_utils
    port = max(plan.junction_ports, key=lambda item: item.feature_degree)
    rail = next(
        rail
        for rail in plan.rail_chains
        if rail.owner_strand_id in port.incident_strand_ids
        and port.port_id in rail.endpoint_port_ids
    )
    source_patch_id = int(rail.side.removeprefix("OWNER_PATCH:"))
    other_rail = next(
        candidate
        for candidate in plan.rail_chains
        if candidate.owner_strand_id in port.incident_strand_ids
        and port.port_id in candidate.endpoint_port_ids
        and candidate.rail_id != rail.rail_id
        and candidate.side == rail.side
    )
    terminal_port = next(
        candidate
        for candidate in plan.junction_ports
        if candidate.feature_degree == 1
        and rail.owner_strand_id not in candidate.incident_strand_ids
    )
    valid = module.BoundaryWitness(
        "valid",
        (rail.rail_id,),
        port.port_id,
        source_patch_id,
    )
    cases = (
        ("missing", (valid,), (("valid",), ())),
        ("duplicate-edge", (valid,), (("valid", "valid"), ("valid",))),
        (
            "conflicting-edge",
            (
                valid,
                module.BoundaryWitness(
                    "other",
                    (rail.rail_id,),
                    port.port_id,
                    source_patch_id,
                ),
            ),
            (("valid", "other"), ("valid",)),
        ),
        ("unknown-witness", (valid,), (("unknown",), ("valid",))),
        (
            "unknown-rail",
            (
                module.BoundaryWitness(
                    "bad-rail",
                    ("rail:unknown",),
                    port.port_id,
                    source_patch_id,
                ),
                valid,
            ),
            (("bad-rail",), ("valid",)),
        ),
        (
            "unknown-port",
            (
                module.BoundaryWitness(
                    "bad-port",
                    (rail.rail_id,),
                    "port:unknown",
                    source_patch_id,
                ),
                valid,
            ),
            (("bad-port",), ("valid",)),
        ),
        (
            "unknown-patch",
            (
                module.BoundaryWitness(
                    "bad-patch",
                    (rail.rail_id,),
                    port.port_id,
                    999999,
                ),
                valid,
            ),
            (("bad-patch",), ("valid",)),
        ),
        (
            "duplicate-registry",
            (
                module.BoundaryWitness(
                    "duplicated-id",
                    (rail.rail_id,),
                    port.port_id,
                    source_patch_id,
                ),
                module.BoundaryWitness(
                    "duplicated-id",
                    (rail.rail_id,),
                    port.port_id,
                    source_patch_id,
                ),
                valid,
            ),
            (("duplicated-id",), ("valid",)),
        ),
        (
            "empty-owner-rails",
            (
                module.BoundaryWitness(
                    "empty-owner-rails",
                    (),
                    port.port_id,
                    source_patch_id,
                ),
                valid,
            ),
            (("empty-owner-rails",), ("valid",)),
        ),
        (
            "rail-patch-mismatch",
            (
                module.BoundaryWitness(
                    "rail-patch-mismatch",
                    (rail.rail_id,),
                    port.port_id,
                    source_patch_id + 1,
                ),
                valid,
            ),
            (("rail-patch-mismatch",), ("valid",)),
        ),
        (
            "rail-port-incidence-mismatch",
            (
                module.BoundaryWitness(
                    "rail-port-incidence-mismatch",
                    (rail.rail_id,),
                    terminal_port.port_id,
                    source_patch_id,
                ),
                valid,
            ),
            (("rail-port-incidence-mismatch",), ("valid",)),
        ),
        (
            "multi-rail-missing-port",
            (
                module.BoundaryWitness(
                    "multi-rail-missing-port",
                    (rail.rail_id, other_rail.rail_id),
                    None,
                    source_patch_id,
                ),
                valid,
            ),
            (("multi-rail-missing-port",), ("valid",)),
        ),
    )
    records = []
    for label, registry, witness_ids_by_edge in cases:
        validation = module.validate_boundary_witnesses(
            plan,
            2,
            registry,
            witness_ids_by_edge,
        )
        ensure(
            validation.status == "boundary_witness_incomplete",
            f"{label} BoundaryWitness did not fail closed: {validation}",
        )
        records.append({
            "case": label,
            "status": validation.status,
            "duplicate_witness_ids": validation.duplicate_witness_ids,
            "incompatible_witness_ids": validation.incompatible_witness_ids,
        })
    result.add_detail(json.dumps(records, sort_keys=True))


# 验证 public decomposition 不依赖 caller 预先更新 BMesh 临时 index。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_boundary_graph_dirty_index_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_binding_utils
    signatures = []
    for repetition in range(3):
        binding, coordinates_before, coordinates_after = bind_literal_boundary_graph(
            module,
            ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)),
            ((0, 1), (2, 3)),
            f"synthetic:dirty-index-coincident:{repetition}",
            update_indices=False,
        )
        signatures.append(
            tuple(
                (
                    strand.ordered_edge_indices,
                    strand.ordered_vertex_indices,
                    strand.endpoint_junction_ids,
                )
                for strand in binding.rail_strands
            )
        )
        ensure(
            binding.status == "PASS"
            and binding.boundary_edge_count == 2
            and binding.consumed_edge_count == 2
            and not binding.missing_edge_indices
            and not binding.duplicate_edge_indices,
            f"Dirty BMesh indices changed coincident topology identity: {binding}",
        )
        ensure(
            coordinates_before == coordinates_after,
            "Dirty-index decomposition changed Boundary coordinates",
        )
    ensure(
        signatures == [
            (((0,), (0, 1), ("boundary-junction:0", "boundary-junction:1")), ((1,), (2, 3), ("boundary-junction:2", "boundary-junction:3")))
        ] * 3,
        f"Coincident dirty-index topology produced unstable IDs: {signatures}",
    )
    result.add_detail("dirty BMesh indices preserved coincident topology identity")


# 验证 public decomposition 对重复 BMEdge refs fail-closed，不把输入 multiplicity 静默折叠为 PASS。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_boundary_graph_duplicate_input_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_binding_utils
    bm = bmesh.new()
    try:
        start = bm.verts.new((0, 0, 0))
        end = bm.verts.new((1, 0, 0))
        edge = bm.edges.new((start, end))
        binding = module.bind_boundary_graph(
            "synthetic:duplicate-input",
            (edge, edge),
        )
        ensure(
            binding.status == "FAIL"
            and binding.boundary_edge_count == 2
            and binding.consumed_edge_count == 1
            and binding.duplicate_edge_indices == (1,),
            f"Duplicate Boundary Edge refs were not rejected: {binding}",
        )
    finally:
        bm.free()
    result.add_detail("duplicate BMEdge refs fail closed at the public seam")


# 构造两条 cyclic rails 的双 tetrahedron Boolean BMesh。
# pipe_ids/patch_ids: 两个待删除 groove Faces 的 owner Pipe IDs 与六个保留 Face Patch IDs；返回 BMesh 与 groove Face refs。
def make_authoritative_boundary_binding_bmesh(pipe_ids, patch_ids):
    bm = bmesh.new()
    mesh = bpy.data.meshes.new("AuthoritativeBoundaryBindingMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
            (3.0, 0.0, 1.0),
        ),
        (),
        (
            (0, 1, 2),
            (1, 0, 3),
            (2, 1, 3),
            (0, 2, 3),
            (4, 5, 6),
            (5, 4, 7),
            (6, 5, 7),
            (4, 6, 7),
        ),
    )
    mesh.update()
    bm.from_mesh(mesh)
    bpy.data.meshes.remove(mesh)
    component_layer = bm.faces.layers.int.new("hst_pipe_component_id")
    patch_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id")
    component_present_layer = bm.faces.layers.int.new("hst_pipe_component_id_present")
    patch_present_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id_present")
    bm.faces.ensure_lookup_table()
    groove_faces = (bm.faces[0], bm.faces[4])
    retained_faces = tuple(bm.faces[1:4]) + tuple(bm.faces[5:8])
    owner_pipe_ids = (
        tuple(pipe_ids)
        if len(pipe_ids) == 2
        else (int(pipe_ids[0]), int(pipe_ids[0]))
    )
    owner_patch_ids = (
        tuple(patch_ids)
        if len(patch_ids) == 6
        else tuple(patch_ids) + tuple(patch_ids)
    )
    for groove_face, pipe_id in zip(groove_faces, owner_pipe_ids):
        groove_face[component_layer] = pipe_id
        groove_face[component_present_layer] = int(pipe_id >= 0)
    for face, patch_id in zip(retained_faces, owner_patch_ids):
        face[component_layer] = -1
        face[patch_layer] = int(patch_id)
        face[patch_present_layer] = int(patch_id >= 0)
    return bm, groove_faces


# 构造含额外无 deleted-Face provenance 的开放 Edge，用于验证 Boundary 全集不能自裁剪。
# 无参数；返回 BMesh 与 groove Face refs。
def make_unowned_extra_boundary_binding_bmesh():
    bm, groove_faces = make_authoritative_boundary_binding_bmesh(
        (7,),
        (10, 10, 10, 11, 11, 11),
    )
    loose_start = bm.verts.new((3.0, 0.0, 0.0))
    loose_end = bm.verts.new((4.0, 0.0, 0.0))
    loose_tip = bm.verts.new((3.0, 1.0, 0.0))
    bm.faces.new((loose_start, loose_end, loose_tip))
    return bm, groove_faces


# 把同一 Patch rail 拆成两个 disconnected runs，验证 binder 不会全局分桶后伪造连续 Rail。
# 无参数；返回 BMesh 与 groove Face refs。
def make_disconnected_rail_boundary_binding_bmesh():
    bm = bmesh.new()
    mesh = bpy.data.meshes.new("DisconnectedRailBoundaryBindingMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
            (3.0, 0.0, 0.0), (4.0, 0.0, 0.0), (3.0, 1.0, 0.0), (3.0, 0.0, 1.0),
        ),
        (),
        (
            (0, 1, 2), (1, 0, 3), (2, 1, 3), (0, 2, 3),
            (4, 5, 6), (5, 4, 7), (6, 5, 7), (4, 6, 7),
        ),
    )
    mesh.update()
    bm.from_mesh(mesh)
    bpy.data.meshes.remove(mesh)
    component_layer = bm.faces.layers.int.new("hst_pipe_component_id")
    patch_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id")
    component_present = bm.faces.layers.int.new("hst_pipe_component_id_present")
    patch_present = bm.faces.layers.int.new("hst_pipe_source_patch_id_present")
    bm.faces.ensure_lookup_table()
    groove_faces = (bm.faces[0], bm.faces[4])
    for groove_face in groove_faces:
        groove_face[component_layer] = 7
        groove_face[component_present] = 1
    for face in tuple(bm.faces[1:4]) + tuple(bm.faces[5:8]):
        face[patch_layer] = 10
        face[patch_present] = 1
    return bm, groove_faces


# 构造单条 open Boundary rail 的 disposable BMesh。
# 无参数；返回 BMesh 与一个 groove Face ref，用于锁定 open endpoint provenance 门禁。
def make_open_rail_boundary_binding_bmesh():
    bm = bmesh.new()
    mesh = bpy.data.meshes.new("OpenRailBoundaryBindingMesh")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (),
        ((0, 1, 2), (1, 0, 2)),
    )
    mesh.update()
    bm.from_mesh(mesh)
    bpy.data.meshes.remove(mesh)
    component_layer = bm.faces.layers.int.new("hst_pipe_component_id")
    patch_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id")
    component_present = bm.faces.layers.int.new("hst_pipe_component_id_present")
    patch_present = bm.faces.layers.int.new("hst_pipe_source_patch_id_present")
    bm.faces.ensure_lookup_table()
    groove_face = bm.faces[0]
    retained_face = bm.faces[1]
    groove_face[component_layer] = 7
    groove_face[component_present] = 1
    retained_face[patch_layer] = 10
    retained_face[patch_present] = 1
    return bm, (groove_face,)


# 构造两条 cyclic Boolean rails，并在待删除 groove Faces 上分别写入 open strand 的 start/end port token。
# pipe_id/patch_ids: cutter owner 与两侧 source Patch；start_token/end_token: plan-local StrandEndpointPort tokens；返回 BMesh 与 groove Face refs。
def make_open_port_anchor_binding_bmesh(
    pipe_id,
    patch_ids,
    start_token,
    end_token,
):
    bm = bmesh.new()
    component_layer = bm.faces.layers.int.new("hst_pipe_component_id")
    component_present = bm.faces.layers.int.new("hst_pipe_component_id_present")
    patch_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id")
    patch_present = bm.faces.layers.int.new("hst_pipe_source_patch_id_present")
    start_port_layer = bm.faces.layers.int.new("hst_pipe_start_port_token")
    end_port_layer = bm.faces.layers.int.new("hst_pipe_end_port_token")
    groove_faces = []
    for rail_index, patch_id in enumerate(patch_ids):
        offset = float(rail_index * 3)
        corners = (
            bm.verts.new((offset + 0.0, 0.0, 0.0)),
            bm.verts.new((offset + 1.0, 0.0, 0.0)),
            bm.verts.new((offset + 1.0, 1.0, 0.0)),
            bm.verts.new((offset + 0.0, 1.0, 0.0)),
        )
        apex = bm.verts.new((offset + 0.5, 0.5, 1.0))
        start_face = bm.faces.new((corners[0], corners[1], corners[2]))
        end_face = bm.faces.new((corners[0], corners[2], corners[3]))
        for face in (start_face, end_face):
            face[component_layer] = pipe_id
            face[component_present] = 1
        start_face[start_port_layer] = start_token
        end_face[end_port_layer] = end_token
        groove_faces.extend((start_face, end_face))
        for index, corner in enumerate(corners):
            next_corner = corners[(index + 1) % len(corners)]
            retained_face = bm.faces.new((corner, next_corner, apex))
            retained_face[patch_layer] = patch_id
            retained_face[patch_present] = 1
    return bm, tuple(groove_faces)


# 构造同一 Boundary Edge 被两个 cutter components 删除面共同拥有的 non-manifold seam。
# 无参数；返回 BMesh 与两个 groove Face refs，用于验证 multi-owner 必须显式 fail-closed。
def make_multi_owner_boundary_binding_bmesh():
    bm = bmesh.new()
    mesh = bpy.data.meshes.new("MultiOwnerBoundaryBindingMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        (),
        ((0, 1, 2), (1, 0, 3), (0, 1, 4)),
    )
    mesh.update()
    bm.from_mesh(mesh)
    bpy.data.meshes.remove(mesh)
    component_layer = bm.faces.layers.int.new("hst_pipe_component_id")
    patch_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id")
    component_present_layer = bm.faces.layers.int.new("hst_pipe_component_id_present")
    patch_present_layer = bm.faces.layers.int.new("hst_pipe_source_patch_id_present")
    bm.faces.ensure_lookup_table()
    retained_face = bm.faces[0]
    groove_faces = (bm.faces[1], bm.faces[2])
    retained_face[component_layer] = -1
    retained_face[patch_layer] = 10
    retained_face[patch_present_layer] = 1
    groove_faces[0][patch_present_layer] = 0
    groove_faces[1][patch_present_layer] = 0
    groove_faces[0][component_layer] = 7
    groove_faces[1][component_layer] = 8
    groove_faces[0][component_present_layer] = 1
    groove_faces[1][component_present_layer] = 1
    return bm, groove_faces


# 构造同一 Edge 的 {known, unknown} cutter owner ledger，unknown 不能被过滤成唯一 owner。
# 无参数；返回 BMesh 与两个 groove Face refs。
def make_known_unknown_owner_boundary_binding_bmesh():
    bm, groove_faces = make_multi_owner_boundary_binding_bmesh()
    component_layer = bm.faces.layers.int.get("hst_pipe_component_id")
    component_present = bm.faces.layers.int.get("hst_pipe_component_id_present")
    groove_faces[0][component_layer] = 7
    groove_faces[0][component_present] = 1
    groove_faces[1][component_present] = 0
    return bm, groove_faces


# 构造 EDGE witness 与 deleted/retained Face provenance 冲突的 Boundary 输入。
# owner_witness_pipe_id/patch_witness_id: 与直接 Face provenance 对照的 witness Pipe/Patch IDs；返回 BMesh、groove Faces 与 layer names。
def make_conflicting_boundary_witness_bmesh(
    owner_witness_pipe_id,
    patch_witness_id,
):
    bm, groove_faces = make_authoritative_boundary_binding_bmesh(
        (7,),
        (10, 10, 10, 11, 11, 11),
    )
    owner_layer_name = f"hst_boundary_owner_witness_{owner_witness_pipe_id}"
    patch_layer_name = f"hst_boundary_patch_witness_{patch_witness_id}"
    owner_layer = bm.edges.layers.int.new(owner_layer_name)
    patch_layer = bm.edges.layers.int.new(patch_layer_name)
    witness_edge = groove_faces[0].edges[0]
    witness_edge[owner_layer] = 1
    witness_edge[patch_layer] = 1
    return bm, groove_faces, owner_layer_name, patch_layer_name


# 验证 authoritative Boolean Boundary binder 只消费 Face provenance，并映射到同一 ChamferPlan。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_authoritative_boundary_binding_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("AuthoritativeBoundaryBinding")
    source = make_edge_network(
        "AuthoritativeBoundaryBindingSource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)),
        ((0, 1), (1, 2), (2, 0)),
    )
    source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [0, 1, 2],
        "vertex_indices": [0, 1, 2],
        "is_cyclic": True,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11), (10, 11), (10, 11)],
        "convexity_by_edge": [1, 1, 1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 2,
        "end_feature_degree": 2,
    }
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    bm, groove_faces = make_authoritative_boundary_binding_bmesh(
        (7,),
        (10, 10, 10, 11, 11, 11),
    )
    try:
        coordinates_before = tuple(tuple(vertex.co) for vertex in bm.verts)
        binding = test_context.addon.utils.feature_chamfer_binding_utils.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(binding.status == "PASS", f"Authoritative binding failed: {binding}")
        ensure(binding.plan_id == plan.plan_id, "Authoritative binding changed plan ID")
        ensure(
            binding.boundary_edge_count == binding.consumed_edge_count == 6
            and not binding.unowned_edge_indices
            and not binding.multi_owner_edge_indices
            and not binding.incompatible_edge_indices,
            f"Authoritative Edge ledger is incomplete: {binding}",
        )
        ensure(
            {record.pipe_id for record in binding.edge_bindings} == {7}
            and {record.owner_strand_id for record in binding.edge_bindings}
            == {plan.feature_strands[0].strand_id}
            and {record.source_patch_id for record in binding.edge_bindings} == {10, 11},
            f"Face provenance did not map to plan ownership: {binding.edge_bindings}",
        )
        ensure(
            {rail.rail_id for rail in binding.rail_bindings}
            == {rail.rail_id for rail in plan.rail_chains},
            f"Authoritative Rail bindings diverged from plan: {binding.rail_bindings}",
        )
        ensure(
            coordinates_before == tuple(tuple(vertex.co) for vertex in bm.verts)
            and not binding.coordinate_reconstruction
            and not binding.centerline_sorting
            and not binding.moves_boundary,
            "Authoritative binding moved or reconstructed Boundary geometry",
        )
    finally:
        bm.free()
    result.add_detail("deleted Face owner + retained Face patch provenance bound 6/6 Boundary Edges")


# 验证 open FeatureStrand 用 attribute-only start/end anchor 绑定 cyclic Boolean rails，不依赖 degree-1 Boundary endpoint。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_open_port_anchor_binding_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("OpenPortAnchorBinding")
    source = make_edge_network(
        "OpenPortAnchorBindingSource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0, 1),),
    )
    source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [0],
        "vertex_indices": [0, 1],
        "is_cyclic": False,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11)],
        "convexity_by_edge": [1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 1,
        "end_feature_degree": 1,
    }
    module = test_context.addon.utils.feature_chamfer_binding_utils
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    strand = plan.feature_strands[0]
    endpoint_tokens = (
        module.StrandEndpointPortToken(101, 7, strand.strand_id, "START", strand.start_port_id),
        module.StrandEndpointPortToken(202, 7, strand.strand_id, "END", strand.end_port_id),
    )
    bm, groove_faces = make_open_port_anchor_binding_bmesh(
        7,
        (10, 11),
        101,
        202,
    )
    try:
        coordinates_before = tuple(tuple(vertex.co) for vertex in bm.verts)
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
            endpoint_port_tokens=endpoint_tokens,
            endpoint_token_layer_names=(
                "hst_pipe_start_port_token",
                "hst_pipe_end_port_token",
            ),
        )
        ensure(binding.status == "PASS", f"Open port anchor binding failed: {binding}")
        ensure(
            binding.boundary_edge_count == binding.consumed_edge_count == 8
            and {rail.rail_id for rail in binding.rail_bindings}
            == {rail.rail_id for rail in plan.rail_chains}
            and all(len(rail.endpoint_port_ids) == 2 for rail in binding.rail_bindings)
            and not binding.missing_port_ids
            and not binding.topology_incompatible_rail_ids,
            f"Open port anchor ledger is incomplete: {binding}",
        )
        ensure(
            coordinates_before == tuple(tuple(vertex.co) for vertex in bm.verts)
            and not binding.coordinate_reconstruction
            and not binding.centerline_sorting
            and not binding.moves_boundary,
            "Open port anchor binding changed Boundary geometry",
        )
    finally:
        bm.free()
    result.add_detail("open strand start/end anchors bound two cyclic Boolean rails without degree-1 inference")


# 验证 open anchor binder 对 unknown、wrong-pipe、wrong-role、duplicate token registry 与 missing anchor 全部 fail-closed。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_open_port_anchor_binding_fail_closed_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("OpenPortAnchorBindingFailClosed")
    source = make_edge_network(
        "OpenPortAnchorBindingFailClosedSource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0, 1),),
    )
    source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [0],
        "vertex_indices": [0, 1],
        "is_cyclic": False,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11)],
        "convexity_by_edge": [1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 1,
        "end_feature_degree": 1,
    }
    module = test_context.addon.utils.feature_chamfer_binding_utils
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    strand = plan.feature_strands[0]
    valid_start = module.StrandEndpointPortToken(101, 7, strand.strand_id, "START", strand.start_port_id)
    valid_end = module.StrandEndpointPortToken(202, 7, strand.strand_id, "END", strand.end_port_id)
    cases = (
        ("unknown-token", 101, 999, (valid_start, valid_end)),
        (
            "wrong-pipe",
            101,
            202,
            (valid_start, module.StrandEndpointPortToken(202, 8, strand.strand_id, "END", strand.end_port_id)),
        ),
        (
            "wrong-strand",
            101,
            202,
            (
                module.StrandEndpointPortToken(101, 7, "strand:unknown", "START", strand.start_port_id),
                valid_end,
            ),
        ),
        (
            "wrong-role",
            101,
            202,
            (valid_start, module.StrandEndpointPortToken(202, 7, strand.strand_id, "START", strand.end_port_id)),
        ),
        (
            "wrong-port-for-role",
            101,
            202,
            (
                module.StrandEndpointPortToken(101, 7, strand.strand_id, "START", strand.end_port_id),
                module.StrandEndpointPortToken(202, 7, strand.strand_id, "END", strand.start_port_id),
            ),
        ),
        (
            "duplicate-token-registry",
            101,
            202,
            (valid_start, module.StrandEndpointPortToken(101, 7, strand.strand_id, "END", strand.end_port_id)),
        ),
        ("missing-end-anchor", 101, 0, (valid_start, valid_end)),
    )
    records = []
    for label, start_token, end_token, endpoint_tokens in cases:
        bm, groove_faces = make_open_port_anchor_binding_bmesh(
            7,
            (10, 11),
            start_token,
            end_token,
        )
        try:
            binding = module.bind_boolean_boundary(
                plan,
                [group],
                bm,
                groove_faces,
                component_layer_name="hst_pipe_component_id",
                source_patch_layer_name="hst_pipe_source_patch_id",
                source_mesh=source.data,
                endpoint_port_tokens=endpoint_tokens,
                endpoint_token_layer_names=(
                    "hst_pipe_start_port_token",
                    "hst_pipe_end_port_token",
                ),
            )
            ensure(
                binding.status == "boundary_binding_incomplete",
                f"{label} port anchor provenance did not fail closed: {binding}",
            )
            records.append({"case": label, "status": binding.status})
        finally:
            bm.free()
    result.add_detail(json.dumps(records, sort_keys=True))


# 验证 authoritative binder 对缺 owner、multi-owner、缺 patch 与 plan 不兼容全部 fail-closed。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_authoritative_boundary_binding_fail_closed_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_binding_utils
    cases = (
        ("missing-owner", -1, (10, 10, 10, 11, 11, 11), "unowned_edge_indices"),
        ("missing-patch", 7, (-1, 10, 10, 11, 11, 11), "missing_patch_edge_indices"),
        ("incompatible-patch", 7, (99, 10, 10, 11, 11, 11), "incompatible_edge_indices"),
        ("unknown-pipe", 99, (10, 10, 10, 11, 11, 11), "incompatible_edge_indices"),
    )
    collection = make_collection("AuthoritativeBoundaryBindingFailClosed")
    source = make_edge_network(
        "AuthoritativeBoundaryBindingFailClosedSource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)),
        ((0, 1), (1, 2), (2, 0)),
    )
    source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [0, 1, 2],
        "vertex_indices": [0, 1, 2],
        "is_cyclic": True,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11), (10, 11), (10, 11)],
        "convexity_by_edge": [1, 1, 1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 2,
        "end_feature_degree": 2,
    }
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    records = []
    for label, pipe_id, patch_ids, evidence_field in cases:
        bm, groove_faces = make_authoritative_boundary_binding_bmesh((pipe_id,), patch_ids)
        try:
            binding = module.bind_boolean_boundary(
                plan,
                [group],
                bm,
                groove_faces,
                component_layer_name="hst_pipe_component_id",
                source_patch_layer_name="hst_pipe_source_patch_id",
                source_mesh=source.data,
            )
            ensure(
                binding.status == "boundary_binding_incomplete"
                and getattr(binding, evidence_field),
                f"{label} did not fail closed with evidence: {binding}",
            )
            records.append({"case": label, "status": binding.status})
        finally:
            bm.free()
    bm, groove_faces = make_multi_owner_boundary_binding_bmesh()
    try:
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.multi_owner_edge_indices,
            f"multi-owner seam did not fail closed with owner evidence: {binding}",
        )
        records.append({"case": "multi-owner", "status": binding.status})
    finally:
        bm.free()
    bm, groove_faces = make_known_unknown_owner_boundary_binding_bmesh()
    try:
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.unowned_edge_indices,
            f"known + unknown owner was collapsed to false unique ownership: {binding}",
        )
        records.append({"case": "known-unknown-owner", "status": binding.status})
    finally:
        bm.free()
    for label, owner_witness_pipe_id, patch_witness_id, rejection_reason in (
        ("owner-witness-conflict", 8, 10, "direct_owner_witness_conflict"),
        ("patch-witness-conflict", 7, 99, "direct_patch_witness_conflict"),
    ):
        (
            bm,
            groove_faces,
            owner_layer_name,
            patch_layer_name,
        ) = make_conflicting_boundary_witness_bmesh(
            owner_witness_pipe_id,
            patch_witness_id,
        )
        try:
            binding = module.bind_boolean_boundary(
                plan,
                [group],
                bm,
                groove_faces,
                component_layer_name="hst_pipe_component_id",
                source_patch_layer_name="hst_pipe_source_patch_id",
                source_mesh=source.data,
                boundary_owner_witness_layer_names=(owner_layer_name,),
                boundary_patch_witness_layer_names=(patch_layer_name,),
            )
            ensure(
                binding.status == "boundary_binding_incomplete"
                and any(
                    diagnostic.rejection_reason == rejection_reason
                    for diagnostic in binding.edge_diagnostics
                ),
                f"{label} did not fail closed with direct provenance evidence: {binding}",
            )
            records.append({"case": label, "status": binding.status})
        finally:
            bm.free()
    bm, groove_faces = make_unowned_extra_boundary_binding_bmesh()
    try:
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.boundary_edge_count == 9
            and binding.unowned_edge_indices,
            f"unledgered Boundary Edges were hidden from the binding universe: {binding}",
        )
        records.append({"case": "unowned-extra-boundary", "status": binding.status})
    finally:
        bm.free()
    bm, groove_faces = make_authoritative_boundary_binding_bmesh((7,), (10, 10, 10, 10, 10, 10))
    try:
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.missing_rail_ids,
            f"missing expected Rail side was accepted: {binding}",
        )
        records.append({"case": "missing-expected-rail", "status": binding.status})
    finally:
        bm.free()
    bm, groove_faces = make_disconnected_rail_boundary_binding_bmesh()
    try:
        binding = module.bind_boolean_boundary(
            plan,
            [group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.topology_incompatible_rail_ids,
            f"disconnected Rail runs were merged into a false Rail: {binding}",
        )
        records.append({"case": "disconnected-rail", "status": binding.status})
    finally:
        bm.free()
    open_source = make_edge_network(
        "AuthoritativeOpenBoundarySource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0, 1),),
    )
    open_source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    open_group = {
        "pipe_id": 7,
        "edge_indices": [0],
        "vertex_indices": [0, 1],
        "is_cyclic": False,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11)],
        "convexity_by_edge": [1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 1,
        "end_feature_degree": 1,
    }
    open_plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        open_source,
        [open_group],
        0.05,
        "GN_PREVIEW_V1",
    )
    bm, groove_faces = make_open_rail_boundary_binding_bmesh()
    try:
        binding = module.bind_boolean_boundary(
            open_plan,
            [open_group],
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=open_source.data,
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.topology_incompatible_rail_ids,
            f"open Rail passed without endpoint → JunctionPort provenance: {binding}",
        )
        records.append({"case": "open-port-provenance-missing", "status": binding.status})
    finally:
        bm.free()
    result.add_detail(json.dumps(records, sort_keys=True))


# 验证 production joined cutter 的双 component 与 source patch Face provenance 会经 Exact Boolean 传播。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_boolean_component_owner_producer_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BooleanComponentOwnerProducer")
    source = make_test_mesh("BooleanComponentOwnerSource", collection)
    input_patch_ids = tuple(101 + index for index in range(len(source.data.polygons)))
    expected_retained_patch_ids = {
        input_patch_ids[index]
        for index in (1, 3, 4, 5)
    }
    pipe_a = make_test_mesh("BooleanComponentOwnerPipeA", collection, location=(-0.7, 0.0, 0.0))
    pipe_b = make_test_mesh("BooleanComponentOwnerPipeB", collection, location=(0.7, 0.0, 0.0))
    for pipe, pipe_id in ((pipe_a, 7), (pipe_b, 8)):
        pipe.scale = (0.35, 0.35, 0.35)
        pipe["hst_pipe_id"] = pipe_id
        pipe.data.transform(pipe.matrix_local)
        pipe.matrix_world = source.matrix_world.copy()
    cutter_collection = bpy.data.collections.new("BooleanComponentOwnerCutters")
    bpy.context.scene.collection.children.link(cutter_collection)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    cutter = utils._build_joined_cutter_mesh(
        [pipe_a, pipe_b],
        source,
        cutter_collection,
        0,
    )
    bpy.context.view_layer.update()
    utils._mark_original_faces(source, input_patch_ids)
    modifier = source.modifiers.new("Authoritative owner probe", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.operand_type = "OBJECT"
    modifier.object = cutter
    with bpy.context.temp_override(
        object=source,
        active_object=source,
        selected_objects=[source],
        selected_editable_objects=[source],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    component = source.data.attributes.get("hst_pipe_component_id")
    component_present = source.data.attributes.get("hst_pipe_component_id_present")
    original = source.data.attributes.get("hst_pipe_original_face")
    patch = source.data.attributes.get("hst_pipe_source_patch_id")
    source_present = source.data.attributes.get("hst_pipe_source_patch_id_present")
    ensure(
        all(attribute is not None and attribute.domain == "FACE" for attribute in (
            component,
            component_present,
            original,
            patch,
            source_present,
        )),
        "Exact Boolean lost authoritative Face provenance attributes",
    )
    groove_indices = [
        polygon.index
        for polygon in source.data.polygons
        if not bool(original.data[polygon.index].value)
    ]
    retained_indices = [
        polygon.index
        for polygon in source.data.polygons
        if bool(original.data[polygon.index].value)
    ]
    retained_patch_ids = {
        patch.data[index].value
        for index in retained_indices
    }
    result.add_detail(
        json.dumps(
            {
                "owners": [component.data[index].value for index in groove_indices],
                "component_present_groove": [bool(component_present.data[index].value) for index in groove_indices],
                "source_present_groove": [bool(source_present.data[index].value) for index in groove_indices],
                "component_present_retained": [bool(component_present.data[index].value) for index in retained_indices],
                "source_present_retained": [bool(source_present.data[index].value) for index in retained_indices],
                "retained_patches": [patch.data[index].value for index in retained_indices],
            },
            sort_keys=True,
        )
    )
    ensure(
        groove_indices
        and {component.data[index].value for index in groove_indices} == {7, 8}
        and all(bool(component_present.data[index].value) for index in groove_indices)
        and all(not bool(source_present.data[index].value) for index in groove_indices)
        and all(not bool(component_present.data[index].value) for index in retained_indices)
        and all(bool(source_present.data[index].value) for index in retained_indices)
        and retained_indices
        and retained_patch_ids == expected_retained_patch_ids,
        "Exact Boolean component/source present provenance is incomplete",
    )
    result.add_detail(
        f"production joined cutter preserved owners=7,8 on {len(groove_indices)} groove Faces"
    )


# 验证 Exact Boolean 后 source/cutter 交线能写入显式 EDGE witness，且不依赖坐标或 nearest Pipe。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_boolean_boundary_witness_producer_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BooleanBoundaryWitness")
    source = make_test_mesh("BooleanBoundaryWitnessSource", collection)
    bpy.ops.mesh.primitive_cube_add(scale=(0.45, 0.45, 1.5))
    cutter = ensure_object_in_collection(bpy.context.active_object, collection)
    cutter.name = "BooleanBoundaryWitnessCutter"
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    cutter[utils.PIPE_ID_TAG] = 7
    cutter.data.transform(cutter.matrix_world)
    cutter.matrix_world.identity()
    utils._ensure_boolean_attribute_schema(cutter.data, False)
    component_attribute = cutter.data.attributes.new(
        utils._component_membership_attribute_name(7),
        type="BOOLEAN",
        domain="FACE",
    )
    for item in component_attribute.data:
        item.value = True
    cutter_collection = bpy.data.collections.new("BooleanBoundaryWitnessCutters")
    bpy.context.scene.collection.children.link(cutter_collection)
    collection.objects.unlink(cutter)
    cutter_collection.objects.link(cutter)
    output = utils._duplicate_source(source, collection)
    source_patch_ids = utils._source_face_patch_ids(source)
    utils._mark_original_faces(output, source_patch_ids)
    utils._initialize_source_membership_schema(
        output.data,
        cutter_collection.objects,
        source_patch_ids,
    )
    utils._initialize_boundary_witness_schema(
        output.data,
        cutter_collection.objects,
        source_patch_ids,
    )
    modifier = utils._add_difference_modifier(output, cutter_collection)
    with bpy.context.temp_override(
        object=output,
        active_object=output,
        selected_objects=[output],
        selected_editable_objects=[output],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    witness_stats = utils._mark_boolean_boundary_witnesses(output)
    owner_witness = output.data.attributes.get(
        utils._boundary_owner_witness_attribute_name(7)
    )
    patch_witnesses = tuple(
        attribute
        for attribute in output.data.attributes
        if attribute.name.startswith(utils.BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX)
    )
    ensure(
        owner_witness is not None
        and owner_witness.domain == "EDGE"
        and any(bool(item.value) for item in owner_witness.data),
        "Exact Boolean produced no explicit Pipe owner EDGE witness",
    )
    ensure(
        patch_witnesses
        and any(
            bool(item.value)
            for attribute in patch_witnesses
            for item in attribute.data
        ),
        "Exact Boolean produced no explicit source Patch EDGE witness",
    )
    ensure(
        witness_stats.get("marked_edge_count", 0) > 0
        and not witness_stats.get("conflicting_edge_indices"),
        f"Boolean Boundary witness ledger is incomplete: {witness_stats}",
    )
    result.add_detail(
        f"Exact Boolean marked {witness_stats['marked_edge_count']} source/cutter Boundary Edges"
    )


# 验证 Blender Exact Mesh Boolean 公开的 Intersecting Edges field 能写入真实 EDGE attribute。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_exact_boolean_intersecting_edges_capability_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    del test_context
    node_group = bpy.data.node_groups.new(
        "FeatureChamferExactBooleanIntersectingEdgesCapability",
        "GeometryNodeTree",
    )
    try:
        boolean_node = node_group.nodes.new("GeometryNodeMeshBoolean")
        boolean_node.operation = "DIFFERENCE"
        boolean_node.solver = "EXACT"
        input_sockets = tuple(
            {
                "name": socket.name,
                "identifier": socket.identifier,
                "type": socket.type,
                "socket_type": socket.bl_idname,
            }
            for socket in boolean_node.inputs
        )
        output_sockets = tuple(
            {
                "name": socket.name,
                "identifier": socket.identifier,
                "type": socket.type,
                "socket_type": socket.bl_idname,
            }
            for socket in boolean_node.outputs
        )
        intersecting_sockets = tuple(
            socket
            for socket in boolean_node.outputs
            if "Intersecting" in socket.name or "Intersecting" in socket.identifier
        )
        artifact_path = ARTIFACT_DIR / "feature_chamfer_exact_boolean_socket_probe.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "inputs": input_sockets,
                    "outputs": output_sockets,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        ensure(
            intersecting_sockets,
            f"Exact Mesh Boolean exposes no Intersecting Edges field: {output_sockets}",
        )
        intersecting_socket_name = intersecting_sockets[0].name
    finally:
        bpy.data.node_groups.remove(node_group)
    result.add_detail(
        f"Exact Boolean intersecting socket={intersecting_socket_name}; artifact={artifact_path}"
    )


# 用临时 Geometry Nodes 跑真实 Exact Difference，并验证 Intersecting Edges 可写成 EDGE witness。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_exact_boolean_intersecting_edges_evaluated_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    del test_context
    collection = make_collection("ExactBooleanIntersectingEdgesEvaluated")
    node_group = bpy.data.node_groups.new(
        "FeatureChamferExactBooleanIntersectingEdgesEvaluated",
        "GeometryNodeTree",
    )
    node_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    group_output = node_group.nodes.new("NodeGroupOutput")
    source_cube = node_group.nodes.new("GeometryNodeMeshCube")
    source_cube.inputs["Size"].default_value = (2.0, 2.0, 2.0)
    cutter_cube = node_group.nodes.new("GeometryNodeMeshCube")
    cutter_cube.inputs["Size"].default_value = (1.5, 1.5, 3.0)
    transform_cutter = node_group.nodes.new("GeometryNodeTransform")
    transform_cutter.inputs["Translation"].default_value = (0.75, 0.0, 0.0)
    boolean_node = node_group.nodes.new("GeometryNodeMeshBoolean")
    boolean_node.operation = "DIFFERENCE"
    boolean_node.solver = "EXACT"
    store_witness = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_witness.data_type = "BOOLEAN"
    store_witness.domain = "EDGE"
    witness_attribute_name = "hst_probe_exact_intersecting_edge"
    store_witness.inputs["Name"].default_value = witness_attribute_name
    node_group.links.new(source_cube.outputs["Mesh"], boolean_node.inputs["Mesh 1"])
    node_group.links.new(cutter_cube.outputs["Mesh"], transform_cutter.inputs["Geometry"])
    node_group.links.new(transform_cutter.outputs["Geometry"], boolean_node.inputs["Mesh 2"])
    node_group.links.new(boolean_node.outputs["Mesh"], store_witness.inputs["Geometry"])
    node_group.links.new(
        boolean_node.outputs["Intersecting Edges"],
        store_witness.inputs["Value"],
    )
    node_group.links.new(store_witness.outputs["Geometry"], group_output.inputs["Geometry"])
    host = make_test_mesh(
        "ExactBooleanIntersectingEdgesHost",
        collection,
        location=(5.0, 0.0, 0.0),
    )
    modifier = host.modifiers.new("Exact Boolean Intersecting Edges Probe", "NODES")
    modifier.node_group = node_group
    evaluated_mesh = None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        evaluated_mesh = bpy.data.meshes.new_from_object(
            host.evaluated_get(depsgraph),
            depsgraph=depsgraph,
        )
        witness_attribute = evaluated_mesh.attributes.get(witness_attribute_name)
        witnessed_edge_indices = (
            [
                edge.index
                for edge in evaluated_mesh.edges
                if witness_attribute is not None
                and bool(witness_attribute.data[edge.index].value)
            ]
        )
        artifact_path = ARTIFACT_DIR / (
            "feature_chamfer_exact_boolean_intersecting_edges_evaluated.json"
        )
        artifact_path.write_text(
            json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "vertex_count": len(evaluated_mesh.vertices),
                    "edge_count": len(evaluated_mesh.edges),
                    "face_count": len(evaluated_mesh.polygons),
                    "witness_attribute_present": witness_attribute is not None,
                    "witness_domain": (
                        witness_attribute.domain if witness_attribute is not None else None
                    ),
                    "witnessed_edge_indices": witnessed_edge_indices,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        ensure(
            witness_attribute is not None
            and witness_attribute.domain == "EDGE"
            and witnessed_edge_indices,
            "Exact Boolean Intersecting Edges did not evaluate into an EDGE witness",
        )
    finally:
        if evaluated_mesh is not None:
            bpy.data.meshes.remove(evaluated_mesh)
        host.modifiers.remove(modifier)
        bpy.data.node_groups.remove(node_group)
    result.add_detail(
        f"Exact Difference wrote {len(witnessed_edge_indices)} EDGE witnesses; artifact={artifact_path}"
    )


# 验证连续 Exact Difference 后，前一阶段 Intersecting Edges witness 仍能在最终 Mesh 中读取。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_exact_boolean_witness_chain_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    del test_context
    collection = make_collection("ExactBooleanWitnessChain")
    node_group = bpy.data.node_groups.new(
        "FeatureChamferExactBooleanWitnessChain",
        "GeometryNodeTree",
    )
    node_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    group_output = node_group.nodes.new("NodeGroupOutput")
    source_cube = node_group.nodes.new("GeometryNodeMeshCube")
    source_cube.inputs["Size"].default_value = (2.0, 2.0, 2.0)

    first_cutter = node_group.nodes.new("GeometryNodeMeshCube")
    first_cutter.inputs["Size"].default_value = (1.2, 1.2, 3.0)
    first_transform = node_group.nodes.new("GeometryNodeTransform")
    first_transform.inputs["Translation"].default_value = (0.75, 0.0, 0.0)
    first_boolean = node_group.nodes.new("GeometryNodeMeshBoolean")
    first_boolean.operation = "DIFFERENCE"
    first_boolean.solver = "EXACT"
    first_store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    first_store.data_type = "BOOLEAN"
    first_store.domain = "EDGE"
    first_witness_name = "hst_probe_exact_intersecting_edge_stage_1"
    first_store.inputs["Name"].default_value = first_witness_name

    second_cutter = node_group.nodes.new("GeometryNodeMeshCube")
    second_cutter.inputs["Size"].default_value = (1.2, 3.0, 1.2)
    second_transform = node_group.nodes.new("GeometryNodeTransform")
    second_transform.inputs["Translation"].default_value = (0.0, 0.75, 0.0)
    second_boolean = node_group.nodes.new("GeometryNodeMeshBoolean")
    second_boolean.operation = "DIFFERENCE"
    second_boolean.solver = "EXACT"
    second_store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    second_store.data_type = "BOOLEAN"
    second_store.domain = "EDGE"
    second_witness_name = "hst_probe_exact_intersecting_edge_stage_2"
    second_store.inputs["Name"].default_value = second_witness_name

    node_group.links.new(source_cube.outputs["Mesh"], first_boolean.inputs["Mesh 1"])
    node_group.links.new(first_cutter.outputs["Mesh"], first_transform.inputs["Geometry"])
    node_group.links.new(first_transform.outputs["Geometry"], first_boolean.inputs["Mesh 2"])
    node_group.links.new(first_boolean.outputs["Mesh"], first_store.inputs["Geometry"])
    node_group.links.new(first_boolean.outputs["Intersecting Edges"], first_store.inputs["Value"])
    node_group.links.new(first_store.outputs["Geometry"], second_boolean.inputs["Mesh 1"])
    node_group.links.new(second_cutter.outputs["Mesh"], second_transform.inputs["Geometry"])
    node_group.links.new(second_transform.outputs["Geometry"], second_boolean.inputs["Mesh 2"])
    node_group.links.new(second_boolean.outputs["Mesh"], second_store.inputs["Geometry"])
    node_group.links.new(second_boolean.outputs["Intersecting Edges"], second_store.inputs["Value"])
    node_group.links.new(second_store.outputs["Geometry"], group_output.inputs["Geometry"])

    host = make_test_mesh("ExactBooleanWitnessChainHost", collection)
    modifier = host.modifiers.new("Exact Boolean Witness Chain Probe", "NODES")
    modifier.node_group = node_group
    evaluated_mesh = None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        evaluated_mesh = bpy.data.meshes.new_from_object(
            host.evaluated_get(depsgraph),
            depsgraph=depsgraph,
        )
        witness_indices_by_stage = {}
        for stage_name, attribute_name in (
            ("stage_1", first_witness_name),
            ("stage_2", second_witness_name),
        ):
            attribute = evaluated_mesh.attributes.get(attribute_name)
            witness_indices_by_stage[stage_name] = [
                edge.index
                for edge in evaluated_mesh.edges
                if attribute is not None and bool(attribute.data[edge.index].value)
            ]
        shared_edge_indices = sorted(
            set(witness_indices_by_stage["stage_1"])
            & set(witness_indices_by_stage["stage_2"])
        )
        artifact_path = ARTIFACT_DIR / "feature_chamfer_exact_boolean_witness_chain.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "vertex_count": len(evaluated_mesh.vertices),
                    "edge_count": len(evaluated_mesh.edges),
                    "face_count": len(evaluated_mesh.polygons),
                    "witness_indices_by_stage": witness_indices_by_stage,
                    "shared_edge_indices": shared_edge_indices,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        ensure(
            witness_indices_by_stage["stage_1"]
            and witness_indices_by_stage["stage_2"],
            "Sequential Exact Boolean did not preserve both stage witness sets",
        )
        ensure(
            not shared_edge_indices,
            f"One final Edge was ambiguously claimed by both Boolean stages: {shared_edge_indices}",
        )
    finally:
        if evaluated_mesh is not None:
            bpy.data.meshes.remove(evaluated_mesh)
        host.modifiers.remove(modifier)
        bpy.data.node_groups.remove(node_group)
    result.add_detail(
        f"Sequential Exact Boolean preserved {len(witness_indices_by_stage['stage_1'])}/"
        f"{len(witness_indices_by_stage['stage_2'])} unique witnesses; artifact={artifact_path}"
    )


# 验证 production Even-Thickness Pipe 与 joined cutter 会保留 plan-local open strand endpoint tokens。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_open_endpoint_token_producer_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("OpenEndpointTokenProducer")
    source = make_edge_network(
        "OpenEndpointTokenProducerSource",
        collection,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0, 1),),
    )
    source.data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE").data[0].value = True
    group = {
        "pipe_id": 7,
        "edge_indices": [0],
        "vertex_indices": [0, 1],
        "points": [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0))],
        "is_cyclic": False,
        "patch_pair": (10, 11),
        "patch_pair_by_edge": [(10, 11)],
        "convexity_by_edge": [1],
        "selected_pair_vertex_ids": [],
        "start_feature_degree": 1,
        "end_feature_degree": 1,
        "start_extension": 0.0,
        "end_extension": 0.0,
    }
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        [group],
        0.05,
        "GN_PREVIEW_V1",
    )
    tokens_by_pipe_id, registry = utils._build_strand_endpoint_port_tokens(
        plan,
        [group],
        source.data,
    )
    pipe = utils._build_pipe_mesh(
        source,
        group,
        0.05,
        4,
        collection,
        tokens_by_pipe_id[7],
    )
    cutter_collection = bpy.data.collections.new("OpenEndpointTokenCutters")
    bpy.context.scene.collection.children.link(cutter_collection)
    cutter = utils._build_joined_cutter_mesh(
        [pipe],
        source,
        cutter_collection,
        0,
    )
    start_attribute = cutter.data.attributes.get("hst_pipe_start_port_token")
    end_attribute = cutter.data.attributes.get("hst_pipe_end_port_token")
    ensure(
        len(registry) == 2
        and {record.endpoint_role for record in registry} == {"START", "END"}
        and all(
            attribute is not None and attribute.domain == "FACE"
            for attribute in (start_attribute, end_attribute)
        ),
        "Production Curve Pipe lost endpoint Face attributes",
    )
    start_values = [item.value for item in start_attribute.data]
    end_values = [item.value for item in end_attribute.data]
    ensure(
        {value for value in start_values if value} == {tokens_by_pipe_id[7]["start"]}
        and {value for value in end_values if value} == {tokens_by_pipe_id[7]["end"]}
        and any(start_values)
        and any(end_values),
        "Production Curve Pipe lost plan-local endpoint Face tokens",
    )
    result.add_detail(
        f"open endpoint producer preserved tokens={tokens_by_pipe_id[7]} on joined cutter Faces"
    )


# 验证 production plan→Pipe producer 能建立显式 owner Rail/JunctionPort/Patch witness registry。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_pipe_boundary_witness_registry_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("PipeBoundaryWitnessRegistry")
    source = make_orthogonal_degree_three_feature_junction(
        "PipeBoundaryWitnessRegistrySource",
        collection,
    )
    radius = 0.05
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils._base_stats(source, radius, 8, 35.0, 3.0, 1.5, "FEATURE_GRAPH")
    groups = utils._build_preview_feature_graph(source, radius, stats)
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        groups,
        radius,
        "GN_PREVIEW_V1",
    )
    witnesses_by_pipe_id = utils._build_pipe_boundary_witnesses(
        plan,
        groups,
        source.data,
    )
    witness_ids = [
        witness.witness_id
        for witnesses in witnesses_by_pipe_id.values()
        for witness in witnesses
    ]
    ensure(
        set(witnesses_by_pipe_id) == {int(group["pipe_id"]) for group in groups}
        and len(witness_ids) == len(set(witness_ids))
        and all(
            witness.owner_rail_ids
            and witness.junction_port_id
            and witness.source_patch_id >= 0
            for witnesses in witnesses_by_pipe_id.values()
            for witness in witnesses
        ),
        f"Pipe BoundaryWitness registry is incomplete: {witnesses_by_pipe_id}",
    )
    known_rails = {rail.rail_id for rail in plan.rail_chains}
    known_ports = {port.port_id for port in plan.junction_ports}
    ensure(
        all(
            set(witness.owner_rail_ids) <= known_rails
            and witness.junction_port_id in known_ports
            for witnesses in witnesses_by_pipe_id.values()
            for witness in witnesses
        ),
        f"Pipe BoundaryWitness registry diverged from ChamferPlan: {witnesses_by_pipe_id}",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_pipe_boundary_witness_registry.json"
    artifact_path.write_text(
        json.dumps(
            {
                "plan_id": plan.plan_id,
                "witnesses_by_pipe_id": {
                    str(pipe_id): [
                        {
                            "witness_id": witness.witness_id,
                            "owner_rail_ids": witness.owner_rail_ids,
                            "junction_port_id": witness.junction_port_id,
                            "source_patch_id": witness.source_patch_id,
                        }
                        for witness in witnesses
                    ]
                    for pipe_id, witnesses in witnesses_by_pipe_id.items()
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"Pipe producer registered {len(witness_ids)} BoundaryWitness records; artifact={artifact_path}"
    )


# 验证 production Cutter Set 的 sequential Exact Intersecting Edges 能覆盖开放 Boundary，且与正式 Collection Difference 几何等价。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_production_sequential_boolean_witness_probe(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("ProductionSequentialBooleanWitness")
    source = make_orthogonal_degree_three_feature_junction(
        "ProductionSequentialBooleanWitnessSource",
        collection,
    )
    source_fingerprint_before = _mesh_fingerprint(source)
    radius = 0.08
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=radius,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="CUTTER_UNION",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
        preserve_source_visibility=True,
    )
    ensure(
        stats["status"] == "finished"
        and stats["joined_cutter_batch_count"] >= 2,
        f"Production Cutter Set was not built: {stats}",
    )
    cutter_collection = bpy.data.collections[stats["cutter_collection_name"]]
    cutters = tuple(sorted(cutter_collection.objects, key=lambda item: item.name))
    production_pipe_objects = tuple(sorted(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and utils.PIPE_ID_TAG in obj
            and obj.get(utils.OUTPUT_TAG) == source.name
        ),
        key=lambda item: int(item[utils.PIPE_ID_TAG]),
    ))
    ensure(
        len(production_pipe_objects) == stats["pipe_group_count"],
        "Production Pipe objects are unavailable for per-Pipe stage probe",
    )
    source_patch_ids = utils._source_face_patch_ids(source)

    collection_output = utils._duplicate_source(source, collection)
    utils._mark_original_faces(collection_output, source_patch_ids)
    utils._initialize_source_membership_schema(
        collection_output.data,
        cutters,
        source_patch_ids,
    )
    utils._apply_difference(collection_output, cutter_collection, source_patch_ids)

    sequential_source = utils._duplicate_source(source, collection)
    utils._mark_original_faces(sequential_source, source_patch_ids)
    utils._initialize_source_membership_schema(
        sequential_source.data,
        cutters,
        source_patch_ids,
    )
    sequential_mesh, stage_records = (
        utils._probe_sequential_exact_boundary_witnesses(
            sequential_source,
            production_pipe_objects,
            pipe_ids_by_cutter={
                pipe: (int(pipe[utils.PIPE_ID_TAG]),)
                for pipe in production_pipe_objects
            },
        )
    )
    ensure(sequential_mesh is not None and stage_records, "Sequential probe returned no Mesh")
    try:
        closed_equivalent = (
            canonical_mesh_geometry_signature(collection_output.data)
            == canonical_mesh_geometry_signature(sequential_mesh)
        )
        closed_equivalent_1e7 = (
            canonical_mesh_geometry_signature(collection_output.data, 7)
            == canonical_mesh_geometry_signature(sequential_mesh, 7)
        )
        closed_faces_equivalent = (
            canonical_mesh_face_signature(collection_output.data)
            == canonical_mesh_face_signature(sequential_mesh)
        )
        stage_witness_counts = {}
        shared_witness_edges = []
        witness_names_by_edge = {}
        for record in stage_records:
            attribute_name = record["witness_attribute_name"]
            attribute = sequential_mesh.attributes.get(attribute_name)
            ensure(
                attribute is not None
                and attribute.domain == "EDGE"
                and len(attribute.data) == len(sequential_mesh.edges),
                f"Sequential stage lost EDGE witness: {record}",
            )
            witnessed_edges = [
                edge.index
                for edge in sequential_mesh.edges
                if bool(attribute.data[edge.index].value)
            ]
            stage_witness_counts[str(record["stage_index"])] = len(witnessed_edges)
            for edge_index in witnessed_edges:
                witness_names_by_edge.setdefault(edge_index, []).append(attribute_name)
        shared_witness_edges = sorted(
            edge_index
            for edge_index, attribute_names in witness_names_by_edge.items()
            if len(attribute_names) != 1
        )

        collection_bm = open_boolean_mesh_with_witness_layers(
            collection_output.data,
            utils.ORIGINAL_FACE_ATTRIBUTE,
        )
        sequential_bm = open_boolean_mesh_with_witness_layers(
            sequential_mesh,
            utils.ORIGINAL_FACE_ATTRIBUTE,
        )
        try:
            collection_open_mesh = bpy.data.meshes.new(
                "ProductionSequentialBooleanCollectionOpen"
            )
            sequential_open_mesh = bpy.data.meshes.new(
                "ProductionSequentialBooleanSequentialOpen"
            )
            collection_bm.to_mesh(collection_open_mesh)
            sequential_bm.to_mesh(sequential_open_mesh)
            open_equivalent = (
                canonical_mesh_geometry_signature(collection_open_mesh)
                == canonical_mesh_geometry_signature(sequential_open_mesh)
            )
            open_equivalent_1e7 = (
                canonical_mesh_geometry_signature(collection_open_mesh, 7)
                == canonical_mesh_geometry_signature(sequential_open_mesh, 7)
            )
            open_faces_equivalent = (
                canonical_mesh_face_signature(collection_open_mesh)
                == canonical_mesh_face_signature(sequential_open_mesh)
            )
            boundary_records = []
            missing_boundary_edge_indices = []
            conflicting_boundary_edge_indices = []
            for edge in sequential_bm.edges:
                if len(edge.link_faces) != 1:
                    continue
                witness_names = tuple(sorted(
                    record["witness_attribute_name"]
                    for record in stage_records
                    for layer in (
                        sequential_bm.edges.layers.int.get(
                            record["witness_attribute_name"]
                        )
                        or sequential_bm.edges.layers.bool.get(
                            record["witness_attribute_name"]
                        ),
                    )
                    if layer is not None and bool(edge[layer])
                ))
                boundary_records.append({
                    "edge_index": edge.index,
                    "vertex_coordinates": tuple(sorted(
                        tuple(round(float(value), 8) for value in vertex.co)
                        for vertex in edge.verts
                    )),
                    "witness_attribute_names": witness_names,
                })
                if not witness_names:
                    missing_boundary_edge_indices.append(edge.index)
                elif len(witness_names) != 1:
                    conflicting_boundary_edge_indices.append(edge.index)
        finally:
            collection_bm.free()
            sequential_bm.free()

        artifact_path = ARTIFACT_DIR / (
            "feature_chamfer_production_sequential_boolean_witness_probe.json"
        )
        artifact = {
            "source_fingerprint_unchanged": (
                _mesh_fingerprint(source) == source_fingerprint_before
            ),
            "closed_equivalent": closed_equivalent,
            "closed_equivalent_1e7": closed_equivalent_1e7,
            "closed_faces_equivalent": closed_faces_equivalent,
            "open_equivalent": open_equivalent,
            "open_equivalent_1e7": open_equivalent_1e7,
            "open_faces_equivalent": open_faces_equivalent,
            "collection_closed_counts": {
                "vertices": len(collection_output.data.vertices),
                "edges": len(collection_output.data.edges),
                "faces": len(collection_output.data.polygons),
            },
            "sequential_closed_counts": {
                "vertices": len(sequential_mesh.vertices),
                "edges": len(sequential_mesh.edges),
                "faces": len(sequential_mesh.polygons),
            },
            "collection_open_counts": {
                "vertices": len(collection_open_mesh.vertices),
                "edges": len(collection_open_mesh.edges),
                "faces": len(collection_open_mesh.polygons),
            },
            "sequential_open_counts": {
                "vertices": len(sequential_open_mesh.vertices),
                "edges": len(sequential_open_mesh.edges),
                "faces": len(sequential_open_mesh.polygons),
            },
            "stage_records": stage_records,
            "stage_witness_counts": stage_witness_counts,
            "shared_closed_witness_edge_indices": shared_witness_edges,
            "boundary_edge_count": len(boundary_records),
            "missing_boundary_edge_indices": missing_boundary_edge_indices,
            "conflicting_boundary_edge_indices": conflicting_boundary_edge_indices,
            "boundary_records": boundary_records,
        }
        artifact_path.write_text(
            json.dumps(artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        ensure(
            artifact["source_fingerprint_unchanged"]
            and not shared_witness_edges
            and not missing_boundary_edge_indices
            and not conflicting_boundary_edge_indices,
            f"Production sequential witness coverage is incomplete: {artifact_path}",
        )
    finally:
        bpy.data.meshes.remove(sequential_mesh)
        if "collection_open_mesh" in locals():
            bpy.data.meshes.remove(collection_open_mesh)
        if "sequential_open_mesh" in locals():
            bpy.data.meshes.remove(sequential_open_mesh)
    result.add_detail(
        f"PROTOTYPE/STOP: sequential Exact covered {len(boundary_records)}/"
        f"{len(boundary_records)} Boundary Edges but geometry_equivalent="
        f"{closed_equivalent and open_equivalent}; artifact={artifact_path}"
    )


# 验证正式 Collection Exact 是否会把 Cutter 输入 EDGE 的 per-Pipe one-hot witness 传播到最终开放 Boundary。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_collection_boolean_input_edge_witness_probe(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("CollectionBooleanInputEdgeWitness")
    source = make_orthogonal_degree_three_feature_junction(
        "CollectionBooleanInputEdgeWitnessSource",
        collection,
    )
    source_fingerprint_before = _mesh_fingerprint(source)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    radius = 0.08
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=radius,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="CUTTER_UNION",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
        preserve_source_visibility=True,
    )
    cutter_collection = bpy.data.collections[stats["cutter_collection_name"]]
    cutters = tuple(cutter_collection.objects)
    source_patch_ids = utils._source_face_patch_ids(source)
    output = utils._duplicate_source(source, collection)
    utils._mark_original_faces(output, source_patch_ids)
    utils._initialize_source_membership_schema(
        output.data,
        cutters,
        source_patch_ids,
    )
    utils._seed_cutter_edge_owner_witnesses(cutters)
    marker_index = utils._apply_difference(
        output,
        cutter_collection,
        source_patch_ids,
    )
    cutter_face_indices = utils._groove_face_indices(output, stats)
    bm, _ = utils._open_boundary(
        output,
        cutter_face_indices,
        stats,
        [],
        radius,
        allow_non_simple=True,
    )
    try:
        owner_layer_names = tuple(sorted(
            attribute.name
            for attribute in output.data.attributes
            if attribute.domain == "EDGE"
            and attribute.name.startswith(
                utils.BOUNDARY_OWNER_WITNESS_ATTRIBUTE_PREFIX
            )
        ))
        records = []
        missing = []
        conflicting = []
        for edge in bm.edges:
            if len(edge.link_faces) != 1:
                continue
            witnesses = tuple(sorted(
                layer_name
                for layer_name in owner_layer_names
                for layer in (
                    bm.edges.layers.int.get(layer_name)
                    or bm.edges.layers.bool.get(layer_name),
                )
                if layer is not None and bool(edge[layer])
            ))
            records.append({
                "edge_index": edge.index,
                "witnesses": witnesses,
                "vertex_coordinates": tuple(sorted(
                    tuple(round(float(value), 8) for value in vertex.co)
                    for vertex in edge.verts
                )),
            })
            if not witnesses:
                missing.append(edge.index)
            elif len(witnesses) != 1:
                conflicting.append(edge.index)
        artifact_path = ARTIFACT_DIR / (
            "feature_chamfer_collection_boolean_input_edge_witness_probe.json"
        )
        artifact = {
            "source_fingerprint_unchanged": (
                _mesh_fingerprint(source) == source_fingerprint_before
            ),
            "boundary_edge_count": len(records),
            "missing_boundary_edge_indices": missing,
            "conflicting_boundary_edge_indices": conflicting,
            "records": records,
        }
        artifact_path.write_text(
            json.dumps(artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        ensure(
            marker_index >= 0
            and artifact["source_fingerprint_unchanged"],
            "Collection input EDGE witness probe changed source",
        )
    finally:
        bm.free()
    result.add_detail(
        f"PROTOTYPE/STOP: Collection input EDGE witnesses covered "
        f"{len(records) - len(missing)}/{len(records)} Boundary Edges; "
        f"conflicts={len(conflicting)}; artifact={artifact_path}"
    )


# 使用 native multi-input Exact 探针验证当前 source 的 authoritative Boundary witness。
# test_context/result/source/radius/artifact_name: 测试上下文、结果记录器、输入 Mesh、半径与 JSON 文件名；返回 artifact。
def test_feature_chamfer_multi_input_boolean_witness_probe(
    test_context: TestContext,
    result: TestCaseResult,
    source=None,
    radius=0.08,
    artifact_name="feature_chamfer_multi_input_boolean_witness_probe.json",
):
    collection = source.users_collection[0] if source is not None else make_collection(
        "MultiInputBooleanWitness"
    )
    source = source or make_orthogonal_degree_three_feature_junction(
        "MultiInputBooleanWitnessSource", collection
    )
    source_fingerprint_before = _mesh_fingerprint(source)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=radius,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="CUTTER_UNION",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
        preserve_source_visibility=True,
    )
    cutter_collection = bpy.data.collections[stats["cutter_collection_name"]]
    cutters = tuple(sorted(cutter_collection.objects, key=lambda item: item.name))
    production_pipe_objects = tuple(sorted(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and utils.PIPE_ID_TAG in obj
            and obj.get(utils.OUTPUT_TAG) == source.name
        ),
        key=lambda item: int(item[utils.PIPE_ID_TAG]),
    ))
    source_patch_ids = utils._source_face_patch_ids(source)
    sharp_source_edge_indices = utils._sharp_edge_indices(source)
    plan_stats = utils._base_stats(
        source,
        radius,
        8,
        35.0,
        3.0,
        1.5,
        "FEATURE_GRAPH",
    )
    groups = utils._build_preview_feature_graph(source, radius, plan_stats)
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        groups,
        radius,
        "GN_PREVIEW_V1",
        source_patch_ids=source_patch_ids,
    )
    witnesses_by_pipe_id = utils._build_pipe_boundary_witnesses(
        plan,
        groups,
        source.data,
    )
    strands_by_pipe_id = utils._plan_strands_by_pipe_id(
        plan,
        groups,
        source.data,
    )
    _, endpoint_registry = utils._build_strand_endpoint_port_tokens(
        plan,
        groups,
        source.data,
    )
    port_id_by_token = {
        record.token: record.port_id for record in endpoint_registry
    }
    pipe_id_by_token = {
        record.token: record.pipe_id for record in endpoint_registry
    }
    collection_output = utils._duplicate_source(source, collection)
    utils._mark_original_faces(collection_output, source_patch_ids)
    utils._initialize_source_membership_schema(
        collection_output.data,
        cutters,
        source_patch_ids,
    )
    utils._apply_difference(collection_output, cutter_collection, source_patch_ids)
    multi_source = utils._duplicate_source(source, collection)
    utils._mark_original_faces(multi_source, source_patch_ids)
    utils._initialize_source_membership_schema(
        multi_source.data,
        cutters,
        source_patch_ids,
    )
    mark_source_topology_identity(multi_source.data)
    source_identity_mesh = multi_source.data.copy()
    (
        multi_mesh,
        witness_name,
        owner_attribute_names,
        token_attribute_names,
        patch_attribute_names,
    ) = (
        utils._probe_multi_input_exact_boundary_witnesses(
        multi_source,
        production_pipe_objects,
        per_cutter_witness_ids={
            pipe: int(pipe[utils.PIPE_ID_TAG])
            for pipe in production_pipe_objects
        },
    ))
    ensure(multi_mesh is not None and witness_name, "Multi-input probe returned no Mesh")
    try:
        closed_equivalent = (
            canonical_mesh_geometry_signature(collection_output.data)
            == canonical_mesh_geometry_signature(multi_mesh)
        )
        collection_bm = open_boolean_mesh_with_witness_layers(
            collection_output.data,
            utils.ORIGINAL_FACE_ATTRIBUTE,
        )
        boundary_origin_records = {}
        multi_bm = open_boolean_mesh_with_witness_layers(
            multi_mesh,
            utils.ORIGINAL_FACE_ATTRIBUTE,
            boundary_origin_records,
        )
        try:
            collection_cleanup = utils._clean_open_boundary_degenerates(
                collection_bm,
                radius,
            )
            multi_cleanup = utils._clean_open_boundary_degenerates(
                multi_bm,
                radius,
            )
            collection_bm.verts.index_update()
            collection_bm.edges.index_update()
            multi_bm.verts.index_update()
            multi_bm.edges.index_update()
            boundary_origin_records = {
                str(edge.index): {
                    **record,
                    "post_cleanup_edge_index": edge.index,
                    "post_cleanup_vertex_coordinates": [
                        list(coordinate)
                        for coordinate in sorted(
                            tuple(round(float(value), 8) for value in vertex.co)
                            for vertex in edge.verts
                        )
                    ],
                }
                for edge in multi_bm.edges
                for record in (boundary_origin_records.get(edge),)
                if len(edge.link_faces) == 1 and record is not None
            }
            collection_open_mesh = bpy.data.meshes.new("MultiInputCollectionOpen")
            multi_open_mesh = bpy.data.meshes.new("MultiInputNativeOpen")
            collection_bm.to_mesh(collection_open_mesh)
            multi_bm.to_mesh(multi_open_mesh)
            open_equivalent = (
                canonical_mesh_geometry_signature(collection_open_mesh)
                == canonical_mesh_geometry_signature(multi_open_mesh)
            )
            witness_layer = (
                multi_bm.edges.layers.int.get(witness_name)
                or multi_bm.edges.layers.bool.get(witness_name)
            )
            ensure(witness_layer is not None, "Multi-input EDGE witness was lost")
            boundary_edge_indices = [
                edge.index for edge in multi_bm.edges if len(edge.link_faces) == 1
            ]
            witnessed_boundary_edge_indices = [
                edge.index
                for edge in multi_bm.edges
                if len(edge.link_faces) == 1 and bool(edge[witness_layer])
            ]
            boundary_owner_candidates = {}
            boundary_endpoint_tokens = {}
            boundary_compound_endpoint_records = {}
            boundary_patch_candidates = {}
            for edge in multi_bm.edges:
                if len(edge.link_faces) != 1:
                    continue
                owner_ids = sorted({
                    int(attribute_name.rsplit("_", 1)[1])
                    for attribute_name in owner_attribute_names
                    for layer in (
                        multi_bm.edges.layers.int.get(attribute_name)
                        or multi_bm.edges.layers.bool.get(attribute_name),
                    )
                    if layer is not None and bool(edge[layer])
                })
                boundary_owner_candidates[str(edge.index)] = owner_ids
                compound_endpoint_records = sorted({
                    tuple(
                        int(value)
                        for value in attribute_name.removeprefix(
                            utils.PROBE_EDGE_COMPOUND_ENDPOINT_ATTRIBUTE_PREFIX
                        ).split("_")
                    )
                    for attribute_name in token_attribute_names
                    for layer in (
                        multi_bm.edges.layers.int.get(attribute_name)
                        or multi_bm.edges.layers.bool.get(attribute_name),
                    )
                    if layer is not None and bool(edge[layer])
                })
                boundary_compound_endpoint_records[str(edge.index)] = [
                    {"pipe_id": pipe_id, "token": token}
                    for pipe_id, token in compound_endpoint_records
                ]
                boundary_endpoint_tokens[str(edge.index)] = sorted({
                    token
                    for pipe_id, token in compound_endpoint_records
                    if pipe_id in owner_ids
                })
                boundary_patch_candidates[str(edge.index)] = sorted({
                    int(attribute_name.removeprefix(
                        utils.BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX
                    ))
                    for attribute_name in patch_attribute_names
                    for layer in (
                        multi_bm.edges.layers.int.get(attribute_name)
                        or multi_bm.edges.layers.bool.get(attribute_name),
                    )
                    if layer is not None and bool(edge[layer])
                })
            boundary_witness_registry = []
            witness_ids_by_boundary = []
            unresolved_boundary_edge_indices = []
            source_fragment_boundary_edge_indices = []
            for boundary_edge_index in boundary_edge_indices:
                edge_key = str(boundary_edge_index)
                owner_ids = boundary_owner_candidates[edge_key]
                patch_ids = boundary_patch_candidates[edge_key]
                matching_port_ids = {
                    port_id_by_token[token]
                    for token in boundary_endpoint_tokens[edge_key]
                    if token in port_id_by_token
                }
                regular_owner_rail_ids = tuple(sorted(
                    rail.rail_id
                    for pipe_id in owner_ids
                    for strand in (strands_by_pipe_id.get(pipe_id),)
                    if strand is not None
                    for rail in plan.rail_chains
                    if rail.owner_strand_id == strand.strand_id
                    and len(patch_ids) == 1
                    and rail.side == f"OWNER_PATCH:{patch_ids[0]}"
                ))
                matching_witnesses = {
                    witness
                    for pipe_id in owner_ids
                    for witness in witnesses_by_pipe_id.get(pipe_id, ())
                    if len(patch_ids) == 1
                    and witness.source_patch_id == patch_ids[0]
                    and witness.junction_port_id in matching_port_ids
                }
                port_local_owner_rail_sets = {
                    witness.owner_rail_ids
                    for witness in matching_witnesses
                    if witness.owner_rail_ids
                }
                origin_record = boundary_origin_records.get(edge_key, {})
                origin_attribute_values = origin_record.get(
                    "closed_edge_attribute_values",
                    {},
                )
                source_fragment = (
                    not owner_ids
                    and not patch_ids
                    and not matching_port_ids
                    and int(origin_attribute_values.get(
                        "hst_probe_source_edge_present",
                        0,
                    )) == 1
                    and bool(origin_record.get("closed_linked_faces"))
                    and all(
                        face_record["is_original"]
                        for face_record in origin_record["closed_linked_faces"]
                    )
                )
                if source_fragment:
                    source_fragment_boundary_edge_indices.append(
                        boundary_edge_index
                    )
                    continue
                if (
                    len(owner_ids) != 1
                    or len(patch_ids) != 1
                    or (
                        not regular_owner_rail_ids
                        and len(port_local_owner_rail_sets) != 1
                    )
                ):
                    unresolved_boundary_edge_indices.append(boundary_edge_index)
                    witness_ids_by_boundary.append(())
                    continue
                if regular_owner_rail_ids:
                    owner_rail_ids = regular_owner_rail_ids
                    junction_port_id = None
                else:
                    owner_rail_ids = next(iter(port_local_owner_rail_sets))
                    matching_port_witness_ids = {
                        witness.junction_port_id
                        for witness in matching_witnesses
                        if witness.owner_rail_ids == owner_rail_ids
                    }
                    if len(matching_port_witness_ids) != 1:
                        unresolved_boundary_edge_indices.append(
                            boundary_edge_index
                        )
                        witness_ids_by_boundary.append(())
                        continue
                    junction_port_id = next(iter(matching_port_witness_ids))
                boundary_witness = (
                    test_context.addon.utils.feature_chamfer_binding_utils.BoundaryWitness(
                        witness_id=f"native-boundary-edge:{boundary_edge_index}",
                        owner_rail_ids=owner_rail_ids,
                        junction_port_id=junction_port_id,
                        source_patch_id=patch_ids[0],
                    )
                )
                boundary_witness_registry.append(boundary_witness)
                witness_ids_by_boundary.append((boundary_witness.witness_id,))
            chamfer_boundary_edge_indices = [
                edge_index
                for edge_index in boundary_edge_indices
                if edge_index not in source_fragment_boundary_edge_indices
            ]
            witness_validation = (
                test_context.addon.utils.feature_chamfer_binding_utils.validate_boundary_witnesses(
                    plan,
                    len(chamfer_boundary_edge_indices),
                    boundary_witness_registry,
                    witness_ids_by_boundary,
                )
            )
            if witness_validation.status == "PASS":
                first_witness_id = witness_ids_by_boundary[0][0]
                missing_witness_ids = list(witness_ids_by_boundary)
                missing_witness_ids[0] = ()
                conflicting_witness_ids = list(witness_ids_by_boundary)
                conflicting_witness_ids[0] = (
                    first_witness_id,
                    witness_ids_by_boundary[1][0],
                )
                missing_validation = (
                    test_context.addon.utils.feature_chamfer_binding_utils.validate_boundary_witnesses(
                        plan,
                        len(boundary_edge_indices),
                        boundary_witness_registry,
                        missing_witness_ids,
                    )
                )
                conflicting_validation = (
                    test_context.addon.utils.feature_chamfer_binding_utils.validate_boundary_witnesses(
                        plan,
                        len(boundary_edge_indices),
                        boundary_witness_registry,
                        conflicting_witness_ids,
                    )
                )
            else:
                missing_validation = witness_validation
                conflicting_validation = witness_validation
        finally:
            collection_bm.free()
            multi_bm.free()
        artifact_path = ARTIFACT_DIR / artifact_name
        artifact = {
            "source_fingerprint_unchanged": (
                _mesh_fingerprint(source) == source_fingerprint_before
            ),
            "closed_equivalent": closed_equivalent,
            "open_equivalent": open_equivalent,
            "collection_closed_counts": {
                "vertices": len(collection_output.data.vertices),
                "edges": len(collection_output.data.edges),
                "faces": len(collection_output.data.polygons),
            },
            "multi_input_closed_counts": {
                "vertices": len(multi_mesh.vertices),
                "edges": len(multi_mesh.edges),
                "faces": len(multi_mesh.polygons),
            },
            "collection_cleanup": collection_cleanup,
            "multi_input_cleanup": multi_cleanup,
            "boundary_edge_count": len(boundary_edge_indices),
            "chamfer_boundary_edge_count": len(chamfer_boundary_edge_indices),
            "source_fragment_boundary_edge_indices": (
                source_fragment_boundary_edge_indices
            ),
            "witnessed_boundary_edge_count": len(witnessed_boundary_edge_indices),
            "missing_boundary_edge_indices": sorted(
                set(boundary_edge_indices) - set(witnessed_boundary_edge_indices)
            ),
            "boundary_owner_candidates": boundary_owner_candidates,
            "boundary_endpoint_tokens": boundary_endpoint_tokens,
            "boundary_compound_endpoint_records": (
                boundary_compound_endpoint_records
            ),
            "boundary_patch_candidates": boundary_patch_candidates,
            "boundary_witness_validation": {
                "status": witness_validation.status,
                "consumed_edge_count": witness_validation.consumed_edge_count,
                "missing_edge_indices": witness_validation.missing_edge_indices,
                "duplicate_edge_indices": witness_validation.duplicate_edge_indices,
                "conflicting_edge_indices": witness_validation.conflicting_edge_indices,
                "unknown_witness_ids": witness_validation.unknown_witness_ids,
                "incompatible_witness_ids": witness_validation.incompatible_witness_ids,
            },
            "fail_closed_validations": {
                "missing_status": missing_validation.status,
                "missing_edge_indices": missing_validation.missing_edge_indices,
                "conflict_status": conflicting_validation.status,
                "conflicting_edge_indices": (
                    conflicting_validation.conflicting_edge_indices
                ),
            },
            "unresolved_boundary_edge_indices": (
                unresolved_boundary_edge_indices
            ),
            "owner_missing_boundary_edge_indices": sorted(
                int(edge_index)
                for edge_index, owner_ids in boundary_owner_candidates.items()
                if not owner_ids
            ),
            "owner_conflicting_boundary_edge_indices": sorted(
                int(edge_index)
                for edge_index, owner_ids in boundary_owner_candidates.items()
                if len(owner_ids) > 1
            ),
            "patch_missing_boundary_edge_indices": sorted(
                int(edge_index)
                for edge_index, patch_ids in boundary_patch_candidates.items()
                if not patch_ids
            ),
            "patch_conflicting_boundary_edge_indices": sorted(
                int(edge_index)
                for edge_index, patch_ids in boundary_patch_candidates.items()
                if len(patch_ids) > 1
            ),
            "foreign_endpoint_token_boundary_edge_indices": sorted(
                int(edge_index)
                for edge_index, owner_ids in boundary_owner_candidates.items()
                if any(
                    record["pipe_id"] not in owner_ids
                    or pipe_id_by_token.get(record["token"]) != record["pipe_id"]
                    for record in boundary_compound_endpoint_records[edge_index]
                )
            ),
            "boundary_plan_assignments": {
                edge_index: {
                    "owner_pipe_ids": owner_ids,
                    "endpoint_port_ids": sorted({
                        port_id_by_token[token]
                        for token in boundary_endpoint_tokens[edge_index]
                        if token in port_id_by_token
                    }),
                    "source_patch_ids": boundary_patch_candidates[edge_index],
                    "candidate_witness_ids": sorted({
                        witness.witness_id
                        for pipe_id in owner_ids
                        for witness in witnesses_by_pipe_id.get(pipe_id, ())
                        if witness.source_patch_id in boundary_patch_candidates[edge_index]
                    }),
                }
                for edge_index, owner_ids in boundary_owner_candidates.items()
            },
            "plan_witness_inputs": {
                "strands_by_pipe_id": {
                    str(pipe_id): strand.strand_id
                    for pipe_id, strand in utils._plan_strands_by_pipe_id(
                        plan,
                        groups,
                        source.data,
                    ).items()
                },
                "groups": [
                    {
                        "pipe_id": group["pipe_id"],
                        "patch_pair": list(group["patch_pair"]),
                        "patch_pair_by_edge": [
                            list(pair) for pair in group["patch_pair_by_edge"]
                        ],
                        "start_feature_degree": group["start_feature_degree"],
                        "end_feature_degree": group["end_feature_degree"],
                    }
                    for group in groups
                ],
                "source_edge_pipe_ids": {
                    str(edge_index + 1): sorted(
                        group["pipe_id"]
                        for group in groups
                        if edge_index in group["edge_indices"]
                    )
                    for edge_index in range(len(source.data.edges))
                    if any(
                        edge_index in group["edge_indices"]
                        for group in groups
                    )
                },
                "source_vertex_port_ids": {
                    str(vertex_index + 1): port.port_id
                    for vertex_index in range(len(source.data.vertices))
                    for vertex_key in (
                        test_context.addon.utils.feature_chamfer_plan_utils._vertex_key(
                            source.data,
                            vertex_index,
                        ),
                    )
                    for port in plan.junction_ports
                    if port.vertex_key == vertex_key
                },
                "rails": [
                    {
                        "rail_id": rail.rail_id,
                        "owner_strand_id": rail.owner_strand_id,
                        "side": rail.side,
                        "endpoint_port_ids": list(rail.endpoint_port_ids),
                    }
                    for rail in plan.rail_chains
                ],
                "ports": [
                    {
                        "port_id": port.port_id,
                        "incident_strand_ids": list(port.incident_strand_ids),
                    }
                    for port in plan.junction_ports
                ],
            },
            "source_identity": {
                "vertices": [
                    {
                        "source_vertex_id": vertex.index + 1,
                        "coordinate": [
                            round(float(value), 8) for value in vertex.co
                        ],
                    }
                    for vertex in source_identity_mesh.vertices
                ],
                "edges": [
                    {
                        "source_edge_id": edge.index + 1,
                        "source_vertex_ids": [
                            int(vertex_index) + 1
                            for vertex_index in edge.vertices
                        ],
                        "sharp": edge.index in sharp_source_edge_indices,
                        "source_patch_ids": sorted({
                            source_patch_ids[polygon_index]
                            for polygon in source_identity_mesh.polygons
                            if edge.key in polygon.edge_keys
                            for polygon_index in (polygon.index,)
                        }),
                    }
                    for edge in source_identity_mesh.edges
                ],
            },
            "boundary_origin_records": boundary_origin_records,
        }
        artifact_path.write_text(
            json.dumps(artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        ensure(
            artifact["source_fingerprint_unchanged"]
            and not artifact["foreign_endpoint_token_boundary_edge_indices"]
            and not artifact["patch_missing_boundary_edge_indices"]
            and not artifact["patch_conflicting_boundary_edge_indices"]
            and not artifact["unresolved_boundary_edge_indices"]
            and artifact["boundary_witness_validation"]["status"] == "PASS"
            and artifact["boundary_witness_validation"]["consumed_edge_count"]
            == artifact["chamfer_boundary_edge_count"]
            and artifact["fail_closed_validations"]["missing_status"]
            == "boundary_witness_incomplete"
            and tuple(artifact["fail_closed_validations"]["missing_edge_indices"])
            == (0,)
            and artifact["fail_closed_validations"]["conflict_status"]
            == "boundary_witness_incomplete"
            and tuple(
                artifact["fail_closed_validations"]["conflicting_edge_indices"]
            ) == (0,),
            f"Multi-input witness probe lost Pipe-local endpoint identity: {artifact_path}",
        )
    finally:
        bpy.data.meshes.remove(multi_mesh)
        bpy.data.meshes.remove(source_identity_mesh)
        if "collection_open_mesh" in locals():
            bpy.data.meshes.remove(collection_open_mesh)
        if "multi_open_mesh" in locals():
            bpy.data.meshes.remove(multi_open_mesh)
    result.add_detail(
        f"PROTOTYPE/STOP: multi-input Exact covered "
        f"{witness_validation.consumed_edge_count}/"
        f"{len(chamfer_boundary_edge_indices)} "
        f"Boundary Edges; equivalent={closed_equivalent and open_equivalent}; "
        f"artifact={artifact_path}"
    )
    return artifact


# 验证两个真实目标与两个半径在 probe-only backend 上均满足 authoritative witness 门槛。
# test_context/result: 已注册 add-on 的测试上下文与结果记录器。
def test_feature_chamfer_multi_input_boolean_real_target_matrix_probe(
    test_context: TestContext,
    result: TestCaseResult,
):
    records = []
    failed = None
    for label, fixture_name, object_name in (
        ("simple", "feature-chamfer-product-simple.blend", "Solid 44"),
        ("tricky", "feature-chamfer-product-tricky.blend", "Solid.004"),
    ):
        for radius in (0.01, 0.03):
            load_fixture_blend(fixture_name)
            source = bpy.data.objects.get(object_name)
            ensure(
                source is not None and source.type == "MESH",
                f"Real target is missing: {fixture_name}/{object_name}",
            )
            cell_name = (
                f"feature_chamfer_multi_input_{label}_"
                f"{object_name.lower().replace(' ', '_').replace('.', '_')}_"
                f"r{radius:.3f}.json"
            )
            try:
                artifact = test_feature_chamfer_multi_input_boolean_witness_probe(
                    test_context,
                    result,
                    source=source,
                    radius=radius,
                    artifact_name=cell_name,
                )
            except TestFailure as error:
                artifact = json.loads(
                    (ARTIFACT_DIR / cell_name).read_text(encoding="utf-8")
                )
                if failed is None:
                    failed = error
            records.append({
                "label": label,
                "fixture": fixture_name,
                "object": object_name,
                "radius": radius,
                "artifact": str(ARTIFACT_DIR / cell_name),
                "boundary_edge_count": artifact["boundary_edge_count"],
                "chamfer_boundary_edge_count": artifact[
                    "chamfer_boundary_edge_count"
                ],
                "source_fragment_edge_count": len(
                    artifact["source_fragment_boundary_edge_indices"]
                ),
                "consumed_edge_count": artifact[
                    "boundary_witness_validation"
                ]["consumed_edge_count"],
                "status": artifact["boundary_witness_validation"]["status"],
                "source_fingerprint_unchanged": artifact[
                    "source_fingerprint_unchanged"
                ],
            })
    matrix_path = ARTIFACT_DIR / (
        "feature_chamfer_multi_input_real_target_matrix_probe.json"
    )
    matrix_path.write_text(
        json.dumps(
            {
                "status": "PASS" if failed is None else "STOP",
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if failed is not None:
        raise TestFailure(f"Real target witness matrix remains STOP: {matrix_path}")
    ensure(
        len(records) == 4
        and all(record["status"] == "PASS" for record in records)
        and all(
            record["chamfer_boundary_edge_count"]
            == record["consumed_edge_count"]
            for record in records
        )
        and all(record["source_fingerprint_unchanged"] for record in records),
        f"Real target witness matrix is incomplete: {matrix_path}",
    )
    result.add_detail(f"PROTOTYPE/STOP: real target matrix 4/4; artifact={matrix_path}")


# 从 production Pipe/Cutter Set 运行 Exact Boolean，并由 authoritative binder 验证 degree-3 junction provenance。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_feature_chamfer_intersecting_endpoint_provenance_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("IntersectingEndpointProvenance")
    source = make_orthogonal_degree_three_feature_junction(
        "IntersectingEndpointProvenanceSource",
        collection,
    )
    radius = 0.08
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=radius,
        pipe_resolution=8,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="CUTTER_UNION",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
        preserve_source_visibility=True,
    )
    ensure(
        stats["status"] == "finished"
        and stats["pipe_group_count"] == 2
        and stats["spatial_junction_count"] >= 1
        and stats["joined_cutter_batch_count"] == 2,
        f"Production degree-3 Cutter Set did not expose intersecting Pipes: {stats}",
    )
    plan_stats = utils._base_stats(
        source,
        radius,
        8,
        35.0,
        3.0,
        1.5,
        "FEATURE_GRAPH",
    )
    groups = utils._build_preview_feature_graph(source, radius, plan_stats)
    plan = test_context.addon.utils.feature_chamfer_plan_utils.build_chamfer_plan(
        source,
        groups,
        radius,
        "GN_PREVIEW_V1",
    )
    _, endpoint_registry = utils._build_strand_endpoint_port_tokens(
        plan,
        groups,
        source.data,
    )
    expected_tokens = {record.token for record in endpoint_registry}
    cutter_collection = bpy.data.collections[stats["cutter_collection_name"]]
    cutter_tokens = {
        int(item.value)
        for cutter in cutter_collection.objects
        for attribute_name in (
            "hst_pipe_start_port_token",
            "hst_pipe_end_port_token",
        )
        for attribute in (cutter.data.attributes.get(attribute_name),)
        if attribute is not None
        for item in attribute.data
        if int(item.value) > 0
    }
    ensure(
        cutter_tokens == expected_tokens,
        f"Production Cutter Set endpoint namespace is incomplete: {cutter_tokens}",
    )
    output = utils._duplicate_source(source, collection)
    source_patch_ids = utils._source_face_patch_ids(source)
    utils._mark_original_faces(output, source_patch_ids)
    utils._initialize_source_membership_schema(
        output.data,
        cutter_collection.objects,
        source_patch_ids,
    )
    utils._initialize_boundary_witness_schema(
        output.data,
        cutter_collection.objects,
        source_patch_ids,
    )
    for cutter in sorted(cutter_collection.objects, key=lambda obj: obj.name):
        modifier = output.modifiers.new(
            f"Authoritative endpoint probe {cutter.name}",
            type="BOOLEAN",
        )
        modifier.operation = "DIFFERENCE"
        modifier.solver = "EXACT"
        modifier.operand_type = "OBJECT"
        modifier.object = cutter
        with bpy.context.temp_override(
            object=output,
            active_object=output,
            selected_objects=[output],
            selected_editable_objects=[output],
        ):
            bpy.ops.object.modifier_apply(modifier=modifier.name)
    boolean_provenance_artifact = {
        "boundary_witness": utils._mark_boolean_boundary_witnesses(output),
    }
    groove_face_indices = utils._groove_face_indices(output, plan_stats)
    bm = bmesh.new()
    bm.from_mesh(output.data)
    bm.faces.ensure_lookup_table()
    groove_faces = tuple(bm.faces[index] for index in groove_face_indices)
    membership_counts = {
        attribute.name: sum(bool(item.value) for item in attribute.data)
        for attribute in output.data.attributes
        if attribute.name.startswith(
            (
                "hst_pipe_component_member_",
                "hst_pipe_endpoint_member_",
            )
        )
    }
    boolean_provenance_artifact.update({
        "plan_id": plan.plan_id,
        "endpoint_registry": [
            {
                "token": record.token,
                "pipe_id": record.pipe_id,
                "strand_id": record.strand_id,
                "endpoint_role": record.endpoint_role,
                "port_id": record.port_id,
            }
            for record in endpoint_registry
        ],
        "faces": [
            {
                "face_index": face.index,
                "vertex_indices": sorted(vertex.index for vertex in face.verts),
                "component_memberships": sorted(
                    int(layer_name.rsplit("_", 1)[1])
                    for layer_name in (
                        attribute.name
                        for attribute in output.data.attributes
                        if attribute.name.startswith("hst_pipe_component_member_")
                    )
                    for layer in (
                        bm.faces.layers.int.get(layer_name)
                        or bm.faces.layers.bool.get(layer_name),
                    )
                    if layer is not None and bool(face[layer])
                ),
                "endpoint_memberships": sorted(
                    int(layer_name.rsplit("_", 1)[1])
                    for layer_name in (
                        attribute.name
                        for attribute in output.data.attributes
                        if attribute.name.startswith("hst_pipe_endpoint_member_")
                    )
                    for layer in (
                        bm.faces.layers.int.get(layer_name)
                        or bm.faces.layers.bool.get(layer_name),
                    )
                    if layer is not None and bool(face[layer])
                ),
                "is_groove": face in groove_faces,
            }
            for face in bm.faces
        ],
    })
    artifact_path = ARTIFACT_DIR / (
        "feature_chamfer_intersecting_endpoint_provenance.json"
    )
    try:
        binding = test_context.addon.utils.feature_chamfer_binding_utils.bind_boolean_boundary(
            plan,
            groups,
            bm,
            groove_faces,
            component_layer_name="hst_pipe_component_id",
            source_patch_layer_name="hst_pipe_source_patch_id",
            source_mesh=source.data,
            endpoint_port_tokens=endpoint_registry,
            endpoint_token_layer_names=(
                "hst_pipe_start_port_token",
                "hst_pipe_end_port_token",
            ),
            component_membership_layer_names=tuple(
                sorted(
                    attribute.name
                    for attribute in output.data.attributes
                    if attribute.name.startswith("hst_pipe_component_member_")
                )
            ),
            endpoint_membership_layer_names=tuple(
                sorted(
                    attribute.name
                    for attribute in output.data.attributes
                    if attribute.name.startswith("hst_pipe_endpoint_member_")
                )
            ),
            source_patch_membership_layer_names=tuple(
                sorted(
                    attribute.name
                    for attribute in output.data.attributes
                    if attribute.name.startswith("hst_pipe_source_patch_member_")
                )
            ),
            boundary_owner_witness_layer_names=tuple(
                sorted(
                    attribute.name
                    for attribute in output.data.attributes
                    if attribute.name.startswith(
                        utils.BOUNDARY_OWNER_WITNESS_ATTRIBUTE_PREFIX
                    )
                )
            ),
            boundary_patch_witness_layer_names=tuple(
                sorted(
                    attribute.name
                    for attribute in output.data.attributes
                    if attribute.name.startswith(
                        utils.BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX
                    )
                )
            ),
        )
        boolean_provenance_artifact["binding"] = {
            "status": binding.status,
            "boundary_edge_count": binding.boundary_edge_count,
            "consumed_edge_count": binding.consumed_edge_count,
            "unowned_edge_indices": list(binding.unowned_edge_indices),
            "topology_incompatible_rail_ids": list(
                binding.topology_incompatible_rail_ids
            ),
            "edge_diagnostics": [
                {
                    "boundary_edge_index": diagnostic.boundary_edge_index,
                    "vertex_indices": list(diagnostic.vertex_indices),
                    "linked_face_indices": list(diagnostic.linked_face_indices),
                    "direct_owner_pipe_ids": list(
                        diagnostic.direct_owner_pipe_ids
                    ),
                    "owner_witness_pipe_ids": list(
                        diagnostic.owner_witness_pipe_ids
                    ),
                    "unknown_owner_present": diagnostic.unknown_owner_present,
                    "vertex_owner_pipe_ids": [
                        [vertex_index, list(pipe_ids)]
                        for vertex_index, pipe_ids
                        in diagnostic.vertex_owner_pipe_ids
                    ],
                    "adjacent_owner_pipe_ids": list(
                        diagnostic.adjacent_owner_pipe_ids
                    ),
                    "candidate_owner_pipe_ids": list(
                        diagnostic.candidate_owner_pipe_ids
                    ),
                    "candidate_owner_strand_ids": list(
                        diagnostic.candidate_owner_strand_ids
                    ),
                    "endpoint_tokens": list(diagnostic.endpoint_tokens),
                    "endpoint_token_records": [
                        {
                            "token": record.token,
                            "pipe_id": record.pipe_id,
                            "strand_id": record.strand_id,
                            "endpoint_role": record.endpoint_role,
                            "port_id": record.port_id,
                        }
                        for record in diagnostic.endpoint_token_records
                    ],
                    "compatible_port_ids": list(
                        diagnostic.compatible_port_ids
                    ),
                    "retained_patch_ids": list(
                        diagnostic.retained_patch_ids
                    ),
                    "patch_witness_ids": list(
                        diagnostic.patch_witness_ids
                    ),
                    "rejection_reason": diagnostic.rejection_reason,
                }
                for diagnostic in binding.edge_diagnostics
            ],
            "boundary_edge_witnesses": [
                {
                    "boundary_edge_index": edge_index,
                    "mesh_edge_index": boundary_edge.index,
                    "vertex_indices": sorted(
                        vertex.index for vertex in boundary_edge.verts
                    ),
                    "owner_witnesses": sorted(
                        int(attribute.name.rsplit("_", 1)[1])
                        for attribute in output.data.attributes
                        if attribute.name.startswith(
                            utils.BOUNDARY_OWNER_WITNESS_ATTRIBUTE_PREFIX
                        )
                        for layer in (
                            bm.edges.layers.int.get(attribute.name)
                            or bm.edges.layers.bool.get(attribute.name),
                        )
                        if layer is not None and bool(boundary_edge[layer])
                    ),
                    "patch_witnesses": sorted(
                        int(attribute.name.rsplit("_", 1)[1])
                        for attribute in output.data.attributes
                        if attribute.name.startswith(
                            utils.BOUNDARY_PATCH_WITNESS_ATTRIBUTE_PREFIX
                        )
                        for layer in (
                            bm.edges.layers.int.get(attribute.name)
                            or bm.edges.layers.bool.get(attribute.name),
                        )
                        if layer is not None and bool(boundary_edge[layer])
                    ),
                }
                for edge_index, boundary_edge in enumerate(
                    edge for edge in bm.edges if len(edge.link_faces) == 1
                )
            ],
        }
        artifact_path.write_text(
            json.dumps(boolean_provenance_artifact, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        ensure(
            binding.status == "boundary_binding_incomplete"
            and binding.boundary_edge_count > binding.consumed_edge_count
            and binding.unowned_edge_indices
            and binding.topology_incompatible_rail_ids
            and not binding.missing_rail_ids
            and not binding.missing_port_ids,
            (
                "Intersecting production endpoint provenance did not preserve "
                "the expected fail-closed evidence: "
                f"memberships={membership_counts}; {binding}"
            ),
        )
    finally:
        bm.free()
    result.add_detail(
        (
            "degree-3 production provenance remained fail-closed with "
            f"tokens={sorted(expected_tokens)}; artifact={artifact_path}"
        )
    )


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
    first_node_group_name = node_group.name
    ensure(
        node_group.get("hst_feature_chamfer_preview_backend") == "PYTHON_CURVE_PIPE",
        "Preview wrapper does not use the Python Curve Pipe backend",
    )


    ensure(node_group.bl_idname == "GeometryNodeTree", "Preview asset has wrong node tree type")
    ensure(
        node_group.get(test_context.const.FEATURE_CHAMFER_GN_ASSET_VERSION_TAG)
        == test_context.const.FEATURE_CHAMFER_GN_ASSET_VERSION,
        "Preview asset version mismatch",
    )
    curve_pipe_nodes = [
        node
        for node in node_group.nodes
        if node.bl_idname == "GeometryNodeGroup"
        and node.node_tree is not None
        and node.node_tree.name == test_context.const.FEATURE_CHAMFER_CURVE_NODE
    ]
    ensure(len(curve_pipe_nodes) == 1, "Preview wrapper does not reference the controlled Curve Pipe asset")
    boolean_pro_nodes = [
        node
        for node in node_group.nodes
        if node.bl_idname == "GeometryNodeGroup"
        and node.node_tree is not None
        and node.node_tree.name.startswith("HST Feature Chamfer :: Boolean Pro")
    ]
    ensure(len(boolean_pro_nodes) == 1, "Preview wrapper does not preserve the controlled Boolean Pro node")
    ensure(
        not any(node.bl_idname == "GeometryNodeMeshBoolean" for node in node_group.nodes),
        "Preview wrapper regressed to native Mesh Boolean",
    )
    ensure(
        any(group.name.startswith("HST Feature Chamfer :: Float Boolean Edges") for group in bpy.data.node_groups)
        and any(group.name.startswith("HST Feature Chamfer :: Boolean Solver Select") for group in bpy.data.node_groups),
        "Boolean Pro nested dependencies were not appended",
    )
    boolean_node = boolean_pro_nodes[0]
    group_input = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupInput")
    curve_pipe_node = curve_pipe_nodes[0]
    ensure(
        any(
            link.from_node == group_input
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry"
            for link in node_group.links
        ),
        "Source Geometry is not connected to Boolean Pro",
    )
    ensure(
        any(
            link.from_node == curve_pipe_node
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry B"
            for link in node_group.links
        ),
        "Curve Pipe cutter is not connected to Boolean Pro Geometry B",
    )
    ensure(
        bpy.data.node_groups.get(test_context.const.FEATURE_CHAMFER_CURVE_DEPENDENCY)
        is not None,
        "Curve Pipe dependency was not appended",
    )
    ensure(
        any(
            node.bl_idname == "GeometryNodeObjectInfo"
            and node.inputs["Object"].default_value is not None
            and node.inputs["Object"].default_value.type == "CURVE"
            for node in node_group.nodes
        ),
        "Preview wrapper does not consume its Python Curve source",
    )
    second_result, second_modifier = run_feature_chamfer_gn(source, action="PREVIEW")
    ensure(second_result == {"FINISHED"}, f"Second Preview failed: {second_result}")
    ensure(first_modifier == second_modifier, "Repeated Preview stacked a modifier")
    ensure(sum(1 for modifier in source.modifiers if modifier.name == first_modifier.name) == 1, "Duplicate Preview modifier")
    ensure(_mesh_fingerprint(source) == source_hash, "Preview changed source Mesh data")
    result.add_detail(f"asset={first_node_group_name}, modifier={first_modifier.name}")


# 返回正式 Preview wrapper 内 Curve Circle 的 resolution 与 radius link contract。
# modifier: 目标 Operator 创建的 owned GN modifier；返回 profile 诊断字典。
def preview_profile_contract(modifier):
    node_group = modifier.node_group
    curve_circle = node_group.nodes.get("HST Four-sided Chamfer Profile")
    ensure(curve_circle is not None, "Formal Preview wrapper has no owned profile node")
    radius_linked = any(
        link.to_node == curve_circle
        and link.to_socket.name == "Radius"
        and link.from_socket.name == "Radius"
        for link in node_group.links
    )
    return {
        "resolution": int(curve_circle.inputs["Resolution"].default_value),
        "radius_linked_directly": radius_linked,
    }


# 从目标 Object 的 evaluated modifier result 读取 Mesh guard，不改变用户 source。
# source: 带 Feature Chamfer Preview 的 Mesh Object；返回 face/boundary/non-manifold 统计。
def evaluated_preview_mesh_guard(source):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated_mesh = bpy.data.meshes.new_from_object(
        source.evaluated_get(depsgraph),
        depsgraph=depsgraph,
    )
    bm = bmesh.new()
    bm.from_mesh(evaluated_mesh)
    guard = {
        "vertex_count": len(bm.verts),
        "face_count": len(bm.faces),
        "boundary_edge_count": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "non_manifold_edge_count": sum(1 for edge in bm.edges if len(edge.link_faces) != 2),
        "zero_area_face_count": sum(1 for face in bm.faces if face.calc_area() <= 1.0e-12),
    }
    bm.free()
    bpy.data.meshes.remove(evaluated_mesh)
    return guard


# 验证目标 Operator 的 Show Cutter 与 Boolean result 都可 evaluated，并留下可读 geometry guards。
# source/radius: 已标记 Sharp Edge 的 source Mesh 与 Preview radius；返回 cutter/boolean guards。
def assert_operator_preview_cutter_and_boolean_guards(source, radius):
    cutter_result, cutter_modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=radius,
        show_cutter=True,
    )
    ensure(cutter_result == {"FINISHED"} and cutter_modifier is not None, "Cutter evaluation Preview failed")
    cutter_guard = evaluated_preview_mesh_guard(source)
    ensure(cutter_guard["face_count"] > 0, "Evaluated Curve Pipe cutter is empty")
    ensure(cutter_guard["boundary_edge_count"] == 0, f"Evaluated cutter has boundary Edges: {cutter_guard}")
    ensure(cutter_guard["non_manifold_edge_count"] == 0, f"Evaluated cutter is non-manifold: {cutter_guard}")

    boolean_result, boolean_modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=radius,
        show_cutter=False,
    )
    ensure(boolean_result == {"FINISHED"} and boolean_modifier == cutter_modifier, "Boolean evaluation Preview failed")
    boolean_guard = evaluated_preview_mesh_guard(source)
    ensure(boolean_guard["face_count"] > 0, "Evaluated Boolean Pro result is empty")
    ensure(boolean_guard["zero_area_face_count"] == 0, f"Evaluated Boolean result has zero-area Faces: {boolean_guard}")
    ensure(
        boolean_guard["vertex_count"] != len(source.data.vertices)
        or boolean_guard["face_count"] != len(source.data.polygons),
        f"Evaluated Boolean Pro result did not change source geometry: {boolean_guard}",
    )
    return cutter_guard, boolean_guard
# 验证 Radius 等参数通过 interface identifier 更新，且 cutter 是 closed manifold。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_modifier_parameter_and_cutter_smoke(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNParameters")
    source = make_test_mesh("GNParameterSource", collection)
    mark_all_edges_sharp(source)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        radius=0.08,
        show_cutter=True,
    )
    ensure(operator_result == {"FINISHED"}, f"Cutter Preview failed: {operator_result}")
    expected = {
        "Radius": 0.08,
        "Show Cutter": True,
    }
    for name, expected_value in expected.items():
        identifier = node_input_identifier(modifier.node_group, name)
        actual_value = modifier[identifier]
        ensure(abs(actual_value - expected_value) < 1.0e-6, f"{name} was not updated: {actual_value}")
    guard = evaluated_preview_mesh_guard(source)
    ensure(guard["face_count"] > 0, "Cutter Preview is empty")
    ensure(guard["boundary_edge_count"] == 0, f"Cutter boundary edges: {guard}")
    ensure(guard["non_manifold_edge_count"] == 0, f"Cutter non-manifold edges: {guard}")
    result.add_detail(f"cutter_faces={guard['face_count']}")


# 从目标 Operator 验证 Preview 已由 Python CutterStrands 与受控 Curve Pipe asset 驱动。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_curve_backend_acceptance(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNOperatorCurveAcceptance")
    source = make_degree_three_feature_junction(
        "GNOperatorCurveAcceptanceSource",
        collection,
    )
    source_hash = _mesh_fingerprint(source)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(operator_result == {"FINISHED"}, f"Operator Preview failed: {operator_result}")
    ensure(modifier is not None, "Operator Preview did not create its owned modifier")
    curve_source = next(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "CURVE"
            and obj.get("hst_feature_chamfer_curve_owner") == source.name
        ),
        None,
    )
    ensure(curve_source is not None, "Operator Preview did not create an owned Python Curve source")
    ensure(
        len(curve_source.data.splines) == 2,
        f"Degree-3 FeatureGraph did not produce two unbranched splines: {len(curve_source.data.splines)}",
    )
    ensure(
        sorted(len(spline.points) for spline in curve_source.data.splines) == [2, 3],
        "Degree-3 main strand and unmatched branch were not preserved",
    )
    first_pairing_signature = sorted(
        tuple(
            tuple(round(value, 6) for value in point.co[:3])
            for point in spline.points
        )
        for spline in curve_source.data.splines
    )
    first_curve_source_name = curve_source.name
    first_curve_splines = [
        {
            "point_count": len(spline.points),
            "cyclic": spline.use_cyclic_u,
        }
        for spline in curve_source.data.splines
    ]
    ensure(
        modifier.node_group.get("hst_feature_chamfer_preview_backend")
        == "PYTHON_CURVE_PIPE",
        "Preview modifier still uses the legacy SDF backend",
    )
    ensure(
        any(
            node.bl_idname == "GeometryNodeGroup"
            and node.node_tree is not None
            and node.node_tree.name == test_context.const.FEATURE_CHAMFER_CURVE_NODE
            for node in modifier.node_group.nodes
        ),
        "Preview Node Group does not reference the controlled Even-Thickness asset",
    )
    ensure(
        any(
            node.bl_idname == "GeometryNodeObjectInfo"
            and node.inputs["Object"].default_value == curve_source
            for node in modifier.node_group.nodes
        ),
        "Preview modifier does not consume the owned Curve source",
    )
    redo_result, redo_modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(redo_result == {"FINISHED"} and redo_modifier == modifier, "Degree-3 Preview redo failed")
    redo_curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    redo_pairing_signature = sorted(
        tuple(
            tuple(round(value, 6) for value in point.co[:3])
            for point in spline.points
        )
        for spline in redo_curve_source.data.splines
    )
    ensure(
        redo_pairing_signature == first_pairing_signature,
        "Degree-3 junction pairing changed across Preview redo",
    )
    ensure(_mesh_fingerprint(source) == source_hash, "Operator Preview changed source Mesh")
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_curve_preview_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "operator": "hst.feature_chamfer_gn",
                "action": "PREVIEW",
                "source_object": source.name,
                "source_fingerprint": source_hash,
                "source_fingerprint_unchanged": _mesh_fingerprint(source) == source_hash,
                "preview_modifier": modifier.name,
                "preview_node_group": modifier.node_group.name,
                "preview_backend": modifier.node_group.get(
                    "hst_feature_chamfer_preview_backend"
                ),
                "curve_source": first_curve_source_name,
                "curve_splines": first_curve_splines,
                "curve_pipe_asset": test_context.const.FEATURE_CHAMFER_CURVE_NODE,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"curve={redo_curve_source.name}, splines={len(redo_curve_source.data.splines)}, "
        f"node_group={modifier.node_group.name}, artifact={artifact_path}"
    )


# 验证目标 Operator 在 miter scale 超限的急转处断开 Curve splines。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_splits_acute_miter(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNOperatorAcuteMiter")
    source = make_acute_feature_turn("GNOperatorAcuteMiterSource", collection)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(operator_result == {"FINISHED"} and modifier is not None, "Acute Preview failed")
    curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_source is not None, "Acute Preview did not create owned Curve")
    ensure(
        len(curve_source.data.splines) == 2
        and all(len(spline.points) == 2 for spline in curve_source.data.splines),
        "Miter scale exceeded turn was not split into independent splines",
    )
    result.add_detail("Acute miter produced two independent 2-point splines")


# 验证目标 Operator 将普通 90° Sharp turn 保持为单一连续 miter spline。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_keeps_right_angle_miter_continuous(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNOperatorRightAngleMiter")
    source = make_right_angle_feature_turn("GNOperatorRightAngleMiterSource", collection)
    source_hash = _mesh_fingerprint(source)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(operator_result == {"FINISHED"} and modifier is not None, "90-degree Preview failed")
    curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_source is not None, "90-degree Preview did not create owned Curve")
    ensure(
        len(curve_source.data.splines) == 1
        and len(curve_source.data.splines[0].points) == 3,
        "90-degree turn was split instead of producing one 3-point spline",
    )
    cutter_guard, boolean_guard = assert_operator_preview_cutter_and_boolean_guards(source, 0.05)
    ensure(_mesh_fingerprint(source) == source_hash, "90-degree Preview changed source Mesh")
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_right_angle_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "operator": "hst.feature_chamfer_gn",
                "action": "PREVIEW",
                "fixture": "degree-2 exact 90-degree turn",
                "curve_spline_point_counts": [3],
                "cutter_guard": cutter_guard,
                "boolean_guard": boolean_guard,
                "source_fingerprint_unchanged": _mesh_fingerprint(source) == source_hash,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(f"90-degree miter continuous; cutter={cutter_guard}, boolean={boolean_guard}")


# 验证正式 Operator 使用四边 profile，Radius 仍直接驱动截面且 cutter 保持 closed manifold。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_uses_four_sided_profile(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNFourSidedProfile")
    source = make_right_angle_feature_turn("GNFourSidedProfileSource", collection)
    operator_result, modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
        show_cutter=True,
    )
    ensure(operator_result == {"FINISHED"} and modifier is not None, "Four-sided Preview failed")
    profile_contract = preview_profile_contract(modifier)
    ensure(
        profile_contract == {"resolution": 4, "radius_linked_directly": True},
        f"Formal Preview profile is not a radius-calibrated four-sided cutter: {profile_contract}",
    )
    cutter_guard = evaluated_preview_mesh_guard(source)
    ensure(
        cutter_guard["boundary_edge_count"] == 0
        and cutter_guard["non_manifold_edge_count"] == 0
        and cutter_guard["zero_area_face_count"] == 0,
        f"Four-sided cutter geometry guard failed: {cutter_guard}",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_four_sided_profile_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "target_operator": "hst.feature_chamfer_gn(action=PREVIEW)",
                "profile_contract": profile_contract,
                "radius": 0.05,
                "cutter_guard": cutter_guard,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"four-sided profile={profile_contract}, cutter={cutter_guard}, artifact={artifact_path}"
    )


# 验证目标 Operator 在 degree-4 junction 中生成两对连续 strands，且 redo 配对稳定。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_pairs_degree_four_junction_deterministically(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNOperatorDegreeFour")
    source = make_crossing_feature_strands("GNOperatorDegreeFourSource", collection)
    source_hash = _mesh_fingerprint(source)
    operator_result, modifier = run_feature_chamfer_gn(source, action="PREVIEW", radius=0.05)
    ensure(operator_result == {"FINISHED"} and modifier is not None, "Degree-4 Preview failed")
    curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_source is not None, "Degree-4 Preview did not create owned Curve")
    first_signature = sorted(
        tuple(tuple(round(value, 6) for value in point.co[:3]) for point in spline.points)
        for spline in curve_source.data.splines
    )
    ensure(
        len(first_signature) == 2 and all(len(points) == 3 for points in first_signature),
        "Degree-4 junction did not produce two continuous 3-point splines",
    )
    redo_result, redo_modifier = run_feature_chamfer_gn(source, action="PREVIEW", radius=0.05)
    ensure(redo_result == {"FINISHED"} and redo_modifier == modifier, "Degree-4 Preview redo failed")
    redo_curve = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    redo_signature = sorted(
        tuple(tuple(round(value, 6) for value in point.co[:3]) for point in spline.points)
        for spline in redo_curve.data.splines
    )
    ensure(redo_signature == first_signature, "Degree-4 pairing changed across Preview redo")
    ensure(_mesh_fingerprint(source) == source_hash, "Degree-4 Preview changed source Mesh")
    result.add_detail("Degree-4 junction produced two deterministic continuous strands")


# 验证三根彼此正交的 junction 不会全部断开，并在 redo 时保持同一配对。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_pairs_orthogonal_degree_three_junction(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNOperatorOrthogonalDegreeThree")
    source = make_orthogonal_degree_three_feature_junction(
        "GNOperatorOrthogonalDegreeThreeSource",
        collection,
    )
    source_hash = _mesh_fingerprint(source)
    operator_result, modifier = run_feature_chamfer_gn(source, action="PREVIEW", radius=0.05)
    ensure(operator_result == {"FINISHED"} and modifier is not None, "Orthogonal degree-3 Preview failed")
    curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_source is not None, "Orthogonal degree-3 Preview did not create owned Curve")
    first_signature = sorted(
        tuple(tuple(round(value, 6) for value in point.co[:3]) for point in spline.points)
        for spline in curve_source.data.splines
    )
    ensure(
        sorted(len(points) for points in first_signature) == [2, 3],
        "Three orthogonal branches were all split instead of pairing one strand",
    )
    cutter_guard, boolean_guard = assert_operator_preview_cutter_and_boolean_guards(source, 0.05)
    redo_result, redo_modifier = run_feature_chamfer_gn(source, action="PREVIEW", radius=0.05)
    ensure(redo_result == {"FINISHED"} and redo_modifier == modifier, "Orthogonal degree-3 redo failed")
    redo_curve = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    redo_signature = sorted(
        tuple(tuple(round(value, 6) for value in point.co[:3]) for point in spline.points)
        for spline in redo_curve.data.splines
    )
    ensure(redo_signature == first_signature, "Orthogonal degree-3 pairing changed across Preview redo")
    ensure(_mesh_fingerprint(source) == source_hash, "Orthogonal degree-3 Preview changed source Mesh")
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_orthogonal_junction_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "operator": "hst.feature_chamfer_gn",
                "action": "PREVIEW",
                "fixture": "three orthogonal degree-3 branches",
                "curve_spline_point_counts": sorted(len(points) for points in first_signature),
                "pairing_stable_across_redo": redo_signature == first_signature,
                "cutter_guard": cutter_guard,
                "boolean_guard": boolean_guard,
                "source_fingerprint_unchanged": _mesh_fingerprint(source) == source_hash,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"Three orthogonal branches paired; cutter={cutter_guard}, boolean={boolean_guard}"
    )


# 生成正交方向的几何排序变体，模拟不同 Vertex/Face 创建顺序但保持同一配对语义。
# variant: 0 为原方向，1 为交换 X/Y 轴后的几何变体。
def coplanar_fixture_point(point, variant):
    if variant == 0:
        return point
    return (point[1], point[0], point[2])


# 把几何变体还原到共同坐标系，便于比较 spline partition。
# point/variant: Curve point 与 fixture 变体编号。
def canonical_coplanar_fixture_point(point, variant):
    coordinates = tuple(round(value, 6) for value in point[:3])
    if variant == 0:
        return coordinates
    return (coordinates[1], coordinates[0], coordinates[2])

# 把 Curve splines 转为与创建顺序无关的几何 signature。
# curve_object: owned Preview Curve；返回规范化 points tuples。
def curve_geometry_signature(curve_object, variant=0):
    splines = []
    for spline in curve_object.data.splines:
        points = tuple(
            canonical_coplanar_fixture_point(point.co, variant)
            for point in spline.points
        )
        reversed_points = tuple(reversed(points))
        splines.append(min(points, reversed_points))
    return tuple(sorted(splines))


# 把 Preview Pipe contract 的 points 转为与 Curve spline 相同的方向无关几何签名。
# contract_pipes: owned Curve 上持久化 JSON contract 的 pipes；返回规范化 points tuples。
def preview_pipe_contract_geometry_signature(contract_pipes):
    signatures = []
    for pipe in contract_pipes:
        contract_points = tuple(pipe["points"])
        points = tuple(
            tuple(round(float(component), 6) for component in point)
            for point in contract_points
        )
        reversed_points = tuple(reversed(points))
        signatures.append((min(points, reversed_points), bool(pipe["is_cyclic"])))
    return tuple(sorted(signatures))


# 把实际 owned Preview Curve 转为包含 cyclic 状态的方向无关几何签名。
# curve_object: 正式 PREVIEW Operator 创建的 owned Curve；返回规范化 spline tuples。
def owned_preview_curve_contract_signature(curve_object):
    signatures = []
    for spline in curve_object.data.splines:
        points = tuple(
            tuple(round(float(component), 6) for component in point.co[:3])
            for point in spline.points
        )
        reversed_points = tuple(reversed(points))
        signatures.append((min(points, reversed_points), bool(spline.use_cyclic_u)))
    return tuple(sorted(signatures))


# 验证正式 Operator 不会因 Surface Patch/convexity metadata 把平滑 degree-2 环切断。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_keeps_smooth_degree_two_ring_cyclic(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNSmoothDegreeTwoRing")
    source = make_smooth_cyclic_feature_ring("GNSmoothDegreeTwoRingSource", collection)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    original_convexity = utils._edge_convexity
    original_surface_patch_map = utils._surface_patch_map

    def alternating_convexity(edge):
        return 1 if edge.index % 2 else -1

    def isolated_surface_patches(bm, sharp_edges):
        face_patch, patch_count = original_surface_patch_map(bm, sharp_edges)
        for edge in sharp_edges:
            for face in edge.link_faces:
                face_patch[face] = face.index
        return face_patch, len({face.index for face in bm.faces})

    utils._edge_convexity = alternating_convexity
    utils._surface_patch_map = isolated_surface_patches
    try:
        operator_result, modifier = run_feature_chamfer_gn(
            source,
            action="PREVIEW",
            radius=0.05,
        )
    finally:
        utils._edge_convexity = original_convexity
        utils._surface_patch_map = original_surface_patch_map
    ensure(operator_result == {"FINISHED"} and modifier is not None, "Smooth ring Preview failed")
    curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_source is not None, "Smooth ring Preview did not create owned Curve")
    ensure(
        len(curve_source.data.splines) == 1
        and curve_source.data.splines[0].use_cyclic_u
        and len(curve_source.data.splines[0].points) == 32,
        "Smooth degree-2 ring was split by patch/convexity metadata",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_smooth_degree_two_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "target_operator": "hst.feature_chamfer_gn(action=PREVIEW)",
                "spline_count": len(curve_source.data.splines),
                "cyclic": curve_source.data.splines[0].use_cyclic_u,
                "point_count": len(curve_source.data.splines[0].points),
                "metadata_fixture": "alternating convexity + isolated Surface Patch IDs",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(
        f"Smooth 32-edge degree-2 ring remained one cyclic Operator spline; artifact={artifact_path}"
    )


# 验证 junction scoring 使用 endpoint containment，且不再依赖 cube 的固定 strand 数。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_junction_endpoint_containment_score_contract(
    test_context: TestContext,
    result: TestCaseResult,
):
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    from mathutils import Vector

    class HalfSpaceBVH:
        def find_nearest(self, point):
            point = Vector(point)
            return (Vector((0.0, point.y, point.z)), Vector((1.0, 0.0, 0.0)), 0, abs(point.x))

    hidden_cap_candidate = [
        {
            "endpoint_samples": [(-0.2, 0.0, 0.0), (-0.15, 1.0, 0.0)],
        }
    ]
    exposed_cap_candidate = [
        {
            "endpoint_samples": [(0.2, 0.0, 0.0), (0.15, 1.0, 0.0)],
        }
    ]
    source_bvh = HalfSpaceBVH()
    hidden_score = utils._strand_endpoint_containment_score(
        hidden_cap_candidate,
        source_bvh,
        0.1,
    )
    exposed_score = utils._strand_endpoint_containment_score(
        exposed_cap_candidate,
        source_bvh,
        0.1,
    )
    ensure(
        hidden_score[0] < exposed_score[0],
        f"Hidden cap candidate did not beat exposed cap candidate: {hidden_score}, {exposed_score}",
    )
    result.add_detail(
        f"endpoint containment hidden={hidden_score}, exposed={exposed_score}"
    )


# 验证 closed Mesh BVH ray parity 能区分埋入 source solid 与外露的 endpoint cap。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_junction_endpoint_containment_closed_mesh_bvh(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNEndpointContainmentBVH")
    source = make_test_mesh("GNEndpointContainmentBVHSource", collection)
    bm = bmesh.new()
    bm.from_mesh(source.data)
    source_bvh = test_context.addon.utils.experimental_pipe_chamfer_utils.BVHTree.FromBMesh(bm)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    hidden_score = utils._strand_endpoint_containment_score(
        [{"endpoint_samples": [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)]}],
        source_bvh,
        0.1,
    )
    exposed_score = utils._strand_endpoint_containment_score(
        [{"endpoint_samples": [(1.2, 0.0, 0.0), (0.0, -1.2, 0.0)]}],
        source_bvh,
        0.1,
    )
    bm.free()
    ensure(
        hidden_score[0] == 0 and exposed_score[0] == 2,
        f"Closed Mesh ray parity classified endpoint caps incorrectly: {hidden_score}, {exposed_score}",
    )
    result.add_detail(
        f"closed Mesh BVH hidden={hidden_score}, exposed={exposed_score}"
    )


# 验证 Rail diagnostic 与正式 GN Preview 使用同一 FeatureGraph 合同。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_rail_feature_graph_contract_alignment(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNRailGraphAlignment")
    source = make_ordered_sharp_cube("GNRailGraphAlignmentSource", collection, 0)
    utils = test_context.addon.utils.experimental_pipe_chamfer_utils
    preview_stats = utils._base_stats(source, 0.05, 4, 35.0, 3.0, 1.5, "PREVIEW")
    preview_groups = utils._build_preview_feature_graph(source, 0.05, preview_stats)
    rail_stats = utils.build_pipe_chamfer(
        source_object=source,
        radius=0.05,
        pipe_resolution=4,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="FEATURE_GRAPH",
        keep_debug_objects=False,
        feature_graph_contract="GN_PREVIEW_V1",
    )

    def signature(groups):
        def canonical_edges(group):
            edge_ids = tuple(group["edge_indices"])
            if not group["is_cyclic"]:
                return min(edge_ids, tuple(reversed(edge_ids)))
            rotations = [
                edge_ids[offset:] + edge_ids[:offset]
                for offset in range(len(edge_ids))
            ]
            reversed_ids = tuple(reversed(edge_ids))
            rotations.extend(
                reversed_ids[offset:] + reversed_ids[:offset]
                for offset in range(len(reversed_ids))
            )
            return min(rotations)

        return sorted(
            (canonical_edges(group), bool(group["is_cyclic"]))
            for group in groups
        )

    ensure(
        rail_stats["feature_graph_contract"] == "GN_PREVIEW_V1"
        and signature(preview_groups) == signature(rail_stats["feature_groups"]),
        "Rail diagnostic FeatureGraph diverged from formal GN Preview",
    )
    result.add_detail(
        f"aligned FeatureGraph groups={len(preview_groups)}, contract=GN_PREVIEW_V1"
    )

# 验证多处等角 90° junction 会全局组成稳定的共面 ]/U strands。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_operator_builds_coplanar_bracket_strands(
    test_context: TestContext,
    result: TestCaseResult,
):
    signatures = []
    edge_sets = []
    artifact_records = []
    for variant in (0, 1):
        collection = make_collection(f"GNCoplanarBracket{variant}")
        source = make_ordered_sharp_cube(
            f"GNCoplanarBracketSource{variant}",
            collection,
            variant,
        )
        operator_result, modifier = run_feature_chamfer_gn(
            source,
            action="PREVIEW",
            radius=0.05,
        )
        ensure(
            operator_result == {"FINISHED"} and modifier is not None,
            f"Coplanar bracket Preview failed for variant {variant}",
        )
        curve_source = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
        signature = curve_geometry_signature(curve_source, variant)
        ensure(
            len(signature) == 4 and all(len(points) == 4 for points in signature),
            f"Cube did not decompose into four 4-point bracket strands: {signature}",
        )
        for points in signature:
            axes = []
            for start, end in zip(points, points[1:]):
                changed_axes = [
                    axis
                    for axis in range(3)
                    if abs(end[axis] - start[axis]) > 1.0e-6
                ]
                ensure(len(changed_axes) == 1, f"Bracket segment is not axis aligned: {points}")
                axes.append(changed_axes[0])
            ensure(
                len(set(axes)) == 2 and axes[0] == axes[2],
                f"Strand changed bend plane instead of forming a coplanar bracket: {points}",
            )
            constant_axis = next(axis for axis in range(3) if axis not in set(axes))
            ensure(
                max(point[constant_axis] for point in points)
                - min(point[constant_axis] for point in points)
                <= 1.0e-6,
                f"Bracket points are not coplanar: {points}",
            )
        signatures.append(signature)
        edge_sets.append(
            {
                tuple(sorted((points[index], points[index + 1])))
                for points in signature
                for index in range(len(points) - 1)
            }
        )
        artifact_records.append(
            {
                "variant": variant,
                "curve_spline_point_counts": [len(points) for points in signature],
                "signature": signature,
            }
        )
        run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(
        all(len(signature) == 4 and all(len(points) == 4 for points in signature) for signature in signatures),
        "Coplanar bracket output changed source Sharp Edge geometry",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_gn_coplanar_bracket_operator.json"
    artifact_path.write_text(
        json.dumps(
            {
                "operator": "hst.feature_chamfer_gn",
                "action": "PREVIEW",
                "fixture": "sharp cube with reordered topology",
                "variants": artifact_records,
                "orientation_variants_preserve_coplanar_bracket_contract": all(
                    len(signature) == 4
                    and all(len(points) == 4 for points in signature)
                    for signature in signatures
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.add_detail(f"Four coplanar bracket strands; artifact={artifact_path}")

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


# 验证缺失或损坏的 plan payload 会让 Preview stale，不能绕过 Finalize 对照。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_rejects_invalid_plan_payload_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNInvalidPlan")
    plan_module = test_context.addon.utils.feature_chamfer_plan_utils
    for suffix, corrupt_payload in (
        ("Missing", None),
        ("Corrupt", "{not-json"),
    ):
        source = make_test_mesh(f"GNInvalidPlan{suffix}", collection)
        mark_all_edges_sharp(source)
        preview_result, modifier = run_feature_chamfer_gn(source)
        ensure(preview_result == {"FINISHED"}, f"{suffix} plan Preview failed")
        if corrupt_payload is None:
            del modifier[plan_module.PLAN_PROPERTY]
        else:
            modifier[plan_module.PLAN_PROPERTY] = corrupt_payload
        finalize_result, kept_modifier = run_feature_chamfer_gn(
            source,
            action="FINALIZE",
        )
        ensure(finalize_result == {"CANCELLED"}, f"{suffix} plan was not rejected")
        ensure(kept_modifier == modifier, f"{suffix} rejection removed Preview")
        ensure(
            source.get(test_context.const.FEATURE_CHAMFER_GN_STATE_TAG)
            == "PREVIEW_STALE",
            f"{suffix} invalid plan did not mark Preview stale",
        )
    result.add_detail("missing/corrupt plan payloads fail closed before Finalize")


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


# 验证重做 Preview 会重建 Curve source，Radius 使用新值且不留下 orphan。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_preview_radius_rebuilds_owned_curve_without_orphans(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNRadiusCurveLifecycle")
    source = make_degree_three_feature_junction("GNRadiusCurveLifecycleSource", collection)
    source_hash = _mesh_fingerprint(source)
    first_result, first_modifier = run_feature_chamfer_gn(source, radius=0.03)
    ensure(first_result == {"FINISHED"}, "Initial Curve Preview failed")
    first_curve = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(first_curve is not None, "Initial Preview has no owned Curve")
    first_curve_pointer = first_curve.as_pointer()
    second_result, second_modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.09,
    )
    ensure(second_result == {"FINISHED"}, "Radius redo failed")
    second_curve = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(second_curve is not None, "Radius redo lost owned Curve")
    ensure(second_modifier == first_modifier, "Radius redo stacked a Preview modifier")
    ensure(
        all(obj.as_pointer() != first_curve_pointer for obj in bpy.data.objects),
        "Radius redo left the old Curve Object",
    )
    ensure(
        sum(
            1
            for group in bpy.data.node_groups
            if group.get("hst_feature_chamfer_preview_backend")
            == "PYTHON_CURVE_PIPE"
        )
        == 1,
        "Radius redo left an old Preview wrapper Node Group",
    )
    ensure(
        sum(
            1
            for curve in bpy.data.curves
            if curve.name.startswith(source.name + "_FeatureChamferPreviewCurve")
        )
        == 1,
        "Radius redo left an old Curve datablock",
    )
    ensure(
        abs(
            second_modifier[
                node_input_identifier(second_modifier.node_group, "Radius")
            ]
            - 0.09
        )
        < 1.0e-6,
        "Radius redo did not update the Preview input",
    )
    ensure(_mesh_fingerprint(source) == source_hash, "Radius redo changed source Mesh")
    result.add_detail(f"curve={second_curve.name}, radius=0.09")


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
    ensure(
        test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
        is None,
        "Cancel Preview left its owned Curve source",
    )


# 验证 source 重命名后 owned Preview 仍可识别并取消。
# test_context/result: 测试上下文与结果记录器。
def test_gn_preview_owner_survives_source_rename(test_context: TestContext, result: TestCaseResult):
    collection = make_collection("GNRename")
    source = make_test_mesh("GNRenameSource", collection)
    mark_all_edges_sharp(source)
    preview_result, modifier = run_feature_chamfer_gn(source)
    ensure(preview_result == {"FINISHED"} and modifier is not None, "Preview setup failed")
    curve_object = test_context.addon.utils.feature_chamfer_gn_utils.owned_preview_curve(source)
    ensure(curve_object is not None, "Preview setup did not create owned Curve")
    curve_pointer = curve_object.as_pointer()
    curve_data_pointer = curve_object.data.as_pointer()
    source.name = "GNRenamedSource"
    cancel_result, modifier_after_cancel = run_feature_chamfer_gn(source, action="CANCEL_PREVIEW")
    ensure(cancel_result == {"FINISHED"}, "Renamed source could not cancel Preview")
    ensure(modifier_after_cancel is None, "Renamed source left owned Preview")
    ensure(
        all(obj.as_pointer() != curve_pointer for obj in bpy.data.objects),
        "Renamed source left owned Curve Object",
    )
    ensure(
        all(curve.as_pointer() != curve_data_pointer for curve in bpy.data.curves),
        "Renamed source left owned Curve datablock",
    )


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


# 验证复杂 END_CAP/JUNCTION 在结构化 rails/ports 未实现前显式 fail-closed。
# test_context/result: 测试上下文与结果记录器。
def test_gn_patch_complex_region_fails_closed(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("GNComplexPatchDonor")
    donor_object = make_test_mesh("GNComplexPatchDonorSource", collection)
    donor_mesh = donor_object.data
    patch_utils = test_context.addon.utils.feature_chamfer_patch_utils
    try:
        patch_utils.patch_boolean_result(
            open_mesh=donor_mesh,
            regions=[{"class": "JUNCTION"}],
            components=[],
            donor_mesh=donor_mesh,
            groove_face_indices=[0],
        )
    except patch_utils.FeatureChamferPatchError as error:
        ensure(
            error.error_code == "structured_junction_not_implemented",
            f"Complex Patch failed with the wrong error: {error.error_code}",
        )
        ensure(
            error.diagnostics.get("strategy") == "FAIL_CLOSED",
            f"Complex Patch diagnostic did not record fail-closed: {error.diagnostics}",
        )
        ensure(
            len(donor_mesh.polygons) == 6,
            "Complex Patch fail-closed path changed donor topology",
        )
        result.add_detail(
            f"error={error.error_code}, strategy={error.diagnostics['strategy']}"
        )
        return
    raise TestFailure("Complex JUNCTION incorrectly returned a patched Mesh")


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


# 从真实 mixed fixture 的目标 Operator 复现并守住下方右侧 terminal connectivity。
# test_context/result: 已注册 add-on 的测试上下文与当前测试结果。
def test_gn_finalize_mixed_fixture_terminal_topology_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    load_fixture_blend("feature-chamfer-topology-defect-mixed.blend")
    source = bpy.data.objects.get("Extruded.002")
    ensure(source is not None, "Mixed fixture source is missing")
    source_hash = _mesh_fingerprint(source)
    preview_result, _ = run_feature_chamfer_gn(source, radius=0.01)
    ensure(preview_result == {"FINISHED"}, f"Mixed fixture Preview failed: {preview_result}")
    finalize_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    ensure(finalize_result == {"FINISHED"}, f"Mixed fixture Finalize failed: {finalize_result}")
    output = bpy.context.active_object
    ensure(output is not None and output is not source, "Mixed fixture created no separate output")
    ensure(_mesh_fingerprint(source) == source_hash, "Mixed fixture Finalize changed source")

    bm = bmesh.new()
    bm.from_mesh(output.data)
    boundary_count = sum(len(edge.link_faces) == 1 for edge in bm.edges)
    non_manifold_count = sum(len(edge.link_faces) != 2 for edge in bm.edges)
    zero_area_count = sum(face.calc_area() <= 1.0e-12 for face in bm.faces)
    focus_point = Vector((0.613128722, 0.204837114, 0.062097311))
    focus_vertex = min(bm.verts, key=lambda vertex: (vertex.co - focus_point).length_squared)
    ensure(
        (focus_vertex.co - focus_point).length <= 1.0e-6,
        f"Mixed fixture focus terminal moved: {tuple(focus_vertex.co)}",
    )
    long_neighbors = [
        edge.other_vert(focus_vertex)
        for edge in focus_vertex.link_edges
        if (edge.other_vert(focus_vertex).co - focus_vertex.co).length > 1.0
    ]
    ensure(
        len(long_neighbors) == 1,
        "Mixed fixture terminal retained an extra diagonal/duplicate long connection",
    )
    long_direction = (long_neighbors[0].co - focus_vertex.co).normalized()
    ensure(
        abs(long_direction.dot(Vector((0.0, 0.0, 1.0)))) >= 0.999,
        f"Mixed fixture terminal long connection is not vertical: {tuple(long_direction)}",
    )
    bm.free()
    ensure(
        boundary_count == 0 and non_manifold_count == 0 and zero_area_count == 0,
        "Mixed fixture output is not a clean closed Mesh",
    )
    chamfer_attribute = output.data.attributes.get("hst_feature_chamfer_face")
    ensure(chamfer_attribute is not None, "Mixed fixture output has no Chamfer Face attribute")
    result.add_detail("Mixed fixture Operator removed the extra long terminal connection")


# 验证能力不足的复杂 fixture 会安全拒绝 FINALIZE，不把失败伪装成产品成功。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_unsupported_complex_fixture_fails_closed(test_context: TestContext, result: TestCaseResult):
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
    ensure(
        finalize_result == {"CANCELLED"},
        f"Complex real fixture must fail-closed before structured junction support: {finalize_result}",
    )
    ensure(bpy.context.active_object is source, "Fail-closed Finalize changed active Object")
    ensure(_mesh_fingerprint(source) == source_hash, "Fail-closed Finalize changed source")
    ensure(modifier.show_viewport, "Fail-closed Finalize disabled Preview")
    ensure(
        test_context.addon.utils.feature_chamfer_gn_utils.preview_state(source)
        == "PREVIEW_VALID",
        "Fail-closed Finalize changed Preview state",
    )
    ensure(
        not any(
            obj.get(test_context.const.FEATURE_CHAMFER_SOURCE_OBJECT_TAG) == source.name
            for obj in bpy.data.objects
            if obj is not source
        ),
        "Fail-closed Finalize left a pseudo output",
    )
    result.add_detail("Complex fixture stayed in PREVIEW_VALID with no pseudo Finalize output")


# 验证失败后的重复 FINALIZE 仍保留原家族，而非退化为 plan mismatch。
# test_context/result: 测试上下文与结果记录器。
def test_gn_finalize_retry_preserves_plan_diagnostic_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    load_fixture_blend("feature-chamfer-gn-junction-safe.blend")
    source = bpy.data.objects["Extruded.002"]
    for modifier in list(source.modifiers):
        source.modifiers.remove(modifier)
    preview_result, modifier = run_feature_chamfer_gn(source, radius=0.03)
    ensure(preview_result == {"FINISHED"}, "Retry diagnostic Preview failed")
    first_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    first_plan = test_context.addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        modifier
    )
    second_result, _ = run_feature_chamfer_gn(source, action="FINALIZE")
    second_plan = test_context.addon.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        modifier
    )
    ensure(
        first_result == {"CANCELLED"} and second_result == {"CANCELLED"},
        "Repeated unsupported Finalize did not fail closed",
    )
    ensure(
        first_plan.unsupported_regions == second_plan.unsupported_regions
        and all(
            region.reason_code != "chamfer_plan_mismatch"
            for region in second_plan.unsupported_regions
        ),
        f"Repeated Finalize replaced the stable diagnostic family: {second_plan}",
    )
    result.add_detail("repeated Finalize preserved the original UnsupportedRegion family")


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


# 验证 batched overlap coloring 完整、batch 内无冲突，并拒绝非法 graph。
# test_context/result: 已加载 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_overlap_coloring_contract(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_batched_finalize_utils
    pipe_ids = (10, 20, 30, 40)
    overlap_pairs = ((10, 20), (20, 30), (30, 40))
    batches = module.color_pipe_overlap_graph(pipe_ids, overlap_pairs)
    ensure(
        sorted(pipe_id for batch in batches for pipe_id in batch) == list(pipe_ids),
        f"Batched coloring did not consume every Pipe exactly once: {batches}",
    )
    ensure(
        all(
            tuple(sorted((pipe_id_a, pipe_id_b))) not in overlap_pairs
            for batch in batches
            for offset, pipe_id_a in enumerate(batch)
            for pipe_id_b in batch[offset + 1 :]
        ),
        f"Batched coloring retained an internal overlap: {batches}",
    )
    ensure(
        batches
        == module.color_pipe_overlap_graph(
            tuple(reversed(pipe_ids)),
            tuple(reversed(overlap_pairs)),
        ),
        "Batched coloring depends on input order",
    )
    invalid_graphs = (
        ((10, 10),),
        ((10, 99),),
    )
    for invalid_pairs in invalid_graphs:
        try:
            module.color_pipe_overlap_graph(pipe_ids, invalid_pairs)
        except ValueError:
            continue
        raise TestFailure(f"Batched coloring accepted invalid graph: {invalid_pairs}")
    result.add_detail(f"color_batches={batches}")


# 验证 short component setback 只接受贴近唯一 Plan/overlap 边界的单侧单 Edge，并原子消费 ledger。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_short_component_setback_contract(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_batched_finalize_utils
    strand = SimpleNamespace(
        ordered_vertex_keys=("0,0,0#v0", "1,0,0#v1"),
        cyclic=False,
        start_port_id="port:start",
        end_port_id="port:end",
    )
    atom = {
        "atom_id": "atom:regular",
        "span_id": 3,
        "patch_pair": [0, 5],
        "convexity": 1,
        "u_interval": [0.0, 0.40],
    }
    unresolved = {
        "reason": "NO_PERFECT_MATCHING",
        "solution_count_capped": 0,
        "correspondence_id": "strip:strand:test:0:5",
        "atom_id": atom["atom_id"],
        "component_id": "atom:regular:0",
        "component_u_interval": [0.385, 0.39],
        "left_runs": [],
        "right_runs": [
            {
                "edge_ids": ["edge:short"],
                "coordinates": [(0.385, 0.0, 0.0), (0.39, 0.0, 0.0)],
                "u_interval": [0.385, 0.39],
            }
        ],
    }
    forbidden_intervals = ((0.40, 0.60),)
    proof = module._short_component_setback_proof(
        unresolved,
        atom,
        strand,
        forbidden_intervals,
        0.01,
    )
    ensure(
        proof is not None
        and proof["proof_version"] == "SHORT_COMPONENT_SETBACK_V1"
        and proof["boundary_type"] == "OVERLAP_FORBIDDEN"
        and proof["span_id"] == atom["span_id"],
        f"Valid short setback proof was rejected: {proof}",
    )
    correspondence = SimpleNamespace(
        correspondence_id=unresolved["correspondence_id"],
        owner_strand_id="strand:test",
        owner_surface_pair=(0, 5),
    )
    ledger = {
        "edge:short": {
            "edge_id": "edge:short",
            "classification": "UNCLASSIFIED",
            "consumer_id": None,
            "pipe_id": 7,
            "strand_id": "strand:test",
            "source_patch_id": 5,
            "rail_id": "rail:strand:test:patch:5",
        }
    }
    port = module._commit_short_component_setback(
        proof,
        correspondence,
        7,
        ledger,
    )
    ensure(
        ledger["edge:short"]["classification"] == "SETBACK_RESERVED"
        and ledger["edge:short"]["consumer_id"] == port["port_id"]
        and port["ordered_edge_ids"] == ["edge:short"]
        and port["boundary_id"] == proof["boundary_id"],
        f"Short setback ledger commit is incomplete: {port}",
    )
    rejected_variants = (
        {**unresolved, "left_runs": unresolved["right_runs"]},
        {
            **unresolved,
            "component_u_interval": [0.10, 0.105],
            "right_runs": [
                {
                    **unresolved["right_runs"][0],
                    "u_interval": [0.10, 0.105],
                }
            ],
        },
        {
            **unresolved,
            "component_u_interval": [0.30, 0.39],
            "right_runs": [
                {
                    **unresolved["right_runs"][0],
                    "u_interval": [0.30, 0.39],
                }
            ],
        },
    )
    ensure(
        all(
            module._short_component_setback_proof(
                variant,
                atom,
                strand,
                forbidden_intervals,
                0.01,
            )
            is None
            for variant in rejected_variants
        ),
        "Short setback accepted a two-sided, atom-interior, or oversized component",
    )
    second_commit_rejected = False
    try:
        module._commit_short_component_setback(
            proof,
            correspondence,
            7,
            ledger,
        )
    except module.BatchedChamferError as error:
        second_commit_rejected = error.error_code == "REGULAR_CORE_LEDGER_CONFLICT"
    ensure(
        second_commit_rejected,
        "Short setback allowed the same Boundary Edge to be consumed twice",
    )
    result.add_detail("single-edge proof accepted; unsafe variants rejected")


# 验证 open Boundary chain 的 forbidden partition 保留真实终点，不把起点复制到末尾。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_open_chain_partition_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_batched_finalize_utils
    chain = {
        "edge_ids": ["edge:0", "edge:1"],
        "coordinates": [(0.0, 0.0, 0.0), (0.4, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "is_cyclic": False,
    }
    strand = SimpleNamespace(
        ordered_vertex_keys=("0,0,0#v0", "1,0,0#v1"),
        cyclic=False,
    )
    partition = module._split_chain_by_forbidden_intervals(
        chain,
        strand,
        (),
    )
    ensure(
        partition["setback"] == []
        and len(partition["regular"]) == 1
        and partition["regular"][0]["edge_ids"] == chain["edge_ids"]
        and partition["regular"][0]["coordinates"] == chain["coordinates"]
        and all(
            abs(actual - expected) <= 1.0e-7
            for actual, expected in zip(
                partition["regular"][0]["u_values"],
                (0.0, 0.4, 1.0),
            )
        ),
        f"Open chain partition lost endpoint provenance: {partition}",
    )
    result.add_detail("open chain partition preserved both real endpoints")


# 验证 cyclic chain 反向时 Edge IDs 与反向 coordinates 仍逐段对应。
# test_context/result: 已加载的 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_cyclic_reverse_provenance_regression(
    test_context: TestContext,
    result: TestCaseResult,
):
    module = test_context.addon.utils.feature_chamfer_batched_finalize_utils
    chain = {
        "edge_ids": ["edge:ab", "edge:bc", "edge:ca"],
        "coordinates": [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)],
        "is_cyclic": True,
    }
    strand = SimpleNamespace(
        ordered_vertex_keys=(
            "0,0,0#v0",
            "1,0,0#v1",
            "0,1,0#v2",
        ),
        cyclic=True,
    )
    oriented, _ = module._chain_strand_parameters(chain, strand)
    ensure(
        oriented["coordinates"] == list(reversed(chain["coordinates"]))
        and oriented["edge_ids"] == ["edge:bc", "edge:ab", "edge:ca"],
        f"Cyclic reverse broke Edge/coordinate provenance: {oriented}",
    )
    result.add_detail("cyclic reverse preserved directed Edge provenance")


# 从真实 PREVIEW Operator 验证 batched backend 只消费同一 ChamferPlan 与正式 Pipe builder。
# test_context/result: 已加载 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_preview_pipe_contract_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BatchedPreviewPipeContract")
    source = make_test_mesh("BatchedPreviewPipeContractSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    source_hash = mesh_topology_hash(source)
    select_objects(source, [source])
    preview_result, preview_modifier = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(preview_result == {"FINISHED"}, "Batched contract Preview failed")
    plan_module = test_context.addon.utils.feature_chamfer_plan_utils
    preview_plan = plan_module.read_chamfer_plan(preview_modifier)
    preview_utils = test_context.addon.utils.feature_chamfer_gn_utils
    owned_curve = preview_utils.owned_preview_curve(source)
    ensure(owned_curve is not None, "Batched contract Preview did not retain owned Curve")
    contract = json.loads(
        owned_curve[test_context.addon.const.FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG]
    )
    ensure(
        contract["contract"] == "GN_PREVIEW_PIPE_V1"
        and contract["plan_id"] == preview_plan.plan_id
        and contract["source_fingerprint"] == preview_utils.source_fingerprint(source)
        and abs(float(contract["radius"]) - float(preview_plan.radius)) <= 1.0e-10,
        f"Persisted Preview Pipe contract diverged from ChamferPlan: {contract}",
    )
    ensure(
        preview_pipe_contract_geometry_signature(contract["pipes"])
        == owned_preview_curve_contract_signature(owned_curve),
        "Persisted Preview Pipe contract does not describe the actual owned Curve",
    )
    preview_parameters = (
        preview_utils.live_preview_parameters(
            preview_modifier
        )
    )
    module = test_context.addon.utils.feature_chamfer_batched_finalize_utils
    ensure(
        not hasattr(module, "_build_preview_feature_graph"),
        "Batched backend still imports secondary Preview grouping",
    )
    probe = module.build_batched_feature_chamfer(
        source,
        preview_plan,
        preview_parameters,
        module.DEBUG_PHASE_B,
    )
    diagnostics = probe.to_dict()
    ensure(
        probe.plan_id == preview_plan.plan_id
        and probe.radius == preview_parameters["radius"],
        f"Batched backend diverged from Preview inputs: {diagnostics}",
    )
    ensure(
        len(probe.pipe_specs) == len(preview_plan.feature_strands)
        and all(spec.mesh_fingerprint for spec in probe.pipe_specs),
        f"Batched backend did not freeze every Preview Pipe: {diagnostics}",
    )
    ensure(
        all(spec.face_count > 0 and spec.vertex_count > 0 for spec in probe.pipe_specs),
        f"Batched Preview Pipe geometry is empty: {diagnostics}",
    )
    ensure(
        probe.topology_diagnostics["all_pipes_colored_once"]
        and probe.topology_diagnostics["batch_internal_overlap_count"] == 0
        and probe.topology_diagnostics["source_unchanged"],
        f"Batched graph contract failed: {diagnostics}",
    )
    ensure(
        probe.topology_diagnostics.get("real_cut_probe") is True
        and probe.topology_diagnostics.get("cut_strategy") == "INDEPENDENT_STAGING"
        and probe.topology_diagnostics.get("batch_order_invariant") is True
        and probe.topology_diagnostics.get("forward_cut_signature")
        == probe.topology_diagnostics.get("reverse_cut_signature")
        and probe.topology_diagnostics.get("forward_cut_signature")
        != probe.batch_order_invariance_fingerprint
        and probe.topology_diagnostics.get("forward_cut_batch_count")
        == len(probe.color_batches)
        and probe.topology_diagnostics.get("reverse_cut_batch_count")
        == len(probe.color_batches),
        f"Phase B did not prove real forward/reverse Cut invariance: {diagnostics}",
    )
    ensure(
        mesh_topology_hash(source) == source_hash,
        "Batched Preview Pipe probe changed source Mesh",
    )
    ensure(
        not [
            obj
            for obj in bpy.data.objects
            if obj.name.startswith(f"{source.name}_FeatureChamferBatchedProbe")
            or obj.name.startswith(f"{source.name}_Pipe_")
        ],
        "Batched Preview Pipe probe left debug Objects",
    )
    artifact_path = ARTIFACT_DIR / "feature_chamfer_batched_phase_ab_contract.json"
    artifact_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.add_detail(
        f"plan={probe.plan_id}, pipes={len(probe.pipe_specs)}, "
        f"batches={len(probe.color_batches)}, artifact={artifact_path}"
    )


# 验证隐藏实验 Adapter 从当前有效 PREVIEW 读取 plan/参数并留下机器结果。
# test_context/result: 已加载 add-on 测试上下文与结果记录器。
def test_feature_chamfer_batched_adapter_smoke(
    test_context: TestContext,
    result: TestCaseResult,
):
    collection = make_collection("BatchedAdapter")
    source = make_test_mesh("BatchedAdapterSource", collection)
    mark_edge_indices_sharp(source, cube_top_loop_edge_indices(source))
    source_hash = mesh_topology_hash(source)
    select_objects(source, [source])
    preview_result, _ = run_feature_chamfer_gn(
        source,
        action="PREVIEW",
        radius=0.05,
    )
    ensure(preview_result == {"FINISHED"}, "Batched Adapter Preview failed")
    adapter_result = bpy.ops.hst.experimental_feature_chamfer_batched_finalize(
        "INVOKE_DEFAULT",
        debug_stage="PHASE_B_BATCH_PROBE",
    )
    ensure(adapter_result == {"FINISHED"}, "Batched Adapter probe failed")
    diagnostics = json.loads(
        bpy.context.scene["hst_feature_chamfer_batched_last_result"]
    )
    ensure(
        diagnostics["backend_id"] == "BATCHED_CUT_FILL_V1"
        and diagnostics["debug_stage"] == "PHASE_B_BATCH_PROBE"
        and diagnostics["topology_diagnostics"]["all_pipes_colored_once"]
        and diagnostics["topology_diagnostics"]["batch_internal_overlap_count"] == 0,
        f"Batched Adapter result is incomplete: {diagnostics}",
    )
    topology = diagnostics["topology_diagnostics"]
    ensure(
        topology.get("real_cut_probe") is True
        and topology.get("cut_strategy") == "INDEPENDENT_STAGING"
        and topology.get("batch_order_invariant") is True
        and topology.get("forward_cut_signature")
        == topology.get("reverse_cut_signature")
        and topology.get("forward_cut_signature")
        != diagnostics.get("batch_order_invariance_fingerprint"),
        f"Batched Adapter reported metadata-only order invariance: {diagnostics}",
    )
    ensure(
        mesh_topology_hash(source) == source_hash,
        "Batched Adapter changed source Mesh",
    )
    result.add_detail(
        f"adapter={diagnostics['backend_id']}, batches={len(diagnostics['color_batches'])}"
    )


def main():
    addon_module = load_addon_module()
    addon_module.register()

    context = TestContext(addon_module)
    context.run_case(
        "feature_chamfer_batched_overlap_coloring_contract",
        test_feature_chamfer_batched_overlap_coloring_contract,
    )
    context.run_case(
        "feature_chamfer_batched_short_component_setback_contract",
        test_feature_chamfer_batched_short_component_setback_contract,
    )
    context.run_case(
        "feature_chamfer_batched_open_chain_partition_regression",
        test_feature_chamfer_batched_open_chain_partition_regression,
    )
    context.run_case(
        "feature_chamfer_batched_cyclic_reverse_provenance_regression",
        test_feature_chamfer_batched_cyclic_reverse_provenance_regression,
    )
    context.run_case(
        "feature_chamfer_batched_preview_pipe_contract_smoke",
        test_feature_chamfer_batched_preview_pipe_contract_smoke,
    )
    context.run_case(
        "feature_chamfer_batched_adapter_smoke",
        test_feature_chamfer_batched_adapter_smoke,
    )
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
    context.run_case("bake_collection_export_fbx_smoke", test_bake_collection_export_fbx_smoke)
    context.run_case("marmoset_bake_pairing_smoke", test_marmoset_bake_pairing_smoke)
    context.run_case("marmoset_bake_pairing_missing_side_regression", test_marmoset_bake_pairing_missing_side_regression)
    context.run_case("marmoset_loader_generation_smoke", test_marmoset_loader_generation_smoke)
    context.run_case("staticmeshexport_glb_smoke", test_staticmeshexport_glb_smoke)
    context.run_case("rename_bones_smoke", test_rename_bones_smoke)
    context.run_case("cleanup_ue_skm_smoke", test_cleanup_ue_skm_smoke)
    context.run_case("sharp_feature_graph_object_smoke", test_sharp_feature_graph_object_smoke)
    context.run_case(
        "pipe_chamfer_degree_three_strand_matching_regression",
        test_pipe_chamfer_degree_three_strand_matching_regression,
    )
    context.run_case("experimental_pipe_chamfer_early_failure_keeps_source_visible_regression", test_experimental_pipe_chamfer_early_failure_keeps_source_visible_regression)
    context.run_case("experimental_pipe_chamfer_pipes_no_blender_bevel_regression", test_experimental_pipe_chamfer_pipes_no_blender_bevel_regression)
    context.run_case("curve_pipe_asset_import_and_backend_smoke", test_curve_pipe_asset_import_and_backend_smoke)
    context.run_case("feature_chamfer_rail_oracle_contract_smoke", test_feature_chamfer_rail_oracle_contract_smoke)
    context.run_case(
        "feature_chamfer_rail_endpoint_core_trim_regression",
        test_feature_chamfer_rail_endpoint_core_trim_regression,
    )
    context.run_case(
        "feature_chamfer_source_surface_intrinsic_offset_regression",
        test_feature_chamfer_source_surface_intrinsic_offset_regression,
    )
    context.run_case(
        "feature_chamfer_folded_surface_walk_intrinsic_distance_regression",
        test_feature_chamfer_folded_surface_walk_intrinsic_distance_regression,
    )
    context.run_case(
        "feature_chamfer_owner_face_adjacency_walk_regression",
        test_feature_chamfer_owner_face_adjacency_walk_regression,
    )
    context.run_case(
        "feature_chamfer_regular_strip_terminal_span_guard_regression",
        test_feature_chamfer_regular_strip_terminal_span_guard_regression,
    )
    context.run_case(
        "feature_chamfer_regular_strip_zero_area_path_regression",
        test_feature_chamfer_regular_strip_zero_area_path_regression,
    )
    context.run_case(
        "feature_chamfer_regular_strip_hard_guard_path_regression",
        test_feature_chamfer_regular_strip_hard_guard_path_regression,
    )
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
    context.run_case(
        "gn_preview_operator_curve_backend_acceptance",
        test_gn_preview_operator_curve_backend_acceptance,
    )
    context.run_case(
        "gn_preview_operator_splits_acute_miter",
        test_gn_preview_operator_splits_acute_miter,
    )
    context.run_case(
        "gn_preview_operator_keeps_right_angle_miter_continuous",
        test_gn_preview_operator_keeps_right_angle_miter_continuous,
    )
    context.run_case(
        "gn_preview_operator_uses_four_sided_profile",
        test_gn_preview_operator_uses_four_sided_profile,
    )
    context.run_case(
        "gn_preview_operator_pairs_degree_four_junction_deterministically",
        test_gn_preview_operator_pairs_degree_four_junction_deterministically,
    )
    context.run_case(
        "gn_preview_operator_pairs_orthogonal_degree_three_junction",
        test_gn_preview_operator_pairs_orthogonal_degree_three_junction,
    )
    context.run_case(
        "gn_preview_operator_keeps_smooth_degree_two_ring_cyclic",
        test_gn_preview_operator_keeps_smooth_degree_two_ring_cyclic,
    )
    context.run_case(
        "gn_preview_junction_endpoint_containment_score_contract",
        test_gn_preview_junction_endpoint_containment_score_contract,
    )
    context.run_case(
        "gn_preview_junction_endpoint_containment_closed_mesh_bvh",
        test_gn_preview_junction_endpoint_containment_closed_mesh_bvh,
    )
    context.run_case(
        "gn_preview_rail_feature_graph_contract_alignment",
        test_gn_preview_rail_feature_graph_contract_alignment,
    )
    context.run_case(
        "gn_preview_operator_builds_coplanar_bracket_strands",
        test_gn_preview_operator_builds_coplanar_bracket_strands,
    )
    context.run_case(
        "gn_shared_chamfer_plan_shadow_contract_smoke",
        test_gn_shared_chamfer_plan_shadow_contract_smoke,
    )
    context.run_case(
        "gn_chamfer_plan_internal_junction_port_contract_smoke",
        test_gn_chamfer_plan_internal_junction_port_contract_smoke,
    )
    context.run_case(
        "gn_chamfer_plan_disconnected_coincident_ports_regression",
        test_gn_chamfer_plan_disconnected_coincident_ports_regression,
    )
    context.run_case(
        "gn_chamfer_plan_endpoint_patch_incidence_contract_smoke",
        test_gn_chamfer_plan_endpoint_patch_incidence_contract_smoke,
    )
    context.run_case(
        "gn_chamfer_plan_cyclic_metadata_alignment_regression",
        test_gn_chamfer_plan_cyclic_metadata_alignment_regression,
    )
    context.run_case(
        "feature_chamfer_boundary_graph_binding_contract_smoke",
        test_feature_chamfer_boundary_graph_binding_contract_smoke,
    )
    context.run_case(
        "feature_chamfer_boundary_witness_contract_smoke",
        test_feature_chamfer_boundary_witness_contract_smoke,
    )
    context.run_case(
        "feature_chamfer_boundary_witness_fail_closed_regression",
        test_feature_chamfer_boundary_witness_fail_closed_regression,
    )
    context.run_case(
        "feature_chamfer_boundary_graph_dirty_index_regression",
        test_feature_chamfer_boundary_graph_dirty_index_regression,
    )
    context.run_case(
        "feature_chamfer_boundary_graph_duplicate_input_regression",
        test_feature_chamfer_boundary_graph_duplicate_input_regression,
    )
    context.run_case(
        "feature_chamfer_authoritative_boundary_binding_contract_smoke",
        test_feature_chamfer_authoritative_boundary_binding_contract_smoke,
    )
    context.run_case(
        "feature_chamfer_open_port_anchor_binding_contract_smoke",
        test_feature_chamfer_open_port_anchor_binding_contract_smoke,
    )
    context.run_case(
        "feature_chamfer_open_port_anchor_binding_fail_closed_regression",
        test_feature_chamfer_open_port_anchor_binding_fail_closed_regression,
    )
    context.run_case(
        "feature_chamfer_authoritative_boundary_binding_fail_closed_regression",
        test_feature_chamfer_authoritative_boundary_binding_fail_closed_regression,
    )
    context.run_case(
        "feature_chamfer_boolean_component_owner_producer_smoke",
        test_feature_chamfer_boolean_component_owner_producer_smoke,
    )
    context.run_case(
        "feature_chamfer_boolean_boundary_witness_producer_smoke",
        test_feature_chamfer_boolean_boundary_witness_producer_smoke,
    )
    context.run_case(
        "feature_chamfer_exact_boolean_intersecting_edges_capability_smoke",
        test_feature_chamfer_exact_boolean_intersecting_edges_capability_smoke,
    )
    context.run_case(
        "feature_chamfer_exact_boolean_intersecting_edges_evaluated_smoke",
        test_feature_chamfer_exact_boolean_intersecting_edges_evaluated_smoke,
    )
    context.run_case(
        "feature_chamfer_exact_boolean_witness_chain_regression",
        test_feature_chamfer_exact_boolean_witness_chain_regression,
    )
    context.run_case(
        "feature_chamfer_open_endpoint_token_producer_smoke",
        test_feature_chamfer_open_endpoint_token_producer_smoke,
    )
    context.run_case(
        "feature_chamfer_pipe_boundary_witness_registry_smoke",
        test_feature_chamfer_pipe_boundary_witness_registry_smoke,
    )
    context.run_case(
        "feature_chamfer_production_sequential_boolean_witness_probe",
        test_feature_chamfer_production_sequential_boolean_witness_probe,
    )
    context.run_case(
        "feature_chamfer_collection_boolean_input_edge_witness_probe",
        test_feature_chamfer_collection_boolean_input_edge_witness_probe,
    )
    context.run_case(
        "feature_chamfer_multi_input_boolean_witness_probe",
        test_feature_chamfer_multi_input_boolean_witness_probe,
    )
    context.run_case(
        "feature_chamfer_multi_input_boolean_real_target_matrix_probe",
        test_feature_chamfer_multi_input_boolean_real_target_matrix_probe,
    )
    context.run_case(
        "feature_chamfer_intersecting_endpoint_provenance_smoke",
        test_feature_chamfer_intersecting_endpoint_provenance_smoke,
    )
    context.run_case("gn_finalize_rejects_stale_preview", test_gn_finalize_rejects_stale_preview)
    context.run_case(
        "gn_finalize_rejects_invalid_plan_payload_regression",
        test_gn_finalize_rejects_invalid_plan_payload_regression,
    )
    context.run_case("gn_preview_modifier_parameter_change_marks_stale", test_gn_preview_modifier_parameter_change_marks_stale)
    context.run_case(
        "gn_preview_radius_rebuilds_owned_curve_without_orphans",
        test_gn_preview_radius_rebuilds_owned_curve_without_orphans,
    )
    context.run_case("gn_cancel_stale_preview_without_sharp_edges", test_gn_cancel_stale_preview_without_sharp_edges)
    context.run_case("gn_preview_owner_survives_source_rename", test_gn_preview_owner_survives_source_rename)
    context.run_case(
        "gn_patch_complex_region_fails_closed",
        test_gn_patch_complex_region_fails_closed,
    )
    context.run_case("legacy_feature_chamfer_uses_patch_adapter", test_legacy_feature_chamfer_uses_patch_adapter)
    context.run_case("gn_finalize_creates_closed_output", test_gn_finalize_creates_closed_output)
    context.run_case(
        "gn_finalize_mixed_fixture_terminal_topology_regression",
        test_gn_finalize_mixed_fixture_terminal_topology_regression,
    )

    context.run_case(
        "gn_finalize_unsupported_complex_fixture_fails_closed",
        test_gn_finalize_unsupported_complex_fixture_fails_closed,
    )
    context.run_case(
        "gn_finalize_retry_preserves_plan_diagnostic_regression",
        test_gn_finalize_retry_preserves_plan_diagnostic_regression,
    )
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
