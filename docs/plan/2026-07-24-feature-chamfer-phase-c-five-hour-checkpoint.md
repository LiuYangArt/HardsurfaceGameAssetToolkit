# Feature Chamfer Phase C — 5 小时 Checkpoint

日期：2026-07-24
状态：`WIP CHECKPOINT / GLOBAL PROTOTYPE / PHASE C STOP`

## 1. 非技术结论

方向的大原则是正确的：先确认每段边真正属于哪条倒角，再调用 Blender 原生 Bridge，遇到身份不明的边就停下，不能靠“看起来最近”去猜。这个选择避免了模型表面看似成功、实际串错槽或以后随机坏掉。

当前不是 Blender 不会 Bridge。真实 5 对 3 边已经成功生成 8 个面，宽度和输入边消费也通过。真正卡点是多条 Pipe 相交并做完 Boolean 后，少数边只剩“一边”，原本配对的另一边被切掉或替换了；现有数据无法可靠判断它们应该继续 Bridge、留给交叉口，还是属于 Boolean 碎片。

因此当前路线应保留，但 immediate implementation 必须转向 `ResidualOwnershipGraph`：先从所有 independent staging 全局恢复这些剩余边的身份，再允许 Bridge。继续在旧局部 matching 上打补丁，成功率会下降并重新引入假绿。

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

## 5. 用户可手动帮助

最有价值的不是重复测试普通 Bridge，而是做一次产品语义判定：打开
`/tmp/hst-phase-c-stop-critical-cluster-20260724-01/tricky__solid_004__r0p030/phase_c_regular_core.blend`，观察剩余三段边在真实模型上更像：

1. 应继续形成倒角面的普通槽边；
2. 应留给 Pipe 交叉口/terminal 的开口边；
3. Boolean 产生、允许丢弃的碎片。

这个判断不能替代自动 provenance，但能决定 pivot 要证明哪种产品语义。若不方便手测，也不阻塞只读 graph probe；当前需要的实质决定是：是否授权按 residual ownership pivot 开启下一轮实现。

## 6. 下一步（需授权）

先只实现只读 `ResidualOwnershipGraph` probe 和 synthetic occluded-opposite-face 合同，不改正式 producer。三个失败 cell 都能获得唯一直接 witness 才 GO；否则继续 STOP 并返回更具体的产品选择，不进入 Phase D/E。
