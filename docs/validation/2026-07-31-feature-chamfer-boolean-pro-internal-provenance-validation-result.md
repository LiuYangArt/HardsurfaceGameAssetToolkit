# Feature Chamfer Boolean Pro 内部身份传播验证结果

日期：2026-07-31
状态：`PROTOTYPE / PHASE 0 PASS / PHASE 1 PASS / OVERALL STOP`

## 1. 目标与边界

本轮只旁路检查当前正式 Preview 实际使用的 Boolean Pro，不修改正式入口、UI、Bridge/Fill 或
`auto_load.py`，不自行实现或更换 Boolean。禁止机制均未使用；未生成、读取或判断图片。

## 2. 固定环境与输入

- macOS；Blender 5.1.2，build hash `ec6e62d40fa9`。
- 样本：`feature-chamfer-topology-defect-mixed.blend` / `Extruded.002` / Radius `0.01` /
  Keep Cutter `false`。
- 复用正式 Preview 快照 `/private/tmp/hst-prepared-preview.blend`；实测 SHA-256 为
  `d6e81f6accd181b5efa8d60a04b60018e3df4ce30672e586430b7505a4f2ddda`，与冻结值一致。
- wrapper 记录的正式 backend 为 `PYTHON_CURVE_PIPE`，source 与 Cutter 各有且只有一条真实输入连接；
  不存在输入替换。
- Oracle 保持只读，只在 actual 已独立产生后参与末端比较。

## 3. Phase 0 — PASS

从正式 wrapper 沿真实 Node Group 引用递归导出 17 棵节点树，共 5077 nodes / 7367 links。
正式 wrapper 为 3863 nodes / 5747 links；Boolean Pro 根组实测 592 nodes / 808 links，与历史计数一致。

连接关系唯一确认 active 原生 Boolean 为 `DIFFERENCE / MANIFOLD`。该原生 Boolean 的 Mesh 与
Intersecting Edges 分别唯一进入 solver 选择组的 Manifold Result 与 Manifold Edges；solver 选择后的
Geometry 进入后置属性物化链。

active 原生 Boolean 只有两个输出 socket：Geometry 类型的 Mesh，以及 Boolean field 类型的
Intersecting Edges。完整 socket inventory 没有 Face/Edge/Point source index、input element index、
contributor ID 或 contributor map 输出。因此节点本身明确输出的是结果几何和相交 Edge selection，
不是来源映射。该结论来自 Blender 实际 RNA socket 与完整真实 link graph，而非 Python 读取失败。

Intersection Edges 一路进入 Boolean Pro 原有 Boundary 输出链；另一路直接作为第一层 76 个 Pipe、segment
与 source Patch Edge Store 的 Selection。后续 POINT/EDGE fact Store 不再显式接 Selection，而是在同一条
Boolean 输出 Geometry 链上按目标 domain 求值。Geometry 穿过完整 Store 链后进入正式 Geometry 输出。

## 4. Phase 1 — PASS

当前机制已沿连接逐字段确认：Boolean 前的 Cutter 为 23 个 Pipe FACE field，以及 32 个 segment
各自独立的 membership、station、station² FACE field，共 96 条 segment field。active 原生 Boolean
不读取或输出任何来源编号。本轮真实连接与同一 Boolean 历史实跑共同支持：这些输入 field 随几何
传播到 Boolean 输出几何；Boolean 后 Named Attribute 在该输出几何上求值；Intersection Edges 只作为
selection；后置 Store 再分别在 EDGE 和 POINT context 中适配、物化。Boolean Pro 没有额外构造、
聚合、重编码固定来源记录或隐藏来源映射输出。

完整 Boundary 合同为 3872 raw、3868 unique、4 duplicate。历史首差 Edge 133 / Pipe 4 /
segment 24 已保存完整 trace：固定 contributor record 能找回 Face owner，却在一个端点把 membership
`0.3333333433` 错成 `0.6666666865`，station `0.7322297176` 错成 `0.4106152084`；说明 endpoint
field context 不能由该固定记录替代。该轮明确标为 `REJECTED`。相反，历史 32 次逐 segment 独立 pass
对全部 7744 endpoint-segment 的 membership、station、station² 逐位零差，证明当前等价语义确由逐
segment field 提供。

另一份同一 Boolean 的 Python FACE producer 证据在 3872 raw Boundary 上比较 81312 个标量：离散零差，
最大 6 ULP、绝对差 `8.94e-8`，均在冻结容差内；Boolean runtime fingerprint 未变。这进一步确认
本轮所见“输入 field 随几何传播 → 输出 context 物化”的机制，而不是现成或隐藏的固定来源映射。

Phase 1 没有找到不随 segment 数增长、且不读取 oracle 构造的真实候选。当前 Boolean Pro 为 32 个
segment 明确展开 96 条输入 field；每增加 segment 都必须增加相应 field 与物化链。因此本轮总体
状态为 `STOP`，表示“Boolean Pro 内已有固定规模来源映射”这个假设被结构证据否定，不是实验不完整，
也不是 Python API 阻塞。

## 5. Phase 2–3 — NOT RUN

Phase 1 没有找到满足合同的固定规模真实候选，按冻结门槛不得运行单次 Boolean 固定 carrier 与性能测试。
没有用 oracle 构造 carrier，也没有重复 FACE 邻接、空间最近匹配、固定元素 ID、固定槽、bitmask、
样本特判、手工补表、station clamp 或多次 Boolean 包装。

## 6. 结论边界

“原生 Boolean 没有来源映射输出 socket”只否定直接读取现成固定来源映射；不否定 Python 后整理整体，
也不要求自研 Boolean。本轮实际证明的是：当前 Boolean Pro 的一次 Boolean 等价结果依赖逐 segment
独立 field，不能把它描述成已存在的固定来源映射。

后续通过 Blender MCP 从 `preset_files/Presets.blend` 导出的原始 Boolean Pro 资产补充了责任边界：

- 原始资产为 184 nodes / 260 links；正式 Feature Chamfer 运行时副本为 592 / 808；
- 原始资产只有固定数量的 Face Index、Cutter Face、材质和法线 Capture，不包含 23 个 Pipe 与
  32×3 个 segment 身份通道；
- 因此 membership、station、station² 由 Feature Chamfer 在 Boolean 前写入 Cutter FACE attribute，
  不是 Boolean Pro 自带数据；Boolean 后逐 segment 的 EDGE/POINT Store 同样由 Feature Chamfer 注入副本；
- 原始资产自身仍是一次 Manifold Difference，且原生 Boolean 仍只暴露 Mesh 与 Intersecting Edges。

MCP JSON 来自 Blender 5.2.0 LTS 的 `Presets.blend`，SHA-256 为
`f178bff89f1be64f44c190d59a56e7e860a9950ace1fb9e146e78d6c9bbd51c6`。它能证明原始资产结构，但不能
替代 Blender 5.1.2 正式运行时副本的结果验证。

用户说明本地 Blender 已启用 MCP 插件；本任务实际枚举到的 MCP resources 与 templates 均为空，且没有
可调用的 Blender MCP 工具。因此未能用 MCP 交叉读取当前 UI 会话，但这不构成阻塞；结构结论来自
Blender 5.1.2 打开同一冻结快照后导出的完整 RNA socket inventory 与真实 link graph，未使用截图。

## 7. 证据位置

- 独立任务：`019fb77b-9f9e-72c3-98a2-0f4626ea6c9a`
- 独立 worktree：`/Users/apple/.codex/worktrees/0a00/HardsurfaceGameAssetToolkit`
- 原始 Boolean Pro MCP 导出：`preset_files/boolean_pro_nodes.json`（该类 JSON 被仓库 `.gitignore` 忽略，
  作为本地可复查证据，不纳入本次提交）
- 机器证据：`tests/artifacts/feature_chamfer_boolean_pro_internal_provenance/`
- 关键文件：`node_tree_inventory.json`、`active_runtime_trace.json`、`socket_capability_matrix.json`、
  `first_endpoint_trace.json`、`candidate_comparison.json`、`timings.json`、`summary.json`。
- 原始日志：同目录 `logs/phase0-export-rerun.log`、`logs/phase1-field-audit.log`。
