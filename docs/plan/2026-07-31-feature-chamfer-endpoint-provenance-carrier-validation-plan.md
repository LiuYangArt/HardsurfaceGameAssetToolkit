# Feature Chamfer Boolean 端点来源载体验证计划

日期：2026-07-31

状态：`VALIDATION COMPLETE / CORRECTNESS PASS / FIXED-SCALE AND PERFORMANCE STOP`

验证结果：[`../validation/2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md`](../validation/2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md)

结果摘要：32 次逐 segment 旁路在全部 7744 组端点数据上逐位零差异，证明 Python 后整理语义可行；
但该原型的批次数随 segment 数增长，Boolean 累计约 6.12 秒，因此固定规模与性能门槛未通过，未接正式入口。

## 1. 对上一轮结论的纠正

上一轮 `STOP` 只否定“Boolean 完成后，仅从最终 FACE 属性和邻接反推 Boundary 身份”这一种机制，
不否定 Python Boolean 后整理本身。把该局部 `STOP` 直接作为整条路线的最终报告不够准确。

此前外部账本验证已经证明：固定规模载体可以在全部 3872 条 raw Boundary 上零差异恢复 Edge 级
Pipe、segment、Patch、port、membership、station 和 station²。当时唯一剩余缺口是 89 条 Point/endpoint
身份差异。因此本轮不得重复 Boundary universe、Face adjacency、Face raw record ID 或 Edge ledger 实验；
验证范围只剩端点贡献者映射。

关联结果：

- `docs/validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`
- `docs/validation/2026-07-31-feature-chamfer-python-post-boolean-materializer-validation-result.md`
- `/Users/apple/.codex/worktrees/d4b3/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_external_ledger/`
- `/Users/apple/.codex/worktrees/995b/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_post_boolean_materializer/`

## 2. 要回答的问题

在 Edge 级外部账本映射已经完全通过的基础上，能否增加固定数量、与 owner/segment/Face 数量无关的
Point provenance carrier，让 Python 确定每个 Boolean Boundary 端点由哪些输入 Cutter Face/Point 贡献，
从而恢复与旧 per-owner Point field 完全一致的：

- endpoint membership；
- endpoint station 与 station²；
- cyclic interval；
- Direct Bridge 当前消费的全部 Boundary POINT 属性。

真正验证对象是“固定端点来源载体 + Python 外部账本恢复”，不是再次用最终相邻 Face 猜身份，也不是
把旧动态 materializer 的结果复制给 Python。

## 3. 固定环境、输入与 oracle

- 项目规范：`/Users/apple/CodeProjects/blender-addons/HardsurfaceGameAssetToolkit/AGENTS.md`
- Blender：macOS 安装的 5.1.2，必须保存完整 build hash。
- fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`，必须保存 SHA-256。
- Object / Radius / Keep Cutter：`Extruded.002` / `0.01` / `false`。
- 正式起点：提交 `46fa628` 的 Python Boolean 前 producer、同一 Cutter Mesh、同一 Boolean Pro。
- Oracle：本轮重新读取的正式动态 materializer 完整逐 Edge/Point identity；必须与既有 oracle 的
  3872 raw / 3868 unique / 4 duplicate、89 条已知 endpoint 差异口径对齐。
- Edge ledger 基线：复用 d4b3 已通过的 source/cutter 独立 membership + 归一化 record 一阶矩合同；
  先核对 artifact SHA 和完整比较结果，不重新发明 Edge 映射。

## 4. 允许与禁止机制

### 4.1 允许

- Python 内存 ledger 保存任意长度的 Face/Point contributor 与完整 owner 数据；JSON 只作证据；
- 在正式 source/Cutter Boolean 输入上写固定数量的 INT/FLOAT carrier；
- 使用 membership、record ID 的归一化一阶/二阶/更高矩、独立校验矩、source/cutter 类型通道；
- 在 active Manifold Difference 的 Point/Edge field 仍存在时，用固定数量 Store 输出这些 carrier；
- 用完整 oracle 诊断贡献者集合，并做信息消融；
- 若单次 Boolean 固定 carrier 有明确反证，再进入分批/overlap batch prototype。

### 4.2 禁止

- 修改正式入口、UI、`auto_load.py`、Boolean Pro 原始语义或 Direct Bridge/Fill；
- 为每个 Pipe、segment、Patch、Face 或 Point 动态创建 GN nodes/links；
- 从旧 per-owner Boundary EDGE/POINT 属性复制目标值，或用 oracle 作为目标输入；
- nearest、BVH、centroid、空间容差、固定 Edge/Face/Vertex ID、fixture 名称分支、手工补表；
- 单 owner、主 owner、固定槽位、固定 bitmask、station clamp；
- 只修 89 条已知差异而不全量比较 3872 raw Boundary；
- 在看到差异后修改 oracle 或放宽容差；
- 生成、读取或判断图片。

## 5. 分阶段硬门槛

### Phase 0 — 复用并核对完整 oracle

必须复制或只读引用 d4b3 的 Edge ledger、完整 raw identity comparison 和首个 endpoint 差异，记录来源
绝对路径、SHA-256 与 schema。同时从当前正式入口重读同一 oracle，核对：

- 3872 raw / 3868 unique / 4 duplicate；
- Edge 级身份零差异结论仍成立；
- 89 条 endpoint 差异和首差 Edge 133 / Pipe 4 / segment 24；
- source/Cutter 输入 Mesh、plan 与 Boolean runtime fingerprint 一致。

全部一致为 `PASS`；artifact 缺失且无法一次有界重建才是 `BLOCKED`。不得重做已通过的 Edge 路线。

### Phase 1 — 首差端点贡献者追踪

只针对首差端点建立完整 trace，但必须使用通用字段：

1. 旧 oracle endpoint membership/station/station²；
2. 输入 Cutter Face/Point ledger 中所有候选贡献记录；
3. 现有固定 Point 通道在 Boolean 前、field adaptation 时、Boolean 输出时的值；
4. 为什么原型得到另一组局部贡献；
5. 至少一组候选固定 contributor carrier 是否能唯一恢复 oracle 贡献集合。

阶段结束必须明确“信息在何处丢失”或“哪组固定 carrier 能恢复”，不能因为脚本尚未完成写 `STOP`。
存在至少一个可推广候选为 `PASS`；所有候选均出现不可逆碰撞且有反证才为 `STOP`。

### Phase 2 — 全量 Point/endpoint identity

用 Phase 1 候选对全部 3872 raw Boundary / 所有端点恢复完整 identity，并比较：

- Edge ledger 继续零差异；
- endpoint contributor record 集合完全一致；
- Point membership 的 `> 1e-6` 消费决策完全一致；
- station、station²、cyclic interval 全量一致；
- Pipe、segment、Patch、port 和共享 owner 集合完全一致；
- 输出属性 schema/domain/type/长度与 Direct Bridge 输入合同一致。

离散数据没有容差。派生 FLOAT 延用已冻结的双重门槛：ULP `≤ 8` 且绝对差 `≤ 1e-6`；必须记录
bitwise 差异数、最大 ULP、最大绝对差和第一处差异。

全部通过为 `PASS`。可复现超容差或离散首差为 `STOP`，Phase 3–4 `NOT RUN`。

### Phase 3 — 固定规模与信息消融

仅 Phase 2 `PASS` 后运行。逐项删除 contributor carrier，证明最小充分合同。必须记录：

- 每个通道的目的；
- nodes/links/attributes 是否与 owner 数无关；
- 最大 contributor 数及候选矩是否存在碰撞；
- 输入顺序、Face 顺序、Edge 方向反转后的稳定性；
- 对任意多 owner 的能力边界；Mixed 无法覆盖的部分必须标 `NOT VALIDATED RISK`，不得假装证明。

找到固定充分合同为 `PASS`；只有动态 one-hot 才能等价且有完整反证为 `STOP`。

### Phase 4 — 未修改 Bridge/Fill 与性能

仅 Phase 3 `PASS` 后运行。把 Python 生成的完整 EDGE/POINT 属性交给未修改 Direct Bridge/Fill：

- Bridge job、顺序、owner pair、segment/pipe 分组、station interval、turn/cyclic split 全量一致；
- 最终产品矩阵规范化 fingerprint 为
  `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107`；
- 3922 Vertex / 8054 Edge / 4134 Face / 3454 Chamfer Face；
- 80 Bridge jobs / 3437 Faces，12 Fill jobs / 28 Faces；
- Boundary、non-manifold、zero-area、self-intersection 均为 0；source 不变且无残留。

连续三次独立冷运行：

- 固定出口 + Python Edge/endpoint 恢复中位数 `≤ 0.70s`，最大 `≤ 1.00s`；
- 完整 prototype 中位数 `≤ 2.00s`，最大 `≤ 2.50s`；
- 三次 identity、下游 ledger、最终 fingerprint 与清理合同一致。

全部通过为 `PROTOTYPE / PASS`；正确但超预算为性能 `STOP`。

## 6. 失败后必须继续检查的备选路线

单个 candidate carrier 失败只标该候选 `REJECTED`，不得立刻终止整个任务。顺序为：

1. source/cutter 分离的 membership + record 一阶矩；
2. 增加 record 二阶矩与独立校验矩，判断贡献集合碰撞；
3. 增加固定 Point contributor 类型/角色通道；
4. 若固定矩确有不可逆碰撞，验证固定出口能否直接导出输入 contributor key；
5. 单次 Boolean 固定 carrier 全部存在反证后，才启动分批/overlap batch 子原型。

只有上述有界候选均有可复现语义反证，才可给整体 `STOP`。不得把第一版实现差异当作路线失败。

## 7. 必须交付的证据

- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/summary.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/environment.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/oracle_sources.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/phase1_trace.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/candidate_matrix.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/identity_comparison.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/ablation.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/downstream_comparison.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/timings.json`
- `tests/artifacts/feature_chamfer_endpoint_provenance_carrier/logs/`
- `docs/validation/2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md`

每阶段结束立即落盘。结果文档必须保留 `REJECTED` / `SUPERSEDED` 轮次、禁止机制使用情况、真实首差、
未覆盖风险和 artifacts 绝对路径。

## 8. 当前授权边界

只允许旁路原型与验证文档。即使全部通过，也不得接正式入口；主任务复核后再由用户决定是否集成。
