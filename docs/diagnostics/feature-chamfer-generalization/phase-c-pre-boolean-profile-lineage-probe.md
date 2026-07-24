# Phase C Pre-Boolean Profile Lineage Probe

日期：2026-07-24
状态：`PROTOTYPE / MAXIMAL-CHAIN PROBE GO / PHASE C STOP`

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

## 实现合同

- Boolean 前冻结 `Pipe / strand / profile side / opposite side / longitudinal segment / port incidence`。
- Boolean 后只通过 transferred cutter Face identity 与实际 Boundary Edge incidence 建立候选。
- consumer 只允许同 `Pipe + strand + authoritative Plan Patch pair + longitudinal segment` 上，由相邻 Cutter Face direct incidence 唯一证明的 Edge/chain；C4 `opposite_profile_side` 只作几何诊断。
- 不沿 longitudinal graph 查找最近 sink，不使用 nearest/BVH/坐标、单 Pipe fallback、synthetic owner/port。
- constrained normalization 仅合并完整 lineage 一致的近共线 degree-2 fragment，并保留 raw→normalized exactly-once。

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

真实权威配对为同一 strand 的 `StripCorrespondence Patch [1,2]`：Patch 1 / side 1 的两个 normalized records 通过 pre-Boolean `profile_neighbor_face_signatures`，分别直接命中 Patch 2 / side 0 的 Edge `d08fa882…`，以及由 `d08fa882… + 78c620a9…` 组成的 chain。该证据只使用 transferred Face ID → Edge incidence；没有 nearest/BVH/coordinate。

resolver 与 synthetic contract 已改为“strand-scoped Plan Patch pair + 相邻 Cutter Face direct Edge/chain”。fresh target artifact 已找到所有 direct incidence，raw exactly-once、source unchanged、正逆 staging 均通过；但独立 Spec Audit 发现 Edge `d08fa882…` 同时落入两个 normalized consumer chain。全局 candidate Edge exactly-once 门禁已补上，该目标现在正确 fail-closed 为 `OVERLAPPING_DIRECT_OPPOSITE_CONSUMER_CHAIN`。

但正式 Phase C Adapter 尚未接入该 resolver，仍以 `UNPROVEN_PLAN_BOUNDARY_EDGE` fail-closed；因此整体 Phase C 继续保持 `STOP / PROTOTYPE`。正式 runtime、Phase D/E 仍未进入。

已继续沿同一 Pre-Boolean Cutter Profile Lineage 主路线实现 maximal-chain pairing：两个共享 endpoint token 的 normalized fragments 被合并为一个 source chain；对侧两条真实 candidate Edges 形成唯一连续 open chain。全程只使用稳定 token、权威 Patch pair 与 pre/post-Boolean Face→Edge incidence，不使用 nearest/BVH/coordinate 生成 owner。

最新 artifact：

- `/private/tmp/hst-phase-c-maximal-chain-real-20260724-05/report.json`
- `/private/tmp/hst-phase-c-maximal-chain-real-20260724-05/phase_c_pre_boolean_profile_lineage.blend`

## Spec Audit

- 终局独立复审：`P0=0 / P1=0`；只授权 Algorithm/Backend 的只读 `PROTOTYPE` probe Go。
- 目标 3→2 identity 已复现；probe 对 residual identity 漂移有显式 hard Stop 字段。
- pre-Boolean complete Face records 参与 direct consumer 决策。
- `all_maximal_source_chains_resolved` 只接受 `UNIQUE_DIRECT_OPPOSITE_CONSUMER_CHAIN`；Plan port 不能触发本轮 Go。
- `strand_id` 已进入 pairing key。
- `longitudinal_segment_ids` 已进入 maximal source component key；跨 segment 共享 token 不得合并。
- candidate Edge 必须拥有唯一完整 pre-Boolean lineage；无 strand 的 legacy Patch pair 输入直接拒绝。
- maximal source grouping 不得跨 protected Plan port/junction token。
- probe-only 开关隔离完整 lineage；既有 `feature_chamfer_batched_adapter_smoke` 通过。
- synthetic 已覆盖 missing、duplicate、Face identity conflict、C4 `+2` rejection、跨 maximal component overlap、source branch、candidate disconnected/cycle，均 fail-closed。

当前只达到 Algorithm/Backend 的只读 `PROTOTYPE` probe Go。隐藏 Adapter 仍按既有 residual gate `CANCELLED`，正式 runtime/`FINALIZE` 未接入；不得提升为 `INTEGRATED/VERIFIED/ACCEPTED`，Phase C 仍为 `STOP`。

真实目标结果：1 条 maximal source chain（2 个 normalized fragments）唯一对应 1 条 candidate chain（2 条 Edge：`d08fa882…` → `78c620a9…`）；raw/normalized/candidate exactly-once、source unchanged、正逆输入一致。`report.json` SHA-256 为 `01cbc19a9ee837ee4d0ba819a4b7bf73652f863e772eb2174a2918b4426cdb44`，`.blend` SHA-256 为 `b93efbcc9c4f8e4dc56b2d8fb3ced0597d000bc9a65891e28048b557fc55fca0`。

下一步仍是只读验证：把相同合同扩展到 `tricky__solid_004__r0p010` 与 `mixed__extruded_002__r0p030` 的全部 residual components。三个失败 cell 全部有唯一 direct witness 前，不接入隐藏 Adapter runtime。
