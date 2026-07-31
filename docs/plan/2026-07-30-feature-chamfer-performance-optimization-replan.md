# Feature Chamfer 性能优化重新规划

日期：2026-07-30
更新：2026-07-31
状态：`PRE-BOOLEAN PRODUCER VERIFIED / INTEGRATION AUTHORIZED`
正确性基线：当前正式结果已获用户确认，继续作为只读 oracle。2026-07-31 已进一步验证：Python 可以在不读取旧逐 segment POINT/FACE 属性的前提下生成完整 Boolean 前属性；同一 Boolean、完整身份、未修改 Bridge/Fill 和最终拓扑均等价。用户已授权下一步仅替换正式入口的 Boolean 前属性生产；Boolean 后 materializer 暂不替换。

历史计划：[`2026-07-30-feature-chamfer-preview-performance-plan.md`](2026-07-30-feature-chamfer-preview-performance-plan.md)  
失败复盘：[`2026-07-30-feature-chamfer-performance-rewrite-failure.md`](../postmortem/2026-07-30-feature-chamfer-performance-rewrite-failure.md)

2026-07-31 验证记录：
[`2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md`](2026-07-31-feature-chamfer-post-boolean-identity-export-validation.md)

外部账本完整验证：
[`../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`](../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md)

Python 完整逐 segment 属性验证：
[`../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md`](../validation/2026-07-31-feature-chamfer-python-segment-attributes-validation-result.md)

## 0. 2026-07-31 路线更新

- 外部压缩账本路线保留为历史 `STOP`，不再作为当前正式接入方案。
- 新验证保留每个 Patch/Pipe/segment 各自独立的完整属性，但改由 Python 批量写入 Mesh，不再为这些属性动态展开 GN。
- Boolean 前 474334 个 Cutter 属性元素中存在 13235 个 float32 逐位差异；最大 6 ULP / `2.38e-7`，首差为 `-0/+0`。用户确认其无业务意义，并冻结 `ULP ≤ 8` 且绝对差 `≤ 1e-6` 的派生浮点容差；离散身份、schema、几何和拓扑仍要求完全一致。
- 同一 Boolean 后 81312 个身份标量中仅 464 个派生浮点逐位差异，最大 6 ULP / `8.94e-8`，零项超容差；Intersection 仍为 3872 raw / 3868 unique / 4 duplicate。
- 未修改 Bridge/Fill 的工作项、顺序、区间判断和最终几何全部一致；三次完整 Boolean 前 producer 中位数约 0.53 秒，连同 Boolean 与完整读取约 0.81 秒。
- 当前接入边界只到 Boolean 输入：替换旧 source Patch、Curve segment POINT 和 Cutter FACE 动态属性生产。Boolean Pro 与 Boolean 后 materializer 保持原样，后者另行验证和优化。

## 1. 实际要改什么

当前流程慢在“给几何贴身份标签”这一步。为了让后面的 Bridge 知道每条切口边属于哪根 Pipe、
哪个 segment、哪两个 Surface Patch，以及它位于 Pipe 的什么位置，现有实现临时创建了数千个
Geometry Nodes 和连线。几何分析、Cutter、Boolean、Bridge 本身都不慢。

本轮实际改造只有一件事：**保留当前正确且很快的 GN Cutter 与 Boolean Pro，只删除为下游身份恢复
动态展开的 one-hot 节点网络。Boolean Pro 直接导出真实相交边及最小基础事实，Python 恢复完整身份后，
继续交给当前正确的 Bridge/Fill。**

正式目标不是纯 Python 重写 Cutter 或 Boolean。GN 可以继续承担固定规模的 Cutter、Boolean 和属性出口；
禁止的是随 Face、Pipe、segment 或 Point 数量增长的运行时身份节点网络。

### 1.1 当前慢路径

```text
分析 Sharp Edge，得到 Pipe 与 segment
  → 生成与当前一致的 Cutter Curve
  → 为每个 Face / Pipe / segment / station 动态创建节点和连线（约 80 秒）
  → Manifold Difference
  → 从 Boolean 结果读取 Boundary 与身份
  → 当前正确的 Bridge / Fill
```

### 1.2 当前目标路径

```text
分析 Sharp Edge，得到同一份 Pipe 与 segment
  → 现有 GN Curve Pipe 生成相同 Cutter
  → 现有 Boolean Pro 执行同一次 Manifold Difference
  → 固定规模出口写入原生 Intersecting Edges 与最小基础身份事实
  → Python 一次扫描切口边，恢复每条边的完整多重归属
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

2. **建立固定规模的 Boolean 后出口**
   - 已验证只增加一个属性写入节点和两条连线，即可把原生相交边写为 Edge 布尔属性；
   - 下一步只增加 Python 无法从 plan、source/Cutter 拓扑和 Boolean 输出确定性恢复的基础事实；
   - 出口节点和连线数量不得随 Face、Pipe、segment 或 Point 数量增长；
   - 不允许把旧 one-hot 换名字后继续动态展开。

3. **一次扫描恢复完整 Boundary 记录**
   - 只遍历 Boolean Pro 已标记的真实相交边；
   - 从固定出口、当前 plan、source/Cutter 拓扑读取全部命中事实；
   - 为一条边保存任意数量的 Pipe、segment、Patch 和 port 归属；
   - 从传播后的 Point/Face 数据读取 station 和 station squared，不使用最近距离重新猜测；
   - 任何标签缺失、冲突或传播不完整都直接报错，不补默认值。

4. **增加一个薄适配层**
   - 将上一步的多值记录写成当前 Bridge 已经读取的 Edge/Point/Patch layers；
   - 适配层不选择左右边、不切分环、不创建 Bridge job，也不 Fill；
   - 现有 Bridge/Fill 代码保持不变，用它来证明前面的替换没有改变几何语义。

5. **接入一步式正式入口**
   - 只有旁路原型在 Mixed / Radius 0.01 上结果和耗时都达标后才接入；
   - 接入后不再创建临时动态 Preview wrapper；
   - Radius、Keep Cutter、Redo/Undo、source 不变和失败清理行为保持现状。

### 1.4 已完成的首个技术实验

实验结论已经冻结：固定规模出口可在约 0.20 秒内导出完全相同的相交边集合；Python 读取和初步恢复
约 0.27 秒。但只凭相交边和相邻 Face，第一条身份比较就丢失 Pipe 5，因此“Boundary-only”路线已
明确失败。下一步不是重做 Cutter/Boolean，也不是继续调 Face 邻接，而是确定并导出最小基础身份事实。

详细数字、旧身份生成链和禁止重复的实验见 2026-07-31 验证记录。

后续完整验证纠正了 Face 整数的解释：raw INT 是被 membership 加权的一阶矩，不能直接当 record ID；
归一化后可在全部 3872 条记录上恢复正确的 Edge 级 Pipe/segment/Patch/port 与 station 合同。真正首差
位于 Boolean Point 的端点事实传播，共 89 条差异。因此下一步只研究 Point/endpoint 贡献者映射；
不得重复 Boundary、Face record 或 Edge 级 ledger 试验。详细证据见外部账本完整验证结果。

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
| Preview 已存在后的 Direct Bridge Finalize | 约 0.27 秒 | 可继续复用 |

动态 wrapper 历史规模为 3863 nodes / 5747 links。当前正式一步入口仍会临时建立这套 Preview，
所以只是把正确的两步包进一次事务，并没有消除性能问题。

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
  → 固定规模出口写入原生相交边与最小基础事实
  → Python 单次扫描，生成与旧路径相同的 Boundary 合同
  → 原封不动的现有 Direct Bridge / Fill
```

新 producer 的输出边界必须与旧 producer 完全相同。下游不应知道身份数据来自动态节点还是批量数据。

### 5.1 身份数据模型

禁止再次把 owner 压成“一个整数就是一个 owner”。当前固定出口只证明相交边集合等价；下一步先用
信息消融确定每类身份中哪些必须穿过 Boolean，再决定最小基础事实的承载方式。外部 ledger 仅负责
汇总、比较和向下游适配，不能取代 Boolean 内必须保留的事实。数据模型仍分为两层：

- Mesh 上保存 Boolean 真正需要传播的完整稀疏事实；批量写入，不逐元素调用 Blender RNA；
- Python ledger 汇总任意长度的 owner set、Patch set、segment set、port role 和 station 记录。
  若使用稳定 record ID，它只能作为 Python 侧索引，不能假设标量 ID 经 Boolean 插值或合并后仍有语义。

如果 Blender Boolean 对基础事实的传播不足以恢复旧路径的完整多 owner 集合，这条路线直接失败；
不得用 nearest、BVH、centroid、主 owner、固定 bitmask 或“最像的一个”补齐。

### 5.2 固定 Boolean 出口层

这一层保留现有 Boolean Pro，只允许增加固定规模的属性出口：

- 直接物化实际 Manifold Difference 的 `Intersection Edges`；
- 传播 Python 无法从 plan 与拓扑确定性恢复的最小基础事实；
- 新增节点和连接数量不随 Face、Pipe、segment 或 Point 数量增长；
- 不实现本工具不需要的 Slice、Union、Intersect 或通用 UI 分支。

已验证相交边出口三次中位数约 0.197 秒，Boundary universe 完全等价。正式采用前仍必须比较完整
owner/station/Patch 合同、材质与法线。若固定数量的基础事实无法无损表达完整多 owner，首选路线
直接 `STOP`；不会退回动态 one-hot 或空间猜测来掩盖问题。

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

状态：`PROTOTYPE`。正式入口保持当前正确慢路径。

按以下顺序替换同一 producer 内部子阶段，每步仍只跑 Mixed / 0.01：

1. 复用已经通过的固定原生相交边出口，不再重测 Cutter/Boolean 等价性；
2. 针对首个 Pipe 5 差异做输入 Face → Boolean 输出 Face → Boundary Edge 的逐层属性追踪；
3. 对 Pipe、segment、Patch、station 与 station squared 做信息消融，确定必须穿过 Boolean 的最小集合；
4. 只增加固定数量的基础属性，并由 Python 单次扫描生成旧 Direct Bridge 所需的 Edge/Point/Patch layers；
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
