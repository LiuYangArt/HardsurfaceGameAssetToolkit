# Feature Chamfer 固定两阶段端到端验证结果

日期：2026-07-31
状态：`PROTOTYPE / CORRECTNESS PASS / PERFORMANCE STOP / FORMAL ENTRY RECOVERED`

> 2026-07-31 后续结果：本文的性能 `STOP` 已被批量安全检查优化解除。新的正式集成与验证证据见
> [`2026-07-31-feature-chamfer-fixed-two-stage-batched-validation-result.md`](2026-07-31-feature-chamfer-fixed-two-stage-batched-validation-result.md)。本文保留为优化前基线，不再代表当前正式 runtime。

## 1. 验证范围

- 固定样本：Mixed / `Extruded.002` / Radius `0.01` / Keep Cutter `false`，Blender 5.1.2。
- 保留现有 FeatureGraph、Plan、Curve/Cutter GN 和未修改的 Bridge/Fill。
- 旁路仅把 Boolean 及其后置身份链改为：固定 raw Boolean 与 Boundary 输出 → Python NumPy 物化 236 层身份 → 固定 Surface 删除。
- 旧正式结果作为 oracle；不使用图片、空间猜测、多次 Boolean、fixture 特判或 silent fallback。

## 2. 结果等价门槛 — `PASS`

三次独立运行均得到同一正式产品结果：

| 项目 | 旁路结果 | 冻结 oracle |
|---|---:|---:|
| 规范化 fingerprint | `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107` | 相同 |
| Vertex / Edge / Face | 3922 / 8054 / 4134 | 相同 |
| Chamfer Face | 3454 | 相同 |
| 初始 Boundary | 3872 | 3872 |
| Bridge jobs / Faces | 80 / 3437 | 80 / 3437 |
| Fill jobs / Faces | 12 / 28 | 12 / 28 |
| 最终 Boundary / non-manifold / zero-area / self-intersection | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

source Mesh、Object 状态和正式一步式事务清理均保持不变。证明已经补齐此前缺少的“固定两阶段结果交给未修改 Bridge/Fill”的完整组合证据；这条架构在业务语义上可行。

## 3. 完整性能门槛 — `STOP`

三次完整一步式运行：

| 运行 | 总耗时 | Preview/两阶段准备 | Bridge/Fill | raw Boolean | Python 身份物化 |
|---|---:|---:|---:|---:|---:|
| 1 | 3.406s | 0.624s | 2.773s | 0.073s | 0.0148s |
| 2 | 3.424s | 0.642s | 2.773s | 0.069s | 0.0140s |
| 3 | 3.440s | 0.651s | 2.780s | 0.087s | 0.0140s |

- 中位数 `3.424s`，最大值 `3.440s`；超过完整产品门槛中位 `≤2.00s`、最大 `≤2.50s`。
- 相比旧正式入口的 `4.635s` 明显下降，但按硬门槛仍不能集成。
- Boolean 后动态身份整理已从旧 Preview 的主要成本降到约 `0.014s`；当前主耗时明确转移到未修改 Bridge/Fill，约 `2.77s`。

## 4. 集成决定与恢复

- 该路径没有接入正式入口，状态保持 `PROTOTYPE / STOP`。
- 用于端到端测量的临时正式入口修改已全部撤回；正式 runtime 仍是上一版已验证的 Python Boolean 前 producer + Boolean Pro 后置动态整理。
- 这次恢复只属于 `RECOVERY`，不记为性能进度；没有把正确但超预算的路径包装为完成。
- 未运行 10-cell、完整回归、GUI Undo/Redo 或视觉验收，因为 Mixed 性能硬门槛未通过。

## 5. 新的瓶颈判断与下一步

已不需要继续怀疑固定 Boolean、Python 236 层身份或固定 Surface 的可行性。后续唯一有意义的性能主线是独立剖析和优化现有 Bridge/Fill：

1. 冻结本次 80 个 Bridge job、12 个 Fill job 及最终 oracle；
2. 分离每个 job 的准备、匹配、BMesh 操作和全局健康检查耗时；
3. 优先消除重复的全 Mesh 扫描、重复自交检测和重复索引/邻接重建；
4. 在独立 prototype 中同时组合固定两阶段上游，先把完整 Mixed 冷运行压到 2 秒内；
5. 只有结果等价与完整性能同时通过，才把两部分一起接入正式入口。

## 6. Evidence

- 机器结果：`tests/artifacts/feature_chamfer_fixed_two_stage_mixed_gate_r2/results.json`
- 三次运行均保存 agent 可读的结构化结果；没有生成、渲染或判断图片。
- 失败的首次装配轮次因 Preview Curve owner 识别仍依赖旧 wrapper 节点而被拒绝，修正生命周期合同后重跑；该轮不参与结论。
