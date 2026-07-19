# Blender Bevel V2 Straight Skeleton 评估

> 日期：2026-07-19  
> 范围：只读核对 Blender 官方 issue、官方 GitHub 镜像 `bevelv2` 分支源码，以及与本项目 Pipe Cut 方案的关系。  
> 核对提交：`7501d4664889988ef9780e01e81b725b02469182`（2023-03-11，`bevelv2` 当前远端 HEAD）。

## 结论

`bevelv2` **确实包含一套相当完整的 Straight Skeleton / Mesh Inset C++ 原型源码**，不是只有设计草稿：有公开接口、3D TriangleMesh、wavefront/event queue、edge-collapse/vertex、split、flip、closing 等事件处理，也有单元测试和一次 Bevel Mesh node 的 face-inset 调用。

但它**不是现在可直接复用的生产级算法**。最关键的一手证据是作者 Howard Trickey 在 2025 年明确说明，这套 straight-skeleton 代码有 bug，调试大模型时卡住，因此新 Bevel V0 放弃 overlap/collision merging；2026 年又说明 straight skeleton merging 尚未进入首发，之后才会继续。源码本身也停留在 Blender 3.6 alpha 时代，含未完成接口、硬编码 epsilon、断言式失败、多个 TODO，且没有成为当前 Blender 的公共 Python API。

因此对 HST 的建议是：**可把它当作算法研究样本或未来 C++ backend spike 的起点，不应把它当成可从 Python 插件直接调用、能替换当前 Pipe Cut junction patch 的现成依赖。**

## 一手证据

### 1. 现成源码在哪里

- 公开接口 [`source/blender/blenlib/BLI_mesh_inset.hh`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L8-L10) 明说这是“基于 2D Straight Skeleton construction 的 3D mesh inset algorithm”。
- 同一头文件的[算法说明](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L29-L58)定义了：轮廓边以恒速 wavefront 前进；边塌缩或撞向对侧边时修改拓扑；可在指定推进量停止；并将 2D 方法适配到 3D surface、跨越内部几何，另支持沿 face normal 的 slope。
- 唯一公开入口是 [`mesh_inset_calc(const MeshInset_Input &)`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L73-L108)。
- 实现在 [`source/blender/blenlib/intern/mesh_inset.cc`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc)。核心内部类型是 [`SkeletonVertex`、`SkeletonEvent`、`StraightSkeleton`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L1300-L1582)。
- 构建入口已接到 Blenlib：[`CMakeLists.txt`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/CMakeLists.txt#L118) 编译实现，并在同文件列出 header/test。
- 该分支还有 [`BLI_mesh_inset_test.cc`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/tests/BLI_mesh_inset_test.cc)，覆盖 Tri、Quad、Square、Pentagon、Hexagon、Splitter、Flipper、Grid，主要断言输出顶点/面数量，少量验证坐标。
- 原型甚至接入过 [`node_geo_bevel_mesh.cc`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/nodes/geometry/nodes/node_geo_bevel_mesh.cc#L1832-L1894)：对选中单 face 构造 `MeshInset_Input`，调用 `mesh_inset_calc`，再重建输出。但 `use_regions` 仍是 TODO，属性复制也多处标为 TODO。

### 2. 算法阶段、输入与输出

公开输入 [`MeshInset_Input`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L73-L85)：

- `vert`：3D 顶点坐标；
- `face`：每个 face 的 CCW 顶点索引；
- `contour`：要 inset 的一个或多个闭环，区域在有向 contour 左侧；
- `inset_amount`、`slope`、`need_ids`。

公开输出 [`MeshInset_Result`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L87-L100)：新顶点、新 faces、最终 contours，以及 output→input 的 `orig_vert` / `orig_face` 映射。

实现流程：

1. [`triangulate_input`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L3109-L3128) 将输入 faces 三角化、连接邻接并加 ghost triangles。
2. [`StraightSkeleton::compute`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2432-L2543) 初始化 inset contour、标记内部区域、建立 moving/stationary SkeletonVertex、推入初始事件，然后按最小 height 处理 priority queue，达到 `target_height` 即停止。
3. 事件分类和拓扑更新包括：[`handle_vertex_event`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2162-L2217)、[`handle_split_event`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2219-L2348)、[`handle_flip_event`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2350-L2419)、[`handle_closing_event`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2421-L2430)。split/collision 分支会判断 reflex vertex，并在碰撞位置拆分 wavefront。
4. [`mesh_inset_calc`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L3395-L3453) 串起 triangulation、StraightSkeleton、可选 slope displacement 和结果重建。

这说明它解决的核心是：**在给定 surface mesh 上推进闭合 contour，并在 offset wavefront 相撞/消失时改变拓扑**，而非生成任意 3D 管道 Boolean union，也不是通用“给 junction hole 自动做 quad patch”的库。

### 3. 为什么不能称为生产可用

最强证据来自作者本人：

- [2023-06-20](https://projects.blender.org/blender/blender/issues/98674#issuecomment-962609)：作者称遇到 hard bugs，暂停 Bevel V2。
- [2025-03-24](https://projects.blender.org/blender/blender/issues/98674#issuecomment-1528586)：作者明确说项目因 straight-skeleton code 有 bug、修复成本太高而搁浅；新的 V0 只复现旧 bevel，不处理 collision/overlap。
- [2026-05-01](https://projects.blender.org/blender/blender/issues/98674#issuecomment-1918332)：作者称早先调试大案例出错时再次卡住；首发不会有 “eat vertices” / “straight skeleton merging”。
- [2026-06-04](https://projects.blender.org/blender/blender/issues/98674#issuecomment-1947839)：当前 bevel node 的过大 offset 仍会 glitch，未来才用 straight skeleton merging 代替 clamp。
- [2026-06-09](https://projects.blender.org/blender/blender/issues/98674#issuecomment-1953376)：作者仍用“if I later add skeleton merging”描述它；当前建议是预处理 offsets 做 clamp。

源码侧风险与上述状态一致：

- 分支 HEAD 是 2023-03-11，版本头仍是 [Blender 3.6 alpha](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenkernel/BKE_blender_version.h#L20-L24)，不是可直接 cherry-pick 到 Blender 5.x 插件的现代实现。
- header 仍写着[接口最终稳定后再补 extras 文档](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L60-L70)。
- 无事件时直接 `BLI_assert(false)`，注释称“probably a bug”：[compute L2509-L2513](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2509-L2513)。
- 使用固定 `1e-5` 的运动/碰撞阈值：[L1737-L1738](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L1737-L1738)，对 CAD tessellation 的尺度差异、近共面和 simultaneous events 都是风险。
- contour 顶点重复使用仍未处理：[L2463-L2478](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L2463-L2478)。
- 内部 face preservation 仍是 TODO：[L3355-L3363](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/intern/mesh_inset.cc#L3355-L3363)。
- 测试数量有限，且大多数只断言顶点/面总数；没有本项目截图所示“圆孔闭环 + 直边 + 圆柱”等 CAD junction 语义验收。
- 它是 Blender C++ 内部 `BLI` 接口；没有 `bpy` 暴露。Python addon 无法直接 import/call，除非修改并自编 Blender，或移植成自有原生扩展。

### 4. 许可证与可移植性

- 两个核心文件 SPDX 都是 [`GPL-2.0-or-later`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/source/blender/blenlib/BLI_mesh_inset.hh#L1)；Blender 的 [`COPYING`](https://github.com/blender/blender/blob/7501d4664889988ef9780e01e81b725b02469182/COPYING) 也声明 Blender 仅按 GNU GPL 提供。
- 技术上并非独立小算法：实现依赖大量 Blender `BLI_*` 容器、数学、polyfill、memory arena 和断言设施，并自带一整套 TriangleMesh/ghost-triangle/topology machinery。移植不只是复制 `StraightSkeleton` 类。
- 若复制/改写到本插件并分发，必须按 GPL 义务处理衍生代码与分发；这不是法律意见。即便许可兼容，Python addon 还需解决 C++ 二进制、Blender ABI/平台打包与 5.x API 维护成本。

## 与当前 Pipe Cut / corner cases 的关系

Blender issue 的原始目标与本项目痛点高度相关：issue 把 overlap/merge 定义为 offset edges 相交后通过 merge/split 消除重叠，并指出 Straight Skeleton 的中间状态是 2D 解法；作者也曾在 [2022-06-14](https://projects.blender.org/blender/blender/issues/98674#issuecomment-125355) 回应 Pipe Boolean 思路，表示当前更倾向 Straight Skeleton，因为它能处理 concave angle 下 advancing edges 的交汇/合并。

对当前 handoff 的具体判断：

| HST 阶段/问题 | Straight Skeleton 原型能提供什么 | 不能直接提供什么 |
|---|---|---|
| Regular strip / rails | 用 wavefront 统一定义 offset 边推进，并自然产生 edge collapse，能减少靠固定 `junction_margin` 猜停止位置 | 它的输入是 surface 上闭合 contour，不直接接受 Pipe Union 后任意 BoundaryGraph |
| 凹角、窄面、offset 相撞 | vertex/split/closing events 正是为这些拓扑变化设计 | 当前实现有作者确认的 hard bugs，且 fixed epsilon 对 CAD 近退化输入风险高 |
| 多 contour 相撞 | 接口允许多个 contours，注释明确考虑另一 contour 的碰撞 | 没有证据证明可稳定通过“孔 loop + 直边/曲边 + 多圆柱”验收 |
| Junction patch | skeleton/event history 可作为 junction 拓扑骨架或 ports/setback 的更原则化依据 | 不输出符合 HST 目标的 quad-dominant Vertex Mesh；输出主要是 inset 后 mesh faces |
| Pipe cutter Boolean | 无需先生成圆管 cutter 就能表达 surface offset 的相撞 | 不等价于 constant-radius rolling-ball / tube subtraction，不替代 3D Exact Boolean |
| Python 插件落地 | 可借鉴事件模型、测试样例和输入/输出设计 | 无 `bpy` API；要自编 Blender或维护 GPL 原生扩展，无法作为短期 addon 依赖 |

截图中箭头指向的“直边 chamfer strip 接圆柱/孔边时过早终止或产生不规则 notch”，本质上是多个 offset fronts 在非平凡 surface 邻接上的 collision/ownership 问题。Straight Skeleton 的思想比“每根 Pipe 独立做 strip，最后猜 junction hole”更接近问题本质；但 `bevelv2` 代码没有把该截图变成一个已验证的现成解。

## 建议的讨论方向

1. **短期不替换当前 Pipe Cut 实验。** 保留 Boolean cutter 作为几何 oracle，继续将 Regular Strip 与 Junction Region 分开；不要把本原型承诺为 corner-case 修复。
2. **把 Straight Skeleton 作为窄范围 spike。** 若要验证，只选一个局部、可展平/近共面的 surface patch，将两条 rails/feature contours 转成 `MeshInset_Input` 等价数据，先测截图的 two-pipe junction、孔 loop + open chain、凹角 collapse 三类；失败即停止扩大范围。
3. **先决定语义再选算法。** 若目标是“surface 上固定 offset 的 chamfer”，skeleton 值得深入；若目标仍是“圆管体积切除后的真实边界”，skeleton 只能辅助 ports/junction topology，不能替代 Pipe Boolean。
4. **不要直接 vendoring。** 在证实算法语义和案例覆盖前，不承担 Blender 3.6-era C++、GPL、ABI 和跨平台打包成本。更合理的是先把 event types、simultaneous-event、scale-aware tolerance 和 regression corpus 抽象成技术评估清单。

## 最终判断

- “bevelv2 里面有没有 Straight Skeleton？”——**有，而且有可编译接口、实现和测试。**
- “有没有现成可用的 Straight Skeleton？”——若“可用”指生产插件直接依赖、稳定覆盖本项目 corner cases，**没有**。
- “是否值得研究？”——**值得**，因为它的 wavefront + topology-event 模型直接命中当前 offset collision/junction 问题；但应作为算法参考/受控 spike，而不是当前 Pipe Cut 的即插即用替代品。
