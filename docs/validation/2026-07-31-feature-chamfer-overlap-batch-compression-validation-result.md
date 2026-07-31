# Feature Chamfer Boolean 后共享批次压缩验证结果

日期：2026-07-31
状态：`PROTOTYPE / CORRECTNESS PASS / PERFORMANCE STOP`

## 1. 结论

- 已将正确性验证所需的 32 次逐 segment Boolean 压缩为 4 个共享批次。
- 3872 条 raw Boundary、7744 组 endpoint-segment 的 membership、station、station² 全部逐位零差；第一处差异为空。
- 当前保守冲突图有 32 个 segment、39 组冲突。精确回溯检查 3184 个状态，证明它不可分成 3 批，因此 4 批是该合同下的下界。
- Boolean 累计中位耗时从约 `6.1217s` 降到 `0.5023s`，约快 `12.2×`。
- 若固定出口预先存在，稳态目标路径中位约 `0.7392s`、最大约 `0.7426s`；最大门槛通过，但中位仍比 `0.70s` 预算高约 `0.039s`，因此性能状态保持 `STOP`。
- 这不是 Python 语义失败。正确性已经通过，剩余问题只是进一步减少运行时准备成本。

## 2. 真实执行机制

- 冲突图只使用当前输入 plan、Cutter FACE/POINT 共现和已经通过的 Edge ledger；最终分组不读取 endpoint oracle。
- Python 先将同一批内的 segment 数据聚合成 membership、加权 station、加权 station² 三个 FACE 属性。
- 每批 Boolean 只读取固定三个通道，不再为批内每个 segment 动态创建节点和连线。
- Python 根据 Edge ledger 确定每条 Boundary 属于哪个 segment，并从该 segment 所在批次读取端点结果。
- Oracle 只在 actual 完成后读取原始 Mesh float32 属性作末端比较。

## 3. 阶段状态

- Phase 0：`PASS`。32-pass 正确性与约 `6.12s` 基线已冻结。
- Phase 1：`PASS AFTER REJECTED ROUNDS`。正序、逆序和 degree 排序均得到 4 批；精确检查证明不可 3 色。
- Phase 2：`PASS`。四批 Boundary 数量、Edge/Vertex 顺序和坐标 bits 一致；7744 组端点三字段逐位零差。
- Phase 3：`STOP`。三次稳态中位 `0.7392s`，未达到 `0.70s`；包含一次固定图准备后约 `1.29s`。完整验证包装中位约 `2.27s`，最大约 `2.33s`。
- Phase 4：`NOT RUN`。性能门槛未通过，没有运行或修改 Bridge/Fill，也未接正式入口。

## 4. 被驳回的轮次

- 第一、二版冲突图漏掉输入 plan 的共享端点关系，实跑分别出现 58 和 32 处差异，均标为 `REJECTED`。
- 第三版曾使用 32-pass endpoint occupancy 参与分组，违反 oracle 只读边界，标为 `REJECTED/SUPERSEDED`。
- 第四版在批内逐 segment 动态创建属性读取与加法节点，虽然可得到正确结果，但没有消除动态网络，标为 `SUPERSEDED`。
- 固定图早期连接到了错误位置，计时轮正确性不通过；修正后最终三次均为 `PASS`，历史差异保留在独立任务日志中。

## 5. 风险与下一步

- 当前 4 批原型已证明语义和压缩方式正确，可作为下一阶段实现 oracle。
- 固定图准备约 `0.55s`。正式实现可把出口静态预建，但本轮没有用预测扣除成本来包装通过。
- 正式 Python Boolean 前阶段已经持有 Cutter Mesh；若后整理直接复用该对象而不再次求值，可能消除约 `0.18s` 重复准备，但必须在正式集成边界另行实测。
- 当前保守冲突图不可 3 色。若要减少批数，必须证明某些输入侧保守冲突实际可以安全删除，不能使用 endpoint oracle 反推分组。
- 本轮只做旁路验证，正式代码未修改。

## 6. Artifacts

- 独立任务：`019fb74a-3b6b-7a10-ab1b-4bf67b2ad902`
- 独立 worktree：`/Users/apple/.codex/worktrees/1321/HardsurfaceGameAssetToolkit`
- 机器证据根目录：`/Users/apple/.codex/worktrees/1321/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_overlap_batch_compression`
- 核心证据：`summary.json`、`conflict_graph.json`、`batches.json`、`correctness.json`、`timings.json`。
- 被驳回轮次及运行日志：同目录 `logs/`。
