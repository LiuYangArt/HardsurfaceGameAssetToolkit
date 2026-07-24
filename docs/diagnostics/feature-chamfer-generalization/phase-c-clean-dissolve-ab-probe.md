# Phase C Clean/Dissolve A/B Probe

日期：2026-07-24  
状态：`PROTOTYPE / CLEAN PREPROCESS VALID / GRAPH WITNESS REQUIRED / PHASE C STOP`

## 目标入口

```text
Feature Chamfer GN
→ hst.feature_chamfer_gn(action=PREVIEW)
→ hst.experimental_feature_chamfer_batched_finalize(debug_stage=PHASE_C_REGULAR_CORE)
→ independent staging copy
→ read-only clean/dissolve A/B artifacts
```

目标为 `tricky__solid_004__r0p030`。正式 runtime、正式 `FINALIZE`、Phase D/E 和 source Mesh 均未修改。

## A/B 结果

- A：4 Vertex / 3 raw Edge，总长 `0.187935362635`。
- 两个 degree-2 内点均有同一 Pipe 1 / Patch 1 / Rail provenance、完整 direct lineage，且没有 endpoint/port token。
- 内点 `f717…` 为 `0.227749°`、到 chord `3.2674e-6`，满足本 probe 的宽松上界 `0.5° / 1e-5`；内点 `50d9…` 为 `7.509917° / 1.05244e-4`，被拒绝。
- B：真实 `bmesh.ops.dissolve_verts()` 仅移除 `f717…`，得到 3 Vertex / 2 normalized Edge。
- normalized 总长 `0.187935356892`，长度差 `-5.74273e-9`；实际 BMesh geometry 与保存的 normalized lineage 一致。
- 3 个 raw Edge 均 exactly-once 映射；terminal token、空 port token 集、Pipe/Patch/Rail provenance、已移除 token lineage 和 source fingerprint 均保持。

## Regular consumer 判定

两个 normalized Edge 需要的 opposite profile Face signatures 分别为：

- `ab75b54a…`；
- `ab75b54a…` 与 `e10b8c9b…`。

在 2115 条 Boundary Edge 的完整 independent staging universe 中，两者的 direct opposite Boundary witness 数量均为 `0`。probe 没有使用 nearest、坐标匹配、synthetic owner 或 synthetic port。

结论：近共线碎点确实能解释 3 Edge 中的一次多余分段，但 dissolve 后仍无法独立恢复 regular consumer。原报告的 `clean_route_go=false` 只表示“clean 单独不足以让 Phase C GO”，不应解释为 clean 本身无用。用户检查 `.blend` 后确认被移除点正对应原蓝色问题区域；因此 constrained normalization 保留为 pre-Boolean profile lineage resolver 的预处理，resolver 消费 normalized chain，同时保留 raw → normalized lineage。

下一阶段合同：

```text
raw fragmented Boundary Edge
→ constrained normalization（已证明有用）
→ pre-Boolean profile lineage（恢复 opposite-side ownership）
→ regular consumer
```

## Artifacts

- 报告：`/private/tmp/hst-phase-c-clean-ab-probe-20260724-05/report.json`
- 可检查 Blender 文件：`/private/tmp/hst-phase-c-clean-ab-probe-20260724-05/phase_c_clean_ab_probe.blend`
- fresh target baseline：`/private/tmp/hst-phase-c-clean-ab-input-20260724-01/`
- probe 脚本：`tools/probe_feature_chamfer_phase_c_clean_ab.py`

SHA-256：

- `report.json`: `c5816d4307990187ca5907609e4354e65c4808d99c323f5fab8750c19c76c5b1`
- `phase_c_clean_ab_probe.blend`: `eb340d08b2203d9910861b7a5f99a8e32d566ce5302413448970643b996e6bc7`

## Independent Spec Audit

- diff 未修改正式 runtime path、`auto_load.py` 或 `FINALIZE`；新增实现仅是只读 probe tool 与结果文档。
- 证据从目标 PREVIEW → Phase C Adapter 开始，而非离线 builder；Adapter 以同三条 Edge 和 `UNPROVEN_PLAN_BOUNDARY_EDGE` fail-closed，A/B 使用 forward/reverse independently-built staging 且 ledger fingerprint 一致。
- raw → normalized lineage、几何、关键 token、Pipe/Patch/Rail provenance 和 exactly-once 合同均有直接 JSON 字段。
- direct witness 缺失触发计划规定的 hard Stop；未越级进入 Phase D/E，也未把 `.blend` 可打开误报为 Operator/Product 验证。
- 当前状态保持 `PROTOTYPE`，不是 `INTEGRATED/VERIFIED/ACCEPTED`。
