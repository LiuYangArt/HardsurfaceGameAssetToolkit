# Feature Chamfer Phase C — 5 小时 Checkpoint

日期：2026-07-24
状态：`HISTORICAL CHECKPOINT / SUPERSEDED BY PRE-BOOLEAN MAXIMAL-CHAIN PLAN / PHASE C STOP`

> 2026-07-24 更新：本文件保留五小时节点的历史证据。后续权威状态与执行门禁以 `2026-07-24-feature-chamfer-phase-c-residual-ownership-pivot.md` 为准；下文“对侧 Edge 不可见”的旧判断已被用户截图和 fresh Face→Edge incidence census 推翻。

## 1. 非技术结论

方向的大原则是正确的：先确认每段边真正属于哪条倒角，再调用 Blender 原生 Bridge，遇到身份不明的边就停下，不能靠“看起来最近”去猜。这个选择避免了模型表面看似成功、实际串错槽或以后随机坏掉。

当前不是 Blender 不会 Bridge。真实 5 对 3 边已经成功生成 8 个面，宽度和输入边消费也通过。用户截图与后续 fresh census 已确认对侧 Boolean Edge 存在；旧卡点来自把 C4 几何相对面误当 Boundary rail pairing。修正后已找到真实对侧 Edge，当前卡点是逐 fragment 配对导致共享 Edge 重复占用，需要改为整段对整段的 maximal-chain pairing。

因此 immediate implementation 改为把判断前移：Boolean 前冻结 cutter 的 Pipe/profile-side/opposite-side/longitudinal-segment 身份，Boolean 后用 Face→Edge incidence 恢复对侧 consumer；constrained normalization 保留为中间步骤。继续在 post-Boolean 局部形状上猜 matching 会重新引入假绿。

## 2. 已完成

- 正式 Preview/Phase A、独立分批 Cut/Phase B 保持 GO；正式 FINALIZE 未修改。
- 新增 ownership-driven `RegularBridgeJob`、全局 claim preflight、job-local Blender `bridge_loops`、Face witness、source unchanged/rollback 保护。
- synthetic open 5-vs-3、cyclic rotation/reversal、duplicate claim、token conflict、zero-length connector 合同通过。
- 真实 `Solid.004 r0.03` 的 L5/R3 成功：8 Faces、8/8 input witness、width inlier 1.0。
- runner 增加 stale/partial/fake-green、Blender backend、claim、Fill=0、final output=null 等门禁。
- 独立审计发现的“无 topology witness 仍配对”“合成 port witness”“macro handoff 假绿”已按 STOP 语义收紧；旧 distance/DP 文本仍是不可达历史代码，后续应单独清理。

## 3. 当前卡点和证据

三个关键 cell 均 fail-closed，source 没被改坏：

| Cell | 未可靠归属的 Edge | 总长度 | 结果 |
|---|---:|---:|---|
| `tricky__solid_004__r0p030` | 3 | 0.187935 | L5/R3 已成功，但仍有单侧剩余 |
| `tricky__solid_004__r0p010` | 18 | 0.181906 | 无法证明完整左右配对 |
| `mixed__extruded_002__r0p030` | 71 | 1.026475 | 交叉区剩余身份不足 |

证据目录：`/tmp/hst-phase-c-stop-critical-cluster-20260724-01/`。完整 regression baseline 为 139/142；其中两个本轮 helper failure 已定向修复通过，剩余一个是既有 mixed 正式 FINALIZE 产品回归。由于审计后代码又有改动，该全量结果只作 baseline，不能作为当前 checkpoint 的 GO 证据。

## 4. 方向与成功率评估

- 方向正确性：`高（约 85%）`。原生 Bridge + direct ownership + fail-closed 与产品语义一致，且已排除“Blender 不支持 unequal rails”这个错误假设。
- 推荐 pivot 能解释三个失败 cluster：`中高（约 70%）`。目标 cell 的相对边已确认存在；剩余风险是其他 cell 是否也能得到唯一、连通且全局 exactly-once 的 maximal consumer chain。
- 完成 Phase C 并通过新鲜 14×3：`中等（约 55%）`。主要不确定性是残余边是否都能从现有 staging/Plan 得到唯一直接 witness。
- 完成 Phase C→D→E 整个正式产品：`中低（约 40%）`。Phase D 的多洞 assembly/junction closure 尚未实现，风险不能用 Phase C 进展抵消。

这些置信度不是工时比例。当前大约完成了 Phase C 基础设施和能力验证的 60%，但 Phase C gate 仍是 0/1：只要关键残余没有唯一归属，就不能进入下一阶段。

## 5. 用户观察结论

用户已检查 A/B `.blend`：被清理的近共线点正对应此前蓝色问题区域，且该区域视觉上只有一条 Pipe cutter 经过、切口简单。该观察支持保留 normalization，也支持把所有权判断前移到 cutter 与 Boolean 交线；它不能单独替代 opposite-side direct witness。

## 6. 已完成的路线选择

clean/dissolve A/B 已完成并证明 normalization 有用，但不能单独恢复 opposite consumer。后续权威执行计划已收敛到 `docs/plan/2026-07-24-feature-chamfer-phase-c-residual-ownership-pivot.md` 的 pre-Boolean profile lineage 路线。

## 7. Clean/Dissolve A/B 结果

`tricky__solid_004__r0p030` 的新鲜 PREVIEW → independent staging probe 已完成。A 组为 4 Vertex / 3 Edge；按 probe-only 的严格门禁，两个 degree-2 内点中只有一个满足共线条件（`0.227749°`，到 chord `3.2674e-6`），B 组通过真实 `bmesh.ops.dissolve_verts()` 得到 3 Vertex / 2 Edge。几何容差、terminal/port token、Pipe/Patch/Rail provenance、raw Edge → normalized Edge exactly-once lineage 和 source unchanged 均通过。

当时 B 组按错误的 C4 `+2` pairing 计算，两个 normalized Edge 的 witness 都是 `0`；后续已确认这是语义错误，不代表 Boolean 缺边。仍保留 constrained normalization 与 raw → normalized lineage；新 resolver 使用权威 partner Patch 和相邻 Cutter Face incidence，并继续在 maximal-chain 层解决重复占用。

证据与审计：`docs/diagnostics/feature-chamfer-generalization/phase-c-clean-dissolve-ab-probe.md`。

## 8. 下一步（已授权）

继续从目标 PREVIEW → Phase C Adapter 做只读 pre-Boolean profile lineage probe：冻结 Cutter Face 身份，用 post-Boolean Face→Edge incidence 找真实 partner Patch Boundary；再把连续 normalized fragments 合成 maximal source chain，与唯一连续 candidate chain 整体配对。几何接触只作验证，不生成 owner；不恢复单 Pipe fallback 或距离评分。

目标 maximal source chain 获得唯一、全局 exactly-once 的 direct consumer chain 前，Phase C 继续 STOP，不修改正式 runtime/`FINALIZE`，不进入 Phase D/E。
