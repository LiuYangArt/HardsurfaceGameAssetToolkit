# Feature Chamfer Python Boolean 后 field adaptation 验证结果

日期：2026-07-31  
状态：`PROTOTYPE / PHASE 0–2 PASS / NUMPY PERFORMANCE PASS / PHASE 3 INTEGRATION STOP`

## 1. 目标与范围

- 保留正式 Python producer 的完整 FACE schema、同一 Cutter 与同一次 Manifold Difference，仅绕过 Boolean 后逐 owner 动态 Store，验证 Python 能否精确复刻 FACE→EDGE/POINT field adaptation。
- 不修改正式入口、Boolean、Cutter、Bridge/Fill、UI 或 `auto_load.py`；不集成原型；不使用图片。

## 2. 冻结合同

- macOS / Blender 5.1.2，build hash `ec6e62d40fa9`。
- Mixed / `Extruded.002` / Radius `0.01` / Keep Cutter `false`。
- 快照 `/private/tmp/hst-prepared-preview.blend`，SHA-256 `d6e81f6accd181b5efa8d60a04b60018e3df4ce30672e586430b7505a4f2ddda`。
- Oracle 只在 actual 独立产生后比较；离散严格一致，派生 FLOAT 同时满足 ULP≤8、绝对差≤1e-6。
- 原始 Boolean Pro 为 184/260；正式 Feature Chamfer 副本为 592/808。逐 owner 通道属于 Feature Chamfer 注入，不归因于原始资产。

## 3. 分阶段结果

### Phase 0 — `PASS`

- 从正式 runtime 的真实连接冻结了 Pipe、Patch、segment membership、station、station² 的 FACE Named Attribute 到 EDGE/POINT Store 链。
- active Boolean 为 `DIFFERENCE / MANIFOLD`。actual 仅增加固定诊断出口，旧后置动态 materializer 未参与 actual。
- Blender 5.1.2 源码规则与 runtime 实跑一致：FLOAT FACE→EDGE/POINT 对全部关联 Face 等权平均；BOOLEAN 对关联 Face 作 logical-any。

### Phase 1 — `PASS`

- Edge 133 / segment 24 六项均命中：Edge membership/station/station²，以及两端 Point membership/station/station²。
- actual Edge membership 为 `0.5`；两端 membership 为 `2/3` 与 `1/3`。贡献 Face、值与权重已持久化。
- actual 在 oracle 比较前独立产生，未读取或复制旧 EDGE/POINT output。

### Phase 2 — `PASS`

- 3872 raw / 3868 unique / 4 duplicate Boundary 全部通过；7744 endpoint-segment 全部通过。
- 离散首差为无；最大 FLOAT 差为 2 ULP / `9.934107070286302e-8`，无超容差项。
- 三次重复 actual 的完整身份均通过。

### Phase 3 — `INTEGRATION STOP / DOWNSTREAM NOT RUN`

- Oracle 下游通过：80 Bridge jobs / 3437 Bridge Faces、12 Fill jobs / 28 Fill Faces；最终 3922/8054/4134，Chamfer Face 3454，四项健康计数为 0。
- NumPy 批量物化三次中位约 `0.0287` 秒、最大约 `0.0293` 秒；Boolean+物化中位约 `0.0764` 秒、最大约 `0.0780` 秒，性能门槛通过。
- 原 236 个动态 Store 位于 active Boolean 输出与后续静态处理之间。它们在完整 Cutter FACE field context 仍存在时物化身份，后续 Surface 分支再消费这些物化层。
- 删除 236 个 Store 后，完整 wrapper 最终几何仍与 oracle 完全一致：4195/4866/680，fingerprint 同为 `54b68282bb2fb8c0865cf4c2ee5ec6c15fa10a64737a4fa2f2a2b77d5ce5aa9f`，Boundary 为 3872。
- 但在最终 Mesh 上再运行 Python，仅 10/236 层一致、226 层失败；119 个 owner FACE 来源层已变为全零，endpoint-segment 为 0。此时所需信息已经丢失，不能事后重建。
- 反向分段确认：中间对象输入和紧随其后的转接本身会保留代表层；问题不是 Python 算法或属性写入能力，而是执行时序与中间 Geometry 边界。
- 普通 Geometry Nodes modifier 不能在一次求值中暂停于 raw Boolean seam、调用 Python、再继续同一个 wrapper。因此“只替换 236 个动态 Store、其余 GN 原样不动”的最小集成合同无法落地。
- 下游前完整身份门槛未命中，所以未修改下游保持 `NOT RUN`；早期下游失败轮次均为装配错误，已标 `REJECTED` 或 `SUPERSEDED`，不作为结论。

## 4. 审计记录

- 多轮错误输入、重复 Preview、错误固定出口、跨求值使用不稳定 Mesh index、同进程状态污染及已知错误的最终邻接猜测均已保留为 `REJECTED`；Phase 2 通过但证据不完整的轮次为 `SUPERSEDED`。
- 禁止机制：无。未使用 nearest/BVH/centroid、空间容差、固定元素 ID、fixture 特判、手工补表、station clamp、固定槽/bitmask、单 owner、多次 Boolean 或图片。
- 正式入口未修改，原型未集成。

## 5. 最终结论与后续边界

- 已证明：同一正式 producer、完整 FACE schema 与单次 Boolean 后，Python 可以准确且快速复刻全部 EDGE/POINT 身份。
- 未证明：只替换中间动态 Store 后，能够把这些身份交给同一个未修改 wrapper 的后半段；限制来自执行边界，不是数据被 Boolean Pro 封住，也不是 Python 计算能力不足。
- 本轮最高为旁路 `PROTOTYPE`，整体为可信 `STOP`；禁止按当前最小替换方案接正式入口。
- 下一方案必须另立合同二选一：
  1. 把 Boolean 后 Surface/static tail 选择与身份物化一起迁到 Python；
  2. 将中间 Mesh 明确持久化，拆成两个 modifier/两阶段，在两次 GN 求值之间运行 Python。
- 两条路线都会扩大当前替换边界并可能增加求值成本，必须先在 Mixed 单样本分别验证结果等价、完整运行时间和生命周期行为，再决定是否集成。

## 6. Artifacts

独立验证任务：`019fb7a0-ebc8-7f43-9a75-472ace0001cc`  
独立 worktree：`/Users/apple/.codex/worktrees/c67c/HardsurfaceGameAssetToolkit`

- 机器摘要：`tests/artifacts/feature_chamfer_python_field_adaptation/summary.json`
- 真实链：同目录 `runtime_chain.json`
- 首差样本：同目录 `first_edge_comparison.json`
- 全量身份：同目录 `full_identity_comparison.json`
- 下游：同目录 `downstream_comparison.json`
- 性能：同目录 `timings.json`
- 236 层紧凑差异：同目录 `final_static_236_layer_comparison.json`
- 正式 runtime 选择：同目录 `runtime_selection.json`
- 分段传播：同目录 `static_tail_checkpoints.json`
