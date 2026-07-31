# Feature Chamfer Boolean 端点来源载体验证结果

日期：2026-07-31
状态：`PROTOTYPE / CORRECTNESS PASS / FIXED-SCALE AND PERFORMANCE STOP`

## 1. 目标与范围

- 在已经通过的 Edge 外部账本上，只验证 Boolean Boundary 端点的 membership、station、station² 与 contributor 身份。
- 固定样本为 Mixed / `Extruded.002` / Radius `0.01` / Keep Cutter `false` / Blender 5.1.2。
- 正式入口、UI、Boolean、Bridge/Fill 均未修改；没有生成、读取或判断图片。

## 2. 冻结合同

- 起点包含正式 Python Boolean 前属性生产；source/Cutter 输入与 Boolean runtime 复用当前正式 Preview。
- Oracle 只在 actual 由 Boolean 输出及输入账本独立生成后比较，不参与 actual segment、坐标或数值构造。
- Edge 基线：3872 raw / 3868 unique / 4 duplicate，Edge 身份零差异；既有端点缺口为 89 条，首差 Edge 133 / Pipe 4 / segment 24。
- 离散身份严格一致；派生 FLOAT 需同时满足 ULP ≤ 8 与绝对差 ≤ 1e-6。
- 未使用最近距离、空间容差、固定 ID、样本特判、手工补表、固定槽、bitmask、station clamp 或 oracle 目标复制。

## 3. 分阶段结果

### Phase 0 — `PASS`

- 完整复用并核对既有 oracle、raw comparison、首差与来源 SHA；固定计数和 Edge 零差异结论一致。
- Blender build 为 `ec6e62d40fa9`；fixture SHA-256 为 `80da3ee4…a513c3a3d1b8`。

### Phase 1 — `PASS VIA DYNAMIC SEMANTIC BATCH`

- 最终 FACE 邻接、高阶矩、Corner、Point role 和 direct key 等单次固定载体均未得到充分合同；其中部分早期“全量差异”后来证明是验证器错误，已标为无效证据，不能作为路线反证。
- 修正比较器后，逐 segment pass 精确恢复了历史首差 Edge 133 两端，其中首端 membership `0.3333333433`、station `0.7322297176`、station² `0.5361603339` 命中 oracle。
- 随后实际运行 32 次独立 Boolean，并按相同 raw ordinal、Edge index、Vertex index 合并。32 pass 的 3872 Boundary 数量、顺序与 endpoint coordinate float32 bits 全部相同，未使用空间匹配。
- 第一次合并曾报告 15 个 station² 差异；复核发现原因是 JSON 小数截断。改为直接读取冻结 Blend 的原始 Mesh float32 属性后，7744 组 endpoint-segment 的 membership、station、station² 全部逐位一致：三字段差异数、最大 ULP、最大绝对差均为 0。
- 因此 endpoint 语义恢复正确性明确 `PASS`；但该候选需要 32 次逐 segment Boolean，pass 数随 segment 数增长，不能算固定规模方案。

### Phase 2 — `PASS`

- 复用已通过的 Edge ledger，并合并 32 个 semantic passes；3872 raw / 3868 unique / 4 duplicate 与拓扑、顺序、坐标 bits 稳定，完整 7744 组端点三字段逐位零差异。
- actual 由各 pass 的真实 Boolean 输出独立生成；oracle 只在稳定 Edge/Vertex index 对齐后比较。

### Phase 3 — `STOP`

- 正确性候选每个 pass 通道固定，但 Mixed 需要 32 pass，数量随 segment 数增长；固定规模硬门槛未通过。
- 单次固定 FACE/CORNER/POINT/role/direct-key 候选仍未证明充分，多 owner 通用能力仍是未验证风险。

### Phase 4 — `NOT RUN`

- Phase 3 未通过，未运行 Bridge/Fill 或三次正式性能验收。
- 32-pass 已有明确性能反证：Boolean 求值累计 `6.1217s`，超过固定出口与 Python 恢复最大 `1.00s` 的预算。完整诊断脚本累计 `205.3143s`，其中包含大量 JSON 和比较开销，不能作为部署性能。

## 4. 重要审计结论

- 早期 7744 全差不是载体路线反证：验证器错误地把常量贡献矩当成最终 semantic membership。
- 后续 15 个 station² 差异也不是路线反证：十进制 JSON 截断造成假差异；原始 Mesh float32 复核为逐位零差异。
- station² 缺少输入 POINT 属性本身不构成失败；逐 segment pass 直接传播已有 FACE station²，并与旧输出逐位一致。
- 这次验证说明应先区分“能否得到正确语义”和“怎样用固定规模高速得到它”，不能因单个载体失败就报告整条 Python 路线失败。

## 5. 最终结论与后续方向

- 已证明：Python Boolean 后整理的 endpoint 语义可以完整恢复；全部 7744 组数据逐位零差异。
- 已证明：32-pass 逐 segment 方案不适合作为正式性能实现，既动态增长又仅 Boolean 就需要约 6.12 秒。
- 未证明：固定 provenance 编码或预编译实现不可能；当前结果反而提供了一个完整正确的诊断 oracle，可用于验证更紧凑方案。
- 下一步应研究减少 Boolean 批次数：优先按实际重叠关系把互不干扰的 segment 合并为共享批次，再比较批次数、完整端点身份和累计 Boolean 时间；若仍超预算，再评估在一次 Boolean 中输出更紧凑的贡献信息。
- 当前仅为旁路原型，禁止接正式入口。

## 6. Artifacts

- 独立任务：`019fb6ef-4fc1-7ba0-8c34-f608e8bcf28b`
- 独立 worktree：`/Users/apple/.codex/worktrees/995b/HardsurfaceGameAssetToolkit`
- 机器证据根目录：`/Users/apple/.codex/worktrees/995b/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_endpoint_provenance_carrier`
- 核心文件：`summary.json`、`identity_comparison.json`、`candidate_matrix.json`、`timings.json`。
- 32-pass 原始证据：`logs/semantic-batch/segment-0.json` 至 `segment-31.json`。
- 精确 float32 复核：`logs/candidate-semantic-batch-exact-oracle.json`。
