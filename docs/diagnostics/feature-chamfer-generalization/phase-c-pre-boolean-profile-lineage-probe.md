# Phase C Pre-Boolean Profile Lineage Probe（历史诊断，主路线已转向 Pre-Delete Groove FaceGraph）

日期：2026-07-24
状态：`HISTORICAL DIAGNOSTIC / SUPERSEDED AS PAIRING ROUTE / PHASE C STOP`

> 当前权威实施计划为 `docs/plan/2026-07-24-feature-chamfer-phase-c-residual-ownership-pivot.md`。本文件保留旧 probe 的证据和失败边界；其中 profile-neighbor direct incidence 不再是当前两侧开放边配对路线。

## 目标入口

```text
Feature Chamfer GN
→ hst.feature_chamfer_gn(action=PREVIEW)
→ hst.experimental_feature_chamfer_batched_finalize(PHASE_C_REGULAR_CORE)
→ independent Exact staging
→ probe-only pre-Boolean profile lineage
```

正式 `FINALIZE`、Phase D/E 和 source Mesh 未修改。完整 lineage 由显式
`freeze_complete_profile_lineage` probe 开关启用；既有 Adapter 默认路径不启用。

## 历史实现合同（已由 Pre-Delete Groove FaceGraph pairing 取代）

- 当时在 Boolean 前冻结 `Pipe / strand / profile side / opposite side / longitudinal segment / port incidence`。
- 当时的 probe 在 Boolean 后通过 transferred cutter Face identity 与实际 Boundary Edge incidence 建立候选。
- 当时的 consumer 合同要求相邻 Cutter Face direct incidence；mixed 已证明该条件不完备，现不再作为通用 Go witness。
- 禁止项仍然有效：不沿 longitudinal graph 查找最近 sink，不使用 nearest/BVH/坐标、单 Pipe fallback、synthetic owner/port。
- constrained normalization 合同仍保留：只合并完整 lineage 一致的近共线 degree-2 fragment，并保留 raw→normalized exactly-once。

## Synthetic 门禁

single-Pipe fixture 已通过：

- unique direct opposite consumer；
- missing direct consumer → `UNRESOLVED`；
- duplicate direct consumer → `UNRESOLVED`；
- transferred Face identity conflict → normalization fail-closed。
- candidate Edge 在同一 maximal source component 内可去重；跨不同 maximal components 重复占用 → `UNRESOLVED`；
- 同一 strand/Patch pair 出现重复权威 correspondence → `UNRESOLVED`；
- C4 `+2` 几何相对面不得冒充 Boundary consumer。

回归 artifact：`/private/tmp/hst-phase-c-maximal-chain-regression-20260724-04/`。

## 真实目标结果

`tricky__solid_004__r0p030` 从目标 Operator 重跑并复现：

- 3 raw Edge → 2 normalized Edge；
- raw→normalized exactly-once；
- 两条 normalized Edge 均为 `profile side 1 → opposite side 3`；
- residual 自身 pre-Boolean profile identity 完整；
- 旧 C4 `+2` pairing 的 direct incidence 为 `0`；修正为权威 Patch pair + 相邻 Cutter Face 后已找到真实 candidate Edges；
- 正逆 staging fingerprint 一致；
- source fingerprint unchanged。

用户提供的 Blender Edit Mode 截图确认该位置的对侧 Boolean Edge 实际存在。新增全量 Pipe incidence census 后，Pipe 1 的 561 条 Boundary incidence 只出现 profile side `0/1`，side `2/3` 为零。根因不是 Face ID transfer 丢失，而是 resolver 把 C4 几何相对面 `side 1 → side 3` 错当成了两条 Boundary rails 的配对关系。

当时在该局部 cell 找到的候选配对为同一 strand 的 `StripCorrespondence Patch [1,2]`：Patch 1 / side 1 的两个 normalized records 通过 pre-Boolean `profile_neighbor_face_signatures`，分别直接命中 Patch 2 / side 0 的 Edge `d08fa882…`，以及由 `d08fa882… + 78c620a9…` 组成的 chain。该证据只使用 transferred Face ID → Edge incidence；后来 mixed 遮挡段证明它不能作为通用权威 pairing。

resolver 与 synthetic contract 已改为“strand-scoped Plan Patch pair + 相邻 Cutter Face direct Edge/chain”。fresh target artifact 已找到所有 direct incidence，raw exactly-once、source unchanged、正逆 staging 均通过；但独立 Spec Audit 发现 Edge `d08fa882…` 同时落入两个 normalized consumer chain。全局 candidate Edge exactly-once 门禁已补上，该目标现在正确 fail-closed 为 `OVERLAPPING_DIRECT_OPPOSITE_CONSUMER_CHAIN`。

但正式 Phase C Adapter 尚未接入该 resolver，仍以 `UNPROVEN_PLAN_BOUNDARY_EDGE` fail-closed；因此整体 Phase C 继续保持 `STOP / PROTOTYPE`。正式 runtime、Phase D/E 仍未进入。

曾沿 Pre-Boolean Cutter Profile Lineage 路线实现 maximal-chain pairing：两个共享 endpoint token 的 normalized fragments 被合并为一个 source chain；对侧两条真实 candidate Edges 形成唯一连续 open chain。该结果保留为历史局部证据，不再代表当前主路线；mixed 遮挡段证明 profile-neighbor direct incidence 不完备。

最新 artifact：

- `/private/tmp/hst-phase-c-maximal-chain-real-20260724-05/report.json`
- `/private/tmp/hst-phase-c-maximal-chain-real-20260724-05/phase_c_pre_boolean_profile_lineage.blend`

## Spec Audit

- 首个 maximal-chain 实现独立复审：`P0=0 / P1=0`；只授权 Algorithm/Backend 的只读 `PROTOTYPE` probe Go。
- 目标 3→2 identity 已复现；probe 对 residual identity 漂移有显式 hard Stop 字段。
- pre-Boolean complete Face records 参与 direct consumer 决策。
- `all_maximal_source_chains_resolved` 只接受 `UNIQUE_DIRECT_OPPOSITE_CONSUMER_CHAIN`；Plan port 不能触发本轮 Go。
- `strand_id` 已进入 pairing key。
- `longitudinal_segment_ids` 已进入 maximal source component key；跨 segment 共享 token 不得合并。
- candidate Edge 必须拥有唯一完整 pre-Boolean lineage；无 strand 的 legacy Patch pair 输入直接拒绝。
- maximal source grouping 不得跨 protected Plan port/junction token。
- probe-only 开关隔离完整 lineage；既有 `feature_chamfer_batched_adapter_smoke` 通过。
- synthetic 已覆盖 missing、duplicate、Face identity conflict、C4 `+2` rejection、跨 maximal component overlap、source branch、candidate disconnected/cycle，均 fail-closed。

旧路线当时只达到 Algorithm/Backend 的局部只读 `PROTOTYPE` probe Go。隐藏 Adapter 仍按既有 residual gate `CANCELLED`，正式 runtime/`FINALIZE` 未接入；不得提升为 `INTEGRATED/VERIFIED/ACCEPTED`，Phase C 仍为 `STOP`。

真实目标结果：1 条 maximal source chain（2 个 normalized fragments）唯一对应 1 条 candidate chain（2 条 Edge：`d08fa882…` → `78c620a9…`）；raw/normalized/candidate exactly-once、source unchanged、正逆输入一致。`report.json` SHA-256 为 `01cbc19a9ee837ee4d0ba819a4b7bf73652f863e772eb2174a2918b4426cdb44`，`.blend` SHA-256 为 `b93efbcc9c4f8e4dc56b2d8fb3ced0597d000bc9a65891e28048b557fc55fca0`。

旧路线随后把相同合同只读扩展到 `tricky__solid_004__r0p010` 与 `mixed__extruded_002__r0p030`；当时的“三个 cell 均有 direct witness”门禁现已由 Pre-Delete Groove FaceGraph 门禁取代。隐藏 Adapter runtime 仍未接入。

## 扩展 cell 结果

- `tricky__solid_004__r0p010`：18 raw/normalized Edge 形成 1 条 source open chain；18 条 candidate Edge 形成唯一 open chain，Face coverage 完整、source unchanged、正逆一致，因此该 cell 当时得到旧路线的局部 probe Go。artifact：`/private/tmp/hst-phase-c-maximal-chain-solid004-r0010-20260724-02/report.json`，SHA-256 `4b38afb3972aae3cf842eeff5a35b6506bbbe4f19d844742155842075acdb534`。
- `mixed__extruded_002__r0p030`：71 raw/normalized Edge 形成 1 条 source open chain；仅找到 65 条 candidate Edge，其中 23 个 source Face identity 没有 direct consumer，candidate token graph 也不是唯一 open chain。因此正确保持 `STOP_UNRESOLVED_DIRECT_WITNESS`；source unchanged、正逆一致。artifact：`/private/tmp/hst-phase-c-maximal-chain-mixed-r0030-20260724-03/report.json`，SHA-256 `c784e5c1a73db1a2881fca4ceb830f1e6c507cfb319cd8578dc77cee6999b5b0`。

三表前，实质阻塞已先缩小为 mixed cell 的 23 个 missing direct Face consumers；随后的 unique open-chain 证据已排除按 protected Plan component 再拆分，且禁止用 nearest、坐标或单 Pipe fallback 补齐。

扩展 cell 独立复审为 `P0=0 / P1=0`：确认 `r0p010` 的同一 pre-Boolean Face 被 Boolean 细分为多条连续 Edge 时，只在完整 candidate union 形成唯一 open chain、Face coverage 完整、跨 chain 无重用时才允许 probe Go；正式 runtime、`FINALIZE` 与 `auto_load.py` 均未修改。

mixed 缺口的 complete cutter Face records → Boundary ledger 三表已完成。24 次 unresolved（23 个唯一 source Face identity）在 source open chain 中是连续的第 `28..51` 段；其 48 次 expected pre-Boolean neighbor Face 引用对应 46 个唯一 signatures，全部各有且仅有一条同 Pipe/segment 的完整 Cutter Face record，但这 46 个 signatures 均未出现在 post-Boolean Boundary ledger。作为对照，另 47 段至少有 direct incidence：每段恰有一个 expected neighbor 在 authoritative Patch 3 Boundary scope 可见，另一个不是 Boundary Face；其中 12 段是 UNIQUE，35 段仍有重复候选，不能称为单段 resolved。截图所示的对侧 Edge 仍由同 Pipe/strand/side/segment census 证明确实存在；当前 hard Stop 的精确原因不是“没有生成边”或 normalization，而是这段连续区域缺少可从 pre-Boolean neighbor Face identity 直接传递到那些 Edge 的 incidence。证据：`/private/tmp/hst-phase-c-mixed-face-lineage-transfer-20260724-03/report.json`，SHA-256 `1a762761c4dab09606c2560c7ce1a91919aa0ce74785c8b00954f1ad4f226dbb`。

当时这进一步排除了“complete cutter lineage 根本没生成”，并要求在 `modifier_apply` 后做 output Face→Edge incidence census。该 census 已在下段完成，因此这里不再是待办；Patch 15 仍只能作几何存在性验证，不能升级成 owner。

raw Boolean output Face ID census 已完成：46 个 expected signatures 全部各自保留为 1 个 groove Face，`PHASE_C_CUTTER_FACE_ID_ATTRIBUTE` 传播完整；但 `46/46` 都是 `FACE_ID_ON_NON_BOUNDARY_GROOVE_FACE`，与 source Face 共享的 Edge 数为 0，marked Boundary Edge 数也为 0。因此 Boundary witness/extraction 没有漏掉本应标记的交线，真正不成立的是“这段 source chain 的 profile-neighbor Face 必须直接接触对侧 Boundary Edge”这一假设。对侧 Edge 和 frozen Face ID 都存在，只是该组 neighbor Faces 位于凹槽内部，不能直接证明对侧 consumer。artifact：`/private/tmp/hst-phase-c-mixed-output-face-incidence-20260724-02/report.json`，SHA-256 `c60442b3bb94c8a9cdefaa7a78ffd5d68bb4b4b79331d9aee7e24e805d1015da`。

Plan lineage 表显示目标 strand 只有 `[3,4]` 与 `[3,5]` 两个 StripCorrespondence，Rail 也只有 Patch `3/4/5`，没有 Patch 15 rail、correspondence 或 junction-port incidence。因此 Patch 15 / side 1 Edge 即使在 token graph 中恰好填补缺口，也没有现有 Plan 身份授权，不能成为 Go witness。结合用户确认的实际删除流程，权威下一步已改为 Boolean 后、删除 Groove Faces 前冻结 Groove FaceGraph→两侧 Boundary Edge pairing；不得把 Patch 15、最近 sink、token-only 或单 Pipe当 fallback。
