# Feature Chamfer 结构化 Curve Pipe / Rail Solver Handoff

> 日期：2026-07-19  
> 状态：候选路线已收敛；先做受控 spike，不宣称 Finalize 可用  
> Blender：固定使用 `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`（本机 5.1.2）  
> 主回归：`C:\Users\LiuYang\Desktop\pipe-chamfer\pipe-chamfer-mixed.blend::Extruded.002`  
> Curve 对照：`C:\Users\LiuYang\Desktop\pipe-chamfer\geo-node.blend::Extruded.002`，Node Group `pipecut`  
> 明确约束：本轮不再询问或等待 Blender 5.0；不要修改 `auto_load.py`

## 1. 决策摘要

旧 `Curve Pipe → Boolean` 仍有优化价值，但用途必须拆开：

- **保留为 cutter/Boolean oracle 与快速 Preview 候选**：Curve sweep 顶点少、截面规则、closed loop/frame transport 比手写 Pipe 稳定，也比 SDF 边界干净。
- **不把 Pipe Boolean surface 当最终 Chamfer**：它仍然是槽；正式 Finalize 必须由 source Surface 上的结构化 rails/ports 生成。
- **不先做全功能 junction**：先证明主文件上 regular rails 与 strips 可稳定重建；再做 setback ports；最后才做 junction Vertex Mesh。
- **SDF 降级为诊断/A-B backend**：只用于判断复杂 junction 体积包络或 clearance，不进入正式 Patch topology。

推荐主路线：`FeatureGraph + Curve Pipe oracle + source-surface rail extraction + regular strips + setback ports + junction dispatch`。

## 2. 从既有研究中保留的有效方案

### 2.1 Curve-based Pipe backend

`geo-node.blend` 已确认核心链为：

```text
sharp_edge → Mesh to Curve → Curve Circle → Curve to Mesh → Boolean Pro
```

价值：

- degree-2 cyclic Feature 可形成连续 spline；
- profile resolution 与 radius 明确，边界密度远低于 SDF；
- Blender Curve 负责 frame transport 与 seam；
- 可为每个 FeatureGroup 独立生成 Curve，以保留 `group_id / patch_pair / u`，避免整张 sharp network 在 degree>=3 直接互穿。

限制：

- `Mesh to Curve` 整网输出不理解 degree-3/4 strand pairing；
- open end 仍需显式 terminal/junction 规则；
- Pipe Difference 仍是槽，不是 final surface；
- Exact Boolean 的切口可作为 rail 候选或 oracle，但 rail ownership 必须来自 FeatureGraph，不可只靠最近距离猜测。

### 2.1.1 `geo-node.blend` 内置 Even-Thickness Asset 评估

用户已在 `geo-node.blend` 中加入本地 asset：

```text
Curve-To-Mesh Even-Thickness
dependency: Poly-Curve Info
```

Blender 5.1.2 后台只读 probe 已确认：

- Node Group 是 local datablock，`library = null`，并标记为 asset；
- 接口为 `Curve / Profile Curve / Fill Caps / Even-Thickness → Geometry`；
- 主 group 37 nodes / 40 links；依赖 `Poly-Curve Info` 61 nodes / 64 links；
- 内部先用 `Poly-Curve Info` 取得相邻位置、tangent、bisect/dot 信息，再计算角平分缩放，驱动原生 `Curve to Mesh.Scale`，随后用 `Set Position` 做 bisect correction；
- 它是纯 Geometry Nodes 实现，不依赖 D16829 的未合入 C++ patch，因此可在当前 Blender 5.1.2 直接复用。

判断：**用得上，作为 Phase 1 Curve cutter 的默认候选 backend**。它已经处理普通 polyline elbow 的恒厚问题，可避免立即在 Python 重写 D16829 的 profile shear/orientation 算法。发布时必须把主 group 与 `Poly-Curve Info` 依赖一并复制到插件受控的 `Presets.blend`，按名称/版本精确导入；不得在运行时引用或修改用户桌面 `.blend`。

但该 asset 不是 junction solver，也不是任意锐角的保证。用户在真实模型已确认：极锐的大转角仍出现 profile 拉长/折叠/overlap。这与 D16829 记录的 miter shear 退化和粗 profile 自重叠属于同类限制。因此 dispatch 固定为：

```text
普通 degree-2 elbow 且 miter 风险通过
  → Curve-To-Mesh Even-Thickness

极锐 elbow / miter_scale 超限 / 预测或实测 profile overlap
  → 在该 Sharp vertex 拆成两个 Feature branches
  → local junction overlap cutter

多分支交点
  → 先执行最大权重 strand matching
  → selected pairs 继续使用 Even-Thickness
  → 只有 unmatched branches 保持独立

Surface Patch pair / convexity 不兼容
  → 禁止配对并拆开
```

Even-Thickness backend 进入正式 Preview 前必须补三类 guard：

1. **角度/miter guard**：输出 `connection_angle / miter_scale / split_reason`；初始候选仍用 `miter_scale > 1.25`，按真实截图校准。
2. **几何 guard**：生成后检查局部截面直径误差、ring 翻转、自交、相邻段 overlap；不能只信节点布尔开关。
3. **版本/依赖 guard**：主 group 与 `Poly-Curve Info` 都有固定 asset version/fingerprint，导入幂等；缺失或被改写时 fail-closed。

只读诊断产物：

- `tools/probe_curve_even_thickness_node.py`
- `tests/artifacts/curve_even_thickness_node_probe.json`
### 2.2 Edge Mesh / Vertex Mesh 分层

沿用 Blender Bevel V2 的有效分解：

1. `FeatureBranch/EdgeMesh`：两侧 rails 之间生成 regular Chamfer strip。
2. `BoundaryPortExtractor`：在 junction 前寻找最后一个稳定截面，形成 setback ports。
3. `VertexMeshBuilder`：根据 2-port、straight-through、3+ port 分类构建局部 junction。

这是后续数据模型的主骨架；不再从一个全局 hole loop 直接 Fill。

### 2.3 Setback Vertex Blending

从研究文档保留：junction region 不应只用固定 `junction_margin`。沿每个 branch 向外扫描，直到两条 rails：

- ownership 唯一；
- 与 spine 参数 `u` 单调；
- rail pairing 不交叉；
- 横向宽度在 radius 容差内稳定。

该截面成为 port；junction 只消费小型 outer boundary + ports。

### 2.4 Junction solver dispatch

保留但延后实现：

1. compatible 2-port：direct stitch；
2. straight-through pair：先维持主 strip profile，再补余区；
3. 3+ ports：setback Vertex Mesh；
4. constrained triangulation/fairing：只作已验证小型局部 hole 的兜底；禁止作用于全局非平面 loop。

### 2.5 Straight Skeleton 与 Boolean backends

- Straight Skeleton 的 wavefront/collision 思想适合未来求 setback limit、短边消失和 offset collision；Blender `bevelv2` 原型有已知 hard bugs、无 Python API，本轮不作为依赖。
- Blender Exact 继续作为首选 Boolean oracle；Manifold 可做 A/B。Direct Mesh Booleans/CGAL 只解决 Boolean robustness/provenance，不能解决 Chamfer 语义，暂不优先。

### 2.6 2026-07-19 用户截图后的 Curve 分段与局部接口决策

用户给出的目标进一步收敛：如果 Curve Tube Difference 能稳定得到图示的均匀切口，后续 Patch 输入基本可用。当前 Curve Tube 先只解决两类 cutter 缺陷：

1. **大转角 miter 变形**：一条 spline 穿过急转角时，`Curve to Mesh` 会连接相邻截面并拉伸/扭曲，视觉管径不再均匀。
2. **多 Curve junction 缺口**：分支刚好共端点或平 cap 接触不是合法 Boolean overlap，容易留下缺口、sliver 或运算顺序依赖。

因此 Phase 1 不再直接对整个 Sharp network 做一次 `Mesh to Curve`；先由 FeatureGraph 生成独立 `FeatureBranchRecord`。分段规则为：

- 每个 Sharp vertex 先执行通用 maximum-weight strand matching，不再按 `degree != 2` 全断；
- 两侧 `Surface Patch pair` 或 convexity 不兼容：禁止配对；
- degree-2：miter/几何 guard 通过则连续，否则断开；
- degree-3：优先连接最接近直通的一对，剩余 branch 独立；
- degree-4 及以上：选择总权重最高且互不冲突的 pair 集合；
- 平滑 chain 与真正 cyclic loop：保持连续。

急转角门槛以截面膨胀率为主，而不是只用固定角度：

```text
connection_angle = 180° 表示直通
miter_scale = 1 / sin(connection_angle / 2)
```

初始 spike 以 `miter_scale > 1.25` 作为禁止配对候选，并同时检查局部转弯半径是否足以容纳目标 Pipe radius。门槛必须通过 `pipe-chamfer-mixed.blend` 截图位置校准，不得直接固化为最终产品常量。

配对后剩余的 unmatched branch 默认停在原共享 Vertex；先验证它的 cap 是否已被 matched 主 Pipe 完整覆盖并形成正体积 overlap。只有覆盖不足时才允许在受控 local bounds 内小幅延伸；同时满足：

- overlap 只发生在 junction local bounds 内；
- 不越过无关薄壁或 Surface Patch；
- 不形成此前 postmortem 中的长十字突出；
- cap coverage、extension、overlap partner 和 minimum overlap depth 写入诊断。

需要区分两种接口：

- **Cutter 接口**：允许圆管在 local junction 内重叠，只负责得到无缺口 Difference。
- **Patch 接口**：regular rails 在 junction 外最后一个稳定截面 setback，形成近似平面、接近直角、较方的 `StripPortRecord`；不得沿用圆形 cap 或 Boolean 圆端作为 Patch 边界。

首轮优先实现用户截图中的 degree-3 matching 与 `2-port corner`；目标不是立刻补 junction，而是证明：大转角分段后两侧管径一致、交汇 cutter 无缺口、删除槽面后只留下局部成对 rails 与方形 ports。

### 2.7 2026-07-20 通用交点分支配对（当前 Phase 1 主决策）

用户手工拆分/合并真实 degree-3 交点后确认：将方向最连续的两段合成一条主 Curve，第三段保持独立并终止在主 Pipe 内，可以把原来的“三根开口 Pipe”变成“一根连续主 Pipe + 一根插入分支”。这样主 Pipe 在交点没有 cap，独立分支的 cap 被主 Pipe 体积覆盖，Boolean cutter 不再需要为该交点默认添加 sphere/capsule。

因此前文“`degree != 2` 一律拆开”废止。Phase 1 的核心改为对每个 Sharp vertex 的 incident half-edges 做**通用最大权重 strand matching**：

1. 枚举允许配对的 half-edge pairs。
2. 方向越接近直通，连续性权重越高。
3. `Surface Patch pair`、convexity 与 Feature 语义兼容时加权；不兼容时禁止配对。
4. Even-Thickness 的 miter 风险超限、预测 profile overlap/self-intersection、局部 clearance 不足时禁止配对。
5. 求互不共享 half-edge 的最大总权重 matching；不能唯一胜出时 fail-closed 或保持保守拆分，并记录候选分数。

按交点连接数的直观行为：

```text
2 条：合法则连成一根；过锐/不兼容则断开
3 条：最接近直通的两条相连；第三条独立插入主 Pipe
4 条：选总权重最高的两组配对
更多：继续两两配对；无法成对的才成为 unmatched branch
```

角度统一使用 outgoing tangents 的夹角 `connection_angle`：

- `180°` 为直通，连接权重最高；
- 角度越小，转弯越锐；
- miter 膨胀按 `miter_scale = 1 / sin(connection_angle / 2)`；
- `miter_scale` 超限或生成后几何 guard 失败时拆开。

这与旧代码 `_turn_angle_degrees()` 的记法相反（旧函数以直线为 `0°`）。实现时必须明确字段名称与换算，禁止把两个角度定义混用。

unmatched branch 默认不做人工延长。先检查它的端部是否已经进入 matched 主 Pipe，并达到 scale-aware minimum overlap depth；满足则直接使用。只有以下少数情况才进入 endpoint fallback：

- 真正位于模型外边界的 terminal；
- unmatched cap 未被任何 matched Pipe 体积覆盖；
- 非拓扑相连的 spatial crossing；
- Boolean probe 仍检测到局部缺口。

因此 endpoint sphere/capsule/extension 从默认 junction 方案降级为可诊断 fallback。Phase 1 的首要产物是正确的 Curve strand decomposition，不是更多端点 primitive。

手工截图对应的 degree-3 交点必须成为固定 regression：断言选出连续主 strand、独立 branch 的端点被主 Pipe 覆盖，且 Boolean cutter 无局部缺口。

## 3. 目标数据合同

后续实现先稳定以下 records，再写复杂 Mesh：

```text
FeatureBranchRecord
  group_id, branch_id, source_edge_ids, cyclic
  patch_pair_by_edge[], convexity_by_edge[]
  ordered_points, tangents, endpoint_classes
  split_reason, connection_angle, miter_scale

CutterStrandRecord
  strand_id, ordered_edge_ids[], cyclic
  selected_pair_vertex_ids[], unmatched_endpoints[]
  generation_backend, geometry_guard

RailPairRecord
  group_id, left_patch_id, right_patch_id
  rail_left[], rail_right[], u[]
  width_error[], ownership_confidence

StripPortRecord
  junction_id, group_id, u_stop
  left_vertex, right_vertex, tangent
  left_patch_id, right_patch_id, profile_frame

VertexMatchingRecord
  vertex_index, incident_edge_ids[]
  pair_candidates[], selected_pairs[], unmatched_edge_ids[]
  ambiguity_margin

JunctionRecord
  junction_id, incident_ports[]
  type, local_bounds, clearance, solver
```

Preview 和 Finalize 必须消费同一组 records。GN 可以显示这些数据，但不能重新推导另一套结构。

### 3.1 Python 与 Geometry Nodes 职责边界（固定架构决策）

Curve 分组、连接与拆分不在 Geometry Nodes 内求解。它属于 FeatureGraph 的拓扑决策，由 Python 完成：

1. 读取 Sharp Edge graph，并在每个交点收集 incident half-edges。
2. 计算 `connection_angle`、Surface Patch compatibility、convexity 与 miter/clearance guards。
3. 求确定性的最大权重 strand matching，决定哪些 Edge 连续、哪些保持独立。
4. 沿配对关系遍历并生成无分支、具有稳定顺序的 `CutterStrandRecord` 与 Curve splines。
5. 将 `strand_id / source_edge_id / patch ownership / split_reason` 等诊断属性交给 Preview 和 Finalize 共用。

Geometry Nodes 只作为几何生成 backend：消费已经完成分组的 Curve，使用 `Curve-To-Mesh Even-Thickness` 生成 Pipe，处理 profile/resolution/material、预览显示和 Boolean A/B artifact。GN 不再自行运行 `Mesh to Curve` 后猜测 junction 配对，也不维护第二套 strand 规则。

虽然 Blender 5.1 的 GN 可用邻接查询、Repeat Zone 和字段运算拼出 degree-2/3/4 的有限配对，但任意分支数的候选枚举、互斥最大权重 matching、路径重建、稳定 tie-break 与诊断会形成庞大且难测试的节点图。因此不把纯 GN solver 作为正式路线；仅允许用它做一次性 prototype 或可视化验证。

## 4. 分阶段实施

### Phase 0：冻结真实基线与失败保护

1. 所有用户文件 probe 按绝对路径、Object 名、Mesh 规模与 fingerprint 选择；禁止 `next(mesh)`。
2. 记录 `pipe-chamfer-mixed.blend::Extruded.002`：1307 vertices / 1988 edges / 683 faces / 990 Sharp Edges。
3. 保存现有 SDF 槽、fan 坏面和 Curve Pipe artifacts 作为 Stop 对照。
4. 暂时让正式 `FINALIZE` 对复杂 regions fail-closed；不要再输出 `TRACKED_BOOLEAN_SURFACE` 并标记成功。

Phase 0 Go：错误路径不隐藏/修改 source，不留下伪 Finalize output。

### Phase 1：Curve Pipe A/B，只验证 cutter

1. 把 `Curve-To-Mesh Even-Thickness` 与 `Poly-Curve Info` 复制到插件受控资产，添加 version/fingerprint，并验证精确、幂等导入。
2. 复用 FeatureGraph，对每个 Sharp vertex 构建 `VertexMatchingRecord`，按连接角、Surface Patch compatibility、convexity、miter/overlap guard 求最大权重 strand matching；每条原始 Edge 的 Patch ownership 必须保留。
3. selected pairs 组装成 `CutterStrandRecord` 并生成同一 Curve；允许跨兼容 Patch pair 连续，但不得把整条 strand 错写成单一 patch pair。degree-3 的 unmatched branch 保持独立，并优先验证其端部是否已被 matched 主 Pipe 体积覆盖。
4. 普通 matched elbow 使用 Even-Thickness asset；miter 风险超限或生成后 overlap guard 失败的 pair 撤销并拆开。
5. profile 为规则圆，resolution/radius 显式；只有未被主 Pipe 覆盖的 unmatched/terminal branch 才进入受控 endpoint fallback。
6. 与原生 `Curve to Mesh`、当前手写 Pipe、SDF 四路比较：face 数、closed manifold、cyclic coverage、tight bend 截面直径、ring flip/自交、junction 局部形状。
7. Curve Pipe 不直接进入正式 output，只生成 `VERTEX_MATCHING / FEATURE_BRANCHES / REGULAR_TUBES / JUNCTION_OVERLAP / CUTTER` artifacts。

Phase 1 Go：

- 所有应为 cyclic 的源 Sharp components 完整覆盖且单 component closed；
- 用户截图中的急转角已断成独立 branches，转角前后截面直径误差在明确容差内；
- regular tube 没有 SDF 式高密度锯齿边界；
- 主测试文件的 degree-3 手工基线中选出最直主 strand，剩余 branch cap 被主 Pipe 覆盖，Boolean 无局部缺口；
- 2-port/degree-3 junction 有正体积 overlap，并且没有过长十字突出；
- endpoint primitive/extension 只用于真实 terminal 或未覆盖 unmatched branch，不再是默认 junction 方案；
- cutter junction 与未来 Patch port 已明确分离，不能把圆 cap 当 Patch 接口；
- 失败能定位到具体 `vertex_index/group_id/branch_id/junction_id`。

### Phase 2：结构化 rail extraction spike（核心决策点）

优先尝试两条 rail 来源，使用相同 contract A/B：

1. **Boolean intersection rail oracle**：每个独立 Curve Pipe 与 source duplicate 做局部 Exact Difference/Intersection，按 pipe provenance + source patch ID 提取两侧 intersection chains。
2. **Source-surface offset rail**：沿 Feature sample，在左右 Surface Patch 上按 Chamfer 定义求 offset 位置并投影/插值到三角 Mesh；不依赖 Pipe 切口拓扑。

每个 rail 必须满足：

- 唯一 `group_id + side + patch_id`；
- `u` 单调且不自交；
- 左右 rails 横向成对，宽度/离 Feature 距离受 radius 控制；
- 不跨无关 Surface Patch；
- 最大 Edge length 与采样密度有上限。

Phase 2 Go：主文件至少覆盖一条长曲边、一条 cyclic hole、一条邻近圆柱的 regular branch，并生成只含局部 strip 的 artifact；任何一条不能稳定配对则先修 rail，不进入 junction。

### Phase 3：Regular Chamfer strips

1. 使用 arc-length zipper/resample 连接 rail pair；不假设 Vertex 数相等。
2. 每个 Face 必须横跨两条 rails，不能沿模型全局跨越。
3. strip 在 terminal 或 setback port 停止；不得自行封复杂 junction。
4. 支持 profile 参数时，先以 segments=1 平面 Chamfer 为 MVP；多段 round profile 后置。

Phase 3 Go：

- strip Face 到 owner Feature 的距离在 radius 容差内；
- 无超长边、反折、跨 patch、zero-area、自交；
- `REGULAR_PATCHED` 只剩局部 junction holes；
- 固定近景中确实是 Chamfer，不是凹槽。

### Phase 4：Setback ports 与少量 unmatched endpoints

1. 对 unmatched branch 先验证其 cap 是否已被 matched Pipe 体积覆盖；满足 minimum overlap depth 时不做额外端点处理。
2. terminal face：rail 与 source boundary 合法相交后生成明确 termination；不使用 capsule 圆帽痕迹。
3. surface stop：需要产品语义；无法确定时 fail-closed。
4. junction：沿 branch 向外寻找最后稳定 rail pair，记录 `StripPortRecord`。
5. local junction bounds 不得越过无关薄壁/Surface Patch；sphere/capsule/extension 只作为未覆盖端点的 fallback，并有局部上下限。

Phase 4 Go：每个 junction 输入变成一个小型 local hole + 明确 ports，不再是跨模型 Boundary component。

### Phase 5：Junction Vertex Mesh

按 2-port / straight-through / 3+ port dispatch。先做截图中最常见的 2-port 与 degree-3；degree-4 先复用 strand pairing。任何 solver 失败均 fail-closed。

Phase 5 Go：topology clean 之外，还要通过局部 Face span、profile continuity、normal deviation 与固定近景人工验收。

### Phase 6：接回 Operator / UI

只有 Phase 1–5 对主文件通过后才重新启用复杂 `FINALIZE`。Preview 显示结构化 rails/strips 或明确 unsupported junction；不再用 SDF 槽冒充最终结果。

## 5. 测试与验收

### 5.1 固定命令

统一回归：

```powershell
python .\tools\run_blender_tests.py
```

真实文件 probe 使用：

```powershell
& "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe" --factory-startup --background --python <probe.py>
```

输入固定为：

```text
C:\Users\LiuYang\Desktop\pipe-chamfer\pipe-chamfer-mixed.blend
C:\Users\LiuYang\Desktop\pipe-chamfer\geo-node.blend
Object: Extruded.002
```

### 5.2 必要数值门槛

- source fingerprint 不变；
- final boundary/non-manifold/zero-area/self-intersection = 0；
- rail coverage/ownership = 100%，ambiguous = 0；
- generated Face 只连接同一 owner branch 的 rail/port；
- generated Vertex/Face 到 owner Feature/Junction local bounds 不越界；
- 不存在超出采样阈值的长边或全局 fan；
- 输出不得保留 cutter-derived groove surface。

### 5.3 必要视觉门槛

为下列区域保存 wireframe + solid 近景，不得只保存全景白模：

- 顶部孔圈；
- 前方圆孔；
- 高圆柱与曲面交汇；
- 前方凸台端点；
- degree-3/4 junction；
- 长曲边 regular strip。

人工语义问题只有三个：这是 Chamfer 吗？半径/宽度是否一致？是否存在凹槽端帽、长三角或 shading dent？任一否定即失败。

## 6. Stop / Go 与禁止事项

立即 Stop：

- rail 只能从全局 Boundary loop 猜测；
- junction 前无法形成局部 ports；
- Curve Pipe 需要明显大于 radius 的 sphere/extension 才能连通；
- source clearance 小于目标 radius；
- solver 只能靠通用 Fill、fan、保留 Boolean groove 或 cleanup 降低错误计数。

禁止：

- 修改 `auto_load.py`；
- 修改用户两个 `.blend` 原文件；
- 用 Blender 5.0 验收阻塞本轮或再次询问用户；
- 把 topology clean 表述为 Chamfer 正确；
- 在 spike 未通过前继续扩展 UI 或提交完成声明。

## 7. 后续 Agent 起始顺序

1. 读取本计划与 `docs/postmortem/2026-07-19-feature-chamfer-sdf-patch-failure.md`。
2. 使用 `blender-cli` 和项目 `agent-skills/hst-blender-regression`；编辑使用 `windows-patch-fallback`。
3. 先执行 Phase 0：关闭复杂伪 Finalize 成功路径，冻结两份用户文件的 probe。
4. 再执行 Phase 1 Curve Pipe A/B；不要同时进入 Patch。
5. Phase 1 Go 后只做 Phase 2 rail spike；用 artifact 和结构化 JSON 决定 Boolean rail oracle 与 surface-offset rail 哪条值得继续。
6. 每个 Phase 完成前运行相应真实 probe；最终才运行完整回归。

## 8. Suggested Skills

- `blender-cli`：Blender 5.1.2 background probes。
- `hst-blender-regression`：统一回归与 artifacts。
- `tdd`：先冻结当前错误语义，再实现 rail/strip。
- `codebase-design`：保持 FeatureGraph、RailSolver、StripBuilder、PortExtractor、JunctionSolver 深模块边界。
- `windows-patch-fallback`：Windows 文件编辑。
- `verification-before-completion`：真实主文件 + 近景 artifacts + 完整 suite。

## 9. 2026-07-20 实施审计与恢复状态

> 历史审计快照（已被 `docs/plan/2026-07-20-feature-chamfer-gn-preview-recovery-tasklist.md` 的后续状态取代）：当时本轮不能视为计划完成。Phase 0 与 Phase 1 的底层 spike 有可复用价值，但正式 `hst.feature_chamfer_gn` Preview 尚未接入新 Curve backend；Phase 2 未过 Go 门槛，Phase 3–6 的原型属于越阶段实现，必须撤回正式入口并重新实施。

### 9.1 目标入口与可见成功条件

本计划的目标入口明确为 UI 中的 `Feature Chamfer GN Preview`，即 `hst.feature_chamfer_gn`，不是旁边的 `hst.experimental_pipe_chamfer`，也不是只能手工打开的离线 `.blend` artifact。

Phase 1 的首个用户可见交付必须是：

```text
hst.feature_chamfer_gn PREVIEW
  → Python 从 source Sharp Edges 构建 FeatureGraph
  → 按 connection angle / Patch ownership / convexity / miter guard 配对
  → 锐角或不兼容位置断开，连续方向合成无分支 CutterStrands
  → 生成受 Operator 生命周期管理的 Curve Object / splines
  → Preview Geometry Nodes 消费这些 Curves
  → Curve-To-Mesh Even-Thickness 生成 Boolean cutter
  → 用户第一次点击 Preview 即看到新 cutter 结果
```

Python 负责分组与 topology decision；Geometry Nodes 只负责消费分组 Curve、生成 Pipe、Boolean 和显示。禁止让旧 GN 再从整张 Sharp Mesh 自行运行 `Mesh to Curve` 推导另一套 strands。

### 9.2 审计后可保留

- Phase 0：复杂 `END_CAP/JUNCTION` 不再保留 `TRACKED_BOOLEAN_SURFACE` 槽面冒充 Chamfer，失败时保留 source/preview。
- 受控资产：`Curve-To-Mesh Even-Thickness`、`Poly-Curve Info`、版本/source/fingerprint 常量及构建脚本。
- FeatureGraph spike：任意 degree 的 maximum-weight strand matching、逐 Edge Patch ownership、degree-3 regression。
- Curve Pipe backend/probe：Python groups 可以生成 Even-Thickness Pipe；主文件 source fingerprint 保持不变。
- Phase 2 rail A/B 代码、JSON 与 `.blend` 仅作为实验诊断保存，不代表正式功能通过。

### 9.3 必须撤回或隔离

- 撤回 `hst.feature_chamfer_gn FINALIZE` 中提前加入的 structured preflight；在 Phase 1 Preview 接通、Phase 2 通过前，不改正式 Finalize。
- 撤回/隔离 `build_structured_feature_chamfer_artifacts`、StripPort、JunctionRecord、Junction Mesh 与相应“PASS”测试。
- 删除 junction center-fan/简单投影排序补面原型；它违反本计划“不得靠通用 Fill/fan 掩盖 solver”的禁止项。
- 不再把离线 strip/junction artifact、字段 contract 或 topology clean 表述为 Phase 3–6 完成。
- `Feature Chamfer GN Preview` 仍调用旧 `ensure_gn_feature_chamfer_preview()` 并显示旧 SDF cutter；这是当前最关键的缺失链路。

### 9.4 当前阶段状态

| 阶段 | 状态 | 证据与下一步 |
|---|---|---|
| Phase 0 | 已完成 | 复杂伪 Finalize fail-closed；需保留相关 regression。 |
| Phase 1A：FeatureGraph/资产 spike | 部分完成 | matching、资产与 Pipe probe 可复用。 |
| Phase 1B：接入正式 GN Preview | 未开始 | 必须让 `hst.feature_chamfer_gn` 第一次 Preview 可见地使用 Python CutterStrands + Even-Thickness。 |
| Phase 2 | Stop | source-surface records 为 51/51，但严格 guard 仅 17/51；不得进入 junction。 |
| Phase 3–5 | 未开始 | 现有 strip/port/junction 仅为越阶段 prototype，撤回后重新按门槛实施。 |
| Phase 6 | 未开始 | 不得声称已接回 Operator/UI。 |

### 9.5 恢复顺序与硬门槛

1. 先撤回越阶段的正式 Operator/Finalize、strip、port、junction 改动，保留 Phase 0、FeatureGraph、资产和 probes。
2. 为 `hst.feature_chamfer_gn` 建立唯一 Preview seam：输入为 Python 生成的 Curve Object/Collection，输出为 Even-Thickness cutter + Boolean Preview。
3. 新增 Operator 级 regression：调用 `PREVIEW` 后断言实际 modifier 使用新受控资产、Curve strands 与 source Sharp graph mapping 一致；禁止只调用底层 builder 测试。
4. 主文件保存同一机位的旧 SDF 与新 Curve cutter 近景；至少覆盖急转角、cyclic hole、degree-3 junction。
5. 只有用户可见 Preview 和 Phase 1 数值/视觉门槛通过，才恢复 Phase 2 rail spike。
6. Phase 2 rail coverage/ownership/geometry guard 达到 100% 前，禁止新增或接入 StripPort/JunctionSolver/Finalize。
7. Phase 3–5 各自通过真实主文件近景和数值门槛后，才能进入 Phase 6。

### 9.6 防止再次偏航的执行规则

- 每个阶段开始前写清 `目标 Operator / 用户操作 / 应看到的可见变化 / 自动证据`；缺一项不得开始实现。
- 每个阶段结束时必须从 UI Operator 入口做一次验收；底层函数、headless JSON、离线 artifact 不能替代入口验收。
- Stop/Go 条件做成任务清单：前一阶段未 Go，后续阶段代码不得进入正式入口。
- 测试分三层并明确命名：`algorithm unit`、`backend probe`、`operator acceptance`；禁止用前两层的绿色结果宣称第三层完成。
- 完成声明必须逐项引用计划门槛，并附用户可见 artifact；不能只报告测试数量或 topology clean。
- 发现实际入口与假设不一致时立即停工并重新定位，不允许先完成旁路 prototype 再声称已接入。

本次偏差的完整原因、影响与长期预防措施见：`docs/postmortem/2026-07-20-feature-chamfer-preview-integration-drift.md`。
