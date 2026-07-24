# Feature Chamfer Phase C — Ownership-driven Blender Bridge 续作计划

日期：2026-07-24
状态：`PAUSED / PROTOTYPE / PHASE A GO / PHASE B GO / PHASE C STOP`
策略决定：`OWNERSHIP_DRIVEN_BLENDER_BRIDGE_THEN_LOCAL_FILL_V2`
本轮审查基线：`24766e2` (`Clarify Phase C ownership-driven bridge and local fill recovery plan`) + 保留现有 dirty worktree
Phase C runtime baseline：`1b8f120` (`wip(feature-chamfer): checkpoint phase c regular diagnostics`)
上游权威 handoff：`docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md`

本文是下一次 Session 的执行入口。权威顺序固定为：项目 `AGENTS.md` → 上游 handoff 的产品语义与 Phase A→E Stop/Go → 本文。本文不重新定义上游 Phase：**Phase C 只完成 regular core；Phase D 才做 product assembly 与 junction/terminal 收口；Phase E 才接入正式 `FINALIZE`。**

本文替代旧版“canonical cyclic rail + circular DP”主路线，也修正上一版把 Junction Fill 提前放进 Phase C 的阶段冲突。旧代码和 diagnostics 只可作为证据或反例，不能因为已经存在就继续叠加 matching、trim 或 handoff 例外。

## 0. 本轮 Review 结论

以下冲突均已在本文修正：

1. **Phase C / D 越界。**上一版要求 Phase C Bridge 后直接 Junction-local Fill，但上游把 Phase C 定义为 regular core、Phase D 定义为 junction 收口。现在 Phase C 只输出 Bridge Faces 与结构化 ports；Fill 后移到 Phase D。
2. **不存在可直接 Fill 的共享 BMesh。**当前 independent staging 在序列化 Boundary records 后就销毁临时 Mesh；上一版所写“当前 provisional patch BMesh”并不存在。Phase C 改为每个 `RegularBridgeJob` 使用 job-local provisional BMesh；Phase D 必须先单独证明 product assembly，才能重新提取最终 boundary graph。
3. **ownership 不等于 cyclic correspondence。**ownership 只负责唯一确定左右 rail 集合和 BridgeJob；同一已证 pair 内的逐点 correspondence 交给 Blender Bridge。Blender 对 closed loops 会先执行内部 best rotation（按两环 Vertex 距离选 rotation），再应用 `twist_offset`；这是用户选定的 Blender Bridge 语义，不等于项目用 distance score 猜 rail owner/pair。仍须用 cyclic permutation/reversal/twist 自动合同证明结果稳定。
4. **已撤销 equal-count 误判。**用户已在 Blender 5.1.2 UI 手动验证普通 Bridge Edge Loops 能连接左右 Edge 数不同的 open rails，并生成包含三角面的 strip。Blender 源码进一步证明 `Selected loops must have equal edge counts` 只在 `use_merge=True` 的 Merge 分支触发；普通 `use_merge=False` 会扩展较短 loop，并 triangulate/beautify 不等分段结果。因此不得再把该字符串作为普通 Bridge 的反证或 Phase C capability blocker。
5. **旧 smoke 证据被高估。**现有 smoke 只用两条同分段 open rails，Bridge 后 Fill 整个外轮廓得到 watertight ribbon；它没有 Plan/overlap junction witness，不能证明产品 junction Fill 正确。
6. **Fill 路线应忠实复现手工工作流。**Edit Mode 的 `F`（New Edge/Face from Vertices）实际走 `contextual_create`，与旧 `_bridge_then_fill()` 和用户描述的 Bridge 后 Fill 一致。Phase D 以“单个已结构证明的闭合 cycle + cloned provisional BMesh + job 外 geometry fingerprint 不变”约束 `contextual_create()`；`edgeloop_fill()` 只作自动对照候选，不因 API 名称更窄就擅自替换产品语义。
7. **claim 与 Face consumption 混淆。**Phase C 的 port Edge 是“已唯一保留”，不是“已被 Face 消费”。V2 分开记录 `claim_state` 与 `face_consumer_id`，禁止用 reserved port 冒充 exactly-once Face coverage。
8. **`Plan junction_id` 并不存在。**当前 `ChamferPlan` 有 `JunctionPort`、port-patch incidence 与 overlap/setback records，没有权威 `junction_id` 字段。V2 使用由结构连通分量生成的 `junction_region_id`，并保存其 Plan port / overlap component witnesses。

### 0.1 用户可先手动验证的 Blender 行为

手测只用于冻结 Blender UI 的实际交互/视觉语义；ownership、provenance、determinism、rollback 和 14×3 gate 仍由自动测试负责。**当前没有供用户点击的新 V2 Phase C 按钮**：面板里的 `Feature Chamfer (Sharp/Seam)` 与动态 `Feature Chamfer GN Preview/Finalize` 仍是现有 runtime，内部 Phase C adapter 也不是 UI 入口。在 V2 接入前，不得用这些按钮的结果冒充本计划 Bridge 实现的验证。

1. **Open unequal rails（ACCEPTED，无需再测）。**用户已在 Blender 5.1.2 Edit Mode 直接选择两条不同 Edge 数的 open rails，并执行 Blender 原生 `Edge → Bridge Edge Loops`，确认成功生成 strip；产品接受混合 tri/quad，不要求 quad-only。后续只需由 agent 自动补 5-vs-3 smoke，并在真实 `tricky__solid_004__r0p030` L5/R3 cell 检查无翻面、无跨 job 写入、槽宽与邻接合同稳定。
2. **Cyclic unequal loops seam（不要求当前预先手测）。**这不是现有插件按钮测试。Step 1 先用 synthetic closed loops 自动覆盖 cyclic permutation/reversal/default twist；Step 4 再由内部 adapter 生成真实 debug artifact，首选 `feature-chamfer-product-tricky.blend :: Solid.016 :: radius 0.01`，复核用 `feature-chamfer-product-tricky-b.blend :: Extruded.003 :: radius 0.01`。届时用户只需打开 agent 提供的 `.blend`/固定近景，确认闭合处没有交叉、扭转、异常长跨面或突然变窄；若默认 seam 视觉不可接受，再讨论显式 `twist_offset` 产品规则。
3. **真实 junction 的局部 Fill（Phase D artifact 产出后再测）。**由 agent 先从目标模型生成 assembled debug artifact 并标出唯一 junction hole；用户打开该 artifact，只选择标记洞口后按 `F`，从正反两面和 Solid/Material Preview 检查长跨面、pinching、翻面和洞外 Faces。它只确认产品视觉/拓扑偏好，不作为具体 BMesh API 证据，也不计入 Phase C gate。
4. **Terminal 与 junction closure 是否同类（Phase D artifact 产出后再测）。**由 agent 在 artifact 中分别标出一个单 Pipe terminal hole 和双 Pipe junction hole；用户分别比较 `F` 与 `Grid Fill` 的 n-gon/tri/quad、pinching和法线，再确认两类是否允许共用 closure 语义。没有真实 assembled holes 时延后，不用 synthetic/旧 backend 结果冻结新产品语义。
5. **正式 UI 生命周期（Phase E 接入后再测）。**届时使用面板动态按钮 `Feature Chamfer GN Preview/Finalize`：simple fixture Preview → `Adjust Last Operation` 修改 Radius/Show Cutter → 确认 Preview 更新和按钮状态；Cancel 只移除 Preview。再 Preview→Finalize：`Cmd-Z` 一次应删除 output 并恢复 Preview，第二次应移除 Preview。该结果只冻结 Phase E 交互语义，不阻塞或授权 Phase C/D runtime。

不需要用户手测：Edit Mode 选择顺序、BMEdge list permutation、`use_merge/use_pairs/use_cyclic` 参数语义、BMesh 返回字段、Face winding 的输入反转稳定性、Edge claim/provenance、batch-order invariant、source unchanged、rollback、fake-green runner。这些应以 Blender 源码或自动合同为准，避免 UI 操作掩盖数据层问题。用户只需对真实 debug artifact 做 Face Orientation 视觉确认。

## 1. 一句话任务

保留已通过的正式 Preview Pipe、independent batched Exact Boolean、Boundary Edge ownership/provenance 与 ledger；Phase C 用 ownership/Plan topology 唯一生成每条 Pipe 的左右 `RegularBridgeJob`，在 job-local BMesh 调用 Blender `bmesh.ops.bridge_loops()` 生成 regular Faces，并留下有结构 witness 的 terminal/junction ports。新鲜 `14 cells × 3` 与独立审计通过前，Phase C 保持 STOP；不得实现 Phase D Fill，不得接入正式 `hst.feature_chamfer_gn(FINALIZE)`。

## 2. 产品路线与阶段分工

最终产品路线仍采用用户确认的手工语义：

1. ownership/Plan topology 找到同一 Pipe 的左右 rails。
2. Blender Bridge Edge Loops 生成 regular strip。
3. Pipe 交叉和 terminal 范围保留结构化 ports，不在 Phase C 封口。
4. Phase C GO 后，Phase D 先完成 batch-neutral product assembly，再从实际 assembled BMesh 重新提取洞口。
5. 只有一个洞能唯一映射到一个 `junction_region_id` 时，才使用 Blender Fill；terminal 走单独 `TerminalCapJob`，不能混入 junction Fill。
6. 任一无法归属、非闭合、混合多个 region 或吞入 unresolved regular Edge 的洞都必须诚实失败。

旧 `Feature Chamfer (Sharp/Seam)` Operator 的 `_bridge_then_fill()` 只提供两个可复用点：BMesh Bridge 调用方式，以及“Bridge 后重新提取 boundary”的时序。以下旧行为明确不复用：`_rail_pair_score()` 距离配对、Bridge 失败后继续、遍历全部剩余闭环 Fill、occupied-cycle 宽松处理。

## 3. 目标入口契约与状态

```text
正式 PREVIEW（已存在）
UI 动态主按钮(action=AUTO/PREVIEW)
→ hst.feature_chamfer_gn.invoke()
→ hst.feature_chamfer_gn.execute(PREVIEW)
→ owned Curve + GN Preview modifier + GN_PREVIEW_PIPE_V1
→ 用户可见 procedural cutter preview

当前正式 FINALIZE（Phase C/D 禁止修改）
同一 UI/Operator
→ hst.feature_chamfer_gn.execute(FINALIZE)
→ 旧 build_pipe_chamfer(PATCHED)

Phase C 验收入口（已存在）
正式 hst.feature_chamfer_gn(PREVIEW)
→ hidden hst.experimental_feature_chamfer_batched_finalize(PHASE_C_REGULAR_CORE)
→ build_batched_feature_chamfer()
→ RegularBridgeJob + job-local Blender Bridge
→ debug Faces / ports / ledger / diagnostics artifacts

Phase D 验收入口（Phase C GO 后才允许新增）
同一 hidden Adapter 的新 Phase D debug stage
→ batch-neutral product assembly
→ assembled BMesh remaining boundary graph
→ JunctionFillJob / TerminalCapJob
→ closed-manifold debug product artifact

Phase E 产品入口
正式 hst.feature_chamfer_gn(PREVIEW→FINALIZE)
→ 新 backend runtime capture
→ 独立 final Object + Undo/rollback + Visual/Product 验收
```

状态分级：

- `Algorithm`：Blender Bridge/Fill API mechanics 有隔离证据；V2 ownership-driven jobs 尚未证明。
- `Backend`：Phase C prototype，STOP。
- `Operator`：`NOT INTEGRATED`；hidden Adapter 只是阶段验收 seam，不算正式 Operator 接入。
- `Visual/Product`：未验证、未接受。

## 4. 已确认基础与证据边界

### 4.1 可继续复用

- Phase A GO：正式 Preview Pipe 输入合同。
- Phase B GO：Pipe overlap graph、stable coloring、batch 内无 overlap、正序/逆序 independent Exact Boolean staging。
- immutable Boundary Edge identity、Pipe/side/source-patch ownership、consumer 双向引用和 ledger 框架。
- `utils/experimental_pipe_chamfer_utils.py::_bridge_then_fill()` 中的 BMesh API 调用形态与 Bridge 后 boundary 重提取时序。
- `tests/blender_test_driver.py::test_experimental_pipe_chamfer_bridge_then_fill_smoke()` 只作为 API mechanics canary。

### 4.2 不能当作 GO 证据

- 2026-07-23 的旧 `14/14 × 3` 已因 fake green 撤销。
- 历史 `2 PASS / 12 FAIL` 只说明旧策略失败分布。
- full-cyclic lift/phase/DP、L5/R3 trim 和任何 distance score 都是旧 WIP。
- 旧 Bridge→Fill smoke 不是 junction 语义证据，也没有覆盖 unequal segmentation 或 cyclic twist。
- `bridge_loops()` 返回 Faces 不代表宽度、方向、自交、provenance 或产品 topology 正确。
- 用户手测已确认普通 open unequal rails 可 Bridge；这证明 Blender UI/API mechanics 能力，不替代真实 L5/R3 的宽度、方向、无自交与 provenance 产品门禁。
- 当前 dirty worktree 中的 evidence-runner hardening 只有在 host 单测、diff audit 与新鲜 artifact 通过后才能标记完成。
- `_zero_length_regular_connector_handoff_proof()` 的已知控制流错位必须先修复并补正负合同。

### 4.3 Blender API 边界

以 Blender 5.0+ API 为准：

- [`bmesh.ops.bridge_loops`](https://docs.blender.org/api/current/bmesh.ops.html#bmesh.ops.bridge_loops) 从 Edge loops 创建 Faces。[Blender `bmo_bridge.cc`](https://github.com/blender/blender/blob/main/source/blender/bmesh/operators/bmo_bridge.cc) 的普通 `use_merge=False` 分支支持不同数量 Edge，并会对结果 triangulate/beautify；equal-count 检查仅属于 `use_merge=True`。cyclic twist 与产品宽度/方向/provenance 仍由本项目合同验证。
- [`bmesh.ops.contextual_create`](https://docs.blender.org/api/current/bmesh.ops.html#bmesh.ops.contextual_create) 对应 Edit Mode `F` 的核心 BMesh 路线，也是旧 operator 已采用的手工语义。Phase D 每次只传一个已证明的 cycle，并在 cloned provisional BMesh 中验证 job 外 geometry fingerprint 不变。
- [`bmesh.ops.edgeloop_fill`](https://docs.blender.org/api/current/bmesh.ops.html#bmesh.ops.edgeloop_fill) 面向一个或多个不重叠 Edge loops，只作自动对照候选；只有与用户确认的 `F` 视觉/拓扑语义一致时才可替换。

## 5. 不可变范围与禁止路线

V1/V2 产品范围固定为四个 `.blend` fixture、7 个 Objects、radius `{0.01, 0.03}`，共 14 cells；每格至少重复 3 次。不得写对象名、fixture、坐标、Edge/Vertex index 或 Pipe ID 特判。

继续禁止：

- SDF / `Points to SDF Grid → Grid to Mesh`；
- nearest-owner、nearest-rail、`_rail_pair_score()` 或距离 score 决定 rail pairing；
- Phase C 内 Junction Fill、terminal cap 或 final product assembly；
- global fill、centroid fan、无约束 triangulate；
- 共享 working Mesh 上按 batch 顺序累计 Cut；
- 放宽 handoff/setback/width/monotonic/zero-area guard 掩盖 regular 失败；
- 忽略大 fragment、重复 provenance、zero-area、self-intersection 或 non-manifold；
- Phase C GO 前进入 Phase D/E；
- Phase E 前修改正式 `hst.feature_chamfer_gn(FINALIZE)` runtime path；
- 修改 `auto_load.py`；
- 修改或再次提交 `tests/.DS_Store`。

Junction-local Fill 与 global fill 的边界在 Phase D 固定为：

```text
允许：assembled BMesh 上的单一闭合洞，全部 Boundary Edge/ports
     唯一映射到同一个 structural junction_region_id，
     且不存在 unresolved regular Edge 或已占用 Face。

禁止：遍历所有剩余 cycles 并无条件 Fill；
     只因闭合、距离接近或 Blender op 成功就认定为 junction；
     把 terminal、ordinary hole 或多个 junction region 混成一个 FillJob。
```

## 6. Phase C 数据流与合同

### 6.1 当前 runtime 事实

`_run_independent_batch_cut_probe()` 为每个 semantic batch 从同一 source 建立独立 Cut，序列化 `boundary_records` 后删除临时 `working_object/working_mesh`。因此 Phase C 当前只有 topology/provenance records，没有一个包含全部 batches 的活 BMesh。V2 不再假设该 BMesh 已存在。

### 6.2 Phase C 数据流

```text
formal PREVIEW contract
→ forward/reverse independent Exact Boolean staging
→ immutable Boundary Edge universe records
→ structural overlap intervals + Plan ports
→ ownership-driven RegularBridgeJob producer
→ global claim preflight（尚不改 ledger）
→ 每个 job 重建 job-local provisional BMesh
→ Blender bridge_loops()
→ serialize Bridge Faces / new terminal Edges / provenance
→ strip geometry guards + permutation/reversal guards
→ atomic publish Phase C records + PORT_RESERVED ledger
→ debug artifacts（不是 final Mesh）
```

job-local BMesh 的输入 Vertex 必须由 stable endpoint token 重建 identity；禁止按“坐标接近”焊接。相同 token 对应不同坐标或不同 token 被意外合并时立即失败。job-local output 只能证明 regular patch backend；不能宣称 source surface 已 assembled 或最终 watertight。

### 6.3 RegularBridgeJob

建议合同：

```text
RegularBridgeJob {
    job_id,
    semantic_batch_key,
    pipe_id,
    strand_id,
    correspondence_id,
    source_patch_pair,
    left_edge_ids,
    right_edge_ids,
    left_endpoint_tokens,
    right_endpoint_tokens,
    chain_kind: OPEN | CYCLIC,
    port_witness_ids,
}
```

生成规则：

- 左右侧来自同一 `pipe_id/strand_id/correspondence_id/source_patch_pair`。
- 左右必须同为 `OPEN` 或同为 `CYCLIC`；每侧连通、有序、无分支、无重复 Edge。
- 先减去有直接结构证据的 overlap/terminal port Edge 和严格 connector Edge。
- 一个 Boundary Edge 最多属于一个 BridgeJob；冲突在调用 Blender 前失败。
- 多个候选 pair 只能由 Plan correspondence、ownership、port token 和结构连通性唯一决定。
- 无唯一 pairing 时记录 `UNRESOLVED` 并使当前 Step STOP；不得选最近的一对。

Blender Bridge 调用合同：

- 每个 job 单独调用 `bmesh.ops.bridge_loops()`；不依赖 Edit Mode selection/context。
- 将完整左右 Edge sets 一次交给 Blender，不自研逐点 zipper、cyclic DP 或 seam rotation。
- 每个 job 恰好包含两条 rails，固定 `use_pairs=False`、`use_cyclic=False`、`use_merge=False`。单条 rail 的 OPEN/CYCLIC 由 Blender 自动提取的 loop topology 决定；`use_cyclic` 只控制“三条以上 loops 时是否把最后一条再 Bridge 回第一条”，不是 chain closure 开关。
- closed pair 默认 `twist_offset=0`，允许 Blender 内部 best rotation；禁止项目用 distance score 决定 rail owner/pair。只有 Plan topology 有直接结构证据且用户手测证明默认 rotation 不符合产品语义时，才研究 explicit `twist_offset`。
- `OPEN` 必须验证两端新 boundary Edge 能唯一继承 port witness。
- `CYCLIC` 必须验证 Edge input permutation、左右交换和方向 reversal 不改变 canonical Faces；如 Blender 默认 twist 不稳定，Phase C STOP，只允许研究由 Plan topology 直接证明的 explicit `twist_offset`，不得恢复 heuristic matching。
- unequal segmentation 的普通 Bridge 能力已由用户 UI 手测与 Blender 源码确认；真实 L5/R3 仍须通过拓扑、宽度、方向和 provenance guards 后才能纳入 GO。
- op 返回空 Faces、修改 job 输入外 geometry 或产生未记录 geometry 时整个 job 失败。

### 6.4 Claim ledger 与 Face provenance

Phase C 在几何操作前建立全局 claim：

```text
edge_id → REGULAR_BRIDGE(job_id, side)
        | PORT_RESERVED(port_or_region_witness_id)
        | STRICT_CONNECTOR(proof_id)
        | UNRESOLVED(reason)
```

守恒门：

```text
Boundary Edge universe
== bridge_claim_edges ∪ port_reserved_edges
   ∪ connector_claim_edges ∪ unresolved_edges
且四者 pairwise disjoint
```

必须分别记录：

- `claim_state`：每条 Boundary Edge 恰好一个分类。
- `face_consumer_id`：只有实际产生 regular Face 的 Bridge Edge 才能非空。
- `PORT_RESERVED` 在 Phase C 的 `face_consumer_id` 必须为空；它的 Go 证据是唯一 port witness，不是伪造 Face consumption。
- 每个 Bridge input Edge 恰好关联一个新 chamfer Face consumer；每个新 Face 反查唯一 BridgeJob。
- 新 terminal Edge 记录 deterministic derived ID、端点 tokens 与 port witness，供 Phase D assembly 使用。

### 6.5 事务与 guards

- producer 完成全局 claim preflight 后才执行 jobs。
- 每个 job 在独立 provisional BMesh 运行；异常补充 job/pipe/strand 上下文后 rethrow。
- job 的 geometry、provenance、guards 全通过后才原子写入 provisional records/ledger。
- 任一 job 失败，丢弃全部 Phase C provisional publication；正式 source、Preview、旧 Finalize 和上次成功 artifact 不变。
- zero-area、duplicate Face、orientation、fold-over/self-intersection、overconnected Edge 为 0。
- Bridge strip 的 combinatorial boundary 必须等于预期 rails + derived terminal ports；不得出现额外开放支路。
- forward/reverse staging 以及 canonical input permutation 的 BridgeJob、Faces、ledger、ports fingerprints 一致。
- source Mesh unchanged；无 allowlist 外 setback/handoff。
- **Phase C 不要求最终 `link_faces == 2` 或 watertight**：结构化 ports 是本阶段预期输出。closed-manifold 是 Phase D gate。

## 7. 已知失败 cluster 的处理

### Cluster A — cyclic full-span / common-only remainder

ownership 唯一确定完整左右 cycles 后，将完整 Edge sets 交给 Blender。是否能稳定选择正确 twist 由 cyclic permutation/reversal 合同和真实 fixtures 决定；不能先写成已解决。任何未 claim 的 macro Edge 都是 coverage failure。

### Cluster B — cyclic provenance duplicate

全局 claim map 在 op 前阻止一个 Edge 进入多个 BridgeJob；不得依赖 component 迭代顺序或事后 ledger 去重。

### Cluster C — bilateral DP/trim failure

删除自研 DP/trim 主路径。普通 unequal Bridge 能力已确认；若真实 cell 生成的 strip 未通过产品 guards，该 cell STOP，但不得把它误报为 Blender 不支持 unequal rails，也不得放宽 setback 或把失败 Edge 移到 port。后续 pivot 必须另写决策文档。

### Cluster D — zero-length connector

先修复 connector proof 控制流。只有唯一结构 proof 的零长度 Edge 可进入 `STRICT_CONNECTOR`；它不进入 Bridge，也不能带走邻近正常 Edge。必要 collapse 只发生在该 proof 的 job-local/provisional geometry。

### Cluster E — tricky Solid.004 r0.01 假绿

旧 7 个 macro residual 必须进入 BridgeJob 并产生 Face witness，或作为 unresolved 使门禁失败。只有严格批准的短 component、terminal/junction port 或 zero-length connector 可离开 regular；Phase C 没有 Fill 出口。

## 8. Phase C 分步执行与 Stop/Go

### Gate 0A — 只读恢复真实基线

目标 Operator：正式 `PREVIEW` → hidden Phase C Adapter。
用户操作：无。
预期可见变化：无。
自动证据：HEAD/status/diff、入口链、baseline ancestry、文档/代码一致性记录。

操作：

1. 读取 `AGENTS.md`、本文、上游 handoff、`tests/TESTING_POLICY.md`、`tests/README.md`。
2. 记录实际 `git HEAD/status/diff`；不得 reset、覆盖或擅自提交现有 dirty changes。
3. 确认 `1b8f120` 仍是祖先，并审计其后的 runtime/test diff。
4. 确认正式 `FINALIZE` 仍走旧 backend、hidden Adapter 仍是 Phase C 唯一验收 seam。

Go：baseline 可追溯，dirty paths 均有归属，入口链与本文一致。
Stop：出现未解释的正式 runtime 修改、Phase A/B/Preview contract 或 source integrity 回归。

### Gate 0B — Evidence runner hardening

目标 Operator：同 Gate 0A。
用户操作：无。
预期可见变化：无。
自动证据：host fake-green tests、唯一 run directory、manifest/hashes、非零负向退出。

- full gate 直接要求 14 cases、42 repetitions、Phase A/B/C、Preview/source/Adapter/debug cleanup 全部通过。
- unknown case、0 executed、requested/executed mismatch、partial run 必须 non-zero。
- partial run 的预期状态是 `DIAGNOSTIC_PARTIAL`；其 non-zero 不等于算法 crash，调用方必须读取 artifact。
- summary 绑定 run-id、Git HEAD + dirty fingerprint、argv、Blender/fixture/code hashes、artifact manifest/sha256。
- 先审计当前 dirty evidence-runner diff，再运行 `python3 -m unittest tests.test_feature_chamfer_evidence_runner`。

Go：fake-green 负向合同通过；stale/partial artifact 不能成为 GO。
Stop：runner 仍可只信 backend `phase_c_go` 或复用旧目录。

### Gate 0C — 修复 connector 与隔离旧策略

目标 Operator：hidden Phase C Adapter。
预期可见变化：simple baseline 仍诚实失败或通过既有已证路径。
自动证据：connector 正负合同、旧策略 runtime capture、API smoke。

1. 修复 `_zero_length_regular_connector_handoff_proof()` 控制流并补 valid/rejection contracts。
2. 为 full-cyclic DP/trim、distance matching 建立明确隔离边界；新 path 不得调用。
3. 运行旧 Bridge→Fill smoke，但只记录为 API mechanics canary。
4. 保存 `simple__extruded_002__r0p010` 的 commit/dirty-bound V2 前失败基线。

Go：connector 合同可信，旧 WIP 不可从 V2 path 到达，环境/fixtures/Adapter 可信。
Stop：旧 fallback 仍可被调用，或 runner/fixture/Operator 不可信。

### Step 1 — RegularBridgeJob 与 Blender Bridge 合同先行

新增最小正负合同：

- 将用户已完成的 open unequal-rail UI 手测记录为 Blender UI mechanics 证据；自动化再补 synthetic `5 vs 3` smoke 防回归，但它不是产品拓扑接受证据，也不是阻止 Phase C 设计成立的探索性 capability gate。
- Plan correspondence 唯一配对 open rails；ambiguous pair fail-closed。
- 同一 Edge 被两个 jobs claim 时 fail-closed。
- job-local endpoint token 重建不按坐标误焊。
- open same-count Bridge 生成 strip 与两端 derived ports。
- cyclic Bridge 在 input permutation、左右交换、方向 reversal 后 canonical invariant。
- 真实 L5/R3 Bridge 只有 geometry/provenance 全通过才转为产品证据。
- Blender op 异常、空 Faces、extra geometry 全部 rollback。

Go：正负合同通过；synthetic `5 vs 3` smoke 与用户已验证的普通 open unequal Bridge 行为一致；新 path 无 `_rail_pair_score()`、自研 cyclic DP/trim/zipper。
Stop/Pivot：仍需 distance/fixture hint 决定 pairing/twist，或真实 L5/R3 的产品 guards 失败。此时按实际 topology/geometry 诊断另写 pivot；不得把 `use_merge=True` 的 equal-count 文案套到普通 Bridge，也不得擅自恢复旧 DP/trim。

### Step 2 — Ownership-driven BridgeJob producer

只生成 jobs/claims/diagnostics，不调用 Blender：

- 从 immutable Boundary universe 按 Pipe/strand/Plan rail/source patch 分组。
- 用 overlap components、Plan ports 与 frozen allowlist 切出 regular chains。
- 输出 jobs、port reservations、connectors、unresolved、claim conflicts 和守恒 diagnostics。
- 对 forward/reverse staging 生成相同 canonical job fingerprint。

Go：simple 4 cells 中所有预期 regular Edge 恰好进入一个 BridgeJob；port/connector/unresolved 互斥；macro unresolved=0。
Stop：duplicate/missing claim、距离配对或把普通 Edge 伪装成 port。

### Step 3 — Simple 4 cells：job-local Blender Bridge backend

运行：

1. `simple__extruded_002__r0p010`
2. `simple__extruded_002__r0p030`
3. `simple__solid_44__r0p010`
4. `simple__solid_44__r0p030`

每格先 1 次，全部通过后各 3 次。要求：

- full regular rails 由 Blender Bridge 生成完整 Faces；
- regular unresolved/claim conflict 为 0；
- Bridge input Edge↔Face witness 100%；reserved ports 的 Face consumer 为空；
- zero-area/orientation/fold-over/self-intersection/overconnected 为 0；
- forward/reverse/permutation fingerprints 一致；
- 无 Fill、final assembly、macro setback 或旧 fallback。

Go：simple `4/4 × 3` 新鲜 PASS，artifact 明确标记 `REGULAR_CORE_DEBUG`。
Stop：只 Bridge 局部 rail，或通过 reserved port 掩盖 regular Edge。

### Step 4 — 同根 cyclic cluster

运行：

- `tricky__solid_016__r0p010/r0p030`
- `tricky_b__extruded_003__r0p010/r0p030`

Go：4 cells 各 3 次通过；cyclic twist/permutation invariant；simple canary 保持绿。
Stop：common-only macro remainder、twist 不稳定、重复 claim 或 port 越界。

### Step 5 — Provenance conflict cluster

运行：

- `tricky_b__extruded_002__r0p010/r0p030`
- `mixed__extruded_002__r0p010`

Go：3 cells 各 3 次通过；claims 在 op 前唯一；没有丢弃 parent/residue Edge。
Stop：结果依赖 job 顺序、事后去重或多个 source patch witness。

### Step 6 — L5/R3 与 zero-length cluster

先运行 `tricky__solid_004__r0p030`，直接证明 Blender Bridge 对真实 L5/R3 的实际行为；再运行 `mixed__extruded_002__r0p030`，证明零边只由严格 connector proof 保留。

Go：两个 cells 各 3 次通过；L5/R3 topology/width/provenance 全绿；simple canary 绿。
Stop：Blender 只返回 Faces 但产品 guard 失败、大 Edge 被 setback、零边带走正常 Edge。

### Step 7 — tricky Solid.004 r0.01 假绿审计

运行 `tricky__solid_004__r0p010` 三次：

- 旧 7 个 macro residual 全部进入 Bridge 并有 Face witness；
- `pipe0 0:5` 只在通用 `SHORT_COMPONENT_SETBACK_V1` 全部直接 proof 成立时保留；
- pipe2 terminal-tail reconciliation 双向唯一；
- 无 folded/numeric/direct terminal 大 Edge例外；
- `fill_job_count == 0`，不存在 Phase C Fill fallback。

Go：3 次稳定，regular unresolved=0，unexpected/macro setback=0。
Stop：Bridge 失败被 port/handoff 掩盖。

### Step 8 — 完整 Phase C gate

运行完整 headless regression，再运行 `14 cells × 3 repetitions`。必须直接核对：

- 14/14 cases、42/42 repetitions PASS/stable；
- Phase A/B/C、Preview contract、source unchanged；
- Boundary claim partition exact/disjoint；
- regular Edge Face consumption exactly once；reserved port Face consumption 为 0；
- BridgeJob claim conflict、regular unresolved 为 0；
- regular Face provenance 双向完整；
- zero-area/orientation/self-intersection/overconnected 为 0；
- forward/reverse/permutation 的 jobs/Faces/ledger/ports fingerprints 一致；
- handoff reason 全在 frozen allowlist，unexpected/macro setback 为 0；
- `fill_job_count == 0`、`final_output_object_name == null`；
- artifacts 与实际 HEAD/dirty fingerprint/argv/hashes 一致。

Go：仅标记 `PHASE C CANDIDATE_GO / EVIDENCE_READY`；仍保持文档头部 `PHASE C STOP`，等待 Step 9 独立审计。
Stop：stale/partial/fake-green、缺失 Face witness、reserved port 冒充消费或 artifact 暗示 final product。

### Step 9 — 独立 Spec Audit

由未参与实现的只读 reviewer 核对：

- diff 实际修改 hidden Phase C runtime path，正式 `FINALIZE` 未提前修改；
- Cut 仍为 independent staging；不存在共享 Mesh 顺序累计；
- job-local BMesh 事实与文档一致，没有虚构 assembled BMesh；
- V2 使用 ownership-driven Blender Bridge；没有 Fill、nearest、score、cyclic DP/trim fallback；
- claim、Face provenance、rollback 和 port reservation 有直接证据；
- 14×3 artifacts 新鲜，runner 无 fake green；
- 审计开始时状态仍为 `PROTOTYPE / PHASE C STOP / CANDIDATE_GO`，没有跨级声称 `INTEGRATED/VERIFIED`。

存在 P0/P1 或高严重度偏差：Phase C 保持 STOP。
无高严重度问题且全部 gate 通过：更新本文和上游 handoff 为 `PHASE C GO / global PROTOTYPE`，然后单独制定 Phase D implementation plan。

## 9. Phase D 入口草案（当前禁止执行）

Phase C GO 只授权写 Phase D 计划，不自动授权修改正式 runtime。Phase D 必须按以下硬门禁推进：

### D0 — 先证明 batch-neutral product assembly

当前没有共享 provisional BMesh。Phase D 必须选择并证明一种不会引入 batch priority 的 assembly contract，例如：

- 用 independent ownership records 约束一个 canonical combined product Cut；或
- 从 independent staging 按 stable source/Face identity 去重并组装 substrate。

选择前须写 ADR/计划。禁止简单拼接多个完整 source staging，也禁止顺序 Apply batches。Go 证据至少包括正/逆序相同、Boundary 可反查 Phase C ports、source unchanged 和可读 `.blend` artifact。

### D1 — Structural closure jobs

从 assembled BMesh 重新提取 remaining boundary graph，生成：

```text
JunctionFillJob {
    junction_region_id,
    structural_witness_ids,
    participating_pipe_ids,
    boundary_edge_ids,
    bridge_terminal_edge_ids,
    source_port_ids,
}

TerminalCapJob {
    terminal_port_id,
    boundary_edge_ids,
    source_patch_witness_ids,
}
```

`junction_region_id` 必须由 overlap/setback/Plan-port 的结构连通分量生成，不得假设 `ChamferPlan` 已有该字段。一个 Plan port 不强制等于一个 Fill hole；inventory gate 比较的是 planned closure jobs 与实际唯一 witnesses，不是简单比较数量。

### D2 — 最小真实双 Pipe prototype

先对矩阵中最小真实双 Pipe cell：assembled BMesh → regular Faces → remaining boundary → 唯一 JunctionFillJob → `contextual_create()` 复现用户确认的 `F` → topology/provenance/rollback。每次只传单一 cycle，并要求 job 外 geometry fingerprint 不变；`edgeloop_fill()` 仅作对照，不自动替代产品语义。

Go：closed manifold、所有 closure Faces 有唯一 job provenance、无 global fill、正逆序一致。
Stop：洞不是闭环、混合 regions、需要 Fill ordinary cycle、吞入 unresolved regular Edge，或 assembly 未证明。

Phase D 全矩阵通过后仍只能是 `Backend PROTOTYPE`；Phase E 才从正式 `hst.feature_chamfer_gn(PREVIEW→FINALIZE)` 做 Operator/Visual/Product 验收。

## 10. 验证命令

Blender executable：

```text
/Applications/Blender.app/Contents/MacOS/Blender
```

Host fake-green contracts：

```bash
python3 -m unittest tests.test_feature_chamfer_evidence_runner
```

语法检查：

```bash
PYTHONPYCACHEPREFIX=/tmp/hst-feature-chamfer-pycache \
python3 -m py_compile \
  utils/feature_chamfer_batched_finalize_utils.py \
  tests/blender_test_driver.py \
  tests/feature_chamfer_batched_matrix_driver.py \
  tools/run_blender_tests.py \
  tools/run_feature_chamfer_batched_matrix.py
```

完整 regression：

```bash
python3 tools/run_blender_tests.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/full-regression
```

单格诊断（预期 runner 返回 non-zero，并写 `DIAGNOSTIC_PARTIAL`）：

```bash
python3 tools/run_feature_chamfer_batched_matrix.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/single-cell \
  --stage PHASE_C_REGULAR_CORE \
  --repetitions 1 \
  --case simple__extruded_002__r0p010
```

完整 Phase C：

```bash
python3 tools/run_feature_chamfer_batched_matrix.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/phase-c \
  --stage PHASE_C_REGULAR_CORE \
  --repetitions 3
```

每次使用不存在的唯一 artifact directory。macOS Blender 5.1.2 若在 fixture 加载前因 Metal `supports_barycentric_whitelist` 崩溃，可原命令重试一次并记录环境失败；算法阶段异常不得归为 Metal crash。

## 11. 实现纪律

- 先按 UI→Operator→invoke/execute→runtime path→用户可见结果核对入口。
- 不修改 `auto_load.py`；功能函数添加中文块注释；imports 位于文件头。
- 新路径只抽取旧 BMesh API 调用模式，不复制旧 pairing/global-fill 控制流。
- Blender op 异常补充上下文后 rethrow，不 silent fallback。
- 每个 Step 先直接合同，再单格 1 次，再 cluster 3 次，并重跑 simple canary。
- 前一 Step 未 GO 时不得实现后续 Step；Phase C 未 GO 时不得写 Phase D runtime。
- 不因 isolated smoke、单格、watertight ribbon 或 API 返回 Faces 更新 GO。
- 不默认提交大 artifacts；未经用户允许不开分支、不自动 commit。
- 保留 `tests/.DS_Store`，不修改、不加入提交。
- 长程任务最终完成、失败或需用户实质决定时，才按 `task-completion-notifier` 发送一次对应通知。

## 12. Suggested Skills

- `context7-cli`：核对 Blender 5.0+ BMesh API 合同。
- `blender-cli`：运行 Blender background contracts、matrix 与 artifacts。
- 项目内 `agent-skills/hst-blender-regression/SKILL.md`：统一 headless regression。
- `diagnosing-bugs`：按 BridgeJob/claim/port cluster 窄化 diagnostics。
- `tdd`：先写 ownership、cyclic/unequal Bridge、rollback 正负合同。
- `code-review`：Phase C GO 前独立 Spec Audit。
- `verification-before-completion`：核对 run-id、HEAD、42 repetitions 和 artifact hashes。
- `task-completion-notifier`：仅最终 completed/attention/failed 使用。

通用 skill 不可用时，使用项目 regression skill 和等价验证流程，不因此停止。

## 13. 新 Session 启动 Prompt

```text
继续 HardsurfaceGameAssetToolkit Feature Chamfer batched Phase C。

先读取并严格遵守：
1. 项目 AGENTS.md
2. docs/plan/2026-07-24-feature-chamfer-phase-c-regular-recovery-plan.md
3. docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md
4. tests/TESTING_POLICY.md 与 tests/README.md

策略为 OWNERSHIP_DRIVEN_BLENDER_BRIDGE_THEN_LOCAL_FILL_V2。Phase C 只做 regular core：从正式 PREVIEW 与 independent staging Boundary universe 生成 ownership-driven RegularBridgeJob，在 job-local provisional BMesh 调用 bmesh.ops.bridge_loops()，发布 regular Face/provenance 与 PORT_RESERVED records。Phase C 禁止 Junction Fill、terminal cap、final product assembly；Phase D 才先证明 batch-neutral assembly，再从实际 assembled BMesh 构造 JunctionFillJob/TerminalCapJob。Phase E 才接入正式 hst.feature_chamfer_gn(FINALIZE)。

ownership 只决定 rail 集合，不自动证明 cyclic twist。普通 open unequal Bridge 已由用户 UI 手测与 Blender 源码确认；后续只需用自动 synthetic 5-vs-3 smoke 防回归，并用真实 L5/R3 合同验证产品 topology/width/orientation/provenance。失败时按实际 guard 诊断 STOP，不得恢复 _rail_pair_score、nearest、自研 cyclic DP/trim/zipper 或放宽 setback。

先记录实际 HEAD/status/diff，不得 reset 或覆盖 dirty changes；不修改 tests/.DS_Store、auto_load.py，不开分支。按 Gate 0A/B/C → Step 1–9 推进。partial matrix runner 预期 non-zero 且写 DIAGNOSTIC_PARTIAL；只有新鲜完整 14×3 + 独立 Spec Audit 可将 Phase C 更新为 GO。当前全局状态仍为 PROTOTYPE，除非真正需要用户作实质决定，否则持续自主推进。
```
