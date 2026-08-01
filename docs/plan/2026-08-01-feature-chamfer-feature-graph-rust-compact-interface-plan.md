# Feature Chamfer FeatureGraph Rust 紧凑接口验证计划

日期：2026-08-01
状态：`PROTOTYPE / PASS`（紧凑接口验证通过；正式 Operator A/B 尚未授权）

## 1. 要回答的问题

上一轮已经证明 Rust 对 729 个组合的计算与 Python 完全一致，纯 Rust 中位从 `1.044854s` 降至 `0.130485s`；失败原因是验证接口每轮回传全部 729 项明细，完整端到端只快 `16.54%`。

本轮验证已经完成：紧凑接口仍计算全部 729 项，端到端中位从 Python `1.026091s` 降至 `0.131558s`，快 `87.18%`、节省 `0.894533s`；全量审计 729/729 等价，状态为 `PROTOTYPE / PASS`。这只授权另建正式 Operator A/B 计划，尚未授权接入。

本轮只验证正式运行实际需要的紧凑接口：Rust 仍计算全部 729 个组合，但只返回最终最佳组合对应的必要数据，判断 Python→PyO3 的真实集成形态能否明显提速。

## 2. 固定样本与 oracle

- Windows x86-64；Blender 5.2 / Python 3.13；Rust release / PyO3。
- Fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- 对象：`Extruded.002`；Radius：`0.01`。
- 正式入口：UI `Feature Chamfer` → `hst.feature_chamfer_gn`。
- Oracle：当前正式 Python runtime。
- 复用上一轮同一生产捕获 replay，SHA256 必须为 `ccedf5a2b0e204d81503857ccee72c5048955d0962edef770cd521ca57c709c3`；若当前正式 runtime 或 replay hash 已变化，先重新捕获并重建 Python/Rust 全量等价证据。

## 3. 紧凑返回合同

Rust 单次批量处理全部组合，仍自行完成 pair links、strand traversal、forbidden reconnection、turn counts、冻结 containment 合并、完整 score 与 tie-break。

计时路径只返回正式下游需要的：

- best combination index；
- best score；
- best option indices，足以恢复正式 `best["options"]`；
- best pair links，使用稳定数值 half-edge ID；
- 用于 101 次稳定性验证的紧凑 fingerprint。

不得返回 729 项逐组合结果。全量 729/729 等价仍通过单独审计调用验证，不能因紧凑返回而降低正确性门槛。

## 4. 允许与禁止

允许：

- 在上一轮独立 worktree 的旁路 crate/验证器上新增紧凑函数与 benchmark；
- 复用上一轮冻结 replay 和 release 构建方式；
- 使用单次 PyO3 批量调用。

禁止：

- 修改正式入口、正式默认后端、算法、阈值、排序、containment/BVH 或 `auto_load.py`；
- 调用 Python scorer 冒充 Rust；
- 每个 combination 跨语言调用；
- 只比较最终 best 而跳过全量 729/729 审计；
- commit、push、完整回归、GUI/视觉验收或图片。

## 5. 分阶段硬门槛

### Phase 0 — 合同与 oracle 复核

- 确认正式 Python 下游实际只消费 best options、best score 和相关 pairing；
- replay hash 与上一轮一致，或重新冻结后全量 Python replay 729/729 PASS；
- 保留旧全量 Rust 等价检查 729/729 PASS。

Stop：无法从紧凑返回重建正式下游输入，后续 NOT RUN。

### Phase 1A — 紧凑返回等价

单独审计调用必须继续满足 729/729 accepted/None、完整 score、geometry signature、pair links、best 全等。

紧凑调用必须与 Python oracle 完全一致：

- best index、best score；
- best option indices 与 selected pairs；
- best pair links；
- 由紧凑结果重建的 vertex matching records/strand pairs 结构化 fingerprint。

Stop：第一差异落盘，性能 NOT RUN，不得放宽。

### Phase 1B — 紧凑接口性能

20 次 warmup + 101 repeats，计时包含：

- 从冻结 Python primitive replay 构造本轮输入；
- 一次 PyO3 调用；
- 解包紧凑返回；
- 在 Python 中恢复正式下游可消费的 best options、strand pairs 和 records 所需数据。

不含 Blender 启动、JSON 磁盘读取和全量审计输出。

Go 同时满足：

- 相对 Python 完整 score replay，中位下降至少 `70%`；
- 绝对节省至少 `0.20s`；
- 101 次紧凑结果和重建 fingerprint 稳定；
- native 缺失时 Python replay PASS。

Stop：任一门槛失败。不得用 pure Rust 内核数字替代端到端结论。

### Phase 1C — 路线判断

- Phase 1B PASS：只记为 `PROTOTYPE / PASS`，说明值得另建正式 Operator A/B 计划；仍不得接入口。
- Phase 1B STOP：停止 FeatureGraph Rust score 路线。
- 前置失败：后续 `NOT RUN`。

## 6. 证据

- 结果文档：`docs/validation/2026-08-01-feature-chamfer-feature-graph-rust-compact-interface-result.md`
- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_rust_compact/summary.json`
- 原始比较与计时：`tests/artifacts/feature_chamfer_feature_graph_rust_compact/`
- 原型：`prototypes/feature_chamfer_rust_global_score/`
