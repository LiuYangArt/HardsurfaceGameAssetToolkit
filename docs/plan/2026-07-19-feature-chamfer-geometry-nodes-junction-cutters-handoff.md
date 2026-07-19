# Feature Chamfer — Geometry Nodes Junction Cutter Handoff

> 日期：2026-07-19  
> Blender：5.1.2（项目目标 5.0+）  
> 输入试件：`C:/Users/LiuYang/Desktop/pipe-chamfer/pipe-chamfer-mixed.blend`  
> 状态：方案评估通过，尚未修改插件代码或用户 `.blend`

## 1. 结论

继续 Pipe Cut 路线是合理的。当前 Geometry Nodes 已证明：

- `sharp_edge → Mesh to Curve → Curve to Mesh` 能覆盖绝大多数 regular feature；
- 当前失败集中在少量 `degree >= 3` 的 Sharp FeatureGraph junction；
- `PATCHED` 已能在 Boolean 产生简单边界后完成 Bridge + Fill；
- 所以下一阶段应把问题收敛为 **Junction-aware Cutter Builder**，而不是替换补面器，也不是先移植 Straight Skeleton。

推荐 cutter：

```text
Regular tubes
+ open-end capsules
+ topology-junction spheres
+ optional spatial-junction spheres/capsules
→ Realize Instances
→ Mesh Boolean Union（先按 junction cluster）
→ source Difference
```

关键原则：junction 必须有正体积 overlap；不能只让几根 Tube 在同一 Sharp Vertex 点接触或共端面。

## 2. MCP 实测

Blender MCP 在本轮评估期间可用，并成功连接到上述 `.blend`：

- Blender：5.1.2；
- active Object：`Extruded.002`；
- Geometry Nodes modifier：`GeometryNodes`；
- node group：`pipecut`；
- 当前核心链：`Named Attribute(sharp_edge) → Mesh to Curve → Curve to Mesh`；
- `Curve Circle`：resolution 8，radius 0.02；
- `Boolean Pro`：Slice / Exact / Sequential / Self Intersection；
- Group Output 当前仍直通原 Geometry；Boolean 结果只用于预览。

MCP 只做了读取和临时依赖图 probe；没有保存 `.blend`，最终已恢复 `Fill Caps=False` 与原 Group Output wiring。一次较重的 evaluated-mesh probe 之后 transport 曾断开；正式编辑前需确认 Blender 内 MCP server 已重新启动并完成一次只读 round-trip。

## 3. 试件暴露的结构

`Extruded.002`：

- 1307 vertices / 1988 edges / 683 faces；
- 990 条 Sharp Edges；
- Sharp vertex degree：`degree-2 = 971`、`degree-3 = 10`、`degree-4 = 2`；
- 13 个 Sharp graph components；
- 只有 12 个真正的 topology junction vertices。

这说明不应重写全部 Pipe 生成：regular 区已占绝大多数，适合只在 junction 做局部补强。

当前未封端的 `Curve to Mesh` 输出经 MCP 临时接到 Group Output 后为：

- 8072 vertices / 15992 edges / 7920 faces；
- 304 boundary / non-manifold edges。

临时打开 `Fill Caps` 后 face 数变为 7958，说明存在 38 个 open curve ends（19 个 open splines）。单纯封端仍不解决多 Tube 在 junction 处的点接触和自交；它只是生成 Boolean 所需 closed operands 的最低条件。

## 4. 当前 Geometry Nodes 的根因

`Mesh to Curve` 会把整个选中 Sharp edge network 输出成 curve splines，但它不提供 FeatureGraph 语义：

- degree-2：适合直接 sweep；
- degree-3：Tube 在一点形成 T/Y junction；
- degree-4：可能是两条直通 strands，也可能是真正四叉 junction；
- Curve to Mesh 不会为这些交汇自动生成 manifold tube union。

因此截图箭头处不是 curve sweep 本身缺一段，而是多个 surface 在 junction 只接触/互穿，交给 Exact Boolean 后拓扑依赖半径、采样和运算顺序。

## 5. 推荐的 Geometry Nodes 原型

### 5.1 Regular Tube 分支

1. 读取 `sharp_edge`。
2. `Mesh to Curve`。
3. `Curve to Mesh`，圆形 profile，必须 `Fill Caps=True`。
4. 保留现有管线作为 regular cutter。

不要在首轮尝试用 GN 内部彻底拆成所有 Pipe Groups。插件已有 FeatureGraph，可以给 Geometry Nodes 写入明确 attributes；GN 只负责可视化/原型和生成 cutter geometry。

### 5.2 Topology Junction 分支

在原 Mesh 上计算每个 vertex 的 selected Sharp Edge degree：

```text
degree = 选中 Sharp Edges 在 Vertex domain 的计数
junction = degree != 2
```

对 `degree >= 3` 的 vertex 实例化 Icosphere 或 UV Sphere：

- 理论 radius：`pipe_radius`；这是 Sharp graph 与半径球的 Minkowski sum 在 graph vertex 处应有的 junction ball，不是任意填充物；
- Boolean robustness inflation 初始只取 `1.005r .. 1.02r`，不要直接用明显改变槽宽的 1.05r；
- sphere center：原 Sharp Vertex；
- 目标：覆盖所有 incident Tube 的端部，形成正体积 overlap；
- sphere 过大会扩大实际槽宽，因此以最小能稳定 Union 的 factor 为准；若超过 `1.02r` 才能成功，应先诊断 Tube cap、profile tessellation 或 Boolean tolerance，而不是继续放大。

端点 `degree == 1` 另用 sphere 或沿 tangent 的 capsule 延长；不要用平 cap 刚好终止在 source surface 上。

### 5.3 Degree-4 分类

degree-4 先分类：

- 若四条 tangent 可唯一配成两组近反向方向：生成两条连续 strands，junction sphere 仅作很小 overlap；
- 否则按真实四叉 junction，使用 sphere。

分类应由插件 FeatureGraph 完成，不建议仅靠 GN node tree 维护复杂 tangent pairing。

### 5.4 Spatial Junction 分支

Topological junction 之外，非邻接 Sharp curves 也可能在空间上相距 `< 2r`。

首版只检测：

- curve segment AABB broad phase；
- segment-segment minimum distance；
- 距离 `< 2r + tolerance` 时建立 spatial junction cluster。

对 cluster 生成：

- 一个 sphere，或
- 沿两 segment 最近点之间的 short capsule。

这部分用 Python/BVH 实现更合适；纯 GN 做 all-pairs 检测复杂且不利于诊断。

### 5.5 Union 策略

不要把所有互穿 Tube 直接 Join 成一个自交 Mesh 再 Difference。

推荐顺序：

1. 按 topology/spatial junction 构建 CutterCluster；
2. cluster 内：Tubes + Junction Primitives 做 Exact Union；
3. 校验 cluster cutter closed manifold；
4. cluster 之间无 overlap 时可以 Join 为 multi-component cutter；
5. source 对 cutter clusters 做一次 Collection Difference；
6. 失败时二分到具体 cluster / Pipe pair。

若 GN 的 Mesh Boolean Union 对同一 cluster 不稳定，则把 GN 定位为 preview/prototype，生产实现继续使用 Blender Exact modifier 或 Python 驱动的 per-cluster union。

## 6. 新 Module seam

保持 Feature Chamfer 外部 interface 不变，在 `utils/experimental_pipe_chamfer_utils.py` 内增加一个深 Module：

```python
cutter_result = build_junction_safe_cutters(
    source_object,
    feature_graph,
    radius,
    pipe_resolution,
)
```

返回：

```python
{
    "cutters": [...],
    "pipe_records": [...],
    "junction_records": [...],
    "cluster_records": [...],
    "warnings": [...],
}
```

Interface 隐藏 Pipe sweep、端点 capsule、sphere、spatial detection、cluster union 和 validation。调用方只消费合法 cutter set 与诊断记录。

## 7. Debug stages

建议将当前调试细分为：

- `FEATURE_GRAPH`：degree、strand pairing、component；
- `REGULAR_TUBES`：原始 sweep；
- `JUNCTION_PRIMITIVES`：sphere/capsule 与 owner junction；
- `CUTTER_CLUSTERS`：每个 union cluster 不同颜色；
- `CUTTER_VALIDATED`：仅显示 closed manifold clusters；
- `BOOLEAN_CUT`：source Difference；
- `OPEN_BOUNDARY`；
- `PATCHED`。

每个 junction record 至少记录：

```text
vertex/cluster id
type: ENDPOINT / DEGREE3 / DEGREE4_STRAIGHT / DEGREE4_JUNCTION / SPATIAL
incident pipe ids
incident tangents
primitive type/radius/length
minimum overlap depth
union status
```

## 8. 实施顺序

### Task 0：冻结基线

- 保存 `pipe-chamfer-mixed.blend` 的副本或 fixture；
- 记录当前 node tree 与 12 个 junction 坐标；
- 保留现有 `radius=0.05` PATCHED topology hash 回归。

### Task 1：GN 局部原型

- 在 `pipecut` 的副本中打开 Fill Caps；
- 只为 `degree >= 3` vertices 加 Icosphere；
- Realize → Mesh Boolean Union；
- 不覆盖用户原 node group，不保存原文件；另存实验副本。

Go 条件：截图箭头处不再存在 open cap / point contact，Union cutter closed manifold。

### Task 2：插件 CutterBuilder

- 复用现有 FeatureGraph；
- endpoint capsule；
- degree-3/真实 degree-4 sphere；
- straight degree-4 pairing；
- cluster records。

### Task 3：Boolean A/B

- A：当前 joined cutter batches；
- B：junction-safe cluster union；
- 在 `r = 0.01 / 0.02 / 0.03 / 0.05` 比较：
  - cutter manifold；
  - cutter-derived faces；
  - Boundary degree histogram；
  - PATCHED topology。

### Task 4：Spatial Junction

只在 topology junction 全部稳定后实现，避免同时调两类问题。

## 9. 测试与验收

新增 fixtures/cases：

1. `gn_mixed_degree3_junction_cutter`；
2. `gn_mixed_degree4_pairing`；
3. `small_radius_junction_overlap_regression`；
4. `closed_loop_no_junction_baseline`；
5. `spatial_curve_crossing_cutter`；
6. `mixed_all_sharp_patched`。

对每个 PATCHED 成功结果断言：

- 每个 cutter cluster closed manifold；
- junction minimum overlap depth > scale-aware epsilon；
- 删除槽面后的 Boundary vertices 全部 degree 2；
- final boundary/non-manifold/zero-area = 0；
- source fingerprint 不变；
- 相同输入 topology hash 一致。

统一入口：

```powershell
python .\tools\run_blender_tests.py
```

## 10. Stop / Go

Go：

- 仅加 junction primitives 就能让 `.01/.03/.05` 都形成简单 Boundary loops；
- sphere factor 在小范围内稳定，不明显改变槽宽；
- cluster union 可定位失败，不再出现全局不可解释 Boolean。

Stop / Pivot：

- junction sphere 必须远大于 radius 才能成功，导致明显过切；
- Curve to Mesh 自身在 regular tight bends 持续自交；
- Exact Union 对少量 capsule+sphere cluster 仍频繁非流形；
- source 上的局部 clearance 小于目标半径，几何上不存在合法槽。

Pivot 时再评估 local surface offset / Straight Skeleton；不是现在的首选。

## 11. 最终判断

这个方案值得做。它最大化复用现有 GN regular tubes 与 PATCHED 补面，只把 990 条 Sharp Edges 中 12 个 topology junction 作为特殊问题处理。GN 很适合作为快速可视化实验台；生产实现应由插件 FeatureGraph 驱动 Junction-aware CutterBuilder，并保持 GN 与 Python 使用同一组 junction records 和验收指标。
