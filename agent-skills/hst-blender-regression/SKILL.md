---
name: hst-blender-regression
description: Run this when working on HardsurfaceGameAssetToolkit and you need Blender headless regression coverage, upgrade smoke checks, or to verify which addon features broke after Blender API/version changes.
---

# HST Blender Regression

Use this skill for this repository when the user asks to:
- run regression tests
- check whether Blender upgrade broke the addon
- know which features/operators failed
- validate addon registration or headless smoke coverage

## Workflow

1. Prefer the unified entrypoint:

```powershell
python .\tools\run_blender_tests.py
```

If Blender auto-detection fails, use:

```powershell
python .\tools\run_blender_tests.py --blender "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Blender\\blender.exe"
```

2. Read the JSON report at:

```text
tests/artifacts/results.json
```

3. Report failures by test case name first, then the broken feature category.

## Current coverage

- addon registration smoke
- all `hst.*` operator registration smoke
- `_TransferProxy` reuse regression
- bake collection low/high smoke
- object vertex color set/copy smoke
- collision setup / extract UCX smoke
- bevel / weighted normal / triangulate modifier smoke
- AO bake operator smoke
- AO proxy topology regression
- decal project smoke
- quickweight smoke
- asset origin / snap transform / reset to origin smoke
- prop / decal collection marker smoke
- static mesh FBX export smoke
- bake collection FBX export smoke
- static mesh GLB export smoke
- rename bones smoke
- cleanup UE SKM smoke

## Notes

- This repository uses headless Blender tests, not pure Python unit tests only.
- Prefer adding regression tests for critical operator workflows by asserting intermediate state: collection, modifier, target object, topology, attribute, export file.
- When extending coverage, update `tests/blender_test_driver.py` first, then `tests/README.md`.
