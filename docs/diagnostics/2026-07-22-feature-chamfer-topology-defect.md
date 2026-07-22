# Feature Chamfer topology defect diagnosis

> Scope note: 此处 `VERIFIED` 仅指历史 mixed / radius=0.01 的局部 topology defect 验证，不代表 14-cell Feature Chamfer 通用化矩阵通过。当前产品基线见 `docs/diagnostics/feature-chamfer-generalization/phase-0-baseline.md`。

Status: `VERIFIED`. Algorithm、Backend、目标 Operator 与固定近景门禁已通过；
仍需用户在真实 Blender UI 中确认后才能标记为 `ACCEPTED`。

## Target entry contract

```text
UI Feature Chamfer GN button
→ hst.feature_chamfer_gn
→ invoke / action PREVIEW then FINALIZE / execute
→ build_pipe_chamfer(debug_stage="PATCHED", feature_graph_contract="GN_PREVIEW_V1")
→ Phase 2 RailPairRecords
→ regular strips
→ local junction ports
→ Extruded.002_FeatureChamfer
```

Expected visible result: the right straight chamfer strip must remain straight into
the lower concave opening. Algorithm evidence must keep accepted Phase 2 rail
coordinates and ordering unchanged. Go requires locating the defect before any
production topology edit.

## Direct evidence

- The defect is already present in `REGULAR_PATCHED`; Junction fill is not its
  point of introduction.
- The focus face belongs to regular `group_id=3`, `span_id=3`.
- Phase 3 polygon 2800 and Phase 4 polygon 2800 have identical vertices and
  coordinates. Phase 4 only adds adjacent Junction face 4431.
- Focus face vertices:
  `(0.619722426, 0.193341598, 0.062481456)` →
  `(0.619722426, 0.193341598, -1.329742551)` and the corresponding other rail.
- Its two longitudinal edges are `1.391840329` and `1.392223939`, while the two
  cross-strip edges are about `0.01325`. It is therefore a real 1.392-unit
  terminal span, not a Normal Transfer artifact.
- The source `RailPairRecord` already contains those two long terminal rail
  edges. The existing geometry guard reports `PASS` despite
  `max_edge_length=1.392223939`, so the defect is upstream of Junction patch and
  is not explained solely by the zipper step choice.

## Artifacts

- `tests/artifacts/feature_chamfer_topology_defect_diagnostic.json`
- `tests/artifacts/feature_chamfer_topology_defect_diagnostic.blend`
- `tests/artifacts/feature_chamfer_topology_defect_regular_face.json`
- `tests/artifacts/feature_chamfer_topology_defect_patched_face.json`
- `tests/artifacts/feature_chamfer_topology_defect_wire_right_lower_*.png`

## Stop / Go decision

`GO` for a focused Algorithm fix in the regular-strip seam. `STOP` for changing
Junction triangulation, Normal Transfer, accepted Rail coordinates/order, or
adding broad Fill. The next implementation must first add a regression that
fails on this terminal span and a guard that rejects unstructured long terminal
connections.

## Implemented fix

- Open Rail 的 greedy zipper 已替换为 terminal-constrained monotonic DP；只生成
  相邻 index advance，不移动、不插值 Phase 2 Rail 坐标。
- DP width cost 按 expected Chamfer width 归一化，100x scale regression 保持
  path / Faces 不变。
- 生产路径启用 width tolerance、95% inlier 门禁与 severe one-sided advance
  硬门槛；异常时 `regular_patch_invalid` fail-closed。
- 真实 mixed fixture 已纳入统一 regression，并从
  `hst.feature_chamfer_gn` PREVIEW → FINALIZE 运行。

## Verification evidence

- Baseline focus terminal 有两条 `> 1.0` 的长连接：一条垂直、一条错误斜向。
- 修复后 focus terminal 仅剩一条长连接，方向与 Z 轴点积绝对值 `>= 0.999`；
  Boundary / non-manifold / zero-area 均为 `0`，source fingerprint unchanged。
- Blender 5.1.2 full regression: `81/81 passed`。
- Operator artifact:
  `tests/artifacts/feature_chamfer_topology_verified_operator.blend`
- Machine-readable probe:
  `tests/artifacts/feature_chamfer_topology_verified_operator.json`
- Fixed closeup:
  `tests/artifacts/feature_chamfer_topology_verified_closeup.png`

## Remaining gate

当前状态不是 `ACCEPTED`。用户仍需在真实 UI、原始观察机位检查右侧直段与其余
Chamfer 区域；若视觉确认通过，再升级为 `ACCEPTED`。
