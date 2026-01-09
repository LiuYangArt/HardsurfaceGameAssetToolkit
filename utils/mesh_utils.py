# -*- coding: utf-8 -*-
"""
Mesh 几何操作工具函数
===================

包含锐边标记、UV Seam 自动生成、路径查找等功能。
"""

import bpy
import bmesh
import math
from mathutils import Vector


def mark_sharp_edges_by_split_normal(obj) -> None:
    """
    根据 SplitNormal 标记锐边

    Args:
        obj: 目标 mesh 对象
    """
    bm = bmesh.new()
    mesh = obj.data
    bm.from_mesh(mesh)

    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    loops = mesh.loops

    split_edges = set()

    for vert in bm.verts:
        for edge in vert.link_edges:
            loops_for_vert_and_edge = []
            for face in edge.link_faces:
                for loop in face.loops:
                    if loop.vert == vert:
                        loops_for_vert_and_edge.append(loop)
            if len(loops_for_vert_and_edge) != 2:
                continue
            loop1, loop2 = loops_for_vert_and_edge
            normal1 = loops[loop1.index].normal
            normal2 = loops[loop2.index].normal

            if are_normals_different(normal1, normal2):
                split_edges.add(edge)

    for edge in bm.edges:
        if edge in split_edges:
            edge.smooth = False
            edge.seam = True

    bm.to_mesh(obj.data)
    bm.free()


def are_normals_different(normal_a, normal_b, threshold_angle_degrees: float = 5.0) -> bool:
    """
    计算法线是否朝向一致

    Args:
        normal_a: 法线 A
        normal_b: 法线 B
        threshold_angle_degrees: 阈值角度（度）

    Returns:
        是否不同
    """
    threshold_cosine = math.cos(math.radians(threshold_angle_degrees))
    dot_product = normal_a.dot(normal_b)
    return dot_product < threshold_cosine


def mark_sharp_edge_by_angle(mesh, sharp_angle: float = 0.08) -> None:
    """
    根据角度标记锐边

    Args:
        mesh: 目标 mesh 对象
        sharp_angle: 锐边角度阈值（弧度）
    """
    bm = bmesh.new()
    mesh_data = mesh.data
    bm.from_mesh(mesh_data)

    to_mark_sharp = []
    has_sharp_edge = False

    for edge in bm.edges:
        if edge.calc_face_angle() >= sharp_angle:
            to_mark_sharp.append(edge.index)

    for attributes in mesh_data.attributes:
        if "sharp_edge" in attributes.name:
            has_sharp_edge = True
            break

    if has_sharp_edge is False:
        mesh_data.attributes.new("sharp_edge", type="BOOLEAN", domain="EDGE")
    
    for edge in mesh_data.edges:
        if edge.index in to_mark_sharp:
            edge.use_edge_sharp = True
        else:
            edge.use_edge_sharp = False

    bm.clear()
    bm.free()


def mark_convex_edges(mesh) -> None:
    """
    标记凸边

    Args:
        mesh: 目标 mesh 对象
    """
    from .mesh_attributes_utils import MeshAttributes
    from .bmesh_utils import BMesh as BMeshUtils
    
    convex_attribute_name = "convex_edge"
    convex_attr = MeshAttributes.add(mesh, attribute_name=convex_attribute_name, data_type="FLOAT", domain="EDGE")
    bm = BMeshUtils.init(mesh, mode="OBJECT")

    convex_layer = bm.edges.layers.float[convex_attr.name]
    for edge in bm.edges:
        if edge.is_convex is True:
            edge[convex_layer] = 1
        else:
            edge[convex_layer] = 0
    BMeshUtils.finished(bm, mesh, mode="OBJECT")


def set_edge_bevel_weight_from_sharp(target_object: bpy.types.Object) -> bool:
    """
    根据边缘是否为 sharp 设置 bevel 权重

    Args:
        target_object: 目标对象

    Returns:
        是否有 sharp 边
    """
    has_sharp: bool = False
    if "sharp_edge" in target_object.data.attributes:
        has_sharp = True
        if "bevel_weight_edge" not in target_object.data.attributes:
            bevel_weight_attr = target_object.data.attributes.new(
                "bevel_weight_edge", "FLOAT", "EDGE"
            )
            for index, edge in enumerate(target_object.data.edges):
                bevel_weight_attr.data[index].value = (
                    1.0 if edge.use_edge_sharp else 0.0
                )
    return has_sharp


class Mesh:
    """Mesh 几何操作工具类"""

    @staticmethod
    def check_open_bondary(mesh: bpy.types.Object) -> bool:
        """
        检查是否存在开放边

        Args:
            mesh: 目标 mesh 对象

        Returns:
            是否有开放边
        """
        if mesh.type != 'MESH':
            return False
            
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        check_result = False
        for edge in bm.edges:
            if edge.is_boundary:
                check_result = True
                break
        
        bm.free()
        return check_result

    @staticmethod
    def clean_lonely_verts(mesh: bpy.types.Object):
        """
        清理孤立顶点

        Args:
            mesh: 目标 mesh 对象
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        # 找到所有孤立顶点（没有连接边的顶点）
        lonely_verts = [v for v in bm.verts if len(v.link_edges) == 0]
        
        # 删除孤立顶点
        for v in lonely_verts:
            bm.verts.remove(v)
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def clean_mid_verts(mesh: bpy.types.Object):
        """
        清理直线中的孤立顶点

        Args:
            mesh: 目标 mesh 对象
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        # 找到所有只连接两条边的顶点
        mid_verts = []
        for v in bm.verts:
            if len(v.link_edges) == 2:
                # 检查两条边是否共线
                e1, e2 = v.link_edges
                v1 = e1.other_vert(v)
                v2 = e2.other_vert(v)
                
                dir1 = (v1.co - v.co).normalized()
                dir2 = (v2.co - v.co).normalized()
                
                # 如果方向接近相反，说明在直线上
                if dir1.dot(dir2) < -0.99:
                    mid_verts.append(v)
        
        # 对于中间顶点，合并边
        for v in mid_verts:
            bmesh.ops.dissolve_verts(bm, verts=[v])
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def clean_loose_verts(mesh: bpy.types.Object):
        """
        清理松散顶点

        Args:
            mesh: 目标 mesh 对象
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        # 找到所有松散顶点（没有连接面的顶点）
        loose_verts = [v for v in bm.verts if len(v.link_faces) == 0]
        
        # 删除松散顶点
        for v in loose_verts:
            bm.verts.remove(v)
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def merge_verts_by_distance(mesh: bpy.types.Object, merge_distance: float = 0.01):
        """
        清理重复顶点

        Args:
            mesh: 目标 mesh 对象
            merge_distance: 合并距离
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def merge_verts_ops(meshes: list):
        """
        使用 ops 合并顶点

        Args:
            meshes: mesh 对象列表
        """
        original_active = bpy.context.active_object
        
        for mesh in meshes:
            if mesh.type != 'MESH':
                continue
            
            bpy.context.view_layer.objects.active = mesh
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles()
            bpy.ops.object.mode_set(mode='OBJECT')
        
        if original_active:
            bpy.context.view_layer.objects.active = original_active

    @staticmethod
    def dissolve_flat_edges(mesh: bpy.types.Object):
        """
        溶解平面区域的内部支撑边 (support edges)

        只保留平面区域的外轮廓边，避免 UV Seam 被标记到这些无意义的边上。

        定义"内部边"：
        - 边的两个相邻面法线方向基本相同（在同一平面上）
        - 边不是边界边 (is_boundary = False)

        Args:
            mesh: 目标 mesh 对象
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        
        # 找到所有平面内部边
        flat_edges = []
        for edge in bm.edges:
            if edge.is_boundary:
                continue
            if len(edge.link_faces) != 2:
                continue
            
            f1, f2 = edge.link_faces
            # 检查两个面的法线是否接近
            if f1.normal.dot(f2.normal) > 0.99:
                flat_edges.append(edge)
        
        # 溶解这些边
        if flat_edges:
            bmesh.ops.dissolve_edges(bm, edges=flat_edges)
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def find_revolve_cap_boundaries(island_faces: set, island_edges: set):
        """
        找到回转体/双盖模型的侧面边界环（使用极性分数选轴 + 严格侧面判定）

        Args:
            island_faces: 当前 island 的所有面
            island_edges: 当前 island 的所有边

        Returns:
            (boundary_edges, axis_idx) 元组
            boundary_edges: set[BMEdge] - 侧面与盖子的分界边
            axis_idx: int - 判定出的主轴索引 (0=X, 1=Y, 2=Z)
        """
        # 计算面的法线分布，确定主轴
        normal_sum = [Vector((0, 0, 0)), Vector((0, 0, 0)), Vector((0, 0, 0))]
        
        for face in island_faces:
            normal = face.normal.normalized()
            for i in range(3):
                axis = Vector((0, 0, 0))
                axis[i] = 1.0
                if abs(normal.dot(axis)) > 0.9:
                    normal_sum[i] += normal * face.calc_area()
        
        # 找到主轴
        axis_idx = max(range(3), key=lambda i: normal_sum[i].length)
        
        # 找到边界边
        boundary_edges = set()
        for edge in island_edges:
            if len(edge.link_faces) == 2:
                f1, f2 = edge.link_faces
                if f1 in island_faces and f2 in island_faces:
                    n1 = f1.normal.normalized()
                    n2 = f2.normal.normalized()
                    
                    # 检查是否是侧面和盖子的分界
                    axis = Vector((0, 0, 0))
                    axis[axis_idx] = 1.0
                    
                    is_f1_cap = abs(n1.dot(axis)) > 0.9
                    is_f2_cap = abs(n2.dot(axis)) > 0.9
                    
                    if is_f1_cap != is_f2_cap:
                        boundary_edges.add(edge)
        
        return boundary_edges, axis_idx

    @staticmethod
    def auto_seam(mesh: bpy.types.Object, mode: str = 'STANDARD'):
        """
        Automatically mark seams for closed shapes

        Args:
            mesh: Mesh 对象
            mode: 'STANDARD' - 标准模式（两端开口的圆柱/管道）
                  'CAPPED' - 带盖模式（单端封闭的环形模型）
        """
        if mesh.type != 'MESH':
            return
        
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        # 清除所有现有 seam
        for edge in bm.edges:
            edge.seam = False
        
        if mode == 'STANDARD':
            # 标准模式：在锐边上标记 seam
            for edge in bm.edges:
                if not edge.smooth:
                    edge.seam = True
        
        elif mode == 'CAPPED':
            # 带盖模式：需要更复杂的处理
            # 首先标记所有锐边
            for edge in bm.edges:
                if not edge.smooth:
                    edge.seam = True
        
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()

    @staticmethod
    def find_shortest_path(bm, start_vert, end_vert, valid_faces_set, 
                           bias_vector=None, allow_flat_edges: bool = False, 
                           silhouette_edges_override=None, end_verts_set=None):
        """
        Dijkstra pathfinder. Flat edges are excluded unless allow_flat_edges=True.

        Args:
            bm: bmesh 对象
            start_vert: 起始顶点
            end_vert: 单个目标顶点（如果 end_verts_set 为 None 时使用）
            valid_faces_set: 有效面集合
            bias_vector: 偏向向量（优先沿此方向的边）
            allow_flat_edges: 是否允许平坦边
            silhouette_edges_override: 轮廓边覆盖集合
            end_verts_set: 目标顶点集合 - 到达任意一个即结束

        Returns:
            从起始到目标的边列表
        """
        import heapq
        
        target_verts = end_verts_set if end_verts_set else {end_vert}
        
        # 初始化距离和前驱
        dist = {v: float('inf') for v in bm.verts}
        prev = {v: None for v in bm.verts}
        prev_edge = {v: None for v in bm.verts}
        
        dist[start_vert] = 0
        pq = [(0, start_vert.index, start_vert)]
        
        while pq:
            d, _, vert = heapq.heappop(pq)
            
            if vert in target_verts:
                # 重建路径
                path_edges = []
                current = vert
                while prev_edge[current]:
                    path_edges.append(prev_edge[current])
                    current = prev[current]
                return list(reversed(path_edges))
            
            if d > dist[vert]:
                continue
            
            for edge in vert.link_edges:
                # 检查边是否有效
                if not allow_flat_edges:
                    # 检查是否是平坦边
                    if len(edge.link_faces) == 2:
                        f1, f2 = edge.link_faces
                        if f1.normal.dot(f2.normal) > 0.99:
                            continue
                
                neighbor = edge.other_vert(vert)
                
                # 计算边的权重
                weight = edge.calc_length()
                
                # 应用偏向
                if bias_vector:
                    edge_dir = (neighbor.co - vert.co).normalized()
                    alignment = abs(edge_dir.dot(bias_vector))
                    weight *= (2 - alignment)  # 对齐时权重更低
                
                new_dist = dist[vert] + weight
                
                if new_dist < dist[neighbor]:
                    dist[neighbor] = new_dist
                    prev[neighbor] = vert
                    prev_edge[neighbor] = edge
                    heapq.heappush(pq, (new_dist, neighbor.index, neighbor))
        
        return []  # 没有找到路径


def check_non_solid_meshes(meshes: list) -> list:
    """
    检查 mesh 列表中是否存在非水密模型，将问题模型移动到特定 Collection
    
    Args:
        meshes: mesh 对象列表
    
    Returns:
        包含开放边界的 mesh 列表，如果全部水密则返回 None
    """
    from .collection_utils import Collection
    
    BAD_MESHES_COLLECTION = "_BadMeshes"  # 临时硬编码，应该从 Const 导入
    
    bad_mesh_count = 0
    bad_meshes = []

    for mesh in meshes:
        check_mesh = Mesh.check_open_bondary(mesh)
        if check_mesh is True:
            bad_mesh_count += 1
            bad_meshes.append(mesh)

    if bad_mesh_count != 0:
        bad_collection = Collection.create(name=BAD_MESHES_COLLECTION, type="MISC")
        for mesh in bad_meshes:
            mesh.users_collection[0].objects.unlink(mesh)
            bad_collection.objects.link(mesh)
        return bad_meshes
    elif bad_meshes == 0:
        return None

