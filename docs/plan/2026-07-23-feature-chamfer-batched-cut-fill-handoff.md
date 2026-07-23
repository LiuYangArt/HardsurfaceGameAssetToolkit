# Feature Chamfer — 分组 Cut / Regular Fill / Junction 收口 Handoff

> 日期：2026-07-23  
> 状态：`PAUSED / PROTOTYPE / PHASE B GO / PHASE C STOP (SPEC AUDIT)`
> 最终目标入口：UI `Feature Chamfer GN Preview` → `hst.feature_chamfer_gn` → `PREVIEW / FINALIZE`  
> 目的：替代当前“Combined Boolean 后反推全部 Rail 归属”的高复杂度 Finalize 路线；保持已经验证通过的 Preview Pipe Cut 不变。

## 0. 续作进度（2026-07-23）

### 已完成

- 目标入口已重新核对：正式 UI/Operator 仍为 `Feature Chamfer GN Preview` → `hst.feature_chamfer_gn(PREVIEW/FINALIZE)`；batched backend 目前只由隐藏 Adapter `hst.experimental_feature_chamfer_batched_finalize` 调用，尚未接入正式 `FINALIZE`。
- Phase A 实现已存在：正式 Preview 在 owned Curve 上冻结 `GN_PREVIEW_PIPE_V1`，包含 plan/source/radius、FeatureStrand、Curve points、cyclic、endpoint class/extension；backend 只消费该合同并复用正式 `_build_pipe_mesh()`，没有二次调用 `_build_preview_feature_graph()`。
- Phase B 实现已存在：Pipe overlap graph、稳定 coloring、batch 内 overlap guard、正序/逆序 Exact Boolean Cut probe、隐藏 Adapter、14 cells × 3 repetitions runner 和 smoke/regression coverage。
- Phase B 已改为 independent staging：每个 non-overlap batch 从同一 source 合同生成独立 Cut staging Mesh，后续只允许通过 ledger 提交 regular core，不在共享 Mesh 上顺序累计 Boolean。Exact Boolean probe 启用 `use_self` 与 `use_hole_tolerant`，修复大 radius multi-component cutter 被错误解释为空 Mesh。
- 最新矩阵 artifact：`tests/artifacts/feature_chamfer_batched_matrix/results.json`（Blender 5.1.2，2026-07-23），14/14 cells × 3 repetitions PASS；source unchanged，未残留 debug Object。

### 当前 Stop / Go

- **Phase A：GO。**runner 已拆分 Phase A/B 门槛；14/14 cells × 3 的 Preview contract、owned Curve、source fingerprint 均稳定。
- **Phase B：GO。**14/14 cells × 3 的 overlap graph complete、batch 内 overlap=0、independent staging signature order-invariant；此前三个 radius `0.03` 的 `BATCH_CUT_EMPTY` 已通过 Exact Boolean self/hole-tolerant 选项修复。
- 顺序累计 Cut probe 已明确废弃：真实测试证明其 12/14 cells 受执行顺序影响，违反产品语义；Phase C 必须消费 independent staging 并用 setback/ledger 延迟提交，禁止回退到共享 working Mesh 顺序 Boolean。
- Phase C 已开始但未 GO；正式 `FINALIZE` 仍走旧 backend。Phase B 已 GO，现只允许推进 Phase C；D/E 仍受后续门禁约束。

### 当前用户无需操作

Phase A/B 已通过，用户无需操作。下一步按硬门禁进入 Phase C：从 independent staging 提取有明确 Pipe/Patch owner 的 regular rails，建立 exactly-once consumption ledger，并在 overlap 邻域 setback。

### Phase C 当前进度（2026-07-23）

- 已开始实现 Preview Plan owner span 还原、隐藏 Adapter `PHASE_C_REGULAR_CORE`、Phase C runner 门槛与 per-Pipe direct provenance rail probe。
- 单个无 overlap cell 已能稳定产出 regular-core contract；但当前 probe 仍通过二次 per-Pipe Boolean 取得坐标 Rail，尚未直接消费 Phase B 的 per-batch staging Boundary Edge，且没有生成可见 strip Faces/有序 setback ports。
- 当前状态保持 `PROTOTYPE`，Phase C **未 GO**。下一步必须把 source Patch provenance 写进 retained per-batch staging，建立真实 Boundary Edge universe 与 exactly-once `REGULAR_STRIP_CONSUMED / SETBACK_RESERVED` ledger；不得用当前坐标 hash 合同跨级验收。
- 已完成 Phase C staging schema 审计：真实 groove Boundary universe 必须取 independent staging 上 `_mark_boolean_boundary_witnesses()` 标记的 Boolean 交线；每条 Edge 的 `hst_boundary_owner_witness_*` 与 `hst_boundary_patch_witness_*` 必须各唯一，并与相邻 groove/source Face one-hot provenance 双向一致。
- 稳定 Edge identity 已定稿为 `plan_id + semantic_batch_key + 无向量化端点 + 相邻 Face canonical loop signatures + direct Pipe/Patch witness`；禁止 BMesh/Mesh index、坐标 segment hash或 nearest Pipe owner。
- 第一轮审计确认的缺口是：independent staging 曾在序列化真实 Boundary 前即被销毁，Phase C 的所谓正/逆序结果曾复用同一次构建；当前仍未补齐的是 strip 真实 Faces，以及 setback 的有序 Edge、方向、u interval 与可靠 endpoint token。以上均属本地实现问题，当前不需要用户提供信息。
- 已完成第一轮缺口修复：independent staging 现在会在清理前序列化全部真实 Boundary Edge，并用 direct Face provenance 交叉验证唯一 Pipe/Patch owner；单个无 overlap cell观察到 `545` 条真实 Edge、`8` 条有序 Plan-bound Rail chains。Phase C ledger 当前故意保持 `UNCLASSIFIED`，因此不会把尚未完成的 exactly-once partition 误报为 GO。
- 正序/逆序 independent staging 现在真实执行两遍并 canonical 比较，不再复用同一次结果；已在 1-batch 与 2-batch 定向 cell 上验证签名一致。runner 已区分 `DIAGNOSTIC_PARTIAL` 与完整 `PHASE_GATE_FULL`，单 cell 不再可能误报 Phase C GO。
- Phase C regular/setback partition 已接入真实 staging ledger：可唯一配对且满足 width/monotonic guard 的区域生成真实 strip Faces；未配对、branch、terminal 与 overlap 区域全部形成有序 `SETBACK_RESERVED` ports，包含 stable Edge IDs、方向与 normalized u interval。
- Phase C 曾出现 `14 cells × 3 repetitions` 自动绿，但独立 Spec Audit 发现测试 universe 被过滤、overlap setback 粒度过大且 strip guard 不完整，因此该结果撤销，**Phase C 保持 STOP**，禁止进入 Phase D。默认 `tests/artifacts/feature_chamfer_batched_matrix/results.json` 现为修正门禁后的定向失败结果，不再作为 GO 证据。
- Phase C artifact 合同已实现并定向验证：每个 cell 第一次 repetition 保存 `phase_c_regular_core.blend`、`diagnostics.json`、`ledger.json`、overview PNG、setback closeup PNG；它们明确是 regular-core debug artifact，不是 final 产品输出。
- 当前尚未进入 Phase D/E；正式 `hst.feature_chamfer_gn(FINALIZE)` 仍未切换到 batched backend。下一步必须先修复并重验 Phase C；只有重新 GO 后才允许推进 Phase D junction 收口。
- 当前高严重度缺口：`_build_staging_boundary_ledger()` 会跳过无法直接匹配 Plan rail/correspondence 的真实 staging Boundary，导致 exactly-once 只覆盖过滤后子集；overlap Pipe 目前整条 defer，没有形成 `intersection component → FeatureStrand u interval → radius margin` 的局部 setback；strip 还缺显式 orientation/self-intersection/zero-area 完整门禁。先修复这三项并重新跑全矩阵及 audit，才能恢复 Phase C GO。
- 审计后修复进度：ledger 不再静默过滤 Plan 外 Patch（全部进入 explicit `OUTSIDE_PLAN` rail/setback）；稳定 endpoint identity 已加入 staging vertex topology token，完全重合且无法语义区分的 Edge 恢复 collision fail-closed；artifact freshness 已按本次 case `mtime` 验证；strip zero-area/duplicate guard 已接入；Pipe overlap 已计算局部 BVH intersection samples 并投影为 FeatureStrand normalized u intervals。当前仍卡在把这些 u intervals 真正切入多-chain unique pairing，复杂 `tricky Solid.004 r0.01` 仍为 `regular_core_count=0`，所以 Phase C 继续 STOP。
- 最新续作已把 Pipe-Pipe BVH contact 按 disconnected triangle contact component 拆分，并对 cyclic strand 使用最短 circular arc 后合并实际相交 interval；此前 `pipe 0/9` 被错误桥接为 `[0,1]` 的 setback 已消除。Boundary chain 现在按真实 Edge 投影到 unwrapped FeatureStrand u，在 overlap 与 Plan Patch span 上保守切分，再以 bipartite graph 只接受唯一 perfect matching；已删除运行中的最低距离 `min(candidates)` 决策路径。
- `tricky Solid.004 r0.01` 最新定向结果为 `13` 个 regular components / `483` 个真实 strip Faces；branch fragment stitch 与长短 fragment 平衡切分已接入，但仍有 `25` 个远离 overlap 的 unmatched/ambiguous/strip-guard components。matrix 门禁已新增 `unresolved_remote_component_count == 0`，因此该 cell 正确为 FAIL，Phase C 继续 STOP。当前无需用户输入；下一步是按 Plan atom 对这些剩余 fragments 继续做确定性 component 归并，并补齐 orientation/self-intersection 与严格 Universe partition 反向引用门禁。
- 无 overlap 对照 `simple Extruded.002 r0.01` 仍通过：`4` 个 regular components / `228` Faces，远端 unresolved 为 `0`，Boundary partition 的 missing/extra/duplicate 均为 `0`；说明新的局部切分与唯一 matching 没有破坏基础路径。此单 cell 只作定向证据，不构成 Phase C GO。
- 对剩余 `25` 个 unresolved 的独立只读复核：`16` 个是左右孤立/零候选 fragments，`9` 个是 `SIGNED_STRIP_WIDTH_EXCEEDED`；没有 ambiguous perfect matching。多数组在 normalized u 上实际属于同一 Plan atom，但候选 hard predicate 在共同 component 归并前把它们拆成单侧孤岛；部分 strip 仅最后一个 remote endpoint 污染 width。下一步必须改为 `Plan atom → canonical cyclic lift → 双侧共同 u component → 端点保守 Edge trim → hard strip guard → unique matching`，不得放宽 width threshold。
- 已按上述顺序完成第一轮归并：Plan Patch span 与 overlap interval 先形成 regular atoms，run 对齐 canonical cyclic lift 后才切入双侧共同 `u component`；component 内只接受唯一 perfect matching，端点 trim 只删除完整 Boundary Edge，并同时保留 width 与最终 `build_chamfer_strip()` 门禁。`tricky Solid.004 r0.01` 最新定向结果推进到 `21` 个 regular components / `698` 个真实 strip Faces，但仍有 `16` 条 raw unresolved diagnostics（约 `9` 个 unique atom/components），因此 Phase C 继续 **STOP**。当前正在统一 backend/runner 的 component 去重合同，并逐 component 区分真正远端失败与紧邻 forbidden boundary、短到不足形成 Face 的合法 `SHORT_COMPONENT_SETBACK`；禁止用简单忽略单 Edge fragment 让门禁假绿。当前仍不需要用户操作。
- 暂停点（2026-07-23）：已统一 backend/runner 的 unique unresolved component 计数，`tricky Solid.004 r0.01` 复测为 `21` 个 regular components / `698` Faces / `9` 个 unique unresolved。已修复一个事务顺序 bug：zero-area candidate 曾在失败前先消费 `30` 条 ledger Edge；现改为几何验证全部通过后才提交，复测 `missing_from_partition_count=0`、`all_ledger_edges_consumed_once=true`。另外已加入 consumer 双向引用与 `OUTSIDE_PLAN_SETBACK` 结构化门禁，但这部分最后编辑只通过 `py_compile` 与 `git diff --check`，尚未再跑 Blender。恢复时先重跑同一 tricky cell，确认新增门禁，再继续处理 `9` 个 unresolved；Phase C 未 GO，严禁进入 Phase D/E 或接入正式 `FINALIZE`。
- 本次续作从上述 STOP 点继续。最新定向 artifact 的真实 Boundary universe 为 `2072` 条 Edge，`regular_core_count=21`、strip Faces `698`、`unresolved_remote_component_count=9`、`phase_c_go=false`；Phase A/B 状态不变，Phase D/E 未开始，正式 `hst.feature_chamfer_gn(FINALIZE)` 未接入 batched backend。
- 下一步只实现 fail-closed 的 `SHORT_COMPONENT_SETBACK_V1`：先按 `(correspondence_id, atom_id, component_id)` 去重；仅允许“一侧完全缺失、存在侧恰好一条真实 Boundary Edge”的结构性短 component，并同时证明 `component_arc_length <= 2 * radius`，且到 overlap forbidden interval 边界或 Plan terminal/junction endpoint 的实际 FeatureStrand 弧长距离 `<= 2 * radius`。通过后，该 component 的全部 `UNCLASSIFIED` Edge 才能原子转为 `SETBACK_RESERVED`，并写入唯一 `short-setback:*` consumer 与完整 proof；width/monotonic/zero-area 失败、双侧有 Edge、大型 fragment 均不得借此放过。
- 本轮先重跑 `tricky__solid_004__r0p010`；只有大 component 仍 fail-closed、合法短 component 被 ledger exactly-once 消费、Universe partition 与正逆序 fingerprint 均通过，才运行 `14 cells × 3 repetitions`。当前阻塞属于本地实现与验证，不需要用户提供信息或执行 Blender。
- 对最新 `9` 个 unique unresolved components 的逐项复核已完成：仅 `pipe0 0:5 / 2c5e…:0` 满足“单侧 `1` 条真实 Edge、极短、紧邻 forbidden boundary”的短组件语义，可进入 `SHORT_COMPONENT_SETBACK_V1`。`305770…:1:2` 的 zero-area zipper、`pipe2 0:4` 的两个 trim/错配 fragment、`pipe0 0:1 / b198…` 的三个内部 fragment，以及 `pipe9 5:7` 的跨 Plan span 与 `NON_MONOTONIC_U` fragment 均必须继续走 regular 诊断/修复，禁止借 short setback 放过。
- `SHORT_COMPONENT_SETBACK_V1` 除既有单侧单 Edge、弧长与 boundary-distance proof 外，还必须 fail-closed 地证明 component 不处于 Plan atom 内部、不跨 Plan/convexity span boundary，并在 ledger 记录相邻 forbidden/terminal boundary ID。该规则先只解决上述唯一合法 component；其余 `8` 个保持 unresolved 是预期门禁，不代表 Phase C GO。
- 续作结果（2026-07-23）：已实现严格 `SHORT_COMPONENT_SETBACK_V1` proof/atomic ledger commit，并把 Plan atom identity 提升为 `span_id + patch_pair + convexity + u interval`。定向 `tricky Solid.004 r0.01` 中唯一合法 `pipe0 0:5` 单 Edge 已变为 `short-setback:*` consumer，proof 记录真实弧长 `0.00002577 <= 0.02`、到唯一 overlap forbidden boundary 的弧长距离 `0.01034 <= 0.02`、Boundary ID、span/convexity；Universe `2072` 条仍 exactly-once、consumer mismatch 为 `0`。其余 `8` 个 unique components 继续 fail-closed，Phase C 仍 **STOP**；新增 diagnostics 证明 `305770…` 的所有裁剪候选是 `SIGNED_STRIP_WIDTH_EXCEEDED` 或 zero-area，pipe2/pipe0/pipe9 的大 fragment、zero-area、width/non-monotonic 失败均未被 setback 放过。恢复时从这 `8` 个 regular components 继续，不得进入 Phase D/E；`tests/.DS_Store` 仍只保留、不提交。

## 1. 用户决策与不可变前提

1. **用于 Cut 的初始 Pipe 必须直接复用正式 Preview 的完整生成路径。**不得另写 Curve 分组器、另建 Pipe sweep，也不得退回 experimental FeatureGraph。
2. 复用范围包括：Sharp Edge 读取、Curve/FeatureStrand 分组、junction pairing、极锐角断开、平滑 degree-2/cyclic continuation、端点分类与延长、四边 Even-Thickness Curve Pipe、Radius 语义及 manifold guard。
3. 现有 `PREVIEW` 可见 Pipe Cut 已验证通过，不属于本任务的重写范围。新工作集中在 `FINALIZE` 的 Cut 顺序、Rail 获取、regular strip 和 junction 收口。
4. 开发过程中 Agent 必须自行使用第 8 节四个 `.blend` fixture 测试；自动门槛全部通过后才能通知用户进行 UI 验收。
5. 不修改 `auto_load.py`，不覆盖 fixture，不写模型名/坐标/vertex index 特判，不通过全局 Fill 或放宽 guard 掩盖失败。
6. 用户确认第 8 节四个 `.blend` fixture 已覆盖绝大多数真实使用场景；V1 的产品完成范围以这 `14` 个 matrix cells 全部通过为准，不额外追求任意 CAD 拓扑的通用完美解。仍禁止为单个 fixture 写名称、坐标或 index 特判。
7. `Points to SDF Grid → Grid to Mesh` 已确认废弃，仅允许历史文档/复盘保留失败证据；当前实现不得回退到 SDF cutter/Finalize 路线。

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
