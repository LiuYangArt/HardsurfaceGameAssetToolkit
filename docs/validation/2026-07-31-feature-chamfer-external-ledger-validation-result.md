# Feature Chamfer 外部身份账本验证结果

日期：2026-07-31  
状态：`PROTOTYPE / STOP`

## 1. 目标与范围

- 固定样本：Mixed / `Extruded.002` / Radius `0.01` / Blender 5.1.2。
- 保留现有 GN Cutter 与 Boolean Pro；正式入口、Bridge/Fill、UI 和 `auto_load.py` 均未修改。
- 验证固定数量 Mesh attributes 能否让 Boolean 输出回指 Python 内存 ledger，并恢复旧路径完整身份。

## 2. 冻结合同

- Oracle：Boolean 后、Bridge 前逐 Edge 的 Pipe、Patch、segment、port、Edge/Point membership、station 与 station²。
- Boundary：3872 条原始记录、3868 个唯一端点键、4 条重复记录。
- 离散集合必须完全一致；浮点容差为一 float32 ULP。
- 禁止空间最近匹配、单 owner、固定槽位/bitmask、station clamp、样本特判和动态 one-hot 目标路径。

## 3. 分阶段结果

### Phase 0 — `PASS WITH SOURCE PATH RECONCILIATION`

- 原指定证据目录已不存在；复用了存活的已构建 Preview、逐 Edge oracle 和三次固定出口证据。
- 未重新构建约 80 秒的旧动态身份网络。
- 从存活 Preview 补齐了 port 与端点事实，并记录源文件及输出 JSON 的 SHA。

### Phase 1 — `PASS`

- 旧实验中 Pipe 5 witness 输出整数 `1375`，此前被误解为错误 Face lineage。
- 纠正后确认：它是未归一化的一阶矩，来自 `0.5 × 2749 = 1374.5` 的整数化结果；除以 membership 后可正确回指 Pipe 5 / segment 22。
- 因此 raw INT 不能直接当 record ID，但 source/cutter 独立的 membership + 一阶矩可恢复 Edge 级 record。
- Boolean 求值为 0.1484 秒。

### Phase 2 — `STOP`

- 已实际比较全部 3872 条原始记录 / 3868 个唯一 Edge；旧的“样本没有多 owner，所以停止”结论已 `REJECTED`。
- Boundary 数量、唯一键、重复 multiplicity 均零差异。
- Pipe、segment、Patch、port，以及 Edge membership/station/station² 全部恢复，零差异。
- 实际固定合同使用 source/cutter 独立 membership + 归一化一阶矩，并带 Point membership/station/station² 三个固定数值通道；数量不随 owner 数增长。
- 完整合同仍有 89 条端点身份差异。首差为 output Edge 133、Pipe 4 / segment 24 / Patch 4：端点 membership 从 `0.3333333433` 变为 `0.6666666865`，station 从 `0.7322297176` 变为 `0.4106152084`，station² 与 cyclic interval 同时不同。
- 准确失败层：Edge record 已可靠回指外部 ledger；失败发生在 Boolean Point 上直接传播固定数值事实时，局部贡献混合方式与旧 per-owner Point 合同不同。
- Mixed 中每条记录最多一个 Pipe/segment/Patch owner，因此通用多 owner 容量仍是 `NOT_VALIDATED_RISK`，但它不是本次停止原因。

### Phase 3–4 — `NOT RUN`

- Phase 2 完整身份未通过，因此未做正式信息消融、未运行 Bridge/Fill、未运行三次性能测试。
- 诊断计时：Phase 2 Boolean 0.1296 秒；包含账本构建、比较和 JSON 的原型总计 7.3338 秒。身份失败，所以这些数字不构成性能通过。

## 4. 结论与后续边界

- 外部账本方案已证明可替代 Edge 级动态 one-hot；当前缺口只剩 Point/endpoint 身份合同。
- 不应重做 Cutter、Boolean 或 Edge record 映射，也不应退回“每 owner 一列”。
- 下一轮只研究固定规模的端点贡献者映射：先解释 89 条差异的 Point 来源混合，再验证能否由输入端点 ledger 与固定贡献矩无损恢复。
- 若 Point 贡献集合不能由固定数量通道无损确定，应记录明确反证，再评估分批 Boolean 或预编译实现；预编译只能优化已正确算法，不能修复身份语义。

## 5. 独立验证证据

- 机器摘要：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/summary.json`
- Phase 1：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/phase1_trace.json`
- 身份比较：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/identity_comparison.json`
- 完整 raw 比较：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/identity_comparison_raw.json`
- 消融：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/ablation.json`
- 计时：`/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/timings.json`
