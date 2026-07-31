# Feature Chamfer Boolean 后身份出口验证记录

日期：2026-07-31  
状态：`SUPERSEDED BY EXTERNAL LEDGER FULL VALIDATION`  
范围：只记录 Mixed / `Extruded.002` / Radius `0.01` 的旁路验证；未接正式入口，未修改 Bridge/Fill。

关联计划：[`2026-07-30-feature-chamfer-performance-optimization-replan.md`](2026-07-30-feature-chamfer-performance-optimization-replan.md)  
失败复盘：[`2026-07-30-feature-chamfer-performance-rewrite-failure.md`](../postmortem/2026-07-30-feature-chamfer-performance-rewrite-failure.md)

## 1. 本轮实际验证的问题

保留当前正确的 GN Cutter 与 Boolean Pro，只在 Boolean Pro 的实际 Manifold Difference 输出位置，
把原生 `Intersection Edges` 写成 Mesh Edge 布尔属性。随后由 Python 读取 evaluated Mesh，尝试从：

- 原生相交边选择；
- Boolean 后的相邻 Face；
- 当前 plan、Pipe 与 segment 合同；

恢复现有 Direct Bridge 所需的完整 Pipe、segment、Surface Patch、station、station squared 和端点身份。

本轮没有验证纯 Python Cutter，也没有改用普通 Boolean Modifier。前两者已经确认不是当前性能热点，
不应再作为这条路线的前置门槛。

## 2. 已冻结的结论

### 2.1 原生相交边出口可行，而且很快

固定出口只增加：

- 1 个 Mesh 属性写入节点；
- 2 条连接；
- 1 个 Edge 布尔属性。

该规模与 Face、Pipe、segment 和 Point 数量无关，验证过程中没有调用旧动态身份构建器。

三次独立运行：

| 运行 | 构建 + 求值 |
|---|---:|
| 1 | 0.1987 秒 |
| 2 | 0.1972 秒 |
| 3 | 0.1956 秒 |
| 中位数 | 0.1972 秒 |

旧正式路径构建动态身份网络约 79.61 秒。本实验已经证明：保留 GN Cutter 和 Boolean Pro 本身不会保留
这个热点；固定规模的 Boolean 后属性出口可以避开它。

### 2.2 Boundary universe 完全一致

当前正式 evaluated Mesh 中有 3872 条被选中的原始 Edge 记录，对应 3868 个唯一、方向无关的端点键。
历史记录中的 3868 使用的是唯一端点键口径。多出的 4 条不是新 Boolean 语义，而是 3 组重合退化
记录造成的原始记录重复。

固定出口与正式 oracle 比较结果：

- 唯一相交边：3868 对 3868；
- 缺失：0；
- 额外：0；
- multiplicity 差异：0。

以后不得再次把“3872 原始记录”与“3868 唯一几何键”当作 Boolean 漂移。所有报告必须同时写明
原始记录数、唯一键数和重复组数。

### 2.3 只导出相交边不足以恢复完整身份

Python 扫描和初步恢复用时约 0.272 秒，但完整身份在第一条比较即失败：

- 正式 oracle：该 Edge 属于 Pipe 5；
- Python 从相交边与相邻 Face 恢复：Pipe 集合为空。

因此本轮仅证明 Boundary universe 可恢复，不证明 Pipe、segment、Patch 或 station 可恢复。按照硬门槛，
没有运行正式 Bridge/Fill，也没有把调查期间的 Bridge 计时纳入验收。

## 3. 旧路径如何获得身份数据

旧路径不是在 Boolean 后凭几何猜身份，而是在 Boolean 前把身份展开成大量稀疏属性，让 Blender Boolean
传播这些属性，之后再把传播结果物化到相交边和端点。

### 3.1 Source Surface Patch

Python 先根据 source Mesh 拓扑为每个 Face 计算 Surface Patch ID。GN 随后为每个 Patch 建立一个独立的
Face 布尔属性：属于该 Patch 的 Face 为真，其余为假。

### 3.2 Cutter Pipe 与 segment

每根 Cutter spline 有稳定 Pipe ID。Curve Point 先写入：

- 每个 segment 的 membership；
- segment 内归一化 station。

Curve Pipe 变成 Mesh 后，这些 Point 字段再转换到 Cutter Face：

- 每个 Pipe 一个 Face membership；
- 每个 segment 一个 Face membership；
- 每个 segment 一列 station；
- 每个 segment 一列 station squared。

segment membership 允许相邻段在共享位置同时为真，因此旧表达本质上支持多归属，而不是单 owner ID。
station squared 也不是冗余副本：Boolean 插值后，下游用 membership、station 一阶矩与 station 二阶矩
恢复一条 Boundary Edge 或 junction Vertex 对应的两个 station 端点，并处理 cyclic 的 0/1 跨界。

### 3.3 Boolean 后物化

Boolean Pro 的实际 Manifold Difference 子分支同时输出几何与 `Intersection Edges` 选择。旧路径复制该
受控节点组，在这个输出位置：

1. 用 `Intersection Edges` 限定真实切口边；
2. 读取 Boolean 已传播的 Pipe、segment、Patch、station 和 station squared；
3. 将它们分别写到 Boundary Edge 与 Point domain；
4. Python Finalize 再读取这些列，构建 Direct Bridge 的输入。

所以旧身份来自“Boolean 前完整稀疏事实 + Boolean 属性传播”，不是来自相交边本身。Pipe 5 的首个
缺失正好证明了这个区别。

## 4. 为什么旧路径慢

语义本身没有被证明很慢，慢的是用 Python 经 Blender RNA 逐个创建并连接动态节点：

- source Face/Patch one-hot 历史约 53.6 秒；
- Curve Point/segment one-hot 历史约 15.4 秒；
- 完整 wrapper 历史达到 3863 nodes / 5747 links；
- 当前完整正式 oracle 统计为 5077 nodes / 7367 links（包含 nested groups）。

Boolean 求值、相交边导出和 Python 扫描都远小于 1 秒。因此下一步应优化“不可推导事实如何进入并
穿过 Boolean”，而不是重写 Cutter、Boolean 或 Bridge。

## 5. 已走弯路与以后禁止重复的验证

### 5.1 把“Python 搭 GN”误报为纯 Python

早期验证用 Python 重建/驱动 Curve Pipe 资产或 Boolean Pro 节点树，曾被错误表述为纯 Python 等价。
这些结果只能证明“Python 可编排相同 GN”，不能证明无 GN。该结论已经撤回。

### 5.2 无必要地先重写 Cutter 与 Boolean

纯 Python Cutter 得到相同拓扑但存在约 `1e-5` 坐标差；阶段门槛随即停止。这个实验对当前路线不是
必要前置条件，因为 Cutter/Boolean 实测不是热点，而且用户已决定保留它们。除非未来固定出口路线被
独立证据彻底否定，否则不得再从纯 Python Cutter 开始。

### 5.3 最小 reader 为空时误判 Blender API 阻断

正式路径在同一 Blender 中已经能物化相交边。独立 reader 读不到选择时，原因应先从节点链接、输入、
求值上下文和 Mesh 阶段中找，不能宣称 API 不可访问。复制正式 active seam 后已经成功导出。

### 5.4 把实现没完成写成技术 STOP

“完整 probe 尚未写完”不是语义失败，也不是 API 阻断。只有出现可复现的第一处合同差异才能 STOP。
本轮可信 STOP 是 Pipe 5 丢失，不是运行时间或实现进度。

### 5.5 错用 3868/3872 统计口径

第一次运行曾因要求原始记录数必须等于 3868 而提前停止，浪费了一轮约 80 秒的 oracle 构建。正确做法
是同时计算 raw records、unique keys 与 multiplicity，并先做口径 reconciliation。

### 5.6 独立会话停滞过久

第一验证会话长时间停在构图/等待且没有 artifact；后续重新启动了严格门槛任务。以后：

- 固定出口单次超过 60 秒立即终止并保留日志；
- 每个门槛先输出最小 JSON，再进入下一步；
- 不等待子任务代替主线程推进；
- 先复用已冻结的正式 oracle，避免每个实验重复支付约 80 秒旧构图成本。

## 6. 下一步还缺什么

当前缺的不是更多 Boundary 规则，而是一份**固定规模、可穿过 Boolean、足以恢复旧 one-hot 语义的
最小基础事实合同**。至少要回答：

1. Pipe 5 为什么没有出现在相交边相邻 Face 上：是输入 Face 属性未保留、domain adaptation 稀释、
   Cutter-Cutter 重叠覆盖，还是该 Edge 的身份依赖非相邻 Face？
2. 哪些身份可由 plan 确定性派生，哪些必须穿过 Boolean：
   - 相交边选择已经证明必须由 Boolean 导出；
   - Pipe/segment membership 是否必须传播；
   - Patch 是否可由相邻 source Face 直接读取；
   - station/station squared 是否可由 segment 端点参数解析推导，还是必须传播数值矩；
   - junction port 是否完全包含在 plan，还是需要额外输出。
   station 二阶矩在旧 Bridge 中承担区间端点恢复，不能在没有等价证明时只保留平均 station。
3. 一个标量 ID 经 Boolean 插值/合并后是否仍可无歧义解释。若不能，不得把多 owner 压成单值。
4. 固定规模出口如何表达任意数量 owner。固定 bitmask、固定槽位和“主 owner”都不合格。

建议按信息消融实验推进，而不是直接设计最终编码：

1. 针对首个 Pipe 5 失败 Edge，冻结它相邻 Face、输入 Cutter Face、传播前后属性和实际 owner；
2. 分别只保留 Pipe、segment、Patch、station 两个矩，确定每类事实的最小必要性；
3. 每次只增加固定数量的基础属性，比较完整 ledger，不运行 Bridge；
4. 完整 ledger 逐 Edge 相等后，才运行未修改的 Bridge/Fill 与 2 秒总预算。

如果证明任意多 owner 无法通过固定数量 Mesh 属性无损传播，应立即报告模型能力边界，再讨论 overlap
batch 或外部 owner ledger；不得退回 nearest、BVH、centroid、station clamp 或 fixture 特判。

## 7. 可复用证据与入口

本轮 artifacts 位于独立 worktree，尚未复制回主工作区：

- 摘要：`/Users/apple/.codex/worktrees/55f7/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_post_boolean_python/summary.json`
- 逐 Edge 比较：`/Users/apple/.codex/worktrees/55f7/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_post_boolean_python/boundary_comparison.json`
- 计时：`/Users/apple/.codex/worktrees/55f7/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_post_boolean_python/timings.json`
- 完整旧身份 oracle：`/Users/apple/.codex/worktrees/55f7/HardsurfaceGameAssetToolkit/tests/artifacts/feature_chamfer_post_boolean_python/oracle_boolean_boundary.json`
- 验证脚本：`/Users/apple/.codex/worktrees/55f7/HardsurfaceGameAssetToolkit/tools/probe_feature_chamfer_post_boolean_python.py`

后续任务必须先读本文和上述摘要，复用已经冻结的 oracle 与首个差异，不得重新从 Cutter/Boolean 等价性
开始，也不得把 Bridge 调查计时当作已通过门槛的性能证据。

## 8. 2026-07-31 稳定 Face 记录号验证

### 8.1 先撤销错误的首差归因

复核发现旧比较器读取 Pipe 与 Patch 时使用了不存在的属性名前缀，因此旧报告中“第一条 Pipe 5 为空”
不能单独作为语义证据。修正 Pipe 名称后，该目标 Edge 仍只有一张 source-side 相邻 Face，Cutter Face 已被
Difference 删除；所以“只看输出相邻 Face”仍然失败，但失败原因必须改写为**载体缺失**，不是 API reader
阻断。Patch 在输出 FACE domain 本来就不存在，也不得再把它写成可读但为空。

### 8.2 固定整数记录号实验

在旁路 graph 的 source 与 Cutter Boolean 输入各增加一个 `INT / FACE` 记录号，并在 active Manifold
Difference 的原生相交边位置把两者物化为 `INT / EDGE`。实验只复用已经构建好的慢 Preview 来取得
输入 Face → 完整身份 ledger，不重复约 80 秒构图，也没有修改正式入口或 Bridge/Fill。

三次独立运行完全一致：

- 3872 条原始相交边都得到非零、落在输入 Face 范围内的整数记录号；
- 但其中 3627 条记录号回查出的 Pipe/segment 与旧 oracle 不一致；
- 第一条稳定差异：Boolean 后记录号 1970 回查为 Pipe 14 / segment 17，oracle 是 Pipe 0 / segment 31；
- 原 Pipe 5 witness 三次均得到记录号 1375，回查为 Pipe 9 / segment 15，oracle 是 Pipe 5 / segment 22；
- 记录号没有变成零或越界值，但已经被 Boolean 的 field adaptation 选成错误输入 Face，因此不能作为
  Python ledger 的无损索引。

三次 Boolean 求值为 0.1510、0.1571、0.1505 秒，中位数 0.1510 秒。Python 从已构建慢 Preview 冻结
3986 张 Cutter Face ledger 为 1.0922、1.1486、1.2011 秒；该步骤仍在读取旧 one-hot，只用于验证
记录号语义，不计作新 producer 的性能结果。

当时据此记录了 `FACE RECORD CARRIER STOP`；后续完整验证已将这段解释标为 `SUPERSEDED`。单个 raw
整数确实不能直接当 record ID，但它是 membership 加权的一阶矩，归一化后可恢复正确的 Cutter Face
record。该历史实验仍可用于证明“必须同时携带 membership”，不能继续作为 lineage 不可恢复的证据。
本轮没有运行 Bridge/Fill，也没有接正式入口。

固定规模为：输入侧 6 nodes / 8 links，输出侧 2 nodes / 6 links，4 个 Mesh attributes；规模不随
Face、Pipe、segment 或 Point 数量增长。实验未使用 nearest/BVH、单 owner、固定槽、bitmask、station
clamp、fixture 名称或固定 Edge ID 补齐。

### 8.3 当前边界与下一路线

Mixed 当前 oracle 的 3872 条原始记录没有多 Pipe/Patch/segment owner，不能用本样本证明“任意数量
owner”的模型容量。完整 Phase 0 也仍未完成三次 L0/L1/L2 oracle 冻结；本轮只复用单次完整身份 oracle
作为子实验比较基线。

本节关于“记录号指向错误 Face lineage”的解释已被后续完整验证纠正：raw INT 实为 membership 加权的
一阶矩，归一化后可正确恢复全部 Edge 级身份。分批 Boolean 不再是当前第一选择；真实剩余问题是
Boolean Point 上的端点事实混合。详见完整验证结果：
[`../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md`](../validation/2026-07-31-feature-chamfer-external-ledger-validation-result.md)。

不得退回动态 one-hot，也不得重复 Boundary、Face record 或 Edge ledger 实验；下一步仅验证固定规模的
Point/endpoint 贡献者映射。

本轮可读取产物：

- 摘要：`tests/artifacts/feature_chamfer_face_record_carrier/summary.json`
- 三次逐 Edge 记录：`tests/artifacts/feature_chamfer_face_record_carrier/edge-export-contract-run-{1,2,3}.json`
- 三次日志：`tests/artifacts/feature_chamfer_face_record_carrier/logs/edge-export-contract-run-{1,2,3}.log`
