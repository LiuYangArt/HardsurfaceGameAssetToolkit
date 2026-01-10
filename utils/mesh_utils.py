# -*- coding: utf-8 -*-
"""
Mesh 几何操作工具函数
===================

包含锐边标记、UV Seam 自动生成、路径查找等功能。
"""

import bpy
import bmesh
import math
import heapq
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
    def find_revolve_cap_boundaries(island_faces: set, island_edges: set) -> tuple[set, int]:
        """
        找到回转体/双盖模型的侧面边界环（使用极性分数选轴 + 严格侧面判定）
        
        参数：
            island_faces: 当前 island 的所有面
            island_edges: 当前 island 的所有边
            
        返回：
            (boundary_edges, axis_idx)
            boundary_edges: set[BMEdge] - 侧面与盖子的分界边
            axis_idx: int - 判定出的主轴索引 (0=X, 1=Y, 2=Z)
        """
        # 1. 确定主轴：使用“极性分数”
        axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
        axis_scores = [0.0, 0.0, 0.0]

        POLARITY_TOLERANCE_SIDE = 0.1  # 视为侧面的 dot 阈值
        POLARITY_TOLERANCE_CAP = 0.9   # 视为盖面的 dot 阈值

        for face in island_faces:
            area = face.calc_area()
            for i, axis in enumerate(axis_vectors):
                dot = abs(face.normal.dot(axis))
                # 如果 dot 落在两极区间，加分
                if dot < POLARITY_TOLERANCE_SIDE or dot > POLARITY_TOLERANCE_CAP:
                    axis_scores[i] += area

        axis_idx = max(range(3), key=lambda i: axis_scores[i])
        axis_vec = axis_vectors[axis_idx]
        
        # 2. 严格定义 Side Face
        # 使用非常严格的阈值提取侧面 (STRICT_SIDE_THRESHOLD = 0.05)
        STRICT_SIDE_THRESHOLD = 0.05 
        
        strict_side_faces = set()
        for face in island_faces:
            dot = abs(face.normal.dot(axis_vec))
            if dot < STRICT_SIDE_THRESHOLD:
                strict_side_faces.add(face)
                
        # 3. 找出 Strict Side Region 的边界边
        boundary_edges = set()
        for edge in island_edges:
            if edge.is_boundary:
                continue
                
            linked = [f for f in edge.link_faces if f in island_faces]
            if len(linked) == 2:
                f0_is_side = linked[0] in strict_side_faces
                f1_is_side = linked[1] in strict_side_faces
                
                # XOR: 只有一侧是 strict side，说明这是侧面与倒角/盖面的分界线
                if f0_is_side != f1_is_side:
                    boundary_edges.add(edge)
                    
        return boundary_edges, axis_idx

    @staticmethod
    def auto_seam(mesh: bpy.types.Object, mode: str = 'STANDARD'):
        """
        Automatically mark seams for closed shapes
        
        参数：
            mesh: Mesh 对象
            mode: 'STANDARD' - 标准模式（两端开口的圆柱/管道）
                  'CAPPED' - 带盖模式（单端封闭的环形模型）
        """

        # Ensure we are in object mode to access data correctly or use bmesh from object
        current_mode = mesh.mode
        if current_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 读取 sharp_edge attribute
        mesh_data = mesh.data
        sharp_edge_attr = mesh_data.attributes.get("sharp_edge")
        if sharp_edge_attr:
            sharp_edge_values = [d.value for d in sharp_edge_attr.data]
        else:
            # fallback: 用 edge.use_edge_sharp
            sharp_edge_values = [e.use_edge_sharp for e in mesh_data.edges]

        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # ============================================================
        # CAPPED 模式预处理：在分 island 之前，对整个 mesh 找 cap boundaries
        # ============================================================
        cap_faces = set()  # 存储盖子区域的面
        global_axis_idx = 2  # 默认 Z 轴
        
        if mode == 'CAPPED':
            all_faces = set(bm.faces)
            all_edges = set(bm.edges)
            
            # 对整个 mesh 调用 find_revolve_cap_boundaries
            cap_boundary_edges, global_axis_idx = Mesh.find_revolve_cap_boundaries(all_faces, all_edges)
            
            print(f"[auto_seam CAPPED] Found {len(cap_boundary_edges)} cap boundary edges on entire mesh")
            
            if cap_boundary_edges:
                # 标记 cap boundary edges 为 seam
                for edge in cap_boundary_edges:
                    edge.seam = True
                
                # 识别 cap_faces（法线平行于主轴的面）
                axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
                axis_vec = axis_vectors[global_axis_idx]
                CAP_FACE_THRESHOLD = 0.9  # dot > 0.9 算作盖面
                
                for face in all_faces:
                    if abs(face.normal.dot(axis_vec)) > CAP_FACE_THRESHOLD:
                        cap_faces.add(face)
                
                print(f"[auto_seam CAPPED] Identified {len(cap_faces)} cap faces (axis: {['X', 'Y', 'Z'][global_axis_idx]})")

        # 1. Identify Islands (connected faces not separated by seams)
        total_faces = set(bm.faces)
        visited_faces = set()
        
        islands = []

        while len(visited_faces) < len(total_faces):
            seed_face = next(iter(total_faces - visited_faces))
            island = set()
            stack = [seed_face]
            
            while stack:
                f = stack.pop()
                if f in visited_faces:
                    continue
                visited_faces.add(f)
                island.add(f)
                
                for edge in f.edges:
                    if not edge.seam: 
                        for neighbor_face in edge.link_faces:
                            if neighbor_face not in visited_faces:
                                stack.append(neighbor_face)
            islands.append(island)

        # 2. Process each island
        for island in islands:
            # ============================================================
            # CAPPED 模式：跳过盖子 island（只包含 cap faces 的 island）
            # ============================================================
            if mode == 'CAPPED' and cap_faces:
                # 判断是否是 cap island（大部分面都是 cap faces）
                cap_face_count = sum(1 for face in island if face in cap_faces)
                cap_ratio = cap_face_count / len(island) if island else 0
                
                if cap_ratio > 0.8:  # 80% 以上是盖面，视为 cap island
                    print(f"[auto_seam CAPPED] Skipping cap island ({len(island)} faces, {cap_ratio:.1%} cap faces)")
                    continue
            
            # Find boundary edges for this island
            boundary_edges = set()
            island_verts = set()

            for face in island:
                for v in face.verts:
                    island_verts.add(v)
                for edge in face.edges:
                    if edge.seam or edge.is_boundary:
                        boundary_edges.add(edge)
                    else:
                        # Check if edge connects to a face NOT in this island (should be covered by seam check strictly speaking, but for safety)
                        # If edge.seam is False, it implies all linked faces are in island (per flood fill logic)
                        pass
            
            # Group boundary edges into Loops
            loops = []
            if boundary_edges:
                edge_pool = set(boundary_edges)
                while edge_pool:
                    # Trace a loop
                    seed_edge = next(iter(edge_pool))
                    edge_pool.remove(seed_edge)
                    
                    # This is simple grouping, might not be perfectly ordered loops, but enough to identify separate holes
                    current_loop = {seed_edge}
                    
                    # Grow loop
                    # A better way: Find connected components of edges in the graph of 'boundary_edges'
                    # Vertices involved in boundary edges
                    loop_stack = [seed_edge]
                    while loop_stack:
                        e = loop_stack.pop()
                        # Find connected edges in pool
                        # Edges share a vertex
                        v1, v2 = e.verts
                        
                        connected_neighbors = []
                        for check_e in list(edge_pool): # Check copy to allow removal
                            if check_e in edge_pool: # double check
                                if check_e.verts[0] == v1 or check_e.verts[0] == v2 or check_e.verts[1] == v1 or check_e.verts[1] == v2:
                                    connected_neighbors.append(check_e)
                        
                        for ne in connected_neighbors:
                            edge_pool.remove(ne)
                            current_loop.add(ne)
                            loop_stack.append(ne)
                    
                    loops.append(current_loop)

            # Analyze Topology
            num_loops = len(loops)
            
            print(f"[auto_seam DEBUG] ========== Island Analysis ==========")
            print(f"[auto_seam DEBUG] Mode: {mode}, num_loops: {num_loops}")
            
            if num_loops == 0:
                print(f"[auto_seam DEBUG] Entering num_loops == 0 branch (closed surface)")
                # Closed Surface (Sphere, Torus) or Double-capped model
                # Get all island edges and faces for processing
                island_edges = set()
                for face in island:
                    for edge in face.edges:
                        island_edges.add(edge)
                island_faces = set(island)
                
                verts_list = list(island_verts)
                if not verts_list: continue

                # Calculate bounding box to find dominant axis
                min_bb = Vector((float('inf'), float('inf'), float('inf')))
                max_bb = Vector((float('-inf'), float('-inf'), float('-inf')))
                
                for v in verts_list:
                    for i in range(3):
                        min_bb[i] = min(min_bb[i], v.co[i])
                        max_bb[i] = max(max_bb[i], v.co[i])
                
                size = max_bb - min_bb
                axis_idx = 0
                if size.y > size.x and size.y > size.z:
                    axis_idx = 1
                elif size.z > size.x and size.z > size.y:
                    axis_idx = 2
                
                # ============================================================
                # CAPPED 模式：对于封闭的双盖模型，使用 find_revolve_cap_boundaries
                # ============================================================
                if mode == 'CAPPED':
                    # 用 Revolve Cap 算法找盖子边界边
                    cap_boundary_edges, precise_axis_idx = Mesh.find_revolve_cap_boundaries(island_faces, island_edges)
                    
                    print(f"[auto_seam DEBUG] num_loops=0, CAPPED mode: found {len(cap_boundary_edges)} cap boundary edges")
                    
                    if cap_boundary_edges:
                        # 标记盖子边界为 seam
                        for edge in cap_boundary_edges:
                            edge.seam = True
                        print(f"[auto_seam DEBUG] Marked {len(cap_boundary_edges)} cap boundary edges as seam")
                        
                        # 获取边界边的顶点，用于找垂直连接路径
                        cap_boundary_verts = set()
                        for edge in cap_boundary_edges:
                            cap_boundary_verts.add(edge.verts[0])
                            cap_boundary_verts.add(edge.verts[1])
                        
                        # 将边界边按高度分成上下两组
                        edge_heights = []
                        for edge in cap_boundary_edges:
                            mid = (edge.verts[0].co + edge.verts[1].co) / 2
                            edge_heights.append((edge, mid[precise_axis_idx]))
                        
                        if edge_heights:
                            min_height = min(h for _, h in edge_heights)
                            max_height = max(h for _, h in edge_heights)
                            mid_height = (min_height + max_height) / 2
                            
                            lower_verts = set()
                            upper_verts = set()
                            for edge, h in edge_heights:
                                if h < mid_height:
                                    lower_verts.add(edge.verts[0])
                                    lower_verts.add(edge.verts[1])
                                else:
                                    upper_verts.add(edge.verts[0])
                                    upper_verts.add(edge.verts[1])
                            
                            print(f"[auto_seam DEBUG] lower_verts: {len(lower_verts)}, upper_verts: {len(upper_verts)}")
                            
                            # 找 bevel edges 用于路径搜索
                            ANGLE_THRESHOLD = 0.98
                            bevel_edges = set()
                            for edge in island_edges:
                                if edge.is_boundary or edge.seam:
                                    continue
                                if sharp_edge_values[edge.index]:
                                    continue
                                linked_faces = [f for f in edge.link_faces if f in island_faces]
                                if len(linked_faces) == 2:
                                    dot = linked_faces[0].normal.dot(linked_faces[1].normal)
                                    if dot < ANGLE_THRESHOLD:
                                        bevel_edges.add(edge)
                            
                            # 在两个边界环之间找 bevel path
                            if lower_verts and upper_verts and bevel_edges:
                                
                                def find_bevel_path(start_verts, target_verts, valid_edges):
                                    all_verts = set()
                                    for e in valid_edges:
                                        all_verts.add(e.verts[0])
                                        all_verts.add(e.verts[1])
                                    
                                    dist = {v: float('inf') for v in all_verts}
                                    prev_edge = {}
                                    pq = []
                                    
                                    for v in start_verts:
                                        if v in dist:
                                            dist[v] = 0
                                            heapq.heappush(pq, (0, id(v), v))
                                    
                                    while pq:
                                        d, _, v = heapq.heappop(pq)
                                        if d > dist[v]:
                                            continue
                                        if v in target_verts:
                                            path = []
                                            current = v
                                            while current in prev_edge:
                                                edge = prev_edge[current]
                                                path.append(edge)
                                                current = edge.other_vert(current)
                                            return path
                                        for e in v.link_edges:
                                            if e in valid_edges:
                                                other = e.other_vert(v)
                                                new_dist = d + e.calc_length()
                                                if new_dist < dist.get(other, float('inf')):
                                                    dist[other] = new_dist
                                                    prev_edge[other] = e
                                                    heapq.heappush(pq, (new_dist, id(other), other))
                                    return []
                                
                                path_edges = find_bevel_path(lower_verts, upper_verts, bevel_edges)
                                if path_edges:
                                    for e in path_edges:
                                        e.seam = True
                                    print(f"[auto_seam DEBUG] Marked {len(path_edges)} vertical seam edges")
                                else:
                                    print(f"[auto_seam DEBUG] No bevel path found between cap boundaries")
                    else:
                        print(f"[auto_seam DEBUG] No cap boundary edges found, using default path")
                        # Fallback: 使用默认的 shortest path
                        verts_list.sort(key=lambda v: v.co[axis_idx])
                        min_v = verts_list[0]
                        max_v = verts_list[-1]
                        bias_vector = Vector((0.0, 0.0, 0.0))
                        bias_vector[axis_idx] = 1.0
                        path_edges, _ = Mesh.find_shortest_path(bm, min_v, max_v, island, bias_vector=bias_vector)
                        if path_edges:
                            for e in path_edges:
                                e.seam = True
                else:
                    # STANDARD 模式: 原来的逻辑
                    verts_list.sort(key=lambda v: v.co[axis_idx])
                    min_v = verts_list[0]
                    max_v = verts_list[-1]
                    
                    # Create bias vector for pathfinding (dominant axis)
                    bias_vector = Vector((0.0, 0.0, 0.0))
                    bias_vector[axis_idx] = 1.0
                    
                    # Find shortest path edges
                    path_edges, _ = Mesh.find_shortest_path(bm, min_v, max_v, island, bias_vector=bias_vector)
                    if path_edges:
                        for e in path_edges:
                            e.seam = True

            elif num_loops >= 1:
                print(f"[auto_seam DEBUG] Entering num_loops >= 1 branch (has boundary loops)")
                # Cylinder-like (Side wall) with one or more boundary loops (holes/openings)
                # For num_loops == 1: single opening (like a cup or hollow cylinder)
                # For num_loops >= 2: multiple holes or a tube

                # 1. Calculate Center of each loop first
                loop_info = []
                for idx, loop in enumerate(loops):
                    center = Vector((0.0, 0.0, 0.0))
                    count = 0
                    for edge in loop:
                        for v in edge.verts:
                            center += v.co
                            count += 1
                    if count > 0:
                        center /= count
                    loop_info.append({'index': idx, 'center': center, 'edge_count': len(loop)})

                # 2. Determine dominant axis by loop spread (not bounding box)
                centers = [li['center'] for li in loop_info]
                spread_x = max(c.x for c in centers) - min(c.x for c in centers)
                spread_y = max(c.y for c in centers) - min(c.y for c in centers)
                spread_z = max(c.z for c in centers) - min(c.z for c in centers)

                if spread_z >= spread_x and spread_z >= spread_y:
                    axis_idx = 2
                elif spread_y >= spread_x and spread_y >= spread_z:
                    axis_idx = 1
                else:
                    axis_idx = 0

                # 3. Sort loops by position on dominant axis
                loop_centers = []
                for li in loop_info:
                    li['measure'] = li['center'][axis_idx]
                    loop_centers.append(li)
                loop_centers.sort(key=lambda x: x['measure'])

                # First, get all island edges
                island_edges = set()
                for face in island:
                    for edge in face.edges:
                        island_edges.add(edge)

                island_faces = set(island)
                ANGLE_THRESHOLD = 0.98  # dot < 0.98 means angle > ~11°

                # ============================================================
                # 方法：sharp_edge attribute + bevel edges 连通性检测
                # 1. 外轮廓边 = sharp edges（直接从 attribute）
                # 2. Bevel edges = 法线角度法选中 + 非 sharp
                # 3. 用 bevel edges 做连通性检测区分内外 boundary loops
                # ============================================================

                # 1. 找出所有 sharp edges（外轮廓边）
                sharp_edges_in_island = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    if sharp_edge_values[edge.index]:
                        sharp_edges_in_island.add(edge)

                # 2. 法线角度法找 bevel edges（用于连通性检测）
                bevel_edges = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    if sharp_edge_values[edge.index]:
                        continue  # 跳过 sharp edges
                    linked_faces = [f for f in edge.link_faces if f in island_faces]
                    if len(linked_faces) == 2:
                        dot = linked_faces[0].normal.dot(linked_faces[1].normal)
                        if dot < ANGLE_THRESHOLD:
                            bevel_edges.add(edge)

                # 3. 用 bevel edges 做连通性检测
                # 获取每个 loop 的顶点集合
                loop_verts_list = []
                for loop in loops:
                    verts = set()
                    for edge in loop:
                        verts.add(edge.verts[0])
                        verts.add(edge.verts[1])
                    loop_verts_list.append(verts)

                def find_reachable_verts(start_verts, valid_edges):
                    """从 start_verts 出发，沿着 valid_edges 能到达的所有顶点"""
                    visited = set(start_verts)
                    stack = list(start_verts)
                    while stack:
                        v = stack.pop()
                        for e in v.link_edges:
                            if e in valid_edges:
                                other_v = e.other_vert(v)
                                if other_v not in visited:
                                    visited.add(other_v)
                                    stack.append(other_v)
                    return visited

                # 4. 找出通过 bevel edges 连通的 loops
                connected_groups = []
                visited_loops = set()

                for start_idx in range(len(loops)):
                    if start_idx in visited_loops:
                        continue

                    # 从这个 loop 的顶点开始 flood fill（沿着 bevel edges）
                    reachable = find_reachable_verts(loop_verts_list[start_idx], bevel_edges)

                    # 检查哪些其他 loops 的顶点在 reachable 中
                    connected_group = {start_idx}
                    for other_idx in range(len(loops)):
                        if other_idx != start_idx:
                            if loop_verts_list[other_idx] & reachable:
                                connected_group.add(other_idx)

                    connected_groups.append(connected_group)
                    visited_loops |= connected_group

                # 5. 选最大的连通组作为外轮廓
                def calc_loop_perimeter(loop_idx):
                    return sum(e.calc_length() for e in loops[loop_idx])

                best_group = None
                best_score = (-1, -1)

                for group in connected_groups:
                    size = len(group)
                    total_perimeter = sum(calc_loop_perimeter(idx) for idx in group)
                    score = (size, total_perimeter)
                    if score > best_score:
                        best_score = score
                        best_group = group

                outer_loops = list(best_group) if best_group else []

                # 6. 从外轮廓 loops 中选首尾两个（按主轴排序）
                outer_loop_centers = [lc for lc in loop_centers if lc['index'] in outer_loops]
                if len(outer_loop_centers) >= 2:
                    start_loop_idx = outer_loop_centers[0]['index']
                    end_loop_idx = outer_loop_centers[-1]['index']
                else:
                    # fallback: 用所有 loops 的首尾
                    start_loop_idx = loop_centers[0]['index']
                    end_loop_idx = loop_centers[-1]['index']

                l1_edges = list(loops[start_loop_idx])
                l2_edges = list(loops[end_loop_idx])

                # 7. 外轮廓 boundary edges
                outer_boundary_edges = set()
                for idx in outer_loops:
                    outer_boundary_edges |= loops[idx]

                # Classify edges - use sharp_edge attribute
                silhouette_edges = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        # Only include if it's part of outer loops
                        if edge in outer_boundary_edges:
                            silhouette_edges.add(edge)
                        continue
                    if edge.seam:
                        silhouette_edges.add(edge)
                        continue
                    # Use sharp_edge attribute instead of coplanar region detection
                    if sharp_edge_values[edge.index]:
                        silhouette_edges.add(edge)

                # ============================================================
                # Dijkstra 路径搜索：在 bevel edges 上找连接两个外轮廓 loops 的最短路径
                # ============================================================

                def find_bevel_edge_path(start_verts, target_verts, valid_edges):
                    """在 bevel edges 上搜索连接两组顶点的最短路径"""
                    # 初始化：收集所有 valid_edges 涉及的顶点
                    all_verts = set()
                    for e in valid_edges:
                        all_verts.add(e.verts[0])
                        all_verts.add(e.verts[1])

                    dist = {v: float('inf') for v in all_verts}
                    prev_edge = {}  # 记录到达每个顶点的边

                    pq = []
                    for v in start_verts:
                        if v in dist:
                            dist[v] = 0
                            heapq.heappush(pq, (0, id(v), v))

                    while pq:
                        d, _, v = heapq.heappop(pq)
                        if d > dist[v]:
                            continue

                        # 检查是否到达目标
                        if v in target_verts:
                            # 回溯路径
                            path = []
                            current = v
                            while current in prev_edge:
                                edge = prev_edge[current]
                                path.append(edge)
                                current = edge.other_vert(current)
                            return path, d

                        # 遍历邻边
                        for e in v.link_edges:
                            if e in valid_edges:
                                other = e.other_vert(v)
                                new_dist = d + e.calc_length()
                                if new_dist < dist.get(other, float('inf')):
                                    dist[other] = new_dist
                                    prev_edge[other] = e
                                    heapq.heappush(pq, (new_dist, id(other), other))

                    return [], float('inf')

                print(f"[auto_seam DEBUG] Island has {len(island)} faces, {len(island_edges)} edges")
                print(f"[auto_seam DEBUG] Sharp edges: {len(sharp_edges_in_island)}, Bevel edges: {len(bevel_edges)}")
                print(f"[auto_seam DEBUG] Outer loops: {outer_loops}, Mode: {mode}")

                # ============================================================
                # STANDARD 模式处理：在两个 outer loops 之间找 bevel path
                # (CAPPED 模式的 cap boundaries 已在预处理阶段完成，
                #  cap islands 已被跳过，这里只处理 side islands)
                # ============================================================
                if len(outer_loops) >= 2:
                    outer_loop_indices = sorted(outer_loops, key=lambda i: loop_centers[i]['center'][axis_idx])
                    loop1_verts = set(v for e in loops[outer_loop_indices[0]] for v in e.verts)
                    loop2_verts = set(v for e in loops[outer_loop_indices[-1]] for v in e.verts)

                    # Dijkstra 搜索
                    path_edges, path_cost = find_bevel_edge_path(loop1_verts, loop2_verts, bevel_edges)

                    print(f"[auto_seam DEBUG] loop1_verts: {len(loop1_verts)}, loop2_verts: {len(loop2_verts)}")
                    print(f"[auto_seam DEBUG] path found: {len(path_edges)} edges, cost: {path_cost:.4f}")

                    if path_edges:
                        for e in path_edges:
                            e.seam = True
                        print(f"[auto_seam DEBUG] Marked {len(path_edges)} bevel edges as seam")
                    else:
                        print(f"[auto_seam DEBUG] No path found on bevel edges!")
                elif len(outer_loops) < 2 and mode != 'CAPPED':
                    print(f"[auto_seam DEBUG] Not enough outer loops: {len(outer_loops)}")

        bm.to_mesh(mesh.data)
        bm.free()
        
        if current_mode == 'EDIT':
             bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def find_shortest_path(bm, start_vert, end_vert, valid_faces_set, bias_vector=None, allow_flat_edges=False, silhouette_edges_override=None, end_verts_set=None):
        """Dijkstra pathfinder. Flat edges are excluded unless allow_flat_edges=True.

        Args:
            end_vert: Single target vertex (used if end_verts_set is None)
            end_verts_set: Set of target vertices - path ends when ANY is reached
            silhouette_edges_override: If provided, use this set as silhouette edges instead of computing
        """

        # Determine target vertices
        if end_verts_set is not None:
            target_verts = end_verts_set
        else:
            target_verts = {end_vert}

        # Convert valid_faces to valid_edges set
        all_edges = set()
        for f in valid_faces_set:
            for e in f.edges:
                all_edges.add(e)

        # Use override if provided, otherwise compute
        if silhouette_edges_override is not None:
            silhouette_edges = silhouette_edges_override & all_edges
            print(f"[find_shortest_path DEBUG] Override provided: {len(silhouette_edges_override)}, all_edges: {len(all_edges)}, intersection: {len(silhouette_edges)}")
        else:
            # ============================================================
            # Identify Coplanar Regions using flood fill
            # ============================================================
            PLANE_DIST_THRESHOLD = 0.01  # 1cm threshold

            face_to_region = {}
            region_id = 0
            all_faces = set(valid_faces_set)
            region_visited = set()

            while len(region_visited) < len(all_faces):
                seed_face = next(iter(all_faces - region_visited))
                ref_normal = seed_face.normal.copy()
                ref_point = seed_face.verts[0].co.copy()

                stack = [seed_face]

                while stack:
                    f = stack.pop()
                    if f in region_visited:
                        continue

                    # Check if ALL vertices of this face lie on the reference plane
                    all_verts_on_plane = True
                    for v in f.verts:
                        dist = abs((v.co - ref_point).dot(ref_normal))
                        if dist > PLANE_DIST_THRESHOLD:
                            all_verts_on_plane = False
                            break

                    if all_verts_on_plane:
                        region_visited.add(f)
                        face_to_region[f] = region_id

                        # Add neighbors through non-seam, non-boundary edges
                        for edge in f.edges:
                            if not edge.seam and not edge.is_boundary:
                                for neighbor in edge.link_faces:
                                    if neighbor in all_faces and neighbor not in region_visited:
                                        stack.append(neighbor)

                region_id += 1

            # Classify edges as silhouette or flat
            silhouette_edges = set()

            for edge in all_edges:
                if edge.is_boundary:
                    silhouette_edges.add(edge)
                    continue

                if edge.seam:
                    silhouette_edges.add(edge)
                    continue

                linked_faces = [f for f in edge.link_faces if f in all_faces]
                if len(linked_faces) != 2:
                    silhouette_edges.add(edge)
                    continue

                f1, f2 = linked_faces
                region1 = face_to_region.get(f1, -1)
                region2 = face_to_region.get(f2, -2)

                if region1 != region2:
                    silhouette_edges.add(edge)

        # ============================================================
        # Dijkstra with edge filtering
        # ============================================================
        # When allow_flat_edges=False, COMPLETELY EXCLUDE flat edges
        valid_edges_for_path = all_edges if allow_flat_edges else silhouette_edges
        print(f"[find_shortest_path DEBUG] valid_edges_for_path: {len(valid_edges_for_path)}, target_verts: {len(target_verts)}")

        # Check if start_vert connects to any valid edge
        start_valid_edges = [e for e in start_vert.link_edges if e in valid_edges_for_path]
        print(f"[find_shortest_path DEBUG] start_vert has {len(start_valid_edges)} valid edges out of {len(start_vert.link_edges)} total")

        queue = [(0.0, id(start_vert), start_vert, [])]
        visited = {start_vert: 0.0}

        while queue:
            cost, _, current_v, path = heapq.heappop(queue)

            # Check if reached ANY target vertex
            if current_v in target_verts:
                return path, cost

            if cost > visited.get(current_v, float('inf')):
                continue

            for edge in current_v.link_edges:
                if edge not in valid_edges_for_path:
                    continue

                other_v = edge.other_vert(current_v)

                # Calculate Cost
                length = edge.calc_length()
                penalty_multiplier = 1.0

                # Directional bias penalty
                if bias_vector:
                    v_diff = (other_v.co - current_v.co)
                    if v_diff.length_squared > 0:
                        v_dir = v_diff.normalized()
                        dot = abs(v_dir.dot(bias_vector))
                        direction_penalty = (1.0 - dot) * 5.0
                        penalty_multiplier += direction_penalty

                new_cost = cost + (length * penalty_multiplier)

                if new_cost < visited.get(other_v, float('inf')):
                    visited[other_v] = new_cost
                    new_path = path + [edge]
                    heapq.heappush(queue, (new_cost, id(other_v), other_v, new_path))

        return None, float('inf')


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

