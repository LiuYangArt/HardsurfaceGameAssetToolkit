# Feature Chamfer Phase C — Regular Recovery 续作计划

日期：2026-07-24  
状态：`PAUSED / PROTOTYPE / PHASE A GO / PHASE B GO / PHASE C STOP`  
代码 checkpoint：`1b8f120` (`wip(feature-chamfer): checkpoint phase c regular diagnostics`)  
上游权威 handoff：`docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md`

本文是下一次 Session 的执行入口。它只重排 Phase C 当前剩余工作，不替代上游 handoff 的产品语义、禁止路线、Phase A→E Stop/Go 或验收标准。发生冲突时以上游 handoff 与项目 `AGENTS.md` 为准。

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

### 3.1 已确认通过

- Phase A：正式 Preview Pipe 输入合同为 GO。
- Phase B：Pipe overlap graph、stable coloring、batch 内无 overlap、正序/逆序 independent Exact Boolean staging 为 GO。
- Source 保持不变；Boundary provenance、consumer 双向引用、outside-plan 分类、geometry guard 和 artifact 保存路径已经建立。
- checkpoint `1b8f120` 后运行的以下定向合同测试通过：
  - `feature_chamfer_batched_short_component_setback_contract`
  - `feature_chamfer_batched_plan_span_crossing_handoff_contract`
  - `feature_chamfer_batched_structural_handoff_reconciliation_contract`
  - `feature_chamfer_batched_regular_numeric_fragment_handoff_contract`
  - `feature_chamfer_batched_regular_terminal_extension_contract`
  - `feature_chamfer_batched_cyclic_seam_boundary_handoff_contract`
- `python3 -m py_compile utils/feature_chamfer_batched_finalize_utils.py tests/blender_test_driver.py` 通过。

### 3.2 不可当作当前 GO 证据

- 2026-07-23 曾有一次 `14/14 × 3` 自动绿，但已因 fake green 被正式撤销。
- 最近一次完整严格矩阵曾得到 `2 PASS / 12 FAIL`；它用于说明失败分布，不代表 checkpoint 后当前代码的最终数字。
- 顶层 `tests/artifacts/feature_chamfer_batched_matrix/results.json` 会被每次定向 run 覆盖。本文编写时它只包含 `simple__extruded_002__r0p010` 的单格失败，不得误读为完整矩阵。
- 各 cell 的历史诊断仍在 `tests/artifacts/feature_chamfer_batched_matrix/<case>/diagnostics.json`；使用前必须核对 `mtime`、运行参数和当前 commit。
- checkpoint 中包含尚未证明正确的 full-cyclic 实验代码。它是 WIP，不是完成方案。

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

证据：三条真实零长度 Edge 位于同一 u；它们不能生成正面积 Faces。已存在 zero-length proof，但有效 outer degree 被已提交的零边影响，short terminal proof 因此拒绝。

正确方向：把已结构化消费的零边从有效 rail continuation degree 中排除，或生成一个唯一 topology connector proof。只能消费零边本身，不能借此把邻近的大 Edge 一起 setback。

### Cluster E — tricky Solid.004 r0.01 的假绿回退

该定向 cell 曾三次稳定 PASS，但独立审计发现 7 个 `PAIRED_BOUNDARY_RESIDUAL_HANDOFF_V1` 都是大 regular fragment：长度约为 `2r` 上限的 `1.58×–11.57×`。宽松 folded/numeric/direct terminal 例外已经禁用；它们必须恢复 regular 或 unresolved。

另有一个很短 matching fragment 与完整 `REGULAR_TERMINAL_TAIL_HANDOFF_V1` port 重叠。checkpoint 新增 `STRUCTURAL_HANDOFF_COMPONENT_RECONCILIATION_V1`，但审计要求它必须保持严格：单侧、same correspondence/atom/side/source patch、Edge 子集、u containment、唯一 consumer、严格 terminal-tail proof。继续修改时不得让 reconciliation 成为删除 unresolved 的通用通道。

## 7. 推荐的新 Phase C 内部设计

不要继续在 handoff 决策树上增加 case。把 Phase C regular 恢复拆为四个明确步骤：

```text
真实 staging rail chains
→ canonical rail topology（方向、cyclic seam、source Patch）
→ Plan atom 内显式 coverage partition
→ unique regular pairing + transactional provenance allocation
→ geometry guard 全通过后一次性提交 ledger/Faces
```

### 7.1 Canonical rail topology

目标：对 cyclic rail 保留完整的 circular Edge 顺序，而不是先切成容易丢失两端的线性 common interval。

要求：

- 方向与 seam 只能由真实 topology、Plan FeatureStrand 和两侧 rail correspondence 决定；
- 对 cyclic pair 枚举有限的方向/rotation 候选，使用全环 width/monotonic/Edge-order hard guard 选择唯一合法候选；
- 如果没有唯一合法候选，保留结构化 unresolved，不能按最近距离选择；
- rotation 必须同步更新 coordinates、Edge IDs、endpoint tokens 及所有 per-edge maps；
- open rail 继续使用现有单调 u path，不受 cyclic solver 影响。

建议实现一个深函数，替换散落的 lift/phase 补丁，例如：

```text
_canonicalize_regular_rail_pair(
    left_chain,
    right_chain,
    strand,
    atom,
    radius,
) -> CanonicalRailPair | Rejection
```

### 7.2 Explicit coverage partition

每个 Plan atom 必须输出三类互斥 coverage：

- `BILATERAL_REGULAR_CANDIDATE`
- `STRUCTURAL_SETBACK_CANDIDATE`
- `UNRESOLVED_REGULAR_GAP`

禁止只返回 common intervals 而丢弃单侧差集。对每条原始 Boundary Edge，必须能反查它进入了哪一个 coverage component。

新增 diagnostics：

- atom 原始左右 Edge universe；
- canonical seam/rotation；
- bilateral、one-sided、forbidden coverage intervals；
- 未归属 Edge IDs；
- 每个 component 的 left/right provenance。

### 7.3 Unique matching and transactional allocation

先生成全部 match claims，不立即改 ledger。建立：

```text
edge_id → [(correspondence_id, atom_id, component_id, side, match_id)]
```

规则：

- 完全相同左右 provenance 和 effective core：确定性合并；
- parent/residue 严格包含：保留唯一不重叠 partition；
- 其他重叠：结构化 unresolved / provenance conflict；
- 所有 claims 唯一后，才调用 geometry builder；
- 所有 geometry guard 成功后，才一次性提交 ledger 和 Faces；
- terminal extension 当前必须保持禁用，除非 Edge 实际参与新增 Face 并纳入同一事务分配。

### 7.4 Structural handoff stays narrow

只保留有直接结构证据的 handoff：

- overlap forbidden envelope；
- 权威 Plan terminal/junction port；
- zero-length connector；
- 已批准的严格 `SHORT_COMPONENT_SETBACK_V1`；
- 经双向 provenance 证明的 terminal-tail reconciliation。

大 fragment、folded continuation、普通 degree-2 点、单个通用 topology signature 均不足以成为 handoff。

## 8. 分步执行与 Stop/Go

### Step 0 — 恢复与基线冻结

操作：

1. 读取项目 `AGENTS.md`、本文、上游 handoff、`tests/TESTING_POLICY.md` 和 `tests/README.md`。
2. `git status --short`，确认 checkpoint 为 `1b8f120`，只保留 `tests/.DS_Store` 未提交。
3. 检查 checkpoint 后是否有用户修改；不得 reset 或覆盖。
4. 重跑 `py_compile` 和本文第 3.1 节 6 个合同测试。
5. 定向运行 `simple__extruded_002__r0p010` 一次，保存新鲜 baseline。

Go：能稳定复现诚实失败，artifact freshness 正确。  
Stop：环境、fixture、Operator 合同或 Phase A/B 回归。

### Step 1 — 删除/隔离未证明的 full-cyclic 补丁

先审计 checkpoint 中四个 full-cyclic 实验函数和 `_align_cyclic_stable_chain()` 新调用。用最小合成测试证明 rotation 后 Edge/coordinate/token/per-edge maps 保持一致。

若不能证明，先移除这些实验分支，恢复到清晰的失败基线；不要在未知 WIP 上继续增加条件。

Go：cyclic canonicalization 有独立合同测试，input order 反转后 fingerprint 稳定。  
Stop：依靠宽度最近值猜 seam，或 rotation 丢失 provenance。

### Step 2 — 先攻 simple 4 cells

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

### Step 3 — 验证同根 cluster

运行：

- `tricky__solid_016__r0p010`
- `tricky__solid_016__r0p030`
- `tricky_b__extruded_003__r0p010`
- `tricky_b__extruded_003__r0p030`

预期：simple solver 应消除 common-only macro remainder。若出现同侧重复/缺对侧，应由 explicit coverage diagnostics 暴露，不能进入 handoff。

### Step 4 — 修 cyclic provenance allocation

运行：

- `tricky_b__extruded_002__r0p010`
- `tricky_b__extruded_002__r0p030`
- `mixed__extruded_002__r0p010`

实现全局 match claims 与事务式 Edge allocation；任何重复 provenance 在 geometry/ledger commit 前处理。

Go：不再出现 `REGULAR_MATCH_PROVENANCE_CONFLICT` 或 `REGULAR_CORE_LEDGER_CONFLICT`，且没有通过丢弃重复 Edge 达成绿灯。

### Step 5 — 修 bilateral DP/trim

运行 `tricky__solid_004__r0p030`。针对同 atom L5/R3 的唯一 topology correspondence修复 DP/trim/residue；保留 width、relative advance、monotonic、zero-area 阈值不变。

Go：大 fragment 进入真实 strip Faces；不是提高 tail/setback 阈值。

### Step 6 — 修 zero-length connector

运行 `mixed__extruded_002__r0p030`。zero-length Edge 必须由唯一 connector proof 消费；有效 outer degree 只计算尚未被同 connector proof 消费的 rail continuation。

Go：零边不生成 Face，邻近正常 Edge 仍由 regular 消费，ledger exactly-once。

### Step 7 — 回到 tricky r0.01 做假绿审计

运行 `tricky__solid_004__r0p010` 三次。重点检查：

- 旧 7 个 paired residual 大 Edge 已成为 regular 或明确 unresolved；
- 只有 handoff 已批准的 pipe0 `0:5` 短 component 可走严格 `SHORT_COMPONENT_SETBACK_V1`；
- pipe2 裁剪残段只有在唯一完整 terminal-tail port 的双向 proof 下可 reconciliation；
- 无 folded/numeric/direct terminal 大 Edge例外；
- no terminal extension Edge 被 regular consumer 吃掉但没生成 Face。

### Step 8 — 完整 Phase C gate

先运行完整合同/回归，再运行：

```bash
python3 tools/run_feature_chamfer_batched_matrix.py \
  --stage PHASE_C_REGULAR_CORE \
  --repetitions 3
```

必须是 14/14 cells × 3 PASS，并核对不是旧 artifact。

### Step 9 — 独立 Spec Audit

由未参与实现的只读 reviewer 核对：

- diff 是否仍只在实验 Phase C backend/runtime path；
- 每个失败 cluster 是否由 regular 或严格 connector 解决；
- 是否新增宽松 handoff、ignore、模型特判或阈值放宽；
- ledger consumer 双向引用、Face provenance 和 exactly-once；
- full matrix 是否新鲜、稳定、从实验目标 Operator 进入；
- 文档阶段状态是否与代码一致。

存在 P0/P1 或高严重度语义偏差：Phase C 保持 STOP 并修复。  
无高严重度问题且全部 gate 通过：更新本文和上游 handoff为 `PHASE C GO`，然后才能为 Phase D 写新计划。

## 9. 测试命令

定向合同：

```bash
python3 tools/run_blender_tests.py \
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
  --stage PHASE_C_REGULAR_CORE \
  --repetitions 1 \
  --case simple__extruded_002__r0p010
```

完整 Phase C：

```bash
python3 tools/run_feature_chamfer_batched_matrix.py \
  --stage PHASE_C_REGULAR_CORE \
  --repetitions 3
```

注意：macOS Blender 5.1.2 偶发在 Metal backend 初始化时崩溃，backtrace 位于 `supports_barycentric_whitelist`。如果崩溃发生在加载 fixture 前，立即以相同命令重试一次，并把它与算法失败区分；不得把算法阶段异常当成环境崩溃忽略。

## 10. 实现纪律

- 修改前先定位调用链：隐藏实验 Adapter → `build_batched_feature_chamfer()` → `_build_cyclic_regular_strip_partition()` → regular pair/build/ledger commit。
- 函数按项目规范添加中文块注释；imports 保持文件头部。
- 让失败结构化暴露，不 catch/silent fallback。
- 每次只处理一个 cluster；先定向 1 次，再重复 3 次，再扩大矩阵。
- 不因单格绿灯更新 Phase C GO。
- 测试产物大，不默认提交 artifacts；只有项目已有惯例或 handoff 明确要求时提交。
- 每个稳定 checkpoint 可以提交，但 commit message 必须表明 WIP 或实际解决的 cluster。
- 不提交 `tests/.DS_Store`。
- 长程任务真正完成、失败或需要用户注意时，按 `task-completion-notifier` 发送一次对应通知；中间进度不发送。

## 11. Suggested Skills

- `blender-cli`：运行 Blender background probes、保存和检查 `.blend`/JSON/PNG artifacts。
- 项目内 `agent-skills/hst-blender-regression/SKILL.md`：产品矩阵与完整 headless 回归。
- `diagnosing-bugs`：按 cluster 读取窄化 diagnostics，不通读大日志。
- `tdd`：先为 cyclic rotation/provenance allocation 写合同，再实现。
- `code-review`：Phase C GO 前独立 Spec Audit。
- `verification-before-completion`：核对新鲜 artifacts、矩阵和阶段状态。
- `task-completion-notifier`：仅最终 completed/attention/failed 时使用。

如果上列某个通用 skill 在新 Session 不可用，使用项目内回归 skill 和等价的只读诊断/验证流程继续，不因此停止。

## 12. 新 Session 启动 Prompt

```text
继续 HardsurfaceGameAssetToolkit Feature Chamfer batched Phase C Regular Recovery。

先读取并严格遵守：
1. 项目 AGENTS.md
2. docs/plan/2026-07-24-feature-chamfer-phase-c-regular-recovery-plan.md
3. docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md
4. tests/TESTING_POLICY.md 与 tests/README.md

Git checkpoint 是 1b8f120。当前状态 PAUSED / PROTOTYPE / Phase A GO / Phase B GO / Phase C STOP。Phase C GO 前禁止进入 D/E，禁止接入正式 hst.feature_chamfer_gn(FINALIZE)。保留 tests/.DS_Store，不修改、不提交；不修改 auto_load.py，不开新分支。

先按新计划 Step 0 恢复基线，再审计 checkpoint 中尚未证明的 full-cyclic WIP。下一目标不是给 handoff 增加例外，而是建立 canonical cyclic rail topology、explicit coverage partition 和 transactional provenance allocation。先让 simple 4 cells 全部真实通过，再按 cluster 扩大验证，最后跑新鲜 14×3 和独立 Spec Audit。

禁止 SDF、nearest-owner、global fill、centroid fan、无约束 triangulate、共享 Mesh 顺序累计 Cut、模型特判、忽略大 fragment 或放宽 geometry guard。除非真正需要用户作实质决定，否则持续自主推进。
```

