# -*- coding: utf-8 -*-
"""Feature Chamfer Phase C 只读 ResidualOwnershipGraph 合同。"""

import bpy

import hashlib
import json
import math

from mathutils import Vector


GRAPH_CONTRACT = "HST_PHASE_C_PRE_BOOLEAN_MAXIMAL_CHAIN_PAIRING_V3"


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


# 只用稳定 endpoint token 验证并排序一条唯一 open chain。
# entries/id_key/token_key: Edge-like 记录及其 identity/token 字段；返回连通性、排序后的 Edge identity 与 token，不读取坐标。
def _validate_open_identity_chain(entries, id_key, token_key):
    entries_by_id = {}
    edge_ids_by_token = {}
    for entry in entries:
        edge_id = entry.get(id_key)
        endpoint_tokens = tuple(entry.get(token_key, ()))
        if edge_id is None or edge_id in entries_by_id:
            return {
                "valid": False,
                "reason": "DUPLICATE_EDGE_IDENTITY",
                "ordered_edge_ids": [],
                "ordered_tokens": [],
            }
        if len(endpoint_tokens) != 2:
            return {
                "valid": False,
                "reason": "INVALID_ENDPOINT_TOKEN_COUNT",
                "ordered_edge_ids": [],
                "ordered_tokens": [],
            }
        if endpoint_tokens[0] == endpoint_tokens[1]:
            return {
                "valid": False,
                "reason": "COLLAPSED_ENDPOINT_TOKENS",
                "ordered_edge_ids": [],
                "ordered_tokens": [],
            }
        entries_by_id[edge_id] = entry
        for token in endpoint_tokens:
            edge_ids_by_token.setdefault(token, set()).add(edge_id)
    if not entries_by_id:
        return {
            "valid": False,
            "reason": "MISSING_EDGES",
            "ordered_edge_ids": [],
            "ordered_tokens": [],
        }
    if any(len(edge_ids) > 2 for edge_ids in edge_ids_by_token.values()):
        return {
            "valid": False,
            "reason": "BRANCHED_TOKEN_GRAPH",
            "ordered_edge_ids": [],
            "ordered_tokens": [],
        }
    endpoints = sorted(
        token for token, edge_ids in edge_ids_by_token.items() if len(edge_ids) == 1
    )
    if len(endpoints) != 2:
        return {
            "valid": False,
            "reason": "NOT_UNIQUE_OPEN_CHAIN",
            "ordered_edge_ids": [],
            "ordered_tokens": [],
        }
    current_token = endpoints[0]
    remaining_edge_ids = set(entries_by_id)
    ordered_edge_ids = []
    ordered_tokens = [current_token]
    while remaining_edge_ids:
        candidate_edge_ids = sorted(
            edge_ids_by_token[current_token] & remaining_edge_ids
        )
        if len(candidate_edge_ids) != 1:
            return {
                "valid": False,
                "reason": "DISCONNECTED_OR_AMBIGUOUS_TOKEN_WALK",
                "ordered_edge_ids": ordered_edge_ids,
                "ordered_tokens": ordered_tokens,
            }
        edge_id = candidate_edge_ids[0]
        endpoint_tokens = tuple(entries_by_id[edge_id][token_key])
        next_tokens = [token for token in endpoint_tokens if token != current_token]
        if len(next_tokens) != 1:
            return {
                "valid": False,
                "reason": "COLLAPSED_ENDPOINT_TOKENS",
                "ordered_edge_ids": ordered_edge_ids,
                "ordered_tokens": ordered_tokens,
            }
        ordered_edge_ids.append(edge_id)
        remaining_edge_ids.remove(edge_id)
        current_token = next_tokens[0]
        ordered_tokens.append(current_token)
    return {
        "valid": True,
        "reason": None,
        "ordered_edge_ids": ordered_edge_ids,
        "ordered_tokens": ordered_tokens,
    }


# 按完整 source lineage key 与共享 endpoint token 划分 maximal source components。
# normalized_results: 带 direct incidence 的 normalized Edge 诊断；返回确定性 component 列表，不跨 Patch/Rail/profile owner 合并。
def _build_maximal_source_components(normalized_results):
    results_by_id = {
        result["normalized_edge_id"]: result for result in normalized_results
    }
    if len(results_by_id) != len(normalized_results):
        raise ValueError("Normalized Edge identity 重复")
    results_by_lineage = {}
    for result in normalized_results:
        lineage_key = (
            tuple(result.get("semantic_batch_key", ())),
            int(result["pipe_id"]),
            result.get("strand_id"),
            int(result["source_patch_id"]),
            result.get("rail_id"),
            int(result["profile_side_id"]),
            int(result["opposite_profile_side_id"]),
            tuple(sorted(result.get("longitudinal_segment_ids", ()))),
        )
        results_by_lineage.setdefault(lineage_key, []).append(result)
    components = []
    for lineage_key, lineage_results in sorted(
        results_by_lineage.items(),
        key=lambda item: _stable_fingerprint(item[0]),
    ):
        result_ids_by_token = {}
        protected_port_tokens = {
            token
            for result in lineage_results
            for token in result.get("endpoint_port_tokens", ())
        }
        for result in lineage_results:
            for token in result.get("endpoint_tokens", ()):
                result_ids_by_token.setdefault(token, set()).add(
                    result["normalized_edge_id"]
                )
        remaining_result_ids = {
            result["normalized_edge_id"] for result in lineage_results
        }
        while remaining_result_ids:
            seed_result_id = min(remaining_result_ids)
            component_result_ids = set()
            pending_result_ids = [seed_result_id]
            while pending_result_ids:
                result_id = pending_result_ids.pop()
                if result_id in component_result_ids:
                    continue
                component_result_ids.add(result_id)
                result = results_by_id[result_id]
                for token in result.get("endpoint_tokens", ()):
                    if token in protected_port_tokens:
                        continue
                    pending_result_ids.extend(
                        sorted(result_ids_by_token.get(token, ()))
                    )
            remaining_result_ids -= component_result_ids
            components.append(
                {
                    "lineage_key": lineage_key,
                    "results": [
                        results_by_id[result_id]
                        for result_id in sorted(component_result_ids)
                    ],
                }
            )
    return components


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


# 构建只读 pre-Boolean profile lineage graph；连续 normalized fragments 合成 maximal source chain 后整体接受 direct candidate chain。
# normalized/universe/faces/claims/setbacks/ports/pairs: lineage 输入合同；pairs 使用 strand_id+Patch pair；返回 Face→Edge/token connectivity artifact。
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
    if set(raw_edge_ids) - set(boundary_by_edge_id):
        raise ValueError("Residual raw→normalized lineage 超出 Boundary universe")
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
        if not isinstance(pair_record, dict):
            raise ValueError(
                "Authoritative StripCorrespondence 必须包含 strand_id"
            )
        pair = tuple(pair_record.get("patch_pair", ()))
        pair_strand_id = pair_record.get("strand_id")
        if pair_strand_id is None:
            raise ValueError(
                "Authoritative StripCorrespondence 缺少 strand_id"
            )
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
            and pair_strand_id == strand_id
            and source_patch_id in pair
        ]
        duplicate_matching_patch_pair = any(
            count > 1
            and pair_strand_id == strand_id
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
                candidate_lineage_identity = _complete_lineage_identity(candidate)
                if (
                    candidate_lineage_identity is None
                    or candidate_lineage_identity[0] != pipe_id
                    or candidate_lineage_identity[1] != strand_id
                    or candidate_lineage_identity[2]
                    != int(candidate_topology["profile_side_id"])
                    or candidate_lineage_identity[3]
                    != int(candidate_topology["opposite_profile_side_id"])
                    or candidate_lineage_identity[4]
                    != residual_topology["longitudinal_segment_id"]
                ):
                    continue
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
                        candidate_lineage_identity
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
                "semantic_batch_key": list(
                    record.get("semantic_batch_key", ())
                ),
                "pipe_id": pipe_id,
                "strand_id": strand_id,
                "source_patch_id": source_patch_id,
                "rail_id": record.get("rail_id"),
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
                "endpoint_port_tokens": list(
                    record.get("endpoint_port_tokens", ())
                ),
                "authoritative_plan_port_incidences": endpoint_port_incidences,
            }
        )
    maximal_source_chains = []
    for component in _build_maximal_source_components(normalized_edge_results):
        component_results = component["results"]
        source_connectivity = _validate_open_identity_chain(
            component_results,
            "normalized_edge_id",
            "endpoint_tokens",
        )
        direct_incidences_by_edge_id = {}
        conflicting_candidate_edge_ids = set()
        for result in component_results:
            for incidence in result["direct_face_edge_incidence"]:
                edge_id = incidence["boundary_edge_id"]
                existing = direct_incidences_by_edge_id.get(edge_id)
                if existing is not None and existing != incidence:
                    conflicting_candidate_edge_ids.add(edge_id)
                else:
                    direct_incidences_by_edge_id[edge_id] = incidence
        expected_source_face_signatures = sorted(
            {
                face_signature
                for result in component_results
                for face_signature in result[
                    "direct_candidate_count_by_source_face"
                ]
            }
        )
        candidate_edge_ids_by_source_face = {
            face_signature: sorted(
                {
                    edge_id
                    for edge_id, incidence
                    in direct_incidences_by_edge_id.items()
                    if incidence["source_face_signature"] == face_signature
                }
            )
            for face_signature in expected_source_face_signatures
        }
        candidate_chain_entries = [
            {
                "boundary_edge_id": edge_id,
                "endpoint_tokens": list(
                    boundary_by_edge_id[edge_id].get("endpoint_tokens", ())
                ),
            }
            for edge_id in sorted(direct_incidences_by_edge_id)
            if edge_id in boundary_by_edge_id
        ]
        candidate_connectivity = _validate_open_identity_chain(
            candidate_chain_entries,
            "boundary_edge_id",
            "endpoint_tokens",
        )
        member_rejection_reasons = sorted(
            {
                result["rejection_reason"]
                for result in component_results
                if result["rejection_reason"] is not None
            }
        )
        blocking_member_rejection_reasons = list(member_rejection_reasons)
        candidate_face_exactly_once = bool(
            expected_source_face_signatures
        ) and all(
            len(edge_ids) == 1
            for edge_ids in candidate_edge_ids_by_source_face.values()
        )
        if not source_connectivity["valid"]:
            chain_status = "UNRESOLVED"
            chain_rejection_reason = (
                "INVALID_MAXIMAL_SOURCE_CHAIN:"
                + source_connectivity["reason"]
            )
        elif conflicting_candidate_edge_ids:
            chain_status = "UNRESOLVED"
            chain_rejection_reason = "CONFLICTING_DIRECT_EDGE_INCIDENCE"
        elif blocking_member_rejection_reasons:
            chain_status = "UNRESOLVED"
            chain_rejection_reason = blocking_member_rejection_reasons[0]
        elif not candidate_face_exactly_once:
            chain_status = "UNRESOLVED"
            chain_rejection_reason = (
                "AMBIGUOUS_MAXIMAL_CANDIDATE_FACE_INCIDENCE"
                if any(
                    len(edge_ids) > 1
                    for edge_ids in candidate_edge_ids_by_source_face.values()
                )
                else "INCOMPLETE_MAXIMAL_CANDIDATE_FACE_INCIDENCE"
            )
        elif not candidate_connectivity["valid"]:
            chain_status = "UNRESOLVED"
            chain_rejection_reason = (
                "INVALID_MAXIMAL_CANDIDATE_CHAIN:"
                + candidate_connectivity["reason"]
            )
        else:
            chain_status = "UNIQUE_DIRECT_OPPOSITE_CONSUMER_CHAIN"
            chain_rejection_reason = None
        normalized_edge_ids = sorted(
            result["normalized_edge_id"] for result in component_results
        )
        maximal_chain_id = "maximal-source:" + _stable_fingerprint(
            {
                "lineage_key": component["lineage_key"],
                "normalized_edge_ids": normalized_edge_ids,
            }
        )
        all_candidate_edge_ids = sorted(direct_incidences_by_edge_id)
        ordered_candidate_edge_ids = candidate_connectivity[
            "ordered_edge_ids"
        ]
        maximal_source_chains.append(
            {
                "maximal_chain_id": maximal_chain_id,
                "status": chain_status,
                "resolved_consumer_id": (
                    "BOUNDARY_MAXIMAL_CHAIN:"
                    + _stable_fingerprint(ordered_candidate_edge_ids)
                    if chain_status
                    == "UNIQUE_DIRECT_OPPOSITE_CONSUMER_CHAIN"
                    else None
                ),
                "rejection_reason": chain_rejection_reason,
                "normalized_edge_ids": normalized_edge_ids,
                "raw_edge_ids": sorted(
                    {
                        edge_id
                        for result in component_results
                        for edge_id in result["raw_edge_ids"]
                    }
                ),
                "semantic_batch_key": list(component["lineage_key"][0]),
                "pipe_id": component["lineage_key"][1],
                "strand_id": component["lineage_key"][2],
                "source_patch_id": component["lineage_key"][3],
                "rail_id": component["lineage_key"][4],
                "profile_side_id": component["lineage_key"][5],
                "opposite_profile_side_id": component["lineage_key"][6],
                "source_lineage_segment_ids": list(
                    component["lineage_key"][7]
                ),
                "longitudinal_segment_ids": sorted(
                    {
                        segment_id
                        for result in component_results
                        for segment_id in result["longitudinal_segment_ids"]
                    }
                ),
                "source_chain_connectivity": source_connectivity,
                "candidate_edge_ids": all_candidate_edge_ids,
                "ordered_candidate_edge_ids": ordered_candidate_edge_ids,
                "candidate_chain_connectivity": candidate_connectivity,
                "candidate_edge_ids_by_source_face": (
                    candidate_edge_ids_by_source_face
                ),
                "candidate_face_exactly_once": candidate_face_exactly_once,
                "direct_face_edge_incidence": [
                    direct_incidences_by_edge_id[edge_id]
                    for edge_id in sorted(direct_incidences_by_edge_id)
                ],
                "conflicting_candidate_edge_ids": sorted(
                    conflicting_candidate_edge_ids
                ),
                "member_rejection_reasons": member_rejection_reasons,
                "blocking_member_rejection_reasons": (
                    blocking_member_rejection_reasons
                ),
            }
        )
    maximal_source_chains.sort(key=lambda item: item["maximal_chain_id"])
    candidate_edge_to_maximal_chains = {}
    for chain in maximal_source_chains:
        for edge_id in chain["candidate_edge_ids"]:
            candidate_edge_to_maximal_chains.setdefault(edge_id, []).append(
                chain["maximal_chain_id"]
            )
    overlapping_candidate_edges = {
        edge_id: sorted(maximal_chain_ids)
        for edge_id, maximal_chain_ids
        in candidate_edge_to_maximal_chains.items()
        if len(maximal_chain_ids) > 1
    }
    if overlapping_candidate_edges:
        for chain in maximal_source_chains:
            if any(
                edge_id in overlapping_candidate_edges
                for edge_id in chain["candidate_edge_ids"]
            ):
                chain["status"] = "UNRESOLVED"
                chain["resolved_consumer_id"] = None
                chain["rejection_reason"] = (
                    "OVERLAPPING_DIRECT_OPPOSITE_CONSUMER_CHAIN"
                )
    all_maximal_source_chains_resolved = bool(maximal_source_chains) and all(
        chain["status"] == "UNIQUE_DIRECT_OPPOSITE_CONSUMER_CHAIN"
        for chain in maximal_source_chains
    )
    maximal_status_by_normalized_edge_id = {
        normalized_edge_id: {
            "maximal_chain_id": chain["maximal_chain_id"],
            "maximal_chain_status": chain["status"],
            "maximal_chain_rejection_reason": chain["rejection_reason"],
        }
        for chain in maximal_source_chains
        for normalized_edge_id in chain["normalized_edge_ids"]
    }
    for result in normalized_edge_results:
        result.update(
            maximal_status_by_normalized_edge_id[result["normalized_edge_id"]]
        )
    return {
        "contract": GRAPH_CONTRACT,
        "status": "PROTOTYPE",
        "graph_input": {
            "normalized_edge_count": len(normalized_records),
            "maximal_source_chain_count": len(maximal_source_chains),
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
        "maximal_source_chains": maximal_source_chains,
        "subchains": maximal_source_chains,
        "all_normalized_edges_resolved": all_maximal_source_chains_resolved,
        "all_maximal_source_chains_resolved": (
            all_maximal_source_chains_resolved
        ),
        "all_subchains_resolved": all_maximal_source_chains_resolved,
        "candidate_edge_exactly_once": not overlapping_candidate_edges,
        "overlapping_candidate_edges": overlapping_candidate_edges,
        "raw_edge_exactly_once": len(raw_edge_ids) == len(set(raw_edge_ids)),
        "nearest_or_coordinate_matching_used": False,
        "consumer_resolution_mode": (
            "MAXIMAL_SOURCE_CHAIN_TO_PLAN_PATCH_ADJACENT_CUTTER_FACE_EDGE_CHAIN"
        ),
        "lineage_fingerprint": _stable_fingerprint(
            {
                record["normalized_edge_id"]: sorted(record["raw_edge_ids"])
                for record in normalized_records
            }
        ),
        "graph_fingerprint": _stable_fingerprint(
            {
                "normalized_edges": normalized_edge_results,
                "maximal_source_chains": maximal_source_chains,
                "overlapping_candidate_edges": overlapping_candidate_edges,
            }
        ),
    }
