# -*- coding: utf-8 -*-
"""Feature Chamfer Phase C 只读 ResidualOwnershipGraph 合同。"""

import bpy

import hashlib
import json
import math

from mathutils import Vector


GRAPH_CONTRACT = "HST_PHASE_C_PRE_BOOLEAN_BOUNDARY_PAIRING_V2"


# 对稳定 JSON payload 生成 SHA-256。
# payload: 可被 json.dumps 序列化的数据；返回十六进制摘要。
def _stable_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


# 提取一个 post-Boolean Boundary Edge 的唯一完整 pre-Boolean profile lineage。
# entry: staging Boundary ledger 条目；返回 Pipe/profile-side/opposite-side/segment identity，缺失或冲突时返回 None。
def _complete_lineage_identity(entry):
    identities = {
        (
            int(topology["pipe_id"]),
            entry.get("strand_id"),
            int(topology["profile_side_id"]),
            int(topology["opposite_profile_side_id"]),
            topology["longitudinal_segment_id"],
        )
        for topology in entry.get("cutter_face_topology", ())
        if topology.get("topology_status") == "PROVEN_C4_PIPE"
        and topology.get("profile_side_id") is not None
        and topology.get("opposite_profile_side_id") is not None
        and topology.get("longitudinal_segment_id")
    }
    if len(identities) != 1:
        return None
    identity = next(iter(identities))
    if (
        identity[0] != int(entry["pipe_id"])
        or identity[3] != (identity[2] + 2) % 4
    ):
        return None
    return identity


# 按 endpoint token 把 raw Boundary Edge 排成唯一 open chain。
# entries: 同一 Pipe/Patch/Rail 的 raw Boundary ledger 条目；返回有序条目、token 与坐标。
def _order_open_token_chain(entries):
    entries_by_id = {entry["edge_id"]: entry for entry in entries}
    edge_ids_by_token = {}
    coordinate_by_token = {}
    for entry in entries:
        if len(entry.get("endpoint_tokens", ())) != 2:
            raise ValueError("Raw Boundary Edge 必须有两个 endpoint token")
        for token, coordinate in zip(entry["endpoint_tokens"], entry["endpoints"]):
            edge_ids_by_token.setdefault(token, set()).add(entry["edge_id"])
            existing = coordinate_by_token.get(token)
            current = tuple(float(value) for value in coordinate)
            if existing is not None and existing != current:
                raise ValueError("同一 endpoint token 对应不同坐标")
            coordinate_by_token[token] = current
    endpoints = sorted(
        token for token, edge_ids in edge_ids_by_token.items() if len(edge_ids) == 1
    )
    if len(endpoints) != 2:
        raise ValueError("Residual raw Edge 不是唯一 open token chain")
    current_token = endpoints[0]
    remaining_edge_ids = set(entries_by_id)
    ordered_entries = []
    ordered_tokens = [current_token]
    while remaining_edge_ids:
        candidate_edge_ids = sorted(
            edge_ids_by_token[current_token] & remaining_edge_ids
        )
        if len(candidate_edge_ids) != 1:
            raise ValueError("Residual raw Edge token walk 存在歧义")
        edge_id = candidate_edge_ids[0]
        entry = entries_by_id[edge_id]
        ordered_entries.append(entry)
        remaining_edge_ids.remove(edge_id)
        next_tokens = [
            token for token in entry["endpoint_tokens"] if token != current_token
        ]
        if len(next_tokens) != 1:
            raise ValueError("Raw Boundary Edge endpoint token collapsed")
        current_token = next_tokens[0]
        ordered_tokens.append(current_token)
    return (
        tuple(ordered_entries),
        tuple(ordered_tokens),
        tuple(coordinate_by_token[token] for token in ordered_tokens),
    )


# 以严格 degree/token/provenance/共线门禁规范化 fragmented Boundary chain。
# entries/universe: 目标 raw chain 与完整 independent staging ledger；angle/distance: probe-only 上限；返回完整 lineage 合同。
def constrained_normalize_boundary_chain(
    entries,
    boundary_universe,
    angle_limit_degrees=0.5,
    distance_limit=1.0e-5,
):
    ordered_entries, ordered_tokens, ordered_coordinates = _order_open_token_chain(
        entries
    )
    entry_by_id = {entry["edge_id"]: entry for entry in ordered_entries}
    universe_by_token = {}
    for entry in boundary_universe:
        for token in entry.get("endpoint_tokens", ()):
            universe_by_token.setdefault(token, []).append(entry)
    angle_limit_radians = math.radians(float(angle_limit_degrees))
    evaluations = []
    eligible_tokens = set()
    for internal_index, token in enumerate(ordered_tokens[1:-1], start=1):
        previous_point = Vector(ordered_coordinates[internal_index - 1])
        point = Vector(ordered_coordinates[internal_index])
        following_point = Vector(ordered_coordinates[internal_index + 1])
        incoming = point - previous_point
        outgoing = following_point - point
        if incoming.length_squared <= 1.0e-20 or outgoing.length_squared <= 1.0e-20:
            angle = math.inf
        else:
            dot = max(
                -1.0,
                min(1.0, incoming.normalized().dot(outgoing.normalized())),
            )
            angle = math.acos(dot)
        chord = following_point - previous_point
        factor = (
            0.0
            if chord.length_squared <= 1.0e-20
            else (point - previous_point).dot(chord) / chord.length_squared
        )
        chord_distance = (
            point - (previous_point + chord * factor)
        ).length
        incident_entries = universe_by_token.get(token, ())
        target_incident_entries = [
            entry
            for entry in incident_entries
            if entry["edge_id"] in entry_by_id
        ]
        owner_signatures = {
            (
                tuple(entry.get("semantic_batch_key", ())),
                int(entry["pipe_id"]),
                entry.get("strand_id"),
                int(entry["source_patch_id"]),
                entry["rail_id"],
                _complete_lineage_identity(entry),
            )
            for entry in incident_entries
        }
        protected_port_tokens = {
            port_token
            for entry in incident_entries
            for port_token in entry.get("endpoint_port_tokens", ())
        }
        direct_topology_complete = bool(target_incident_entries) and all(
            _complete_lineage_identity(entry) is not None
            and entry.get("groove_face_signatures")
            and entry.get("adjacent_face_signatures")
            for entry in target_incident_entries
        )
        eligible = (
            len(incident_entries) == 2
            and len(target_incident_entries) == 2
            and len(owner_signatures) == 1
            and not protected_port_tokens
            and direct_topology_complete
            and angle <= angle_limit_radians
            and chord_distance <= float(distance_limit)
        )
        if eligible:
            eligible_tokens.add(token)
        evaluations.append(
            {
                "token": token,
                "degree": len(incident_entries),
                "incident_edge_ids": sorted(
                    entry["edge_id"] for entry in incident_entries
                ),
                "angle_degrees": math.degrees(angle),
                "chord_distance": chord_distance,
                "direct_topology_complete": direct_topology_complete,
                "protected_port_tokens": sorted(protected_port_tokens),
                "eligible": eligible,
            }
        )
    segments = [
        {
            "raw_edge_ids": [entry["edge_id"]],
            "start_token": ordered_tokens[index],
            "end_token": ordered_tokens[index + 1],
            "start_coordinate": ordered_coordinates[index],
            "end_coordinate": ordered_coordinates[index + 1],
            "dissolved_internal_tokens": [],
        }
        for index, entry in enumerate(ordered_entries)
    ]
    normalized_segments = []
    current = dict(segments[0])
    for segment in segments[1:]:
        if current["end_token"] in eligible_tokens:
            current["raw_edge_ids"] = [
                *current["raw_edge_ids"],
                *segment["raw_edge_ids"],
            ]
            current["dissolved_internal_tokens"] = [
                *current["dissolved_internal_tokens"],
                current["end_token"],
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
        source_entries = [
            entry_by_id[edge_id] for edge_id in segment["raw_edge_ids"]
        ]
        owner_signatures = {
            (
                tuple(entry.get("semantic_batch_key", ())),
                int(entry["pipe_id"]),
                entry.get("strand_id"),
                int(entry["source_patch_id"]),
                entry["rail_id"],
                _complete_lineage_identity(entry),
            )
            for entry in source_entries
        }
        if len(owner_signatures) != 1 or next(iter(owner_signatures))[-1] is None:
            raise ValueError("Normalization 试图合并不同完整 profile lineage")
        lineage_identity = next(iter(owner_signatures))[-1]
        normalized_edge_id = "normalized:" + _stable_fingerprint(
            {
                "raw_edge_ids": segment["raw_edge_ids"],
                "endpoint_tokens": [
                    segment["start_token"],
                    segment["end_token"],
                ],
            }
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
            "semantic_batch_key": list(
                source_entries[0].get("semantic_batch_key", ())
            ),
            "pipe_id": int(source_entries[0]["pipe_id"]),
            "strand_id": source_entries[0].get("strand_id"),
            "source_patch_id": int(source_entries[0]["source_patch_id"]),
            "rail_id": source_entries[0]["rail_id"],
            "profile_side_id": lineage_identity[2],
            "opposite_profile_side_id": lineage_identity[3],
            "longitudinal_segment_ids": sorted(
                {
                    identity[4]
                    for entry in source_entries
                    for identity in (_complete_lineage_identity(entry),)
                }
            ),
            "endpoint_port_tokens": sorted(
                {
                    token
                    for entry in source_entries
                    for token in entry.get("endpoint_port_tokens", ())
                }
            ),
            "adjacent_face_signatures": sorted(
                {
                    signature
                    for entry in source_entries
                    for signature in entry.get("adjacent_face_signatures", ())
                }
            ),
            "groove_face_signatures": sorted(
                {
                    signature
                    for entry in source_entries
                    for signature in entry.get("groove_face_signatures", ())
                }
            ),
            "cutter_face_topology": sorted(
                {
                    _stable_fingerprint(topology): topology
                    for entry in source_entries
                    for topology in entry.get("cutter_face_topology", ())
                }.values(),
                key=_stable_fingerprint,
            ),
        }
        records.append(record)
        for raw_edge_id in segment["raw_edge_ids"]:
            if raw_edge_id in raw_edge_to_normalized_edge:
                raise ValueError("Raw Edge 被映射到多个 normalized Edge")
            raw_edge_to_normalized_edge[raw_edge_id] = normalized_edge_id
    raw_edge_ids = [entry["edge_id"] for entry in ordered_entries]
    exactly_once = (
        sorted(raw_edge_to_normalized_edge) == sorted(raw_edge_ids)
        and len(raw_edge_to_normalized_edge) == len(raw_edge_ids)
    )
    return {
        "raw_edge_ids": raw_edge_ids,
        "raw_endpoint_tokens": list(ordered_tokens),
        "raw_coordinates": [list(coordinate) for coordinate in ordered_coordinates],
        "candidate_internal_vertices": evaluations,
        "eligible_internal_tokens": sorted(eligible_tokens),
        "records": records,
        "raw_edge_to_normalized_edge": raw_edge_to_normalized_edge,
        "raw_edge_exactly_once": exactly_once,
        "lineage_fingerprint": _stable_fingerprint(
            raw_edge_to_normalized_edge
        ),
        "limits": {
            "angle_degrees": float(angle_limit_degrees),
            "chord_distance": float(distance_limit),
        },
    }


# 构建只读 pre-Boolean profile lineage graph；每条 normalized Edge 只接受权威 Patch pair 上相邻 Cutter Face 的 direct Edge chain。
# normalized/universe/faces/claims/setbacks/ports/pairs: lineage 输入合同；pairs 使用 strand_id+Patch pair；返回 Face→Edge incidence artifact。
def build_residual_ownership_graph(
    normalized_records,
    boundary_universe,
    complete_cutter_face_records,
    regular_claims=(),
    setback_proofs=(),
    authoritative_plan_port_incidences=(),
    allowed_source_patch_pairs=(),
):
    raw_edge_ids = [
        raw_edge_id
        for record in normalized_records
        for raw_edge_id in record.get("raw_edge_ids", ())
    ]
    if len(raw_edge_ids) != len(set(raw_edge_ids)):
        raise ValueError("Residual graph raw→normalized lineage 不是 exactly-once")
    boundary_by_edge_id = {
        entry["edge_id"]: entry for entry in boundary_universe
    }
    if len(boundary_by_edge_id) != len(boundary_universe):
        raise ValueError("Boundary universe 含重复 Edge identity")
    regular_claim_by_edge_id = {}
    for claim in regular_claims:
        edge_id = claim["edge_id"]
        if edge_id in regular_claim_by_edge_id:
            raise ValueError("RegularBridgeJob claims 不是全局互斥")
        regular_claim_by_edge_id[edge_id] = dict(claim)
    setback_edge_ids = set()
    serialized_setback_proofs = []
    for proof in setback_proofs:
        edge_ids = tuple(
            edge_id
            for edge_id in proof.get(
                "edge_ids",
                (proof.get("edge_id"),),
            )
            if edge_id is not None
        )
        if setback_edge_ids & set(edge_ids):
            raise ValueError("Frozen setback proofs 重复声明 Boundary Edge")
        setback_edge_ids.update(edge_ids)
        serialized_setback_proofs.append({**proof, "edge_ids": list(edge_ids)})
    claim_edge_ids = set(regular_claim_by_edge_id)
    if claim_edge_ids & setback_edge_ids:
        raise ValueError("Regular claims 与 setback proofs 相交")
    outside_universe = (claim_edge_ids | setback_edge_ids) - set(boundary_by_edge_id)
    if outside_universe:
        raise ValueError("Graph subtraction proof 超出 Boundary universe")
    if set(raw_edge_ids) & (claim_edge_ids | setback_edge_ids):
        raise ValueError("Residual normalized lineage 已被 claim/setback 消费")
    face_records_by_signature = {}
    for record in complete_cutter_face_records:
        if record.get("topology_status") != "PROVEN_C4_PIPE":
            continue
        face_signature = record.get("face_signature")
        if not face_signature:
            continue
        existing = face_records_by_signature.get(face_signature)
        if existing is not None and existing != record:
            raise ValueError("Cutter Face signature 对应冲突 topology")
        face_records_by_signature[face_signature] = dict(record)
    port_incidences_by_token = {}
    for incidence in authoritative_plan_port_incidences:
        if not incidence.get("authoritative", False):
            continue
        port_incidences_by_token.setdefault(
            incidence["endpoint_token"], []
        ).append(dict(incidence))
    normalized_allowed_patch_pair_counts = {}
    for pair_record in allowed_source_patch_pairs:
        if isinstance(pair_record, dict):
            pair = tuple(pair_record.get("patch_pair", ()))
            pair_strand_id = pair_record.get("strand_id")
        else:
            pair = tuple(pair_record)
            pair_strand_id = None
        if len(pair) != 2:
            continue
        normalized_pair = frozenset(int(patch_id) for patch_id in pair)
        pair_key = (pair_strand_id, normalized_pair)
        normalized_allowed_patch_pair_counts[pair_key] = (
            normalized_allowed_patch_pair_counts.get(pair_key, 0) + 1
        )
    normalized_edge_results = []
    for record in sorted(
        normalized_records,
        key=lambda item: item["normalized_edge_id"],
    ):
        pipe_id = int(record["pipe_id"])
        strand_id = record.get("strand_id")
        source_patch_id = int(record["source_patch_id"])
        matching_patch_pairs = [
            pair
            for (pair_strand_id, pair), count
            in normalized_allowed_patch_pair_counts.items()
            if count == 1
            and pair_strand_id in {None, strand_id}
            and source_patch_id in pair
        ]
        duplicate_matching_patch_pair = any(
            count > 1
            and pair_strand_id in {None, strand_id}
            and source_patch_id in pair
            for (pair_strand_id, pair), count
            in normalized_allowed_patch_pair_counts.items()
        )
        if len(matching_patch_pairs) == 1:
            allowed_patch_pair = matching_patch_pairs[0]
        else:
            allowed_patch_pair = None
        raw_edge_id_set = set(record.get("raw_edge_ids", ()))
        longitudinal_segment_ids = tuple(record["longitudinal_segment_ids"])
        profile_side_id = int(record["profile_side_id"])
        opposite_profile_side_id = int(record["opposite_profile_side_id"])
        direct_candidates = []
        patch_pair_identity_complete = (
            allowed_patch_pair is not None
            and not duplicate_matching_patch_pair
        )
        residual_topologies = tuple(
            topology
            for topology in record.get("cutter_face_topology", ())
            if topology.get("topology_status") == "PROVEN_C4_PIPE"
            and topology.get("longitudinal_segment_id")
            in longitudinal_segment_ids
        )
        direct_candidates_by_edge_id = {}
        for residual_topology in residual_topologies:
            expected_neighbor_signatures = set(
                residual_topology.get("profile_neighbor_face_signatures", ())
            )
            for candidate in boundary_universe:
                edge_id = candidate["edge_id"]
                if (
                    not patch_pair_identity_complete
                    or edge_id in raw_edge_id_set
                    or edge_id in setback_edge_ids
                    or int(candidate["pipe_id"]) != pipe_id
                    or candidate.get("strand_id") != strand_id
                    or int(candidate["source_patch_id"]) == source_patch_id
                    or (
                        allowed_patch_pair is not None
                        and int(candidate["source_patch_id"])
                        not in allowed_patch_pair
                    )
                ):
                    continue
                claim = regular_claim_by_edge_id.get(edge_id)
                candidate_topologies = [
                    topology
                    for topology in candidate.get(
                        "cutter_face_topology",
                        (),
                    )
                    if topology.get("topology_status")
                    == "PROVEN_C4_PIPE"
                    and topology.get("longitudinal_segment_id")
                    == residual_topology["longitudinal_segment_id"]
                    and topology.get("face_signature")
                    in expected_neighbor_signatures
                ]
                if len(candidate_topologies) != 1:
                    continue
                candidate_topology = candidate_topologies[0]
                candidate_face_signature = candidate_topology.get(
                    "face_signature"
                )
                pre_boolean_face_record = face_records_by_signature.get(
                    candidate_face_signature
                )
                face_identity_matches = (
                    candidate_topology is not None
                    and pre_boolean_face_record == candidate_topology
                    and candidate_face_signature
                    in expected_neighbor_signatures
                )
                existing_candidate = direct_candidates_by_edge_id.get(edge_id)
                if (
                    existing_candidate is not None
                    and existing_candidate["source_face_signature"]
                    != residual_topology.get("face_signature")
                ):
                    raise ValueError(
                        "同一 direct consumer Edge 对应多个 residual Cutter Face"
                    )
                direct_candidates_by_edge_id[edge_id] = {
                    "boundary_edge_id": edge_id,
                    "boundary_source_patch_id": int(candidate["source_patch_id"]),
                    "claim_state": (
                        claim.get("claim_state") if claim is not None else None
                    ),
                    "face_consumer_id": (
                        claim.get("face_consumer_id") if claim is not None else None
                    ),
                    "direct_lineage_identity": list(
                        _complete_lineage_identity(candidate) or ()
                    ),
                    "source_face_signature": residual_topology.get(
                        "face_signature"
                    ),
                    "candidate_face_signature": candidate_face_signature,
                    "pre_boolean_face_identity_matches": face_identity_matches,
                }
        direct_candidates = list(direct_candidates_by_edge_id.values())
        direct_candidates.sort(key=lambda item: item["boundary_edge_id"])
        endpoint_port_incidences = [
            incidence
            for endpoint_token in record["endpoint_tokens"]
            for incidence in port_incidences_by_token.get(endpoint_token, ())
            if int(incidence.get("pipe_id", pipe_id)) == pipe_id
            and incidence.get("lineage_source") == "CHAMFER_PLAN"
        ]
        unique_port_ids = sorted(
            {incidence["port_id"] for incidence in endpoint_port_incidences}
        )
        pre_boolean_face_identity_complete = bool(direct_candidates) and all(
            candidate["pre_boolean_face_identity_matches"]
            for candidate in direct_candidates
        )
        expected_consumer_face_signatures = {
            topology.get("face_signature")
            for topology in residual_topologies
            if topology.get("face_signature")
        }
        direct_candidate_count_by_source_face = {
            face_signature: sum(
                candidate["source_face_signature"] == face_signature
                for candidate in direct_candidates
            )
            for face_signature in expected_consumer_face_signatures
        }
        complete_direct_chain = (
            bool(expected_consumer_face_signatures)
            and all(
                count == 1
                for count in direct_candidate_count_by_source_face.values()
            )
        )
        if (
            direct_candidates
            and pre_boolean_face_identity_complete
            and complete_direct_chain
        ):
            status = "UNIQUE_DIRECT_OPPOSITE_CONSUMER"
            resolved_consumer_id = "BOUNDARY_CHAIN:" + _stable_fingerprint(
                [
                    candidate["boundary_edge_id"]
                    for candidate in direct_candidates
                ]
            )
            rejection_reason = None
        elif len(unique_port_ids) == 1:
            status = "UNIQUE_PLAN_PORT_INCIDENCE"
            resolved_consumer_id = f"PLAN_PORT:{unique_port_ids[0]}"
            rejection_reason = None
        else:
            status = "UNRESOLVED"
            resolved_consumer_id = None
            if direct_candidates and not pre_boolean_face_identity_complete:
                rejection_reason = "MISSING_PRE_BOOLEAN_OPPOSITE_FACE_IDENTITY"
            elif duplicate_matching_patch_pair:
                rejection_reason = "DUPLICATE_AUTHORITATIVE_PLAN_PATCH_PAIR"
            elif not patch_pair_identity_complete:
                rejection_reason = "MISSING_AUTHORITATIVE_PLAN_PATCH_PAIR"
            elif direct_candidates and not complete_direct_chain:
                rejection_reason = (
                    "DUPLICATE_DIRECT_OPPOSITE_CONSUMER"
                    if any(
                        count > 1
                        for count in direct_candidate_count_by_source_face.values()
                    )
                    else "INCOMPLETE_DIRECT_OPPOSITE_CONSUMER_CHAIN"
                )
            elif len(unique_port_ids) > 1:
                rejection_reason = "AMBIGUOUS_PLAN_PORT_INCIDENCE"
            else:
                rejection_reason = "MISSING_DIRECT_OPPOSITE_CONSUMER"
        normalized_edge_results.append(
            {
                "status": status,
                "resolved_consumer_id": resolved_consumer_id,
                "rejection_reason": rejection_reason,
                "normalized_edge_id": record["normalized_edge_id"],
                "raw_edge_ids": sorted(raw_edge_id_set),
                "endpoint_tokens": list(record["endpoint_tokens"]),
                "pipe_id": pipe_id,
                "strand_id": strand_id,
                "source_patch_id": source_patch_id,
                "allowed_source_patch_pair": (
                    sorted(allowed_patch_pair)
                    if allowed_patch_pair is not None
                    else None
                ),
                "profile_side_id": profile_side_id,
                "opposite_profile_side_id": opposite_profile_side_id,
                "longitudinal_segment_ids": list(longitudinal_segment_ids),
                "direct_opposite_lineage_identities": [
                    candidate["direct_lineage_identity"]
                    for candidate in direct_candidates
                ],
                "direct_face_edge_incidence": direct_candidates,
                "direct_candidate_count_by_source_face": (
                    direct_candidate_count_by_source_face
                ),
                "pre_boolean_face_identity_complete": (
                    pre_boolean_face_identity_complete
                ),
                "authoritative_plan_port_incidences": endpoint_port_incidences,
            }
        )
    all_normalized_edges_resolved = bool(normalized_edge_results) and all(
        result["status"] == "UNIQUE_DIRECT_OPPOSITE_CONSUMER"
        for result in normalized_edge_results
    )
    candidate_edge_to_normalized_edges = {}
    for result in normalized_edge_results:
        for candidate in result["direct_face_edge_incidence"]:
            candidate_edge_to_normalized_edges.setdefault(
                candidate["boundary_edge_id"],
                [],
            ).append(result["normalized_edge_id"])
    overlapping_candidate_edges = {
        edge_id: sorted(normalized_edge_ids)
        for edge_id, normalized_edge_ids
        in candidate_edge_to_normalized_edges.items()
        if len(normalized_edge_ids) > 1
    }
    if overlapping_candidate_edges:
        all_normalized_edges_resolved = False
        for result in normalized_edge_results:
            if any(
                candidate["boundary_edge_id"] in overlapping_candidate_edges
                for candidate in result["direct_face_edge_incidence"]
            ):
                result["status"] = "UNRESOLVED"
                result["resolved_consumer_id"] = None
                result["rejection_reason"] = (
                    "OVERLAPPING_DIRECT_OPPOSITE_CONSUMER_CHAIN"
                )
    return {
        "contract": GRAPH_CONTRACT,
        "status": "PROTOTYPE",
        "graph_input": {
            "normalized_edge_count": len(normalized_records),
            "raw_edge_count": len(raw_edge_ids),
            "boundary_universe_edge_count": len(boundary_universe),
            "complete_cutter_face_node_count": len(face_records_by_signature),
            "regular_claim_edge_count": len(claim_edge_ids),
            "setback_edge_count": len(setback_edge_ids),
        },
        "subtraction": {
            "regular_claims": [
                regular_claim_by_edge_id[edge_id]
                for edge_id in sorted(regular_claim_by_edge_id)
            ],
            "setback_proofs": serialized_setback_proofs,
            "claim_setback_disjoint": True,
            "subtraction_outside_universe": [],
        },
        "normalized_edges": normalized_edge_results,
        "subchains": normalized_edge_results,
        "all_normalized_edges_resolved": all_normalized_edges_resolved,
        "all_subchains_resolved": all_normalized_edges_resolved,
        "candidate_edge_exactly_once": not overlapping_candidate_edges,
        "overlapping_candidate_edges": overlapping_candidate_edges,
        "raw_edge_exactly_once": len(raw_edge_ids) == len(set(raw_edge_ids)),
        "nearest_or_coordinate_matching_used": False,
        "consumer_resolution_mode": (
            "PLAN_PATCH_PAIR_ADJACENT_CUTTER_FACE_EDGE_INCIDENCE_ONLY"
        ),
        "lineage_fingerprint": _stable_fingerprint(
            {
                record["normalized_edge_id"]: sorted(record["raw_edge_ids"])
                for record in normalized_records
            }
        ),
        "graph_fingerprint": _stable_fingerprint(normalized_edge_results),
    }
