# Feature Chamfer topology defect diagnosis

Status: `PROTOTYPE`. Algorithm、Backend 与目标 Operator 已有证据，但截图中的
terminal topology defect 尚未通过同机位 Visual 门禁，不能标记为 `VERIFIED`。

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
