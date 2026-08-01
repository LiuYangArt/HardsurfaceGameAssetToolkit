# Feature Chamfer FeatureGraph 分段性能验证结果

日期：2026-08-01
状态：`VERIFIED / PASS / IMPLEMENTATION NOT RUN`

## 结论

固定 Mixed / `Extruded.002` / Radius `0.01` / 正式 UI `hst.feature_chamfer_gn` 的未插桩 oracle、低开销插桩和三轮正式 Operator 均完成。FeatureGraph groups、vertex matching、ChamferPlan、最终 order-independent Mesh fingerprint/计数/健康性逐轮完全一致，第一差异为“无”。

唯一达到双重门槛的候选是 **global combination score exclusive**：插桩中位 `0.351563s`；按同边界未插桩 oracle 比例折算约 `0.340919s`，约占未插桩 FeatureGraph `62.95%`，同时超过 `35%` 和 Operator `0.20s` 门槛。下一步应另立纯数值 replay/oracle 计划评估 Rust；本轮未实现、未接入。

## 固定环境与机制

- Windows x86-64；Blender `5.2.0 LTS`；Python `3.13.13`。
- Fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- 正式入口：`bpy.ops.hst.feature_chamfer_gn("INVOKE_DEFAULT", radius=0.01, show_cutter=False, dissolve_chamfer=True)`。
- 每轮独立 Blender 进程；启动时间不计；正式 Operator wall/runtime 均记录。
- 插桩位于独立 worktree，只加入计时/计数；未改算法、阈值、排序、缓存或正式默认行为。

## 三层边界审计

1. **FeatureGraph core**：`_build_feature_graph`。本次互斥子项和 `unattributed` 只解释这一层。
2. **正式 `feature_graph_seconds`**：代码在 `_rebuild_owned_preview_curve` 中仅包围 `_preview_feature_graph_with_cache`；cache miss 时等价于 FeatureGraph core 加缓存管理/复制开销。未包含 ChamferPlan、source patch IDs、endpoint/pipe contract。
3. **Preview / Operator**：ChamferPlan、source patch IDs、endpoint/pipe contract 位于上一步计时结束之后、Preview 结束之前；因此单列为 outer timings，不与 core 相加。

历史约 `0.591s` 对应第 2 层正式 `feature_graph_seconds`，不是整个 Preview rebuild。

## Phase 状态

- Phase 0：`PASS`。三次未插桩正式运行稳定。
- Phase 1：`PASS`。三次逐轮 groups、matching、plan、最终 Mesh 与健康性完全等价。
- Phase 2：`PASS`。三次有效正式 Operator，输入规模一致，无语义离群；互斥分解可解释 core。
- Phase 3：`PASS`。存在达到双重收益门槛的单一候选；仅给后续建议，未实现。

## 三轮明细（秒）

| 轮次 | Operator | 正式 feature_graph | Core | Score exclusive | Containment/BVH | Core 未归属 |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 1.949051 | 0.569269 | 0.563321 | 0.347712 | 0.111730 | 0.061350 |
| 2 | 1.916837 | 0.564536 | 0.558477 | 0.351563 | 0.114607 | 0.052348 |
| 3 | 1.923596 | 0.564202 | 0.558022 | 0.352216 | 0.114414 | 0.052165 |

未插桩 oracle 中位：Operator `1.841912s`，正式 FeatureGraph `0.541568s`。插桩中位开销：FeatureGraph `+0.022968s`，Operator `+0.081683s`；热点收益判断使用按 oracle 边界折算的估计值，不使用插桩绝对值冒充未插桩性能。

## Core 中位互斥分解（秒）

- BMesh/Sharp：`0.001956`
- Surface patch：`0.000848`
- Metadata/adjacency/local pairing：`0.004542`
- BVH build：`0.000336`
- Junction option/search-space：`0.011640`
- Global combination score exclusive：`0.351563`
- Containment/BVH query：`0.114414`
- Group traversal/sort：`0.019322`
- Stats serialization：`0.001038`
- 未归属：`0.052818`（core 的 `9.46%`）

Outer 中位（不属于正式 `feature_graph_seconds`）：source patch IDs `0.001828s`、ChamferPlan `0.023067s`、endpoint/pipe contract `0.014204s`。

## 规模与调用次数

三轮一致：Mesh `1307 V / 1988 E / 683 F`；Sharp Edge `990`；Patch `21`；junction `12`；groups `23`；junction candidates `42`；global combinations `729`；有效 score `681`；containment batch `681`；endpoint samples / nearest query `17,706`；BVH ray casts `116,451`；ChamferPlan strands `23`；ports `16`。

## 被驳回轮次

- `REJECTED`：首轮 instrumented 使用了不同版本的 fingerprint 定义，不能与 oracle 比较。
- `REJECTED`：逐点 containment timer 调用过多，开销偏高，改为每个组合一次 batch timer。
- `REJECTED`：候选秒数最初直接使用插桩值，改为按未插桩 oracle 同边界折算。

历史均保留在 `tests/artifacts/feature_chamfer_feature_graph_profile/rejected-*/`，未覆盖。

## 禁止机制与未验证事项

禁止机制使用：无。未接 Rust、未优化、未改算法/阈值/排序/缓存/BMesh/Bridge/Fill/Boolean、未改 `auto_load.py`、未生成或判断图片、未 commit/push。

尚未验证：任何优化后的真实提速、Rust replay 等价、集成收益、完整矩阵和用户视觉验收。若继续，必须另行授权并以当前 oracle 为只读对照。

## 证据

- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_profile/summary.json`
- Oracle：`tests/artifacts/feature_chamfer_feature_graph_profile/oracle/`
- 三轮明细：`tests/artifacts/feature_chamfer_feature_graph_profile/instrumented/`
- 日志：`tests/artifacts/feature_chamfer_feature_graph_profile/logs/`
