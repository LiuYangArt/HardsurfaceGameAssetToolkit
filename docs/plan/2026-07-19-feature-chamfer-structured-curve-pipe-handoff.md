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

degree != 2 / Surface Patch pair 改变
  → 必拆，不交给 Even-Thickness 连续穿越
```

Even-Thickness backend 进入正式 Preview 前必须补三类 guard：

1. **角度/miter guard**：输出 `turn_angle / miter_scale / split_reason`；初始候选仍用 `miter_scale > 1.25`，按真实截图校准。
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

- Sharp vertex `degree != 2`：必断；
- 两侧 `Surface Patch pair` 改变：必断；
- degree-2 但 tangent 突变超过门槛：断开成两个 branches；
- degree-4：先配对唯一近反向 strands，不能配对的部分进入 junction；
- 平滑 degree-2 chain 与真正 cyclic loop：保持连续。

急转角门槛以截面膨胀率为主，而不是只用固定角度：

```text
turn_angle = 0° 表示直行
miter_scale = 1 / cos(turn_angle / 2)
```

初始 spike 以 `miter_scale > 1.25` 作为断开候选，并同时检查局部转弯半径是否足以容纳目标 Pipe radius。门槛必须通过 `pipe-chamfer-mixed.blend` 截图位置校准，不得直接固化为最终产品常量。

断开后的两个 Curve 不能只停在同一点。每个 branch 应向一个受控的 local junction volume 小幅延伸，使 cutter 产生**正体积 overlap**；同时满足：

- overlap 只发生在 junction local bounds 内；
- 不越过无关薄壁或 Surface Patch；
- 不形成此前 postmortem 中的长十字突出；
- extension、overlap partner 和 minimum overlap depth 写入诊断。

需要区分两种接口：

- **Cutter 接口**：允许圆管在 local junction 内重叠，只负责得到无缺口 Difference。
- **Patch 接口**：regular rails 在 junction 外最后一个稳定截面 setback，形成近似平面、接近直角、较方的 `StripPortRecord`；不得沿用圆形 cap 或 Boolean 圆端作为 Patch 边界。

首轮优先实现用户截图中的 `2-port corner`，再做 degree-3；目标不是立刻补 junction，而是证明：大转角分段后两侧管径一致、交汇 cutter 无缺口、删除槽面后只留下局部成对 rails 与方形 ports。
## 3. 目标数据合同

后续实现先稳定以下 records，再写复杂 Mesh：

```text
FeatureBranchRecord
  group_id, branch_id, source_edge_ids, patch_pair, cyclic
  ordered_points, tangents, endpoint_classes
  split_reason, turn_angle, miter_scale

RailPairRecord
  group_id, left_patch_id, right_patch_id
  rail_left[], rail_right[], u[]
  width_error[], ownership_confidence

StripPortRecord
  junction_id, group_id, u_stop
  left_vertex, right_vertex, tangent
  left_patch_id, right_patch_id, profile_frame

JunctionRecord
  junction_id, incident_ports[]
  type, local_bounds, clearance, solver
```

Preview 和 Finalize 必须消费同一组 records。GN 可以显示这些数据，但不能重新推导另一套结构。

## 4. 分阶段实施

### Phase 0：冻结真实基线与失败保护

1. 所有用户文件 probe 按绝对路径、Object 名、Mesh 规模与 fingerprint 选择；禁止 `next(mesh)`。
2. 记录 `pipe-chamfer-mixed.blend::Extruded.002`：1307 vertices / 1988 edges / 683 faces / 990 Sharp Edges。
3. 保存现有 SDF 槽、fan 坏面和 Curve Pipe artifacts 作为 Stop 对照。
4. 暂时让正式 `FINALIZE` 对复杂 regions fail-closed；不要再输出 `TRACKED_BOOLEAN_SURFACE` 并标记成功。

Phase 0 Go：错误路径不隐藏/修改 source，不留下伪 Finalize output。

### Phase 1：Curve Pipe A/B，只验证 cutter

1. 把 `Curve-To-Mesh Even-Thickness` 与 `Poly-Curve Info` 复制到插件受控资产，添加 version/fingerprint，并验证精确、幂等导入。
2. 复用 FeatureGraph，先按 `degree / Surface Patch pair / tangent miter_scale` 把 group 分成独立 branches；cyclic group 使用 cyclic spline。
3. 普通 degree-2 elbow 默认通过 Even-Thickness asset 生成；初始以 `miter_scale > 1.25` 标记急转角断点，并结合局部转弯半径与生成后 overlap guard 校准。
4. profile 为规则圆，resolution/radius 显式；open branch 按 endpoint class 决定 cap/受控 extension。
5. 2-port/degree-3 junction 的 branch 必须在 local bounds 内产生可测量的正体积 overlap，不能只共点或共端面。
6. 与原生 `Curve to Mesh`、当前手写 Pipe、SDF 四路比较：face 数、closed manifold、cyclic coverage、tight bend 截面直径、ring flip/自交、junction 局部形状。
7. Curve Pipe 不直接进入正式 output，只生成 `FEATURE_BRANCHES / REGULAR_TUBES / JUNCTION_OVERLAP / CUTTER` artifacts。

Phase 1 Go：

- 所有应为 cyclic 的源 Sharp components 完整覆盖且单 component closed；
- 用户截图中的急转角已断成独立 branches，转角前后截面直径误差在明确容差内；
- regular tube 没有 SDF 式高密度锯齿边界；
- 2-port/degree-3 junction 有正体积 overlap、Boolean 无缺口，并且没有过长十字突出；
- cutter junction 与未来 Patch port 已明确分离，不能把圆 cap 当 Patch 接口；
- 失败能定位到具体 `group_id/branch_id/junction_id`。

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

### Phase 4：Setback ports 与端点

1. terminal face：rail 与 source boundary 合法相交后生成明确 cap/termination；不使用 capsule 圆帽痕迹。
2. surface stop：需要产品语义；无法确定时 fail-closed。
3. junction：沿 branch 向外寻找最后稳定 rail pair，记录 `StripPortRecord`。
4. local junction bounds 不得越过无关薄壁/Surface Patch；extension 只有局部范围和上下限。

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
