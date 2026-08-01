# Feature Chamfer Python Bridge 链清理优化验证结果

日期：2026-08-01  
状态：`PROTOTYPE / PHASE 0 PASS / PHASE 1 PASS / REGRESSION STOP`

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
- 原始证据：`tests/artifacts/feature_chamfer_python_bridge_cleanup/oracle/`。

### Phase 1 — Python 无修改快速路径

- 状态：`PASS`（Phase 1 自身硬门槛）；后续相关回归门槛当前 `STOP`。
- 实际执行机制：正式 Python 路径只新增一个条件：无 merge 且无 dissolve 时偏差为 `0.0`；39 条已修改 chain 全部继续调用原 Python 偏差验证。
- 三次共同计数：总 chain `160`；无修改/快速路径 `121/121`；已修改/剩余偏差调用 `39/39`；剩余点到线段求值 `216,322`。
- 中位耗时：Operator `1.809630s`；Bridge/Fill `0.797091s`；Bridge 链清理 `0.353871s`；剩余偏差内核 `0.069489s`。
- Bridge 清理相对冻结基线中位下降 `12.41%`（`0.404031s → 0.353871s`）；逐轮下降 `12.41% / 6.03% / 16.45%`，三轮均更快。偏差内核逐轮下降 `40.13% / 32.60% / 43.11%`。
- 结果等价：三次结果 fingerprint、Mesh 健康性、chain 分区及已修改 chain 的逐条 deviation 均一致；121 条 oracle 无修改 chain 的 source/cleaned 有序坐标逐条相同。
- 原始 decision fingerprint 从 `ec636...` 变为 `fba005...`，首差是预期的无修改 chain `maximum_geometric_deviation` 浮点噪声变 `0.0` 与新增 `deviation_fast_path`；排除这两个预期字段及跨进程内存 identity token 后，全部正式 Operator 语义统计一致，首个非预期差异为“无”。
- 第一处差异：无非预期差异。
- 原始证据：`tests/artifacts/feature_chamfer_python_bridge_cleanup/optimized/` 与 `comparison.json`。

### Phase 2 — Rust

- 状态：`NOT RUN / OUT OF SCOPE`。
- Rust 启动门槛：`TRIGGERED`，因为优化后 Bridge 清理中位 `0.353871s >= 0.15s`；剩余内核 `0.069489s < 0.10s`。按 OR 合同触发后续评估，但本任务不实施 Rust。

## 4. 审计记录

- 被驳回或取代的轮次：`REJECTED` — 首次对原始 decision fingerprint 的直接比较；`SUPERSEDED` — 相关测试批次 `2 passed / 1 failed` 后的“可能由优化污染”解释。
- 驳回原因：原始 fingerprint 包含允许变化的偏差展示字段；后者经单独重跑、临时恢复生产代码后重跑，均在同一旧断言失败，证明不是新快速路径或测试顺序污染。
- 使用过的禁止机制：无。
- 预存用户修改：`tests/README.md` 与 `tests/feature_chamfer_matrix_driver.py` 保留原样，不计入本优化修改。
- 回归门槛：`feature_chamfer_bridge_cleanup_deviation_fast_path_contract` 与 `gn_finalize_tricky_b_bridge_input_cleanup_regression` 通过；既有 `feature_chamfer_bridge_input_cleanup_safety_contract` 在统一入口单 case 与完整统一回归均失败。完整错误首差是构造的 open chain 期望保留 3 个 Vertex，但实际触发断言：`Bridge cleanup merged or dissolved a protected open endpoint`（`tests/blender_test_driver.py:10389`）。临时恢复快速路径生产改动后，统一入口单 case 仍可复现；归因仍未解决。
- 完整统一回归：当前优化 worktree `158` cases 中 `156 PASS / 2 FAIL`。第二项 `feature_chamfer_python_pre_boolean_mixed_formal_regression` 首差为冻结输出合同不等：实际 fingerprint `900803deddc8b1712bcf86305b31f5d4cb159a9db0a09b84b66551347b183d0a`，`3909 V / 7235 E / 3328 F / 2648 Chamfer F`（`tests/blender_test_driver.py:8900`）；该 case 单独统一入口运行通过，表明完整套件存在顺序或共享状态影响，但归因未解决。
- 主工作区 `157/157 PASS` 是预优化主工作区的反证：两边 Git HEAD 相同，但优化 worktree 额外包含生产快速路径与新测试，因此不是等价代码状态，不能称为“same commit 等价验证”。根据硬门槛，Phase 1 保持 `PROTOTYPE`，整体状态 `STOP`。
- 命令异常审计：两次手工单测最初缺少 `HST_TEST_ARTIFACT_DIR` / `HST_TEST_RESULTS`，补齐统一入口环境后针对性新测试通过；桌面 shell 对长命令使用了 1 秒等待上限而返回 `124`，但 Blender 子进程已退出并写出三轮完整 JSON/Blend，后续汇总均从这些原始 JSON 重建。上述异常未被当作功能证据。

## 5. 当前结论

- 已证明：Phase 1 正式路径结果等价；快速路径仅命中 121 条无修改 chain；Bridge 清理三轮均下降，中位下降 12.41%。
- 未证明：当前优化 worktree 的完整统一回归没有通过；safety 与 mixed formal 两项失败的归因尚未定位。现有证据不能声称它们与 fast path 无关。最终人工视觉验收也未进行。当前只能声明 `PROTOTYPE / STOP`，不能声明 `VERIFIED` 或 `ACCEPTED`。
- 被替代方案或依赖是否仍有必要：Rust 后续评估门槛已触发，但本任务明确不进入 Rust。
- 建议下一步：审计完整套件前序 case 对 Blender 全局状态、BMesh 行为和测试模块状态的污染；不得修改既有 safety 断言迎合本优化。定位并使完整统一回归通过后，才可升级状态。

## 6. Artifacts

- 机器摘要：`tests/artifacts/feature_chamfer_python_bridge_cleanup/oracle/summary.json`
- 环境：`tests/artifacts/feature_chamfer_python_bridge_cleanup/environment.json`
- A/B 比较：`tests/artifacts/feature_chamfer_python_bridge_cleanup/comparison.json`
- 总机器摘要：`tests/artifacts/feature_chamfer_python_bridge_cleanup/summary.json`
- 逐次输入、决策与计时：`tests/artifacts/feature_chamfer_python_bridge_cleanup/oracle/run-01..03/result.json`
- 最终 Mesh：`tests/artifacts/feature_chamfer_python_bridge_cleanup/oracle/run-01..03/result.blend`（仅交付人工查看，本报告未读取图片）。
