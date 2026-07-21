# -*- coding: utf-8 -*-
"""在真实主文件上只读比较 Boolean rail oracle 与 source-surface offset rails。"""

import json
import os
import sys
from pathlib import Path

import bpy


def _make_material(name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def _make_curve_object(name, chains, material):
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = RADIUS * 0.045
    curve.bevel_resolution = 0
    curve.materials.append(material)
    for chain in chains:
        coordinates = chain["coordinates"]
        if len(coordinates) < 2:
            continue
        spline = curve.splines.new("POLY")
        spline.points.add(len(coordinates) - 1)
        for point, coordinate in zip(spline.points, coordinates):
            point.co = (*coordinate, 1.0)
        spline.use_cyclic_u = bool(chain.get("is_cyclic"))
    object_ = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(object_)
    return object_


REPO_ROOT = Path(os.environ["HST_ADDON_ROOT"])
sys.path.insert(0, str(REPO_ROOT.parent))
ADDON = __import__(REPO_ROOT.name)
UTILS = ADDON.utils.experimental_pipe_chamfer_utils
SOURCE = bpy.data.objects.get("Extruded.002")
if SOURCE is None:
    raise RuntimeError("Extruded.002 missing")

RADIUS = float(os.environ.get("HST_PHASE2_RADIUS", "0.01"))
RESOLUTION = int(os.environ.get("HST_PHASE2_RESOLUTION", "4"))
OUTPUT_PATH = Path(
    os.environ.get(
        "HST_PHASE2_PROBE_PATH",
        str(REPO_ROOT / "tests" / "artifacts" / "feature_chamfer_rail_phase2_probe.json"),
    )
)

fingerprint_before = ADDON.utils.feature_chamfer_gn_utils.source_fingerprint(SOURCE)
try:
    stats = UTILS.build_pipe_chamfer(
        source_object=SOURCE,
        radius=RADIUS,
        pipe_resolution=RESOLUTION,
        chain_turn_threshold_degrees=35.0,
        chain_turn_spike_ratio=3.0,
        junction_margin=1.5,
        debug_stage="OPEN_BOUNDARY",
        keep_debug_objects=True,
        feature_graph_contract="GN_PREVIEW_V1",
    )
except UTILS.PipeChamferError as error:
    stats = error.stats
fingerprint_after = ADDON.utils.feature_chamfer_gn_utils.source_fingerprint(SOURCE)

topology = stats.get("boundary_rail_topology", {})
owned_chains = topology.get("owned_chains", [])
unowned_chains = [
    {
        "coordinates": segment["coordinates"],
        "is_cyclic": False,
    }
    for segment in topology.get("unowned_segments", [])
]
deferred_chains = [
    {
        "coordinates": segment["coordinates"],
        "is_cyclic": False,
    }
    for segment in topology.get("deferred_segments", [])
]
output = bpy.data.objects.get(stats.get("output_object_name", ""))
if output is not None:
    output.display_type = "WIRE"
    output.color = (0.18, 0.18, 0.18, 1.0)
    output.show_name = True
owned_object = _make_curve_object(
    "HST_FinalBooleanBoundary_Owned",
    owned_chains,
    _make_material("HST_Rail_Owned_Green", (0.02, 1.0, 0.08, 1.0)),
)
unowned_object = _make_curve_object(
    "HST_FinalBooleanBoundary_RegularUnowned",
    unowned_chains,
    _make_material("HST_Rail_RegularUnowned_Red", (1.0, 0.0, 0.0, 1.0)),
)
deferred_object = _make_curve_object(
    "HST_FinalBooleanBoundary_JunctionTerminalDeferred",
    deferred_chains,
    _make_material("HST_Rail_Deferred_Orange", (1.0, 0.35, 0.0, 1.0)),
)
valid_pair_chains = []
invalid_pair_chains = []
valid_connectors = []
invalid_connectors = []
for record in stats.get("boolean_rail_pairs", []):
    is_valid = record["geometry_guard"]["status"] == "PASS"
    target = valid_pair_chains if is_valid else invalid_pair_chains
    connector_target = valid_connectors if is_valid else invalid_connectors
    target.extend(
        (
            {
                "coordinates": record["rail_left"],
                "is_cyclic": record["cyclic"],
            },
            {
                "coordinates": record["rail_right"],
                "is_cyclic": record["cyclic"],
            },
        )
    )
    left = record["rail_left"]
    right = record["rail_right"]
    left_u = UTILS._coordinate_parameters(
        [UTILS.Vector(point) for point in left],
        record["cyclic"],
    )
    right_u = UTILS._coordinate_parameters(
        [UTILS.Vector(point) for point in right],
        record["cyclic"],
    )
    connector_count = 8 if record["cyclic"] else 5
    parameters = [
        index / (connector_count if record["cyclic"] else connector_count - 1)
        for index in range(connector_count)
    ]
    connector_segments = []
    for parameter in parameters:
        left_index = min(
            range(len(left_u)),
            key=lambda index: abs(left_u[index] - parameter),
        )
        right_index = min(
            range(len(right_u)),
            key=lambda index: abs(right_u[index] - parameter),
        )
        connector_segments.append(
            {
                "coordinates": [left[left_index], right[right_index]],
                "is_cyclic": False,
            }
        )
    connector_lengths = [
        (
            UTILS.Vector(segment["coordinates"][1])
            - UTILS.Vector(segment["coordinates"][0])
        ).length
        for segment in connector_segments
    ]
    median_length = sorted(connector_lengths)[len(connector_lengths) // 2]
    correspondence_valid = (
        median_length <= RADIUS * 3.5
        and max(connector_lengths, default=0.0) <= RADIUS * 6.0
    )
    connector_target = (
        valid_connectors if correspondence_valid else invalid_connectors
    )
    connector_target.extend(connector_segments)
valid_pair_object = _make_curve_object(
    "HST_RailPairs_GuardPass",
    valid_pair_chains,
    _make_material("HST_RailPair_Pass_Cyan", (0.0, 0.65, 1.0, 1.0)),
)
invalid_pair_object = _make_curve_object(
    "HST_RailPairs_GuardFail",
    invalid_pair_chains,
    _make_material("HST_RailPair_Fail_Magenta", (1.0, 0.02, 0.6, 1.0)),
)
valid_connector_object = _make_curve_object(
    "HST_RailPairConnectors_GuardPass",
    valid_connectors,
    _make_material("HST_RailConnector_Pass_White", (1.0, 1.0, 1.0, 1.0)),
)
invalid_connector_object = _make_curve_object(
    "HST_RegularRailPairConnectors_CorrespondenceFail",
    invalid_connectors,
    _make_material("HST_RegularConnector_Fail_Red", (1.0, 0.0, 0.0, 1.0)),
)
valid_connector_object.name = "HST_RegularRailPairConnectors_CorrespondencePass"
if output is not None:
    owned_object.matrix_world = output.matrix_world.copy()
    unowned_object.matrix_world = output.matrix_world.copy()
    deferred_object.matrix_world = output.matrix_world.copy()
    valid_pair_object.matrix_world = output.matrix_world.copy()
    invalid_pair_object.matrix_world = output.matrix_world.copy()
    valid_connector_object.matrix_world = output.matrix_world.copy()
    invalid_connector_object.matrix_world = output.matrix_world.copy()
owned_object["hst_rail_semantics"] = "EXACT_FINAL_BOOLEAN_BOUNDARY_EDGE"
unowned_object["hst_rail_semantics"] = "REGULAR_UNOWNED_EXACT_BOUNDARY_EDGE"
deferred_object["hst_rail_semantics"] = "JUNCTION_OR_TERMINAL_DEFERRED_BOUNDARY_EDGE"

for key in ("boolean_rail_pairs", "surface_offset_rail_pairs"):
    for record in stats.get(key, []):
        record["max_width_error"] = max(record["width_error"], default=0.0)
        record["mean_width_error"] = (
            sum(record["width_error"]) / len(record["width_error"])
            if record["width_error"]
            else 0.0
        )

boolean_summary = stats.get("rail_oracle_summary", {}).get("boolean", {})
surface_summary = stats.get("rail_oracle_summary", {}).get("source_surface", {})
summary = {
    "status": stats.get("status"),
    "error_code": stats.get("error_code"),
    "source_file": bpy.data.filepath,
    "object": SOURCE.name,
    "radius": RADIUS,
    "profile_resolution": RESOLUTION,
    "feature_graph_contract": stats.get("feature_graph_contract"),
    "graph_alignment": stats.get("feature_graph_contract") == "GN_PREVIEW_V1",
    "source_fingerprint_unchanged": fingerprint_before == fingerprint_after,
    "boolean": boolean_summary,
    "source_surface": surface_summary,
    "boolean_max_width_error": max(
        (
            record["max_width_error"]
            for record in stats.get("boolean_rail_pairs", [])
        ),
        default=None,
    ),
    "surface_max_width_error": max(
        (
            record["max_width_error"]
            for record in stats.get("surface_offset_rail_pairs", [])
        ),
        default=None,
    ),
    "phase2_go": False,
    "phase2_gate": {
        "target_operator": "hst.feature_chamfer_gn",
        "user_action": "FINALIZE",
        "runtime_integration": False,
        "boundary_ownership_go": (
            topology.get("ownership_coverage") == 1.0
            and topology.get("unowned_edge_count") == 0
            and topology.get("deferred_edge_count") == 0
            and topology.get("adjacency_guard", {}).get("status") == "PASS"
            and topology.get("adjacency_guard", {}).get("consumable_rail_guard")
            == "PASS"
        ),
        "span_classification_go": (
            boolean_summary.get("classified_span_count")
            == boolean_summary.get("span_count")
            and boolean_summary.get("deferred_span_count") == 0
        ),
        "pairable_span_rail_go": (
            boolean_summary.get("pairable_coverage") == 1.0
            and boolean_summary.get("pairable_guarded_coverage") == 1.0
        ),
        "span_rail_go": (
            boolean_summary.get("coverage") == 1.0
            and boolean_summary.get("guarded_coverage") == 1.0
        ),
        "pairable_boundary_rail_contract_go": (
            boolean_summary.get("boundary_consumption_guard", {}).get("status")
            == "PASS"
            and not boolean_summary.get("unclassified_boundary_edge_indices")
            and boolean_summary.get("pairable_guarded_coverage") == 1.0
            and boolean_summary.get("deferred_span_count") == 0
        ),
        "rail_contract_go": False,
        "operator_go": False,
        "visual_product_go": False,
    },
    "scope": "RAIL_DIAGNOSTIC_ONLY",
}
stats["phase2_summary"] = summary
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
blend_artifact_path = OUTPUT_PATH.with_suffix(".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(blend_artifact_path))
summary["visual_artifact"] = str(blend_artifact_path)
summary["visual_legend"] = {
    "green": "owned exact final Boolean Boundary Edges",
    "red": "regular Boundary Edges with unresolved owner",
    "orange": "Boundary Edges still deferred from Rail ownership",
    "shared_owner": "multi-owner overlap Rail edges are included in the green exact Boundary partition",
    "cyan": "paired Rail A/B with geometry guard PASS",
    "magenta": "paired Rail A/B with geometry guard FAIL",
    "white": "regular cross-connectors with plausible Rail A/B correspondence",
    "red": "regular cross-connectors with implausible Rail A/B correspondence",
    "occluded": "endpoint spans with overlap evidence have no synthetic A/B connector",
    "deferred": "unresolved spans remain outside the Phase 2 GO count",
}
OUTPUT_PATH.write_text(
    json.dumps(stats, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("HST_PHASE2_PROBE=" + json.dumps(summary, ensure_ascii=False))
