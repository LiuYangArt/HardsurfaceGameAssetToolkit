# Feature Chamfer Phase C — Residual Ownership Pivot

日期：2026-07-24
状态：`RECOMMENDED / USER DECISION PENDING / PHASE C STOP / GLOBAL PROTOTYPE`

## 1. Stop 事实

- 目标入口仍是 hidden `PHASE_C_REGULAR_CORE` Adapter；正式 `hst.feature_chamfer_gn(FINALIZE)` 未修改，Phase D/E 未开始。
- synthetic open 5-vs-3、cyclic permutation/reversal、claim collision、token conflict、rollback 与严格 zero-length connector 合同通过；derived Edge 当前只有 endpoint tokens，没有权威 Plan port witness，因此不能发布为已验证 port。
- `tricky__solid_004__r0p030` 的真实 L5/R3 job 使用一次 `bmesh.ops.bridge_loops()` 生成 8 Faces；8/8 input Edge 有 Face witness，width inlier `1.0`，最大误差 `0.00498009`。
- 同 cell 随后 fail-closed：patch 1 rail 仍有 3 条 Edge（长度 `0.0287845 / 0.000828165 / 0.158323`，总长 `0.187935`）没有 regular consumer 或结构化 handoff。
- cutter `PROVEN_C4_PIPE` witness 对其中两条 Edge给出 opposite Face signature，但当前 staging Boundary universe 没有对应相对 Face；第三条也没有完整 topology record。它们不能由 distance、nearest、宽度 trim 或扩大 setback 合法配对。
- `tricky__solid_004__r0p010` 与 `mixed__extruded_002__r0p030` 同样以 `UNPROVEN_PLAN_BOUNDARY_EDGE` fail-closed，分别留下 18/71 条 Edge。

证据：`/tmp/hst-phase-c-stop-critical-cluster-20260724-01/results.json` 及各 cell 的 `phase_c_regular_core.blend`、PNG、ledger/diagnostics。

## 2. 根因边界

当前 producer 只能在同一 Plan atom 内，以 direct topology 证明完整左右 rail pair。Boolean 会把某些 profile Face 的相对 Boundary 全部遮挡或替换；因此 subtraction 后出现单侧 macro residual。它不是 Blender Bridge 能力问题，也不是允许交给 terminal/junction 的 port：没有相对 Face/Plan port witness，且长度远超 zero-length connector 阈值。

## 3. 推荐 Pivot

在继续 Phase C 前新增只读 `ResidualOwnershipGraph` 设计门禁：

1. 从所有 independent staging（不是当前 correspondence 的局部视图）建立 `cutter pipe/profile ring/face/longitudinal adjacency → Boundary Edge` 图。
2. 先全局减去已通过 preflight 的 RegularBridgeJob claims 与 frozen setback proofs。
3. 对余下 maximal token-connected subchains，只允许三种结果：唯一相对 Face path、唯一 Plan port incidence、或 `UNRESOLVED`；缺失相对 Face不得合成 rail。
4. 用 synthetic occluded-opposite-face fixture 先证明图合同；然后只读重跑三个失败 cells。只有三者 residual 全部获得 direct witness，才可修改正式 producer。
5. producer 修改后重新从 Step 1 开始，按 cluster 逐级过门；完整 14×3 与独立 Spec Audit 仍是 Phase C GO 的必要条件。

## 4. 明确禁止

- 不恢复 `_rail_pair_score`、nearest、cyclic DP/trim/zipper、坐标误差焊接或 fixture 特判。
- 不把 macro residual 标成 port/setback，不允许 runner allowlist 掩盖 regular Edge。
- 不进入 Phase D Fill/product assembly，不接入正式 FINALIZE。

## 5. 当前交付状态

`Algorithm/Backend: PROTOTYPE`；`Operator: NOT INTEGRATED`；`Visual/Product: NOT VERIFIED`。本轮 hard Stop 已执行，等待用户决定是否授权上述 pivot 的新一轮实现。

独立 Spec Audit 还发现三条假绿风险：无 direct topology witness 时只凭同一 Plan component 配对、过宽 handoff allowlist、由 endpoint token 合成虚假 port witness。checkpoint 已删除前两类 runtime 假证据并收紧 macro handoff 门禁；完整回归证据因代码随后有改动而只记为历史 baseline，pivot 实现后必须重新跑新鲜全量测试。
