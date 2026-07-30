---
name: hst-edge-visualizer
description: Create reusable Blender diagnostic artifacts that overlay selected HardsurfaceGameAssetToolkit edges as thick red, green, and blue markers with numbered labels in an inspectable .blend. Use when users ask to make problematic, residual, unconsumed, or otherwise hard-to-see HST edges visible from a diagnostics JSON containing edge_endpoints.
---

# HST Edge Visualizer

Generate the same colored Edge visualization without rewriting Blender Python.

## Inputs

Require:

- a source `.blend` artifact;
- its `diagnostics.json`;
- `repetitions[0].topology_diagnostics.edge_endpoints` containing `edge_id` and two local-space endpoints;
- matching `edge_ids` and `edge_lengths`;
- `object_name` and `radius` at the diagnostics root.

If `edge_endpoints` is absent, regenerate diagnostics with the relevant HST probe. Do not guess Edge coordinates from a screenshot or use nearest geometry.

## Run

Locate Blender first. On this macOS project, prefer:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --version
```

Then run:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --factory-startup \
  --python .agents/skills/hst-edge-visualizer/scripts/create_edge_visualization.py \
  -- SOURCE.blend DIAGNOSTICS.json OUTPUT.blend
```

The script sorts selected edges by length, applies red/green/blue in that order, adds numbered labels, darkens the source Mesh, and saves an inspectable `.blend`.

The current palette contains three colors. For more than three edges, filter the diagnostics to the exact three edges needed before running; do not silently omit ambiguous targets.

## Validate

Require Blender exit code `0`, the output `.blend` to exist and be non-empty, and the log to contain `Saved`. Never render or inspect an image. Visual correctness is decided only by the user opening the `.blend` in Blender.

Keep outputs in a run-specific artifact directory, preferably under `/private/tmp`. Never overwrite the source `.blend` or diagnostics.

## Report

Return the absolute path for the generated `.blend`, the Blender version used, and any missing-input or save error. When several cases need inspection, generate all `.blend` files first and return them together with one checklist. Ask the user for consolidated feedback. Do not claim that colored continuity proves ownership; this artifact supports human diagnosis only.
