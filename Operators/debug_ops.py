# -*- coding: utf-8 -*-
"""
调试工具 Operators
=================

包含用于开发调试的 Operators，如边缘选择调试工具。
"""

import bpy
from ..Functions.CommonFunctions import Mesh


class HST_OT_DebugSilhouetteEdges(bpy.types.Operator):
    """Debug: 选中所有轮廓边（使用 sharp edge + 排除中间孔洞）"""
    bl_idname = "hst.debug_silhouette_edges"
    bl_label = "Debug Silhouette Edges"
    bl_options = {'REGISTER', 'UNDO'}

    select_mode: bpy.props.EnumProperty(
        name="Select Mode",
        items=[
            ('SILHOUETTE', "Silhouette", "Select silhouette edges (outer boundary + sharp)"),
            ('BEVEL', "Bevel Edges", "Select bevel edges only"),
            ('OUTER_BOUNDARY', "Outer Boundary", "Select outer boundary loops only"),
            ('SHARP', "Sharp Edges", "Select sharp edges only"),
            ('BEVEL_PATH', "Bevel Path", "Find shortest path on bevel edges connecting outer loops"),
            ('BEVEL_LOOPS', "Bevel Loops", "Find closed bevel edge loops (cap separators)"),
            ('SIDE_BOUNDARY', "Side Boundary", "Find boundary between side faces and cap faces (using boundary loops)"),
            ('CAP_BOUNDARY_PARALLEL', "Cap Boundary (Parallel)", "Find cap boundary using parallel area method (for closed shapes)"),
            ('DOUBLE_CAP', "Double Cap", "Find seams for closed shapes with two caps (top and bottom)"),
        ],
        default='SILHOUETTE'
    )

    def execute(self, context):
        import bmesh
        from mathutils import Vector

        mesh = context.active_object
        if mesh is None or mesh.type != 'MESH':
            self.report({'ERROR'}, "请选中一个Mesh对象")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')

        # 读取 sharp_edge attribute
        mesh_data = mesh.data
        sharp_edge_attr = mesh_data.attributes.get("sharp_edge")
        if sharp_edge_attr:
            sharp_edge_values = [d.value for d in sharp_edge_attr.data]
            print(f"[DEBUG] Found sharp_edge attribute with {len(sharp_edge_values)} values")
            print(f"[DEBUG] Sharp edges count: {sum(sharp_edge_values)}")
        else:
            # fallback: 用 edge.use_edge_sharp
            sharp_edge_values = [e.use_edge_sharp for e in mesh_data.edges]
            print(f"[DEBUG] No sharp_edge attribute, using edge.use_edge_sharp fallback")

        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # 获取所有face islands
        all_faces = set(bm.faces)
        islands = []
        visited = set()

        while len(visited) < len(all_faces):
            seed = next(iter(all_faces - visited))
            island = set()
            stack = [seed]
            while stack:
                f = stack.pop()
                if f in island:
                    continue
                island.add(f)
                for edge in f.edges:
                    if not edge.seam:
                        for neighbor in edge.link_faces:
                            if neighbor not in island:
                                stack.append(neighbor)
            visited |= island
            islands.append(island)

        all_silhouette_edges = set()

        for island in islands:
            island_faces = set(island)
            island_edges = set()
            for face in island:
                for edge in face.edges:
                    island_edges.add(edge)

            # CAP_BOUNDARY_PARALLEL: 平行面积法（适用于封闭形状，不依赖 boundary loops）
            if self.select_mode == 'CAP_BOUNDARY_PARALLEL':
                axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
                parallel_areas = [0.0, 0.0, 0.0]

                for face in island_faces:
                    area = face.calc_area()
                    for i, axis in enumerate(axis_vectors):
                        if abs(face.normal.dot(axis)) > 0.7:
                            parallel_areas[i] += area

                axis_idx_local = max(range(3), key=lambda i: parallel_areas[i])
                axis_vec = axis_vectors[axis_idx_local]

                SIDE_THRESHOLD = 0.7

                side_faces = set()
                cap_faces = set()
                for face in island_faces:
                    dot = abs(face.normal.dot(axis_vec))
                    if dot < SIDE_THRESHOLD:
                        side_faces.add(face)
                    else:
                        cap_faces.add(face)

                print(f"[DEBUG CAP_BOUNDARY_PARALLEL] Parallel areas: X={parallel_areas[0]:.4f}, Y={parallel_areas[1]:.4f}, Z={parallel_areas[2]:.4f}")
                print(f"[DEBUG CAP_BOUNDARY_PARALLEL] Axis: {['X', 'Y', 'Z'][axis_idx_local]}, Side: {len(side_faces)}, Cap: {len(cap_faces)}")

                boundary_edges_found = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    linked = [f for f in edge.link_faces if f in island_faces]
                    if len(linked) == 2:
                        f0_is_side = linked[0] in side_faces
                        f1_is_side = linked[1] in side_faces
                        if f0_is_side != f1_is_side:
                            boundary_edges_found.add(edge)

                print(f"[DEBUG CAP_BOUNDARY_PARALLEL] Found {len(boundary_edges_found)} boundary edges")
                all_silhouette_edges |= boundary_edges_found
                continue  # 处理下一个 island

            # DOUBLE_CAP: 双盖模型的边界环检测
            if self.select_mode == 'DOUBLE_CAP':
                boundary_edges_found, axis_idx = Mesh.find_revolve_cap_boundaries(island_faces, island_edges)
                print(f"[DEBUG DOUBLE_CAP] Found {len(boundary_edges_found)} boundary edges, Axis: {axis_idx}")
                all_silhouette_edges |= boundary_edges_found
                continue  # 处理下一个 island


            # 找 boundary loops（SIDE_BOUNDARY 和其他模式需要）
            boundary_edges = [e for e in island_edges if e.is_boundary]
            if len(boundary_edges) < 2:
                # 没有足够的 boundary loops，跳过
                continue

            # 分组 boundary loops
            visited_boundary = set()
            loops = []
            for edge in boundary_edges:
                if edge in visited_boundary:
                    continue
                loop = set()
                stack = [edge]
                while stack:
                    e = stack.pop()
                    if e in loop:
                        continue
                    loop.add(e)
                    for v in e.verts:
                        for linked in v.link_edges:
                            if linked.is_boundary and linked in boundary_edges and linked not in loop:
                                stack.append(linked)
                visited_boundary |= loop
                loops.append(loop)

            if len(loops) < 2:
                continue

            # 计算每个 loop 的中心点，确定主轴
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

            # 通过 loops 的分布确定主轴
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

            # 按主轴排序 loops
            for li in loop_info:
                li['measure'] = li['center'][axis_idx]
            loop_info.sort(key=lambda x: x['measure'])

            start_loop_idx = loop_info[0]['index']
            end_loop_idx = loop_info[-1]['index']
            l1_edges = set(loops[start_loop_idx])
            l2_edges = set(loops[end_loop_idx])
            start_end_boundary_edges = l1_edges | l2_edges

            # ============================================================
            # SIDE_BOUNDARY 模式：用 boundary loops 的 spread 确定主轴
            # 用更严格的阈值，使 bevel 过渡面归入 cap，边界更靠近纯侧面
            # ============================================================
            if self.select_mode == 'SIDE_BOUNDARY':
                axis_vectors = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
                axis_vec = axis_vectors[axis_idx]

                # 降低阈值：dot < 0.3 才算 side face（近乎垂直于主轴）
                # 这样 bevel 过渡面会被归类为 cap，边界边更靠近纯侧面
                SIDE_THRESHOLD = 0.1

                side_faces = set()
                cap_faces = set()
                for face in island_faces:
                    dot = abs(face.normal.dot(axis_vec))
                    if dot < SIDE_THRESHOLD:
                        side_faces.add(face)
                    else:
                        cap_faces.add(face)

                print(f"[DEBUG SIDE_BOUNDARY] Axis from loops spread: {['X', 'Y', 'Z'][axis_idx]}")
                print(f"[DEBUG SIDE_BOUNDARY] spread X={spread_x:.4f}, Y={spread_y:.4f}, Z={spread_z:.4f}")
                print(f"[DEBUG SIDE_BOUNDARY] SIDE_THRESHOLD={SIDE_THRESHOLD}")
                print(f"[DEBUG SIDE_BOUNDARY] Side faces: {len(side_faces)}, Cap faces: {len(cap_faces)}")

                boundary_edges_found = set()
                for edge in island_edges:
                    if edge.is_boundary:
                        continue
                    linked = [f for f in edge.link_faces if f in island_faces]
                    if len(linked) == 2:
                        f0_is_side = linked[0] in side_faces
                        f1_is_side = linked[1] in side_faces
                        if f0_is_side != f1_is_side:
                            boundary_edges_found.add(edge)

                print(f"[DEBUG SIDE_BOUNDARY] Found {len(boundary_edges_found)} boundary edges")
                all_silhouette_edges |= boundary_edges_found
                continue  # 处理下一个 island

            # ============================================================
            # 方法：sharp_edge attribute + bevel edges 连通性检测
            # 1. 外轮廓边 = sharp edges（直接从 attribute）
            # 2. Bevel edges = 法线角度法选中 + 非 sharp
            # 3. 用 bevel edges 做连通性检测区分内外 boundary loops
            # ============================================================

            ANGLE_THRESHOLD = 0.98  # dot < 0.98 意味着角度 > ~11°

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

            print(f"[DEBUG] Edge classification:")
            print(f"  Sharp edges in island: {len(sharp_edges_in_island)}")
            print(f"  Bevel edges: {len(bevel_edges)}")

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
            inner_loops = [i for i in range(len(loops)) if i not in outer_loops]

            print(f"[DEBUG] Connectivity-based Loop classification:")
            print(f"  Total loops: {len(loops)}, Bevel edges: {len(bevel_edges)}")
            print(f"  Connected groups: {connected_groups}")
            print(f"  Outer loops: {outer_loops} (size={len(outer_loops)}, perimeter={best_score[1]:.2f})")
            print(f"  Inner loops (holes): {inner_loops}")

            # 6. 外轮廓 boundary edges
            outer_boundary_edges = set()
            for idx in outer_loops:
                outer_boundary_edges |= loops[idx]

            # 7. 最终轮廓边 = sharp edges + 外轮廓 boundary edges
            silhouette_edges = sharp_edges_in_island | outer_boundary_edges

            print(f"[DEBUG] Result:")
            print(f"  Sharp edges in island: {len(sharp_edges_in_island)}")
            print(f"  Outer boundary edges: {len(outer_boundary_edges)}")
            print(f"  Bevel edges: {len(bevel_edges)}")
            print(f"  Total silhouette edges: {len(silhouette_edges)}")

            # 根据选择模式收集边
            if self.select_mode == 'SILHOUETTE':
                all_silhouette_edges |= silhouette_edges
            elif self.select_mode == 'BEVEL':
                all_silhouette_edges |= bevel_edges
            elif self.select_mode == 'OUTER_BOUNDARY':
                all_silhouette_edges |= outer_boundary_edges
            elif self.select_mode == 'SHARP':
                all_silhouette_edges |= sharp_edges_in_island
            elif self.select_mode == 'BEVEL_PATH':
                # Dijkstra 路径搜索：在 bevel edges 上找连接两个外轮廓 loops 的最短路径
                import heapq

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

                # 获取外轮廓 loops 的顶点（按主轴排序后的首尾）
                if len(outer_loops) >= 2:
                    outer_loop_indices = sorted(outer_loops, key=lambda i: loop_info[i]['center'][axis_idx])
                    loop1_verts = set(v for e in loops[outer_loop_indices[0]] for v in e.verts)
                    loop2_verts = set(v for e in loops[outer_loop_indices[-1]] for v in e.verts)

                    # Dijkstra 搜索
                    path_edges, path_cost = find_bevel_edge_path(loop1_verts, loop2_verts, bevel_edges)

                    print(f"[DEBUG BEVEL_PATH] outer_loops: {outer_loops}")
                    print(f"[DEBUG BEVEL_PATH] loop1_verts: {len(loop1_verts)}, loop2_verts: {len(loop2_verts)}")
                    print(f"[DEBUG BEVEL_PATH] bevel_edges: {len(bevel_edges)}")
                    print(f"[DEBUG BEVEL_PATH] path found: {len(path_edges)} edges, cost: {path_cost:.4f}")

                    if path_edges:
                        all_silhouette_edges |= set(path_edges)
                else:
                    print(f"[DEBUG BEVEL_PATH] Not enough outer loops: {len(outer_loops)}")
            elif self.select_mode == 'BEVEL_LOOPS':
                # 找闭合 bevel edge loops（用于分离 cap 和 side 区域）
                # 条件：每个顶点恰好连接 2 条 bevel edges = 形成闭合环

                # 1. 统计每个顶点连接的 bevel edge 数量
                vert_bevel_count = {}
                for e in bevel_edges:
                    for v in e.verts:
                        vert_bevel_count[v] = vert_bevel_count.get(v, 0) + 1

                # 2. 只保留两端顶点都恰好连接 2 条 bevel edges 的边
                loop_candidate_edges = set()
                for e in bevel_edges:
                    v0_count = vert_bevel_count.get(e.verts[0], 0)
                    v1_count = vert_bevel_count.get(e.verts[1], 0)
                    if v0_count == 2 and v1_count == 2:
                        loop_candidate_edges.add(e)

                # 3. 分组成独立的闭合环
                closed_loops = []
                visited_edges = set()
                for start_edge in loop_candidate_edges:
                    if start_edge in visited_edges:
                        continue
                    # Flood fill 找连通的边
                    loop = set()
                    stack = [start_edge]
                    while stack:
                        e = stack.pop()
                        if e in loop:
                            continue
                        loop.add(e)
                        for v in e.verts:
                            for linked in v.link_edges:
                                if linked in loop_candidate_edges and linked not in loop:
                                    stack.append(linked)
                    visited_edges |= loop
                    closed_loops.append(loop)

                print(f"[DEBUG BEVEL_LOOPS] Bevel edges: {len(bevel_edges)}")
                print(f"[DEBUG BEVEL_LOOPS] Loop candidate edges: {len(loop_candidate_edges)}")
                print(f"[DEBUG BEVEL_LOOPS] Found {len(closed_loops)} closed loops:")
                for i, loop in enumerate(closed_loops):
                    perimeter = sum(e.calc_length() for e in loop)
                    print(f"  Loop {i}: {len(loop)} edges, perimeter: {perimeter:.4f}")

                # 选中所有闭合环的边
                for loop in closed_loops:
                    all_silhouette_edges |= loop

        # 取消所有选择，然后选中对应的边
        for e in bm.edges:
            e.select = False
        for v in bm.verts:
            v.select = False
        for f in bm.faces:
            f.select = False

        for e in all_silhouette_edges:
            e.select = True

        bm.to_mesh(mesh.data)
        bm.free()

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)

        mode_names = {'SILHOUETTE': 'silhouette', 'BEVEL': 'bevel', 'OUTER_BOUNDARY': 'outer boundary', 'SHARP': 'sharp', 'BEVEL_PATH': 'bevel path', 'BEVEL_LOOPS': 'closed bevel loops', 'SIDE_BOUNDARY': 'side boundary', 'CAP_BOUNDARY_PARALLEL': 'cap boundary (parallel)', 'DOUBLE_CAP': 'double cap'}
        self.report({'INFO'}, f"选中了 {len(all_silhouette_edges)} 条 {mode_names[self.select_mode]} 边")
        return {'FINISHED'}
