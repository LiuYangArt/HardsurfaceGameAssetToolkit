# Feature Chamfer 通用化 Phase 0 基线

> 日期：2026-07-22；状态：`PROTOTYPE`；Phase 0：`GO`；产品整体：`NOT VERIFIED`。

## 入口与验收合同

```text
UI：Feature Chamfer GN
→ Operator：hst.feature_chamfer_gn
→ INVOKE_DEFAULT
→ action=PREVIEW / action=FINALIZE
→ GN_PREVIEW_V1 runtime
→ Preview artifact / 独立 Final output / 结构化 fail-closed
```

- 用户操作：逐 cell 执行 PREVIEW→FINALIZE。
- 预期可见变化：本 Phase 不改算法；仅冻结可重复结果和 evidence。
- 自动证据：14 cells × 2 repetitions、fixture SHA、source fingerprint、Operator/runtime marker、每次 `.blend` 与 JSON。
- Go：14 cells 均稳定分类、预期 safety error family 精确匹配、source Mesh fingerprint 不变、runtime path 可证明、fixture hash 正确。

## 执行结果

- Blender：5.1.2 / Darwin arm64。
- fixture SHA-256：四项均与 `tests/fixtures/README.md` 一致。
- 重复性：14/14 cells 两次 signature 一致。
- source Mesh geometry、Sharp Edge 与 transform：14/14 cells 两次均保持 fingerprint；Operator lifecycle properties 与 Preview modifier 不属于该 fingerprint。
- 入口证据：14/14 cells 均通过 `hst.feature_chamfer_gn` 的 `INVOKE_DEFAULT` PREVIEW/FINALIZE，并捕获到 Finalize `GN_PREVIEW_V1` backend。
- 分类：`PRODUCT_SUCCESS=2`，`SAFETY_PASS=11`，`REGRESSION_FAILURE=1`，`EXPECTED_UNSUPPORTED=0`。
- safety 语义：11/11 均匹配预先冻结的 wrapper `error_code` 与底层 root message；任一漂移都会转为 `REGRESSION_FAILURE`。
- Phase 0 Go 仅表示基线可信；产品成功率为 2/14，不能据此宣称通用化完成。

## 产品矩阵

| Fixture / Object | 0.01 | 0.03 |
|---|---|---|
| simple / `Extruded.002` | `PRODUCT_SUCCESS` | `PRODUCT_SUCCESS` |
| simple / `Solid 44` | `SAFETY_PASS` `ambiguous_boundary` | `SAFETY_PASS` `ambiguous_boundary` |
| tricky / `Solid.004` | `SAFETY_PASS` `ambiguous_boundary` | `SAFETY_PASS` `ambiguous_boundary` |
| tricky / `Solid.016` | `SAFETY_PASS` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` | `SAFETY_PASS` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` |
| tricky_b / `Extruded.003` | `SAFETY_PASS` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` | `SAFETY_PASS` `regular_patch_shared_rail_invalid` |
| tricky_b / `Extruded.002` | `SAFETY_PASS` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` | `SAFETY_PASS` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` |
| mixed / `Extruded.002` | `REGRESSION_FAILURE` `regular_patch_invalid` → `SIGNED_STRIP_WIDTH_EXCEEDED` | `SAFETY_PASS` `regular_patch_shared_rail_invalid` |

mixed / 0.01 在进入本 roadmap 前已有目标 Operator 产品成功证据；本次稳定 fail-closed，因此按 `REGRESSION_FAILURE` 记录，不能改写为 safety pass。

## Input Contract 草案 v0

当前已冻结：

- 输入必须是单一 active Mesh Object、Object Mode、仅选中该 Object；
- source 是 closed manifold，且无 zero-length Edge / zero-area Face；
- 存在显式 `sharp_edge` EDGE Boolean attribute，Sharp Edge 数量大于 0；
- Object scale 必须 applied（`1,1,1`）；location/rotation 可为非零；
- output 必须是独立 Object/Mesh，source Mesh geometry、Sharp Edge 与 transform fingerprint 不变；
- junction 暂不排除；本矩阵中的失败 fixture 仍视为合同内输入；
- radius=0.01/0.03 暂不因 solver 失败而排除。

未决：

- 局部 feature size 的正式几何定义。Phase 0 暂记录“与 Sharp vertex 相邻的 Mesh Edge 长度”的 min/p10/median，只作为诊断，不作为拒绝依据；
- radius 与局部厚度/曲率/相邻 feature 距离的可接受界限；
- self-intersection、zero-thickness CAD 与合法 junction 类型的精确输入证据。

## 证据与复现

- 汇总：`tests/artifacts/feature_chamfer_matrix/results.json`
- 每个 cell：`tests/artifacts/feature_chamfer_matrix/<case>/diagnostics.json`
- 可打开证据：每个 cell 的 `preview.blend`、`final.blend`
- runner：`python tools/run_feature_chamfer_matrix.py --blender <path> --repetitions 2`

本次 macOS 命令：

```text
python tools/run_feature_chamfer_matrix.py --blender /Applications/Blender.app/Contents/MacOS/Blender --repetitions 2
```

## Stop / Go 决策

Phase 0 = `GO`。允许下一独立 session 只执行 Phase 1。当前仍有 1 个明确 regression、11 个 safety-only cell；不得进入 Phase 2 或改正式算法，直到 Phase 1 诊断门禁完成。

## 明确未做

- 未修改 `auto_load.py`、Feature Chamfer production 算法或 fixture；
- 未把 fail-closed 计入产品成功；
- 未批准任何 `EXPECTED_UNSUPPORTED`；
- 未进行产品视觉验收、性能优化或 Phase 1+ runtime 接入。
