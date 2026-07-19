# Feature Chamfer `tricky_b` 修复 Handoff

日期：2026-07-19
状态：根因已定位，真实失败尚未修复；本提交只冻结修复方案，不提交当前实验代码。
目标文件：`C:/Users/LiuYang/Desktop/pipe-chamfer/pipe-chamfer-test-tricky_b.blend`

## 1. 本轮已确认事实

### 1.1 之前“通过”测错了 Object

同一 `.blend` 包含两个可见 Mesh：

| Object | Mesh 规模 | Sharp Edges | Radius 0.05 / Resolution 8 |
|---|---:|---:|---|
| `Extruded.003` | 94 verts / 136 edges / 44 faces | 99 | `PATCHED` 成功，11 groups，boundary=0 |
| `Extruded.002` | 371 verts / 552 edges / 183 faces | 324 | 用户实际选中对象；32 groups，失败 |

之前 probe 使用“场景中第一个 Mesh”，实际跑了 `Extruded.003`。此后所有用户文件验证必须按 **Object 名 + Mesh 指纹 + 最低 Mesh 规模** 精确选择，禁止再用 `next(mesh)`。

用户现场自动诊断确认：

- Blender 5.1.2；
- Radius `0.05`，Pipe Resolution `8`；
- 实际代码路径是 Blender `vscode_development/HardsurfaceGameAssetToolkit`；
- 该目录与工作区 Feature Chamfer operator/utils 文件 SHA256 一致；
- 输入指纹：`f62100103b6926528efde370610db3f015d41c900b972b7e21a374f5abae22f8`；
- 错误：`Fill produced no Faces for 3-Edge hole`。

因此已排除：Blender 未重启、旧 Python module、安装副本不同、参数持久化。

### 1.2 失败统计

`Extruded.002`，Radius 0.05 / Resolution 8：

- `32` Pipe Groups：`27 open / 5 closed`；
- `10` topology junctions，`63` spatial junctions；
- Boolean cutter faces：`1371`；
- Open Boundary edges：`1231`；
- Rail chains：`58`；
- Bridge 成功区域：`22`；
- Fill 前剩余 loops：`17`；
- 第 11 次 `contextual_create` 遇到三边环返回 0 faces。

关键三边环：

- edges：`[857, 490, 858]`；
- verts：`[117, 1006, 1007]`；
- BMesh 中已经存在完全相同的 Triangle Face `116`；
- 三条 Edge 都只链接 Face `116`。

这意味着它不是合法“待补洞”：剩余 boundary 集合中混入了已经由单面 Triangle 完全占据的闭环。直接复用或跳过该 Triangle 后仍剩 `6` 条 non-manifold edges；所以该 Triangle 是更早的 rail ownership/bridge partition 问题的症状，不能用 Fill fallback 掩盖。

### 1.3 Geometry Nodes 参考

用户文件：`C:/Users/LiuYang/Desktop/pipe-chamfer/geo-node.blend`。

核心链路：

`sharp_edge Named Attribute → Mesh to Curve → Curve Circle → Curve to Mesh`

它适合替代手写 `_build_pipe_mesh()` 的 sweep/tube 生成，优点是：

- degree-2 closed feature 天然成为 cyclic spline；
- 环形 Pipe 连续性、frame transport、seam 由 Blender Curve 系统处理；
- 减少手写 closed-loop 截面旋转和缝合问题。

但它不能替代：

- degree-3/4 Feature strand pairing；
- open Pipe junction 延长；
- Boolean 后 BoundaryGraph ownership；
- Regular/Junction patch solver。

推荐采用 **Curve-based Pipe + 独立 junction partition** 的混合方案，而不是把整个算法改成一个 Geometry Nodes modifier。

## 2. 修复策略

### Phase A：先固定真实回归入口

在任何几何修改前新增 `Extruded.002` 回归：

1. 从外部 fixture 加载 `.blend`，按名称 `Extruded.002` 选择；
2. 断言 Mesh 指纹、`371/552/183` 与 `324 Sharp Edges`；
3. 运行 Radius 0.05 / Resolution 8 / PATCHED；
4. 当前先断言已知错误；完成修复后改为断言：
   - status=finished；
   - boundary=0；
   - non-manifold=0；
   - zero-area=0；
   - source Mesh 指纹不变；
   - 重复运行 topology hash 一致。

不要把桌面路径硬编码到通用 CI；可将精简 fixture 纳入 `tests/fixtures/`，或者让本地用户文件 probe 与常规 headless regression 分层。

### Phase B：修 BoundaryGraph 快照与 region ownership

当前 `_bridge_then_fill()` 的问题是：

1. 先一次性计算所有 Pipe rail chains；
2. 顺序执行多个 `bmesh.ops.bridge_loops()`，不断修改同一个 BMesh；
3. 最后把所有 `len(link_faces)==1` 的 Edge 当作“剩余 junction holes”；
4. `_ordered_edge_chains()` 只按连通性/degree 排序，不验证 loop 是否已被同一个 Face 完整占据，也没有 region provenance。

实施顺序：

1. 给每个 boundary Edge 保存稳定的 `pipe_id / patch_id / region_id / source kind`，不要只靠每次查询 BVH 最近距离；
2. rail pairing 候选生成后，Bridge 前验证两条 chain：
   - 所有 Edge 当前仍为 boundary；
   - 两 chain 不共享 Vertex/Edge；
   - endpoints/winding 兼容；
   - Bridge 结果不得产生 zero-area/repeated-vertex Face；
3. 每次 Bridge 后更新受影响的 BoundaryGraph region，而不是继续使用旧 rails 快照；
4. Fill 前对 candidate loop 分类：
   - `true_hole`：每条 Edge 当前只有外侧 Face，没有完全匹配 loop 的现存 Face；
   - `occupied_cycle`：存在完全同 Vertex set 的 Face；不是 hole，说明 region partition/bridge 有问题，应追溯 owner，而不是 Fill；
   - `open/non-simple`：稳定失败；
5. 对 `occupied_cycle` 记录产生它的 `pipe_id/bridge attempt`。必须修掉来源后再允许 PATCHED 成功。

### Phase C：Curve-based Pipe builder

保留 `_build_feature_graph()` 与 degree-4 strand pairing，替换 Pipe 几何生成后端：

1. 每个 Pipe Group 建 Curve spline；closed group 使用 cyclic spline；
2. 圆截面 resolution=`pipe_resolution`、radius=`radius`；
3. 转 Mesh 后检查 closed manifold / zero area；
4. 保留现有 Object tags、Pipe BVH、cutter collection interface；
5. 不直接依赖用户 `geo-node.blend` 的 Node Group datablock，代码中生成 Curve/mesh，避免外部资产依赖；
6. 可做 A/B debug backend：`MANUAL_MESH` 与 `CURVE_TO_MESH`，确认同一 FeatureGraph 下 closed Pipe 数与 Boolean topology。

先用 PIPES stage 验证：`Extruded.002` 的 5 条 closed Pipe 均单个连续 manifold component；再进入 Boolean/Patch。

### Phase D：Open Pipe junction 延长

固定 `1 × radius` 只适合 terminal face。Junction branch 采用按交角计算的 overlap：

`extension = radius / max(sin(angle / 2), epsilon) + safety_margin`

并限制：

- closed/cyclic 不延长；
- terminal face 至少延长 radius；
- junction 延长必须通过 Pipe BVH overlap 验证；
- 防止越过无关薄壁/邻近 Surface；
- 记录每端分类、角度、extension 与实际 overlap partner。

### Phase E：最终 Junction patch

当 Regular bridge 不再制造 occupied cycles 后：

1. 从剩余 BoundaryGraph 提取真实 hole regions；
2. 2-port compatible：direct stitch；
3. straight-through pair：保持主 Pipe profile 后补剩余区域；
4. 3+ ports：setback ports + constrained triangulation；
5. 最终 topology/self-intersection validation，失败则 fail-closed。

不要把 `contextual_create` 当通用 junction solver；它只可用于已验证的简单闭环。

## 3. 实施任务拆分

1. **Test fixture / selection guard**：真实 `Extruded.002` 回归，禁止选错对象。
2. **BoundaryGraph instrumentation**：bridge attempt 与 region/owner provenance。
3. **Occupied-cycle root cause**：定位 Triangle 116 由哪个 rail pair/region 产生；修 rail snapshot/ownership。
4. **Curve Pipe backend**：用 Curve-based sweep 替代手写 closed-loop seam；PIPES stage A/B。
5. **Adaptive endpoint extension**：junction 交角与 overlap 验证。
6. **Junction solver**：真实 holes 的 2-port/3+-port patch。
7. **Regression**：用户 `Extruded.002`、旧 `pipe-chamfer-test.blend`、完整 Blender suite。

## 4. 验收标准

必须同时满足：

- `Extruded.002` Radius 0.05 / Resolution 8：PATCHED 成功；
- `boundary=0 / non-manifold=0 / zero-area=0`；
- 5 条 closed Pipe 都是连续 cyclic manifold Pipe；
- 不存在 occupied boundary cycle；
- source Mesh 指纹不变；
- `pipe-chamfer-test.blend` 旧通过结果不回退；
- Adjust Last Operation 在失败时仍可修改参数；
- HST tab 不崩溃；
- `python .\tools\run_blender_tests.py` 全通过；
- `auto_load.py` 语义 diff 必须为 0。

## 5. 当前工作区注意事项

- 工作区处于 `codex/marmoset-bake-bridge-plan`，而 Feature Chamfer 历史提交存在于 `main.sbak`；当前 Feature Chamfer 文件是 untracked。不要切分支、reset 或覆盖用户改动。
- 当前 dirty worktree 含用户/此前工作：`AGENTS.md`、`__init__.py`、tests、operator/utils、docs/research 等。
- `auto_load.py` 在 status 中显示 modified，但 `git diff --quiet -- auto_load.py` 为 0，属于行尾状态；禁止编辑。
- 本轮新增诊断日志写入 `%TEMP%/hst_feature_chamfer_diagnostic.jsonl`；它已经证明用户现场与工作区 Feature Chamfer 文件内容一致。
- 当前常规回归最近为 `34/34 passed`，但未包含真实 `Extruded.002` 成功断言。

现有背景文档：

- `docs/plan/2026-07-18-experimental-pipe-chamfer-operator-handoff.md`
- `docs/plan/2026-07-18-pipe-chamfer-cutter-set-optimization.md`
- `docs/research/2026-07-18-bevel-and-robust-mesh-boolean-research.md`
- `docs/research/2026-07-19-bevel-v2-straight-skeleton-assessment.md`

## 6. Suggested Skills

下一 Agent 建议依次使用：

1. `blender-cli`：真实 Blender 5.1 background probe；
2. 项目 `agent-skills/hst-blender-regression`：统一回归；
3. `tdd`：先冻结 `Extruded.002` 失败与最终验收；
4. `codebase-design`：保持 FeatureGraph、Pipe backend、BoundaryGraph、Junction solver 的深模块边界；
5. `windows-patch-fallback`：Windows 文件编辑；
6. `verification-before-completion`：真实用户 Object + 旧 fixture + 完整 suite。
