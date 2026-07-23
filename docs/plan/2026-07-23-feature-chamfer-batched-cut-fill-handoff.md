# Feature Chamfer — 分组 Cut / Regular Fill / Junction 收口 Handoff

> 日期：2026-07-23  
> 状态：`PROTOTYPE / NOT STARTED`  
> 最终目标入口：UI `Feature Chamfer GN Preview` → `hst.feature_chamfer_gn` → `PREVIEW / FINALIZE`  
> 目的：替代当前“Combined Boolean 后反推全部 Rail 归属”的高复杂度 Finalize 路线；保持已经验证通过的 Preview Pipe Cut 不变。

## 1. 用户决策与不可变前提

1. **用于 Cut 的初始 Pipe 必须直接复用正式 Preview 的完整生成路径。**不得另写 Curve 分组器、另建 Pipe sweep，也不得退回 experimental FeatureGraph。
2. 复用范围包括：Sharp Edge 读取、Curve/FeatureStrand 分组、junction pairing、极锐角断开、平滑 degree-2/cyclic continuation、端点分类与延长、四边 Even-Thickness Curve Pipe、Radius 语义及 manifold guard。
3. 现有 `PREVIEW` 可见 Pipe Cut 已验证通过，不属于本任务的重写范围。新工作集中在 `FINALIZE` 的 Cut 顺序、Rail 获取、regular strip 和 junction 收口。
4. 开发过程中 Agent 必须自行使用第 8 节四个 `.blend` fixture 测试；自动门槛全部通过后才能通知用户进行 UI 验收。
5. 不修改 `auto_load.py`，不覆盖 fixture，不写模型名/坐标/vertex index 特判，不通过全局 Fill 或放宽 guard 掩盖失败。

正式 Preview 的权威路径：

```text
hst.feature_chamfer_gn(PREVIEW)
→ ensure_gn_feature_chamfer_preview()
→ _rebuild_owned_preview_curve()
→ _build_preview_feature_graph(source, radius, stats)
→ ChamferPlan.feature_strands
→ owned multi-spline Curve
→ HST Even-Thickness Curve Pipe（四边 profile，Fill Caps）
→ Boolean Pro Preview
```

定位入口：

- `utils/feature_chamfer_gn_utils.py::_rebuild_owned_preview_curve`
- `utils/experimental_pipe_chamfer_utils.py::_build_preview_feature_graph`
- `utils/feature_chamfer_gn_utils.py::_build_curve_preview_node_group`
- `utils/experimental_pipe_chamfer_utils.py::_build_pipe_mesh`

## 2. 现有路线与改向原因

旧 roadmap：`docs/plan/2026-07-22-feature-chamfer-generalization-roadmap.md`。

它采用：共享 `ChamferPlan` → 所有 Pipe Combined Exact Boolean → 在最终 Boolean Boundary 上恢复 `Pipe / Rail / Patch / JunctionPort` → regular strip → junction patch。

难点不是 Pipe Cut，而是交叉区的几何满足 `∂(A∪B)`，并不完整保留 `∂A∪∂B`。某根 Pipe 的两侧 Rail 会被其他 Pipe 遮挡、截断或替换为 shared seam；正式 patch runtime 还在使用 BVH 最近 Pipe 推断归属。Phase 3 因此长期停在 `PROTOTYPE / STOP`。详细证据见：

- `docs/diagnostics/feature-chamfer-generalization/phase-3-boundary-binding.md`
- `docs/diagnostics/feature-chamfer-generalization/phase-1-failure-profile.md`

本 handoff 改为：**利用 Pipe 冲突图分批，在 Pipe 归属天然明确时完成 regular 区；所有冲突附近保留显式 ports，最后统一收口 junction。**

旧 Phase 3 尚未接入正式 Finalize 的未提交 witness / port-incidence 修改，不得直接当作新方案的前置成功，也不得未经审计叠加两套实现。

## 3. 产品语义

目标语义是**对称的 multi-Pipe chamfer**，不是按执行顺序决定胜负的 priority chamfer。

```text
Preview ChamferPlan + Preview Pipe specs
→ Pipe overlap graph
→ non-overlapping color batches
→ 每批 Cut 并获取唯一 Pipe/Rail provenance
→ 只构建远离冲突区的 regular core
→ 为 overlap/terminal 区留下有 owner 的 setback ports
→ 所有批次完成后统一构建 junction patches
→ closed-manifold FinalArtifact
```

硬约束：

- batch 顺序不得成为隐藏的产品参数；至少验证正序、逆序结果的 canonical topology 与固定近景一致。
- 后一批 Cut 不得破坏前一批已经完成的 regular strip。实现可采用安全的工作 Mesh/ledger、延迟合并或只在不可重叠 core 上提交；不得假定“先补后切自然正确”。
- overlap/junction 范围在 regular 阶段必须 setback，不可提前封死。
- 最终输出仍为独立 Object；source fingerprint 在 PREVIEW / FINALIZE 前后保持不变。

## 4. Module 与 Interface

新 backend 应是一个深 Module，实验 Operator 只能作为薄 Adapter：

```text
build_batched_feature_chamfer(
    source_object,
    preview_plan,
    preview_parameters,
    debug_stage,
) -> BatchedChamferResult
```

`BatchedChamferResult` 至少包含：

- `output_object_name`
- `plan_id`、source fingerprint、radius
- Pipe IDs、overlap graph、color batches
- 每个 batch 的 Cut、Rail、regular-core、setback-port 统计
- 每条 Boolean Boundary Edge 的 owner/消费 ledger
- junction regions、port ranges、生成 Faces
- boundary/non-manifold/zero-area、自交与 face-quality 诊断
- batch-order invariance fingerprint
- 可稳定序列化的失败 code；错误必须 fail-closed

建议新增 `utils/feature_chamfer_batched_finalize_utils.py` 承载实现；复用现有公共逻辑，必要的小型共享函数才从旧大文件中提取。不要复制 Preview 算法。

## 5. Operator 策略

### 开发阶段

允许新增一个**不放进正式 UI**的薄实验 Operator，例如：

```text
hst.experimental_feature_chamfer_batched_finalize
```

用途仅限：从当前有效 Preview 读取 `ChamferPlan`/参数，调用新 backend，输出 artifact 和 diagnostics。不得复制 PREVIEW、Cancel、Redo、参数同步或 source 恢复逻辑。

### 集成阶段

实验 backend 通过 Algorithm + Backend 门槛后，接入现有：

```text
UI Feature Chamfer GN Preview
→ hst.feature_chamfer_gn
→ FINALIZE
→ build_batched_feature_chamfer(...)
```

最终不发布第二个正式 Feature Chamfer Operator；原 Preview 和用户操作保持不变。实验 Operator 在目标入口通过后删除或保留为隐藏诊断入口，不能出现在面板中。

## 6. 分阶段 Stop / Go

### Phase A — 冻结 Preview Pipe 输入合同

**目标 Operator：** `hst.feature_chamfer_gn(PREVIEW)`  
**用户操作：** 选中 fixture 对象，运行 Preview。  
**预期可见变化：** 无；只证明新 backend 消费的 Pipe 与正式 Preview 完全相同。  
**自动证据：** plan ID、FeatureStrand edge IDs、Curve spline、cyclic/open、endpoint class/extension、evaluated Pipe fingerprint。  
**Go：** 新 backend 不执行第二次独立分组；所有 Pipe spec 与 Preview 一致。  
**Stop：** 调用 `_build_feature_graph(...EXPERIMENTAL...)`、重新按 angle/seam 分组，或重建另一套 Curve/Pipe 语义。

### Phase B — Overlap graph 与 batch-order probe

**目标 Operator：** 隐藏实验 Finalize Adapter。  
**用户操作：** Preview 后运行实验 Finalize。  
**预期可见变化：** 只生成 debug Cut / Rail artifacts，不宣称产品完成。  
**自动证据：** overlap pairs、graph coloring、每批内部 overlap=0、正序/逆序 Cut 签名、source unchanged。  
**Go：** 每根 Pipe 恰好属于一个 batch；batch 内互不相交；所有 fixture 可重复运行。  
**Stop：** 分组遗漏 Pipe、batch 内存在 overlap，或顺序差异无法被后续 setback/ledger 隔离。

### Phase C — Regular-core Cut + Fill

**目标 Operator：** 隐藏实验 Finalize Adapter。  
**用户操作：** 同上。  
**预期可见变化：** 非交叉槽段形成正确 chamfer strip；交叉附近保留洞口。  
**自动证据：** 每条 regular rail 明确绑定同一 Pipe 的两侧 Patch；Edge 单次消费；strip orientation、width envelope、自交、zero-area guard。  
**Go：** 所有远离 overlap 的预期 regular regions 完成；无跨 Pipe 错配；后批不切坏早批 strip。  
**Stop：** 使用最近 Pipe猜 owner、全局 Fill、忽略未消费 Edge，或依赖 batch 优先级得到结果。

### Phase D — Junction ports 与最终收口

**目标 Operator：** 隐藏实验 Finalize Adapter。  
**用户操作：** 同上。  
**预期可见变化：** setback 后的小范围 junction holes 被统一连接。  
**自动证据：** Junction region/port owner ledger、所有 Boundary Edge 恰好消费一次、closed manifold、zero-area=0、source unchanged。  
**Go：** 四个 fixture 的 7 个对象 × 两个 radius 全部产生机器可接受输出；正序/逆序 batch invariant。  
**Stop：** centroid fan、无约束 triangulate、通用 hole fill、残留 Boundary 或 non-manifold。

### Phase E — 接入正式 FINALIZE 与独立 Spec Audit

**目标 Operator：** `hst.feature_chamfer_gn(PREVIEW→FINALIZE)`。  
**用户操作：** 对矩阵对象运行正式入口。  
**预期可见变化：** Preview 不变；Finalize 生成独立、完整的 chamfer Mesh。  
**自动证据：** 产品矩阵、完整回归、固定近景、runtime capture 证明调用新 backend。  
**Go：** 第 9 节全部门槛通过，独立 audit 无高严重度偏差。  
**Stop：** 只有实验 Operator 通过、正式入口仍走旧 backend，或测试绕过目标 Operator。

## 7. 实现提示

1. 现有 `_non_overlapping_pipe_batches()` 已实现 overlap graph greedy coloring，可作为初始实现；先验证其稳定性和 Pipe ID 合同，不要重写算法。
2. 不要永久执行简单的 `batch A Cut→全部 Fill→batch B Cut→全部 Fill`。该流程会把 priority/order 写入几何。必须只提交 regular core，并把冲突邻域保留为 ports，或者在独立工作 Mesh 上记录后统一合并。
3. Rail provenance 优先来自当前 batch 的 Boolean intersection/stage identity；不得回落到最终全局 Boundary 上的 BVH nearest owner。
4. 现有 `ChamferPlan` 可继续保存 plan ID、FeatureStrand 与 Patch 语义；若新算法不需要旧 `BoundaryWitness` 的某些字段，应删除或替换，不要层叠兼容层。
5. junction solver 只接收显式有序 ports、owner Pipe/Patch、方向和已消费区间；它不负责重新猜 Rail。
6. 每完成一阶段保存可读 `.blend`、JSON diagnostics 和固定视角 PNG；低层通过不得替代正式 Operator / Visual 验收。

## 8. Agent 必须自行测试的真实文件

Fixture 均视为 immutable，路径从 repository root 解析：

| Fixture | 对象 |
|---|---|
| `tests/fixtures/feature-chamfer-product-simple.blend` | `Extruded.002`、`Solid 44` |
| `tests/fixtures/feature-chamfer-product-tricky.blend` | `Solid.004`、`Solid.016` |
| `tests/fixtures/feature-chamfer-product-tricky-b.blend` | `Extruded.003`、`Extruded.002` |
| `tests/fixtures/feature-chamfer-topology-defect-mixed.blend` | `Extruded.002` |

每个对象至少测试 radius `{0.01, 0.03}`，即 `14` 个 matrix cells；每个 cell 至少重复 `3` 次。不得只修或只运行单一 fixture。

现有入口：

```bash
python tools/run_feature_chamfer_matrix.py --repetitions 3
python tools/run_blender_tests.py
```

如果开发阶段实验 Operator 尚未接入现有 matrix runner，应新增 batched prototype runner，但最终 Phase E 必须恢复使用现有目标 Operator matrix。新增 smoke/regression test 统一进入 `tests/blender_test_driver.py`，并更新 `tests/README.md`。

## 9. 通知用户验收前的硬门槛

Agent 不得因单个 `.blend` 可打开、Operator 返回 `FINISHED`、测试总数通过或 topology clean 就通知用户验收。必须同时满足：

### Algorithm

- Preview plan/Pipe 输入一致；graph coloring complete。
- 每条 Rail/Port/Boundary Edge 有明确 owner 与 exactly-once consumption。
- batch 正序/逆序结果 invariant；无模型特判和隐藏 priority。

### Backend

- 14/14 cells × 3 repetitions 自动成功且语义 fingerprint 稳定。
- 输出 `boundary_edge_count=0`、`non_manifold_edge_count=0`、`zero_area_face_count=0`。
- chamfer FACE attribute 存在且非空；source fingerprint 全程不变。
- 没有伪 output、残留 debug Object 或后台 Blender 进程。

### Operator

- 14/14 cells 从 `hst.feature_chamfer_gn PREVIEW→FINALIZE` 进入新 backend。
- Preview modifier、Cancel、Undo/Redo、Adjust Last Operation 参数和失败恢复不回归。
- 每个 cell 保存 `preview.blend`、`final.blend`、`diagnostics.json`。

### Visual/Product（Agent 先验收）

- Agent 自行渲染并检查每个对象至少一个全景和所有 junction 固定近景。
- 无错接槽、缺面、尖刺、翻面、长跨面、明显 pinching 或 batch seam。
- radius `0.01/0.03` 的宽度变化符合 Preview；Preview 与 Finalize 可见语义一致。

全部通过后，状态只能先报告 `VERIFIED`，并向用户提供：

- 产品矩阵摘要与 `results.json` 路径；
- 四个 fixture 的最终 `.blend` artifacts；
- 固定近景 PNG 路径；
- 仍未覆盖的输入合同范围；
- 明确请用户在真实 Blender UI 中验收，用户确认后才标记 `ACCEPTED`。

若任一门槛失败，继续诊断和实现；需要用户作实质决定时才报告 `PROTOTYPE / STOP`，不得把失败转交给用户当测试员。

## 10. 推荐 Skills

- `implement`：按本 handoff 分 Phase 实现，禁止跨 Stop/Go。
- `tdd`：先写最小合成 overlap/order/port contract，再写实现。
- `blender-cli`：运行真实 Blender background probe、保存 `.blend`/JSON/PNG artifacts。
- 项目内 `agent-skills/hst-blender-regression/SKILL.md`：运行完整 headless 回归。
- `diagnosing-bugs`：处理 batch order、Rail 错配、junction topology 等硬故障。
- `codebase-design`：保持 Preview Pipe、batched finalize、patch solver 的 Module seam。
- `verification-before-completion`：完成声明和通知用户验收前核验新鲜证据。
- `code-review`：Phase E 独立 Spec Audit，确认正式 runtime path 与测试入口。

## 11. 新 Session 启动 Prompt

```text
读取项目 AGENTS.md、docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md、tests/TESTING_POLICY.md，以及旧 Phase 3 诊断。先审计当前未提交修改，保留用户工作，不开分支，不修改 auto_load.py。

目标入口最终固定为 UI Feature Chamfer GN Preview → hst.feature_chamfer_gn → PREVIEW/FINALIZE。用于 Cut 的初始 Pipe 必须 100% 复用正式 Preview 的 Curve/FeatureStrand 分组、极锐角断开、junction pairing、端点延长和 Even-Thickness 四边 Pipe；不得另写或简化。

从 Phase A 开始，只推进一个尚未 Go 的 Phase。使用四个 tests/fixtures Feature Chamfer 文件、7 个对象、radius 0.01/0.03 自行测试并留下 JSON/.blend/PNG artifacts。自动 Algorithm/Backend/Operator/Visual 门槛全部通过后才通知用户验收；失败时继续诊断，不把用户当测试员。
```

## 12. 当前工作树警告

编写本 handoff 时工作树已有 Feature Chamfer Phase 3 未提交修改，以及无关 `.DS_Store`。它们属于既有用户工作：

- 不得 reset、checkout、覆盖或擅自提交；
- 开始实现前先逐文件审计哪些可复用、哪些属于旧 witness 路线；
- 新方案的 diff 与旧实验 diff 必须能被独立解释；若重叠无法安全拆分，先请求用户决定。

