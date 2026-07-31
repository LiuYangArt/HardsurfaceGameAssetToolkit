# Feature Chamfer Python Boolean 等价性验证计划

日期：2026-07-30  
状态：`CLOSED / SUPERSEDED FOR CURRENT ROUTE`  
范围：只验证 Cutter Pipe、Boolean 槽和 Boundary 身份；不接正式入口，不执行 Bridge/Fill。

> 2026-07-31：本计划的“纯 Python Cutter → Python Boolean”路线不再是当前性能主线。Cutter 与
> Boolean 已确认不是热点，用户决定保留现有 GN Cutter 和 Boolean Pro。有效历史证据与当前身份出口
> 结论见
> [`2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md`](2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md)。
> 除非固定规模身份出口路线被新的独立证据否定，不得重复从 Phase 1/2 开始验证。

## 1. 要回答的问题

本次验证只回答三个问题：

1. Python 能否生成与当前正式 GN 路径相同的 Cutter Pipe？
2. Python 能否复刻 Boolean Pro 当前实际生效的原生节点流程，切出完全相同的槽？
3. Python 能否复刻 Boolean Pro 内部用原生节点生成 Boundary Edges 和身份属性的方式，恢复完全相同的边界身份？

三个问题逐级验证。前一阶段不通过，后一阶段不开始。任何结果都只属于旁路 `PROTOTYPE`，
不能接入正式功能，也不能改动当前正确的 Bridge/Fill。

代表样本固定为：

- fixture：`feature-chamfer-topology-defect-mixed.blend`
- Object：`Extruded.002`
- Radius：`0.01`
- 产品矩阵 ID：`mixed__extruded_002__r0p010`

## 2. 总体方法

先把当前 GN 路径拆成三个可比较的边界：

```text
输入 Sharp Edge / Radius
  → A. Cutter Pipe Mesh
  → B. Boolean 后、尚未 Bridge/Fill 的开槽 Mesh
  → C. 带 Boundary / Pipe / segment / Patch / station 身份的开槽 Mesh
```

当前正式 GN 路径作为 oracle。Python 路径使用同一个输入文件、对象、Radius、变换和采样参数，
分别停在 A、B、C 三个边界输出可机器读取的 JSON 与 `.blend`。

禁止通过渲染图、截图或人工看图判定 PASS。自动验证只比较 Mesh、属性、拓扑和稳定 fingerprint。

## 3. Phase 0 — 拆解 Boolean Pro 的真实执行分支

在实现 Python 对照前，先读取受控资产中 Boolean Pro 当前参数和内部节点连接，记录 Feature Chamfer
实际走到的分支。只记录当前 Difference runtime，不复制无关的 Slice、Union、Intersect 或 UI。

必须明确：

- source 与 Cutter 进入 Boolean 前经过了哪些节点和变换；
- Cutter 是单 Mesh、多输入还是 Collection；
- Boolean solver、operation、self-intersection、hole tolerance 等实际参数；
- Boolean 后经过了哪些删除、合并、材质、法线或属性处理；
- `Boundary Edges` / `Intersecting Edges` 来自哪个原生节点输出；
- Pipe、segment、Patch、station 和 station squared 如何从输入 domain 传到输出 Edge/Point domain；
- 哪些节点只是当前动态身份编码，哪些节点会改变几何。

交付 `boolean_pro_runtime_map.json` 和一份简短说明。每个结论必须来自实际资产节点、socket 值和 links，
不能仅依据旧文档推测。

Go：当前生效分支和全部关键参数都可确定。  
Stop：资产版本或分支无法唯一确认。

## 4. Phase 1 — Python 复刻 Cutter Pipe

### 4.1 GN oracle

从当前正式 Preview 中只提取进入 Boolean 前的最终 Cutter Mesh，不包含 source Boolean 结果。

记录：

- 规范化 Vertex、Edge、Face fingerprint；
- Vertex/Edge/Face 数量；
- connected component 数量；
- closed manifold、boundary、non-manifold、zero-area 统计；
- 每个 component 的 bounding box、面积和体积；
- Pipe/segment membership、station 等 Boolean 前已有属性的 domain、类型和值 fingerprint；
- Object transform 已应用后的 source-local 坐标。

### 4.2 Python 对照

Python 复用当前已正确的 FeatureGraph、ChamferPlan、Curve 点和 Pipe 参数，但不创建正式 Preview wrapper。

优先顺序：

1. 先用 Python 驱动当前 Curve Pipe 资产，只把最终 Cutter 评估为 Mesh；
2. 若这一过程仍依赖会随模型规模增长的动态节点，只保留固定 Curve-to-Mesh 几何资产；
3. 只有固定资产仍无法单独调用时，才用 Python/BMesh 直接生成 Pipe Mesh；此时必须另外证明采样、
   环方向、端盖和 junction 形状等价。

### 4.3 比较与门槛

必须完全一致：

- 规范化几何 fingerprint；
- 拓扑计数和 component 划分；
- closed manifold 与退化统计；
- Pipe/segment 对应的 Face/Point 集合。

连续三次结果稳定后 Phase 1 才通过。性能只记录，不作为本阶段主要结论。

Go：Python 产生的 Boolean 输入 Cutter 与 GN oracle 等价。  
Stop：需要修改 Pipe 形状、采样、端盖或 junction 规则才能继续。

## 5. Phase 2 — Python 复刻 Boolean 槽

### 5.1 固定输入

GN 与 Python 必须消费 Phase 1 已证明等价的同一份 source-local Cutter Mesh。不得一边使用 Curve，
另一边使用近似重建的 Mesh。

### 5.2 Python 实现

按照 Phase 0 的 runtime map，用 Python 调用 Blender 原生能力逐步复刻 Boolean Pro 当前分支：

- source 临时副本与 transform；
- Cutter 输入组织；
- Manifold Difference 及全部实际参数；
- Boolean 前后的几何处理；
- 材质索引、Face 方向和必要属性处理。

本阶段先比较“开槽几何”，不要求 Python 恢复 Boundary 身份。为了避免身份实现影响几何比较，
GN oracle 与 Python 对照都移除只用于诊断的属性后再计算几何 fingerprint。

### 5.3 比较与门槛

比较：

- 规范化 Vertex、Edge、Face fingerprint；
- Vertex/Edge/Face 数量；
- source-derived 与 cutter-derived Face 的空间集合；
- boundary、non-manifold、zero-area 和自交统计；
- connected component、面积和体积；
- Face winding、材质索引和法线合同；
- 正序、逆序输入运行的稳定性。

离散集合必须完全一致。浮点容差在运行 Python 对照前，根据 GN oracle 三次自身波动冻结，不得看到
差异后放宽。

Go：Python 切出的槽与 Boolean Pro oracle 等价。  
Stop：需要修改 Cutter、使用其他 solver、后处理补面或按 fixture 特判才能相等。

## 6. Phase 3 — Python 复刻 Boundary 身份

### 6.1 首选路线：照搬 Boolean Pro 的原生节点语义

先确认 Phase 0 中 Boundary Edges 的精确来源。如果它确实是原生 Boolean 节点的
`Intersecting Edges` / `Boundary Edges` 输出，再确认 Python API 是否直接暴露等价选择。

- 若 Python API 能直接读取：直接使用并比较；
- 若 Modifier 只返回 Mesh、不暴露选择：在独立临时固定 GN probe 中，仅执行同一个原生 Boolean 节点
  并把该 selection 写入 Mesh，作为“原生节点输出读取器”；这只用于验证 Blender 暴露能力，
  不是目标正式架构；
- 同时验证能否从 Boolean 输出的 source-derived / cutter-derived Face 邻接关系，纯 Python 确定性地
  重建同一 Edge 集合；如果完全一致，目标 Python 路径不需要 GN selection reader。

这一步的重点是复制原生节点的实际语义，不是重新发明 Boundary 猜测算法。

### 6.2 身份属性复刻

按 Phase 0 记录的 domain 转换和属性传播方式，用 Python 批量写入 Boolean 前的完整稀疏标签：

- source Surface Patch membership；
- Cutter Pipe membership；
- segment membership；
- station 与 station squared；
- junction/port 所需的多 owner 事实。

Boolean 后只对已经证明等价的 Boundary Edge 集合读取并整理属性。一个 Edge 可以拥有任意数量的
owner，不允许压成单值、固定槽位或固定 bitmask。

### 6.3 比较与门槛

为每条 Boundary Edge 使用方向无关的端点坐标作为稳定 key，逐 Edge 比较：

- Boundary Edge universe；
- Pipe owner set；
- segment membership set；
- source Patch set；
- endpoint/port 身份；
- Edge/Point station 与 station squared；
- missing、unknown、conflict 和 multi-owner 统计。

Go：Boundary Edge 集合及每条 Edge 的全部身份与 GN oracle 一致。  
Stop：需要 nearest、BVH、centroid、主 owner、station clamp、fixture 名称或固定 Edge ID 才能补齐。

## 7. 本次明确不做

- 不调用现有 Bridge/Fill；
- 不生成最终 Feature Chamfer 产品 Mesh；
- 不修改正式 Operator 或 UI；
- 不删除当前正确慢路径；
- 不运行 10-cell 矩阵、GUI 或完整回归；
- 不做缓存、Rust、多线程或进一步性能优化；
- 不生成、读取或比较图片；
- 不把 prototype 成功表述为 `INTEGRATED` 或 `VERIFIED`。

## 8. 产物与结果报告

建议产物目录：`tests/artifacts/feature_chamfer_python_parity/`。

至少包含：

- `environment.json`
- `boolean_pro_runtime_map.json`
- `phase1_cutter_oracle.json`
- `phase1_cutter_python.json`
- `phase1_comparison.json`
- `phase2_groove_oracle.json`
- `phase2_groove_python.json`
- `phase2_comparison.json`
- `phase3_boundary_oracle.json`
- `phase3_boundary_python.json`
- `phase3_comparison.json`
- `summary.json`
- `oracle.blend` 与 `python.blend`，只供后续用户需要时手动打开，不作为自动 PASS 证据。

最终 `summary.json` 对三个阶段分别给出：

- `PASS`：等价，附耗时和 artifact；
- `STOP`：不等价，附第一处最小差异和证据；
- `BLOCKED`：环境或 Blender API 无法继续，附具体阻断。

验证完成后只同步事实：哪一阶段通过、第一处差异是什么、GN 是否仍有必要、下一步有哪些可选路线。
在用户确认前不扩展后续正式性能计划。

## 9. 最终历史结论

- 严格纯 Python Cutter：拓扑计数一致，但坐标 fingerprint 不一致，第一处约 `1e-5` 量级差异；`STOP`。
- 此 STOP 不代表当前性能路线失败，因为 Cutter/Boolean 不是热点，当前路线继续保留它们。
- 早期“Phase 1/2/3 全部 PASS”使用了 Python 编排 GN，不属于纯 Python，已作废。
- Boolean 原生相交边可以通过固定规模出口稳定物化；该结论由 2026-07-31 的新验证替代本计划中对
  selection reader 的不确定判断。
