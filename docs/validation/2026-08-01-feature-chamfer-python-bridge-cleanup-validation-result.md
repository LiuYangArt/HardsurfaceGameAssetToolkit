# Feature Chamfer Python Bridge 链清理优化验证结果

日期：2026-08-01  
状态：`VERIFIED / PHASE 0 PASS / PHASE 1 PASS / REGRESSION PASS`

## 1. 目标与范围

- 要回答的问题：Python 无修改快速路径能否保持正式 Feature Chamfer 结果和全部清理决策，同时明显降低 Bridge 链清理耗时。
- 明确不做：不实现 Rust，不创建 Rust crate，不进入 Phase 2，不修改 `auto_load.py`，不改变清理、Bridge/Fill、Boolean 或补面 dissolve 语义。

## 2. 冻结合同

- 环境与版本：Windows x86-64；Blender 5.2.0 LTS；Blender Python 3.13.13。
- 固定样本与输入：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`；Object `Extruded.002`；Radius `0.01`；Dissolve Chamfer 开启。
- Oracle：修改前当前 Python 正式路径，3 个独立 Blender 进程分别调用 UI 对应 Operator `hst.feature_chamfer_gn` / `INVOKE_DEFAULT`。
- 目标路径允许机制：仅当 `merged_vertex_count == 0` 且 `dissolved_vertex_count == 0` 时将偏差记为 `0.0`，跳过双向距离计算。
- 禁止机制：已修改 chain 跳过验证；修改阈值、候选、排序、Bridge/Fill、Boolean、补面 dissolve；Rust；图片证据。
- 比较规则：清理决策 fingerprint、结果 fingerprint、Mesh 健康性必须逐次一致；Edge/Face 数只作同轮等价证据，不与 dissolve 前旧值比较。

## 3. 分阶段结果

### Phase 0 — 冻结 Python oracle

- 状态：`PASS`。
- 实际执行机制：正式注册插件后，通过 `bpy.ops.hst.feature_chamfer_gn("INVOKE_DEFAULT", radius=0.01, dissolve_chamfer=True)` 运行；计时包装只调用原生产清理函数和原生产偏差函数，未替换正式 Operator、builder 或算法结果。
- 三次共同计数：总 chain `160`；无修改 chain `121`；已修改 chain `39`；偏差调用 `160`；点到线段求值 `368,194`；source/cleaned 坐标数 `3,998 / 3,748`。
- 中位耗时：Operator `1.916035s`；Bridge/Fill `0.857566s`；Bridge 链清理 `0.404031s`；偏差内核 `0.116070s`。
- 结果合同：三次 fingerprint 均为 `a4cf20d263b5c2cc490323ab92f45ec2eaf1365321195dcacf3accabfd3784b2`；`3910 V / 7208 E / 3300 F`；Boundary、Non-manifold、零面积 Face 均为 `0`。
- 清理决策：三次 fingerprint 均为 `ec63693b5b0ebc9121d1c258fb7d6ed91254dfa39d6ed315149cb6ec801e90cd`。
- 第一处差异：无。
- 汇总证据：`tests/artifacts/feature_chamfer_python_bridge_cleanup/comparison.json` 与 `summary.json`；原始逐次文件保留在隔离任务，主工作区仅同步汇总。

### Phase 1 — Python 无修改快速路径

- 状态：`PASS`。
- 实际执行机制：正式 Python 路径只新增一个条件：无 merge 且无 dissolve 时偏差为 `0.0`；39 条已修改 chain 全部继续调用原 Python 偏差验证。
- 三次共同计数：总 chain `160`；无修改/快速路径 `121/121`；已修改/剩余偏差调用 `39/39`；剩余点到线段求值 `216,322`。
- 中位耗时：Operator `1.809630s`；Bridge/Fill `0.797091s`；Bridge 链清理 `0.353871s`；剩余偏差内核 `0.069489s`。
- Bridge 清理相对冻结基线中位下降 `12.41%`（`0.404031s → 0.353871s`）；逐轮下降 `12.41% / 6.03% / 16.45%`，三轮均更快。偏差内核逐轮下降 `40.13% / 32.60% / 43.11%`。
- 结果等价：三次结果 fingerprint、Mesh 健康性、chain 分区及已修改 chain 的逐条 deviation 均一致；121 条 oracle 无修改 chain 的 source/cleaned 有序坐标逐条相同。
- 原始 decision fingerprint 从 `ec636...` 变为 `fba005...`，首差是预期的无修改 chain `maximum_geometric_deviation` 浮点噪声变 `0.0` 与新增 `deviation_fast_path`；排除这两个预期字段及跨进程内存 identity token 后，全部正式 Operator 语义统计一致，首个非预期差异为“无”。
- 第一处差异：无非预期差异。
- 汇总证据：`tests/artifacts/feature_chamfer_python_bridge_cleanup/comparison.json` 与 `summary.json`；主工作区另有 `tests/artifacts/feature_chamfer_python_bridge_cleanup_main/optimized/summary.json`。

### Phase 2 — Rust

- 状态：`NOT RUN / OUT OF SCOPE`。
- Rust 启动门槛：`TRIGGERED`，因为优化后 Bridge 清理中位 `0.353871s >= 0.15s`；剩余内核 `0.069489s < 0.10s`。按 OR 合同触发后续评估，但本任务不实施 Rust。

## 4. 审计记录

- `SUPERSEDED`：此前“当前 worktree 两项失败归因未解决”的结论。用户授权继续后，将分别以 open chain 原始坐标方向证据和已接受的 dissolve 后产品合同修正测试误报；历史失败及错误保留如下，不覆盖。
- `SUPERSEDED`：只用“open chain 遍历方向不稳定”解释 safety 误报的中间结论不完整。raw proof 显示 remaining 三点、两个端点、`merged=0`、`dissolved=0` 均正确；第二处真实差异是输入 Python double `0.0025` 经 BMesh float32 roundtrip 成为 `0.0024999999441206455`。最终测试采用每分量 `1e-7` 容差的双向一一匹配，同时保留端点集合、三点数量和零 merge/dissolve 硬断言。
- 被驳回或取代的轮次：`REJECTED` — 首次对原始 decision fingerprint 的直接比较；`SUPERSEDED` — 相关测试批次 `2 passed / 1 failed` 后的“可能由优化污染”解释。
- 驳回原因：原始 fingerprint 包含允许变化的偏差展示字段；后续 raw proof 证明 safety 失败来自方向无关坐标断言中的 float32 roundtrip 精度误报，而 Mixed 失败来自已被用户接受的 dissolve 后内部拓扑冻结误报。
- 使用过的禁止机制：无。
- 预存用户修改：`tests/README.md` 与 `tests/feature_chamfer_matrix_driver.py` 保留原样，不计入本优化修改。
- safety 修正证据：raw proof 的 remaining 为三点，端点集合为 `{(0,0,0),(1,0,0)}`，`merged=0`、`dissolved=0`；误报来自 Python double `0.0025` 与 BMesh float32 `0.0024999999441206455` 的 exact 比较。测试现以每分量 `1e-7` 双向一一匹配，仍硬性检查三点、两端点及零修改。
- Mixed formal 修正：默认 dissolve 路径不再冻结 fingerprint/Edge/Face/Chamfer Face 数，改为正式 Operator、source 状态、dissolve 实际执行、闭合健康 Mesh、非空 Chamfer 标记、Bridge/Fill 合同与最终可见状态；关闭 dissolve 路径仍核对精确 topology oracle。
- 针对性两个 case：`2/2 PASS`。Feature Chamfer 最小相关回归：`6/6 PASS`。
- 完整统一回归：前两轮 `157/158`，唯一无关失败 `bake_collection_export_fbx_smoke` 均为 stdout `OSError: [Errno 22] Invalid argument`；第三轮使用独立 stdout/stderr 与全新 artifact 目录后 `158/158 PASS`，Bake FBX 正常导出。该证据支持前两轮为 runner 输出句柄环境冲突，不涉及本优化，也未修改 Bake 功能。
- `SUPERSEDED`：前两轮 Bake 失败。正常前台统一入口单跑 `bake_collection_export_fbx_smoke` 再次 `PASS`，导出 `SM_BakeExportCase_Low.fbx`（12,828 bytes）；确认失败来自隐藏/捕获 stdout 运行方式，而非文件路径、Bake 或 Feature Chamfer。
- 性能 A/B 未因测试断言修正而重跑：两处修正只改变测试验收，不改变正式 runtime、benchmark driver、fixture 或生产代码；正式路径仍由 `deviation_fast_path` 统计证明 121 条无修改 chain 命中、39 条已修改 chain 继续 Python 偏差验证。
- 命令异常审计：两次手工单测最初缺少 `HST_TEST_ARTIFACT_DIR` / `HST_TEST_RESULTS`，补齐统一入口环境后针对性新测试通过；桌面 shell 对长命令使用了 1 秒等待上限而返回 `124`，但 Blender 子进程已退出并写出三轮完整 JSON/Blend，后续汇总均从这些原始 JSON 重建。上述异常未被当作功能证据。

## 5. 主工作区集成复核

- 状态：`INTEGRATED / VERIFIED`；正式 Python 路径、针对性测试与可重复 benchmark 已同步到主工作区。
- Mixed 三次中位：Operator `1.892255s`；Bridge/Fill `0.840274s`；Bridge 链清理 `0.360479s`；偏差内核 `0.069121s`。
- 相对冻结基线：Operator `-1.24%`；Bridge/Fill `-2.02%`；Bridge 链清理 `-10.78%`；偏差内核 `-40.45%`。
- 三次共同计数：总 chain `160`；快速路径 `121`；已修改 chain 与偏差调用均为 `39`。结果 fingerprint、Mesh 健康性和决策 fingerprint 三轮分别唯一且一致。
- 主工作区完整统一回归：`158/158 PASS`。日志中的两处故意注入异常属于回滚合同测试，退出码为 `0`；结束后无残留 Blender 进程。
- 主工作区机器摘要：`tests/artifacts/feature_chamfer_python_bridge_cleanup_main/optimized/summary.json`；统一回归：`tests/artifacts/results.json`。
## 6. 当前结论

- 已证明：Phase 1 正式路径结果等价；快速路径仅命中 121 条无修改 chain；隔离同轮 A/B 的 Bridge 清理中位下降 `12.41%`，同步到主工作区后的独立复核下降 `10.78%`；相关回归 `6/6`、完整统一回归 `158/158`。
- 未证明：最终人工视觉验收未进行，因此状态为 `VERIFIED`，不能声明 `ACCEPTED`。
- 被替代方案或依赖是否仍有必要：Rust 后续评估门槛已触发，但本任务明确不进入 Rust。
- 下一步：本 Python 范围结束并保存进度。Rust 评估门槛虽已触发，但按当前决定暂缓，以后作为独立任务重新授权和验证。

## 7. Artifacts

以下均为本地验证产物，位于被 Git 忽略的 `tests/artifacts/`；核心结论已固化在本文，清理 artifacts 不影响代码或回归入口。

- 隔离 A/B 比较：`tests/artifacts/feature_chamfer_python_bridge_cleanup/comparison.json`
- 隔离总机器摘要：`tests/artifacts/feature_chamfer_python_bridge_cleanup/summary.json`
- 隔离完整回归：`tests/artifacts/feature_chamfer_python_bridge_cleanup/full-regression-final-detached-3/results.json`
- Bake 正常前台确认：`tests/artifacts/feature_chamfer_python_bridge_cleanup/bake-normal-confirmation/results.json`
- 主工作区优化复核：`tests/artifacts/feature_chamfer_python_bridge_cleanup_main/optimized/summary.json`
- 主工作区完整回归：`tests/artifacts/results.json`
- 复现入口：`python .\tools\run_feature_chamfer_python_cleanup_validation.py --mode optimized --repetitions 3` 与 `python .\tools\run_blender_tests.py`。
