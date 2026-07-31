# Feature Chamfer Python 逐 segment 属性等价验证结果

日期：2026-07-31  
状态：`PROTOTYPE / VERIFIED`

## 1. 范围与冻结门槛

- 固定样本：Mixed / `Extruded.002` / Radius `0.01` / Blender 5.1.2。
- 完整 Python producer 不读取旧逐 segment POINT/FACE 属性；Cutter 由固定规模 geometry-only Curve-to-Mesh 生成，并送入同一个 Boolean Pro。
- 几何、schema 和 Pipe/segment/Patch/port 等离散身份要求完全一致。
- station、station²、cyclic interval 等派生 FLOAT 冻结为双重门槛：每项同时满足 `ULP ≤ 8` 且绝对差 `≤ 1e-6`；`-0/+0` 数值等价。
- 正式入口、Boolean Pro、Bridge/Fill、UI、operator 与 `auto_load.py` 均未修改；未生成或判定图片。

## 2. 纠正历史

- 旧 POINT→Python FACE adaptation 仍为子问题 `PASS`：140 列、488677 元素逐位一致，同一 Boolean 与下游亦一致；它不代表完整 producer。
- 旧整体 `PROTOTYPE / VERIFIED` 已 `SUPERSEDED`：当时 target 仍读取旧 POINT 字段，且约 0.400 秒计时从预求值 Cutter 开始。
- 完整 producer 的严格逐位 `STOP` 已由用户决策 `SUPERSEDED → PHASE1_SEMANTIC_PASS`。原 13235 个 bitwise 差异、首差 `-0/+0`、最大 6 ULP / `2.38e-7` 全部保留，不作清零或隐藏。
- 更早十位小数合同重算的 114 ULP `STOP` 保持 `REJECTED`；它只证明有损 JSON 不足以逐位复刻旧 field。

## 3. 真实机制

- Python 重跑相同 `GN_PREVIEW_V1` FeatureGraph，取得舍入前 Pipe/segment/port 拓扑与 membership。
- 重跑分析与冻结 Curve 的 3009 个坐标分量最大 0 ULP；单一固定规模 Factor field 的 1003 项与旧 GN Spline Parameter 逐位一致。
- geometry-only Cutter 为固定 4 nodes / 3 links，不包含旧逐 segment Store 链，节点/连线不随 segment 数增长。
- Python 用分析 membership 与固定 Factor 直接批量写 23 个 Pipe FACE 和 32×3 个 segment FACE 属性；旧逐 segment POINT 仅作事后 oracle 比较，不是输入。
- 禁止机制均未使用：无 nearest/BVH/centroid、空间猜测、record/压缩通道、固定槽位/bitmask、station clamp、fixture/Edge 特判或逐 owner GN。

## 4. 阶段结果

### Phase 0 — `PASS`

- 冻结 blend：`/private/tmp/hst-prepared-preview.blend`，SHA-256 `d6e81f6accd181b5efa8d60a04b60018e3df4ce30672e586430b7505a4f2ddda`。
- source 1307/1988/683；Cutter 4012/7972/3986。geometry-only Cutter 与旧 Cutter fingerprint 同为 `51a31aa8362b6370e1f879b90e5314bfb4a69e16853f40a2ba4084e471556e70`。
- 冻结 wrapper 3863 nodes / 5747 links；Boolean 子组 592 / 808；实验后完全恢复，runtime 参数 fingerprint 前后一致。

### Phase 1 — `SEMANTIC_PASS`

- source 21 列 / 14343 元素逐位一致。
- Cutter 119 列 / 474334 元素：schema、domain、type 和离散 membership 全部一致。
- 保留 bitwise 诊断：13235 个派生 FLOAT 元素未逐位一致；首差为 segment station Face 258 的 `-0/+0`；最大 6 ULP / `2.38e-7`。
- 超出冻结双重容差的元素为 0，因此按用户批准的语义门槛通过。

### Phase 2 — `PASS`

- 完整 Python producer 实际送入同一 Boolean Pro；节点组、solver、operation、输入顺序和完整参数 fingerprint 未改变。
- Boolean 后几何完全一致：4195 Vertex / 4866 Edge / 680 Face，fingerprint `54b68282bb2fb8c0865cf4c2ee5ec6c15fa10a64737a4fa2f2a2b77d5ce5aa9f`。
- Intersection：旧/新均为 3872 raw、3868 unique、4 duplicate。
- 完整比较 81312 个身份标量，包含 Pipe/segment/Patch/port、Edge/Point membership、station、station² 与 cyclic interval。
- 离散差异为 0；包含 cyclic interval 重复派生值在内共保留 464 个 bitwise FLOAT 差异，最大 6 ULP / `8.94e-8`，超容差为 0。
- 下游实际消费的 segment 分组、工作项排序、station interval 与区间重叠决策继续由未修改 Bridge/Fill A/B 完整记录比较。

### Phase 3 — `PASS`

- 三次独立完整运行均包括：重跑分析、固定 Factor 求值、geometry-only Cutter、Python 全部属性生成/写入、同一 Boolean、完整后读取。
- 三次结果的 producer 中位数约 0.53 秒、最大约 0.55 秒；producer+Boolean+完整读取中位数约 0.81 秒、最大约 0.85 秒，均通过 1.0/1.5 与 2.0/2.5 秒门槛。精确分时以 `timings.json` 为准。
- 旧 79.61 秒仍标 `NOT COMPARABLE`：没有本轮可重放、逐阶段机器 artifact，不计算精确加速倍数。
- 后 Boolean per-owner materializer 未替代；它作为 oracle readout 实际求值，其耗时列入 Boolean/后读取分时，但不计作 Python producer 已替代的结论。

### 未修改 Bridge/Fill — `PASS`

- 两条 Boolean 结果的稳定业务记录逐项比较；工作项集合、顺序、segment 分组与区间判断语义一致。
- 最终几何完全一致：3922 Vertex / 8054 Edge / 4134 Face，fingerprint `c485119c3a9ba9654373fe77d0ec8ed151727f9b2b91ea386262de8b109fc067`。
- 旧/新均为 80 Bridge jobs / 3437 Bridge Faces、12 Fill jobs / 28 Fill Faces。
- Boundary、non-manifold、zero-area、self-intersection 均为 0。
- 仅排除跨独立 BMesh 不稳定的运行时 identity token 和输出对象名；稳定 Edge index 覆盖与全部业务记录均比较。

## 5. 结论

- 完整 Python 逐 segment 属性 producer 在冻结语义门槛下通过 Boolean 前、同一 Boolean 后、三次性能和未修改 Bridge/Fill 旁路验证。
- 结果最高为旁路 `PROTOTYPE / VERIFIED`；正式入口未集成，也未获得用户产品层 `ACCEPTED`。
- 后 Boolean materializer 仍是后续性能范围，不能由本轮结果推断已消除。

## 6. Artifacts

- 摘要：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/summary.json`
- Boolean 前：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/pre_boolean_comparison.json`
- Boolean 后：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/post_boolean_comparison.json`
- 三次分时与下游：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/timings.json`
- Phase 0：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/phase0-inspection.json`
- 日志：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/logs/`
- 最终运行：`/Users/apple/.codex/worktrees/1274/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_python_segment_attributes/logs/final-semantic-validation-2.log`
