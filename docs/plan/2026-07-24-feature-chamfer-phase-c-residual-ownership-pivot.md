# Feature Chamfer Phase C — Pre-Boolean Profile Lineage Plan

日期：2026-07-24
状态：`AUTHORIZED / PRE-BOOLEAN LINEAGE RETAINED / MAXIMAL-CHAIN PROBE GO / PHASE C STOP / PROTOTYPE`

## 0. 目标入口与阶段范围

```text
UI Feature Chamfer GN
→ hst.feature_chamfer_gn(action=PREVIEW)
→ hst.experimental_feature_chamfer_batched_finalize(PHASE_C_REGULAR_CORE)
→ independent Exact Boolean staging
→ constrained normalization
→ pre-Boolean Cutter profile lineage
→ regular consumer candidate artifact
```

- 用户操作：对 `tricky__solid_004__r0p030` 运行 PREVIEW，再从 hidden Phase C Adapter 进入只读 probe。
- 预期可见变化：只生成 diagnostics / `.blend` artifact；正式 `FINALIZE` 和 source Mesh 不变。
- 自动证据：目标 Operator 入口、raw → normalized exactly-once lineage、pre/post Boolean Face/Edge incidence、Pipe/profile-side/opposite-side/longitudinal-segment 身份、source unchanged。
- 本阶段 Go：一个 maximal source chain 获得唯一、连续、全局 exactly-once 的 Boundary consumer chain；正逆 batch 结果一致。
- 本阶段 Stop：consumer Edge 被多个 source chain 重复占用、候选不形成唯一连续 chain、仍需 nearest/坐标匹配、合成 owner/port、fixture 特判，或 pre-Boolean identity 在 Boolean 后丢失/冲突。

本计划不授权正式 producer/`FINALIZE` 接入，不授权 Phase D/E。

## 1. 已确认事实

1. 目标 3 条 raw Edge 已有唯一 `Pipe 1 / Patch 1 / Rail` owner；问题不是“属于哪条 Pipe”。
2. clean A/B 只安全 dissolve 一个近共线 degree-2 内点：3 raw Edge → 2 normalized Edge。被移除点正对应用户观察的蓝色问题区域。
3. 几何容差、terminal/port token、Pipe/Patch/Rail provenance、source unchanged、raw Edge exactly-once lineage 均通过；constrained normalization 应保留。
4. 旧 probe 把 C4 几何相对面当 Boundary pairing，因此错误报告 direct witness 为 `0`；这不是 Boolean 没有生成边。
5. 每条 residual 已能追到 `PROVEN_C4_PIPE` cutter Face、profile ring 和 C4 几何 opposite Face signature；用户截图和后续全量 incidence census 已确认对侧 Boundary Edge 实际存在。旧结论把 C4 `+2` Face 错当成两条 Boundary rails 的 pairing。
6. 修正后找到 Patch 2 / side 0 的真实 Edge `d08fa882…` 与 `78c620a9…`；但逐 normalized Edge 解析让 `d08fa882…` 被两个 consumer chain 重复占用，证明 pairing 粒度必须提升为 maximal chain。
7. 局部只有一条 Pipe 只消除了 Pipe owner 歧义；同一 Pipe 仍有四个 profile sides 和沿程多个 Face ring，不能仅凭单 Pipe 推导唯一对侧 consumer。

证据：

- `docs/diagnostics/feature-chamfer-generalization/phase-c-clean-dissolve-ab-probe.md`
- `/private/tmp/hst-phase-c-clean-ab-probe-20260724-05/report.json`

## 2. Boolean Pro、旧 Finalize 与当前 Phase C 的边界

- `Boolean Pro` 继续负责 viewport Preview；当前 Phase C Adapter 重新执行 independent Exact Boolean，不直接消费 Boolean Pro evaluated result。
- 历史 probe 已证明 Boolean Pro 的 `New Faces / Slice Faces` 在当前资产配置为空，`Boundary Edges` 含 loose Edge，不能作为 authoritative provenance 真源。
- 旧 tracked Boolean 更容易判断 source/groove，是因为它在 Boolean 前写入 source Face/Patch marker。这个“先写 provenance、后做 Boolean”的原则应复用。
- 旧 owner classifier 中“只有一个 Pipe 就归给它”及距离评分只能提供候选，不能证明 profile opposite-side pairing；不得恢复为权威路径。
- Commit `1b8f120` 的“已能判断边归属”指 Pipe/Patch/Rail owner 基础设施；当前门禁新增的是 opposite-side pairing 和实际 Face consumer。两者验收层级不同，不冲突。

## 3. 新主路线：Pre-Boolean Cutter Profile Lineage

### Step 1 — 冻结 cutter 身份

在每个 Pipe cutter 进入 Boolean 前，为每个 profile Face 建立稳定、非坐标身份：

- `pipe_id`、`strand_id`；
- `profile_side_id` 与 `opposite_profile_side_id`；
- `profile_ring_id`；
- `longitudinal_segment_id` 与前后邻接；
- terminal/junction/port incidence（若存在）。

Go：相同 cutter 在正逆 batch 中身份图完全一致；C4 ring 每个 side 恰有一个 opposite side。

### Step 2 — 传递到 Boolean 交线

沿用已有 Face one-hot / cutter Face ID / source Patch marker，把 pre-Boolean Face 身份传递到 post-Boolean groove/source intersection Edge。优先使用：

- 同一 Boolean 结果内的 Face → Edge incidence；
- native `Intersecting Edges` field 能力；
- 完整 cutter Face ID 与 longitudinal adjacency。

几何“是否接触”可以作为结果一致性验证，但不得用 nearest distance 或坐标阈值产生 owner。

Go：每条目标 Boundary Edge 恰有一个 `(Pipe, profile side, source Patch, longitudinal segment)` direct witness；这是 identity transfer 门禁，不等于最终 fragment-to-fragment pairing。missing/conflict 必须 fail-closed。

### Step 3 — Constrained normalization

对同一完整 lineage 的近共线 degree-2 fragmented Edge 运行已验证 normalization：

- 禁止跨 Pipe/Patch/Rail/profile-side/segment 合并；
- 禁止删除 endpoint/port/junction/setback token；
- 保留 raw Edge → normalized Edge exactly-once、dissolved token 与 Face lineage。

Go：A/B 合同保持，normalized Edge 的 lineage 是其所有 raw Edge lineage 的无冲突并集。

### Step 4 — Boundary consumer 解析

对 normalized subchain，使用同一 `strand_id` 的唯一权威 `StripCorrespondence` 取得 partner Patch，再从当前 Cutter Face 的 `profile_neighbor_face_signatures + longitudinal segment` 查找对侧 Boundary chain。C4 `opposite_profile_side_id` 保留为几何诊断，不能再直接充当 Boundary pairing。只允许：

1. 唯一 direct opposite Edge/chain；
2. 唯一权威 Plan port incidence；
3. `UNRESOLVED`。

禁止把“沿 graph 最近的已消费 Edge”自动当作当前 residual 的 consumer；longitudinal graph 只能证明身份连续性，不能跨 segment 借用 unrelated sink。

### Step 5 — Maximal chain pairing

先按共享 endpoint token、完整 source lineage 和同一 Plan component，把连续 normalized Edge 合并为 maximal source chain；再验证 candidate Edge 形成唯一连续 open chain。pairing 以整条 source chain 为单位，禁止要求每条 normalized fragment 独占一条对边。

Go：source/candidate chain 都连通、端点与 chain kind 唯一；candidate Edge 在不同 maximal source chains 之间全局 exactly-once。missing、断链、重复 chain、跨 component overlap 均 fail-closed。

### Step 6 — 目标 cell 只读验收

先用 synthetic single-Pipe fixture 证明 missing/duplicate/conflict、candidate overlap、重复 StripCorrespondence 与断链均 fail-closed，再从目标 Operator 重跑 `tricky__solid_004__r0p030`。

Go：目标 maximal source chain 获得唯一 direct Boundary consumer chain，且 raw/normalized/candidate exactly-once、source unchanged、正逆 batch 一致。否则保持 Phase C STOP，并输出缺失发生在 Face identity、Boolean transfer、chain connectivity 还是全局 overlap。

## 4. 后续 Stop / Go

- 目标 cell 通过后，才允许把同一只读 probe 扩展到 `tricky__solid_004__r0p010` 与 `mixed__extruded_002__r0p030`。
- 三个失败 cell 都有唯一 direct witness 后，才可以另立接入计划修改正式 producer。
- 正式接入后重新从目标 Operator 跑 cluster、完整 14×3、source/rollback、Face witness、exactly-once 和独立 Spec Audit。
- 完整 Phase C GO 前不得进入 Phase D Fill/product assembly 或 Phase E。

## 5. 明确禁止

- `_rail_pair_score`、nearest/BVH/centroid、坐标焊接、宽度 trim 猜 owner；
- “当前只有一条 Pipe”作为 opposite pairing 的充分证据；
- 合成 owner/port、扩大 setback、runner allowlist、fixture 特判；
- 直接把 Boolean Pro loose `Boundary Edges` 当正式 ledger；
- 低层 artifact 可运行就宣称 `INTEGRATED/VERIFIED/ACCEPTED`。

## 6. 当前状态与下一交付

- `Algorithm/Backend: PROTOTYPE`
- `Operator: NOT INTEGRATED`
- `Visual/Product: NOT VERIFIED`
- `Phase C: STOP`

只读 maximal-chain pairing report 和可检查 `.blend` 已从目标 PREVIEW → Phase C Adapter 产生，Algorithm/Backend probe 条件通过；终局独立 spec audit 为 `P0=0 / P1=0`。下一步按第 4 节把同一只读 probe 扩展到 `tricky__solid_004__r0p010` 与 `mixed__extruded_002__r0p030`，不能因单个目标 cell 通过就接入 Adapter runtime；正式 `FINALIZE`、Phase D/E 仍不在本阶段。

完成声明前独立 Spec Audit 必须检查：runtime 未越级修改；测试从目标 Operator 开始；consumer 不是最近 sink；计划、代码、artifact 的阶段状态一致。
