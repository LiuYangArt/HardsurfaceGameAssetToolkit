# -*- coding: utf-8 -*-
"""对 Phase C tricky residual Boundary chain 执行只读 clean/dissolve A/B probe。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


PACKAGE_NAME = "hst_feature_chamfer_phase_c_clean_ab_probe_addon"
DEFAULT_FIXTURE = "tests/fixtures/feature-chamfer-product-tricky.blend"
DEFAULT_OBJECT = "Solid.004"
DEFAULT_RADIUS = 0.03
DEFAULT_TARGET_EDGE_IDS = (
    "d8ce93d1c4b2b13f3eab65c22edbbf1177d08e66bd2bad19164ed240b7e8e586",
    "8d21f0ea6c78dc5bdd3a14e830dea1f62d50c09572025502bb7d95c42a127fdc",
    "0cf5064cb369e00092499f3a73e9d3bae3ac9f484c2566b1e18b99d74d678c5e",
)
COLLINEAR_ANGLE_LIMIT_RADIANS = math.radians(0.5)
COLLINEAR_DISTANCE_LIMIT = 1.0e-5


# 解析 Blender 脚本参数；无参数，返回 argparse Namespace。
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--object", default=DEFAULT_OBJECT)
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS)
    parser.add_argument("--baseline-diagnostics")
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(arguments)


# 对稳定 JSON payload 生成 SHA-256；payload: JSON 可序列化数据；返回十六进制摘要。
def stable_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


# 返回文件 SHA-256；path: 待绑定证据的文件；返回十六进制摘要。
def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 从仓库 __init__.py 载入真实插件；repo_root: 仓库根目录；返回已注册模块。
def load_addon_module(repo_root):
    init_path = repo_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        init_path,
        submodule_search_locations=[str(repo_root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    module.register()
    return module


# 把 source 设为唯一 active Object；source_object: fixture Mesh；无返回值。
def activate_source(source_object):
    for selected_object in tuple(bpy.context.selected_objects):
        selected_object.select_set(False)
    source_object.hide_set(False)
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.context.view_layer.update()


# 从现有 Phase C 失败 diagnostics 读取目标 raw Edge IDs；path: 可选 diagnostics；返回稳定 Edge ID tuple。
def target_edge_ids_from_diagnostics(path):
    if path is None:
        return DEFAULT_TARGET_EDGE_IDS
    diagnostics = json.loads(path.read_text(encoding="utf-8"))
    repetitions = diagnostics.get("repetitions", ())
    if len(repetitions) != 1:
        raise RuntimeError("Baseline diagnostics must contain exactly one repetition")
    edge_ids = tuple(
        repetitions[0].get("topology_diagnostics", {}).get("edge_ids", ())
    )
    if len(edge_ids) != 3 or len(set(edge_ids)) != 3:
        raise RuntimeError("Baseline diagnostics does not expose exactly three residual Edge IDs")
    return edge_ids


# 建立目标 Operator PREVIEW 后的 independent staging universe；source/plan/parameters/module/collection: 真实入口状态；返回 staging 合同。
def build_independent_staging_contract(
    source_object,
    preview_plan,
    preview_parameters,
    batched_module,
    probe_collection,
):
    groups, pipes, pipe_specs = batched_module._build_preview_pipe_contract(
        source_object,
        preview_plan,
        preview_parameters,
        probe_collection,
    )
    batched_module._validate_plan_rail_coverage(preview_plan, groups)
    batched_module._normalize_pipe_winding(pipes)
    overlap_pairs = batched_module._pipe_overlap_pairs(pipes)
    color_batches = batched_module.color_pipe_overlap_graph(
        tuple(spec.pipe_id for spec in pipe_specs),
        overlap_pairs,
    )
    cut_diagnostics = batched_module._run_batch_order_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        preview_plan.plan_id,
    )
    if not cut_diagnostics["batch_order_invariant"]:
        raise RuntimeError("Fresh independent staging is not batch-order invariant")
    ledger = batched_module._build_staging_boundary_ledger(
        preview_plan,
        pipe_specs,
        cut_diagnostics["forward_cut_records"],
    )
    reverse_ledger = batched_module._build_staging_boundary_ledger(
        preview_plan,
        pipe_specs,
        cut_diagnostics["reverse_cut_records"],
    )
    if batched_module._stable_fingerprint(ledger) != batched_module._stable_fingerprint(
        reverse_ledger
    ):
        raise RuntimeError("Forward/reverse Boundary ledger differs")
    return {
        "groups": groups,
        "pipes": pipes,
        "pipe_specs": pipe_specs,
        "overlap_pairs": overlap_pairs,
        "color_batches": color_batches,
        "cut_diagnostics": cut_diagnostics,
        "ledger": ledger,
    }


# 按 endpoint token 连续性排序三个 raw Edge；entries: 未排序 target ledger entries；返回定向 entries 与点/token 序列。
def order_target_chain(entries):
    entries_by_id = {entry["edge_id"]: entry for entry in entries}
    edge_ids_by_token = {}
    coordinate_by_token = {}
    for entry in entries:
        for token, coordinate in zip(entry["endpoint_tokens"], entry["endpoints"]):
            edge_ids_by_token.setdefault(token, set()).add(entry["edge_id"])
            coordinate_by_token[token] = tuple(float(value) for value in coordinate)
    endpoints = sorted(
        token for token, edge_ids in edge_ids_by_token.items() if len(edge_ids) == 1
    )
    if len(endpoints) != 2:
        raise RuntimeError("Target residual Edges are not one open token chain")
    current = endpoints[0]
    remaining = set(entries_by_id)
    ordered_entries = []
    ordered_tokens = [current]
    while remaining:
        candidates = sorted(edge_ids_by_token[current] & remaining)
        if len(candidates) != 1:
            raise RuntimeError("Target residual Edge token walk is ambiguous")
        edge_id = candidates[0]
        entry = entries_by_id[edge_id]
        ordered_entries.append(entry)
        remaining.remove(edge_id)
        following = next(
            token for token in entry["endpoint_tokens"] if token != current
        )
        ordered_tokens.append(following)
        current = following
    return (
        tuple(ordered_entries),
        tuple(ordered_tokens),
        tuple(coordinate_by_token[token] for token in ordered_tokens),
    )


# 序列化 raw chain 的 token/provenance 合同；entries/tokens/coordinates: 有序 chain；返回机器可读合同。
def raw_chain_contract(entries, tokens, coordinates):
    return {
        "edge_ids": [entry["edge_id"] for entry in entries],
        "endpoint_tokens": list(tokens),
        "coordinates": [list(point) for point in coordinates],
        "edge_lengths": [
            (Vector(entry["endpoints"][1]) - Vector(entry["endpoints"][0])).length
            for entry in entries
        ],
        "pipe_ids": sorted({int(entry["pipe_id"]) for entry in entries}),
        "source_patch_ids": sorted(
            {int(entry["source_patch_id"]) for entry in entries}
        ),
        "rail_ids": sorted({entry["rail_id"] for entry in entries}),
        "semantic_batch_keys": sorted(
            {tuple(entry["semantic_batch_key"]) for entry in entries}
        ),
        "endpoint_port_tokens_by_edge": {
            entry["edge_id"]: list(entry.get("endpoint_port_tokens", ()))
            for entry in entries
        },
        "cutter_face_topology_by_edge": {
            entry["edge_id"]: list(entry.get("cutter_face_topology", ()))
            for entry in entries
        },
        "groove_face_signatures_by_edge": {
            entry["edge_id"]: list(entry.get("groove_face_signatures", ()))
            for entry in entries
        },
        "adjacent_face_signatures_by_edge": {
            entry["edge_id"]: list(entry.get("adjacent_face_signatures", ()))
            for entry in entries
        },
    }


# 计算 chain 内部 Vertex 的共线/degree/token/provenance 资格；entries/tokens/coordinates/universe: raw chain 与全 universe；返回逐点结果。
def evaluate_internal_vertices(entries, tokens, coordinates, universe):
    entry_by_id = {entry["edge_id"]: entry for entry in entries}
    universe_by_token = {}
    for entry in universe:
        for token in entry["endpoint_tokens"]:
            universe_by_token.setdefault(token, []).append(entry)
    results = []
    for internal_index, token in enumerate(tokens[1:-1], start=1):
        previous_point = Vector(coordinates[internal_index - 1])
        point = Vector(coordinates[internal_index])
        following_point = Vector(coordinates[internal_index + 1])
        incoming = point - previous_point
        outgoing = following_point - point
        dot = max(-1.0, min(1.0, incoming.normalized().dot(outgoing.normalized())))
        angle = math.acos(dot)
        chord = following_point - previous_point
        factor = (
            0.0
            if chord.length_squared <= 1.0e-20
            else (point - previous_point).dot(chord) / chord.length_squared
        )
        projected = previous_point + chord * factor
        distance = (point - projected).length
        incident_entries = universe_by_token.get(token, ())
        incident_edge_ids = sorted(entry["edge_id"] for entry in incident_entries)
        incident_owner_signatures = {
            (
                tuple(entry["semantic_batch_key"]),
                int(entry["pipe_id"]),
                int(entry["source_patch_id"]),
                entry["rail_id"],
            )
            for entry in incident_entries
        }
        incident_endpoint_port_tokens = {
            endpoint_token
            for entry in incident_entries
            for endpoint_token in entry.get("endpoint_port_tokens", ())
        }
        target_incident_edges = [
            entry_by_id[edge_id]
            for edge_id in incident_edge_ids
            if edge_id in entry_by_id
        ]
        direct_topology_complete = all(
            entry.get("cutter_face_topology")
            and entry.get("groove_face_signatures")
            and entry.get("adjacent_face_signatures")
            for entry in target_incident_edges
        )
        eligible = (
            len(incident_entries) == 2
            and len(target_incident_edges) == 2
            and len(incident_owner_signatures) == 1
            and not incident_endpoint_port_tokens
            and direct_topology_complete
            and angle <= COLLINEAR_ANGLE_LIMIT_RADIANS
            and distance <= COLLINEAR_DISTANCE_LIMIT
        )
        results.append(
            {
                "token": token,
                "coordinate": list(coordinates[internal_index]),
                "incident_edge_ids": incident_edge_ids,
                "degree": len(incident_entries),
                "owner_signatures": [
                    [list(batch_key), pipe_id, patch_id, rail_id]
                    for batch_key, pipe_id, patch_id, rail_id in sorted(
                        incident_owner_signatures
                    )
                ],
                "endpoint_port_tokens": sorted(incident_endpoint_port_tokens),
                "direct_topology_complete": direct_topology_complete,
                "angle_radians": angle,
                "angle_degrees": math.degrees(angle),
                "chord_distance": distance,
                "angle_limit_radians": COLLINEAR_ANGLE_LIMIT_RADIANS,
                "distance_limit": COLLINEAR_DISTANCE_LIMIT,
                "eligible": eligible,
                "rejection_reasons": [
                    reason
                    for condition, reason in (
                        (len(incident_entries) != 2, "NOT_DEGREE_2"),
                        (len(target_incident_edges) != 2, "NOT_TARGET_CHAIN_ONLY"),
                        (len(incident_owner_signatures) != 1, "MIXED_OWNER_PROVENANCE"),
                        (bool(incident_endpoint_port_tokens), "ENDPOINT_OR_PORT_TOKEN"),
                        (not direct_topology_complete, "INCOMPLETE_DIRECT_LINEAGE"),
                        (angle > COLLINEAR_ANGLE_LIMIT_RADIANS, "NOT_STRICTLY_COLLINEAR"),
                        (distance > COLLINEAR_DISTANCE_LIMIT, "COLLINEAR_DISTANCE_EXCEEDED"),
                    )
                    if condition
                ],
            }
        )
    return tuple(results)


# 按已批准的 eligible internal Vertex 合并 raw Edge lineage；entries/tokens/coordinates/evaluations/module: raw chain；返回 normalized contract。
def normalize_chain(entries, tokens, coordinates, evaluations, batched_module):
    eligible_tokens = {
        evaluation["token"]
        for evaluation in evaluations
        if evaluation["eligible"]
    }
    source_entry_by_id = {entry["edge_id"]: entry for entry in entries}
    segments = [
        {
            "raw_edge_ids": [entry["edge_id"]],
            "dissolved_internal_tokens": [],
            "start_token": tokens[index],
            "end_token": tokens[index + 1],
            "start_coordinate": coordinates[index],
            "end_coordinate": coordinates[index + 1],
        }
        for index, entry in enumerate(entries)
    ]
    normalized_segments = []
    current = dict(segments[0])
    for segment in segments[1:]:
        if current["end_token"] in eligible_tokens:
            current["dissolved_internal_tokens"] = [
                *current["dissolved_internal_tokens"],
                current["end_token"],
                *segment["dissolved_internal_tokens"],
            ]
            current["raw_edge_ids"] = [
                *current["raw_edge_ids"],
                *segment["raw_edge_ids"],
            ]
            current["end_token"] = segment["end_token"]
            current["end_coordinate"] = segment["end_coordinate"]
        else:
            normalized_segments.append(current)
            current = dict(segment)
    normalized_segments.append(current)
    records = []
    raw_edge_to_normalized_edge = {}
    for segment in normalized_segments:
        raw_entries = [source_entry_by_id[edge_id] for edge_id in segment["raw_edge_ids"]]
        provenance_signatures = {
            (
                tuple(entry["semantic_batch_key"]),
                int(entry["pipe_id"]),
                int(entry["source_patch_id"]),
                entry["rail_id"],
            )
            for entry in raw_entries
        }
        if len(provenance_signatures) != 1:
            raise RuntimeError("Normalization attempted to merge mixed provenance")
        normalized_edge_id = "normalized:" + stable_fingerprint(
            {
                "raw_edge_ids": segment["raw_edge_ids"],
                "endpoint_tokens": [segment["start_token"], segment["end_token"]],
            }
        )
        cutter_topology = sorted(
            {
                stable_fingerprint(record): record
                for entry in raw_entries
                for record in entry.get("cutter_face_topology", ())
            }.values(),
            key=stable_fingerprint,
        )
        record = {
            "normalized_edge_id": normalized_edge_id,
            "raw_edge_ids": list(segment["raw_edge_ids"]),
            "dissolved_internal_tokens": list(
                segment["dissolved_internal_tokens"]
            ),
            "endpoint_tokens": [segment["start_token"], segment["end_token"]],
            "endpoints": [
                list(segment["start_coordinate"]),
                list(segment["end_coordinate"]),
            ],
            "semantic_batch_key": list(raw_entries[0]["semantic_batch_key"]),
            "pipe_id": int(raw_entries[0]["pipe_id"]),
            "source_patch_id": int(raw_entries[0]["source_patch_id"]),
            "rail_id": raw_entries[0]["rail_id"],
            "endpoint_port_tokens": sorted(
                {
                    token
                    for entry in raw_entries
                    for token in entry.get("endpoint_port_tokens", ())
                }
            ),
            "adjacent_face_signatures": sorted(
                {
                    signature
                    for entry in raw_entries
                    for signature in entry.get("adjacent_face_signatures", ())
                }
            ),
            "groove_face_signatures": sorted(
                {
                    signature
                    for entry in raw_entries
                    for signature in entry.get("groove_face_signatures", ())
                }
            ),
            "cutter_face_topology": cutter_topology,
        }
        records.append(record)
        for raw_edge_id in segment["raw_edge_ids"]:
            if raw_edge_id in raw_edge_to_normalized_edge:
                raise RuntimeError("Raw Edge mapped to more than one normalized Edge")
            raw_edge_to_normalized_edge[raw_edge_id] = normalized_edge_id
    raw_edge_ids = [entry["edge_id"] for entry in entries]
    exactly_once = (
        sorted(raw_edge_to_normalized_edge) == sorted(raw_edge_ids)
        and len(raw_edge_to_normalized_edge) == len(raw_edge_ids)
    )
    return {
        "eligible_internal_tokens": sorted(eligible_tokens),
        "records": records,
        "raw_edge_to_normalized_edge": raw_edge_to_normalized_edge,
        "exactly_once": exactly_once,
        "lineage_fingerprint": batched_module._stable_fingerprint(
            raw_edge_to_normalized_edge
        ),
    }


# 对 normalized Edge 的 cutter topology 查找唯一 direct opposite Face Boundary Edge；records/universe: normalized 与 raw universe；返回证据。
def direct_opposite_witnesses(records, universe):
    raw_face_records = [
        (entry, face_record)
        for entry in universe
        for face_record in entry.get("cutter_face_topology", ())
        if face_record.get("topology_status") == "PROVEN_C4_PIPE"
    ]
    witnesses = []
    for record in records:
        face_records = [
            face_record
            for face_record in record["cutter_face_topology"]
            if face_record.get("topology_status") == "PROVEN_C4_PIPE"
        ]
        opposite_signatures = sorted(
            {
                face_record.get("profile_opposite_face_signature")
                for face_record in face_records
                if face_record.get("profile_opposite_face_signature")
            }
        )
        opposite_edges = sorted(
            {
                entry["edge_id"]
                for entry, face_record in raw_face_records
                if face_record.get("face_signature") in opposite_signatures
                and int(entry["pipe_id"]) == int(record["pipe_id"])
                and int(entry["source_patch_id"]) != int(record["source_patch_id"])
            }
        )
        witnesses.append(
            {
                "normalized_edge_id": record["normalized_edge_id"],
                "raw_edge_ids": list(record["raw_edge_ids"]),
                "profile_opposite_face_signatures": opposite_signatures,
                "direct_opposite_boundary_edge_ids": opposite_edges,
                "direct_witness_count": len(opposite_edges),
                "status": "UNIQUE" if len(opposite_edges) == 1 else "MISSING" if not opposite_edges else "AMBIGUOUS",
            }
        )
    return witnesses


# 用 source duplicate 证明 dissolve 只改变 staging 副本；source/raw/normalized/evaluations/output: probe 上下文；返回几何与 Mesh artifact 合同。
def create_staging_ab_artifact(
    source_object,
    raw_contract,
    normalized_contract,
    evaluations,
    output_path,
):
    collection = bpy.data.collections.new("HST_PhaseC_CleanAB_Probe")
    bpy.context.scene.collection.children.link(collection)
    a_mesh = bpy.data.meshes.new("HST_PhaseC_CleanAB_A_Raw_Mesh")
    raw_edges = [
        (index, index + 1)
        for index in range(len(raw_contract["coordinates"]) - 1)
    ]
    a_mesh.from_pydata(raw_contract["coordinates"], raw_edges, [])
    a_mesh.update()
    a_object = bpy.data.objects.new("HST_PhaseC_CleanAB_A_Raw", a_mesh)
    collection.objects.link(a_object)
    a_object.matrix_world = source_object.matrix_world.copy()
    b_mesh = bpy.data.meshes.new("HST_PhaseC_CleanAB_B_Normalized_Mesh")
    staging_bmesh = bmesh.new()
    staging_bmesh.from_mesh(a_mesh)
    staging_bmesh.verts.ensure_lookup_table()
    eligible_tokens = set(normalized_contract["eligible_internal_tokens"])
    dissolve_vertices = [
        staging_bmesh.verts[index]
        for index, token in enumerate(raw_contract["endpoint_tokens"])
        if token in eligible_tokens
    ]
    if len(dissolve_vertices) != len(eligible_tokens):
        staging_bmesh.free()
        raise RuntimeError("BMesh dissolve candidates do not match eligible token lineage")
    if dissolve_vertices:
        dissolve_vertex_count = len(dissolve_vertices)
        bmesh.ops.dissolve_verts(
            staging_bmesh,
            verts=dissolve_vertices,
            use_face_split=False,
            use_boundary_tear=False,
        )
    else:
        dissolve_vertex_count = 0
    staging_bmesh.to_mesh(b_mesh)
    staging_bmesh.free()
    b_mesh.update()
    b_object = bpy.data.objects.new("HST_PhaseC_CleanAB_B_Normalized", b_mesh)
    collection.objects.link(b_object)
    b_object.matrix_world = source_object.matrix_world.copy()
    a_object.display_type = "WIRE"
    b_object.display_type = "WIRE"
    a_object["hst_phase_c_clean_ab_group"] = "A_RAW"
    b_object["hst_phase_c_clean_ab_group"] = "B_NORMALIZED"
    b_object["hst_raw_edge_to_normalized_edge"] = json.dumps(
        normalized_contract["raw_edge_to_normalized_edge"], sort_keys=True
    )
    b_object["hst_candidate_evaluations"] = json.dumps(
        evaluations, sort_keys=True
    )
    actual_edge_signatures = sorted(
        tuple(
            sorted(
                tuple(round(float(value), 7) for value in b_mesh.vertices[index].co)
                for index in edge.vertices
            )
        )
        for edge in b_mesh.edges
    )
    expected_edge_signatures = sorted(
        tuple(
            sorted(
                tuple(round(float(value), 7) for value in endpoint)
                for endpoint in record["endpoints"]
            )
        )
        for record in normalized_contract["records"]
    )
    bpy.ops.wm.save_as_mainfile(
        filepath=str(output_path),
        check_existing=False,
        compress=True,
        copy=True,
    )
    return {
        "blend_path": str(output_path),
        "blend_sha256": file_sha256(output_path),
        "a_vertex_count": len(a_mesh.vertices),
        "a_edge_count": len(a_mesh.edges),
        "b_vertex_count": len(b_mesh.vertices),
        "b_edge_count": len(b_mesh.edges),
        "actual_bmesh_dissolve_count": dissolve_vertex_count,
        "actual_bmesh_geometry_matches_lineage": (
            actual_edge_signatures == expected_edge_signatures
        ),
        "source_object_name": source_object.name,
    }


# 执行完整只读 A/B probe 并写 JSON/.blend artifact；arguments: CLI 参数；无返回值。
def main(arguments):
    repo_root = Path(arguments.repo_root).resolve()
    artifact_directory = Path(arguments.artifact_dir).resolve()
    artifact_directory.mkdir(parents=True, exist_ok=True)
    fixture_path = (repo_root / arguments.fixture).resolve()
    baseline_path = (
        Path(arguments.baseline_diagnostics).resolve()
        if arguments.baseline_diagnostics
        else None
    )
    target_edge_ids = target_edge_ids_from_diagnostics(baseline_path)
    bpy.ops.wm.open_mainfile(
        filepath=str(fixture_path),
        load_ui=False,
        use_scripts=False,
    )
    addon_module = load_addon_module(repo_root)
    source_object = bpy.data.objects.get(arguments.object)
    if source_object is None or source_object.type != "MESH":
        raise RuntimeError(f"Fixture Mesh missing: {arguments.object}")
    preview_utils = addon_module.utils.feature_chamfer_gn_utils
    source_fingerprint_before = preview_utils.source_fingerprint(source_object)
    activate_source(source_object)
    preview_result = sorted(
        bpy.ops.hst.feature_chamfer_gn(
            "INVOKE_DEFAULT",
            action="PREVIEW",
            radius=arguments.radius,
        )
    )
    if preview_result != ["FINISHED"]:
        raise RuntimeError(f"Target PREVIEW Operator failed: {preview_result}")
    preview_modifier = preview_utils.owned_preview_modifier(source_object)
    preview_plan = addon_module.utils.feature_chamfer_plan_utils.read_chamfer_plan(
        preview_modifier
    )
    preview_parameters = preview_utils.live_preview_parameters(preview_modifier)
    phase_c_adapter_result = sorted(
        bpy.ops.hst.experimental_feature_chamfer_batched_finalize(
            "INVOKE_DEFAULT",
            debug_stage="PHASE_C_REGULAR_CORE",
        )
    )
    phase_c_diagnostics = json.loads(
        bpy.context.scene.get("hst_feature_chamfer_batched_last_result", "{}")
    )
    phase_c_failure_code = phase_c_diagnostics.get("failure_code")
    phase_c_edge_ids = tuple(
        phase_c_diagnostics.get("topology_diagnostics", {}).get("edge_ids", ())
    )
    if phase_c_adapter_result != ["CANCELLED"]:
        raise RuntimeError(
            f"Expected Phase C Adapter fail-closed, got: {phase_c_adapter_result}"
        )
    if phase_c_failure_code != "UNPROVEN_PLAN_BOUNDARY_EDGE":
        raise RuntimeError(
            f"Unexpected Phase C Adapter failure: {phase_c_failure_code}"
        )
    if set(phase_c_edge_ids) != set(target_edge_ids):
        raise RuntimeError("Fresh Phase C Adapter residual Edge IDs changed")
    if preview_utils.source_fingerprint(source_object) != source_fingerprint_before:
        raise RuntimeError("Phase C Adapter modified source while failing closed")
    probe_collection = bpy.data.collections.new("HST_PhaseC_CleanAB_Temporary")
    bpy.context.scene.collection.children.link(probe_collection)
    batched_module = addon_module.utils.feature_chamfer_batched_finalize_utils
    staging = build_independent_staging_contract(
        source_object,
        preview_plan,
        preview_parameters,
        batched_module,
        probe_collection,
    )
    target_entries = [
        entry for entry in staging["ledger"] if entry["edge_id"] in target_edge_ids
    ]
    if {entry["edge_id"] for entry in target_entries} != set(target_edge_ids):
        raise RuntimeError("Fresh staging does not reproduce all target residual Edges")
    ordered_entries, ordered_tokens, ordered_coordinates = order_target_chain(
        target_entries
    )
    raw_contract = raw_chain_contract(
        ordered_entries,
        ordered_tokens,
        ordered_coordinates,
    )
    evaluations = evaluate_internal_vertices(
        ordered_entries,
        ordered_tokens,
        ordered_coordinates,
        staging["ledger"],
    )
    normalized_contract = normalize_chain(
        ordered_entries,
        ordered_tokens,
        ordered_coordinates,
        evaluations,
        batched_module,
    )
    opposite_witnesses = direct_opposite_witnesses(
        normalized_contract["records"],
        staging["ledger"],
    )
    raw_length = sum(raw_contract["edge_lengths"])
    normalized_length = sum(
        (Vector(record["endpoints"][1]) - Vector(record["endpoints"][0])).length
        for record in normalized_contract["records"]
    )
    removed_internal_tokens = set(ordered_tokens) - {
        token
        for record in normalized_contract["records"]
        for token in record["endpoint_tokens"]
    }
    dissolved_lineage_tokens = {
        token
        for record in normalized_contract["records"]
        for token in record["dissolved_internal_tokens"]
    }
    raw_port_tokens = {
        token
        for entry in ordered_entries
        for token in entry.get("endpoint_port_tokens", ())
    }
    normalized_port_tokens = {
        token
        for record in normalized_contract["records"]
        for token in record.get("endpoint_port_tokens", ())
    }
    normalized_endpoint_tokens = {
        token
        for record in normalized_contract["records"]
        for token in record["endpoint_tokens"]
    }
    maximum_removed_vertex_deviation = max(
        (
            evaluation["chord_distance"]
            for evaluation in evaluations
            if evaluation["eligible"]
        ),
        default=0.0,
    )
    raw_owner_signature = {
        (
            tuple(entry["semantic_batch_key"]),
            int(entry["pipe_id"]),
            int(entry["source_patch_id"]),
            entry["rail_id"],
        )
        for entry in ordered_entries
    }
    normalized_owner_signature = {
        (
            tuple(record["semantic_batch_key"]),
            int(record["pipe_id"]),
            int(record["source_patch_id"]),
            record["rail_id"],
        )
        for record in normalized_contract["records"]
    }
    source_unchanged = (
        preview_utils.source_fingerprint(source_object) == source_fingerprint_before
    )
    group_b_contracts = {
        "geometry_preserved": (
            normalized_contract["records"][0]["endpoints"][0]
            == raw_contract["coordinates"][0]
            and normalized_contract["records"][-1]["endpoints"][1]
            == raw_contract["coordinates"][-1]
            and abs(raw_length - normalized_length) <= 1.0e-7
            and maximum_removed_vertex_deviation <= COLLINEAR_DISTANCE_LIMIT
        ),
        "raw_length": raw_length,
        "normalized_length": normalized_length,
        "length_delta": normalized_length - raw_length,
        "maximum_removed_vertex_deviation": maximum_removed_vertex_deviation,
        "normalization_distance_limit": COLLINEAR_DISTANCE_LIMIT,
        "terminal_tokens_preserved": {
            ordered_tokens[0],
            ordered_tokens[-1],
        }.issubset(normalized_endpoint_tokens),
        "dissolved_tokens_preserved_in_lineage": (
            removed_internal_tokens == dissolved_lineage_tokens
        ),
        "port_tokens_unchanged": raw_port_tokens == normalized_port_tokens,
        "protected_token_preserved": (
            {ordered_tokens[0], ordered_tokens[-1]}.issubset(
                normalized_endpoint_tokens
            )
            and removed_internal_tokens == dissolved_lineage_tokens
            and raw_port_tokens == normalized_port_tokens
        ),
        "removed_internal_tokens": sorted(removed_internal_tokens),
        "dissolved_lineage_tokens": sorted(dissolved_lineage_tokens),
        "raw_port_tokens": sorted(raw_port_tokens),
        "normalized_port_tokens": sorted(normalized_port_tokens),
        "pipe_patch_rail_provenance_preserved": (
            raw_owner_signature == normalized_owner_signature
        ),
        "raw_edge_exactly_once": normalized_contract["exactly_once"],
        "source_unchanged": source_unchanged,
    }
    blend_artifact = create_staging_ab_artifact(
        source_object,
        raw_contract,
        normalized_contract,
        evaluations,
        artifact_directory / "phase_c_clean_ab_probe.blend",
    )
    group_b_contracts["actual_bmesh_geometry_matches_lineage"] = blend_artifact[
        "actual_bmesh_geometry_matches_lineage"
    ]
    all_contracts_preserved = all(
        group_b_contracts[key]
        for key in (
            "geometry_preserved",
            "protected_token_preserved",
            "pipe_patch_rail_provenance_preserved",
            "raw_edge_exactly_once",
            "source_unchanged",
            "actual_bmesh_geometry_matches_lineage",
        )
    )
    direct_witness_recovered = all(
        witness["status"] == "UNIQUE" for witness in opposite_witnesses
    )
    decision = (
        "CLEAN_NORMALIZATION_CANDIDATE"
        if all_contracts_preserved and direct_witness_recovered
        else "STOP_CLEAN_ROUTE_PIVOT_RESIDUAL_OWNERSHIP_GRAPH"
    )
    report = {
        "contract": "HST_PHASE_C_CLEAN_AB_PROBE_V1",
        "status": "PROTOTYPE",
        "phase_c_gate": "STOP",
        "decision": decision,
        "target_contract": {
            "ui_entry": "Feature Chamfer GN",
            "operator_chain": [
                "hst.feature_chamfer_gn(action=PREVIEW)",
                "hst.experimental_feature_chamfer_batched_finalize(debug_stage=PHASE_C_REGULAR_CORE)",
            ],
            "runtime_path": "PHASE_C_REGULAR_CORE Adapter then independent staging copy",
            "user_visible_result": "debug artifacts only; FINALIZE unchanged",
        },
        "environment": {
            "blender_version": bpy.app.version_string,
            "fixture": str(fixture_path),
            "fixture_sha256": file_sha256(fixture_path),
            "object_name": source_object.name,
            "radius": float(arguments.radius),
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        },
        "operator_evidence": {
            "preview_result": preview_result,
            "preview_state": preview_utils.preview_state(source_object),
            "phase_c_adapter_result": phase_c_adapter_result,
            "phase_c_failure_code": phase_c_failure_code,
            "phase_c_residual_edge_ids": list(phase_c_edge_ids),
            "plan_id": preview_plan.plan_id,
            "source_fingerprint_before": source_fingerprint_before,
            "source_fingerprint_after": preview_utils.source_fingerprint(
                source_object
            ),
        },
        "staging_evidence": {
            "cut_strategy": staging["cut_diagnostics"]["cut_strategy"],
            "batch_order_invariant": staging["cut_diagnostics"][
                "batch_order_invariant"
            ],
            "forward_reverse_built_independently": staging["cut_diagnostics"][
                "forward_reverse_built_independently"
            ],
            "color_batches": [list(batch) for batch in staging["color_batches"]],
            "boundary_edge_count": len(staging["ledger"]),
            "boundary_universe_fingerprint": batched_module._stable_fingerprint(
                staging["ledger"]
            ),
        },
        "group_a_raw": raw_contract,
        "candidate_internal_vertices": list(evaluations),
        "probe_only_normalization_limits": {
            "angle_degrees": math.degrees(COLLINEAR_ANGLE_LIMIT_RADIANS),
            "chord_distance": COLLINEAR_DISTANCE_LIMIT,
            "runtime_threshold_authorized": False,
        },
        "group_b_normalized": {
            **normalized_contract,
            "contracts": group_b_contracts,
        },
        "regular_consumer_probe": {
            "required_witness": "OPPOSITE_CUTTER_PROFILE_FACES_V1 direct Boundary incidence",
            "normalized_edge_witnesses": opposite_witnesses,
            "direct_witness_recovered": direct_witness_recovered,
            "nearest_or_coordinate_matching_used": False,
            "synthetic_owner_or_port_used": False,
        },
        "stop_go": {
            "all_preservation_contracts_pass": all_contracts_preserved,
            "all_normalized_edges_have_unique_direct_consumer": direct_witness_recovered,
            "clean_route_go": decision == "CLEAN_NORMALIZATION_CANDIDATE",
            "residual_ownership_graph_required": decision
            == "STOP_CLEAN_ROUTE_PIVOT_RESIDUAL_OWNERSHIP_GRAPH",
            "phase_d_or_e_authorized": False,
            "formal_finalize_modified": False,
        },
        "artifacts": blend_artifact,
    }
    report_path = artifact_directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[HST_PHASE_C_CLEAN_AB_PROBE]" + json.dumps(
        {
            "decision": decision,
            "eligible_internal_token_count": sum(
                evaluation["eligible"] for evaluation in evaluations
            ),
            "direct_witness_recovered": direct_witness_recovered,
            "report": str(report_path),
        },
        separators=(",", ":"),
    ))


if __name__ == "__main__":
    main(parse_arguments())
