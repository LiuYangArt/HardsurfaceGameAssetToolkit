# Feature Chamfer Python 逐 segment 属性等价验证计划

日期：2026-07-31  
状态：`EXECUTED / PROTOTYPE VERIFIED`  
范围：验证 Python 直接写入旧路径的全部逐 Pipe、segment、Patch 与 station 属性，能否替代动态 GN 属性生产网络，同时保持同一 Cutter、同一 Boolean Pro 和同一 Boolean 后身份输出。

关联经验：

- [`2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md`](2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md)
- [`../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`](../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md)
- [`../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md)

执行结论：Python 已能在不读取旧逐 segment 属性的前提下生成完整独立属性。第一次严格比较发现 station 派生浮点值最大相差 6 ULP / `2.38e-7`，其中首差只是 `-0` 与 `+0`；原差异完整保留。按用户批准的语义容差继续后，同一 Boolean、完整身份、三次完整性能和未修改 Bridge/Fill 均通过，最高状态为旁路 `PROTOTYPE / VERIFIED`。正式入口和后 Boolean materializer 尚未替换。

## 1. 要回答的问题

旧路径慢在运行时为每个 Pipe、segment、Patch 创建大量 GN 节点和连线；并未证明“每个 segment 一组独立 Mesh 属性”本身很慢。

本轮验证目标是：

1. 保留现有分析结果、Cutter 几何和 Boolean Pro；
2. 不再用动态 GN 网络生产逐 owner 属性；
3. Python 直接在 Boolean 输入几何上创建与旧路径同名、同 domain、同 data type、同数值的完整属性；
4. 让同一个 Boolean Pro 执行；
5. 比较 Boolean 前属性、Boolean 后完整身份和写入性能。

这里验证的是完整逐 owner 属性路径，不要求 Mesh attribute 数量固定。属性数量可以随 Pipe、segment 和 Patch 增长；硬约束是 GN node/link 数量不得随之增长。

## 2. 固定环境、样本和 oracle

- fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`
- Object：`Extruded.002`
- Radius：`0.01`
- Blender：macOS Blender 5.1.2
- 分析与 Pipe/segment 合同：复用同一次冻结结果
- Cutter：现有 GN Curve Pipe 的同一 evaluated Cutter Mesh
- Boolean：现有 Boolean Pro 的实际 Manifold Difference 分支，节点组、solver、输入顺序与参数不得改变
- Boolean 前 oracle：旧动态 GN 路径送入 Boolean 的 source Mesh、Cutter Mesh，以及其全部相关属性
- Boolean 后 oracle：已冻结的 3872 条原始 Boundary 记录、3868 个唯一 Edge、4 条重复记录及完整 Edge/Point 身份

旧正式路径只读。不得接正式入口，不得修改 Bridge/Fill、UI、operator 或 `auto_load.py`。

## 3. 目标路径和禁止机制

目标路径：

```text
冻结分析与 Pipe/segment 合同
  → 现有 GN 只生成相同 Cutter 几何
  → Python 在 source/Cutter Mesh 直接写入旧路径全部逐 owner 属性
  → 同一个 Boolean Pro
  → 比较 Boolean 后全部 Edge/Point 属性
```

允许：

- Python 直接创建、批量写入 Mesh attributes；
- 属性数量随 Pipe、segment、Patch 增长；
- 为了喂给同一 Boolean Pro 使用固定规模的临时节点/对象入口；
- JSON 只保存验证证据。

禁止：

- Python 动态创建每 owner 对应的 GN 节点或连线；
- 固定数量压缩属性、record 矩或外部账本解码替代本轮目标；
- nearest、BVH、centroid、空间容差猜属性；
- 单 owner、固定槽位、bitmask、station clamp、fixture/Edge ID 特判；
- 重建 Cutter、换普通 Boolean、修改 Boolean Pro 内部语义；
- 为通过比较而修改 Bridge/Fill；
- 图片、截图或渲染判定。

## 4. Phase 0 — 冻结同一次 Boolean 前输入

从一份已构建旧 Preview 或一次有界旧路径运行中，在 Boolean 节点输入边界分别导出：

- source 和 Cutter 的顶点、Edge、Face 拓扑与坐标；
- 所有参与身份传播的属性清单、domain、data type、长度和值；
- Pipe/segment/Patch 数与总属性数；
- 输入几何及每个属性的稳定 fingerprint。

Python 目标路径必须从相同分析合同和相同 Cutter 几何开始。不得拿 Boolean 后 Mesh 或旧路径已写好的属性冒充 Python producer。

Go：旧输入 oracle 完整且可独立重建 Python 属性。  
Stop：关键输入或字段确实无法冻结，并有 API、正式路径和替代读取审计证据。

## 5. Phase 1 — Python 写入 Boolean 前完整属性

Python 必须从 Pipe/segment/Patch 合同和几何对应关系直接生产：

- source Face 的逐 Patch membership；
- Cutter Face 的逐 Pipe membership；
- Cutter Face 的逐 segment membership；
- Cutter Face 的逐 segment station 加权值；
- Cutter Face 的逐 segment station² 加权值；
- 若旧 Boolean 输入还实际携带 Curve/Point 来源属性，也必须列明它们是 Boolean 输入必需字段还是只用于生成 Face 属性。

比较旧 GN 输入与 Python 输入：

- source/Cutter 几何 fingerprint 完全相同；
- 属性名称集合、domain、data type 完全相同；
- Boolean 实际消费的离散属性逐元素、逐位相同；
- station、station² 等派生 FLOAT 仍报告 bitwise、ULP 与绝对差，但语义门槛为：每项同时满足 `ULP ≤ 8` 且绝对差 `≤ 1e-6`；`-0` 与 `+0` 视为数值相同；
- 该容差只适用于派生位置 FLOAT，不适用于几何、拓扑、Pipe/segment/Patch/port 归属或属性 schema；
- 不允许比较器只看汇总、非零计数或 witness。

同时记录：Python 建表、属性创建、bulk write、Mesh 更新和总耗时；连续三次独立运行。

Go：Boolean 前几何、schema 与离散身份完全一致，所有派生 FLOAT 均在上述双重容差内。  
Stop：第一处明确差异；不得运行 Boolean 后比较。

## 6. Phase 2 — 同一 Boolean Pro 后完整等价

把旧输入和 Python 输入分别送入同一个 Boolean Pro。必须核对实际 runtime 的节点组、solver、输入顺序和参数 fingerprint 一致。

逐项比较：

- 输出 Mesh 顶点、Edge、Face 拓扑与坐标；
- 原生 Intersection Edges；
- 3872 raw / 3868 unique / 4 duplicate 的 multiplicity；
- 每条 Boundary Edge 的 Pipe、segment、Patch、port；
- Edge membership、station、station²；
- 两个 Vertex 的 segment membership、station、station²；
- cyclic station interval。

Go：几何、拓扑与离散身份零差异；派生 FLOAT 不超过 Phase 1 冻结的 `8 ULP / 1e-6` 双重容差；Bridge/Fill 使用的排序、区间重叠和工作项集合保持一致。  
Stop：记录第一处真实差异及其 Boolean 前对应输入；不得运行 Bridge/Fill。

## 7. Phase 3 — 性能与下游证明

只有 Phase 2 通过后运行：

1. 连续三次测量 Python 完整属性生产、Boolean、Boolean 后读取；
2. 与旧动态 GN 属性生产约 79.61 秒比较；
3. 将 Python 产生的同等属性交给未经修改的 Bridge/Fill，仅作旁路算法/产品证据；
4. 比较最终几何合同和 Bridge/Fill 诊断；最终视觉仍只交付 `.blend` 由用户人工验收，本轮不得代看图片。

性能硬门槛：

- Python 全部属性生产中位数 ≤ 1.00 秒，单次最大值 ≤ 1.50 秒；
- 属性生产 + Boolean + Python 读取中位数 ≤ 2.00 秒，单次最大值 ≤ 2.50 秒；
- 正确但超时与快速但不同都不算 PASS。

## 8. 状态和产物

- `PASS`：本阶段目标对象及全部字段通过硬门槛。
- `STOP`：出现明确、可复现的第一处语义或结果差异。
- `BLOCKED`：外部条件确实阻止验证，且已有正式路径反证与替代检查。
- `NOT RUN`：前置阶段未通过。
- `REJECTED` / `SUPERSEDED`：保留被审计驳回或纠正的旧结论。

独立任务必须维护：

- `tests/artifacts/feature_chamfer_python_segment_attributes/summary.json`
- `tests/artifacts/feature_chamfer_python_segment_attributes/pre_boolean_comparison.json`
- `tests/artifacts/feature_chamfer_python_segment_attributes/post_boolean_comparison.json`
- `tests/artifacts/feature_chamfer_python_segment_attributes/timings.json`
- `tests/artifacts/feature_chamfer_python_segment_attributes/logs/`
- `docs/validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md`

每阶段结束立即落盘。独立 worktree 的文档不会自动进入主工作区；主任务复核后只固化结果文档，不自动合并原型代码。
