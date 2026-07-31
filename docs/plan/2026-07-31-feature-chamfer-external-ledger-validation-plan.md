# Feature Chamfer 外部身份账本验证计划

日期：2026-07-31  
状态：`COMPLETED / PROTOTYPE STOP AT ENDPOINT CONTRACT`  
范围：验证“完整身份存 Python 外部账本，Boolean 只携带最小映射数据”是否可替代动态 GN one-hot。

关联经验：[`2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md`](2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md)  
当前计划：[`2026-07-30-feature-chamfer-performance-optimization-replan.md`](2026-07-30-feature-chamfer-performance-optimization-replan.md)

验证结果：[`../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`](../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md)

最终结果：Edge 级外部账本映射在全部 3872 条原始记录上零差异；完整身份仍有 89 条 Point/endpoint
差异，因此停在 Phase 2。Phase 3–4 未运行。后续不得重复 Edge record、Boundary 或 Face INT 试验，只研究
端点贡献者映射。

## 1. 要回答的核心问题

外部账本和 GN 属性记录的数据可以完全相同，区别只在于：

- 外部账本能保存任意长度的多 owner 集合，创建和查询成本低；
- 但 Boolean 会新建、拆分和合并 Face/Edge，外部账本不会自动知道输出元素来自哪条输入记录；
- GN one-hot 的作用不是“数据更丰富”，而是借 Blender Boolean 的属性传播自动建立输入到输出的对应关系。

本轮因此不讨论 JSON 是否能存数据——它当然能。唯一需要实证的是：**能否用固定数量的 Mesh
attributes 建立可靠的 Boolean 前后映射，随后用 Python 内存账本恢复与旧 one-hot 完全相同的身份。**

运行时使用 Python 内存结构；JSON 只用于保存验证证据，不作为正式热路径数据库。

## 2. 固定范围与 oracle

- fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`
- Object：`Extruded.002`
- Radius：`0.01`
- Blender：macOS 已安装的 Blender 5.1.2
- 正式 Cutter：保留当前 GN Curve Pipe
- 正式 Boolean：保留当前 Boolean Pro 的实际 Manifold Difference 分支
- oracle：2026-07-31 已冻结的 Boolean 后、Bridge 前逐 Edge 完整身份 ledger
- 已冻结 Boundary：3872 条原始记录、3868 个唯一端点键，重复组口径不得再次误判
- 已冻结首差：Boundary-only 恢复在第一条 Edge 丢失 Pipe 5

旧正式路径和 oracle 只读。不得接正式入口，不得修改 Bridge/Fill、UI 或 `auto_load.py`。

## 3. 目标架构与允许机制

```text
Python 内存 ledger
  输入 Face/Curve/segment record → 任意长度 Pipe/Patch/segment/port/station 事实

现有 GN Cutter + Boolean Pro
  只携带固定数量的映射 attributes
  + 输出原生 Intersection Edges

Python
  输出 Face/Edge 映射 → 回查 ledger → 生成旧 Direct Bridge 完整合同
```

允许：

- Python dict/list/array 保存完整身份；
- JSON 保存 oracle、诊断和比较结果；
- 固定数量的 INT/FLOAT/BOOLEAN/VECTOR Mesh attributes 穿过 Boolean；
- 从当前 plan、source/Cutter 拓扑确定性推导数据；
- 如 Python 经验证成为热点，再单独评估预编译扩展，但不得提前改变语义。

禁止：

- 随 Face、Pipe、segment、Patch 或 Point 数量增长的 GN nodes/links；
- 每个 owner 一列的动态 one-hot 作为目标路径；
- nearest、BVH、centroid、空间容差猜 owner；
- 单 owner、主 owner、固定槽位、固定 bitmask、station clamp；
- fixture 名称或固定 Edge ID 特判；
- 重写 Cutter、改用普通 Boolean Modifier或修改 Bridge/Fill 以绕过差异；
- 图片、截图或渲染判定。

## 4. Phase 0 — 复用证据并建立实验底座

不得重新支付约 80 秒构建旧动态图，除非已有 oracle 无法回答某个具体字段。

必须读取并复用：

- 完整旧逐 Edge ledger；
- 固定相交边出口的三次计时与比较；
- 首个 Pipe 5 失败 Edge；
- 现有 plan 与 Pipe/segment 合同。

先将独立 worktree 的关键 oracle 复制到本轮 artifact 目录，记录来源 SHA，不改变内容。

Go：上述证据可直接用于逐 Edge 比较。  
Stop：oracle 缺少本轮必要字段且无法通过一次有上限的旧路径运行补齐。

## 5. Phase 1 — 首个 Pipe 5 差异的逐层追踪

只追踪第一条失败 Edge，不先设计完整编码。记录：

1. oracle 的 Pipe、segment、Patch、station、station² 和端点身份；
2. 对应输入 source/Cutter Face 的所有事实；
3. Boolean 前固定候选属性值；
4. Boolean 输出相邻 Face 的候选属性值；
5. 原生相交边上的 domain adaptation 结果；
6. 身份首次丢失的准确层级。

至少分别试验：

- 单一稳定 Face record ID；
- 输入来源类型 + record ID；
- Pipe/segment 的数值 record ID；
- station 一阶矩与二阶矩；
- 必要时两个独立哈希/校验列，用来判断 ID 被插值、合并或覆盖，不能用哈希冒充 owner 集合。

Go：能精确说明 Pipe 5 在哪一层丢失，以及至少一种固定属性能把必要映射带到输出。  
Stop：所有固定候选载体在 Boolean 中都不可逆地丢失映射，并有逐层证据。

## 6. Phase 2 — 固定映射 + 外部账本恢复完整身份

根据 Phase 1 的最小映射，构建 Python 内存账本：

- source Face record → Patch 集合；
- Cutter Face/segment record → Pipe、segment、port 与 station 参数；
- record 允许引用任意长度 owner 集合；Mesh 上只保存映射键，不保存完整集合。

Boolean 后从原生相交边及其相邻 Face/Point读取映射键，回查账本，逐 Edge 恢复：

- Boundary universe 与 multiplicity；
- Pipe owner set；
- segment set；
- Patch set；
- port/endpoint 身份；
- Edge/Point membership、station、station²；
- cyclic station 区间。

离散集合必须完全一致。浮点使用旧 oracle 冻结的一 float32 ULP 容差，不得看到差异后放宽。

Go：3868 个唯一 Edge 的完整身份逐字段等价，且禁止机制均未使用。  
Stop：首处明确差异；不得跨到 Bridge/Fill。

## 7. Phase 3 — 信息消融与最小合同

Phase 2 通过后，逐项去掉候选属性，回答哪些数据必须穿过 Boolean、哪些可由 plan/ledger 推导：

- source/Cutter 来源类型；
- Face record；
- Pipe/segment record；
- Patch record；
- station 一阶矩；
- station 二阶矩；
- endpoint/port record。

每次只改变一项并运行完整逐 Edge身份比较。最终合同必须固定属性数，不随输入规模增长。

Go：找到唯一或充分最小的固定合同，并解释每列用途。  
Stop：只有恢复动态 one-hot 才能等价。

## 8. Phase 4 — Bridge/Fill 与性能

只有完整身份通过后，才把恢复的合同交给未经修改的 Direct Bridge/Fill。

比较最终几何、Chamfer Face、Bridge job、junction Fill、方向与法线。连续三次独立运行记录：

- 固定属性出口构建与 Boolean 求值；
- Python 读取、账本回查与身份恢复；
- Bridge/Fill；
- prototype 总耗时。

性能门槛：

- 属性出口 + Python 恢复中位数 ≤ 0.70 秒，单次最大值 ≤ 1.00 秒；
- 完整 prototype 中位数 ≤ 2.00 秒，单次最大值 ≤ 2.50 秒；
- Python 恢复若超过预算，必须先剖析；只有纯数组/图计算成为真实热点，才评估 C++/Rust/Cython
  预编译扩展。Blender 数据访问仍留在主线程。

## 9. 状态与产物

- `PASS`：本阶段全部合同和机制约束同时成立。
- `STOP`：出现明确、可复现的首处语义差异。
- `NOT RUN`：前置门槛未通过。
- `BLOCKED`：外部条件确实阻止验证，且已有反证审计。
- `REJECTED`：旧轮证据无效，保留审计原因。

独立任务必须维护：

- `tests/artifacts/feature_chamfer_external_ledger/summary.json`
- `tests/artifacts/feature_chamfer_external_ledger/phase1_trace.json`
- `tests/artifacts/feature_chamfer_external_ledger/identity_comparison.json`
- `tests/artifacts/feature_chamfer_external_ledger/ablation.json`
- `tests/artifacts/feature_chamfer_external_ledger/timings.json`
- `docs/validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`

每阶段结束立即落盘。固定出口单次超过 60 秒立即终止并记录；不得静默等待。独立 worktree 的结果文档
不会自动进入主工作区，主任务复核后再固化，不自动合并原型代码。
