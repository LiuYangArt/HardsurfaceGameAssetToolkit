# Feature Chamfer Boolean 后共享批次压缩验证计划

日期：2026-07-31
状态：`VALIDATION COMPLETE / CORRECTNESS PASS / PERFORMANCE STOP`

验证结果：[`../validation/2026-07-31-feature-chamfer-overlap-batch-compression-validation-result.md`](../validation/2026-07-31-feature-chamfer-overlap-batch-compression-validation-result.md)

结果摘要：32 次逐 segment Boolean 已压缩为当前冲突合同下最少的 4 批，全部 7744 组端点数据逐位零差；
Boolean 累计中位约 0.50 秒，但稳态完整恢复中位约 0.739 秒，略高于 0.70 秒门槛，因此正确性通过、性能仍未通过。

## 1. 已知起点

- Edge 外部账本在 3872 条 raw Boundary 上零差异。
- 32 次逐 segment Boolean 已在全部 7744 组 endpoint-segment 上逐位恢复 membership、station、station²。
- 因此不再验证“Python 能否做到”，只验证能否把 32 次正确处理压缩成少量共享批次。
- 32 次结果是正确性 oracle，不是性能实现；正式入口保持不变。

## 2. 待验证机制

把不会在同一条 Boundary Edge / endpoint 上同时被消费的 segment 放入同一批。每批只传播三类合并事实：

- membership；
- membership 加权 station；
- membership 加权 station²。

Python 使用已经通过的 Edge segment ledger 确定当前 Edge 在该批中对应哪个 segment，再把批次事实写回该 segment。

分组必须从当前输入 plan、Cutter 拓扑和已经验证的 Edge ledger 独立生成；禁止用旧 endpoint oracle 选择颜色、修补冲突或构造 actual。Oracle 只在结果生成后比较。

## 3. 顺序与硬门槛

### Phase 0 — 冻结 32-pass 正确性 oracle

复用上一轮原始 Mesh float32 证据，核对 7744 组数据逐位零差异、32 次 Boolean 累计约 6.12 秒。

### Phase 1 — 构建冲突图与共享批次

- 两个 segment 只要可能在同一 Boundary Edge 或同一输入 Cutter Point/Face 上共同贡献，就必须冲突；
- 记录 segment 数、冲突数、每批成员、颜色数与构造依据；
- 正序、逆序和稳定 tie-break 至少三种着色顺序必须得到相同或可解释的批次数，不能依赖 fixture 固定编号。

### Phase 2 — 全量正确性

- 实际运行所有共享批次；
- 每批 Boolean 的 Boundary 数量、Edge/Vertex 顺序和坐标 bits 必须与基线一致；
- 合并全部 3872 raw Boundary / 7744 组端点；
- membership、station、station² 与原始 Mesh float32 oracle 逐位比较；
- 离散身份零差异，派生 FLOAT 至少满足 ULP ≤ 8 且绝对差 ≤ 1e-6，并同时报告 bitwise 差异数。

若失败，必须给出第一处真实冲突并判断是冲突图漏边、合并字段不足还是 Boolean 传播差异；实现错误只记 `REJECTED`，修正后继续。

### Phase 3 — 性能

仅正确性通过后统计：

- 共享批次数；
- Boolean 求值累计时间；
- Python 构图、解码与合并时间，排除证据 JSON 序列化；
- 完整旁路时间。

目标：固定出口 + Python 恢复中位数 ≤ 0.70 秒、最大 ≤ 1.00 秒。若正确但超预算，继续记录批次数与主要成本，不把它表述成语义失败。

### Phase 4 — 下游

只有正确性与阶段性能均通过才运行未修改 Bridge/Fill，并比较冻结工作项、最终指纹与 3922 / 8054 / 4134 / 3454 统计。

## 4. 禁止机制

- 不修改正式入口、Boolean 语义或 Bridge/Fill；
- 不用空间最近匹配、固定 ID、样本特判、手工补表、station clamp；
- 不用 endpoint oracle 参与分组或 actual 生成；
- 不生成、读取或判断图片；
- 单次实现错误或某种着色策略不通过，不得直接报告整条路线失败。

## 5. 交付物

- `tests/artifacts/feature_chamfer_overlap_batch_compression/` 下环境、冲突图、批次、正确性、计时和日志 JSON；
- `docs/validation/2026-07-31-feature-chamfer-overlap-batch-compression-validation-result.md`；
- 结果必须明确区分正确性、批次数、性能和下游四层状态。

## 6. 授权边界

只允许独立 worktree 中的旁路原型、证据与验证文档。即使通过也不得接正式入口。
