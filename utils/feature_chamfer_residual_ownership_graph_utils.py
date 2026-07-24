# -*- coding: utf-8 -*-
"""Feature Chamfer Phase C 只读 ResidualOwnershipGraph 合同。"""

import bpy

import hashlib
import json
import math
from collections import deque

from mathutils import Vector


GRAPH_CONTRACT = "HST_PHASE_C_RESIDUAL_OWNERSHIP_GRAPH_V1"


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
                int(entry["source_patch_id"]),
                entry["rail_id"],
            )
            for entry in incident_entries
        }
        protected_port_tokens = {
            port_token
            for entry in incident_entries
            for port_token in entry.get("endpoint_port_tokens", ())
        }
        direct_topology_complete = all(
            entry.get("cutter_face_topology")
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
            )
            for entry in source_entries
        }
        if len(owner_signatures) != 1:
            raise ValueError("Normalization 试图合并不同 Pipe/Patch/Rail provenance")
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


# 把 normalized Edge 排成 maximal token-connected open subchains。
# normalized_records: constrained normalization 输出；返回稳定 subchain 列表。
def _normalized_token_subchains(normalized_records):
    records_by_id = {
        record["normalized_edge_id"]: record for record in normalized_records
    }
    record_ids_by_token = {}
    for record in normalized_records:
        for token in record["endpoint_tokens"]:
            record_ids_by_token.setdefault(token, set()).add(
                record["normalized_edge_id"]
            )
    remaining = set(records_by_id)
    subchains = []
    while remaining:
        seed_id = min(remaining)
        component = set()
        queue = [seed_id]
        while queue:
            record_id = queue.pop()
            if record_id in component:
                continue
            component.add(record_id)
            for token in records_by_id[record_id]["endpoint_tokens"]:
                queue.extend(record_ids_by_token[token] - component)
        remaining -= component
        component_records = [records_by_id[record_id] for record_id in component]
        owner_signatures = {
            (
                int(record["pipe_id"]),
                record.get("strand_id"),
                int(record["source_patch_id"]),
                record["rail_id"],
            )
            for record in component_records
        }
        if len(owner_signatures) != 1:
            raise ValueError("Normalized subchain 混入不同 owner provenance")
        degrees = {
            token: len(record_ids_by_token[token] & component)
            for record in component_records
            for token in record["endpoint_tokens"]
        }
        endpoints = sorted(token for token, degree in degrees.items() if degree == 1)
        if len(endpoints) != 2:
            raise ValueError("Normalized residual component 不是唯一 open subchain")
        current_token = endpoints[0]
        remaining_component = set(component)
        ordered_records = []
        ordered_tokens = [current_token]
        while remaining_component:
            candidates = sorted(
                record_ids_by_token[current_token] & remaining_component
            )
            if len(candidates) != 1:
                raise ValueError("Normalized residual token walk 存在歧义")
            record = records_by_id[candidates[0]]
            ordered_records.append(record)
            remaining_component.remove(record["normalized_edge_id"])
            current_token = next(
                token
                for token in record["endpoint_tokens"]
                if token != current_token
            )
            ordered_tokens.append(current_token)
        subchains.append(
            {
                "subchain_id": "residual-subchain:" + _stable_fingerprint(
                    [record["normalized_edge_id"] for record in ordered_records]
                ),
                "records": ordered_records,
                "endpoint_tokens": ordered_tokens,
            }
        )
    return tuple(sorted(subchains, key=lambda item: item["subchain_id"]))


# 从一个 opposite Face seed 沿同 Pipe longitudinal adjacency 查找最近的直接 Boundary/consumer sink。
# seed/pipe/graph/face-boundary/claims/setback/excluded/patches: graph 上下文；返回最短路径与候选身份。
def _nearest_longitudinal_sinks(
    seed_face_signature,
    pipe_id,
    face_records_by_signature,
    longitudinal_adjacency,
    boundary_entries_by_face,
    regular_claim_by_edge_id,
    setback_edge_ids,
    excluded_edge_ids,
    source_patch_ids,
    allowed_patch_pair=None,
):
    seed_record = face_records_by_signature.get(seed_face_signature)
    if seed_record is None or int(seed_record.get("pipe_id", -1)) != int(pipe_id):
        return {
            "seed_face_signature": seed_face_signature,
            "status": "MISSING_FACE_NODE",
            "distance": None,
            "candidates": [],
        }
    queue = deque([seed_face_signature])
    distance_by_face = {seed_face_signature: 0}
    path_count_by_face = {seed_face_signature: 1}
    predecessor_by_face = {seed_face_signature: None}
    found_distance = None
    candidate_records = []
    while queue:
        face_signature = queue.popleft()
        distance = distance_by_face[face_signature]
        if found_distance is not None and distance > found_distance:
            break
        face_candidates = []
        for entry in boundary_entries_by_face.get(face_signature, ()):
            edge_id = entry["edge_id"]
            if (
                edge_id in excluded_edge_ids
                or edge_id in setback_edge_ids
                or int(entry["pipe_id"]) != int(pipe_id)
                or int(entry["source_patch_id"]) in source_patch_ids
                or (
                    allowed_patch_pair is not None
                    and int(entry["source_patch_id"]) not in allowed_patch_pair
                )
            ):
                continue
            claim = regular_claim_by_edge_id.get(edge_id)
            if claim is None:
                sink_id = f"BOUNDARY_EDGE:{edge_id}"
                sink_kind = "UNCLAIMED_BOUNDARY_EDGE"
            else:
                consumer_id = claim.get("face_consumer_id") or (
                    f"face-consumer:{claim['job_id']}"
                )
                sink_id = f"REGULAR_CONSUMER:{consumer_id}"
                sink_kind = "REGULAR_CONSUMER"
            path = [face_signature]
            predecessor = predecessor_by_face[face_signature]
            while predecessor is not None:
                path.append(predecessor)
                predecessor = predecessor_by_face[predecessor]
            face_candidates.append(
                {
                    "sink_id": sink_id,
                    "sink_kind": sink_kind,
                    "boundary_edge_id": edge_id,
                    "boundary_source_patch_id": int(entry["source_patch_id"]),
                    "distance": distance,
                    "face_path": list(reversed(path)),
                    "shortest_path_count": path_count_by_face[face_signature],
                }
            )
        if face_candidates:
            found_distance = distance
            candidate_records.extend(face_candidates)
            continue
        for neighbor in sorted(longitudinal_adjacency.get(face_signature, ())):
            neighbor_record = face_records_by_signature.get(neighbor)
            if (
                neighbor_record is None
                or int(neighbor_record.get("pipe_id", -1)) != int(pipe_id)
            ):
                continue
            next_distance = distance + 1
            existing_distance = distance_by_face.get(neighbor)
            if existing_distance is None:
                distance_by_face[neighbor] = next_distance
                path_count_by_face[neighbor] = path_count_by_face[face_signature]
                predecessor_by_face[neighbor] = face_signature
                queue.append(neighbor)
            elif existing_distance == next_distance:
                path_count_by_face[neighbor] += path_count_by_face[face_signature]
    candidate_records = sorted(
        candidate_records,
        key=lambda item: (item["sink_id"], item["boundary_edge_id"]),
    )
    sink_ids = sorted({item["sink_id"] for item in candidate_records})
    unique_path = (
        len(candidate_records) == 1
        and len(sink_ids) == 1
        and candidate_records[0]["shortest_path_count"] == 1
    )
    return {
        "seed_face_signature": seed_face_signature,
        "status": (
            "UNIQUE" if unique_path else "MISSING" if not candidate_records else "AMBIGUOUS"
        ),
        "distance": found_distance,
        "sink_ids": sink_ids,
        "candidates": candidate_records,
    }


# 构建只读 ResidualOwnershipGraph，并对每条 maximal normalized subchain 输出唯一 direct witness 或 UNRESOLVED。
# normalized/universe/faces/claims/setbacks/ports: graph 输入合同；返回机器可读 graph artifact。
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
    longitudinal_adjacency = {}
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
        longitudinal_adjacency.setdefault(face_signature, set()).update(
            record.get("longitudinal_neighbor_face_signatures", ())
        )
    for face_signature, neighbors in tuple(longitudinal_adjacency.items()):
        for neighbor in tuple(neighbors):
            if neighbor in face_records_by_signature:
                longitudinal_adjacency.setdefault(neighbor, set()).add(
                    face_signature
                )
    boundary_entries_by_face = {}
    for entry in boundary_universe:
        for topology in entry.get("cutter_face_topology", ()):
            if topology.get("topology_status") != "PROVEN_C4_PIPE":
                continue
            boundary_entries_by_face.setdefault(
                topology.get("face_signature"), []
            ).append(entry)
    port_incidences_by_token = {}
    for incidence in authoritative_plan_port_incidences:
        if not incidence.get("authoritative", False):
            continue
        port_incidences_by_token.setdefault(
            incidence["endpoint_token"], []
        ).append(dict(incidence))
    normalized_allowed_patch_pairs = {
        frozenset(int(patch_id) for patch_id in pair)
        for pair in allowed_source_patch_pairs
        if len(pair) == 2
    }
    subchain_results = []
    for subchain in _normalized_token_subchains(normalized_records):
        records = subchain["records"]
        pipe_ids = {int(record["pipe_id"]) for record in records}
        source_patch_ids = {
            int(record["source_patch_id"]) for record in records
        }
        if len(pipe_ids) != 1:
            raise ValueError("Residual subchain 混入不同 Pipe")
        pipe_id = next(iter(pipe_ids))
        matching_patch_pairs = [
            pair
            for pair in normalized_allowed_patch_pairs
            if source_patch_ids < pair
        ]
        if len(matching_patch_pairs) == 1:
            allowed_patch_pair = matching_patch_pairs[0]
        else:
            allowed_patch_pair = None
        opposite_face_signatures = sorted(
            {
                topology.get("profile_opposite_face_signature")
                for record in records
                for topology in record.get("cutter_face_topology", ())
                if topology.get("topology_status") == "PROVEN_C4_PIPE"
                and topology.get("profile_opposite_face_signature")
            }
        )
        excluded_edge_ids = {
            raw_edge_id
            for record in records
            for raw_edge_id in record.get("raw_edge_ids", ())
        }
        seed_witnesses = [
            _nearest_longitudinal_sinks(
                seed_face_signature,
                pipe_id,
                face_records_by_signature,
                longitudinal_adjacency,
                boundary_entries_by_face,
                regular_claim_by_edge_id,
                setback_edge_ids,
                excluded_edge_ids,
                source_patch_ids,
                allowed_patch_pair,
            )
            for seed_face_signature in opposite_face_signatures
        ]
        unique_seed_sink_ids = {
            witness["sink_ids"][0]
            for witness in seed_witnesses
            if witness["status"] == "UNIQUE"
            and len(witness.get("sink_ids", ())) == 1
        }
        all_seeds_unique = bool(seed_witnesses) and all(
            witness["status"] == "UNIQUE" for witness in seed_witnesses
        )
        opposite_path_unique = (
            all_seeds_unique and len(unique_seed_sink_ids) == 1
        )
        endpoint_port_incidences = [
            incidence
            for endpoint_token in (
                subchain["endpoint_tokens"][0],
                subchain["endpoint_tokens"][-1],
            )
            for incidence in port_incidences_by_token.get(endpoint_token, ())
            if int(incidence.get("pipe_id", pipe_id)) == pipe_id
        ]
        unique_port_ids = sorted(
            {incidence["port_id"] for incidence in endpoint_port_incidences}
        )
        if opposite_path_unique:
            status = "UNIQUE_OPPOSITE_FACE_PATH"
            resolved_consumer_id = next(iter(unique_seed_sink_ids))
            rejection_reason = None
        elif len(unique_port_ids) == 1:
            status = "UNIQUE_PLAN_PORT_INCIDENCE"
            resolved_consumer_id = f"PLAN_PORT:{unique_port_ids[0]}"
            rejection_reason = None
        else:
            status = "UNRESOLVED"
            resolved_consumer_id = None
            if not opposite_face_signatures:
                rejection_reason = "MISSING_PROVEN_C4_OPPOSITE_FACE"
            elif any(
                witness["status"] == "AMBIGUOUS" for witness in seed_witnesses
            ):
                rejection_reason = "AMBIGUOUS_OPPOSITE_FACE_PATH"
            elif len(unique_port_ids) > 1:
                rejection_reason = "AMBIGUOUS_PLAN_PORT_INCIDENCE"
            else:
                rejection_reason = "MISSING_DIRECT_WITNESS"
        subchain_results.append(
            {
                "subchain_id": subchain["subchain_id"],
                "status": status,
                "resolved_consumer_id": resolved_consumer_id,
                "rejection_reason": rejection_reason,
                "normalized_edge_ids": [
                    record["normalized_edge_id"] for record in records
                ],
                "raw_edge_ids": sorted(excluded_edge_ids),
                "endpoint_tokens": list(subchain["endpoint_tokens"]),
                "pipe_id": pipe_id,
                "source_patch_ids": sorted(source_patch_ids),
                "allowed_source_patch_pair": (
                    sorted(allowed_patch_pair)
                    if allowed_patch_pair is not None
                    else None
                ),
                "profile_opposite_face_signatures": opposite_face_signatures,
                "opposite_face_seed_witnesses": seed_witnesses,
                "authoritative_plan_port_incidences": endpoint_port_incidences,
            }
        )
    all_subchains_resolved = bool(subchain_results) and all(
        result["status"] != "UNRESOLVED" for result in subchain_results
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
        "subchains": subchain_results,
        "all_subchains_resolved": all_subchains_resolved,
        "raw_edge_exactly_once": len(raw_edge_ids) == len(set(raw_edge_ids)),
        "nearest_or_coordinate_matching_used": False,
        "synthetic_owner_or_port_used": False,
        "lineage_fingerprint": _stable_fingerprint(
            {
                record["normalized_edge_id"]: sorted(record["raw_edge_ids"])
                for record in normalized_records
            }
        ),
        "graph_fingerprint": _stable_fingerprint(subchain_results),
    }
