# Feature Chamfer Phase C — Regular Recovery 续作计划

日期：2026-07-24  
状态：`PAUSED / PROTOTYPE / PHASE A GO / PHASE B GO / PHASE C STOP`  
文档 HEAD：`92d2953` (`docs(feature-chamfer): add phase c regular recovery plan`)
代码 baseline：`1b8f120` (`wip(feature-chamfer): checkpoint phase c regular diagnostics`)
上游权威 handoff：`docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md`

本文是下一次 Session 的执行入口。权威顺序固定为：项目 `AGENTS.md` → 上游 handoff 的不可变产品语义/Phase A→E 阶段边界 → 本文的 Phase C 当前事实、执行策略与门禁。上游 handoff 中已撤销的历史绿灯和旧暂停数字只保留诊断价值，不能覆盖本文的新鲜状态；其他冲突必须停止并更新计划。

## 1. 给下一位 Agent 的一句话任务

保留已经通过的 Preview Pipe、independent batched Exact Boolean、Boundary provenance 与 exactly-once ledger；停止增加 setback/handoff 例外，重新收敛 Phase C 的 cyclic/open regular rail 配对，使 14 个产品矩阵 cell 的所有非 junction 区都真正生成 chamfer strip。Phase C 全矩阵和独立审计通过前，不得进入 Phase D/E，也不得接入正式 `hst.feature_chamfer_gn(FINALIZE)`。

## 2. 非技术进度说明

当前已经能可靠完成三件事：

1. 找到模型上需要倒角的槽线，并复用正式 Preview 的 Pipe。
2. 多条相交槽线按互不冲突的批次独立切割，切割顺序不会决定产品结果。
3. 给切出来的每条 Boundary Edge 保存稳定身份和 owner；未处理的边不能再被测试静默忽略。

尚未完成的是“把一对切口边稳定地拉成倒角表面”。尤其闭环两侧虽然是同一圈，但投影起点不同；旧算法只填两圈参数重叠的部分，把其余大段遗留给后续 handoff。先前一些宽松 handoff 又把这些大段误当成 junction，造成假绿。独立审计发现后，相关宽松路径已经关停或加严，因此当前失败是诚实的。

可以继续复用的底层能力很多，不建议推倒重来。应把范围聚焦在“regular rail 的规范化、分段、唯一配对和事务式提交”。

## 3. 当前可信状态与证据边界

### 3.0 目标入口合同

当前存在三条必须分开的入口链：

```text
产品 PREVIEW
UI 主按钮(action=AUTO)
→ hst.feature_chamfer_gn.invoke/execute(PREVIEW)
→ ensure_gn_feature_chamfer_preview()
→ owned Curve + GN Preview modifier + GN_PREVIEW_PIPE_V1 contract

当前产品 FINALIZE
同一 UI/Operator
→ hst.feature_chamfer_gn.invoke/execute(FINALIZE)
→ build_pipe_chamfer(debug_stage=PATCHED, feature_graph_contract=GN_PREVIEW_V1)
→ 产品 output Object / PATCHED 状态

Phase C 验收
matrix
→ 正式 hst.feature_chamfer_gn(PREVIEW)
→ INTERNAL hst.experimental_feature_chamfer_batched_finalize(PHASE_C_REGULAR_CORE)
→ build_batched_feature_chamfer()
→ diagnostics/debug artifacts only
```

Batched backend 读取 owned Preview Curve 上冻结的 `GN_PREVIEW_PIPE_V1` immutable Pipe contract，并通过同一 Even-Thickness builder 重建临时 Pipe Mesh；它不是直接复用 evaluated GN cutter Mesh。Phase C 当前返回 `PROTOTYPE`、`output_object_name=None`，并在结束时清理临时数据。

因此 Phase C 证据只覆盖 `Algorithm`、`Backend` 和隐藏实验 Adapter seam。即使 Phase C GO，全局产品状态仍是 `PROTOTYPE`；不得声明正式 `FINALIZE` 已 `INTEGRATED`，也不得声明 `Visual/Product` 已 `VERIFIED` 或 `ACCEPTED`。

### 3.1 已确认通过

- Phase A：正式 Preview Pipe 输入合同为 GO。
- Phase B：Pipe overlap graph、stable coloring、batch 内无 overlap、正序/逆序 independent Exact Boolean staging 为 GO。
- Source 保持不变；Boundary provenance、consumer 双向引用、outside-plan 分类、geometry guard 和 artifact 保存路径已经建立。
- 以下定向 handoff guard 曾运行通过，但 artifact 时间早于代码 baseline commit 约 8 秒，且 JSON 不含 commit/run-id/argv，当前只能作为弱基线，Step 0 必须在独立目录重跑：
  - `feature_chamfer_batched_short_component_setback_contract`
  - `feature_chamfer_batched_plan_span_crossing_handoff_contract`
  - `feature_chamfer_batched_structural_handoff_reconciliation_contract`
  - `feature_chamfer_batched_regular_numeric_fragment_handoff_contract`
  - `feature_chamfer_batched_regular_terminal_extension_contract`
  - `feature_chamfer_batched_cyclic_seam_boundary_handoff_contract`
- 历史 `py_compile` 通过只证明语法；它不能发现控制流错位。macOS 验证必须设置可写 pycache，例如 `PYTHONPYCACHEPREFIX=/tmp/hst-feature-chamfer-pycache`。

### 3.2 不可当作当前 GO 证据

- 2026-07-23 曾有一次 `14/14 × 3` 自动绿，但已因 fake green 被正式撤销。
- 最近一次完整严格矩阵曾得到 `2 PASS / 12 FAIL`；它用于说明失败分布，不代表 checkpoint 后当前代码的最终数字。
- 顶层 `tests/artifacts/feature_chamfer_batched_matrix/results.json` 会被每次定向 run 覆盖。本文编写时它只包含 `simple__extruded_002__r0p010` 的单格失败，不得误读为完整矩阵。
- 各 cell 的历史诊断仍在 `tests/artifacts/feature_chamfer_batched_matrix/<case>/diagnostics.json`；使用前必须核对 `mtime`、运行参数和当前 commit。
- checkpoint 中包含尚未证明正确的 full-cyclic 实验代码。它是 WIP，不是完成方案。
- 当前 matrix runner 的 `phase_c_go` 汇总门禁存在 fake-green 风险：它未直接要求每个 case/repetition 的总状态、Phase A/B、Preview contract、source unchanged 与无 debug 残留全部通过；必须先修 runner，旧 `phase_c_go` 字段不能单独作为 GO 证据。
- `_zero_length_regular_connector_handoff_proof()` 当前在建立 `unique_records` 后隐式返回 `None`；其余判定代码误落在 `_regular_overlap_bridge_handoff_proof()` 的无条件 `return` 之后，属于不可达代码。`py_compile` 不会发现，Step 0 必须先用直接合同测试锁定并修复控制流边界。

### 3.3 当前产品状态

- `Algorithm`：部分通过。
- `Backend`：Phase C prototype，未 GO。
- `Operator`：实验 Adapter；正式 FINALIZE 未接入。
- `Visual/Product`：未验证、未接受。

## 4. 不可变范围与禁止路线

V1 完成范围固定为四个 fixture、7 个对象、radius `{0.01, 0.03}`，共 14 个 cells；每格至少重复 3 次。全部通过才能进入后续阶段。不得为对象名、坐标、Edge/Vertex index 或 fixture 写特判。

继续禁止：

- SDF / `Points to SDF Grid → Grid to Mesh`；
- nearest-owner 或投影最近邻回退；
- global fill、centroid fan、无约束 triangulate；
- 共享 working Mesh 上按顺序累计 Cut；
- 用扩大 setback/handoff 范围掩盖 regular 失败；
- 把 zero-area、non-monotonic、width failure 或大 fragment 简单忽略；
- Phase C GO 前进入 Phase D/E；
- Phase C GO 前接入正式 `hst.feature_chamfer_gn(FINALIZE)`；
- 修改 `auto_load.py`；
- 提交 `tests/.DS_Store`。

## 5. 当前工作树与关键文件

checkpoint 已提交全部 Phase C WIP 代码和测试。正常工作树只应残留：

```text
 M tests/.DS_Store
```

保留该文件，不修改、不清理、不提交。

主要实现：

- `utils/feature_chamfer_batched_finalize_utils.py`
- `tests/blender_test_driver.py`
- `tests/feature_chamfer_batched_matrix_driver.py`
- `tools/run_feature_chamfer_batched_matrix.py`

主要 artifacts：

- `tests/artifacts/feature_chamfer_batched_matrix/results.json`
- `tests/artifacts/feature_chamfer_batched_matrix/<case>/diagnostics.json`
- `tests/artifacts/feature_chamfer_batched_matrix/<case>/ledger.json`
- `tests/artifacts/feature_chamfer_batched_matrix/<case>/phase_c_regular_core.blend`
- `tests/artifacts/feature_chamfer_batched_matrix/<case>/phase_c_regular_core_overview.png`
- `tests/artifacts/feature_chamfer_batched_matrix/<case>/phase_c_setback_closeup.png`

## 6. 失败聚类与应有产品语义

### Cluster A — cyclic full-span 的 common-only remainder

涉及的已知 cells：

- `simple__extruded_002__r0p010`
- `simple__extruded_002__r0p030`
- `simple__solid_44__r0p010`
- `simple__solid_44__r0p030` 的 seam 邻近变体
- `tricky__solid_016__r0p010`
- `tricky__solid_016__r0p030` 的同侧重复/缺对侧变体
- `tricky_b__extruded_003__r0p010`

根因：`_common_atom_component_intervals()` 与 `_partition_run_to_component_intervals()` 只保留左右 rail 的参数交集。闭环两侧的参数 seam/phase 不同，交集之外的 macro remainder 没进入 regular matching，也没有成为 unresolved component；直到 ledger 尾端才报 `UNPROVEN_PLAN_BOUNDARY_EDGE`。

这些长边是 regular，不是 junction。正确结果必须让整圈两侧由同一个 cyclic correspondence 消费并生成 Faces。

最近加入但尚未证明的实验函数：

- `_align_cyclic_stable_chain()` 的调用接入；
- `_lift_full_cyclic_atom_runs()`；
- `_align_full_cyclic_atom_run_phase()`；
- `_full_cyclic_regular_pair_candidate()`。

当前实验仍未解决完整闭环：它可以把两侧 seam 靠近，但 strip guard 仍会在闭合端看到大宽度跳变，或只生成到一侧较短终点。新 Session 必须先审计这些函数；可删除、替换或重构，不得因为它们已在 checkpoint 中就继续叠补丁。

### Cluster B — cyclic component/provenance 重复

已知 cells：

- `tricky_b__extruded_002__r0p010`
- `tricky_b__extruded_002__r0p030`
- `mixed__extruded_002__r0p010`

历史根因：同一个 seam provenance 被拆为两个线性 component，pair evaluation 再自由执行整数 shift，使同一左右 Edge 组合被多个 component claim；部分场景是两条 match 只部分重叠，直到逐 record 提交 ledger 才冲突。

已有临时保护：componentized pair 默认不再自由 cyclic shift；相同 effective core 的重复 claim 可去重。最终仍应改为事务式 global provenance allocation，而不是依赖迭代顺序。

### Cluster C — bilateral regular DP/trim failure

已知 cell：

- `tricky__solid_004__r0p030`

证据：同 atom 的 L5/R3 fragments、u 区间重合；最小 endpoint trim 有多个候选，最终 `NO_MONOTONIC_CORRESPONDENCE_PATH`。形成的残段约 `4.59r`，不能提高手尾 handoff 阈值。

这是 regular matching / topology-unique trim canonicalization 问题。应在 DP、paired residues 或 Edge provenance 约束中解决。

### Cluster D — zero-length connector topology

已知 cell：

- `mixed__extruded_002__r0p030`

证据：三条真实零长度 Edge 位于同一 u；它们不能生成正面积 Faces。代码中存在 zero-length proof 的意图，但当前 connector 函数控制流损坏，实际永远返回 `None`；即使恢复控制流，有效 outer degree 仍会受已提交零边影响。

正确方向：把已结构化消费的零边从有效 rail continuation degree 中排除，或生成一个唯一 topology connector proof。只能消费零边本身，不能借此把邻近的大 Edge 一起 setback。

### Cluster E — tricky Solid.004 r0.01 的假绿回退

该定向 cell 曾三次稳定 PASS，但独立审计发现 7 个 `PAIRED_BOUNDARY_RESIDUAL_HANDOFF_V1` 都是大 regular fragment：长度约为 `2r` 上限的 `1.58×–11.57×`。宽松 folded/numeric/direct terminal 例外已经禁用；它们必须恢复 regular 或 unresolved。

另有一个很短 matching fragment 与完整 `REGULAR_TERMINAL_TAIL_HANDOFF_V1` port 重叠。checkpoint 新增 `STRUCTURAL_HANDOFF_COMPONENT_RECONCILIATION_V1`，但审计要求它必须保持严格：单侧、same correspondence/atom/side/source patch、Edge 子集、u containment、唯一 consumer、严格 terminal-tail proof。继续修改时不得让 reconciliation 成为删除 unresolved 的通用通道。

## 7. 推荐的新 Phase C 内部设计

不要继续在 handoff 决策树上增加 case。把 Phase C regular 恢复拆为以下流水线：

```text
真实 staging rail chains
→ 单 Rail canonical circular topology（owner、方向候选、Edge 顺序）
→ Plan atom/forbidden envelope 的 whole-Edge coverage arrangement
→ bilateral component 的 unique circular pairing + closed-strip proposal
→ 全 Boundary universe 的 transactional claim allocation
→ global guard 全通过后一次性提交 ledger/records/ports
```

### 7.1 Canonical rail topology

目标：先对每条 cyclic rail 单独保留完整 circular Edge 顺序，再在 bilateral component 上求相对 rotation；不能在 coverage partition 前把 left/right 强绑成一对 canonical seam。

要求：

- 单 Rail canonicalization 只能使用真实 topology、stable endpoint token、Edge order、owner Rail/Patch 与 Plan FeatureStrand；pair distance 不能决定单 Rail seam；
- rotation/reverse 必须同步更新 coordinates、Edge IDs、endpoint tokens、port/junction/degrees/topology-signature maps 及所有 per-edge maps；rounded coordinate 不能作为唯一映射 key；
- 对 bilateral cyclic component 枚举 `2 directions × relative rotations`，允许左右 Edge 数不同并用 circular monotonic DP 求解；
- 对称环可能有多个 raw rotations。先按完整 circular Edge correspondence 取等价类；只有非等价合法类数量恰为 1 才通过，等价类内用 stable topology token 选序列化代表；
- 没有合法类或非等价合法类多于 1 时，保留结构化 unresolved，不能按 nearest/min-distance 选 seam；
- open rail 继续使用现有单调 u path，不受 cyclic solver 影响。

建议拆成两个边界，替换散落的 lift/phase 补丁，例如：

```text
_canonicalize_single_rail_cycle(chain, strand, owner) -> CanonicalRailCycle | Rejection
_solve_cyclic_pair_for_component(left_cycle, right_cycle, component, radius)
    -> CyclicPairProposal | Rejection
```

现有 `_align_cyclic_stable_chain()` 在全字段守恒合同通过前必须禁用其新调用。`_full_cyclic_regular_pair_candidate()` 不能继续把 cyclic loop 当 open strip：闭环求解序列必须显式追加首点（`u + 1 cycle`）并生成最后 Edge→第一 Edge 的 closure Faces。

### 7.2 Explicit coverage partition

Boundary Edge 是 ledger 最小不可分单元。每个 Plan atom 必须输出三类互斥 whole-Edge claims：

- `BILATERAL_REGULAR_CANDIDATE`
- `STRUCTURAL_SETBACK_CANDIDATE`
- `UNRESOLVED_REGULAR_GAP`

禁止只返回 common intervals 而丢弃单侧差集。跨 atom/forbidden 边界的 Edge 必须携带 crossing witness 并由唯一 claim 消费，不能因 virtual clip 被拆成两个 ledger claims。

Coverage 守恒门：

```text
Boundary Edge universe
== regular_claim_edges ∪ setback_claim_edges ∪ unresolved_claim_edges
且三者 pairwise disjoint
```

新增 diagnostics：

- atom 原始左右 Edge universe；
- canonical seam/rotation；
- bilateral、one-sided、forbidden coverage intervals；
- 未归属 Edge IDs；
- 每个 component 的 left/right provenance。

### 7.3 Unique matching and transactional allocation

事务边界是整个 Phase C Boundary universe，不是单个 component/correspondence。先纯生成全部 `RegularClaim / SetbackClaim / UnresolvedClaim`，不得改 ledger。建立：

```text
edge_id → [(correspondence_id, atom_id, component_id, side, match_id)]
```

规则：

- 完全相同 semantic provenance 和 effective core：确定性合并；
- parent/children 只在 children Edge-disjoint、provenance union 精确等于 parent、Face witness 也精确分割时用 children 替换 parent；否则 conflict/unresolved。禁止仅按 u containment 丢弃 parent/residue；
- 其他重叠：结构化 unresolved / provenance conflict；
- 所有 claims 唯一且 coverage 守恒后，才为全部 regular claims 构建纯 geometry proposals；
- 每条 regular provenance Edge 必须直接反查生成 Face boundary；每个 Face 必须反查唯一 regular consumer，禁止只用全局 `face_count > 0`；
- cyclic proposal 必须验证 closure seam、Edge→Face coverage、width、monotonic、zero-area、orientation 与 self-intersection；
- 所有 global guard 成功后，才在 ledger copy 上一次提交 records/ports；失败时原 ledger/outputs fingerprint 不变；
- terminal extension 当前必须保持禁用，除非 Edge 实际参与新增 Face 并纳入同一事务分配。

### 7.4 Structural handoff stays narrow

Phase C 必须先生成 runtime handoff proof inventory，再冻结 allowlist。只保留有直接结构证据、正负合同和长度/owner 门禁的 handoff：

- overlap forbidden envelope；
- 权威 Plan terminal/junction port；
- zero-length connector；
- 已批准的严格 `SHORT_COMPONENT_SETBACK_V1`；
- 经双向 provenance 证明的 terminal-tail reconciliation。

同一 chain 若同时命中多个不同 proof，不得按 tuple 顺序取第一个，必须以 `AMBIGUOUS_HANDOFF_PROOF` fail-closed。每个 matrix cell 必须输出 proof-version/count/edge-length/radius-ratio；出现 allowlist 外 reason、unexpected count 或 macro setback 立即 FAIL。

最终 allowlist 不能由计划臆定：Step 0 先列出现有 runtime proof、对应正负合同与 14 cells 预期结构，再由 direct structural evidence 批准。`SHORT_COMPONENT_SETBACK_V1` 只能由通用唯一结构条件成立，不能用 fixture/object/Pipe ID 白名单。大 fragment、folded continuation、普通 degree-2 点、单个通用 topology signature 均不足以成为 handoff。

## 8. 分步执行与 Stop/Go

### Gate 0A — 工作树、代码 baseline 与 source integrity

目标入口：只读 source/runner；不运行产品 Operator。

用户操作：无。

预期可见变化：无产品几何变化；只建立可信执行基线。

自动证据：

1. 读取项目 `AGENTS.md`、本文、上游 handoff、`tests/TESTING_POLICY.md` 和 `tests/README.md`。
2. `git status --short`、`git merge-base --is-ancestor 1b8f120 HEAD`；确认当前 HEAD 可包含计划文档提交，但 `1b8f120..HEAD` 的 runtime/test blobs 未被意外修改。检查所有用户修改，不得 reset 或覆盖。
3. 修复并直接测试 `_zero_length_regular_connector_handoff_proof()` 的控制流归属；加入 valid/rejection contract，证明返回值来自本函数且 `_regular_overlap_bridge_handoff_proof()` 后无不可达残段。
4. 用可写 pycache 运行 §9 的 `py_compile`；同时保留源级结构/直接行为测试，不能把语法通过当控制流证据。
5. 生成 runtime handoff proof inventory，记录每条 proof path 的函数、正负合同、matrix 预期 count/length/radius-ratio；未批准路径先 fail-closed。

Go：代码 baseline 可追溯；connector 直接合同正负通过；无已知不可达 proof 逻辑；inventory 完整。

Stop：runtime/test blob 与预期 baseline 不一致、connector 控制流仍损坏、出现未解释的用户改动。

### Gate 0B — Evidence runner hardening

目标入口：`tools/run_blender_tests.py` 与 batched matrix runner。

用户操作：无；Agent 运行 headless Blender。

预期可见变化：无产品几何变化；每次 run 产生独立、可绑定代码版本的 artifacts。

自动证据：

- `phase_c_go` 必须直接要求：14 case 全 `PASS/stable`；42 repetition 全 `status=PASS` 且 `phase_a/b/c_pass=true`；Preview contract、source unchanged、Adapter result、无 debug 残留全部通过。
- 直接断言 `missing/extra/duplicate partition == 0`，以及 forward/reverse boundary-universe、rail-chain、geometry、ledger、port fingerprints 分别相等；不能只信 backend 写入的布尔值。
- runner 加负向合同：以上任一字段失败时 `phase_c_go=false` 且 host exit non-zero；unknown `--case`、0 executed cases、requested/executed set 不一致必须失败；通用 test runner 使用 `--python-exit-code 1`。
- 每次 gate 使用不存在的独立 `--artifact-dir`；summary 写 `run_id`、started/finished UTC、git HEAD + dirty diff fingerprint、argv、requested/executed cases、Blender executable/version、fixture/code hashes、artifact manifest/sha256。summary 用 temp + atomic replace。
- `phase_c_setback_closeup.png` 仅在 `setback_port_count > 0` 时 required；无 port 记为 `N/A`。所有 required artifacts 必须携带相同 run-id 且新鲜。

Go：runner 正负合同通过；失败不能汇总成 GO；新 run manifest 可唯一复现。

Stop：仍可 fake green、partial run 覆盖 full gate、unknown case 静默通过或 artifact 不能绑定 source revision。

### Gate 0C — 新鲜失败基线

目标 Operator：正式 `hst.feature_chamfer_gn(PREVIEW)` → hidden experimental Adapter。

用户操作：对 `simple__extruded_002__r0p010` 执行 Preview 后 Phase C probe。

预期可见变化：只生成 diagnostics/debug artifact，不生成产品 output。

自动证据：在唯一 run 目录重跑 6 个 narrow handoff guards、已存在的 cyclic span/stitch/reverse/closure/atom-clip contracts，再定向运行该 cell 一次。

Go：Phase A/B、fixture hash、Operator/Preview contract 全通过，且诚实复现结构化 Phase C 失败；artifact manifest 新鲜。

Stop：环境、fixture、Operator、runner 或 Phase A/B 回归；只修基线，不进入 solver。

### Step 1 — 合同先行并隔离未证明 cyclic WIP

目标 Operator：hidden experimental Adapter 的纯 helper/runtime seam。

用户操作：无 UI 操作。

预期可见变化：无产品输出；新增机器可读 Algorithm contracts。

自动证据：为 full-field rotation/reverse 守恒、对称 rotation 等价类、cyclic closure Face coverage、whole-Edge coverage conservation、claim conflict/rollback 编写正负合同。审计四个 full-cyclic 实验函数和 `_align_cyclic_stable_chain()` 新调用；证明前先禁用。

Go：正负合同已落地；旧 WIP 已隔离；旧实现对预期失败合同诚实失败，新的最小纯 canonical/claim proposal 对 rotation 等价类、全字段守恒和 rollback 合同通过。完整 closure Edge→Face coverage 留到 Step 3。

Stop：依靠 nearest/min-distance 猜 seam、rotation 丢 provenance、open-strip 假装 cyclic closure，或合同只能验证 fingerprint 不验证语义。

### Step 2 — Single-rail topology 与 coverage conservation

目标 Operator：hidden experimental Adapter。

用户操作：定向运行 simple cells 的 Phase C probe。

预期可见变化：diagnostics 能显示完整 circular rail 和三类互斥 claims，尚不要求生成 strip。

自动证据：每个 atom 的 input Edge universe、canonical order、bilateral/setback/unresolved claims、crossing witnesses 与守恒计数。

Go：每条输入 Edge 恰属一个 claim，无未归属、重复、common-only 丢失；forward/reverse fingerprint 一致。

Stop：coverage 依赖整个 Edge 的最大 u-overlap猜 owner、单侧差集消失或 virtual clip 重复 claim。

### Step 3 — Cyclic pair solver：先攻 simple 4 cells

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：对下列 4 cells 运行 Phase C probe。

预期可见变化：完整 cyclic regular rail 生成闭合 debug chamfer strips，不生成产品 output。

自动证据：每格的 coverage、candidate equivalence classes、closure Edge→Face witness、ledger/geometry guards 与独立 artifacts。

顺序：

1. `simple__extruded_002__r0p010`
2. `simple__extruded_002__r0p030`
3. `simple__solid_44__r0p010`
4. `simple__solid_44__r0p030`

这四格无复杂 multi-Pipe junction，是 cyclic regular solver 的最小产品基线。

每格要求：

- `unresolved_remote_component_count == 0`
- `deferred_attempt_count == 0`
- `all_ledger_edges_consumed_once == true`
- missing/extra/duplicate/consumer mismatch 全为 0
- strip zero-area/orientation/self-intersection 全为 0
- 正序/逆序 geometry、ledger、port fingerprint 一致
- 未使用大 fragment handoff

四格每格先 1 次，全部通过后再 3 次。

Go：simple `4/4 × 3` 新鲜 PASS，cyclic closure Edge→Face coverage 100%，claim conflict=0，allowlist 外 handoff=0。

Stop：任一格只有局部 strip、macro setback、non-equivalent rotation ambiguity 或依赖 order；留在本 Step 修复。

### Step 4 — 全局 transactional allocation

目标 Operator：hidden experimental Adapter。

用户操作：重跑 simple 4 cells。

预期可见变化：成功几何不变；失败不留下部分 ledger/records/ports。

自动证据：全 universe claim graph、semantic quotient、conflict/partition 计数、pre/post ledger fingerprint、Edge↔Face 双向 provenance。

Go：所有 claims/geometry proposals 先全局验证，随后一次提交；注入任一跨 correspondence conflict/geometry failure 均完整 rollback；simple `4/4 × 3` 保持绿。

Stop：仍在 `_build_regular_record_from_match()` 或 handoff helper 内逐 claim 修改正式 ledger，或失败依赖迭代顺序。

### Step 5 — 验证同根 cluster

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：对下列 4 cells 运行 Phase C probe。

预期可见变化：同根 cyclic cases 生成完整 debug strips；同侧缺对侧保持结构化 unresolved。

自动证据：与 Step 3 相同，并额外核对 common-only macro remainder 和 one-sided claims。

运行：

- `tricky__solid_016__r0p010`
- `tricky__solid_016__r0p030`
- `tricky_b__extruded_003__r0p010`
- `tricky_b__extruded_003__r0p030`

预期：simple solver 应消除 common-only macro remainder。若出现同侧重复/缺对侧，应由 explicit coverage diagnostics 暴露，不能进入 handoff。

Go：4 cells 各 1 次后各 3 次稳定通过；common-only macro remainder=0，coverage 守恒。

Stop：出现单侧大差集、allowlist 外 handoff 或 coverage/transaction 回归。

### Step 6 — 修 cyclic provenance allocation

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：对下列 3 cells 运行 Phase C probe。

预期可见变化：重复 provenance 由全局 allocation 唯一分配，不改变用户 source。

自动证据：claim graph、semantic quotient、coverage/Face witness 与 transaction fingerprints。

运行：

- `tricky_b__extruded_002__r0p010`
- `tricky_b__extruded_002__r0p030`
- `mixed__extruded_002__r0p010`

实现全局 match claims 与事务式 Edge allocation；任何重复 provenance 在 geometry/ledger commit 前处理。

Go：不再出现 `REGULAR_MATCH_PROVENANCE_CONFLICT` 或 `REGULAR_CORE_LEDGER_CONFLICT`；claim graph conflict=0、coverage/Face witness 守恒，且没有通过丢弃重复 Edge 达成绿灯。

Stop：按 component 迭代顺序解决冲突、只按 u containment 去重或静默丢 parent/residue。

### Step 7 — 修 bilateral DP/trim

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：运行 `tricky__solid_004__r0p030` Phase C probe。

预期可见变化：L5/R3 bilateral component 生成真实 debug strip，不进入 handoff。

自动证据：唯一 circular/open DP path、trim/residue provenance、Face witness 与原 geometry thresholds。

运行 `tricky__solid_004__r0p030`。针对同 atom L5/R3 的唯一 topology correspondence修复 DP/trim/residue；保留 width、relative advance、monotonic、zero-area 阈值不变。

Go：大 fragment 进入带 Edge↔Face witness 的真实 strip Faces；不是提高 tail/setback 阈值。

Stop：任何大 fragment 进入 setback/ignore，或 geometry guard 被放宽。

### Step 8 — 修 zero-length connector

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：运行 `mixed__extruded_002__r0p030` Phase C probe。

预期可见变化：零边由 connector port 消费、邻近 regular strip 保持完整，不生成零面积 Face。

自动证据：connector 直接正负合同、effective-degree diagnostics、ledger/Face witness 与独立 artifacts。

运行 `mixed__extruded_002__r0p030`。先以 Gate 0A 的直接合同确认 connector 函数控制流已修复。zero-length Edge 必须由唯一 connector proof 消费；有效 outer degree 只排除同一已验证 connector claim 内的零边，不能泛化过滤所有短边。

Go：零边不生成 Face，邻近正常 Edge 仍由 regular 消费，ledger exactly-once；valid/rejection connector 合同和 cell 各 3 次通过。

Stop：connector 始终返回 `None`、把邻近正常 Edge 一并 setback，或全局忽略短边。

### Step 9 — 回到 tricky r0.01 做假绿审计

目标 Operator：正式 PREVIEW → hidden experimental Adapter。

用户操作：运行 `tricky__solid_004__r0p010` 三次。

预期可见变化：旧 macro residual 变成真实 debug strips；仅结构严格的小 port 保留 setback。

自动证据：proof inventory/count/length ratio、Edge↔Face witness、transaction 与 3 repetitions fingerprints。

运行 `tricky__solid_004__r0p010` 三次。重点检查：

- 旧 7 个 paired residual 大 Edge 已成为 regular 或明确 unresolved；
- 只有 handoff 已批准的 pipe0 `0:5` 短 component 可走严格 `SHORT_COMPONENT_SETBACK_V1`；
- pipe2 裁剪残段只有在唯一完整 terminal-tail port 的双向 proof 下可 reconciliation；
- 无 folded/numeric/direct terminal 大 Edge例外；
- no terminal extension Edge 被 regular consumer 吃掉但没生成 Face。

Go：3 次稳定通过；所有旧 macro residual 进入有 Face witness 的 regular strip，或由冻结 allowlist 中的严格结构 proof 消费；handoff inventory 与批准 allowlist/count 完全一致，unresolved=0。

Stop：任一大 Edge 仅因 first-match proof、folded/numeric/direct terminal 例外或 reconciliation 泛化而被消费。

### Step 10 — 完整 Phase C gate

目标 Operator：正式 PREVIEW → hidden experimental Adapter；不是正式 FINALIZE。

用户操作：Agent 对 14 cells 运行 headless matrix，无需用户点击 UI。

预期可见变化：每格留下 commit-bound debug artifacts，不生成产品 output。

自动证据：42 repetitions summary、直接 JSON assertions、artifact manifest/sha256、handoff inventory 与全部 Algorithm/Backend guards。

先运行 §9 的 `py_compile`、完整 headless regression 和“完整 Phase C”命令；不得省略显式 Blender 路径或独立 `--artifact-dir`。

必须是独立 run 目录中的 `14/14 cells × 3 PASS`，并由 §9 的独立 JSON 断言复核：完整 scope、42 repetitions、Phase A/B/C、每级 status、所有直接计数/fingerprint、artifact manifest 与 source revision 全部一致。每个 regular Edge↔Face 双向 witness 完整；handoff reason 全在冻结 allowlist 且 count/length/radius-ratio 符合预期；unexpected/macro setback=0。

Go：上述机器门禁全部通过；只将 Phase C internal gate 标为 GO，全局状态仍为 `PROTOTYPE`。

Stop：任何 partial/stale/mismatched artifact、runner 自证布尔、unexpected proof、缺失 Face witness 或 Phase A/B/Operator 回归。

### Step 11 — 独立 Spec Audit

目标 Operator：审计正式 PREVIEW→实验 Adapter runtime diff；明确正式 FINALIZE 未集成。

用户操作：无。

预期可见变化：只更新阶段文档状态，不改变 runtime。

自动证据：未参与实现的只读 reviewer 报告、diff、fresh matrix manifest 与逐门禁证据索引。

由未参与实现的只读 reviewer 核对：

- diff 是否严格落在 change budget：Phase C backend、hidden Adapter（仅必要时）、tests/runner 与 docs；正式 Operator/UI/FINALIZE 不得修改；
- 每个失败 cluster 是否由 regular 或严格 connector 解决；
- 是否新增宽松 handoff、ignore、模型特判或阈值放宽；
- ledger consumer 双向引用、Face provenance 和 exactly-once；
- full matrix 是否新鲜、稳定、source-bound，且明确从正式 PREVIEW→实验 Adapter 进入；
- 文档阶段状态是否与代码一致。

存在 P0/P1 或高严重度语义偏差：Phase C 保持 STOP 并修复。  
无高严重度问题且全部 gate 通过：更新本文和上游 handoff 为 `PHASE C GO / global PROTOTYPE`，然后才能为 Phase D 写新计划。Phase D 完成后，Phase E 才能单独接入正式 FINALIZE，并验证 preflight、modifier hide/restore、failure rollback、source unchanged、output naming/attribute、PATCHED state、selection 与正式 Operator matrix；Phase C 通过不能跳过这些合同。

## 9. 测试命令

所有 gate 先创建唯一 `<run-id>`，下列目录必须不存在；不得复用顶层 canonical results。Blender 环境固定为本机 `/Applications/Blender.app/Contents/MacOS/Blender`（当前实测 5.1.2）。

语法与 source integrity：

```bash
PYTHONPYCACHEPREFIX=/tmp/hst-feature-chamfer-pycache \
python3 -m py_compile \
  utils/feature_chamfer_batched_finalize_utils.py \
  tests/blender_test_driver.py \
  tests/feature_chamfer_batched_matrix_driver.py \
  tools/run_blender_tests.py \
  tools/run_feature_chamfer_batched_matrix.py
```

完整 headless regression（Gate 0 通过后使用独立目录）：

```bash
python3 tools/run_blender_tests.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/full-regression
```

定向合同：

```bash
python3 tools/run_blender_tests.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/contracts \
  --case feature_chamfer_batched_short_component_setback_contract \
  --case feature_chamfer_batched_plan_span_crossing_handoff_contract \
  --case feature_chamfer_batched_structural_handoff_reconciliation_contract \
  --case feature_chamfer_batched_regular_numeric_fragment_handoff_contract \
  --case feature_chamfer_batched_regular_terminal_extension_contract \
  --case feature_chamfer_batched_cyclic_seam_boundary_handoff_contract
```

单格：

```bash
python3 tools/run_feature_chamfer_batched_matrix.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --artifact-dir tests/artifacts/runs/<run-id>/simple-r0p010 \
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

完整 gate 后必须对 `tests/artifacts/runs/<run-id>/phase-c/results.json` 做独立 `jq -e` 复核，至少断言：

```jq
.status == "finished" and .phase == "C" and
.run_scope == "PHASE_GATE_FULL" and .gate_eligible == true and
.blender_version == "5.1.2" and .requested_repetitions == 3 and
.case_count == 14 and .passed_case_count == 14 and .failed_case_count == 0 and
.phase_a_go == true and .phase_b_go == true and .phase_c_go == true and
([.cases[].repetitions[]] | length) == 42 and
all(.cases[];
  .status == "PASS" and .stable == true and
  (.repetitions | length) == 3 and
  all(.repetitions[];
    .status == "PASS" and .phase_a_pass == true and
    .phase_b_pass == true and .phase_c_pass == true and
    .source_unchanged == true and
    .preview_contract_matches_owned_curve == true))
```

runner hardening 完成后，复核还必须包含 manifest/source revision、required artifact sha256、direct partition counts、五组 forward/reverse fingerprints、Edge↔Face witness、handoff allowlist/count/length ratio，不能停留在上面这组最小字段。

注意：macOS Blender 5.1.2 偶发在 Metal backend 初始化时崩溃，backtrace 位于 `supports_barycentric_whitelist`。如果崩溃发生在加载 fixture 前，立即以相同命令重试一次，并把它与算法失败区分；不得把算法阶段异常当成环境崩溃忽略。

## 10. 置信度与升级条件

本文评估的对象是“计划能否可靠把 Phase C 推到 internal GO”，不是当前实现成功率。

| 时点 | 置信度 | 依据与剩余缺口 |
|---|---:|---|
| 原计划 | 约 `0.58` | 方向正确，但 runner 可 fake green、artifact 未绑定 commit、cyclic closure/transaction 合同不完整、connector 控制流损坏 |
| 本次优化后（尚未执行 Gate 0） | 程序性约 `0.90` / 算法完成约 `0.62` | 入口、证据、算法边界与 Stop/Go 已明确；solver 尚未以动态证据证明 |
| Gate 0A/B/C 全通过 | 目标 `≥0.88` | source/runner/失败基线可信 |
| simple `4/4 × 3` + transaction contracts | 目标 `≥0.92` | cyclic 主路径已跨越最小产品基线 |
| 新鲜 `14/14 × 3` + independent audit | 目标 `≥0.96` | 仅可把 Phase C internal gate 标为 GO；全局仍为 `PROTOTYPE` |

程序性置信度表示计划能否防止越阶段与 fake green；算法完成置信度表示当前设计最终覆盖 14 cells 的工程判断。后者不能因文档更完整而自动提高。任一 P0/P1、unexpected handoff、stale/partial artifact 或正式入口混淆都会把程序性置信度降回 `<0.80` 并保持 Phase C STOP。数值是基于已核对代码/runner/历史 artifacts 的工程判断，不是统计成功概率。

## 11. 实现纪律

- 修改前先定位调用链：正式 PREVIEW → owned Curve/immutable Pipe contract → hidden Adapter → `build_batched_feature_chamfer()` → shared Even-Thickness builder/independent staging → `_build_cyclic_regular_strip_partition()` → pair/build/ledger diagnostics。
- 函数按项目规范添加中文块注释；imports 保持文件头部。
- 让失败结构化暴露，不 catch/silent fallback。
- 每次只处理一个 cluster；先定向 1 次，再重复 3 次，再扩大矩阵。
- 任一 Step 的 Go 未证明时只允许继续当前 Step 的诊断、设计、测试与修复，禁止实现或接入后续 Step runtime path。
- Step 5–9 每个 cluster 先 1 次诊断，再本 cluster 3 次，并重跑 simple canary；canary 回归则退回最近通过的 Step。
- 不因单格绿灯更新 Phase C GO。
- 测试产物大，不默认提交 artifacts；只有项目已有惯例或 handoff 明确要求时提交。
- 未经用户允许不开分支。本计划不授权 commit；仅在用户另行授权后，稳定 checkpoint 才可提交且 message 必须表明 WIP 或实际解决的 cluster。
- 不提交 `tests/.DS_Store`。
- 长程任务真正完成、失败或需要用户注意时，按 `task-completion-notifier` 发送一次对应通知；中间进度不发送。

## 12. Suggested Skills

- `blender-cli`：运行 Blender background probes、保存和检查 `.blend`/JSON/PNG artifacts。
- 项目内 `agent-skills/hst-blender-regression/SKILL.md`：产品矩阵与完整 headless 回归。
- `diagnosing-bugs`：按 cluster 读取窄化 diagnostics，不通读大日志。
- `tdd`：先为 cyclic rotation/provenance allocation 写合同，再实现。
- `code-review`：Phase C GO 前独立 Spec Audit。
- `verification-before-completion`：核对新鲜 artifacts、矩阵和阶段状态。
- `task-completion-notifier`：仅最终 completed/attention/failed 时使用。

如果上列某个通用 skill 在新 Session 不可用，使用项目内回归 skill 和等价的只读诊断/验证流程继续，不因此停止。

## 13. 新 Session 启动 Prompt

```text
继续 HardsurfaceGameAssetToolkit Feature Chamfer batched Phase C Regular Recovery。

先读取并严格遵守：
1. 项目 AGENTS.md
2. docs/plan/2026-07-24-feature-chamfer-phase-c-regular-recovery-plan.md
3. docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md
4. tests/TESTING_POLICY.md 与 tests/README.md

当前文档 HEAD 是 92d2953，代码 baseline 是 1b8f120；先记录实际 HEAD/工作树并验证 runtime/test blobs，而不是要求 HEAD 恰等于 baseline。当前状态 PAUSED / PROTOTYPE / Phase A GO / Phase B GO / Phase C STOP。Phase C GO 前禁止进入 D/E，禁止接入正式 hst.feature_chamfer_gn(FINALIZE)。保留 tests/.DS_Store，不修改、不提交；不修改 auto_load.py，不开新分支。

先完成 Gate 0A/B/C：修复 zero-length connector 的不可达控制流，hardening evidence runner，冻结 handoff proof inventory，并保存 commit-bound 的新鲜失败基线。然后用合同先行建立 single-rail circular topology、whole-Edge coverage、closed cyclic solver 和全 universe transactional allocation。先让 simple 4 cells 全部真实通过，再按 cluster 扩大验证，最后跑新鲜 14×3 和独立 Spec Audit。

禁止 SDF、nearest-owner、global fill、centroid fan、无约束 triangulate、共享 Mesh 顺序累计 Cut、模型特判、忽略大 fragment 或放宽 geometry guard。除非真正需要用户作实质决定，否则持续自主推进。
```
