# Feature Chamfer Phase C — Ownership-driven Bridge / Local Fill 续作计划

日期：2026-07-24  
状态：`PAUSED / PROTOTYPE / PHASE A GO / PHASE B GO / PHASE C STOP`
策略决定：`OWNERSHIP_DRIVEN_BLENDER_BRIDGE_LOCAL_FILL_V1`
最近检查的仓库 HEAD：`b87bb7d` (`Clarify Phase C recovery gates and evidence requirements`)
Phase C runtime baseline：`1b8f120` (`wip(feature-chamfer): checkpoint phase c regular diagnostics`)
上游权威 handoff：`docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md`

本文是下一次 Session 的执行入口。权威顺序固定为：项目 `AGENTS.md` → 上游 handoff 的产品语义和 Phase A→E Stop/Go → 本文的 Phase C 当前策略与门禁。

本文明确替代旧版第 7–8 节中的“自研 canonical cyclic rail + circular DP”主路线。旧代码和历史 diagnostics 仍可用于定位问题，但不得因为已经存在就继续叠加 matching、trim 或 handoff 例外。

## 1. 一句话任务

保留已经通过的 Preview Pipe、independent batched Exact Boolean、Boundary Edge ownership/provenance 与 exactly-once ledger；利用稳定 ownership 唯一选出每条 Pipe 的左右 regular rails，调用 Blender 自己的 `bmesh.ops.bridge_loops()` 补 regular 面，再只对能唯一证明属于 Plan junction 的剩余闭合洞调用 Blender Fill。14 cells × 3 和独立审计通过前，Phase C 保持 STOP，不进入 D/E，不接入正式 `hst.feature_chamfer_gn(FINALIZE)`。

## 2. 非技术说明

目前最困难的部分不是“边属于谁”，而是旧实现试图自己计算两排边应该怎样逐点配对。闭环起点不同、两边分段数不同、多个 Pipe 相交时，这套自研配对会产生丢边、重复认领或假绿。

新的方向把职责分开：

1. 现有系统继续负责准确找到每条边属于哪条 Pipe、哪一侧、是否靠近交点。
2. Blender 的 Bridge Edge Loops 负责把同一 Pipe 的左右两排 regular edges 连成面。
3. 两条 Pipe 交叉位置预先留空；全部 regular bridge 完成后，重新找交点处留下的闭合洞。
4. 只有洞口被证明属于一个已知 junction 时，才使用 Blender Fill 填面。
5. 任何无法归属、非闭合或混合多个 junction 的洞都应诚实失败，不能自动补掉。

这条路线不是从头猜算法。项目旧 `Feature Chamfer (Sharp/Seam)` Operator 已有 `_bridge_then_fill()` 实现，测试也证明过 `Bridge Edge Loops → Fill` 可以生成 watertight Mesh。需要复用的是 Blender 操作和手工工作流语义，不是旧实现里基于 `_rail_pair_score()` 的近似配对或“Fill 全部剩余闭环”的宽松判断。

## 3. 目标入口与阶段边界

当前三条入口必须分开：

```text
正式 PREVIEW
UI 主按钮(action=AUTO)
→ hst.feature_chamfer_gn(PREVIEW)
→ owned Curve + GN Preview modifier + GN_PREVIEW_PIPE_V1

当前正式 FINALIZE（本阶段禁止修改/接入）
同一 UI/Operator
→ hst.feature_chamfer_gn(FINALIZE)
→ 旧 build_pipe_chamfer(PATCHED)

Phase C 验收入口
正式 hst.feature_chamfer_gn(PREVIEW)
→ hidden hst.experimental_feature_chamfer_batched_finalize(PHASE_C_REGULAR_CORE)
→ build_batched_feature_chamfer()
→ debug Mesh / diagnostics / ledger artifacts
```

Phase C 只验证 `Algorithm + Backend + hidden Adapter seam`。即使 Phase C GO，全局产品状态仍是 `PROTOTYPE`；Phase D/E 仍要分别完成 backend product assembly、正式 Operator 接入、Undo/rollback 和 Visual/Product 验收。

## 4. 已确认基础与证据边界

### 4.1 可继续复用

- Phase A GO：正式 Preview Pipe 输入合同已确认。
- Phase B GO：Pipe overlap graph、stable coloring、batch 内无 overlap、正序/逆序 independent Exact Boolean staging 已确认。
- Source 不变；每条切口 Boundary Edge 已有 stable identity、Pipe/side/source-patch ownership、consumer 双向引用和 exactly-once ledger 框架。
- 旧实验代码存在 `_bridge_then_fill()`：同一 Pipe 两侧 rail 调用 `bmesh.ops.bridge_loops()`，然后对剩余闭合洞调用 `bmesh.ops.contextual_create()`。
- 已有 `feature_chamfer_bridge_then_fill_smoke`，证明隔离 BMesh 中 Bridge → Fill 可得到 watertight Mesh。

相关代码入口：

- `ui_panel.py`：`Feature Chamfer (Sharp/Seam)` → `hst.experimental_pipe_chamfer`
- `utils/experimental_pipe_chamfer_utils.py::_bridge_then_fill()`
- `tests/blender_test_driver.py::test_experimental_pipe_chamfer_bridge_then_fill_smoke()`

### 4.2 不能当作 GO 证据

- 2026-07-23 的旧 `14/14 × 3` 已因 fake green 撤销。
- 历史 `2 PASS / 12 FAIL` 只说明失败分布，不代表新策略当前结果。
- 顶层 matrix `results.json` 会被定向 run 覆盖；所有 gate 必须使用独立 run-id/artifact directory。
- checkpoint 中 full-cyclic lift/phase/DP 是未证明 WIP；新路线不依赖它们。
- `_zero_length_regular_connector_handoff_proof()` 存在已记录的控制流错位，必须在进入 Bridge 集成前修复并补直接合同。
- 当前 matrix runner 的 `phase_c_go` 存在 fake-green 风险，必须先 harden。

### 4.3 当前状态

- `Algorithm`：Bridge/Fill 手工语义和隔离 smoke 已有证据；ownership 驱动的产品组合尚未实现。
- `Backend`：Phase C prototype，STOP。
- `Operator`：hidden experimental Adapter。
- `Visual/Product`：未验证、未接受。

## 5. 不可变范围与禁止路线

V1 固定范围：四个 `.blend` fixture、7 个 objects、radius `{0.01, 0.03}`，共 14 cells；每格至少重复 3 次。不得写对象名、fixture、坐标、Edge/Vertex index 或 Pipe ID 特判。

继续禁止：

- SDF / `Points to SDF Grid → Grid to Mesh`；
- nearest-owner、nearest-rail 或 `_rail_pair_score()` 猜测配对；
- global fill、centroid fan、无约束 triangulate；
- 共享 working Mesh 上按顺序累计 Cut；
- 用放宽 handoff/setback/width/monotonic/zero-area guard 掩盖 regular 失败；
- 忽略大 fragment、重复 provenance、zero-area 或 non-manifold；
- Phase C GO 前进入 Phase D/E；
- Phase C GO 前修改正式 `hst.feature_chamfer_gn(FINALIZE)` runtime path；
- 修改 `auto_load.py`；
- 修改或再次提交 `tests/.DS_Store`。

“Junction-local Fill”不属于被禁止的 global fill。两者边界如下：

```text
允许：一个闭合洞的全部边与端口能唯一映射到同一个 Plan junction，
     且洞由已完成的相邻 regular Bridge 自然留下。

禁止：遍历所有剩余 boundary cycles 并无条件 Fill；
     仅因为闭合、距离接近或 Fill 能成功就认定它是 junction。
```

## 6. 新的 Phase C 数据流

```text
independent batched Exact Boolean staging
→ immutable Boundary Edge universe + ownership ledger
→ structural junction envelope / ports
→ ownership-driven RegularBridgeJob 列表
→ 全局 Edge claim preflight
→ provisional BMesh 上调用 Blender Bridge Edge Loops
→ 重新提取 remaining boundary graph
→ 唯一归属的 JunctionFillJob 列表
→ provisional BMesh 上调用 Blender Fill
→ topology / provenance / geometry / watertight guards
→ 成功后一次性发布 Mesh、ledger、records、ports
```

Cut 仍然独立 batched，不在共享 Mesh 上累计。Bridge/Fill 发生在所有 Cut staging 和 ownership 冻结之后的 provisional patch BMesh，因此不违反 Phase B 的顺序独立约束。

### 6.1 RegularBridgeJob

建议内部合同：

```text
RegularBridgeJob {
    pipe_id,
    strand_id,
    source_patch_pair,
    left_edge_ids,
    right_edge_ids,
    left_chain_kind: OPEN | CYCLIC,
    right_chain_kind: OPEN | CYCLIC,
    terminal_or_junction_ports,
}
```

生成规则：

- 左右侧必须来自同一 `pipe_id/strand_id` 和权威 `source_patch_pair`。
- 每侧 Edge 必须各自形成一个连通、有序、无分支的 boundary chain/cycle。
- regular Edge 在生成 job 前先减去有直接结构证据的 junction envelope / terminal port Edge。
- 一个 Edge 最多属于一个 BridgeJob；相同 Edge 出现在两个 job 时立即 `REGULAR_BRIDGE_CLAIM_CONFLICT`。
- 多个候选 chain pair 时，只能使用 ownership、Plan topology 和端口 token 唯一决定；不得用距离分数挑最近的一对。
- 无唯一 pairing 时保留结构化 unresolved，不进入 Bridge。

Bridge 调用原则：

- 使用 BMesh API `bmesh.ops.bridge_loops()`，不依赖 Edit Mode selection/context。
- 把完整两侧 Edge sets 一次交给 Blender；不再自研 vertex-to-vertex cyclic DP、seam rotation 或 zipper faces。
- open/cyclic 具体参数必须由 chain topology 决定，并有直接合同；不得为了某 fixture 硬编码。
- Blender 可以处理左右分段数不同，但返回结果仍必须通过本计划的 provenance 和 geometry guards。

### 6.2 JunctionFillJob

全部 Bridge 完成后，必须从当前 BMesh 重新提取 boundary graph，不能复用 Bridge 前的 Edge 快照。

建议内部合同：

```text
JunctionFillJob {
    junction_id,
    participating_pipe_ids,
    boundary_edge_ids,
    bridge_terminal_edge_ids,
    source_ports,
}
```

只有同时满足以下条件才允许 Fill：

- boundary 是单一闭合 cycle，没有分支、开放端或重复 Edge；
- cycle 的原始 Boundary Edges 都属于同一个权威 Plan junction/envelope；
- Bridge 新生成的 terminal Edges 都能通过 BridgeJob 端口反查到同一 junction；
- participating Pipe 集合与 Plan junction 一致；
- 该 cycle 未被现有 Face 占据，也未被其他 FillJob claim；
- Fill 前后不吞掉任何 regular unresolved Edge。

满足合同后，使用项目旧路线已验证的 Blender Fill API（优先复用 `bmesh.ops.contextual_create()` 的现有模式）。返回 Faces 为空、产生多个不受约束区域或 topology guard 失败时，整个 Phase C transaction 失败。

### 6.3 Ownership、provenance 与事务提交

在修改 BMesh 前建立全局 claim map：

```text
edge_id → REGULAR_BRIDGE(job_id, side)
        | STRUCTURAL_JUNCTION(junction_id)
        | STRICT_CONNECTOR(proof_id)
        | UNRESOLVED(reason)
```

守恒门：

```text
Boundary Edge universe
== bridge_claim_edges ∪ junction_claim_edges
   ∪ connector_claim_edges ∪ unresolved_edges
且四者 pairwise disjoint
```

事务规则：

- 在 provisional BMesh 和 provisional ledger 上执行全部 Bridge/Fill。
- 每次 Blender op 后立刻记录返回 Faces/Edges 和对应 job ID。
- 每条 Bridge 输入 Boundary Edge 必须恰好增加一个 chamfer Face consumer。
- 每个新 Face 必须反查唯一 `RegularBridgeJob` 或 `JunctionFillJob`。
- 任一 job 失败时丢弃 provisional 结果，正式 ledger/output fingerprint 不变。
- 全部 topology、geometry、provenance 和 coverage guards 通过后才一次性发布。

### 6.4 必须保留的 guards

Bridge/Fill 成功返回 Faces 不等于产品正确。必须继续检查：

- missing / extra / duplicate Edge claim 为 0；
- Edge consumer 正反向引用一致；
- zero-area Faces 为 0；
- face orientation 一致；
- self-intersection / non-manifold / overconnected Edge 为 0；
- 所有最终 Edge 的 `link_faces == 2`，除非阶段合同明确允许开放 port；
- forward/reverse staging 的 geometry、ledger、BridgeJob、FillJob fingerprints 一致；
- source Mesh unchanged；
- 未产生 allowlist 外 handoff 或 macro setback。

## 7. 已知失败 cluster 在新路线中的处理

### Cluster A — cyclic full-span / common-only remainder

不再按左右 rail 的参数交集切片，也不再寻找人工 seam。ownership 唯一确定完整左右 cycles 后，把两侧完整 Edge sets 交给 Blender Bridge。任何未进入 Bridge 的 macro Edge 都是 coverage failure。

### Cluster B — cyclic provenance duplicate

Bridge 前的全局 claim map 保证一个 Edge 只能进入一个 BridgeJob。冲突在几何修改前失败，不再依赖 component 迭代顺序或事后 ledger 去重。

### Cluster C — bilateral DP/trim failure

移除自研 L5/R3 DP/trim 主路径。只要两侧 ownership/ports 能唯一形成一对完整 regular chains，就由 Blender Bridge 处理不同分段数。若 ownership 无法唯一成对，报告 pairing ambiguity，不能提高 setback 阈值。

### Cluster D — zero-length connector

先修复 connector proof 控制流。只有有唯一结构 proof 的零长度 Edge可以走 `STRICT_CONNECTOR`；它们不进入 Bridge/Fill，也不能带走邻近正常 Edge。必要 collapse 只能在 provisional BMesh 上对该 proof 的 Edge执行。

### Cluster E — tricky Solid.004 r0.01 假绿

旧 7 个大 paired residual 必须进入 RegularBridgeJob，不能再进入 handoff。只有严格批准的短 component、权威 terminal/junction port 或 zero-length connector 能离开 regular。Fill 也只能消费明确的 junction hole，不能成为大 fragment 的替代出口。

## 8. 分步执行与 Stop/Go

### Gate 0A — 恢复真实基线

目标：只读核对 source、文档和工作树。

操作：

1. 读取 `AGENTS.md`、本文、上游 handoff、`tests/TESTING_POLICY.md`、`tests/README.md`。
2. 记录实际 `git HEAD/status/diff`；不得假设 HEAD 仍等于本文记录值，不得 reset 用户改动。
3. 确认 runtime baseline `1b8f120` 仍是祖先，并审计其后的 runtime/test diff。
4. 明确 `tests/.DS_Store` 当前实际状态；保留它，不修改、不加入下一次提交。
5. 修复 `_zero_length_regular_connector_handoff_proof()` 控制流并补 valid/rejection 合同。

Go：baseline 可追溯、没有未解释的 runtime 修改、connector 合同可信。
Stop：Phase A/B、Preview contract 或 source integrity 回归。

### Gate 0B — Evidence runner hardening

保留旧计划已经确定的 runner 门禁：

- full gate 必须直接要求 14 cases、42 repetitions、Phase A/B/C、Preview contract、source unchanged、Adapter result 和无 debug 残留全部通过；
- unknown case、0 executed case、requested/executed mismatch、partial run 必须 non-zero；
- 每次 gate 使用唯一 artifact directory；
- summary 记录 run-id、Git HEAD + dirty fingerprint、argv、Blender/fixture/code hashes、artifact manifest/sha256；
- runner 加 fake-green 负向合同，不能只信 backend 的 `phase_c_go` 布尔值。

Go：失败不能汇总为 GO，artifact 能绑定具体代码和命令。
Stop：partial/stale artifact 仍可能冒充完整 gate。

### Gate 0C — 冻结诚实失败与旧策略边界

1. 新鲜重跑现有 handoff/connector/cyclic contracts。
2. 定向运行 `simple__extruded_002__r0p010`，保存 commit-bound 失败基线。
3. 为旧 full-cyclic lift/phase/DP 函数加策略开关或隔离边界；新 Bridge 主路径不得调用它们。
4. 运行已有 `feature_chamfer_bridge_then_fill_smoke`。

Go：旧 WIP 被隔离；Bridge → Fill smoke 通过；simple case 诚实失败且 Phase A/B 正常。
Stop：环境、fixture、Operator 或 runner 不可信。

### Step 1 — Bridge / Local Fill 合同先行

新增最小正负合同：

- ownership 唯一配对两条 open rails；
- ownership 唯一配对两条 cyclic rails；
- 左右 Edge 数不同仍由 Blender Bridge 生成合法 strip；
- 同一 Edge 被两个 BridgeJob claim 时 fail-closed；
- ambiguous rail pair 不使用距离 score；
- Bridge 返回 Faces 后 Edge↔Face provenance 完整；
- Bridge 后一个明确 junction cycle 可 local Fill；
- ordinary remaining cycle、mixed-junction cycle、open chain、occupied cycle 均拒绝 Fill；
- 任一 Blender op 失败时 provisional Mesh/ledger rollback。

Go：所有正负合同通过；旧 `_rail_pair_score()` 和自研 cyclic DP 不在新 runtime path。
Stop：仍需 nearest/fixture hint 才能决定 pairing，或 Fill 只靠“闭合”判断。

### Step 2 — Ownership-driven BridgeJob producer

在 batched backend 中只生成 jobs/diagnostics，不先生成 Faces：

- 从 immutable Boundary universe 按 Pipe/side/source patch 分组；
- 用权威 Plan junction envelope/ports 切出 regular chains；
- 生成全局 Edge claim map；
- 输出 job、unresolved、claim conflicts 和 coverage 守恒 diagnostics。

Go：simple 4 cells 的所有 regular Edge 恰好进入一个 BridgeJob；junction/connector/unresolved 分类互斥。
Stop：出现 macro unclaimed Edge、重复 claim 或基于距离的 pairing。

### Step 3 — Simple 4 cells：Blender Bridge 主路径

依次运行：

1. `simple__extruded_002__r0p010`
2. `simple__extruded_002__r0p030`
3. `simple__solid_44__r0p010`
4. `simple__solid_44__r0p030`

每格先 1 次，全部通过后各 3 次。要求：

- full regular rail 由 Blender Bridge 生成完整 strip；
- unresolved/deferred/claim conflict 为 0；
- all ledger edges exactly once；
- Edge↔Face witness 100%；
- zero-area/orientation/self-intersection/non-manifold 为 0；
- forward/reverse fingerprints 一致；
- 无 junction Fill、macro setback 或自研 DP fallback。

Go：simple `4/4 × 3` 新鲜 PASS。
Stop：任一格只 Bridge 局部 rail，或通过 handoff/Fill 掩盖 regular Edge。

### Step 4 — 两 Pipe 交叉：先留洞再 Junction-local Fill

选择矩阵中最小的真实双 Pipe 交叉 cell 做定向原型：

1. Plan junction envelope 内的 Edge 预先不进入 Bridge。
2. 对各 Pipe 两侧 regular rails 完成全部 Bridge。
3. 从当前 BMesh 重新提取 remaining boundary graph。
4. 构造唯一 `JunctionFillJob`，调用 Blender Fill。
5. 验证 Fill Faces 只消费该 junction cycle，最终 watertight。

Go：交点洞具有唯一 junction witness；Bridge 和 Fill Face provenance 完整；无 global fill。
Stop：需要 Fill 非 junction cycle、洞不是闭环、一个洞混合多个 junction，或 Fill 吞掉 unresolved regular Edge。

### Step 5 — 同根 cyclic cluster

运行：

- `tricky__solid_016__r0p010/r0p030`
- `tricky_b__extruded_003__r0p010/r0p030`

目标：证明完整 ownership cycles 交给 Blender 后，不再出现 common-only macro remainder。

Go：4 cells 各 3 次通过；simple 4 cells canary 保持绿。
Stop：单侧大差集、重复 claim 或 junction Fill 越界。

### Step 6 — Provenance conflict cluster

运行：

- `tricky_b__extruded_002__r0p010/r0p030`
- `mixed__extruded_002__r0p010`

目标：所有 BridgeJob/FillJob claims 在 op 前唯一；不再出现 `REGULAR_MATCH_PROVENANCE_CONFLICT` 或 ledger conflict。

Go：3 cells 各 3 次通过；没有通过丢弃 parent/residue Edge 达成绿灯。
Stop：结果依赖 job 执行顺序或事后去重。

### Step 7 — L5/R3 与 zero-length cluster

先运行 `tricky__solid_004__r0p030`：证明 Blender Bridge 能处理完整 L5/R3 chains，不使用自研 DP/trim 或放宽 setback。

再运行 `mixed__extruded_002__r0p030`：零边只由严格 connector proof 消费；邻近正常 Edge 继续 Bridge，不产生零面积 Face。

Go：两个 cells 各 3 次通过，并重跑 simple canary。
Stop：大 Edge 进入 setback、零边带走正常 Edge或 geometry guard 被放宽。

### Step 8 — tricky Solid.004 r0.01 假绿审计

运行 `tricky__solid_004__r0p010` 三次，逐项确认：

- 旧 7 个 macro residual 全部进入 Bridge 并产生 Face witness；
- 只有结构证明的 junction/terminal/short connector 留给 handoff；
- pipe0 `0:5` 只能在通用严格 `SHORT_COMPONENT_SETBACK_V1` 成立时使用，不写 ID 白名单；
- pipe2 terminal-tail reconciliation 保持双向唯一；
- 无 folded/numeric/direct terminal 大 Edge例外；
- Fill 只发生在有唯一 junction witness 的洞。

Go：3 次稳定通过，unresolved=0，unexpected/macro setback=0。
Stop：Bridge 失败被 handoff 或 Fill 掩盖。

### Step 9 — 完整 Phase C gate

运行完整 headless regression，再运行 `14 cells × 3 repetitions`。必须直接核对：

- 14/14 cases、42/42 repetitions 全 PASS/stable；
- Phase A/B/C、Preview contract、source unchanged 全通过；
- Boundary coverage exactly-once；
- BridgeJob/FillJob claim conflicts 为 0；
- regular/junction Face provenance 双向完整；
- no unresolved/deferred/zero-area/non-manifold/self-intersection；
- forward/reverse geometry、ledger、BridgeJob、FillJob、port fingerprints 一致；
- junction Fill count 与 Plan junction inventory 一致；
- ordinary/global Fill count 为 0；
- handoff reason 全在冻结 allowlist，unexpected/macro setback 为 0；
- artifacts 与实际 HEAD/dirty fingerprint/命令一致。

Go：只将 Phase C internal gate 更新为 GO；全局仍为 `PROTOTYPE`。
Stop：任一 stale/partial/fake-green、unproven Fill 或缺失 Face witness。

### Step 10 — 独立 Spec Audit

由未参与实现的只读 reviewer 核对：

- 正式 PREVIEW → hidden Adapter 是实际测试入口；正式 FINALIZE 未提前修改；
- Cut 仍是 independent batched，不是共享 Mesh 顺序累计；
- new runtime path 使用 ownership-driven Blender Bridge / junction-local Fill；
- `_rail_pair_score()`、nearest、旧 cyclic DP/trim 没有成为 fallback；
- Fill 必须有唯一 Plan junction witness，不存在 global fill；
- ledger/Face provenance/exactly-once 和 rollback 有直接证据；
- 14×3 artifacts 新鲜且 runner 无 fake green；
- 文档状态与代码一致。

存在 P0/P1 或高严重度偏差：Phase C 保持 STOP 并继续修复。
无高严重度问题且全部 gate 通过：更新本文及上游 handoff 为 `PHASE C GO / global PROTOTYPE`，再为 Phase D 写新计划。

## 9. 验证命令

每次 gate 创建唯一 `<run-id>` 和不存在的 artifact directory。Blender 固定使用：

```text
/Applications/Blender.app/Contents/MacOS/Blender
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

单格：

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

macOS Blender 5.1.2 偶发在 Metal 初始化 `supports_barycentric_whitelist` 崩溃。如果发生在 fixture 加载前，以相同命令重试一次并单独记录为环境失败；算法阶段异常不得归入 Metal crash。

## 10. 实现纪律

- 先定位入口链，再修改；不修改 `auto_load.py`。
- 新主路径优先复用项目已有 BMesh Bridge/Fill 模式，做最小充分抽取；不直接复制旧 `_rail_pair_score()`。
- 功能函数按项目规范添加中文块注释；imports 放文件头。
- Blender op 异常补充 job/pipe/junction 上下文后 rethrow，不 silent fallback。
- 每个 Step 先跑直接合同，再定向 1 次，再 cluster 3 次，并重跑 simple canary。
- 任一 Step 未 GO 时只修当前 Step，不提前进入后续 runtime path。
- 不因单格或 isolated smoke 绿灯更新 Phase C GO。
- 不默认提交大 artifacts。
- 未经用户允许不开分支；本文不授权自动 commit。
- 保留 `tests/.DS_Store`，不修改、不加入下一次提交。
- 长程任务真正完成、失败或需要用户决策时，按 `task-completion-notifier` 发送一次对应通知；中间进度不发送。

## 11. Suggested Skills

- `blender-cli`：运行 Blender background contracts、matrix 与 artifact 检查。
- 项目内 `agent-skills/hst-blender-regression/SKILL.md`：统一 headless 回归入口。
- `diagnosing-bugs`：按 BridgeJob / FillJob / claim cluster 窄化 diagnostics。
- `tdd`：先写 ownership pairing、local Fill 和 rollback 正负合同。
- `code-review`：Phase C GO 前独立 Spec Audit。
- `verification-before-completion`：核对 run-id、HEAD、42 repetitions、artifact hashes。
- `task-completion-notifier`：仅最终 completed/attention/failed 使用。

某个通用 skill 不可用时，使用项目内 regression skill 和等价验证流程继续，不因此停止。

## 12. 新 Session 启动 Prompt

```text
继续 HardsurfaceGameAssetToolkit Feature Chamfer batched Phase C。

先读取并严格遵守：
1. 项目 AGENTS.md
2. docs/plan/2026-07-24-feature-chamfer-phase-c-regular-recovery-plan.md
3. docs/plan/2026-07-23-feature-chamfer-batched-cut-fill-handoff.md
4. tests/TESTING_POLICY.md 与 tests/README.md

当前策略已经改为 OWNERSHIP_DRIVEN_BLENDER_BRIDGE_LOCAL_FILL_V1：保留 independent batched Exact Boolean、Boundary Edge ownership/provenance 和 exactly-once ledger；用 ownership 唯一选择同一 Pipe 两侧 regular rails，调用 Blender bmesh.ops.bridge_loops() 补 regular 面；交叉 Pipe 的 junction 先留空，全部 Bridge 后重新提取 boundary，只对有唯一 Plan junction witness 的闭合洞调用 Blender Fill。禁止 global fill，也禁止 _rail_pair_score()/nearest 或旧自研 cyclic DP/trim fallback。

先记录实际 HEAD/status/diff，不要假定文档中的 HEAD 仍是当前值，不得 reset 用户修改。保留 tests/.DS_Store，不修改、不加入下一次提交；不修改 auto_load.py，不开新分支。

当前状态 PAUSED / PROTOTYPE / Phase A GO / Phase B GO / Phase C STOP。Phase C GO 前禁止进入 D/E，禁止接入正式 hst.feature_chamfer_gn(FINALIZE)。

按 Gate 0A/B/C 开始：修 zero-length connector 控制流、harden evidence runner、隔离旧 cyclic WIP并保存新鲜失败基线。随后合同先行实现 RegularBridgeJob、JunctionFillJob、全局 claim preflight 和 provisional transaction。先让 simple 4 cells 的 Blender Bridge 主路径 4/4×3 通过，再完成最小真实双 Pipe junction-local Fill，之后按 cluster 扩展，最后跑新鲜 14×3 和独立 Spec Audit。

禁止 SDF、nearest-owner/rail、global fill、centroid fan、无约束 triangulate、共享 Mesh 顺序累计 Cut、模型特判、忽略大 fragment 或放宽 geometry guard。除非真正需要用户作实质决定，否则持续自主推进。
```
