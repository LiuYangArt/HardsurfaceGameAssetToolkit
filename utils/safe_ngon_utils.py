# -*- coding: utf-8 -*-
"""CAD Mesh 的 Safe Ngon 拓扑修复与法线参考生命周期。"""

import math
import random

import bpy
import bmesh
import mathutils
from mathutils import Vector


# 本模块的拓扑算法迁移自 Kushiro 的 Safe Ngon（GPL-2.0-or-later）。
# 来源：https://github.com/LiuYangArt/blender_safe_ngon_fork
# 本项目修改：移除 Operator/UI/context 依赖，改为显式 BMesh helper 与 CAD pipeline。


class _CutPoint:
    """记录候选切点坐标以及最终创建的 BMVert。"""

    def __init__(self, coordinate: Vector):
        self.coordinate = coordinate
        self.vertex = None


class MeshNormalSnapshot:
    """保存拓扑修改前的 Mesh，并在结束时恢复 custom split normals。"""

    def __init__(self, context: bpy.types.Context, obj: bpy.types.Object):
        self.context = context
        self.obj = obj
        self.source_mesh = None
        self.source_obj = None
        self.modifier = None
        self.has_custom_normals = False
        self.mode = obj.mode
        self.active = context.view_layer.objects.active
        self.selected = list(context.selected_objects)

    # 创建独立的临时 Object/Mesh；context 为当前 Blender Context，obj 为目标 Mesh Object。
    def __enter__(self):
        try:
            self.source_mesh = self.obj.data.copy()
            self.source_mesh.name = f"__HST_SafeNgon_SourceMesh_{self.obj.name}"
            self.has_custom_normals = self.source_mesh.has_custom_normals
            self.source_obj = bpy.data.objects.new(
                f"__HST_SafeNgon_Source_{self.obj.name}", self.source_mesh
            )
            self.source_obj.matrix_world = self.obj.matrix_world.copy()
            self.context.scene.collection.objects.link(self.source_obj)
            self.source_obj.hide_render = True
            self.source_obj.hide_set(True)
            self.context.view_layer.update()
        except Exception:
            self.cleanup()
            raise
        return self

    # 从修改前 source 传回 custom split normals；mapping 为 Data Transfer 的 Loop mapping。
    def transfer_custom_normals(self, mapping: str = "POLYINTERP_LNORPROJ") -> bool:
        if not self.has_custom_normals:
            return False

        if self.obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected_obj in list(self.context.selected_objects):
            selected_obj.select_set(False)
        self.obj.hide_set(False)
        self.obj.select_set(True)
        self.context.view_layer.objects.active = self.obj

        if not self.obj.data.has_custom_normals:
            self.obj.data.attributes.new("custom_normal", "FLOAT_VECTOR", "CORNER")
        self.modifier = self.obj.modifiers.new("__HST_SafeNgon_NormalTransfer", "DATA_TRANSFER")
        self.modifier.object = self.source_obj
        self.modifier.use_object_transform = True
        self.modifier.use_loop_data = True
        self.modifier.data_types_loops = {"CUSTOM_NORMAL"}
        self.modifier.loop_mapping = mapping
        self.modifier.mix_mode = "REPLACE"
        self.modifier.mix_factor = 1.0
        self.context.view_layer.update()
        bpy.ops.object.modifier_apply(modifier=self.modifier.name)
        self.modifier = None
        return True

    # 删除临时 Modifier、Object 与 Mesh；可重复调用。
    def cleanup(self) -> None:
        if self.modifier and self.modifier.name in self.obj.modifiers:
            self.obj.modifiers.remove(self.modifier)
        self.modifier = None
        if self.source_obj and self.source_obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.source_obj, do_unlink=True)
        self.source_obj = None
        if self.source_mesh and self.source_mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.source_mesh)
        self.source_mesh = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()
        for selected_obj in list(self.context.selected_objects):
            selected_obj.select_set(False)
        for selected_obj in self.selected:
            if selected_obj.name in self.context.view_layer.objects:
                selected_obj.select_set(True)
        if self.active and self.active.name in self.context.view_layer.objects:
            self.context.view_layer.objects.active = self.active
        if self.mode == "EDIT" and self.obj.mode != "EDIT":
            self.context.view_layer.objects.active = self.obj
            self.obj.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")


# 判断两条向量是否在给定角度内平行；first/second 为方向，angle_degrees 为角度阈值。
def _is_parallel(first: Vector, second: Vector, angle_degrees: float) -> bool:
    if first.length == 0.0 or second.length == 0.0:
        return False
    angle = math.degrees(second.angle(first))
    return angle < angle_degrees or angle > 180.0 - angle_degrees


# 判断 point 是否位于 segment_start 与 segment_end 的线段上；tolerance 为距离容差。
def _is_inside_segment(point: Vector, segment_start: Vector, segment_end: Vector, tolerance: float) -> bool:
    segment_length = (segment_end - segment_start).length
    return abs((point - segment_start).length + (point - segment_end).length - segment_length) < tolerance


# 查找两条三维直线的单一交点；无唯一交点时返回 None。
def _find_line_intersection(first_start, first_end, second_start, second_end):
    result = mathutils.geometry.intersect_line_line(first_start, first_end, second_start, second_end)
    if result is None:
        return None
    first_point, second_point = result
    return first_point if (second_point - first_point).length < 0.0001 else None


# 返回 Face 的循环 Loop 列表；start_loop 为起点。
def _face_loops(start_loop) -> list:
    loops = []
    current_loop = start_loop
    while True:
        loops.append(current_loop)
        current_loop = current_loop.link_loop_next
        if current_loop == start_loop:
            return loops


# 检查候选连接线是否穿过 Face 的其他边；tolerance 为线段判定容差。
def _intersects_other_edges(midpoint_a, midpoint_b, border_a, border_b, face_loops, tolerance) -> bool:
    for loop in face_loops:
        if loop in (border_a, border_b):
            continue
        edge_start = loop.vert
        edge_end = loop.edge.other_vert(edge_start)
        intersection = _find_line_intersection(midpoint_a, midpoint_b, edge_start.co, edge_end.co)
        if intersection is None:
            continue
        if _is_inside_segment(intersection, midpoint_a, midpoint_b, tolerance) and _is_inside_segment(
            intersection, edge_start.co, edge_end.co, tolerance
        ):
            return True
    return False


# 计算一对平行边上的投影中点；四个参数为两条边端点。
def _project_midpoints(first_a, first_b, second_a, second_b):
    first_direction = first_b.co - first_a.co
    second_direction = second_b.co - second_a.co
    if first_direction.length < second_direction.length:
        first_midpoint = (first_b.co + first_a.co) * 0.5
        second_midpoint = (first_midpoint - second_a.co).project(second_direction) + second_a.co
        if not _is_inside_segment(second_midpoint, second_a.co, second_b.co, 0.001):
            return None
    else:
        second_midpoint = (second_a.co + second_b.co) * 0.5
        first_midpoint = (second_midpoint - first_a.co).project(first_direction) + first_a.co
        if not _is_inside_segment(first_midpoint, first_a.co, first_b.co, 0.001):
            return None
    return first_midpoint, second_midpoint


# 为目标 Loop 查找 Safe Ngon 候选边对；parallel_angle 为平行阈值，multiple_split 控制是否返回全部。
def _find_pairs(start_loop, parallel_angle: float, multiple_split: bool, seed: int) -> list:
    face = start_loop.face
    loops = _face_loops(start_loop)
    borders = []
    candidates = list(loops)
    if seed:
        random.Random(seed).shuffle(candidates)
    else:
        candidates.sort(key=lambda loop: loop.edge.calc_length(), reverse=True)
    for loop in candidates:
        if len(loop.edge.link_faces) != 2:
            continue
        face_angle = loop.edge.calc_face_angle()
        if face_angle is not None and face_angle > math.radians(0.1):
            borders.append(loop)

    pairs = []
    for border_a in borders:
        for border_b in borders:
            if border_a == border_b:
                continue
            first_a, first_b = border_a.edge.verts
            second_a, second_b = border_b.edge.verts
            first_direction = first_b.co - first_a.co
            second_direction = second_b.co - second_a.co
            if not _is_parallel(first_direction, second_direction, parallel_angle):
                continue
            midpoints = _project_midpoints(first_a, first_b, second_a, second_b)
            if midpoints is None:
                continue
            midpoint_a, midpoint_b = midpoints
            connection = midpoint_b - midpoint_a
            edge_direction = first_a.co - first_b.co
            if connection.length == 0.0 or edge_direction.length == 0.0:
                continue
            perpendicular = edge_direction.cross(face.normal)
            if perpendicular.length == 0.0 or perpendicular.angle(connection) > (-perpendicular).angle(connection):
                continue
            if _intersects_other_edges(midpoint_a, midpoint_b, border_a, border_b, loops, 0.001):
                continue
            pairs.append((border_a, border_b, midpoint_a, midpoint_b))
            if not multiple_split:
                return pairs
    return pairs


# 合并同一 source Edge 上距离小于 merge_distance 的候选切点。
def _merge_cut_point(cut_points: list, new_point: _CutPoint, merge_distance: float) -> _CutPoint:
    for cut_point in cut_points:
        if (new_point.coordinate - cut_point.coordinate).length <= merge_distance:
            return cut_point
    cut_points.append(new_point)
    return new_point


# 把 source Face 的 BMesh Custom Data 插值到新 Face 的新顶点 Loop。
def _interpolate_new_face_data(source_face, new_face, new_vertices: set) -> None:
    try:
        new_face.copy_from_face_interp(source_face, True)
    except ValueError as error:
        raise RuntimeError("Safe Ngon 无法插值新 Face 的 BMesh Custom Data") from error
    new_face.smooth = source_face.smooth
    new_face.material_index = source_face.material_index


# 修复非三角 Face 内部 Edge flow；bm 为目标 BMesh，faces 为显式 Face 集合，其余参数对应 Safe Ngon 设置。
def repair_safe_ngon_topology(
    bm: bmesh.types.BMesh,
    faces=None,
    parallel_angle: float = 10.0,
    merge_distance: float = 0.01,
    multiple_split: bool = False,
    seed: int = 0,
) -> dict:
    if parallel_angle <= 0.0:
        raise ValueError("parallel_angle 必须大于 0")
    if merge_distance <= 0.0:
        raise ValueError("merge_distance 必须大于 0")
    bm.faces.ensure_lookup_table()
    target_faces = list(faces) if faces is not None else list(bm.faces)
    target_faces = [face for face in target_faces if face.is_valid]
    edge_cut_points = {}
    connection_pairs = []
    dissolve_edges = []

    for face in target_faces:
        if len(face.loops) == 3:
            continue
        for loop in face.loops:
            edge = loop.edge
            if len(edge.link_faces) != 2:
                continue
            face_angle = edge.calc_face_angle()
            if face_angle is None or face_angle >= math.radians(0.1) or loop.calc_angle() >= math.radians(179.0):
                continue
            for border_a, border_b, midpoint_a, midpoint_b in _find_pairs(
                loop, parallel_angle, multiple_split, seed
            ):
                first_point = _CutPoint(midpoint_a)
                second_point = _CutPoint(midpoint_b)
                first_point = _merge_cut_point(edge_cut_points.setdefault(border_a.edge, []), first_point, merge_distance)
                second_point = _merge_cut_point(edge_cut_points.setdefault(border_b.edge, []), second_point, merge_distance)
                connection_pairs.append((first_point, second_point))
                dissolve_edges.append(edge)

    edge_lineage = {
        edge: (edge.smooth, edge.seam, list(edge.verts), list(points))
        for edge, points in edge_cut_points.items()
    }
    for edge, cut_points in edge_cut_points.items():
        for cut_point in cut_points:
            cut_point.vertex = bm.verts.new(cut_point.coordinate)

    rebuilt_faces = 0
    for edge, cut_points in edge_cut_points.items():
        new_vertices = {cut_point.vertex for cut_point in cut_points}
        for source_face in list(edge.link_faces):
            vertices = []
            for loop in source_face.loops:
                vertices.append(loop.vert)
                if loop.edge == edge:
                    vertices.extend(
                        sorted(new_vertices, key=lambda vertex: (vertex.co - loop.vert.co).length)
                    )
            new_face = bm.faces.new(vertices)
            _interpolate_new_face_data(source_face, new_face, new_vertices)
            rebuilt_faces += 1
        bmesh.ops.delete(bm, geom=list(edge.link_faces), context="FACES")

    for source_edge, (smooth, seam, endpoints, cut_points) in edge_lineage.items():
        direction = endpoints[1].co - endpoints[0].co
        chain = endpoints[:1] + sorted(
            (point.vertex for point in cut_points),
            key=lambda vertex: (vertex.co - endpoints[0].co).dot(direction),
        ) + endpoints[1:]
        for first, second in zip(chain, chain[1:]):
            descendant = bm.edges.get((first, second))
            if descendant is None:
                raise RuntimeError("Safe Ngon 无法解析 source Edge 的后代 Edge")
            descendant.smooth = smooth
            descendant.seam = seam

    connected_edges = []
    for first_point, second_point in connection_pairs:
        result = bmesh.ops.connect_verts(bm, verts=[first_point.vertex, second_point.vertex])
        for edge in result.get("edges", []):
            edge.smooth = True
            edge.seam = False
            connected_edges.append(edge)

    valid_dissolve_edges = list({edge for edge in dissolve_edges if edge.is_valid})
    if valid_dissolve_edges:
        bmesh.ops.dissolve_edges(
            bm, edges=valid_dissolve_edges, use_verts=True, use_face_split=False
        )
    if seed:
        flat_edges = [
            edge for edge in bm.edges
            if len(edge.link_faces) == 2
            and edge.calc_face_angle() is not None
            and edge.calc_face_angle() < math.radians(0.1)
        ]
        random.Random(seed).shuffle(flat_edges)
        if flat_edges:
            bmesh.ops.dissolve_edges(bm, edges=flat_edges, use_verts=True, use_face_split=False)
    bm.normal_update()
    return {
        "new_vertices": sum(len(points) for points in edge_cut_points.values()),
        "rebuilt_faces": rebuilt_faces,
        "connected_edges": len(connected_edges),
        "dissolved_edges": len(valid_dissolve_edges),
    }


# 溶解目标范围内近共面的内部 Edge，并清理共线二价顶点；bm 为目标 BMesh，faces 为显式范围。
def convert_coplanar_faces_to_ngons(
    bm: bmesh.types.BMesh, faces=None, angle_degrees: float = 0.1
) -> dict:
    target_faces = set(faces) if faces is not None else set(bm.faces)
    edges = [
        edge for edge in bm.edges
        if len(edge.link_faces) == 2
        and all(face in target_faces for face in edge.link_faces)
        and edge.calc_face_angle() is not None
        and edge.calc_face_angle() < math.radians(angle_degrees)
    ]
    if edges:
        bmesh.ops.dissolve_edges(bm, edges=edges, use_verts=True, use_face_split=False)
    mid_vertices = []
    for vertex in bm.verts:
        if len(vertex.link_edges) != 2:
            continue
        first, second = vertex.link_edges
        first_direction = (first.other_vert(vertex).co - vertex.co).normalized()
        second_direction = (second.other_vert(vertex).co - vertex.co).normalized()
        if first_direction.dot(second_direction) < -0.999999:
            mid_vertices.append(vertex)
    if mid_vertices:
        bmesh.ops.dissolve_verts(bm, verts=mid_vertices)
    bm.normal_update()
    return {"dissolved_edges": len(edges), "dissolved_vertices": len(mid_vertices)}


# 只读验证 Mesh 是否 closed manifold、无 loose geometry 与 zero-area Face；obj 为目标 Mesh Object。
def validate_cad_mesh_topology(obj: bpy.types.Object, area_epsilon: float = 1.0e-12) -> dict:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        boundary_edges = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
        non_manifold_edges = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
        loose_vertices = sum(1 for vertex in bm.verts if not vertex.link_faces)
        zero_area_faces = sum(1 for face in bm.faces if face.calc_area() <= area_epsilon)
    finally:
        bm.free()
    return {
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "loose_vertices": loose_vertices,
        "zero_area_faces": zero_area_faces,
    }


# 生成用于重复执行判定的 Mesh 拓扑指纹；obj 为目标 Mesh Object。
def _mesh_topology_fingerprint(obj: bpy.types.Object) -> str:
    coordinates = tuple(
        tuple(round(component, 8) for component in vertex.co)
        for vertex in obj.data.vertices
    )
    edges = tuple(tuple(edge.vertices) for edge in obj.data.edges)
    polygons = tuple(tuple(polygon.vertices) for polygon in obj.data.polygons)
    return repr((coordinates, edges, polygons))


# 对单个 Object 执行共享 CAD topology/normal pipeline；各布尔参数控制 Prepare 与 Fix 的差异。
def repair_cad_mesh(
    context: bpy.types.Context,
    obj: bpy.types.Object,
    *,
    clean_mid_vertices: bool,
    clean_loose_vertices: bool,
    use_safe_ngon: bool = True,
    convert_coplanar: bool = False,
    parallel_angle: float = 10.0,
    merge_distance: float = 0.01,
    weld_distance: float = 0.0001,
    multiple_split: bool = False,
    seed: int = 0,
    normal_mapping: str = "POLYINTERP_LNORPROJ",
) -> dict:
    if obj.type != "MESH":
        raise TypeError(f"{obj.name!r} 不是 Mesh Object")
    from .mesh_utils import Mesh

    stats = {"object": obj.name}
    pipeline_signature = (
        bool(use_safe_ngon),
        bool(convert_coplanar),
        round(parallel_angle, 6),
        round(merge_distance, 9),
        bool(multiple_split),
        int(seed),
    )
    signature_text = repr(pipeline_signature)
    try:
        with MeshNormalSnapshot(context, obj) as snapshot:
            if clean_mid_vertices:
                Mesh.clean_mid_verts(obj)
            if clean_loose_vertices:
                Mesh.clean_loose_verts(obj)
            Mesh.merge_verts_by_distance(obj, weld_distance)

            previous_signature = obj.data.get("hst_safe_ngon_signature")
            previous_fingerprint = obj.data.get("hst_safe_ngon_fingerprint")
            current_fingerprint = _mesh_topology_fingerprint(obj)
            skip_safe_ngon = (
                previous_signature == signature_text
                and previous_fingerprint == current_fingerprint
            )

            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                if convert_coplanar and not skip_safe_ngon:
                    stats["convert_coplanar"] = convert_coplanar_faces_to_ngons(bm)
                if use_safe_ngon and not skip_safe_ngon:
                    stats["safe_ngon"] = repair_safe_ngon_topology(
                        bm,
                        parallel_angle=parallel_angle,
                        merge_distance=merge_distance,
                        multiple_split=multiple_split,
                        seed=seed,
                    )
                else:
                    stats["safe_ngon"] = {
                        "new_vertices": 0,
                        "rebuilt_faces": 0,
                        "connected_edges": 0,
                        "dissolved_edges": 0,
                    }
                bm.to_mesh(obj.data)
            finally:
                bm.free()
            obj.data.update()
            stats["custom_normals_restored"] = snapshot.transfer_custom_normals(normal_mapping)
            stats["topology"] = validate_cad_mesh_topology(obj)
            obj.data["hst_safe_ngon_signature"] = signature_text
            obj.data["hst_safe_ngon_fingerprint"] = _mesh_topology_fingerprint(obj)
            stats["skipped_idempotent"] = skip_safe_ngon
    except Exception as error:
        raise RuntimeError(f"CAD Mesh repair 失败：{obj.name!r}") from error
    return stats
