# Feature Chamfer FeatureGraph Rust 全局评分 Replay 验证计划

日期：2026-08-01
状态：`PROTOTYPE / STOP`（Phase 0、1A PASS；Phase 1B STOP；Phase 1C NOT RUN；正式集成未授权）

## 1. 目标

验证 FeatureGraph 最大热点 `global combination score exclusive` 是否能作为独立纯数值批次迁移到 Rust，并在 Mixed 正式样本上同时满足：

1. 729 个全局组合的接受/拒绝、完整 score、最佳组合和 pairing 结果与 Python oracle 等价；
2. 单次 Python→PyO3 批量调用，包含输入打包、返回解包和最佳结果选择后的端到端耗时明显下降；
3. Rust 模块缺失时，原 Python replay 仍完整可用；
4. 正式 Feature Chamfer runtime 始终保持 Python，本轮不接入口、不改变结果。

本轮只验证 profiling 已确认约 `0.340919s / 62.95%` 的 score-exclusive 热点。Containment/BVH 约 `0.114414s` 只作为冻结输入，不在 Phase 1 中迁移；是否启动 Rust BVH 必须等 Phase 1 复核后另行授权。

验证已经完成：Rust 内核逐项等价且中位快 `87.51%`，但 Python→PyO3 完整端到端仅快 `16.54%`、节省 `0.172818s`，未达到本计划的 `70% / 0.20s` 双门槛。因此本路线按合同停止，正式 Python runtime 保持不变。完整证据见 `docs/validation/2026-08-01-feature-chamfer-feature-graph-rust-score-replay-result.md`。

## 2. 固定环境与样本

- Windows x86-64；Blender 5.2 / Python 3.13；Rust release 构建；PyO3 ABI 必须记录。
- Fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- 对象：`Extruded.002`。
- Radius：`0.01`。
- 正式入口：UI `Feature Chamfer` → `hst.feature_chamfer_gn`。
- 已验证 profiling：`docs/validation/2026-08-01-feature-chamfer-feature-graph-profiling-result.md`。
- 已冻结规模参考：990 Sharp Edges、12 junction、42 candidates、729 combinations、681 个有效 score。

旧 profiling 数字只用于核对量级；本轮必须从当前正式 Python 路径重新冻结 replay 和计时，不得直接复制历史汇总冒充新 oracle。

## 3. Oracle 与 replay 合同

### 3.1 Python oracle

在不改变生产逻辑的前提下，从正式 `_global_surface_patch_strand_pairs` / `_score_global_strand_option_combination` 边界导出实际输入和逐组合结果：

- Edge/Vertex 的稳定数值 ID 与连接关系；
- metadata：patch pair、convexity；
- 每个 junction 的 options、selected candidates、geometry signature 与 weight；
- fixed strand pairs、forbidden reconnections、edge start records；
- 每个组合冻结的 containment 输出：`exposed_endpoint_count`、`endpoint_containment_margin`；
- 每个组合是否因 forbidden reconnection 返回 `None`；
- 非 `None` 组合的完整 score 七元组与 pair links；
- 最终 best combination、best score、selected pairs 与 vertex matching records；
- 下游 Feature groups、ChamferPlan 与最终 order-independent Mesh fingerprint/计数/健康性。

Replay 必须使用生产运行时实际浮点值，不能从四舍五入后的诊断文本反推。Python oracle 和 Rust 必须读取同一份 replay JSON/二进制输入。

### 3.2 Phase 1 Rust 目标边界

Rust 负责一次性批量完成：

1. 根据每个 option combination 建立 pair links；
2. 遍历全部 Feature Edges，重建 strand records；
3. 判定 forbidden reconnection；
4. 统计 supported/unsupported turns 和 selected candidates；
5. 合并已冻结 containment 输出；
6. 构造与 Python 相同的完整 score 与 geometry signature；
7. 按 Python 相同的比较和 tie-break 选出最佳组合；
8. 返回最佳组合、score、pair links，以及逐组合审计结果。

禁止把 Python 已算好的 score、best index 或 pair links直接作为 Rust 输出；containment 结果是 Phase 1 唯一允许的预计算数值输入，必须在 artifacts 中明确标注为仍由 Python/BVH 提供。

## 4. 允许与禁止

允许：

- 独立 worktree 中新增 Rust crate、PyO3 release extension、oracle 导出器、replay validator 和 benchmark；
- 仅为导出 oracle 添加旁路 hook 或 monkeypatch；
- 原型构建产物放在 `prototypes/` 或 `tests/artifacts/`，并忽略 `target/`。

禁止：

- 修改正式入口、正式默认后端或 `auto_load.py`；
- 修改 FeatureGraph 算法、候选、阈值、排序、tie-break、containment、BVH、BMesh、Bridge/Fill、Boolean；
- 包装或调用 Python scorer 来冒充 Rust 结果；
- 每个 combination 进行一次 Python↔Rust 往返；
- 发现差异后放宽结果门槛、改变 replay 输入或只比较最终 best；
- 生成或判断图片；
- commit、push 或合并主工作区。

## 5. 分阶段门槛

### Phase 0 — 冻结正式 Python replay

状态起点：`NOT RUN`。

必须完成：

- 从一次正式 Operator 捕获 replay；
- Python replay 在不调用 Blender scorer 的独立验证器中复现 729 个组合、681 个有效 score 和最终 best；
- 再运行至少 101 次纯 replay benchmark，20 次 warmup；
- 保存输入 SHA256、逐组合 oracle、计时原始值、环境和捕获日志。

Go：逐组合和最终 best 完全复现，输入规模与正式 profiling 一致。
Stop：正式边界无法捕获或 replay 无法独立复现；Phase 1 `NOT RUN`。

### Phase 1A — 纯 Rust 等价

逐组合必须全部满足：

- `None` / accepted 完全一致；
- score 中整数、tuple、geometry signature 完全一致；
- Python `round(..., 7)` 后的两个浮点 score 字段逐值一致；
- pair links 完全一致；
- 最终 best combination、best score、selected pairs 完全一致。

Rust 单元测试必须至少覆盖：open/cyclic strand、forbidden reconnection、相同前六项时 geometry signature tie-break、空/单一 search space。

Go：729/729 与最终 best 全部通过。
Stop：第一处差异落盘；性能验证 `NOT RUN`，不得加容差掩盖。

### Phase 1B — 性能

仅 Phase 1A `PASS` 后运行：

- pure Rust release：20 warmup + 101 repeats；
- Python→PyO3 端到端：20 warmup + 101 repeats；
- 每次必须在一个批次处理 729 combinations；
- 端到端必须包含从冻结 replay 结构打包、PyO3 调用、返回解包、完整逐组合与 best 结果可用；
- Python oracle 使用相同冻结 replay 和相同进程环境；Blender 启动与 JSON 磁盘读取不计入两边。

Go 同时满足：

- pure Rust 中位相对 Python score-exclusive replay 下降至少 `80%`；
- Python→PyO3 端到端中位下降至少 `70%`；
- 端到端绝对节省至少 `0.20s`；
- 101 次结果 fingerprint 稳定；
- native 缺失时 Python replay 仍 `PASS`。

Stop：任一门槛失败。不得用 pure Rust 内核数字代替 PyO3 端到端结论。

### Phase 1C — 路线结论

- `PASS`：只证明 score-exclusive Rust 旁路值得继续；更新计划为“Rust containment/BVH 或正式 A/B 可另行评估”，仍不得接入口。
- `STOP`：记录第一失败门槛并停止 Rust FeatureGraph 路线；正式 Python 不变。

本轮不运行正式 Python/native Operator A/B，不运行完整矩阵、GUI、回归或视觉验收。

## 6. 状态定义

- `PASS`：当前阶段目标路径、输入、输出和全部硬门槛同时满足。
- `STOP`：出现明确等价差异或性能门槛失败。
- `BLOCKED`：外部条件确实阻止验证且替代路径审计后仍无法继续。
- `NOT RUN`：前置阶段未通过。
- `REJECTED`：旧轮次的输入、比较或结论无效，必须保留原因和证据。

## 7. 证据路径

- 结果文档：`docs/validation/2026-08-01-feature-chamfer-feature-graph-rust-score-replay-result.md`
- 原型：`prototypes/feature_chamfer_rust_global_score/`
- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_rust_score/summary.json`
- Replay 与逐组合比较：`tests/artifacts/feature_chamfer_feature_graph_rust_score/`
- 构建与运行日志：`tests/artifacts/feature_chamfer_feature_graph_rust_score/logs/`
