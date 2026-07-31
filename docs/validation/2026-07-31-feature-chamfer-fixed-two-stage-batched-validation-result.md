# Feature Chamfer 固定两阶段与批量安全检查验证结果

日期：2026-07-31
状态：`INTEGRATED / VERIFIED`；视觉层等待用户确认

## 1. 结论

正式一步入口已经切换为固定 Boolean 两阶段：现有 GN Cutter 生成相同输入，受控原生 Boolean 内核输出真实切口，Python 一次物化 Boolean 后 236 层身份，固定 Surface 阶段交给原有 Bridge/Fill。

性能热点并不是 80 次 Bridge 本身，而是每个 Bridge、每个 Fill 都重复为整份 Mesh 建三角化与 BVH。Mixed 基线共执行 94 次自交检查，约 2.29 秒。现在按阶段合并为最多三次：全部 Bridge 后、全部 Fill 后、最终清理后。几何生成、结构门禁、失败码与最终健康检查没有取消。

## 2. 最复杂样本硬门槛

样本：Mixed / `Extruded.002` / Radius `0.01` / Blender 5.1.2。

| 项目 | 结果 |
|---|---:|
| 三次耗时 | 1.227 / 1.226 / 1.222 秒 |
| 中位 / 最大 | 1.226 / 1.227 秒 |
| 冻结 fingerprint | `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107` |
| Vertex / Edge / Face / Chamfer Face | 3922 / 8054 / 4134 / 3454 |
| Bridge jobs / Faces | 80 / 3437 |
| Fill jobs / Faces | 12 / 28 |
| Boundary / non-manifold / zero-area / self-intersection | 0 / 0 / 0 / 0 |
| 自交检查次数 / 耗时 | 3 / 约 0.086 秒 |

结果与冻结 oracle 完全一致，且中位不超过 2.00 秒、最大不超过 2.50 秒。相比优化前固定两阶段中位 3.424 秒，完整入口减少约 64%。

## 3. 扩展验证

- 产品矩阵：第一阶段与延期范围均稳定，`first_stage_go=true`、`deferred_tricky_go=true`、`run_go=true`；18 个产品成功、4 个安全失败，2 个既有不支持场景仍被明确拒绝。
- source 全部不变，正式 runtime、一步事务、Preview 清理与重复运行稳定性通过。
- 完整回归首次运行 152/156，通过后发现 4 个旧架构断言没有随正式路径更新；这些测试只在检查旧节点形态，不是产品回归。更新为固定两阶段合同后，4/4 定向重跑通过。
- 没有生成、读取或判断任何图片。

## 4. 证据

- Mixed 三次硬门槛：`tests/artifacts/feature_chamfer_fixed_two_stage_batched_intersections_mixed_gate/results.json`
- 正式产品矩阵：`tests/artifacts/feature_chamfer_fixed_two_stage_batched_intersections_matrix_r2/results.json`
- 热点剖析：`tests/artifacts/feature_chamfer_bridge_profile/baseline.json` 与 `current_batched.json`
- 完整回归：`tests/artifacts/feature_chamfer_fixed_two_stage_batched_intersections_full_regression/results.json`
- 旧断言定向重跑：`tests/artifacts/feature_chamfer_fixed_two_stage_batched_intersections_legacy_tests_retry/results.json` 与 `feature_chamfer_fixed_two_stage_batched_intersections_remaining_tests_retry2/results.json`

## 5. 状态边界

自动层已经达到 `VERIFIED`。按项目验收规则，最终视觉层必须由用户打开矩阵生成的 `.blend` 手动确认；收到反馈前不声明 `ACCEPTED`。
