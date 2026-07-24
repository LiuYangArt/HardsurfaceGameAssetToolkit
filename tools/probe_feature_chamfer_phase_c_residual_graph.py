# -*- coding: utf-8 -*-
"""从真实 PREVIEW→Phase C Adapter 运行只读 ResidualOwnershipGraph probe。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import bpy


PACKAGE_NAME = "hst_feature_chamfer_phase_c_residual_graph_probe_addon"
DEFAULT_FIXTURE = "tests/fixtures/feature-chamfer-product-tricky.blend"
DEFAULT_OBJECT = "Solid.004"
DEFAULT_RADIUS = 0.03
DEFAULT_TARGET_EDGE_IDS = (
    "d8ce93d1c4b2b13f3eab65c22edbbf1177d08e66bd2bad19164ed240b7e8e586",
    "8d21f0ea6c78dc5bdd3a14e830dea1f62d50c09572025502bb7d95c42a127fdc",
    "0cf5064cb369e00092499f3a73e9d3bae3ac9f484c2566b1e18b99d74d678c5e",
)


# 解析 Blender 脚本参数。
# 无参数；返回 argparse Namespace。
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


# 返回文件 SHA-256。
# path: 待绑定 evidence 的文件；返回十六进制摘要。
def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 从仓库 __init__.py 载入真实插件。
# repo_root: 仓库根目录；返回已注册模块。
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


# 把 source 设为唯一 active Mesh Object。
# source_object: fixture 中的目标 Object；无返回值。
def activate_source(source_object):
    for selected_object in tuple(bpy.context.selected_objects):
        selected_object.select_set(False)
    source_object.hide_set(False)
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.context.view_layer.update()


# 从可选 single-cell diagnostics 读取目标 residual raw Edge IDs。
# path: diagnostics JSON 路径或 None；返回稳定 Edge ID tuple。
def target_edge_ids_from_diagnostics(path):
    if path is None:
        return DEFAULT_TARGET_EDGE_IDS
    diagnostics = json.loads(path.read_text(encoding="utf-8"))
    repetitions = diagnostics.get("repetitions", ())
    if len(repetitions) != 1:
        raise RuntimeError("Baseline diagnostics 必须恰好包含一次 repetition")
    edge_ids = tuple(
        repetitions[0].get("topology_diagnostics", {}).get("edge_ids", ())
    )
    if len(edge_ids) != 3 or len(set(edge_ids)) != 3:
        raise RuntimeError("Baseline diagnostics 未暴露目标三条 residual Edge")
    return edge_ids


# 建立含完整 cutter Face 图的 fresh independent staging universe。
# source/plan/parameters/module/collection: 真实 PREVIEW 状态；返回正逆序稳定 staging 合同。
def build_graph_staging_contract(
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
    forward = batched_module._run_independent_batch_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        preview_plan.plan_id,
        "FORWARD",
        include_complete_cutter_face_records=True,
    )
    reverse = batched_module._run_independent_batch_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        preview_plan.plan_id,
        "REVERSE",
        include_complete_cutter_face_records=True,
    )
    forward_ledger = batched_module._build_staging_boundary_ledger(
        preview_plan,
        pipe_specs,
        forward["records"],
    )
    reverse_ledger = batched_module._build_staging_boundary_ledger(
        preview_plan,
        pipe_specs,
        reverse["records"],
    )
    complete_cutter_face_records = tuple(
        sorted(
            {
                batched_module._stable_fingerprint(face_record): face_record
                for record in forward["records"]
                for face_record in record.get("complete_cutter_face_records", ())
            }.values(),
            key=batched_module._stable_fingerprint,
        )
    )
    reverse_complete_cutter_face_records = tuple(
        sorted(
            {
                batched_module._stable_fingerprint(face_record): face_record
                for record in reverse["records"]
                for face_record in record.get("complete_cutter_face_records", ())
            }.values(),
            key=batched_module._stable_fingerprint,
        )
    )
    if batched_module._stable_fingerprint(forward_ledger) != batched_module._stable_fingerprint(
        reverse_ledger
    ):
        raise RuntimeError("Forward/reverse Boundary ledger 不一致")
    if batched_module._stable_fingerprint(
        complete_cutter_face_records
    ) != batched_module._stable_fingerprint(reverse_complete_cutter_face_records):
        raise RuntimeError("Forward/reverse complete cutter Face graph 不一致")
    return {
        "groups": groups,
        "pipes": pipes,
        "pipe_specs": pipe_specs,
        "overlap_pairs": overlap_pairs,
        "color_batches": color_batches,
        "forward_ledger": forward_ledger,
        "reverse_ledger": reverse_ledger,
        "complete_cutter_face_records": complete_cutter_face_records,
        "reverse_complete_cutter_face_records": reverse_complete_cutter_face_records,
    }


# 从 producer-only partition 提取全局 RegularBridgeJob claims 与 frozen setback proofs。
# preview/groups/staging/overlap/radius/module: Phase C graph 上下文；返回只读 subtraction 合同。
def build_global_subtraction_contract(
    preview_plan,
    groups,
    staging_rail_chains,
    boundary_ledger,
    overlap_pairs,
    overlap_setback_intervals,
    radius,
    batched_module,
):
    producer_jobs, setback_ports, strip_attempts = (
        batched_module._build_cyclic_regular_strip_partition(
            preview_plan,
            groups,
            staging_rail_chains,
            boundary_ledger,
            overlap_pairs,
            overlap_setback_intervals,
            radius,
            producer_only=True,
        )
    )
    claims_by_edge_id, unresolved_edge_ids = (
        batched_module._preflight_regular_bridge_claims(
            producer_jobs,
            (entry["edge_id"] for entry in boundary_ledger),
        )
    )
    regular_claims = tuple(
        {"edge_id": edge_id, **claim}
        for edge_id, claim in sorted(claims_by_edge_id.items())
    )
    setback_proofs = tuple(
        {
            "proof_version": port.get("reason", "PRODUCER_SETBACK_PORT"),
            "edge_ids": list(port.get("ordered_edge_ids", ())),
            "port_id": port.get("port_id"),
            "proof": port.get("proof"),
        }
        for port in setback_ports
        if port.get("ordered_edge_ids")
    )
    return {
        "producer_jobs": producer_jobs,
        "regular_claims": regular_claims,
        "setback_proofs": setback_proofs,
        "unresolved_edge_ids": unresolved_edge_ids,
        "strip_attempt_fingerprint": batched_module._stable_fingerprint(
            strip_attempts
        ),
    }


# 执行目标入口与只读 graph probe，并写 machine-readable artifact。
# arguments: Blender CLI 参数；无返回值。
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
    adapter_result = sorted(
        bpy.ops.hst.experimental_feature_chamfer_batched_finalize(
            "INVOKE_DEFAULT",
            debug_stage="PHASE_C_REGULAR_CORE",
        )
    )
    adapter_diagnostics = json.loads(
        bpy.context.scene.get("hst_feature_chamfer_batched_last_result", "{}")
    )
    adapter_residual_edge_ids = tuple(
        adapter_diagnostics.get("topology_diagnostics", {}).get("edge_ids", ())
    )
    if adapter_result != ["CANCELLED"]:
        raise RuntimeError(f"Expected Phase C STOP, got: {adapter_result}")
    if adapter_diagnostics.get("failure_code") != "UNPROVEN_PLAN_BOUNDARY_EDGE":
        raise RuntimeError(
            f"Unexpected Phase C failure: {adapter_diagnostics.get('failure_code')}"
        )
    if set(adapter_residual_edge_ids) != set(target_edge_ids):
        raise RuntimeError("Fresh Phase C residual Edge IDs changed")
    if preview_utils.source_fingerprint(source_object) != source_fingerprint_before:
        raise RuntimeError("Phase C Adapter changed source while failing closed")
    probe_collection = bpy.data.collections.new("HST_PhaseC_ResidualGraph_Temporary")
    bpy.context.scene.collection.children.link(probe_collection)
    batched_module = addon_module.utils.feature_chamfer_batched_finalize_utils
    graph_module = (
        addon_module.utils.feature_chamfer_residual_ownership_graph_utils
    )
    staging = build_graph_staging_contract(
        source_object,
        preview_plan,
        preview_parameters,
        batched_module,
        probe_collection,
    )
    forward_rail_chains = batched_module._build_staging_rail_chains(
        staging["forward_ledger"]
    )
    reverse_rail_chains = batched_module._build_staging_rail_chains(
        staging["reverse_ledger"]
    )
    overlap_setback_intervals = (
        batched_module._pipe_overlap_setback_intervals(
            staging["groups"],
            staging["pipes"],
            staging["overlap_pairs"],
            float(arguments.radius),
        )
    )
    subtraction = build_global_subtraction_contract(
        preview_plan,
        staging["groups"],
        forward_rail_chains,
        staging["forward_ledger"],
        staging["overlap_pairs"],
        overlap_setback_intervals,
        float(arguments.radius),
        batched_module,
    )
    reverse_subtraction = build_global_subtraction_contract(
        preview_plan,
        staging["groups"],
        reverse_rail_chains,
        staging["reverse_ledger"],
        staging["overlap_pairs"],
        overlap_setback_intervals,
        float(arguments.radius),
        batched_module,
    )
    subtraction_order_invariant = batched_module._stable_fingerprint(
        {
            "claims": subtraction["regular_claims"],
            "setbacks": subtraction["setback_proofs"],
        }
    ) == batched_module._stable_fingerprint(
        {
            "claims": reverse_subtraction["regular_claims"],
            "setbacks": reverse_subtraction["setback_proofs"],
        }
    )
    target_entries = [
        entry
        for entry in staging["forward_ledger"]
        if entry["edge_id"] in target_edge_ids
    ]
    if {entry["edge_id"] for entry in target_entries} != set(target_edge_ids):
        raise RuntimeError("Fresh staging 未复现全部目标 residual Edge")
    normalization = graph_module.constrained_normalize_boundary_chain(
        target_entries,
        staging["forward_ledger"],
    )
    reverse_target_entries = [
        entry
        for entry in staging["reverse_ledger"]
        if entry["edge_id"] in target_edge_ids
    ]
    reverse_normalization = graph_module.constrained_normalize_boundary_chain(
        reverse_target_entries,
        staging["reverse_ledger"],
    )
    graph = graph_module.build_residual_ownership_graph(
        normalization["records"],
        staging["forward_ledger"],
        staging["complete_cutter_face_records"],
        regular_claims=subtraction["regular_claims"],
        setback_proofs=subtraction["setback_proofs"],
        allowed_source_patch_pairs=tuple(
            correspondence.owner_surface_pair
            for correspondence in preview_plan.strip_correspondences
        ),
    )
    reverse_graph = graph_module.build_residual_ownership_graph(
        reverse_normalization["records"],
        staging["reverse_ledger"],
        staging["reverse_complete_cutter_face_records"],
        regular_claims=reverse_subtraction["regular_claims"],
        setback_proofs=reverse_subtraction["setback_proofs"],
        allowed_source_patch_pairs=tuple(
            correspondence.owner_surface_pair
            for correspondence in preview_plan.strip_correspondences
        ),
    )
    normalization_order_invariant = normalization["lineage_fingerprint"] == (
        reverse_normalization["lineage_fingerprint"]
    )
    graph_order_invariant = graph["graph_fingerprint"] == reverse_graph[
        "graph_fingerprint"
    ]
    source_unchanged = (
        preview_utils.source_fingerprint(source_object) == source_fingerprint_before
    )
    report = {
        "contract": "HST_PHASE_C_RESIDUAL_OWNERSHIP_GRAPH_PROBE_V1",
        "status": "PROTOTYPE",
        "phase_c_gate": "STOP",
        "decision": (
            "GRAPH_DIRECT_WITNESS_CANDIDATE"
            if graph["all_subchains_resolved"]
            else "STOP_UNRESOLVED_DIRECT_WITNESS"
        ),
        "target_contract": {
            "ui_entry": "Feature Chamfer GN",
            "operator_chain": [
                "hst.feature_chamfer_gn(action=PREVIEW)",
                "hst.experimental_feature_chamfer_batched_finalize(debug_stage=PHASE_C_REGULAR_CORE)",
            ],
            "runtime_path": "PREVIEW then hidden Phase C Adapter then fresh independent staging graph probe",
            "user_visible_result": "read-only graph artifact; FINALIZE unchanged",
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
            "phase_c_adapter_result": adapter_result,
            "phase_c_failure_code": adapter_diagnostics.get("failure_code"),
            "phase_c_residual_edge_ids": list(adapter_residual_edge_ids),
            "source_fingerprint_before": source_fingerprint_before,
            "source_fingerprint_after": preview_utils.source_fingerprint(
                source_object
            ),
            "source_unchanged": source_unchanged,
        },
        "staging_evidence": {
            "boundary_universe_edge_count": len(staging["forward_ledger"]),
            "complete_cutter_face_node_count": len(
                staging["complete_cutter_face_records"]
            ),
            "color_batches": [list(batch) for batch in staging["color_batches"]],
            "forward_reverse_built_independently": True,
            "normalization_order_invariant": normalization_order_invariant,
            "graph_order_invariant": graph_order_invariant,
            "subtraction_order_invariant": subtraction_order_invariant,
            "producer_job_count": len(subtraction["producer_jobs"]),
            "regular_claim_edge_count": len(subtraction["regular_claims"]),
            "setback_proof_edge_count": sum(
                len(proof["edge_ids"])
                for proof in subtraction["setback_proofs"]
            ),
        },
        "normalization": normalization,
        "residual_ownership_graph": graph,
        "stop_go": {
            "synthetic_graph_contract_required_first": True,
            "normalization_contract_pass": normalization[
                "raw_edge_exactly_once"
            ],
            "all_normalized_subchains_have_unique_direct_witness": graph[
                "all_subchains_resolved"
            ],
            "source_unchanged": source_unchanged,
            "forward_reverse_graph_equal": (
                normalization_order_invariant
                and graph_order_invariant
                and subtraction_order_invariant
            ),
            "phase_c_go": False,
            "phase_d_or_e_authorized": False,
            "formal_finalize_modified": False,
        },
    }
    report_path = artifact_directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "[HST_PHASE_C_RESIDUAL_GRAPH_PROBE]"
        + json.dumps(
            {
                "decision": report["decision"],
                "all_subchains_resolved": graph["all_subchains_resolved"],
                "subchain_statuses": [
                    result["status"] for result in graph["subchains"]
                ],
                "report": str(report_path),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main(parse_arguments())
