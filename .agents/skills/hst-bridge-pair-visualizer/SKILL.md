---
name: hst-bridge-pair-visualizer
description: Capture every actual HardsurfaceGameAssetToolkit Feature Chamfer Bridge Edge Loop pair from the formal Preview/Finalize runtime after all open U-turn or cyclic job segmentation, then create an inspectable Blender file with pairs named 1a/1b, 2a/2b, and so on. Use when a user needs to verify whether visible Bridge topology distortion comes from the production pairing or from Blender's native Bridge behavior.
---

# HST Bridge Pair Visualizer

Generate a diagnostic artifact from the exact Edge components passed to Blender's native Bridge operation. Never infer or reconstruct pairs from a screenshot, the final Mesh, proximity, or pre-segmentation plans.

## Inputs

Require:

- a Feature Chamfer fixture `.blend`;
- the exact source Mesh object name;
- a Radius;
- a run-specific output directory, preferably under `/private/tmp`.

Use Blender 5.0+ and locate the executable before running. On this macOS project, prefer `/Applications/Blender.app/Contents/MacOS/Blender` and validate it with `--version`.

## Run

Run the bundled orchestrator from the repository root:

```bash
python3 .agents/skills/hst-bridge-pair-visualizer/scripts/create_bridge_pair_visualization.py \
  --fixture tests/fixtures/feature-chamfer-product-tricky-b.blend \
  --object 'Extruded.002' \
  --radius 0.01 \
  --output-dir /private/tmp/hst-bridge-pairs-run
```

Override Blender only when required:

```bash
python3 .agents/skills/hst-bridge-pair-visualizer/scripts/create_bridge_pair_visualization.py \
  --blender /absolute/path/to/Blender \
  --fixture /absolute/path/to/fixture.blend \
  --object 'Object Name' \
  --radius 0.03 \
  --output-dir /private/tmp/hst-bridge-pairs-run
```

The orchestrator runs the formal UI Operator Preview and Finalize. A temporary hook records each native Bridge call after production job segmentation. The render script creates one collection per pair and only the Curve objects named `1a`, `1b`, `2a`, `2b`, and so on; it does not create separate label objects. Cyclic sides remain cyclic in the visualization.

## Validate

Require all of the following:

- both Blender processes exit `0`;
- Preview and Finalize report `FINISHED`;
- `pair_count` is greater than zero;
- every pair contains exactly two sides;
- runtime indices are continuous from `1` through `pair_count`;
- the `.blend`, PNG, JSON capture, and manifest exist and are non-empty;
- each manifest side has the expected numbered object name.

Do not claim that visual proximity proves correct ownership. This artifact shows the exact production Bridge inputs so the user can identify a suspicious group. Wait for the user's group number before changing pairing rules.

## Outputs

Return absolute paths for:

- `bridge-pairs.blend` — primary inspectable artifact;
- `bridge-pairs.png` — overview render;
- `pair-manifest.json` — group number, edge count, length, and cyclic state;
- `runtime-pairs.json` — captured coordinates and formal runtime result;
- `run-summary.json` — validation status and Blender version.

Also report the Radius, object name, pair count, and whether every manifest check passed.
