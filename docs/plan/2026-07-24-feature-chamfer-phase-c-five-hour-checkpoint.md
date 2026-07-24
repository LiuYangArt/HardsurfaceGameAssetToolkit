# Feature Chamfer Phase C — 5 小时 Checkpoint

日期：2026-07-24
状态：`CLEAN A/B USEFUL / PRE-BOOLEAN PROFILE LINEAGE AUTHORIZED / GLOBAL PROTOTYPE / PHASE C STOP`

## 1. 非技术结论

方向的大原则是正确的：先确认每段边真正属于哪条倒角，再调用 Blender 原生 Bridge，遇到身份不明的边就停下，不能靠“看起来最近”去猜。这个选择避免了模型表面看似成功、实际串错槽或以后随机坏掉。

当前不是 Blender 不会 Bridge。真实 5 对 3 边已经成功生成 8 个面，宽度和输入边消费也通过。目标 residual 已知属于唯一 Pipe/Patch/Rail；真正卡点是 Boolean 后预期的对侧 profile Face 没有可见 Boundary Edge，因而无法证明应和哪条 Edge 配对补面。局部只有一条 Pipe 也不能替代 profile-side/opposite-side 身份。

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
- 推荐 pivot 能解释三个失败 cluster：`中高（约 70%）`。它能提供当前缺失的全局身份信息，但仍可能证明某些相对边已被 Boolean 永久抹除。
- 完成 Phase C 并通过新鲜 14×3：`中等（约 55%）`。主要不确定性是残余边是否都能从现有 staging/Plan 得到唯一直接 witness。
- 完成 Phase C→D→E 整个正式产品：`中低（约 40%）`。Phase D 的多洞 assembly/junction closure 尚未实现，风险不能用 Phase C 进展抵消。

这些置信度不是工时比例。当前大约完成了 Phase C 基础设施和能力验证的 60%，但 Phase C gate 仍是 0/1：只要关键残余没有唯一归属，就不能进入下一阶段。

## 5. 用户观察结论

用户已检查 A/B `.blend`：被清理的近共线点正对应此前蓝色问题区域，且该区域视觉上只有一条 Pipe cutter 经过、切口简单。该观察支持保留 normalization，也支持把所有权判断前移到 cutter 与 Boolean 交线；它不能单独替代 opposite-side direct witness。

## 6. 已完成的路线选择

clean/dissolve A/B 已完成并证明 normalization 有用，但不能单独恢复 opposite consumer。后续权威执行计划已收敛到 `docs/plan/2026-07-24-feature-chamfer-phase-c-residual-ownership-pivot.md` 的 pre-Boolean profile lineage 路线。

## 7. Clean/Dissolve A/B 结果

`tricky__solid_004__r0p030` 的新鲜 PREVIEW → independent staging probe 已完成。A 组为 4 Vertex / 3 Edge；按 probe-only 的严格门禁，两个 degree-2 内点中只有一个满足共线条件（`0.227749°`，到 chord `3.2674e-6`），B 组通过真实 `bmesh.ops.dissolve_verts()` 得到 3 Vertex / 2 Edge。几何容差、terminal/port token、Pipe/Patch/Rail provenance、raw Edge → normalized Edge exactly-once lineage 和 source unchanged 均通过。

但 B 组两个 normalized Edge 的 direct opposite Boundary witness 都是 `0`。因此碎点会造成一次可约束的分段合并，却不是 regular consumer 缺失的充分根因。用户检查 `.blend` 后确认被清理点正对应原蓝色问题区域；结论修正为：保留 constrained normalization，让后续 pre-Boolean profile lineage resolver 消费 normalized chain，并持续保存 raw → normalized lineage。clean 单独不能触发 Phase C GO，也暂不接入正式 runtime。

证据与审计：`docs/diagnostics/feature-chamfer-generalization/phase-c-clean-dissolve-ab-probe.md`。

## 8. 下一步（已授权）

从目标 PREVIEW → Phase C Adapter 做只读 pre-Boolean profile lineage probe：为 cutter Face 冻结 Pipe/profile side/opposite side/longitudinal segment，并用 post-Boolean Face→Edge incidence 找对侧 chain。几何接触只作验证，不生成 owner；旧 tracked Boolean 只复用“Boolean 前写 provenance”的原则，不恢复单 Pipe fallback 或距离评分。

目标 cell 获得唯一 direct opposite consumer 前，Phase C 继续 STOP，不修改正式 runtime/`FINALIZE`，不进入 Phase D/E。
