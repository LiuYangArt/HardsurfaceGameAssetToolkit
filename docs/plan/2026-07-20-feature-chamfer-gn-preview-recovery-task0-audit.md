# Task 0 恢复干净阶段边界审查

> 日期：2026-07-20  
> 状态：VERIFIED  
> 目标 Operator：`hst.feature_chamfer_gn`  
> 本轮唯一 Task：Task 0

## 入口契约

```text
UI：Feature Chamfer GN Preview
→ Operator：hst.feature_chamfer_gn
→ invoke / execute（action=PREVIEW / FINALIZE）
→ Preview：ensure_gn_feature_chamfer_preview
→ Finalize：extract_feature_chamfer_finalize_context → patch_boolean_result
→ 用户可见结果：旧 SDF Preview；支持区域可 Finalize，复杂 END_CAP/JUNCTION fail-closed
```

## KEEP

- `utils/feature_chamfer_patch_utils.py`：complex region fail-closed。
- `const.py`：Even-Thickness asset 名称、版本、source、fingerprint 常量。
- `preset_files/Presets.blend`：Even-Thickness 与 `Poly-Curve Info` 依赖。
- `utils/experimental_pipe_chamfer_utils.py`：maximum-weight matching、逐 Edge ownership、Curve Pipe backend、Rail A/B diagnostic。
- `tests/blender_test_driver.py`：degree-3 matching、asset/backend、Rail A/B、complex fail-closed tests。
- Phase 1A / Phase 2 STOP probes、文档与 artifacts；仅作 prototype/diagnostic。

## REVERT / ISOLATE

- `operators/feature_chamfer_gn_ops.py`：撤回 structured Finalize preflight 与 cleanup；文件已回到基线 diff。
- `utils/experimental_pipe_chamfer_utils.py`：移除 structured artifact orchestrator、StripPort/JunctionRecord/Junction Mesh/Strip builders 及专用 resample helper。
- `tests/blender_test_driver.py`：移除 `structured_feature_chamfer_preflight_contract_smoke` 及注册。
- junction center-fan / projection ordering filler 随 Junction Mesh builder 移除。
- 未保留任何 Phase 3–6 “完成/PASS”声明。

## 直接证据

- `git diff -- operators/feature_chamfer_gn_ops.py`：空。
- Python 源码中无 `build_structured_feature_chamfer_artifacts`、`StripPort`、`JunctionRecord`。
- `python -m py_compile operators/feature_chamfer_gn_ops.py utils/experimental_pipe_chamfer_utils.py tests/blender_test_driver.py`：exit 0。
- `git diff --check`：exit 0。
- `python .\tools\run_blender_tests.py`：runner exit 0；`tests/artifacts/results.json` 为 Blender 5.1.2、67/67 passed。
- 退出清理仍打印既有 `unregister_class` traceback，但未造成测试失败。

## 未通过门槛 / 本轮未做

- Phase 1B 未开始：正式 Preview 仍是旧 SDF runtime。
- Phase 2 仍 STOP（17/51）。
- Task 1–4 未执行。
- 未修改 `auto_load.py`；未修改用户原始 `.blend`。
