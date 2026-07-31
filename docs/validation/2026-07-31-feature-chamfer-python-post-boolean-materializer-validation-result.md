# Feature Chamfer Python Boolean 后身份整理验证结果

日期：2026-07-31

状态：`PROTOTYPE / LOCAL MECHANISM STOP`（路线级结论已被后续验证更新）

独立验证任务：`019fb6ef-4fc1-7ba0-8c34-f608e8bcf28b`

> 2026-07-31 后续结论：本文只否定“Boolean 完成后，仅凭最终 FACE 邻接反推身份”这一种机制，
> 不否定 Python Boolean 后整理。后续端点来源验证已用 32 次逐 segment 旁路证明全部 7744 组
> endpoint membership、station、station² 可逐位一致恢复；当前剩余问题是把正确语义压缩成固定规模且足够快的出口。
> 详见 [`2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md`](2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md)。

## 1. 目标与范围

- 要回答的问题：固定 Intersection 出口后，Python 能否只依赖同一 Boolean 输出 FACE 属性、Mesh 邻接、同一 plan 与正式 Cutter FACE ledger，完整生成 Direct Bridge 现有 EDGE/POINT 身份。
- 明确不做：不修改正式入口、UI、`auto_load.py`、Boolean Pro、Bridge/Fill；不集成原型；不生成或判断图片。

## 2. 冻结合同

- 环境：macOS / Blender 5.1.2，build `ec6e62d40fa9`；代码起点 `46fa628`。
- 固定样本：Mixed / `Extruded.002` / Radius `0.01` / Keep Cutter `false`；fixture SHA-256 `80da3ee4144ba83cab4e9bed980c8829d846369f22a694abfe1aa513c3a3d1b8`。
- Oracle：本轮从同一 fixture 新建正式 Preview，复用正式 Python Boolean 前输入、同一 Boolean Pro 与原动态后整理；三次独立读取稳定。
- 比较：离散身份严格一致；派生 FLOAT 预冻结为 ULP ≤ 8 且绝对差 ≤ 1e-6。Phase 2 在首个离散差即停止，FLOAT 全量比较未到达。

## 3. 分阶段结果

### Phase 0 — `PASS`

- 真实机制：正式入口建立 17 nodes / 21 links wrapper；Boolean 前固定输入 3 nodes / 3 links；当前动态后整理构建 1.075 秒；Boolean 子组 592 nodes / 808 links。
- 三次完整 Boundary ledger 与稳定下游摘要 fingerprint 均为 `a8a3558aea8dde553d2e052709a788fa8918e2a809a69ec5b32c454943d02fa5`。
- Boolean 输出 4195 Vertex / 4866 Edge / 680 Face；Boundary 3872 raw / 3868 unique / 4 duplicate。
- Oracle 未修改 Bridge/Fill：80 Bridge jobs / 3437 Faces；12 Fill jobs / 28 Faces；最终 3922 / 8054 / 4134，Chamfer Face 3454，四项健康计数均为 0。
- 最终结果同时命中两种不同算法的冻结指纹：按当前 Mesh 元素顺序直接哈希为 `c485119c3a9ba9654373fe77d0ec8ed151727f9b2b91ea386262de8b109fc067`；产品矩阵消除元素顺序影响后的规范化指纹为 `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107`。两者用途不同，各自命中 oracle。

### Phase 1 — `PARTIAL PASS`

- 真实机制：直接复用 formal Preview 的 source/Cutter Mesh；复制同一 Boolean Pro，仅在 active Manifold Difference 增加 1 个固定 EDGE Store 与 4 条连接，写出原生 Intersection Edges。
- 节点/连接不随 owner 数增长；Boundary 3872 / 3868 / 4 与 oracle 一致。
- 固定输出的所需 FACE schema、domain、type 与长度可读取；但完整值和 provenance 信息充分性未通过：首差 Edge 的相邻 FACE 上 Pipe 0 为 false，不能支持旧 EDGE 值 true。

### Phase 2 — `LOCAL MECHANISM STOP`

- 首差：raw ordinal 0 / output Edge 0，oracle `pipe_ids=[0]`，目标为空。
- 首差 trace：该 Edge 仅邻接最终 Face 0；输出 Pipe 0 FACE 属性存在但值为 false；旧 GN 在同一 Intersection Edge 上通过 BOOLEAN Named Attribute 的 EDGE field adaptation 得到 true。
- 有界信息审计：正式 Cutter 输入确有 Pipe 0 FACE ledger，但固定最终 geometry + Intersection 没有 Boundary Edge → 输入 Cutter Face/Corner/Edge 的来源键。仅凭最终 FACE 邻接无法知道该 Edge 的贡献 Face。
- 因此这是“最终 FACE 邻接反推”机制的信息缺失，不是整条 Python 后整理路线的 `STOP`，也不是 `BLOCKED`。不得以 any/max 相邻 Face、空间匹配、固定 ID 或手工表补齐。

### Phase 3–4 — `NOT RUN`

- Phase 2 硬门槛未通过，目标 Mesh 未交给 Bridge/Fill，也未运行三次目标性能。Phase 0 下游数字仅为 oracle。

## 4. 审计记录

- Phase 0 首轮与 probe-run 1–4 均为 `REJECTED`：原因包括字段读取、旧节点依赖、旧 POINT oracle、汇总变量和错误重建 Boolean 前 Cutter。
- probe-run 5/6 为 `SUPERSEDED`：首差有效，但初始 any/max 相邻 Face 规则只作诊断；最终解释由 field trace 与固定出口信息审计取代。
- 使用过的禁止机制：无。未使用 nearest/BVH/centroid、固定 Edge/Face ID、fixture 分支、手工补表、station clamp、单 owner、固定槽或 bitmask；未复制 oracle 输出为目标。

## 5. 最终结论

- 已证明：只有最终 Boolean geometry、Intersection EDGE、传播后 FACE 属性与邻接时，无法无损恢复完整后段身份；第一条 Boundary 已丢 Pipe 0。
- 本文尚未证明的两项已在后续验证中部分回答：分批 Boolean 可以逐位恢复全部端点语义，但当前 32 次逐 segment 形式耗时过高；固定规模 carrier 仍未找到充分合同。
- 后续不得重复相邻 Face 猜测；应继续研究如何把已经证明可恢复的逐 segment 语义压缩为少量批次或固定规模出口。

## 6. Artifacts

- 独立 worktree：`/Users/apple/.codex/worktrees/995b/HardsurfaceGameAssetToolkit`
- 机器摘要：`tests/artifacts/feature_chamfer_python_post_boolean_materializer/summary.json`
- 完整 oracle：`tests/artifacts/feature_chamfer_python_post_boolean_materializer/oracle.json`
- 固定出口：`tests/artifacts/feature_chamfer_python_post_boolean_materializer/fixed_export.json`
- 身份首差：`tests/artifacts/feature_chamfer_python_post_boolean_materializer/identity_comparison.json`
- 环境、下游与性能状态：同目录 `environment.json`、`downstream_comparison.json`、`timings.json`。
- trace、信息审计、被驳回轮次和三次读取原始产物：同目录 `logs/`。
