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
        freeze_complete_profile_lineage=True,
    )
    reverse = batched_module._run_independent_batch_cut_probe(
        source_object,
        pipes,
        color_batches,
        probe_collection,
        preview_plan.plan_id,
        "REVERSE",
        include_complete_cutter_face_records=True,
        freeze_complete_profile_lineage=True,
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


# 统计 normalized residual 的 C4 几何 opposite Face 在 post-Boolean Boundary universe 中的真实 Edge incidence。
# normalization/boundary_ledger/regular_claims: normalization 合同、完整 Boundary universe 与 producer claims；返回不参与决策的诊断 census。
def build_direct_opposite_incidence_census(
    normalization,
    boundary_ledger,
    regular_claims,
):
    claims_by_edge_id = {
        claim["edge_id"]: claim for claim in regular_claims
    }
    census = []
    for normalized_record in normalization["records"]:
        pipe_id = int(normalized_record["pipe_id"])
        strand_id = normalized_record.get("strand_id")
        source_patch_id = int(normalized_record["source_patch_id"])
        expected_opposite_face_signatures = sorted({
            topology["profile_opposite_face_signature"]
            for topology in normalized_record.get("cutter_face_topology", ())
            if topology.get("topology_status") == "PROVEN_C4_PIPE"
            and topology.get("profile_opposite_face_signature")
        })
        expected_opposite_side_ids = sorted({
            int(topology["opposite_profile_side_id"])
            for topology in normalized_record.get("cutter_face_topology", ())
            if topology.get("topology_status") == "PROVEN_C4_PIPE"
            and topology.get("opposite_profile_side_id") is not None
        })
        expected_segment_ids = sorted({
            topology["longitudinal_segment_id"]
            for topology in normalized_record.get("cutter_face_topology", ())
            if topology.get("topology_status") == "PROVEN_C4_PIPE"
            and topology.get("longitudinal_segment_id")
        })
        exact_face_incidences = []
        opposite_side_incidences = []
        paired_boundary_neighbor_incidences = []
        same_pipe_profile_incidence_summary = {}
        for boundary_entry in boundary_ledger:
            if (
                int(boundary_entry["pipe_id"]) != pipe_id
                or boundary_entry.get("strand_id") != strand_id
            ):
                continue
            for topology in boundary_entry.get("cutter_face_topology", ()):
                if topology.get("topology_status") != "PROVEN_C4_PIPE":
                    continue
                summary_key = (
                    int(boundary_entry["source_patch_id"]),
                    int(topology["profile_side_id"]),
                    topology["longitudinal_segment_id"],
                )
                summary = same_pipe_profile_incidence_summary.setdefault(
                    summary_key,
                    {
                        "source_patch_id": summary_key[0],
                        "profile_side_id": summary_key[1],
                        "longitudinal_segment_id": summary_key[2],
                        "boundary_edge_ids": set(),
                        "face_signatures": set(),
                    },
                )
                summary["boundary_edge_ids"].add(boundary_entry["edge_id"])
                if topology.get("face_signature"):
                    summary["face_signatures"].add(topology["face_signature"])
                incidence = {
                    "boundary_edge_id": boundary_entry["edge_id"],
                    "source_patch_id": int(boundary_entry["source_patch_id"]),
                    "same_source_patch": (
                        int(boundary_entry["source_patch_id"]) == source_patch_id
                    ),
                    "face_signature": topology.get("face_signature"),
                    "profile_side_id": topology.get("profile_side_id"),
                    "opposite_profile_side_id": topology.get(
                        "opposite_profile_side_id"
                    ),
                    "longitudinal_segment_id": topology.get(
                        "longitudinal_segment_id"
                    ),
                    "claim": claims_by_edge_id.get(boundary_entry["edge_id"]),
                }
                if topology.get("face_signature") in set(
                    expected_opposite_face_signatures
                ):
                    exact_face_incidences.append(incidence)
                if (
                    topology.get("profile_side_id")
                    in expected_opposite_side_ids
                    and topology.get("longitudinal_segment_id")
                    in expected_segment_ids
                ):
                    opposite_side_incidences.append(incidence)
                if topology.get("face_signature") in {
                    signature
                    for residual_topology in normalized_record.get(
                        "cutter_face_topology",
                        (),
                    )
                    for signature in residual_topology.get(
                        "profile_neighbor_face_signatures",
                        (),
                    )
                }:
                    paired_boundary_neighbor_incidences.append(incidence)
        census.append(
            {
                "normalized_edge_id": normalized_record["normalized_edge_id"],
                "source_patch_id": source_patch_id,
                "expected_opposite_face_signatures": (
                    expected_opposite_face_signatures
                ),
                "expected_opposite_side_ids": expected_opposite_side_ids,
                "expected_segment_ids": expected_segment_ids,
                "exact_face_incidences": sorted(
                    exact_face_incidences,
                    key=lambda item: (
                        item["boundary_edge_id"],
                        str(item["face_signature"]),
                    ),
                ),
                "opposite_side_incidences": sorted(
                    opposite_side_incidences,
                    key=lambda item: (
                        item["boundary_edge_id"],
                        str(item["face_signature"]),
                    ),
                ),
                "paired_boundary_neighbor_incidences": sorted(
                    paired_boundary_neighbor_incidences,
                    key=lambda item: (
                        item["boundary_edge_id"],
                        str(item["face_signature"]),
                    ),
                ),
                "same_pipe_profile_incidence_summary": sorted(
                    (
                        {
                            **summary,
                            "boundary_edge_ids": sorted(
                                summary["boundary_edge_ids"]
                            ),
                            "face_signatures": sorted(
                                summary["face_signatures"]
                            ),
                        }
                        for summary in same_pipe_profile_incidence_summary.values()
                    ),
                    key=lambda item: (
                        item["source_patch_id"],
                        item["profile_side_id"],
                        item["longitudinal_segment_id"],
                    ),
                ),
            }
        )
    return census


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
        print(
            "[HST_PHASE_C_RESIDUAL_IDS_CHANGED]"
            + json.dumps(
                {
                    "expected": sorted(target_edge_ids),
                    "actual": sorted(adapter_residual_edge_ids),
                },
                separators=(",", ":"),
            )
        )
        target_identity_changed = True
    else:
        target_identity_changed = False
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
    fresh_target_edge_ids = (
        adapter_residual_edge_ids if target_identity_changed else target_edge_ids
    )
    target_entries = [
        entry
        for entry in staging["forward_ledger"]
        if entry["edge_id"] in fresh_target_edge_ids
    ]
    if {entry["edge_id"] for entry in target_entries} != set(fresh_target_edge_ids):
        raise RuntimeError("Fresh staging 未复现全部目标 residual Edge")
    normalization = graph_module.constrained_normalize_boundary_chain(
        target_entries,
        staging["forward_ledger"],
    )
    reverse_target_entries = [
        entry
        for entry in staging["reverse_ledger"]
        if entry["edge_id"] in fresh_target_edge_ids
    ]
    reverse_normalization = graph_module.constrained_normalize_boundary_chain(
        reverse_target_entries,
        staging["reverse_ledger"],
    )
    direct_opposite_incidence_census = build_direct_opposite_incidence_census(
        normalization,
        staging["forward_ledger"],
        subtraction["regular_claims"],
    )
    reverse_direct_opposite_incidence_census = (
        build_direct_opposite_incidence_census(
            reverse_normalization,
            staging["reverse_ledger"],
            reverse_subtraction["regular_claims"],
        )
    )
    graph = graph_module.build_residual_ownership_graph(
        normalization["records"],
        staging["forward_ledger"],
        staging["complete_cutter_face_records"],
        regular_claims=subtraction["regular_claims"],
        setback_proofs=subtraction["setback_proofs"],
        allowed_source_patch_pairs=tuple(
            {
                "strand_id": correspondence.owner_strand_id,
                "patch_pair": list(correspondence.owner_surface_pair),
            }
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
            {
                "strand_id": correspondence.owner_strand_id,
                "patch_pair": list(correspondence.owner_surface_pair),
            }
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
        "contract": "HST_PHASE_C_PRE_BOOLEAN_PROFILE_LINEAGE_PROBE_V2",
        "status": "PROTOTYPE",
        "phase_c_gate": "STOP",
        "decision": (
            "STOP_TARGET_RESIDUAL_IDENTITY_CHANGED"
            if target_identity_changed
            else "MAXIMAL_CHAIN_DIRECT_WITNESS_PROBE_GO"
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
            "expected_phase_c_residual_edge_ids": list(target_edge_ids),
            "target_residual_identity_changed": target_identity_changed,
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
        "direct_opposite_incidence_census": (
            direct_opposite_incidence_census
        ),
        "residual_ownership_graph": graph,
        "stop_go": {
            "synthetic_graph_contract_required_first": True,
            "normalization_contract_pass": normalization[
                "raw_edge_exactly_once"
            ],
            "all_maximal_source_chains_have_unique_direct_witness": graph[
                "all_subchains_resolved"
            ],
            "expected_two_normalized_edges": (
                len(normalization["records"]) == 2
            ),
            "target_residual_identity_unchanged": not target_identity_changed,
            "source_unchanged": source_unchanged,
            "forward_reverse_graph_equal": (
                normalization_order_invariant
                and graph_order_invariant
                and subtraction_order_invariant
                and direct_opposite_incidence_census
                == reverse_direct_opposite_incidence_census
            ),
            "probe_go": (
                graph["all_subchains_resolved"]
                and len(normalization["records"]) == 2
                and not target_identity_changed
                and source_unchanged
                and normalization_order_invariant
                and graph_order_invariant
                and subtraction_order_invariant
                and direct_opposite_incidence_census
                == reverse_direct_opposite_incidence_census
            ),
            "phase_c_go": False,
            "phase_d_or_e_authorized": False,
            "formal_finalize_modified": False,
            "phase_c_adapter_runtime_modified": False,
        },
    }
    report_path = artifact_directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    blend_path = artifact_directory / "phase_c_pre_boolean_profile_lineage.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    report["artifacts"] = {
        "report_path": str(report_path),
        "blend_path": str(blend_path),
        "blend_sha256": file_sha256(blend_path),
    }
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
