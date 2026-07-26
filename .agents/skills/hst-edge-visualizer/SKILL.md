---
name: hst-edge-visualizer
description: Create reusable Blender diagnostic artifacts that overlay selected HardsurfaceGameAssetToolkit edges as thick red, green, and blue markers with numbered labels, a close-up camera, a rendered PNG, and an inspectable .blend. Use when users ask to make problematic, residual, unconsumed, or otherwise hard-to-see HST edges visible from a diagnostics JSON containing edge_endpoints.
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
  -- SOURCE.blend DIAGNOSTICS.json OUTPUT.blend OUTPUT.png
```

The script sorts selected edges by length, applies red/green/blue in that order, adds numbered labels, darkens the source Mesh, frames the markers, renders a close-up PNG, and saves an inspectable `.blend`.

The current palette contains three colors. For more than three edges, filter the diagnostics to the exact three edges needed before running; do not silently omit ambiguous targets.

## Validate

Require Blender exit code `0`, both output files to exist and be non-empty, and the log to contain `Saved` plus a completed render. Open or inspect the PNG only when visual verification is requested.

Before model-side visual inspection, create a lightweight JPEG preview and inspect that preview only. Never pass the rendered PNG to `view_image` with `detail: "original"`.

```bash
/usr/bin/sips -s format jpeg -s formatOptions 72 -Z 1400 \
  OUTPUT.png --out OUTPUT-preview.jpg
```

Require each preview to be at most 350 KB. If it is larger, retry with a 1000 px longest edge and JPEG quality 58. View no more than three previews in one Codex task; crop the region of interest or reuse an existing observation before viewing more images. This prevents diagnostic renders from being embedded into task history at full PNG size and triggering a provider payload limit.

Keep outputs in a run-specific artifact directory, preferably under `/private/tmp`. Never overwrite the source `.blend` or diagnostics.

## Report

Return absolute paths for the generated `.blend` and PNG, the Blender version used, and any missing-input or render error. Do not claim that colored continuity proves ownership; this artifact supports human diagnosis only.
