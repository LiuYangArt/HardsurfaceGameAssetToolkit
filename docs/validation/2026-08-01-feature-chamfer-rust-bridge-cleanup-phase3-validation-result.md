# Feature Chamfer Rust Bridge 清理 Phase 3 验证结果

日期：2026-08-01
状态：`PROTOTYPE / STOP`

## 1. 目标与范围

在独立 worktree 中，用正式 UI `Feature Chamfer` → `hst.feature_chamfer_gn`（`INVOKE_DEFAULT`）对 Mixed / `Extruded.002` / Radius `0.01` 强制 `python` 与 `native`，进行三次同轮 A/B。只验证 Phase 3 原型接线；没有修改主工作区、Phase 4 默认入口或 `auto_load.py`，没有 commit/push 或图片证据。

## 2. 冻结合同

- 基线：`a59adbf6a6aaf675395645c1643033df69c177b2`。
- 默认后端：未设置 `HST_FEATURE_CHAMFER_CLEANUP_BACKEND` 时为 `python`；仅测试进程显式强制 `python/native`。
- 正确性：每条清理决策和 deviation、merged/dissolved、Bridge/Fill、Chamfer Face 几何集合、order-independent 结果几何 fingerprint、健康性、Operator 状态必须完全一致。
- 性能门槛按冻结顺序判定：偏差内核下降 >=70%；Bridge cleanup 完整边界下降 >=50%；Operator 中位至少节省 0.20s 或下降 >=10%；三轮 native 不得有一轮慢于 Python。
- `bridge_cleanup_total_seconds` 包含所有 `_clean_bridge_component` 调用，加 native flush 中的坐标打包、模块加载、PyO3 调用、结果回填与阈值验证；kernel 单列。

## 3. 分阶段结果

### 3.1 原型接线与正式入口

- 状态：`PASS`。
- 生产 BMesh merge/dissolve、Bridge/Fill、Boolean、阈值和排序未迁移或修改。
- native 只批量计算 39 条 modified chain deviation，一次 Operator 一次 PyO3 batch。
- 三轮 native 均报告 `backend=native / batch_count=1 / modified_chain_count=39 / python_deviation_call_count=0`；Python 三轮均调用原函数 39 次。
- 默认模式仍为 Python；每次 Operator 开始与 `finally` 都清理 session。

### 3.2 正确性 A/B

- 状态：`PASS`。
- 三对 A/B 的语义 signature 全部相同：`46d393606fd602b0ed926c56b2476f242115d8c4dbfb9446d7ad46575bdd64f1`。
- 清理 decision、deviation、merge/dissolve 总数与逐 chain record、Bridge/Fill contract、Operator `FINISHED` 完全一致。
- order-independent Mesh/Edge/Face 坐标集合和 Chamfer Face 坐标集合 fingerprint 完全一致；结果均为 `3910 V / 7208 E / 3300 F / 2620 Chamfer Faces`，boundary/non-manifold/zero-area 均为 0。
- 第一处语义差异：无。

### 3.3 被拒绝的 round 0 fingerprint

- 状态：`REJECTED`，证据保留在 `comparison-round0-rejected.json`。
- 旧 fingerprint 把按 polygon index 排列的 Chamfer 布尔数组写入 hash。不同 Blender 进程的 face index 顺序不同，导致 `result_contract.fingerprint` 与随后 `chamfer_attribute_fingerprint` 假差。
- 结构化审计证明清理决策、Bridge/Fill、顶点/边/面坐标集合、计数和健康性相同。修正后 fingerprint 使用 Edge/Face 坐标集合和 Chamfer Face 坐标集合，不依赖 index/order；没有删除形状门禁，也没有把 backend/计时字段混入语义 signature。

### 3.4 Session 与 deferred validation 风险

- 状态：`PASS`（固定样本的 session/异常合同）。
- 同一 Blender 进程连续运行 `python → native → native 缺失异常`：前两次 `FINISHED`；缺失模块明确抛错；三次结束后 session 均为 `None`，未复用旧 items。
- 集成风险：native deviation 的合同检查延迟到全部 Bridge jobs 完成后的 flush；Python 是逐 chain 当场校验。固定样本结果等价，但一般失败输入可能先执行更多 BMesh/Bridge 工作后才暴露 deviation 错误，失败时序与中断现场不完全相同。Phase 4 必须先消除或明确处理该差异，当前原型不能被称为完全同架构语义。

### 3.5 三轮性能与第一失败门槛

- 状态：`STOP`。

| 指标 | Python 中位 | Native 中位 | 降幅 | 门槛 |
|---|---:|---:|---:|---|
| deviation kernel | `0.068600s` | `0.001188s` | `98.268%` | PASS |
| Bridge cleanup total | `0.357210s` | `0.292894s` | `18.005%` | **第一失败：需 >=50%** |
| Bridge/Fill | `0.820449s` | `0.740534s` | `9.740%` | 观察项 |
| Operator | `1.846956s` | `1.764103s` | `4.486%` / `0.082853s` | **失败：需 >=10% 或 0.20s** |

三轮 Operator 均无 native 单次回退：Python `1.897328 / 1.846956 / 1.831366s`；Native `1.783662 / 1.761751 / 1.764103s`。

阶段耗时解释：Python cleanup 中 deviation kernel 只占 `19.20%`（`0.068600 / 0.357210s`）；即使 kernel 变成零，理论上也只能让 cleanup 下降约 `19.20%`。实测 native cleanup 下降 `18.005%`，已经接近这个上限。剩余约 `0.289–0.292s` 来自 chain 排序、坐标提取、merge/dissolve 候选搜索、`BMesh` 查询与修改，以及 native queue/import/回填验证等非 kernel 工作。因此 kernel 巨幅提速不会自然转化成 50% cleanup 或 10% Operator 提速。

## 4. 审计记录

- `comparison.json`：3/3 正确性 PASS，Python/native 各自三轮稳定。
- `summary.json`：真实 `STOP`，第一失败门槛已结构化写入。
- `timings.json`：六次正式 Operator 原始分阶段时序和四项 gate。
- `session-audit.json`：连续切换、缺失 native 异常与 session 清理 PASS。
- command exit 2 是 runner 按冻结门槛报告 `STOP`，不是产品崩溃。
- 单轮探针只作 preliminary，最终结论来自三轮同轮 A/B。
- 禁止机制：无。完整回归按合同 `NOT RUN`；失败证据未覆盖或删除。

## 5. 最终结论与下一条建议

Phase 3 为真实 `STOP`：正确性、单次 native 调用、session/异常、kernel 性能和三轮无回退均通过，但第一失败门槛 Bridge cleanup 只有 `18.005%`，Operator 只有 `4.486% / 0.082853s`。Phase 4 保持 `NOT RUN`，不得把当前原型接为默认 `auto/native`。正式默认 runtime 仍为 Python。

下一条可验证建议：另立 Phase 3B 旁路 profiling，不接入口，只在这一个 Mixed 样本冻结约 `0.289s` 非 kernel cleanup 的细分耗时。依次量化 chain 排序/坐标复制、短边簇搜索、merge/dissolve 候选搜索、BMesh remove/dissolve、component refresh。只有一个独立、可迁移且不改变 BMesh/排序/阈值语义的纯数值阶段单项占到足以使 cleanup 下降到 50% 门槛，才建立新的 Rust oracle；否则应停止 Rust cleanup 路线。BMesh 修改仍留在 Python。

## 6. Artifacts

- 机器摘要：`tests/artifacts/feature_chamfer_rust_bridge_cleanup/phase3/summary.json`
- 三轮对比：`phase3/comparison.json`
- timings：`phase3/timings.json`
- session/异常：`phase3/session-audit.json`
- 范围审计：`phase3/scope-audit.json`
- 历史假差：`phase3/comparison-round0-rejected.json`
- 每轮 raw：`phase3/python/run-01..03.json`、`phase3/native/run-01..03.json`
- 日志：`phase3/logs/`
