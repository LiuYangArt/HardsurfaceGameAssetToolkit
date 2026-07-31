# Feature Chamfer 性能优化重新规划

日期：2026-07-30
更新：2026-07-31
状态：`INTEGRATED / VERIFIED`；固定两阶段与批量安全检查已进入正式一步入口，完整性能门槛通过
正确性基线：旧正式结果继续作为只读 oracle。2026-07-31 已把固定 raw Boolean、Python 后置身份、固定 Surface 与批量 Bridge/Fill 安全检查一次性接入正式入口。Mixed / Radius 0.01 三次冷运行保持完全相同的最终 fingerprint，中位约 1.23 秒、最大约 1.23 秒，已同时通过结果等价与 2 秒性能硬门槛。完整产品矩阵已通过；自动验证最高为 `VERIFIED`，仍等待用户在 Blender 中做最终视觉确认。

历史计划：[`2026-07-30-feature-chamfer-preview-performance-plan.md`](2026-07-30-feature-chamfer-preview-performance-plan.md)  
失败复盘：[`2026-07-30-feature-chamfer-performance-rewrite-failure.md`](../postmortem/2026-07-30-feature-chamfer-performance-rewrite-failure.md)

2026-07-31 验证记录：
[`2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md`](2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md)

外部账本完整验证：
[`../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`](../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md)

Python 完整逐 segment 属性验证：
[`../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md)

正式入口集成结果：
[`../validation/2026-07-31-feature-chamfer-python-pre-boolean-formal-integration-result.md`](../validation/2026-07-31-feature-chamfer-python-pre-boolean-formal-integration-result.md)

Boolean 后端点来源验证：
[`../validation/2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md`](../validation/2026-07-31-feature-chamfer-endpoint-provenance-carrier-validation-result.md)

Boolean 后共享批次压缩验证：
[`../validation/2026-07-31-feature-chamfer-overlap-batch-compression-validation-result.md`](../validation/2026-07-31-feature-chamfer-overlap-batch-compression-validation-result.md)

Boolean Pro 内部身份传播审计：
[`../validation/2026-07-31-feature-chamfer-boolean-pro-internal-provenance-validation-result.md`](../validation/2026-07-31-feature-chamfer-boolean-pro-internal-provenance-validation-result.md)

Boolean 后 Python field adaptation 验证：
[`../validation/2026-07-31-feature-chamfer-python-field-adaptation-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-field-adaptation-validation-result.md)

Python Cutter 与 Boolean 控制验证：
[`../validation/2026-07-31-feature-chamfer-python-cutter-boolean-control-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-cutter-boolean-control-validation-result.md)

固定两阶段端到端验证：
[`../validation/2026-07-31-feature-chamfer-fixed-two-stage-end-to-end-validation-result.md`](../validation/2026-07-31-feature-chamfer-fixed-two-stage-end-to-end-validation-result.md)

批量安全检查与正式集成结果：
[`../validation/2026-07-31-feature-chamfer-fixed-two-stage-batched-validation-result.md`](../validation/2026-07-31-feature-chamfer-fixed-two-stage-batched-validation-result.md)

## 0. 2026-07-31 路线更新

以下条目按时间顺序保留；前面的 `STOP` 与“未接入”记录是当时的门禁结论，已被本节末尾的新证据取代。

- 外部压缩账本路线保留为历史 `STOP`，不再作为当前正式接入方案。
- 新验证保留每个 Patch/Pipe/segment 各自独立的完整属性，但改由 Python 批量写入 Mesh，不再为这些属性动态展开 GN。
- Boolean 前 474334 个 Cutter 属性元素中存在 13235 个 float32 逐位差异；最大 6 ULP / `2.38e-7`，首差为 `-0/+0`。用户确认其无业务意义，并冻结 `ULP ≤ 8` 且绝对差 `≤ 1e-6` 的派生浮点容差；离散身份、schema、几何和拓扑仍要求完全一致。
- 同一 Boolean 后 81312 个身份标量中仅 464 个派生浮点逐位差异，最大 6 ULP / `8.94e-8`，零项超容差；Intersection 仍为 3872 raw / 3868 unique / 4 duplicate。
- 未修改 Bridge/Fill 的工作项、顺序、区间判断和最终几何全部一致；三次完整 Boolean 前 producer 中位数约 0.53 秒，连同 Boolean 与完整读取约 0.81 秒。
- 当前接入边界只到 Boolean 输入：替换旧 source Patch、Curve segment POINT 和 Cutter FACE 动态属性生产。Boolean Pro 与 Boolean 后 materializer 保持原样，后者另行验证和优化。
- 正式入口现已使用固定 3 个输入节点和 3 条连线消费 Python 准备的 source/Cutter Mesh；旧的 Boolean 前逐 Patch/Pipe/segment 动态属性节点不再进入正式运行时。
- Mixed / Radius 0.01 的正式一步式运行再次命中冻结 fingerprint 与 3922/8054/4134/3454 统计；本次整套运行中 Python producer 为 0.021 秒，但总耗时为 4.635 秒。剩余主要耗时已移到 Boolean 后动态身份整理和 Bridge/Fill，完整任务不得宣称达到 2 秒目标。
- Blender 5.1.2 全量回归 156/156 通过；当前状态仅表示这次替换已集成并自动验证，不表示完整性能计划完成或用户视觉验收完成。
- Boolean 后端点来源旁路已完成：逐 segment 动态 batch 在 3872 条 raw Boundary、7744 组 endpoint-segment 上恢复的 membership、station、station² 全部逐位一致，证明 Python 后整理并不存在语义不可行障碍。
- 历史 32 次 Boolean 原型需要约 6.12 秒，后续 4 批原型约 0.739 秒；两者均只保留为诊断 oracle，已被最新“单次 Boolean + Python field adaptation”结果取代，不再是当前性能判断。
- Boolean Pro 原始资产与正式副本审计纠正了责任边界：原始资产为 184 nodes / 260 links；正式运行时副本为 592 / 808。逐 Pipe/segment 身份通道不是 Boolean Pro 自带，而是 Feature Chamfer 写入 Cutter FACE attribute 并在 Boolean 后向副本注入 EDGE/POINT Store。原生 Boolean 仍只有 Mesh 与 Intersecting Edges 两个输出。
- 最新验证已完成真实 domain adaptation 复刻：Edge 133 / segment 24 首差与全部 3872 raw Boundary / 7744 endpoint-segment 均通过；最大 2 ULP / `9.934107070286302e-8`，NumPy 物化中位约 0.0287 秒。
- 早期 `STOP` 的执行时序问题已经定位：236 个动态 Store 位于 Boolean 原始输出和 Surface/static tail 之间；最终 Mesh 已丢失来源信息，所以不能在旧 wrapper 求值完成后补算。
- “只删除 236 个动态 Store、其余 GN 完全不动”已被证据否定；后续选择了持久化中间 Mesh 的固定两阶段路线继续验证。
- 后续独立验证已证明第二条路线可行：固定 5-node 原生 Boolean 内核输出 raw Mesh 与切口属性，Python 物化236层，再由固定 Surface 删除阶段处理。最终几何、Boundary消费身份、材质、Sharp与normal一致；三次阶段总耗时中位约0.082秒。完全无 GN 仍无法取得 Intersecting Edges，因此应保留极小的原生 Boolean 节点内核。
- Python 直接生成 Cutter 尚未完成 Curve-to-Mesh frame/tilt transport 等价验证，不能宣称失败；当前性能路线继续保留已验证等价且固定规模的 Cutter GN。
- 随后的完整端到端旁路已补齐未修改 Bridge/Fill 证据：三次均命中冻结 fingerprint、3922/8054/4134/3454、80/3437 Bridge 和 12/28 Fill，结果等价门槛通过。
- 但三次完整冷运行约3.406/3.424/3.440秒，超过2秒产品门槛；其中上游两阶段准备约0.62–0.65秒，Bridge/Fill约2.77秒。Boolean后Python身份只约0.014秒，新的主瓶颈已明确位于Bridge/Fill。
- 按硬门槛，固定两阶段没有接正式入口；测量修改已撤回，正式runtime保持上一版已验证架构。后续须先独立优化Bridge/Fill并与固定两阶段上游组合达到2秒，再考虑一次性正式集成。
- 随后的热点剖析纠正了“Bridge 几何操作本身慢”的判断：80 次 Bridge、12 次 Fill 与一次最终检查各自重复重建整份 Mesh 的三角化/BVH，自交检查共调用 94 次、约占 2.29 秒。
- 新实现没有删除安全门禁，而是按几何阶段合并为最多三次：全部 Bridge 完成后一次、全部 Fill 完成后一次、最终清理后一次。结构检查、失败码、最终闭合/非流形/零面积/自交门禁仍保留。
- 正式 Mixed / Radius 0.01 三次结果均为冻结 fingerprint `f991...` 与 3922/8054/4134/3454；耗时约 1.227/1.226/1.222 秒。自交检查从 94 次降为 3 次、约 0.086 秒。
- 第一阶段与延期范围产品矩阵 `run_go=true`；正式入口已使用固定 Boolean、Python 身份物化和固定 Surface，不再建立随 segment 增长的 Boolean 后动态 Store。

## 1. 实际要改什么

历史流程首先慢在“给几何贴身份标签”；现已验证可用固定两阶段把这部分降到约 0.65 秒以内。
完整端到端测量当时表明 Bridge/Fill 阶段约 2.77 秒；随后剖析已把其中 2.29 秒定位为重复自交检查，并完成优化。

正式入口现在保留正确的 GN Cutter 与受控 Boolean 内核；Boolean 前身份、Boolean 后 236 层适配均由 Python
批量写 Mesh attribute。Bridge/Fill 几何算法保持不变，只把逐 job 重复的全 Mesh 自交检查合并为阶段检查。

正式目标不是纯 Python 重写 Cutter 或 Boolean。GN 可以继续承担固定规模的 Cutter、Boolean 和属性出口；
禁止的是随 Face、Pipe、segment 或 Point 数量增长的运行时身份节点网络。

### 1.1 当前慢路径

```text
分析 Sharp Edge，得到 Pipe 与 segment
  → 生成与当前一致的 Cutter Curve
  → Boolean 前后都为每个 Face / Pipe / segment / station 动态创建节点和连线（历史约 80 秒）
  → Manifold Difference
  → 从 Boolean 结果读取 Boundary 与身份
  → 当前正确的 Bridge / Fill
```

### 1.2 当前目标路径

```text
分析 Sharp Edge，得到同一份 Pipe 与 segment
  → 现有 GN Curve Pipe 生成相同 Cutter
  → Python 批量写入 source/Cutter 的完整 Boolean 前身份
  → 固定规模输入执行同一 Boolean
  → 固定 raw Boolean 输出 Boundary，Python 批量物化 Boolean 后身份
  → 固定 Surface 删除阶段
  → 转换成当前 Bridge 已经读取的数据格式
  → 不修改当前 Bridge / Fill，直接生成最终结果
```

换句话说，新实现不会重新发明 Cutter、Boolean 或倒角连接。它只把“创建几千个节点来记账”
换成“固定出口保留不可推导的事实，Python 在内存中记账”。

### 1.3 具体实现步骤

1. **原样复用现有分析、Cutter 和 Boolean**
   - 继续使用当前已经正确的 Sharp Edge 分组、Pipe、segment 和 station 计算；
   - 继续使用当前 Curve Pipe 资产生成 Cutter，保证 Cutter 形状不变；
   - 继续使用受控 Boolean Pro 的实际 Difference 分支与原生相交边选择；
   - 不再验证纯 Python Cutter 或普通 Boolean Modifier，除非当前路线以后被独立证据否定。

2. **直接消费现有逐 segment FACE attribute**
   - Boolean 前 schema 已由正式 Python producer 保留，不再搜索新的 domain 或压缩 carrier；
   - 已证明同一次 Boolean 原始输出上的同名 FACE attribute 可被 Python 正确读取；
   - Python 按现有 GN 的真实 domain adaptation 生成 EDGE/POINT 值，不重新猜 owner；
   - 不允许调用旧 Boolean 后动态 Store，也不增加随 Pipe、segment 或 Point 数增长的节点和连线。

3. **一次扫描复刻现有后置物化**
   - 只遍历 Boolean Pro 已标记的真实相交边；
   - 逐项复刻现有 FACE → EDGE 与 FACE → POINT 的 field adaptation，而不是从最终 Face 邻接反推；
   - 为一条边保存任意数量的 Pipe、segment、Patch 和 port 归属，并读取 station 与 station squared；
   - 任何标签缺失、冲突或传播不完整都直接报错，不补默认值。

4. **增加一个薄适配层**
   - 将上一步的多值记录写成当前 Bridge 已经读取的 Edge/Point/Patch layers；
   - 适配层不选择左右边、不切分环、不创建 Bridge job，也不 Fill；
   - 现有 Bridge/Fill 代码保持不变，用它来证明前面的替换没有改变几何语义。

5. **优化当前新的主瓶颈（已完成）**
   - 完整旁路已经证明步骤 1–4 正确，但总耗时仍为约 3.42 秒；
   - 现有 Bridge/Fill 占约 2.77 秒，必须先在独立原型中定位重复全 Mesh 扫描、重复自交检测和邻接重建；
   - 实测热点是重复自交检查，不是 Bridge/Fill 的几何生成；合并后完整正式入口达到约 1.23 秒。

6. **接入一步式正式入口（已完成）**
   - 旁路原型先通过 Mixed / Radius 0.01 的结果与 producer 阶段预算，再接入；
   - 接入后正式 wrapper 的 Boolean 前输入固定为 3 个节点和 3 条连线；
   - Boolean 后 materializer 已改为一次 Python 批量适配，动态节点数为零；
   - Radius、Keep Cutter、Redo/Undo、source 不变和失败清理行为保持现状。

### 1.4 已完成的首个技术实验

实验结论已经冻结：固定规模出口可在约 0.20 秒内导出完全相同的相交边集合；Python 读取和初步恢复
约 0.27 秒。但只凭相交边和相邻 Face，第一条身份比较就丢失 Pipe 5，因此“Boundary-only”路线已
明确失败。该结论只否定最终 Face 邻接猜测；后续结构审计已把下一步收敛为复刻现有 FACE → EDGE/POINT
field adaptation，不再重做 Cutter/Boolean，也不再搜索压缩身份事实。

详细数字、旧身份生成链和禁止重复的实验见 2026-07-31 验证记录。

后续完整验证纠正了 Face 整数的解释：raw INT 是被 membership 加权的一阶矩，不能直接当 record ID；
归一化后可在全部 3872 条记录上恢复正确的 Edge 级 Pipe/segment/Patch/port 与 station 合同。真正首差
位于 Boolean Point 的端点事实传播，共 89 条差异。该阶段曾把下一步限定为 Point/endpoint 贡献者映射；
后续原始资产与运行时注入结构审计已取代这一方向：直接保留现有完整 FACE schema，复刻它在 POINT
context 的求值。不得重复 Boundary、Face record 或 Edge 级 ledger 试验。

端点来源验证随后完成了这一缺口：32 次逐 segment Boolean 在全部 7744 组端点数据上逐位零差异，
原先 89 条差异已全部消除。这证明端点语义能够恢复；同时也测明直接逐 segment 批处理不可用于性能方案，
因为批次数随 segment 数增长且仅 Boolean 累计就约 6.12 秒。后续应以该正确实现作为诊断 oracle，
该 32-pass 结果只作为完整语义 oracle；不得再把它或局部载体失败表述为 Python 路线失败。

共享批次实验进一步证明：从输入 plan、Cutter 拓扑和 Edge ledger 独立建立冲突图，可把 32 个 segment
压缩为 4 批且逐位等价；该 39-edge 冲突图经精确检查不可分为 3 批。其 0.739 秒结果现已由单次 Boolean
原始输出上的 0.0287 秒 Python 物化取代；共享批次不再是候选实现，只保留为历史语义证据。

Boolean Pro 内部审计进一步明确：固定 carrier 不是必要前提。原始 Boolean Pro 本体没有逐 segment
通道；Feature Chamfer 已经掌握完整身份并把它们写入 Cutter FACE。该审计把当时待验证的问题缩小为：
在保留同一输入 schema 与同一次 Boolean 的情况下，Python 能否直接消费 Boolean 传播后的同名 FACE
attribute，并逐项复刻当前 GN 后置 Store 在 EDGE/POINT context 中得到的值。此前“只凭最终 FACE
邻接”失败不能否定这条路线，因为那次没有复刻 GN field adaptation。

随后 field adaptation 验证已把该问题回答完整：Python 在同一次 Boolean 原始输出上可以准确复刻全部
236 层，且耗时远低于预算。失败的是原计划假定的执行位置——在一次 modifier 求值内部，Python 无法
插入 Boolean 与后续 Surface/static tail 之间；等最终 Mesh 可由 Python 读取时，119 个 owner FACE 来源
已经变为全零。后续不得再重复验证转换公式，也不得把这一结果描述为 Python 或 Boolean 能力失败。

## 2. 为什么选择这条实现路线

本轮不再以“重写完整 Python 后端”为首要路线。第一次失败同时替换了身份表达、Boolean 组织、
Boundary 绑定和 Bridge/Fill 语义，结果虽然快，却出现重复面、拉伸面和错误封口。

新路线保留当前正确的 FeatureGraph、ChamferPlan、Curve/Pipe 几何、受控 Manifold Difference、
Boundary 选择、Direct Bridge、junction Fill、法线和事务行为，只替换已经测明的 80 秒瓶颈。

它仍是待证伪的技术假设。成功定义不是“减少了节点”或“某个 Boolean 很快”，而是同一正式结果
从约 97–176 秒降到不超过 2 秒，并且用户可见几何不变。

## 3. 已知事实与待重新冻结的数据

### 3.1 已知事实

历史测量基于 Blender 5.1.2、Mixed、Radius 0.01：

| 阶段 | 历史耗时 | 结论 |
|---|---:|---|
| FeatureGraph、Plan、Curve | 优化后中位数约 0.493 秒 | 已不是主瓶颈 |
| 动态 Geometry Nodes 身份编码 | 约 79.87 秒 | 首要且明确的瓶颈 |
| 其中 source Face one-hot | 约 53.6 秒 | 最大单项 |
| 其中 Curve Point / segment one-hot | 约 15.4 秒 | 第二大单项 |
| Cutter / Boolean 强制求值 | 约 0.10 秒 | 几何运算本身不是当前主瓶颈 |
| Preview 已存在后的 Direct Bridge Finalize | 历史约 0.27 秒；最新完整旁路约 2.77 秒 | 必须按最新正式规模重新剖析，不能沿用历史判断 |

动态 wrapper 历史规模为 3863 nodes / 5747 links。本轮已消除其中 Boolean 前生产网络；正式一步入口
仍会临时建立包含 Boolean 后动态 materializer 的 Preview，所以完整性能问题尚未消除。

现有产品矩阵已冻结 Mixed / Radius 0.01 的第一层最终结果：

| 项目 | 基线 |
|---|---:|
| 规范化几何 fingerprint | `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107` |
| Vertex | 3922 |
| Edge | 8054 |
| Face | 4134 |
| Chamfer Face | 3454 |

这些数据可以防止重复面、拉伸和错误封口再次假绿，但还不足以单独证明完整语义等价。

### 3.2 开工前必须重新冻结

历史 `/private/tmp` 数据只作为路线依据，不作为本轮完成证据。Phase 0 必须在当前 Mac mini、当前
Blender、当前正确正式入口上重新测量并把产物写到仓库持久 artifact 目录，至少记录：

- Blender 完整版本、fixture SHA、源代码状态、对象、Radius 和全部公开参数；
- 三次独立冷运行及三次同进程重复运行；Blender 启动时间不计入 Operator 时间；
- `analysis_plan`、`curve_cutter`、`identity_producer`、`boolean_evaluate`、
  `boundary_adapter`、`bridge_fill`、`publish_cleanup`、`total` 的统一阶段耗时；
- 每阶段的节点数、link 数、Mesh 属性数、属性元素数和峰值数据规模；
- 当前正确路径的 Boolean 中间合同与最终输出合同。

未得到新的持久基线前，不写新后端，不使用历史 97–176 秒作为“本轮已复测”结论。

## 4. 必须冻结的语义与允许替换的实现

### 4.1 不可改变

- FeatureGraph、ChamferPlan、Pipe/segment/station 的含义和 canonical 顺序；
- 当前 Curve/Pipe 的几何输出和受控 Manifold Difference 的输入组织；
- Boundary 必须来自同一次受控 Boolean 的真实 Intersecting/Boundary selection；
- 同一 Boundary 可同时属于多个 Pipe、segment、Surface Patch 或 junction port；owner 是集合，不是单值；
- 普通槽段的左右完整 Edge Loop、共同转折分段、cyclic 共同 station 分段；
- 原生 Bridge 的输入、job 顺序与结果，以及 Bridge 后才执行的 junction Fill；
- Chamfer Face 区域、Face 方向、法线传递、材质处理、source 不变、Redo/Undo 和失败清理；
- 只有 source 与 Cutter 都满足 closed manifold 合同时才使用 Manifold；不允许自动降级到其他 solver。

### 4.2 可以替换，但必须逐层证明等价

- one-hot Named Attribute 的物理承载方式；
- 逐 node/link 创建改为批量 Mesh/Attribute 数据写入；
- owner 数据改为无固定容量的 Python set/record ledger；
- 运行时 Curve/Pipe 是否先物化为临时 Mesh；
- 原生 Manifold Boolean 的临时 Object、合并 Cutter 和应用方式；
- Python 一次扫描生成下游既有 BMesh layers 的适配方式；
- 在首个样本通过后，Cutter 合并、批次组织和重复扫描消除。

“可以替换”只表示允许做实验，不表示已经证明产品等价。

## 5. 数据模型细节

```text
当前正确慢路径
FeatureGraph / Plan / Curve
  → 动态创建数千个身份 nodes / links
  → 受控 Manifold Boolean
  → 带 Boundary / owner / station layers 的 evaluated Mesh
  → 现有 Direct Bridge / Fill

首选旁路原型
同一 FeatureGraph / Plan / Curve
  → 当前 GN Curve Pipe 与 Boolean Pro
  → Python 写入现有完整逐 owner FACE attributes
  → 固定规模出口写入原生相交边
  → Python 复刻 EDGE/POINT field adaptation，生成相同 Boundary 合同
  → 原封不动的现有 Direct Bridge / Fill
```

新 producer 的输出边界必须与旧 producer 完全相同。下游不应知道身份数据来自动态节点还是批量数据。

### 5.1 身份数据模型

禁止再次把 owner 压成“一个整数就是一个 owner”。当前固定出口只证明相交边集合等价；后续审计已确认
不需要继续做信息消融或决定新承载方式：沿用正式 Python producer 已写入的完整逐 owner FACE schema。
外部 ledger 仅负责汇总、比较和向下游适配，不能取代 Boolean 内必须保留的事实。数据模型仍分为两层：

- Mesh 上保存 Boolean 真正需要传播的完整稀疏事实；批量写入，不逐元素调用 Blender RNA；
- Python ledger 汇总任意长度的 owner set、Patch set、segment set、port role 和 station 记录。
  若使用稳定 record ID，它只能作为 Python 侧索引，不能假设标量 ID 经 Boolean 插值或合并后仍有语义。

Python 对现有 GN 完整 FACE field 的 EDGE/POINT 求值已经通过全量验证；该规则已冻结，不得改用
nearest、BVH、centroid、主 owner、固定 bitmask 或“最像的一个”补齐。当前未解决的是如何在正确的
中间执行时刻把结果交给后续处理。

### 5.2 固定 Boolean 出口层

这一层保留现有 Boolean Pro，只允许增加固定规模的诊断/Intersection 出口：

- 直接物化实际 Manifold Difference 的 `Intersection Edges`；
- 完整逐 owner FACE attribute 已由 Python 在 Boolean 前写入，不再另找压缩事实；
- 新增节点和连接数量不随 Face、Pipe、segment 或 Point 数量增长；
- 不实现本工具不需要的 Slice、Union、Intersect 或通用 UI 分支。

已验证相交边出口三次中位数约 0.197 秒，Boundary universe 完全等价。正式采用前仍必须比较完整
owner/station/Patch 合同、材质与法线。若 Python 无法从同一次 Boolean 后的完整 FACE fields 复刻当前
EDGE/POINT field adaptation，首选路线直接 `STOP`；不会退回动态 Store 或空间猜测来掩盖问题。

### 5.3 Boundary 适配层

适配层只做格式转换，不做几何猜测：

- 从真实 Boundary selection 开始；
- 为每条 Boundary Edge 和端点生成稳定、排序后的多 owner 记录；
- 物化现有 Direct Bridge 已读取的 segment membership、station、station squared 和 Patch layers；
- 缺失、未知、冲突或无法无损表达时 fail-closed；
- 不改变 Bridge job 分组、station interval、切点、配对或 Fill 规则。

一旦必须修改下游规则才能让原型通过 Mixed，说明本轮已经跨越性能层，立即 `STOP`。

## 6. 实施顺序与硬门槛

### Phase 0 — 冻结 oracle 与性能剖面

状态目标：`BASELINE FROZEN`，不计入性能实现进度。

只运行 Mixed / Radius 0.01，现有矩阵的单样本 ID 为 `mixed__extruded_002__r0p010`。完成：

1. 冻结当前正确正式入口的 L0 输入合同：fixture、source、plan、Pipe、参数；
2. 冻结 L1 Boolean 输出合同：
   - evaluated Boolean 规范化几何；
   - Boundary Edge universe；
   - 每条 Edge 的完整 Pipe/segment/Patch/port owner set；
   - Edge/Point membership、station、station squared；
   - 缺失、冲突、多 owner 统计和稳定 ledger fingerprint；
3. 冻结 L2 最终产品合同：
   - 现有规范化几何 fingerprint 和拓扑计数；
   - Chamfer Face 的空间集合 fingerprint，而不只是数量；
   - Bridge job、terminal connectivity、junction Fill ledger；
   - Face 方向与法线合同；
   - source 不变、无 Preview 残留、失败时无伪输出；
4. 加入统一阶段计时，不改变正式结果；
5. 连续三次结果 fingerprint 一致，再锁定 oracle。

浮点字段的容差必须根据旧路径自身三次运行的实际波动预先冻结；离散 ID、集合、计数和连接关系
必须完全一致。不得在看到新路径差异后放宽容差。

Go：oracle 完整、三次稳定、阶段耗时齐全且产物持久保存。  
Stop：缺任一中间合同、只能得到最终健康性指标，或旧路径自身不稳定。

### Phase 1 — provenance producer 单层原型

历史阶段状态：Boolean 前 producer 已通过并进入正式集成；Boolean 后 field adaptation 的算法与阶段
性能也已通过，但当前最小集成边界 `STOP`。以下步骤保留为历史合同。

按以下顺序替换同一 producer 内部子阶段，每步仍只跑 Mixed / 0.01：

1. 复用已经通过的固定原生相交边出口，不再重测 Cutter/Boolean 等价性；
2. 针对 Edge 133 / segment 24 做输入 FACE → Boolean 输出 FACE → EDGE/POINT Store 的逐层属性追踪；
3. 沿用全部现有逐 Pipe/segment/Patch/station/station² FACE attributes，不做信息消融或压缩；
4. Python 复刻现有 field adaptation，单次扫描生成旧 Direct Bridge 所需的 Edge/Point/Patch layers；
5. prototype 不创建任何随输入规模增长的运行时 Geometry Nodes。

每一步先比较 L1 Boolean 输出合同，再看耗时。L1 不等价时，不运行 Bridge/Fill，不讨论最终性能。

Go：

- L0 输入合同完全一致；
- L1 的 Boundary Edge universe 与逐 Edge 多 owner/station/Patch ledger 一致；
- 固定出口新增节点/link 数不随输入规模增长，旧动态身份构建器调用次数为零；
- `identity_producer + boolean_evaluate + boundary_adapter` 冷运行中位数不超过 0.70 秒；
- 三次独立运行稳定，无一轮超过 1.00 秒。

Stop：

- 任一 Boundary 多一条、少一条，或 owner set 不一致；
- 任一多 owner 被降为单 owner、固定槽位或固定 bitmask；
- 需要 nearest、空间容差猜 owner、越界 station clamp、fixture 特判或后处理补洞；
- 为通过原型需要修改 Direct Bridge、切点、分组或 Fill；
- 两轮有针对性的 producer 修正后 L1 仍不等价；
- 一小时内没有可重复的阶段耗时下降；
- 数据写入或传播只是把 80 秒转移为 `owner × element` 的新热点。

### Phase 2 — 最终输出与 2 秒门槛

状态仍为 `PROTOTYPE`，只运行 Mixed / 0.01。

把 Phase 1 的等价 Boundary 合同交给未经修改的 Direct Bridge/Fill，比较 L2 最终产品合同。

阶段预算：

| 阶段 | Mixed 冷运行预算 |
|---|---:|
| analysis + plan | ≤ 0.65 秒 |
| curve / cutter | ≤ 0.15 秒 |
| identity producer | ≤ 0.20 秒 |
| Boolean evaluate | ≤ 0.20 秒 |
| Boundary adapter | ≤ 0.25 秒 |
| Bridge / Fill | ≤ 0.35 秒 |
| publish / cleanup | ≤ 0.15 秒 |
| 总计 | ≤ 2.00 秒 |

单阶段预算用于定位偏航；总计是产品硬门槛。测量为三次独立冷运行 Operator 时间：中位数 ≤ 2.00 秒，
单次最大值 ≤ 2.50 秒。另记录热 Redo，但热运行不能代替冷运行门槛。

Go：

- L1 Boolean 合同继续完全等价；
- L2 最终 fingerprint、Chamfer Face 空间集合、Bridge/Fill ledger、Face/normal 合同完全等价；
- source、事务、失败清理和 Preview 残留合同通过；
- 三次冷运行满足总耗时和最大值门槛。

任一条件不满足，保持 `PROTOTYPE / STOP`。正确但超过 2 秒不算通过；2 秒内但结果不同也不算通过。

### Phase 3 — 正式入口集成

只有 Phase 2 全部通过后，状态才可升为 `INTEGRATED`。

- 用新 producer 替换正式入口内部的临时 Preview 身份编码；
- 保留当前 Operator 的一步式交互、Redo/Undo、Radius 和 Keep Cutter 行为；
- 保留旧慢路径为测试 oracle，不在用户入口做 silent fallback；
- 新路径失败时明确失败并清理事务，不自动退回慢路径伪装成功；
- 验证正式 runtime 确实调用目标架构，不接受旁路 probe 代替；
- 不修改 `auto_load.py`。

集成后首先再次只跑 Mixed / 0.01。正式入口的 L0/L1/L2 与性能门槛不变。

Go：正式 Operator 三次通过全部合同且冷运行达标。  
Stop：probe 达标但正式入口仍建立动态 Preview，或正式入口耗时/结果与 prototype 不同。

### Phase 4 — 扩展验证

只有 Phase 3 通过后才允许扩展：

1. 正式 10-cell 产品矩阵，每格三次；
2. 常见 simple case 冷运行中位数 ≤ 1.00 秒；
3. 完整 Blender regression；
4. GUI Redo/Undo、Radius 和 Keep Cutter；
5. 独立规格审计，确认正式 runtime、测试、文档、日志和用户行为一致；
6. 一次性批量输出全部最终 `.blend` 与人工检查清单。

自动层全部通过后状态最高为 `VERIFIED`。禁止生成、渲染、读取或比较 PNG/JPEG/截图；最终视觉层
由用户在 Blender 中批量检查，收到确认后才可声明 `ACCEPTED`。

## 7. 备选路线与切换条件

首选路线失败后，不在同一路线反复修改几何语义。

### Route B — overlap batch identity export

仅当 Phase 1 证明单次 Boolean 的固定事实出口无法无损表达所需多 owner，而不是 Python 读取速度不足时启用。

- 根据 Cutter 重叠图分批，显式保留每批 owner ledger；
- 先比较正序、逆序和不同图着色的 Boolean 规范化结果；
- 必须仍通过 Mixed 的 L1 Boundary 合同和 L2 最终 oracle；
- Boolean 批次、总耗时或拓扑随顺序变化即 `STOP`。

Route B 是新的旁路 prototype，不继承 Route A 的进度状态。

### Route C — 完整 Boundary binding 重写

若当前固定出口与 Route B 都无法无损表达 `(Pipe, Port, Patch, station interval)` 多 owner，说明瓶颈与身份模型
耦合，需要独立算法项目。此路线不属于本轮性能优化计划，必须重新写规格、oracle 和预算，经用户确认
后再启动。不得把第一次失败的 compact scalar 后端直接复活。

## 8. 每小时审计与状态记录

每 60 分钟或每次路线失败后记录：

1. 正式入口是否仍保持当前正确稳定路径；
2. 当前 prototype 是否只替换 provenance producer；
3. Mixed 的 L1 Boolean 合同是否完全等价；
4. Mixed 的 L2 最终合同是否完全等价；
5. 哪个阶段从多少秒降到多少秒；
6. 当前状态是 `PROTOTYPE`、`INTEGRATED`、`VERIFIED`，还是仅 `RECOVERY`。

任一问题无直接 artifact 证据，状态立即为 `STOP`。恢复旧正确行为只能记为 `RECOVERY`，不能计入性能进度。

## 9. 交付物

建议持久目录：`tests/artifacts/feature_chamfer_performance/`。

每一阶段至少交付：

- `environment.json`：版本、fixture、参数、代码状态；
- `timings.json`：每次运行及各阶段耗时、节点/link/属性规模；
- `oracle_input.json`：L0；
- `oracle_boolean_boundary.json`：L1 逐 Edge 多 owner/station/Patch ledger 与 fingerprint；
- `oracle_final.json`：L2 最终几何、Chamfer Face、Bridge/Fill、法线和事务合同；
- `comparison.json`：旧/新逐字段比较与 Stop/Go 结论；
- `result.blend`：仅在达到对应阶段后输出的可检查结果；
- `audit.md`：每小时审计、路线切换和失败原因。

测试日志必须能让 agent 直接判断失败发生在输入、Boolean、Boundary、Bridge/Fill 还是产品入口，
不能只输出一个总 `PASS/FAIL`。

## 10. 明确禁止

- 不得先接正式入口再补 oracle；
- 不得用 closed manifold、无零面积、无自交代替旧/新等价；
- 不得用最终 Mesh 偶然相同掩盖 L1 Boundary 合同不同；
- 不得用固定 owner 容量、单 owner、nearest、BVH、centroid 或 station clamp；
- 不得修改 Bridge/Fill 规则来修补新 producer；
- 不得把旧 Exact 对照或仅 Manifold benchmark 当成产品正确性证据；
- 不得在 Mixed / 0.01 通过三重门槛前运行 10-cell、GUI 或完整回归；
- 不得以缓存旧动态 wrapper 的热运行成绩代替冷运行；
- 不得生成或判断图片作为验收证据；
- 不得把 `RECOVERY`、测试补强或文档更新描述为性能完成。

## 11. 完成定义

本计划只有满足以下全部条件才可声明 `VERIFIED`：

1. 正式一步入口不创建任何随输入规模增长的动态身份 Geometry Nodes；固定 Cutter、Boolean 与固定
   属性出口允许保留；
2. Mixed / 0.01 的 L0、L1、L2 与旧 oracle 完全等价；
3. Mixed 三次冷运行中位数 ≤ 2.00 秒，单次最大值 ≤ 2.50 秒；
4. 常见 simple case 三次冷运行中位数 ≤ 1.00 秒；
5. 10-cell × 3、完整回归、GUI Redo/Undo 和独立规格审计通过；
6. 正式 runtime、测试入口、artifact 和文档指向同一架构。

用户批量打开最终 `.blend` 并确认视觉结果后，状态才可从 `VERIFIED` 升为 `ACCEPTED`。

## 12. 2026-07-31 产品细节补全

正式入口在保持上述几何与性能门槛的基础上，补全三项产品行为：

- Radius 重做：以 source Object、Mesh 数据及其几何与 Sharp 标记的稳定指纹联合缓存 Python FeatureGraph/Curve 路径拓扑。
  只有所有 junction 都没有多套全局配对候选时才跨 Radius 复用；存在二义性时 Radius 会参与端点
  containment 评分，因此保守地完整重算。无论是否命中缓存，endpoint 分类、计划、Cutter、Boolean
  和全部下游都使用新 Radius 重新生成。缓存只保留 Python 数据、最多 8 份，不持有临时 Blender Object。
- 多物体：选中的 Mesh 作为一个原子批次处理。全部成功后一次性发布；任一对象失败时回收整批结果、
  Cutter 和临时状态，并恢复所有 source 的原可见性。
- 显示结果：成功后 source 的 Mesh 与配置不变，但在 viewport、Outliner 和 render 中隐藏；只显示并
  选择最终结果。Undo 恢复 source 可见并删除结果，Redo 再次生成结果并隐藏 source。

新增证据：Mixed 两半径各三次继续命中旧结果且约 1.22–1.25 秒；完整回归 159/159；真实 GUI 的
Adjust Last Operation、Keep Cutter、Undo/Redo 通过。详见历史计划第 8 节和以下 artifacts：

- `tests/artifacts/feature_chamfer_three_details_mixed_matrix/results.json`
- `tests/artifacts/feature_chamfer_three_details_full_regression/results.json`
- `tests/artifacts/feature_chamfer_gn_gui_undo.json`

## 13. 功能收尾

用户已确认当前 Feature Chamfer 状态可接受，功能进入收尾：

- UI 只保留当前正式 Feature Chamfer；旧 Sharp/Seam 按钮已删除；
- 旧 Sharp/Seam Operator 已停止注册，避免脚本或搜索菜单继续进入过时产品路径；
- 新实现仍复用的底层 FeatureGraph、Cutter、Boundary 与历史诊断工具继续保留，不因下线旧入口而删除；
- 回归门禁新增“旧入口未注册、面板只有一个正式入口”的检查；仅依赖已下线 Operator 的旧入口测试停止执行，底层几何合同测试继续运行；
- 当前状态为 `ACCEPTED / CLOSED`；后续修改按新的独立任务重新建立门槛，不再延续本轮性能重构状态。
