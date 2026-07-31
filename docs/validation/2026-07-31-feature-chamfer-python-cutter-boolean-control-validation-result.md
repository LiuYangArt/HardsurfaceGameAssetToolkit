# Feature Chamfer Python Cutter 与 Boolean 控制验证结果

日期：2026-07-31
状态：`PROTOTYPE / CUTTER NOT ESTABLISHED / BOOLEAN CONTROL VERIFIED`

## 1. 范围与固定合同

- 固定样本：Mixed / `Extruded.002` / Radius `0.01` / Keep Cutter `false`，Blender 5.1.2。
- Oracle 为正式一步式路径；离散严格一致，派生 FLOAT 为 ULP≤8 且绝对差≤1e-6。
- Cutter 与 Boolean 是两个独立验证轴；不修改正式入口、资产、UI、Bridge/Fill 或 `auto_load.py`。
- 不自研 Boolean，不使用坐标猜测、Edge index 对照、nearest/BVH、多次 Boolean、fixture 特判或图片。

## 2. Python Cutter — `NOT ESTABLISHED`

- 已冻结正式 Cutter 的 23 条 spline、点坐标/radius/tilt、对象变换与 Curve Pipe 节点链。
- Python 从正式 Plan/strand 直接建立了相同规模的 4012/7972/3986 Mesh，未求值或复制旧 Cutter。
- 纠正截面符号后第一圈完全一致；加入相邻 tangent transport 后，第一处差异仍在第二圈，来自 Blender Curve-to-Mesh 的 frame/tilt transport 尚未被完整复刻。
- 现有差异不能证明 Python Cutter 不可行，因此不记 `STOP`；性能与组合验证均 `NOT RUN`。

## 3. Boolean 控制

### 完全无 GN — `STOP`

- Python 的 Mesh/Boolean modifier API 只返回结果 Mesh，不暴露 `Intersecting Edges`。
- 因而完全无 GN 时无法直接取得正式切口选择；未用反推或坐标匹配补代。

### 固定原生 Boolean 内核 — `PASS`

- Python 新建固定 5 nodes / 5 links 的原生 Manifold Difference 与 EDGE Store，不包装 Boolean Pro，规模不随 owner 增长。
- 两路输入直接来自正式 active Boolean 的真实输入 socket。
- raw actual/oracle 均为 5785/9159/3376，几何 fingerprint、schema、全部标量属性值与 3872 Boundary 完全相同。
- 从 actual 独立生成 236 层身份：3872 raw / 3868 unique / 4 duplicate，7744 endpoint-segment，离散和 FLOAT 均零差；约 0.029 秒。

### 两阶段 Surface/static tail — `PASS`

- 第一阶段输出 raw Boolean 与持久 Boundary；Python 物化236层；第二个固定阶段完成 Surface Face 删除。
- Cutter Face 在 Cutter 输入上为 true，经 Boolean 传播后标识 Cutter-derived Face；正式 Surface 分支取 NOT。结果 Face 上的任一 Pipe membership 标识同一 Cutter-derived 集合，因此持久化 `original_surface = NOT(any Pipe membership)` 与正式选择等价。
- 最终 actual/oracle 均为4195/4866/680，几何 fingerprint 完全相同。
- 最终 Boundary 消费身份全部通过，最大 2 ULP / `9.934107070286302e-8`；材质、Sharp 与 custom normal 一致。
- Patch 1 的全 Mesh 属性 hash 在非 Boundary 元素上不同；正式 Bridge/Fill 只在 Boundary record 上读取该层，3872条 Boundary 的 Patch 集合完全一致，因此不影响当前消费合同。

### 性能 — `PASS`

- 三次独立冷任务：约0.0813 / 0.0819 / 0.0825秒。
- 中位0.0819秒、最大0.0825秒，低于0.35/0.50秒阶段预算。

## 4. 审计记录

- `REJECTED`：首轮近似 Cutter frame；不能据此声明 Python Cutter 失败。
- `REJECTED`：以原始 source 代替正式 Boolean 输入，并把完整 Surface 输出误当 raw oracle。
- `REJECTED`：只注入 raw Mesh、没有提供 Surface 选择链，未真正执行第二阶段。
- `REJECTED`：用 source Patch OR 近似 Cutter Face，得到错误的 4496/6038/1476。
- 使用过的禁止机制：无。

## 5. 结论与下一步

- 已证明：Boolean Pro 当前被 Feature Chamfer 消费的路径可以由“固定原生 Boolean → Python 身份物化 → 固定 Surface 删除”替代，正确性与阶段性能均通过。
- 不需要复制完整 Boolean Pro，也不需要自研 Boolean；仍需保留一个极小的原生 GN Boolean 内核，以取得 `Intersecting Edges`。
- 尚未证明：Python 直接 Cutter 完全等价；因此“Python Cutter + 新 Boolean 控制”的组合与未修改下游尚未运行。
- 下一步应继续完成 Curve-to-Mesh frame/tilt transport 复刻；若只以性能优化为目标，也可以保留当前固定 Cutter GN，优先验证已通过的 Boolean 两阶段路径与正式入口/未修改下游。

## 6. Artifacts

独立任务：`019fb7d7-4676-74a2-bc54-10caa30cac91`
独立 worktree：`/Users/apple/.codex/worktrees/9d5b/HardsurfaceGameAssetToolkit`

- 机器摘要：`tests/artifacts/feature_chamfer_python_cutter_boolean_control/summary.json`
- Boolean：同目录 `boolean_raw_comparison.json`、`boundary_comparison.json`、`identity_comparison.json`
- Static tail：同目录 `static_tail_comparison.json`、`static_tail_consumer_audit.json`
- 性能：同目录 `boolean_timings.json`
- Cutter：同目录 `cutter_contract_inspection.json`、`cutter_comparison.json`
- 日志：同目录 `logs/`
