# Phase 3 — BoundaryGraph / JunctionPort Binding

> 日期：2026-07-22；状态：`PROTOTYPE / STOP`；目标 Operator：`hst.feature_chamfer_gn`。

## 入口与阶段门禁

```text
UI Feature Chamfer GN
→ hst.feature_chamfer_gn
→ PREVIEW / FINALIZE
→ Exact Boolean result
→ authoritative BoundaryGraph / JunctionPort binding
→ existing regular-strip / junction runtime
```

- 用户操作：对 simple / `Solid 44` 与 tricky / `Solid.004` 运行 `PREVIEW → FINALIZE`。
- 预期可见变化：四个 radius cell 不再以 `ambiguous_boundary` 结束；允许暴露后续 Phase 4/5 已知失败家族。
- 自动证据：目标 Operator runtime result、Boundary Edge single-consumption ledger、source fingerprint、固定 `.blend` artifact。
- Go：两个目标对象均消除 `ambiguous_boundary`；每条原 Boundary Edge 恰好消费一次；不重排/插值坐标；source unchanged。
- Stop：跳过 branch、用最近 Pipe/BVH 或 centroid 猜 owner、全局 Fill、放宽阈值，或只修单一 fixture。

## TDD seams

1. Product seam：`bpy.ops.hst.feature_chamfer_gn(action="PREVIEW")` → `FINALIZE`。
2. Backend seam：`bind_boolean_boundary(plan, boolean_mesh, groove_face_indices)` → immutable `FinalizationBinding`。

合成 seam 覆盖 cyclic、open、Y/T/X；真实 fixture 验收始终从目标 Operator 开始。Phase 2 已于 commit `bdc0a5b` 达到 `PROTOTYPE / GO`，因此 Phase 3 可进入 runtime implementation。

## 当前 RED

- simple / `Solid 44`：radius `0.01`、`0.03` 均为 `ambiguous_boundary`，每个失败 BoundaryGraph 含一个 degree-4 Junction。
- tricky / `Solid.004`：radius `0.01` 含三个 degree-4 Junction components；`0.03` 含四个。
- 现有 `_open_boundary()` 在删除 groove Faces 后遇到 degree≠2 立即失败，authoritative binding 尚不可达。

## 本轮 Stop 证据

WIP probe 仅用于验证门禁，已从 production runtime 撤出，未作为 Phase 3 实现提交。

| case | WIP probe 结果 | Boundary Edge | 未分类 Edge |
|---|---|---:|---:|
| simple / `Solid 44` / `0.01` | `junction_boundary_unresolved` | 295 | 0 |
| simple / `Solid 44` / `0.03` | `junction_boundary_unresolved` | 294 | 0 |
| tricky / `Solid.004` / `0.01` | `boundary_binding_incomplete` | 2036 | 10 |
| tricky / `Solid.004` / `0.03` | `boundary_binding_incomplete` | 1999 | 10 |

probe 证明 maximal degree-2 decomposition 与 Edge 单次拓扑消费可行，但没有证明 authoritative ownership：

- 无直接 provenance 的 component 曾把邻接 owner union 赋给每条 Edge，多 owner junction 会被伪装成已分类；
- binding 只读取 `plan_id`，未映射到 plan `FeatureStrand`、`JunctionPort`、`RailChain` 或 `StripCorrespondence`；
- patch runtime 仍由 `_final_boolean_boundary_rails()` 的 BVH 最近 Pipe 路径驱动，新 binding 只是 stats 旁路；
- WIP probe 当时缺少 public binder 的 cyclic/open/Y/T/X contract，Operator gate 也没有锁定精确 2 PASS / 2 fail-closed 结果。

因此本轮没有 authoritative binding artifact；`/tmp/hst_phase3_stop_final` 只保留 WIP probe 诊断，不能作为 Go 证据。

## 下一轮入口

1. 在同一 BMesh 内用 `BMEdge` identity 保留删除槽面前后的 cutter/source provenance，禁止坐标 key。
2. 建立 cutter component → plan `FeatureStrand/JunctionPort` 显式映射；无 owner 或多 owner ambiguity 必须 fail-closed。
3. 让正式 patch runtime 消费 `FinalizationBinding`，不得落回 BVH/centroid owner。
4. public `bind_boundary_graph` 已补 cyclic/open/Y/T/X、dirty-index、重复 Edge fail-closed 与 Junction/Port/Rail 双向引用 contract；下一步扩展为含 owner provenance 的 `bind_boolean_boundary`，再从目标 Operator 验证两个真实对象与两个 radius。

2026-07-22 后续子切片：public `bind_boolean_boundary` 已能在 disposable 同一 BMesh 上，以 deleted cutter Face 的 component-present/owner layer 与 retained source Face 的 patch-present/ID layer，权威绑定 cyclic Rail；缺 owner、known+unknown、multi-owner、缺 patch、未知 Pipe、额外 Boundary、缺预期 Rail、断裂 Rail 均 `boundary_binding_incomplete`。open Rail 因尚无 Boundary endpoint → plan `JunctionPort` provenance，当前明确 fail-closed，未冒充通用 binding；production cutter/source Face producer 已写入 provenance，但 binder handoff 与正式 Operator 验收仍未接入。

Exact Boolean production joined-cutter 双 component smoke 已证明 Blender 5.1.2 会把 cutter Face 的 `component_id + present` 与 source Face 的 `patch_id + present` 传播到结果；这只是 producer 可行性证据。cutter-cutter overlap / multi-owner seam 与正式 runtime handoff 尚未验证，Phase 3 状态不变。

后续 attribute-only probe 进一步证明：Curve endpoint 的 POINT token 可经受控 Even-Thickness GN 传播到 Mesh，并仅凭 token 把端点 cap/sidewall Faces 分类；FACE INT port token 也可经 Exact Boolean 传播，并在删除 groove Faces 前通过 `BMFace → BMVert` incidence 恢复到真实 Boundary vertex。probe 同时证伪了“open plan 必然对应 degree-1 Boundary endpoint”：盲槽 Boundary 仍可能是 degree-2 闭环，所以 port 必须建模为 `(strand endpoint, JunctionPort)` anchor incidence，而不是 Boundary graph endpoint。当前仍未证明相交多 Pipe 的 token namespace、cap 被遮挡后的 sidewall anchor 与 conflicting token 行为；在这些 producer/binder tests 通过前保持 Stop，禁止接正式 runtime。

public binder 已据此补充 plan-local `StrandEndpointPortToken` registry：open strand 的 start/end role 与 plan `JunctionPort` 必须同时在各自 `(Pipe, Patch)` Rail 的 Boundary vertex incidence 中出现；Boundary Rail 本身允许保持 cyclic。缺 anchor、unknown token、wrong Pipe、wrong role、role/port 对调与重复 token registry 均 `boundary_binding_incomplete`。该合成 contract 仍只是 Algorithm/Backend slice；production GN endpoint token producer、Y/T/X overlap 与目标 Operator 尚未接入，Phase 3 继续 Stop。

production Even-Thickness Pipe producer 已用 GN `Curve Endpoint Selection → Store Named Attribute` 写入 start/end POINT token，并在 evaluated Pipe 上 attribute-only 提升为 FACE token，再由 joined cutter 原样复制；production helper smoke 验证两个 token 均存在。该 producer 尚未经过相交多 Pipe Exact Boolean，也尚未在正式 Finalize 中传给 binder；因此仍不能接 runtime 或宣称 open/Y/T/X 完成。

相交 degree-3 production probe 已证明 Collection Exact Boolean 可传播 plan-local component、endpoint token 与 source Patch one-hot Face provenance；但共享 junction 仍产生未归属的 seam Boundary Edges，两个 Rail 也被切成 topology-incompatible fragments。binder 因此稳定返回 `boundary_binding_incomplete`，没有落回 BVH owner。当前证据只达到“authoritative provenance 可达且 fail-closed”，尚未满足 Y/T/X `Boundary Edge consumption=100%`，Phase 3 继续 Stop。

当前状态仅为 `PROTOTYPE / STOP`，未达到 `INTEGRATED`、`VERIFIED` 或 `ACCEPTED`。

## 2026-07-22 Boundary witness probe

结构化 edge diagnostics 已证伪上一轮把 degree-3 production fixture 的两条缺失 Edge
强行解释为 shared `JunctionPort` seam 的方向。两条 Edge 都只有 Pipe 0 的端点 token，
没有共享原点的直接 owner 证据；因此已删除“两条 Pipe 时使用全部 owner”的兜底，继续
`boundary_binding_incomplete`。最新可读 artifact：

`/tmp/hst_boundary_witness_index_probe/feature_chamfer_intersecting_endpoint_provenance.json`

probe 结果：

- Boundary `13` 条，direct/witness consumed `11` 条，未归属仍为 `7/8`；
- Edge `7/8` 的 `candidate_owner_pipe_ids=[0]`，无 compatible shared port；
- endpoint tokens 分别只指向 Pipe 0 `END/START`，不能替代 Boundary owner；
- Exact Boolean source/cutter 交线可在 Boolean 后用同一 Mesh 的 Face incidence 写显式
  EDGE owner/Patch witness；独立 smoke 标记 `8` 条，production degree-3 标记 `11` 条；
- 缺失的两条 Edge 不与任何 cutter-derived Face 相邻，因此仍没有 witness。现有
  Face provenance、endpoint token 与拓扑对其 owner 存在多解，必须 fail-closed。

新增 witness producer 目前只是 `PROTOTYPE` 能力探针，尚未由正式 `_open_boundary()`
或目标 Operator 的 `FinalizationBinding` runtime 消费。真实目标矩阵仍保持 Phase 2
基线分类；`simple / Solid 44` 与 `tricky / Solid.004` 四格仍为
`ambiguous_boundary`。Phase 3 继续 Stop，禁止接 runtime 或进入 Phase 4。

下一条 Go 路径必须先解决 producer 合同：每条预期 Boundary Edge 都要有 direct
cutter/source Face provenance，或明确的 `owner Rail set + JunctionPort + source Patch`
witness；缺失、unknown、duplicate、conflict 全部 fail-closed。只有合成 Y/T/X 与两个
真实目标达到 100% 单次消费后，才允许接入 `hst.feature_chamfer_gn`。

## 2026-07-22 native Intersecting Edges producer probe

Blender 5.1.2 的 native `GeometryNodeMeshBoolean` `EXACT` 已确认公开
`Intersecting Edges` field，并能把每个 sequential Difference stage 的交线写入唯一
EDGE Boolean attribute。production degree-3 Cutter Set 的 per-Pipe probe 得到：

- 最终开放 Boundary `13/13` 条均有且仅有一个 stage witness；缺失 `0`、冲突 `0`；
- stage 0/1 在 closed Mesh 分别保留 `12/11` 条 witness，交集为空；
- source fingerprint 未变化；witness 不依赖坐标、排序或 BVH 最近 owner；
- artifact：`/tmp/hst_phase3_native_witness_delivery_final_retry/feature_chamfer_production_sequential_boolean_witness_probe.json`。

该方案仍被等价性硬门禁挡住：正式 Collection Difference 与 sequential Difference
虽然都有 `21 Vertex / 13 Face`，但 closed Edge 为 `32 / 34`；删除 groove Faces 后
都是 `15 Vertex / 4 Face`，open Edge 为 `18 / 20`，canonical Face/Edge signature 也
不相同。因 roadmap 禁止用未证明等价的 Boolean backend 替换正式结果，本轮只保留
probe-only helper，未修改 `_apply_difference()`、`build_pipe_chamfer()` 或目标 Operator。

同时新增 plan-local `BoundaryWitness` fail-closed 合同，验证 owner Rail 非空、Rail→
source Patch、Rail→JunctionPort incidence、multi-Rail 必须显式 port，以及 registry/Edge
duplicate、unknown、missing、conflict。合同与 producer capability 均为 `PROTOTYPE`；
当前结论仍是 `STOP`，不得进入 Phase 4。

后续同拓扑 probe 发现更合适的 backend seam：把 production overlap-safe joined Cutter
objects 同时接入**同一个** native `GeometryNodeMeshBoolean` 的 multi-input `Mesh 2`，其
结果与正式 Collection Modifier 在 closed/open canonical topology 上完全等价；经过与
`_open_boundary()` 相同的 degenerate cleanup 后，`Intersecting Edges` 覆盖 `12/12`
Boundary Edge，source unchanged。artifact：
`/tmp/hst_multi_input_boolean_witness_clean/feature_chamfer_multi_input_boolean_witness_probe.json`。

这只解决“哪些 Edge 是正式 Boolean 交线”，尚未解决每条 Edge 的 plan-local
`Pipe/Rail/Patch/JunctionPort` assignment；另外把 cutter 输入 EDGE one-hot attribute
交给 Collection Modifier 仅传播到 `2/12`，不能作为 owner ledger。故当前仍保持
`PROTOTYPE / STOP`，下一步必须在 multi-input node 内产生 per-cutter/per-Pipe field，
并从目标 Operator 对两个真实对象验证，才能接 runtime。
