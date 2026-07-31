# Feature Chamfer Boolean Pro 内部身份传播验证计划

日期：2026-07-31
状态：`FROZEN / PROTOTYPE ONLY`

## 1. 要回答的问题

本轮不自行实现 Boolean，也不替换正式入口。只检查当前正式 Preview 实际使用的 Boolean Pro，回答：

1. 它为何能在一次 Boolean 中保留各 segment 独立的端点身份；
2. 这种能力来自 Blender Boolean 暴露的固定来源映射，还是来自 Boolean 前逐 segment 独立字段随几何传播；
3. Boolean Pro 内部是否已有可由 Python 读取或复用的固定规模中间信息，使一次 Boolean 后仍能恢复完整
   endpoint membership、station、station²；
4. 如果没有现成映射，能否只保留同一个原生 Boolean、用固定数量输入/输出属性做单次旁路原型。

本轮明确排除：用 Python/BMesh/C/C++ 自行实现 Boolean、换 solver、改变 Cutter 几何、重复验证最终
FACE 邻接猜测、把多次 Boolean 包装成一次、修改正式 Operator、UI、Bridge/Fill 或 `auto_load.py`。

## 2. 固定环境、样本与 oracle

- 环境：macOS、Blender 5.1.2，记录完整 build、插件代码提交与工作区状态。
- 固定样本：`feature-chamfer-topology-defect-mixed.blend` / `Extruded.002` / Radius `0.01` /
  Keep Cutter `false`。
- 当前已生成的正式 Preview 只可作为输入快照；使用前记录文件 SHA-256，并核对它仍包含当前正式
  wrapper、同一 Cutter 与 Boolean Pro。
- Oracle：冻结的旧动态 GN Boolean 后完整身份，以及后续 32-pass 精确复核结果。完整比较范围为
  3872 条 raw Boundary、7744 组 endpoint-segment 的 membership、station、station²。
- 离散身份必须严格一致；FLOAT 必须同时满足 ULP ≤ 8、绝对误差 ≤ 1e-6。已有 oracle 自身逐位稳定，
  不得看到差异后放宽门槛。
- Oracle 只能在目标信息独立生成后参与末端比较；不得用于构造输入编码、分组、输出身份或补值。

## 3. Phase 0 — 冻结实际 runtime 与节点树

从正式 Preview 的外层 wrapper 一直追到当前 active Manifold Difference，机器导出：

- 所有嵌套 Node Group、节点、连接、接口 socket、默认值与分支开关；
- 实际生效的 source/Cutter 输入链、Boolean operation、solver 与 multi-input 组织；
- active Boolean 的 Geometry 与 Intersection Edges 两个输出分别流向哪里；
- Boolean 前的 Capture/Store/Named Attribute 与 Boolean 后的 domain adaptation、物化位置；
- 只影响属性的节点与会改变几何的节点；
- 节点树 fingerprint、592 nodes / 808 links 等历史计数是否仍匹配。

Go：能唯一确定当前实际分支，并由连接关系证明每项来源。
Stop：快照不是当前正式路径，或 active 分支无法唯一确认。后续不得运行。

## 4. Phase 1 — 信息来源审计

对当前 active Boolean 做字段级追踪，区分三类信息：

1. 原生 Boolean 明确输出的信息，例如 Geometry 与 Intersection Edges；
2. source/Cutter 输入字段经 Boolean 自动传播后，在输出几何上下文中继续求值的信息；
3. Boolean Pro 自己额外构造、聚合或重编码的信息。

必须核对 Blender 节点实际 socket，而不是从截图或文档名称推测。对完整 Boundary 和历史首差
Edge 133 / Pipe 4 / segment 24，记录每个候选字段在 Boolean 前、active Boolean 输出接缝、最终物化
位置的 domain、类型、有效率、多 owner 表达能力与第一处信息丢失。

本阶段要明确回答：原生 Boolean 是否提供输入 Face/Edge/Point 的来源索引或稳定映射；如果没有，当前
一次 Boolean 的等价结果是否只是因为旧网络为每个 segment 都保留了一条独立 field。

Go：来源链与信息能力都有可复查证据。
Stop：只观察最终属性值、无法证明它从哪条输入链产生。

## 5. Phase 2 — 单次 Boolean 固定规模候选

只有 Phase 1 找到不随 segment 数增长、且不读取 oracle 的真实来源信息，才运行本阶段。候选必须：

- 复用完全相同的 source、Cutter、active Manifold Difference 与单次 Boolean；
- 输入和输出字段数量固定，不按 segment、Pipe、Patch 或 owner 数增加；
- Python 可以在 Boolean 前批量写入，在 Boolean 后读取并恢复任意数量 owner；
- 不使用最近距离、空间容差、固定 Edge/Face ID、固定槽位、有限 bitmask、样本特判、手工补表、
  station clamp 或多次 Boolean；
- 不允许只比较汇总数量，必须逐 raw Boundary、逐 endpoint、逐 segment 比较完整三字段。

若 Phase 1 证明原生节点没有来源映射，允许做一个有界的反证 probe，验证最有希望的固定 carrier；
不得无休止枚举编码，也不得把失败外推为“Python 永远做不到”。

Go：一次 Boolean、固定规模、7744 组完整身份零差异。
Stop：出现可复现首差，或正确结果仍依赖逐 segment 独立 field / 多次 Boolean。
Not Run：Phase 1 没有满足本阶段输入合同的候选。

## 6. Phase 3 — 性能与通用性

仅 Phase 2 通过才执行：同一最复杂样本连续三次，记录 Boolean、字段准备、Python 恢复和总耗时。
目标中位数 ≤ 0.70 秒、最大值 ≤ 1.00 秒。再通过合成增大 segment 数的样本核对节点、字段与 Boolean
次数恒定；本轮不扩展 GUI、完整矩阵或 Bridge/Fill。

Go：正确性、性能、固定规模三项同时通过。
Stop：任一项不满足。

## 7. 状态解释

- `PASS`：本阶段目标和全部硬门槛成立。
- `STOP`：存在明确、可复现的语义或性能首差。
- `BLOCKED`：外部条件确实阻止验证，且已检查替代入口与反证。
- `NOT RUN`：前置阶段未通过。
- `REJECTED`：旧轮次证据或解释无效，保留记录但不得用于结论。

“Boolean Pro 内没有原生来源映射”只说明不能直接读取现成映射，不等于 Python 后整理整体失败；
“当前一次 Boolean 依赖逐 segment field”也不等于必须自行实现 Boolean。

## 8. 交付物

机器证据目录：
`tests/artifacts/feature_chamfer_boolean_pro_internal_provenance/`

至少包含：

- `environment.json`
- `node_tree_inventory.json`
- `active_runtime_trace.json`
- `socket_capability_matrix.json`
- `first_endpoint_trace.json`
- `candidate_comparison.json`
- `timings.json`
- `summary.json`
- `logs/`

人类结果文档：
`docs/validation/2026-07-31-feature-chamfer-boolean-pro-internal-provenance-validation-result.md`

每阶段结束立即落盘。不得生成、读取或判断 PNG/JPEG/截图；本轮不以视觉证据判定结果。
