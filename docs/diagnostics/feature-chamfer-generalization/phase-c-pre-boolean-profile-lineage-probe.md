# Phase C Pre-Boolean Profile Lineage Probe

日期：2026-07-24
状态：`PROTOTYPE / TARGET 3→2 REPRODUCED / OVERLAPPING CONSUMER CHAINS / PHASE C STOP`

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
- candidate Edge 跨 normalized records 重复占用 → `UNRESOLVED`；
- 同一 strand/Patch pair 出现重复权威 correspondence → `UNRESOLVED`；
- C4 `+2` 几何相对面不得冒充 Boundary consumer。

回归 artifact：`/private/tmp/hst-phase-c-boundary-pairing-regression-20260724-08/`。

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

下一步保持同一 Pre-Boolean Cutter Profile Lineage 主路线：先将共享 endpoint token、完整 source lineage 与同一 Plan component 的连续 normalized fragments 合并为 maximal source chain，再验证对侧 candidate Edges 构成唯一连续 chain。整条 chain 配对通过前不接入正式 runtime。

最新 artifact：

- `/private/tmp/hst-phase-c-boundary-pairing-real-20260724-04/report.json`
- `/private/tmp/hst-phase-c-boundary-pairing-real-20260724-04/phase_c_pre_boolean_profile_lineage.blend`

## Spec Audit

- 目标 3→2 identity 已复现；probe 对 residual identity 漂移有显式 hard Stop 字段。
- pre-Boolean complete Face records 参与 direct consumer 决策。
- `all_normalized_edges_resolved` 只接受 `UNIQUE_DIRECT_OPPOSITE_CONSUMER`，Plan port 不能触发本轮 Go。
- `strand_id` 已进入 pairing key。
- probe-only 开关隔离完整 lineage；既有 `feature_chamfer_batched_adapter_smoke` 通过。

未通过 probe 门槛：两个 normalized Edge 的 direct candidate chain 重叠消费同一真实 Edge。不得提升为 `INTEGRATED/VERIFIED/ACCEPTED`，Phase C 仍为 `STOP`。
