# Phase 2 — Shared ChamferPlan Shadow Seam

> 日期：2026-07-22；状态：`PROTOTYPE / GO`；目标 Operator：`hst.feature_chamfer_gn`。

## 入口与阶段边界

```text
UI Feature Chamfer GN
→ hst.feature_chamfer_gn
→ PREVIEW / FINALIZE
→ immutable ChamferPlan (SHADOW)
→ existing Preview Curve / existing Finalize Mesh runtime
```

- 用户操作：在同一 source 上依次运行 `PREVIEW → FINALIZE`。
- 用户可见变化：无；plan 不驱动最终 Mesh。
- 自动证据：14 cells × 3 repetitions 的 plan ID、provenance、source/output fingerprint 与分类。
- Go：既有分类不变；plan ID 三次稳定；PREVIEW/FINALIZE 共享语义；仅 shadow mode。
- Stop：adapter 重新推断 FeatureGraph、两 action plan 不一致或正式 Mesh 行为改变。

## Contract

`utils/feature_chamfer_plan_utils.py` 定义 frozen dataclass：

- `ChamferPlan`
- `FeatureStrand`
- `JunctionPort`
- `RailChain`
- `StripCorrespondence`
- `UnsupportedRegion`

Plan identity 使用 source fingerprint、radius、input contract 与 canonical strand coordinates；不使用 BMesh 临时 index。Blender ID custom properties 保存完整 JSON 与独立 plan ID。

Preview adapter 从 plan 的 immutable `FeatureStrand` 构建 Curve，不再读取 mutable FeatureGraph group。Finalize 仍运行既有 shadow backend，但在 FeatureGraph 阶段重建 semantic plan 并 fail-closed 核对；Boolean 后生成只读 Boundary binding ledger，直接核对 expected Rail、StripCorrespondence、Boundary Edge 消费和 port 引用，不移动或重建 Boundary。失败 fixture 的 Operator runtime 会把 Phase 1 stable diagnostic family 写回 Preview Object/Modifier 的 incomplete plan `UnsupportedRegion`，matrix 只读取该 runtime plan；本阶段不改变产品分类。

## 验证证据

- matrix：`tests/artifacts/feature_chamfer_matrix/results.json`
- 结果：`phase_0_go=true`、`phase_1_go=true`、`phase_2_go=true`
- 分类：`PRODUCT_SUCCESS=2`、`SAFETY_PASS=11`、`REGRESSION_FAILURE=1`
- 既有产品回归：mixed / `Extruded.002` / radius=0.01，未在 Phase 2 修复或重新分类。
- 完整回归：87 cases；新增 shared plan、JunctionPort、cyclic alignment、invalid payload 与 retry contracts 通过；唯一失败仍为上述冻结回归。

## 四层状态

- Algorithm：immutable contract 与 plan fingerprint 已验证 3 次确定性。
- Backend：Preview/Finalize shadow plan ID 与 provenance 一致；PRODUCT_SUCCESS 的实际 Finalize Boundary binding `status=PASS`，expected Rail/StripCorrespondence 与 Boundary Edge 消费无 missing/extra/unclassified，现有输出不变。
- Operator：目标 `hst.feature_chamfer_gn` 的 PREVIEW/FINALIZE artifact 直接证明 runtime path。
- Visual/Product：本阶段没有新增视觉成功声明。

当前状态仅为 `PROTOTYPE`。Phase 3 尚未开始；BoundaryGraph/JunctionPort 泛化、正式 plan-driven Mesh、产品级 `VERIFIED/ACCEPTED` 均不在本阶段范围。
