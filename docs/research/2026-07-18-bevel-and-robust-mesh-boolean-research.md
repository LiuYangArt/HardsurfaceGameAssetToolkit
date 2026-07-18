# Bevel 与 Robust Mesh Boolean 算法调研

> 日期：2026-07-18
> 关联方案：docs/plan/2026-07-18-experimental-pipe-chamfer-operator-handoff.md
> 目标：为 Sharp Edge → Multi-Pipe → Boolean Cut → Edge Mesh → Vertex Mesh 寻找可落地算法。

## 1. 结论

当前方案可继续，但应增加两条硬要求：

1. Patch 分层：
   Edge Mesh → Boundary Ports → 2-port stitch / Pipe Joint constraint / 3+ port Vertex Mesh → 通用 hole filling 兜底。
2. Boolean 必须返回 Face Provenance：
   每个输出 Face 来自 source 还是某根 Pipe、对应哪个输入 Face、哪些 Edge 是新交线。不能默认依赖 nearest-distance 猜 cutter-derived Faces。

推荐顺序：

1. Blender Exact + Face attribute provenance probe。
2. Blender Manifold solver 做 A/B。
3. Direct Mesh Booleans 做外部 C++ backend spike。
4. CGAL PMP 只做离线 oracle。
5. Junction 先实现 setback ports，再实现通用 hole filling。

## 2. Bevel / Junction 算法

### 2.1 Blender Bevel V2

来源：

- [Bevel V2 issue](https://projects.blender.org/blender/blender/issues/98674)
- [bmesh_bevel.cc](https://projects.blender.org/blender/blender/src/branch/main/source/blender/bmesh/tools/bmesh_bevel.cc)
- [bevelnode2 分支](https://projects.blender.org/howardt/blender/src/branch/bevelnode2)

最有价值的问题分解：

    Offset / Cut
    → Edge Mesh
    → Boundary Points / Ports
    → Vertex Mesh

对应当前方案：

- Edge Mesh：红色 regular chamfer strip。
- Boundary Ports：strip 在 junction setback 截面的端点。
- Vertex Mesh：蓝色 junction patch。

Issue 中直接出现过同一 Tube Boolean 路线：

- [Tube Boolean 提议](https://projects.blender.org/blender/blender/issues/98674#issuecomment-125353)
- [Howard 的 Straight Skeleton 回应](https://projects.blender.org/blender/blender/issues/98674#issuecomment-125355)

Howard 没有否定 Tube Boolean；选择 Straight Skeleton 是因为它能表达 offset fronts 的 collision、merge 和 concave events。后来 Straight Skeleton merging 因复杂案例难调而推迟。

可直接采用的 Junction dispatch：

- 2 ports 且 profile 兼容：direct stitch。
- 2 ports 但要求 miter：小型 Vertex Mesh。
- 3+ ports：通用 Vertex Mesh。
- 存在近共线 straight-through pair：先保持贯穿 Pipe profile，再填剩余区域。

最后一种是 Blender 所称 Pipe Joint。普通填洞容易鼓包，相关点必须 constrain/snap 到贯穿 junction 的 profile。

### 2.2 Setback Vertex Blending

- Várady & Rockwood, Geometric construction for setback vertex blending, CAD 1997。
- [原文入口](https://www.sciencedirect.com/science/article/pii/S001044859600070X)

核心：

- Edge blends 不延伸到互相穿插。
- 在 junction 前选择 setback 截面。
- 每个 edge blend 在截面形成稳定 port。
- ports 之间构造小型 multi-sided vertex blend。

这比从 Boolean 碎边被动判断蓝区更强。建议：

- 由 Pipe overlap 和 stable cross-section 计算 setback；
- red Edge Mesh 精确停止在 ports；
- blue Vertex Mesh 只处理受控小区域。

### 2.3 Straight Skeleton

来源：

- [Weighted Straight Skeletons in the Plane](https://www.sciencedirect.com/science/article/pii/S0925772114000807)
- [作者项目](https://www.cosy.sbg.ac.at/~held/projects/wsk/wsk.html)
- [Eder & Held 2018 PDF](https://www.geder.at/static/research/2018/2018%20Eder%2C%20Held%20-%20Computing%20Positively%20Weighted%20Straight%20Skeletons%20of%20Simple%20Polygons%20Using%20an%20Induced%20Line%20Arrangement%2C%20IPL%202018%20%5BEdHe18a%5D.pdf)
- [CGAL Straight Skeleton 2](https://doc.cgal.org/latest/Straight_skeleton_2/index.html)

可解决 offset collision、short-edge disappearance、front merge/split、不同传播速度和 clamp/setback 上限。

限制：

- 核心是 planar polygon。
- 不是任意 3D Pipe Union junction hole 的通解。
- 应用于本项目需要 Surface Patch 或局部 junction 展平。
- Blender 团队已有较高实现和 debugging 成本。

结论：不做 MVP 前置；二期用于 clearance、setback limit 和吃掉短边/顶点。

### 2.4 Rolling-Ball / Canal Surface

CAD constant-radius fillet 通常是球心沿两个支持面的等距 locus 移动，并取球族 envelope。

重要区别：

- 沿 tessellated feature polyline 扫圆 Tube，不一定等价于严格 rolling-ball fillet。
- 只有特定支持面和轨迹条件下等价。

第一版术语应为 Uniform Tube-Cut Chamfer，不声称严格 CAD Constant-Radius Fillet。未来完成 Surface Patch 拟合后再研究 rolling-ball。

### 2.5 Hole Filling

#### Liepa 2003

- Peter Liepa, Filling Holes in Meshes。
- [Eurographics DOI](https://doi.org/10.2312/SGP/SGP03/200-205)
- [CGAL hole filling](https://doc.cgal.org/latest/Polygon_mesh_processing/group__hole__filling__grp.html)

流程是 boundary triangulation → refinement → fairing。适合作为蓝区兜底，但不能天然保持 Pipe profile、straight-through pair 或 Surface Patch constraints。

#### Levin / Poisson 类

- [Levin hole filling 入口](http://www.math.tau.ac.il/~levin/adi/paper8.htm)

适合高段数 smooth patch。当前 segments=1 mid-poly 不应优先使用，避免无约束鼓包。

## 3. Direct Mesh Booleans（2026）

- Čižmarik & Španěl, Direct Mesh Booleans: A Step towards Non-Restrictive Boolean Operations。
- [DOI](https://doi.org/10.5220/0014043800004728)
- [SCITEPRESS](https://www.scitepress.org/Link.aspx?doi=10.5220/0014043800004728)
- [官方 MIT 源码](https://github.com/RomanCizmarik/Direct-Mesh-Booleans)

### 3.1 论文主张

- 直接处理 triangle meshes，不转 voxel。
- 接受 open boundary、non-manifold 和 self-intersection。
- exact computations 保证数值稳定。
- 轻量 regularization 尽量生成 two-manifold output，必要时允许 open boundary。
- 在 Thingi10K 上报告 reliability、robustness、speed 优于 prior art。
- 支持 Union、Intersection、Difference。

### 3.2 公开源码流程

依赖 Eigen、OpenMesh、FaRMA、exact/indirect predicates、TBB 和 C++20。

流程：

1. 输入 TriangleSoup：coordinates、triangles、per-triangle labels。
2. FaRMA solveIntersections 建 exact mesh arrangement。
3. 保留 implicit exact intersection points，输出 approximate coordinates。
4. 为 operands 构建 manifold representation。
5. 识别 coplanar faces 和 intersection edges。
6. 对 connected components 做 volume / inside-outside classification。
7. Boolean predicate 决定 fragment：discard、keep 或 keep-and-flip。
8. 构建 result manifold mesh并处理 non-manifold vertices。

Difference 中，cutter 位于 source 内部的 fragments 会翻转成为新 cut surface。因此 cutter-derived Faces 在算法内部天然可知。

### 3.3 Provenance

公开 Interface有 copyFunctor(result, meshArrangement)：

- arrangement 保留 per-triangle labels；
- intersection edge/face flags；
- coplanar flags；
- inside/outside labels；
- component IDs。

可由 wrapper 输出：

- output_face_operand_id；
- output_face_source_face_id；
- output_face_pipe_id / owner bitset；
- output_edge_is_intersection；
- output_face_is_cutter_surface。

若只调用示例 executable 并用 OBJ/STL 往返，provenance 会丢失。应链接库加 C ABI/Python binding，或扩展示例输出 sidecar JSON。

### 3.4 集成判断

优势：

- MIT。
- Windows 11 tested。
- 输入限制明显比 Manifold/CGAL PMP宽松。
- 对 dirty CAD triangle soup 很有研究价值。
- provenance 所需底层数据已存在。

成本：

- 无现成 Python binding。
- C++20 + OpenMesh + FaRMA + exact predicates + TBB，构建和分发成本高。
- 项目较新，源码仍有 TODO 和失败路径。
- 论文允许 open output，而本项目成功仍需 closed manifold。

建议做独立 backend spike，不立即替换 Blender Exact。第一版输出 mesh + provenance sidecar JSON，并用同一 fixtures 对比 Exact、Manifold、DMB。

## 4. Boolean Backend 候选

### 4.1 Blender Exact — MVP 首选

官方源码：

- [BLI exact Boolean](https://github.com/blender/blender/blob/blender-v5.0-release/source/blender/blenlib/BLI_mesh_boolean.hh)
- [mesh_boolean.cc](https://github.com/blender/blender/blob/blender-v5.0-release/source/blender/geometry/intern/mesh_boolean.cc)
- [Geometry Boolean Interface](https://github.com/blender/blender/blob/blender-v5.0-release/source/blender/geometry/GEO_mesh_boolean.hh)

优势：

- 无额外依赖。
- exact mesh arrangement。
- 内部输出 Face 有 input Face mapping，并复制 Face CustomData/material。

第一优先 probe：

1. source Faces写 hst_operand_id=0 和 hst_source_face_id。
2. 每根 Pipe Faces写 hst_operand_id=pipe_id 和 hst_source_face_id。
3. Exact Union / Difference evaluate + apply。
4. 检查 Face attributes coverage。
5. 按 operand_id 删除 cutter Faces。

若传播完整，BVH nearest classifier只能作为 fallback。

### 4.2 Manifold — 最佳 A/B

- [Manifold](https://github.com/elalish/manifold)
- [manifold3d](https://pypi.org/project/manifold3d/)
- Apache-2.0。

优势：

- 目标是 guaranteed manifold output。
- BatchBoolean适合多 Pipe。
- Python binding现成。
- MeshGL original ID / face mapping支持 provenance。
- Blender 已集成 Manifold solver时可直接测试。

限制：

- 输入必须是 correctly oriented 2-manifold solid。
- Merge不能修复真正 non-manifold CAD。

### 4.3 Interactive and Robust Mesh Booleans / FaRMA

- [2022 paper](https://www.gianmarcocherchi.com/pdf/interactive_exact_booleans.pdf)
- [源码](https://github.com/gcherchi/InteractiveAndRobustMeshBooleans)
- [2020 arrangement paper](https://www.gianmarcocherchi.com/pdf/mesh_arrangement.pdf)
- [FaRMA](https://github.com/gcherchi/FastAndRobustMeshArrangements)

DMB建立在 FaRMA上并进一步处理 non-manifold/open/self-intersecting inputs。不建议单独集成 FaRMA；论文适合理解 arrangement、exact predicates 和 provenance。

### 4.4 CGAL PMP — 离线 Oracle

- [Corefinement](https://doc.cgal.org/latest/PMP_Boolean_operations/group__PMP__corefinement__grp.html)
- [PMP](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html)
- [License](https://www.cgal.org/license.html)

优点：exact kernel、intersection polylines、visitor/property maps。限制：通常要求 triangulated、orientable、closed 2-manifold，Windows集成重，并涉及 GPL/commercial license。适合离线正确性 oracle。

### 4.5 libigl CGAL

- [mesh_boolean.h](https://github.com/libigl/libigl/blob/main/include/igl/copyleft/cgal/mesh_boolean.h)

输出 J：每个 result Face 对应输入 birth facet。J 是本项目 provenance Interface 的最佳参考，但仍有 CGAL copyleft依赖。

### 4.6 Geogram

- [Geogram](https://github.com/BrunoLevy/geogram)
- [CSG builder](https://github.com/BrunoLevy/geogram/blob/main/src/lib/geogram/mesh/mesh_CSG_builder.h)

BSD-3，有 exact predicates、CSG、repair；但 provenance contract不如 DMB/libigl/Manifold明确。可做宽松许可证后续候选。

### 4.7 CGAL Nef_3 与 Cork

- [CGAL Nef_3](https://doc.cgal.org/latest/Nef_3/index.html)
- [Cork](https://github.com/gilbo/cork)

Nef集合表达力强但开销/许可证/转换成本高，只作病态案例研究。Cork长期无人维护且有已知问题，排除。

## 5. BooleanBackend Interface

建议深模块 Interface：

    boolean_result = boolean_backend.evaluate(
        source_mesh,
        cutter_meshes,
        operation="SOURCE_MINUS_UNION_CUTTERS",
        require_closed_manifold=True,
        require_provenance=True,
    )

结果至少包括：

    mesh
    face_birth_operand
    face_birth_index
    face_pipe_owners
    edge_is_intersection
    ambiguous_face_count
    boundary_edge_count
    non_manifold_edge_count
    zero_area_face_count
    backend

成功条件：

- provenance coverage = 100%；
- source/cutter classification无 ambiguous；
- output closed manifold；
- 交线拓扑可提取；
- 无 zero-area/sliver/self-intersection；
- topology hash确定。

Backend排序：

1. BLENDER_EXACT；
2. BLENDER_MANIFOLD；
3. DMB_EXTERNAL；
4. CGAL_ORACLE。

## 6. 对现方案的修改建议

1. BVH nearest classifier降级为 fallback：
   - 主路径是 Face-domain operand/source IDs；
   - evaluate/apply 后验证 coverage；
   - 丢失才使用 BVH，并标记 degraded。

2. Patch正式采用：
   - EdgeMeshBuilder；
   - BoundaryPortExtractor；
   - VertexMeshBuilder。

3. Junction先计算 setback ports，不只依赖 fixed junction_margin。

4. Junction dispatch：

       2-port compatible → direct stitch
       straight-through pair → Pipe profile constraint + fill residual
       3+ ports → setback vertex patch
       generic failure → constrained triangulation / Liepa fairing

5. 增加 Exact / Manifold / DMB backend A/B tests。

6. 增加 provenance regression：
   source IDs、per-Pipe IDs、Union multi-owner、Difference cutter Faces、删除后的 BoundaryGraph。

7. 将严格 constant-radius CAD fillet表述改为 uniform tube-cut chamfer。

## 7. 验证矩阵

几何：

- 两 Pipe L junction；
- T junction；
- three-pipe cube corner；
- straight-through Pipe Joint；
- closed hole Pipe + open Pipe；
- 不同半径圆柱 feature；
- near-tangent；
- coplanar/sliver；
- dirty CAD：duplicate triangles、self-intersection、small open boundary、non-manifold vertex。

Backends：

- Exact；
- Manifold；
- DMB。

指标：

- status；
- runtime；
- output counts；
- provenance coverage；
- intersection-edge count；
- boundary/non-manifold count；
- zero-area/sliver count；
- self-intersection count；
- deterministic topology hash；
- Patch 后 watertight。

## 8. 最终推荐

短期：

- 不换 Boolean。
- 先证明 Blender Exact能传播 Face provenance。
- 实现 Edge Mesh / Ports / Vertex Mesh。
- Junction用 setback + dispatch，不一律 triangulate。

中期：

- 加 Manifold A/B。
- 编译 DMB独立 spike，重点验证 dirty CAD与 provenance。
- 若 DMB显著提高成功率，再决定 C++ extension或 helper executable。

长期：

- Straight Skeleton只用于 offset collision / short-edge disappearance。
- Rolling-ball只在 Surface Patch拟合成熟后研究。
- Liepa/Poisson用于高段数 smooth junction，不作为首版 mid-poly。
