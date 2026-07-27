# -*- coding: utf-8 -*-
"""Feature Chamfer Geometry Nodes 预览资产、状态与生命周期。"""

import hashlib
import json

import bpy

from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION
from ..const import FEATURE_CHAMFER_GN_ASSET_VERSION_TAG
from ..const import FEATURE_CHAMFER_GN_ASSET_SOURCE
from ..const import FEATURE_CHAMFER_GN_ASSET_SOURCE_TAG
from ..const import FEATURE_CHAMFER_GN_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_GN_LAST_ACTION_TAG
from ..const import FEATURE_CHAMFER_GN_MODIFIER
from ..const import FEATURE_CHAMFER_GN_NODE
from ..const import FEATURE_CHAMFER_GN_OWNER_TAG
from ..const import FEATURE_CHAMFER_GN_PARAMETERS_TAG
from ..const import FEATURE_CHAMFER_GN_STATE_TAG
from ..const import FEATURE_CHAMFER_PREVIEW_NONE
from ..const import FEATURE_CHAMFER_PREVIEW_STALE
from ..const import FEATURE_CHAMFER_PREVIEW_VALID
from ..const import FEATURE_CHAMFER_PATCHED
from ..const import FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG
from ..const import FEATURE_CHAMFER_CURVE_NODE
from ..const import FEATURE_CHAMFER_CURVE_OBJECT_TAG
from ..const import FEATURE_CHAMFER_CURVE_OWNER_TAG
from ..const import FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG
from ..const import PRESET_FILE_PATH
from .experimental_pipe_chamfer_utils import _base_stats
from .experimental_pipe_chamfer_utils import _build_preview_feature_graph
from .experimental_pipe_chamfer_utils import _classify_pipe_endpoints
from .experimental_pipe_chamfer_utils import _source_face_patch_ids
from .experimental_pipe_chamfer_utils import ensure_feature_chamfer_curve_pipe_asset
from .feature_chamfer_plan_utils import build_chamfer_plan
from .feature_chamfer_plan_utils import feature_strand_points
from .feature_chamfer_plan_utils import PLAN_ID_PROPERTY
from .feature_chamfer_plan_utils import PLAN_PROPERTY
from .feature_chamfer_plan_utils import read_chamfer_plan
from .feature_chamfer_plan_utils import write_chamfer_plan


PREVIEW_NONE = FEATURE_CHAMFER_PREVIEW_NONE
PREVIEW_VALID = FEATURE_CHAMFER_PREVIEW_VALID
PREVIEW_STALE = FEATURE_CHAMFER_PREVIEW_STALE
OWNER_VALUE = "HST_FEATURE_CHAMFER_GN_V1"
CURVE_PREVIEW_BACKEND = "PYTHON_CURVE_PIPE"
BOUNDARY_EDGE_ATTRIBUTE = "hst_feature_chamfer_boundary_edge"
PIPE_INPUT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_pipe_member_"
PIPE_BOUNDARY_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_pipe_"
SEGMENT_POINT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_segment_point_"
SEGMENT_STATION_POINT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_segment_station_point_"
SEGMENT_FACE_ATTRIBUTE_PREFIX = "hst_feature_chamfer_segment_face_"
SEGMENT_STATION_FACE_ATTRIBUTE_PREFIX = "hst_feature_chamfer_segment_station_face_"
SEGMENT_STATION_SQUARED_FACE_ATTRIBUTE_PREFIX = "hst_feature_chamfer_segment_station_squared_face_"
SEGMENT_BOUNDARY_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_segment_"
SEGMENT_BOUNDARY_POINT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_segment_point_"
SEGMENT_STATION_BOUNDARY_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_station_"
SEGMENT_STATION_SQUARED_BOUNDARY_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_station_squared_"
SEGMENT_STATION_SQUARED_BOUNDARY_POINT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_station_squared_point_"
SEGMENT_STATION_BOUNDARY_POINT_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_station_point_"
SOURCE_PATCH_ATTRIBUTE_PREFIX = "hst_feature_chamfer_boundary_patch_"
OWNED_BOOLEAN_PRO_TAG = "hst_feature_chamfer_owned_boolean_pro"


class FeatureChamferPreviewError(RuntimeError):
    """可诊断的 Feature Chamfer Preview 失败。"""


# 验证发布资产保留 fixture Boolean Pro 主链和受控 nested dependencies。
# node_group: 待验证 GeometryNodeTree；返回是否满足正式 Preview 基线。
def _is_valid_feature_chamfer_asset(node_group):
    if node_group.get(FEATURE_CHAMFER_GN_ASSET_SOURCE_TAG) != FEATURE_CHAMFER_GN_ASSET_SOURCE:
        return False
    boolean_node = node_group.nodes.get("Boolean Pro")
    group_input = next(
        (node for node in node_group.nodes if node.bl_idname == "NodeGroupInput"),
        None,
    )
    if (
        boolean_node is None
        or boolean_node.bl_idname != "GeometryNodeGroup"
        or boolean_node.node_tree is None
        or not boolean_node.node_tree.name.startswith("HST Feature Chamfer :: Boolean Pro")
        or group_input is None
    ):
        return False
    return (
        any(
            link.from_node == group_input
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry"
            for link in node_group.links
        )
        and any(
            dependency.name.startswith("HST Feature Chamfer :: Float Boolean Edges")
            for dependency in bpy.data.node_groups
        )
        and any(
            dependency.name.startswith("HST Feature Chamfer :: Boolean Solver Select")
            for dependency in bpy.data.node_groups
        )
    )


# 按 exact name、版本与 Boolean Pro runtime contract 导入受控 Preview 资产。
# 无参数；返回只读基线 GeometryNodeTree，冲突时 fail-closed。
def ensure_feature_chamfer_preview_node_group():
    node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is None:
        if not PRESET_FILE_PATH.exists():
            raise FeatureChamferPreviewError(f"Preview 资产不存在：{PRESET_FILE_PATH}")
        bpy.ops.wm.append(
            filepath=str(PRESET_FILE_PATH),
            directory=str(PRESET_FILE_PATH / "NodeTree"),
            filename=FEATURE_CHAMFER_GN_NODE,
        )
        node_group = bpy.data.node_groups.get(FEATURE_CHAMFER_GN_NODE)
    if node_group is None or node_group.bl_idname != "GeometryNodeTree":
        raise FeatureChamferPreviewError("无法导入受控 Feature Chamfer Preview 资产")
    if node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION:
        raise FeatureChamferPreviewError("Feature Chamfer Preview 资产版本不匹配")
    if not _is_valid_feature_chamfer_asset(node_group):
        raise FeatureChamferPreviewError("Feature Chamfer Preview 资产缺少受控 Boolean Pro 主链")
    return node_group


# 计算 source Mesh topology、位置和 Sharp Edge 的稳定指纹。
# source_object: 单个 Mesh Object；返回 SHA-256 字符串。
def source_fingerprint(source_object):
    mesh = source_object.data
    sharp_attribute = mesh.attributes.get("sharp_edge")
    payload = {
        "vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in mesh.vertices],
        "edges": [tuple(edge.vertices) for edge in mesh.edges],
        "polygons": [tuple(polygon.vertices) for polygon in mesh.polygons],
        "sharp_edges": [
            edge.index
            for edge in mesh.edges
            if sharp_attribute is not None and bool(sharp_attribute.data[edge.index].value)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# 把 Preview 构图时唯一生成的 Pipe groups 冻结为可跨阶段读取的稳定 JSON 合同。
# source_object/groups/chamfer_plan/radius: Preview source、已分类 groups、immutable plan 与半径；返回 JSON 字符串。
def _serialize_preview_pipe_contract(source_object, groups, chamfer_plan, radius):
    strands_by_edge_keys = {
        frozenset(strand.ordered_edge_keys): strand
        for strand in chamfer_plan.feature_strands
    }
    pipe_specs = []
    source_mesh = source_object.data
    for group in sorted(groups, key=lambda item: item["pipe_id"]):
        group_edge_keys = frozenset(
            "|".join(
                sorted(
                    ",".join(
                        f"{float(component):.8f}"
                        for component in source_mesh.vertices[vertex_index].co
                    )
                    for vertex_index in source_mesh.edges[edge_index].vertices
                )
            )
            for edge_index in group["edge_indices"]
        )
        strand = strands_by_edge_keys.get(group_edge_keys)
        if strand is None:
            raise FeatureChamferPreviewError(
                f"Preview Pipe {group['pipe_id']} 无法绑定到 ChamferPlan FeatureStrand"
            )
        pipe_specs.append(
            {
                "pipe_id": int(group["pipe_id"]),
                "strand_id": strand.strand_id,
                "ordered_edge_keys": list(strand.ordered_edge_keys),
                "edge_indices": [int(index) for index in group["edge_indices"]],
                "owner_surface_pairs_by_edge": [
                    [int(patch_id) for patch_id in owner_surface_pair]
                    for owner_surface_pair in group["patch_pair_by_edge"]
                ],
                "vertex_indices": [int(index) for index in group["vertex_indices"]],
                "points": [
                    [round(float(component), 10) for component in point]
                    for point in group["points"]
                ],
                "is_cyclic": bool(group["is_cyclic"]),
                "start_endpoint_class": str(group.get("start_endpoint_class", "CYCLIC")),
                "end_endpoint_class": str(group.get("end_endpoint_class", "CYCLIC")),
                "start_extension": round(float(group.get("start_extension", 0.0)), 10),
                "end_extension": round(float(group.get("end_extension", 0.0)), 10),
            }
        )
    if len(pipe_specs) != len(chamfer_plan.feature_strands):
        raise FeatureChamferPreviewError("Preview Pipe 合同与 ChamferPlan 不是一一对应")
    pipe_specs_by_strand_id = {
        pipe_spec["strand_id"]: pipe_spec
        for pipe_spec in pipe_specs
    }
    point_offsets_by_pipe_id = {}
    point_offset = 0
    for feature_strand in chamfer_plan.feature_strands:
        ordered_pipe_spec = pipe_specs_by_strand_id[feature_strand.strand_id]
        point_offsets_by_pipe_id[ordered_pipe_spec["pipe_id"]] = point_offset
        point_offset += len(ordered_pipe_spec["points"])
    preview_segments = []
    for spline_index, feature_strand in enumerate(chamfer_plan.feature_strands):
        pipe_spec = pipe_specs_by_strand_id[feature_strand.strand_id]
        pipe_spec["spline_index"] = spline_index
        pipe_cumulative_lengths = [0.0]
        for start, end in zip(pipe_spec["points"], pipe_spec["points"][1:]):
            pipe_cumulative_lengths.append(
                pipe_cumulative_lengths[-1]
                + sum(
                    (float(end[axis]) - float(start[axis])) ** 2
                    for axis in range(3)
                )
                ** 0.5
            )
        pipe_total_length = pipe_cumulative_lengths[-1]
        if pipe_spec["is_cyclic"] and len(pipe_spec["points"]) > 1:
            pipe_total_length += sum(
                (
                    float(pipe_spec["points"][0][axis])
                    - float(pipe_spec["points"][-1][axis])
                )
                ** 2
                for axis in range(3)
            ) ** 0.5
        if pipe_total_length <= 1.0e-12:
            raise FeatureChamferPreviewError(
                f"Preview Pipe {pipe_spec['pipe_id']} 缺少有效纵向长度"
            )
        port_records = []
        for port_index, port in enumerate(chamfer_plan.junction_ports):
            if feature_strand.strand_id not in port.incident_strand_ids:
                continue
            port_coordinate = tuple(
                float(component)
                for component in port.vertex_key.split("#", 1)[0].split(",")
            )
            matching_point_indices = [
                point_index
                for point_index, point in enumerate(pipe_spec["points"])
                if all(
                    abs(float(component) - port_component) <= 1.0e-7
                    for component, port_component in zip(point, port_coordinate)
                )
            ]
            if len(matching_point_indices) != 1:
                raise FeatureChamferPreviewError(
                    f"Preview Pipe {pipe_spec['pipe_id']} 无法唯一绑定 junction port"
                )
            port_records.append(
                {
                    "port_index": port_index,
                    "point_index": matching_point_indices[0],
                }
            )
        port_records.sort(key=lambda record: record["point_index"])
        pipe_spec["ports"] = port_records
        if not port_records:
            if not pipe_spec["is_cyclic"]:
                raise FeatureChamferPreviewError(
                    f"Open Preview Pipe {pipe_spec['pipe_id']} 缺少 junction ports"
                )
            segment_spans = [((), tuple(range(len(pipe_spec["points"]))))]
        else:
            pair_count = len(port_records) if pipe_spec["is_cyclic"] else len(port_records) - 1
            segment_spans = []
            for pair_index in range(pair_count):
                start_record = port_records[pair_index]
                end_record = port_records[(pair_index + 1) % len(port_records)]
                start_index = start_record["point_index"]
                end_index = end_record["point_index"]
                if start_index <= end_index:
                    point_indices = tuple(range(start_index, end_index + 1))
                else:
                    point_indices = (
                        tuple(range(start_index, len(pipe_spec["points"])))
                        + tuple(range(0, end_index + 1))
                    )
                segment_spans.append(
                    (
                        tuple(sorted((start_record["port_index"], end_record["port_index"]))),
                        point_indices,
                    )
                )
        pipe_spec["segment_ids"] = []
        for port_pair, point_indices in segment_spans:
            segment_id = len(preview_segments)
            pipe_spec["segment_ids"].append(segment_id)
            point_coordinates = [
                pipe_spec["points"][point_index]
                for point_index in point_indices
            ]
            cumulative_lengths = [0.0]
            for start, end in zip(point_coordinates, point_coordinates[1:]):
                cumulative_lengths.append(
                    cumulative_lengths[-1]
                    + sum(
                        (float(end[axis]) - float(start[axis])) ** 2
                        for axis in range(3)
                    )
                    ** 0.5
                )
            cyclic_segment = bool(pipe_spec["is_cyclic"] and not port_pair)
            source_edge_offsets = list(point_indices[:-1])
            if cyclic_segment:
                source_edge_offsets.append(point_indices[-1])
            source_edge_indices = [
                pipe_spec["edge_indices"][edge_offset]
                for edge_offset in source_edge_offsets
            ]
            owner_surface_pairs = []
            for edge_offset in source_edge_offsets:
                owner_surface_pair = tuple(
                    pipe_spec["owner_surface_pairs_by_edge"][edge_offset]
                )
                if owner_surface_pair not in owner_surface_pairs:
                    owner_surface_pairs.append(owner_surface_pair)
            if not source_edge_indices or not owner_surface_pairs:
                raise FeatureChamferPreviewError(
                    f"Preview segment {segment_id} 缺少 source Edge owner Surface pair"
                )
            total_length = cumulative_lengths[-1]
            if cyclic_segment and len(point_coordinates) > 1:
                total_length += sum(
                    (
                        float(point_coordinates[0][axis])
                        - float(point_coordinates[-1][axis])
                    )
                    ** 2
                    for axis in range(3)
                ) ** 0.5
            if total_length <= 1.0e-12:
                raise FeatureChamferPreviewError(
                    f"Preview segment {segment_id} 缺少有效纵向长度"
                )
            preview_segments.append(
                {
                    "segment_id": segment_id,
                    "pipe_id": pipe_spec["pipe_id"],
                    "strand_id": feature_strand.strand_id,
                    "port_indices": list(port_pair),
                    "point_indices": list(point_indices),
                    "global_point_indices": [
                        point_offsets_by_pipe_id[pipe_spec["pipe_id"]] + point_index
                        for point_index in point_indices
                    ],
                    "source_edge_indices": source_edge_indices,
                    "owner_surface_pairs": [
                        list(owner_surface_pair)
                        for owner_surface_pair in owner_surface_pairs
                    ],
                    "point_coordinates": point_coordinates,
                    "point_stations": [
                        round(length / total_length, 10)
                        for length in cumulative_lengths
                    ],
                    "spline_start_station": round(
                        pipe_cumulative_lengths[point_indices[0]] / pipe_total_length,
                        10,
                    ),
                    "spline_end_station": round(
                        pipe_cumulative_lengths[point_indices[-1]] / pipe_total_length,
                        10,
                    ),
                    "is_cyclic": cyclic_segment,
                }
            )
    return json.dumps(
        {
            "contract": "GN_PREVIEW_PIPE_V1",
            "plan_id": chamfer_plan.plan_id,
            "source_fingerprint": source_fingerprint(source_object),
            "radius": round(float(radius), 10),
            "pipes": pipe_specs,
            "segments": preview_segments,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


# 查找本工具拥有且名称稳定的 Geometry Nodes modifier。
# source_object: Preview 所属 Mesh Object；返回 modifier 或 None。
def owned_preview_modifier(source_object):
    modifier = source_object.modifiers.get(FEATURE_CHAMFER_GN_MODIFIER)
    if modifier is None or modifier.type != "NODES":
        return None
    if modifier.get(FEATURE_CHAMFER_GN_OWNER_TAG) != OWNER_VALUE:
        return None
    return modifier


# 查找由 source Object 拥有的 Python Curve source。
# source_object: Feature Chamfer source Mesh；返回 owned Curve Object 或 None。
def owned_preview_curve(source_object):
    curve_object_name = source_object.get(FEATURE_CHAMFER_CURVE_OBJECT_TAG)
    curve_object = bpy.data.objects.get(curve_object_name) if curve_object_name else None
    if (
        curve_object is None
        or curve_object.type != "CURVE"
    ):
        return None
    modifier = owned_preview_modifier(source_object)
    if modifier is not None:
        object_info = (
            modifier.node_group.nodes.get("HST Python CutterStrands")
            if modifier.node_group is not None
            else None
        )
        if (
            object_info is None
            or object_info.inputs["Object"].default_value != curve_object
        ):
            return None
    return curve_object


# 删除 source 拥有的 Curve Object 与 Curve datablock。
# source_object: Feature Chamfer source Mesh；无返回值。
def _remove_owned_preview_curve(source_object):
    curve_object = owned_preview_curve(source_object)
    if curve_object is not None:
        _remove_preview_curve_object(curve_object)
    if FEATURE_CHAMFER_CURVE_OBJECT_TAG in source_object:
        del source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG]


# 删除指定 Preview Curve Object 与无用户 Curve datablock。
# curve_object: 待删除 Curve Object；无返回值。
def _remove_preview_curve_object(curve_object):
    if curve_object is None or bpy.data.objects.get(curve_object.name) != curve_object:
        return
    curve_data = curve_object.data
    bpy.data.objects.remove(curve_object, do_unlink=True)
    if curve_data.users == 0:
        bpy.data.curves.remove(curve_data)


# 从 FeatureGraph 的有序 strands 重建一个由 Operator 管理的多 spline Curve。
# source_object/radius: source Mesh 与 endpoint cap containment 的采样距离；返回 Curve 与 stats。
def _rebuild_owned_preview_curve(source_object, radius):
    stats = _base_stats(source_object, 0.0, 8, 35.0, 3.0, 1.5, "PREVIEW")
    groups = _build_preview_feature_graph(source_object, radius, stats)
    _classify_pipe_endpoints(source_object, groups, radius)
    chamfer_plan = build_chamfer_plan(
        source_object,
        groups,
        radius,
        "GN_PREVIEW_V1",
        source_patch_ids=_source_face_patch_ids(source_object),
    )
    curve_data = bpy.data.curves.new(
        f"{source_object.name}_FeatureChamferPreviewCurve",
        type="CURVE",
    )
    curve_data.dimensions = "3D"
    pipe_contract_json = _serialize_preview_pipe_contract(
        source_object,
        groups,
        chamfer_plan,
        radius,
    )
    pipe_contract = json.loads(pipe_contract_json)
    pipe_records_by_strand_id = {
        item["strand_id"]: item for item in pipe_contract["pipes"]
    }
    for feature_strand in chamfer_plan.feature_strands:
        pipe_record = pipe_records_by_strand_id[feature_strand.strand_id]
        points = tuple(tuple(point) for point in pipe_record["points"])
        spline = curve_data.splines.new("POLY")
        spline.points.add(len(points) - 1)
        for index, point in enumerate(points):
            spline.points[index].co = (*point, 1.0)
        spline.use_cyclic_u = feature_strand.cyclic
    curve_object = bpy.data.objects.new(curve_data.name, curve_data)
    curve_object.matrix_world = source_object.matrix_world.copy()
    source_object.users_collection[0].objects.link(curve_object)
    curve_object.hide_set(True)
    curve_object.hide_render = True
    curve_object[FEATURE_CHAMFER_CURVE_OWNER_TAG] = source_object.name
    curve_object[FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG] = source_fingerprint(source_object)
    curve_object[FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG] = pipe_contract_json
    source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG] = curve_object.name
    return curve_object, stats, chamfer_plan


# 把多个 Boolean selection 连成一个 field，避免为 source Patch 引入新的 Mesh 分析路线。
# node_group/fields: 当前 wrapper 与 Boolean fields；返回合并后的 Boolean socket。
def _or_boolean_fields(node_group, fields):
    if not fields:
        return None
    combined = fields[0]
    for field in fields[1:]:
        boolean_or = node_group.nodes.new("FunctionNodeBooleanMath")
        boolean_or.operation = "OR"
        node_group.links.new(combined, boolean_or.inputs[0])
        node_group.links.new(field, boolean_or.inputs[1])
        combined = boolean_or.outputs["Boolean"]
    return combined


# 在 Geometry 上按 index selection 写一个 Boolean Named Attribute。
# node_group/geometry_socket/index_socket/indices/name/domain: Node Tree、输入 Geometry、Index field、目标索引、属性名与 domain；返回 Geometry socket。
def _store_index_membership(
    node_group,
    geometry_socket,
    index_socket,
    indices,
    attribute_name,
    domain,
):
    fields = []
    for target_index in indices:
        compare = node_group.nodes.new("FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.inputs[3].default_value = int(target_index)
        node_group.links.new(index_socket, compare.inputs[2])
        fields.append(compare.outputs["Result"])
    membership = _or_boolean_fields(node_group, fields)
    if membership is None:
        raise FeatureChamferPreviewError(
            f"Named Attribute {attribute_name} 缺少 selection indices"
        )
    store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "BOOLEAN"
    store.domain = domain
    store.inputs["Name"].default_value = attribute_name
    node_group.links.new(geometry_socket, store.inputs["Geometry"])
    node_group.links.new(membership, store.inputs["Value"])
    return store.outputs["Geometry"]


# 根据 Spline Parameter 生成槽段内归一化纵向位置，避免逐点构造庞大字段树。
# node_group/spline_factor/segment: Node Tree、Spline Parameter Factor 与冻结槽段；返回 Float field socket。
def _segment_station_field(node_group, spline_factor, segment):
    if segment["is_cyclic"]:
        return spline_factor
    start_station = float(segment["spline_start_station"])
    end_station = float(segment["spline_end_station"])
    adjusted_factor = spline_factor
    if end_station < start_station:
        compare = node_group.nodes.new("FunctionNodeCompare")
        compare.data_type = "FLOAT"
        compare.operation = "LESS_THAN"
        compare.inputs[1].default_value = start_station
        node_group.links.new(spline_factor, compare.inputs[0])
        add_one = node_group.nodes.new("ShaderNodeMath")
        add_one.operation = "ADD"
        add_one.inputs[1].default_value = 1.0
        node_group.links.new(spline_factor, add_one.inputs[0])
        switch = node_group.nodes.new("GeometryNodeSwitch")
        switch.input_type = "FLOAT"
        node_group.links.new(compare.outputs["Result"], switch.inputs["Switch"])
        node_group.links.new(spline_factor, switch.inputs["False"])
        node_group.links.new(add_one.outputs["Value"], switch.inputs["True"])
        adjusted_factor = switch.outputs["Output"]
        end_station += 1.0
    span = end_station - start_station
    if span <= 1.0e-12:
        raise FeatureChamferPreviewError(
            f"Preview segment {segment['segment_id']} 缺少有效 Spline span"
        )
    subtract = node_group.nodes.new("ShaderNodeMath")
    subtract.operation = "SUBTRACT"
    subtract.inputs[1].default_value = start_station
    node_group.links.new(adjusted_factor, subtract.inputs[0])
    divide = node_group.nodes.new("ShaderNodeMath")
    divide.operation = "DIVIDE"
    divide.inputs[1].default_value = span
    node_group.links.new(subtract.outputs["Value"], divide.inputs[0])
    return divide.outputs["Value"]


# 在 owned Curve 的 POINT 域写槽段 one-hot 与纵向位置，交叉点可同时属于相邻两段。
# node_group/curve_socket/pipe_contract: wrapper、Curve Geometry 与冻结合同；返回带槽段属性的 Curve socket。
def _store_preview_segment_points(node_group, curve_socket, pipe_contract):
    index = node_group.nodes.new("GeometryNodeInputIndex")
    spline_parameter = node_group.nodes.new("GeometryNodeSplineParameter")
    current_geometry = curve_socket
    for segment in pipe_contract["segments"]:
        current_geometry = _store_index_membership(
            node_group,
            current_geometry,
            index.outputs["Index"],
            segment["global_point_indices"],
            SEGMENT_POINT_ATTRIBUTE_PREFIX + str(segment["segment_id"]),
            "POINT",
        )
        store_station = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
        store_station.data_type = "FLOAT"
        store_station.domain = "POINT"
        store_station.inputs["Name"].default_value = (
            SEGMENT_STATION_POINT_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        node_group.links.new(current_geometry, store_station.inputs["Geometry"])
        node_group.links.new(
            _segment_station_field(
                node_group,
                spline_parameter.outputs["Factor"],
                segment,
            ),
            store_station.inputs["Value"],
        )
        current_geometry = store_station.outputs["Geometry"]
    return current_geometry


# 在 Curve Pipe FACE 域写 Pipe/槽段 one-hot，供 Boolean Pro solver 直接物化到 Boundary Edges。
# node_group/cutter_socket/pipe_contract: wrapper、Curve Pipe Mesh 与冻结合同；返回带全部 FACE provenance 的 Mesh socket。
def _store_cutter_grouping_attributes(node_group, cutter_socket, pipe_contract):
    named_pipe_id = node_group.nodes.new("GeometryNodeInputNamedAttribute")
    named_pipe_id.data_type = "INT"
    named_pipe_id.inputs["Name"].default_value = "hst_feature_chamfer_pipe_id"
    current_geometry = cutter_socket
    for pipe_record in pipe_contract["pipes"]:
        compare = node_group.nodes.new("FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.inputs[3].default_value = int(pipe_record["spline_index"]) + 1
        node_group.links.new(named_pipe_id.outputs["Attribute"], compare.inputs[2])
        store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type = "BOOLEAN"
        store.domain = "FACE"
        store.inputs["Name"].default_value = (
            PIPE_INPUT_ATTRIBUTE_PREFIX + str(pipe_record["pipe_id"])
        )
        node_group.links.new(current_geometry, store.inputs["Geometry"])
        node_group.links.new(compare.outputs["Result"], store.inputs["Value"])
        current_geometry = store.outputs["Geometry"]
    for segment in pipe_contract["segments"]:
        named_segment = node_group.nodes.new("GeometryNodeInputNamedAttribute")
        named_segment.data_type = "FLOAT"
        named_segment.inputs["Name"].default_value = (
            SEGMENT_POINT_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        named_pipe = node_group.nodes.new("GeometryNodeInputNamedAttribute")
        named_pipe.data_type = "BOOLEAN"
        named_pipe.inputs["Name"].default_value = (
            PIPE_INPUT_ATTRIBUTE_PREFIX + str(segment["pipe_id"])
        )
        multiply = node_group.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        node_group.links.new(named_segment.outputs["Attribute"], multiply.inputs[0])
        node_group.links.new(named_pipe.outputs["Attribute"], multiply.inputs[1])
        store = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type = "FLOAT"
        store.domain = "FACE"
        store.inputs["Name"].default_value = (
            SEGMENT_FACE_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        node_group.links.new(current_geometry, store.inputs["Geometry"])
        node_group.links.new(multiply.outputs["Value"], store.inputs["Value"])
        current_geometry = store.outputs["Geometry"]
        named_station = node_group.nodes.new("GeometryNodeInputNamedAttribute")
        named_station.data_type = "FLOAT"
        named_station.inputs["Name"].default_value = (
            SEGMENT_STATION_POINT_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        station_multiply = node_group.nodes.new("ShaderNodeMath")
        station_multiply.operation = "MULTIPLY"
        node_group.links.new(named_station.outputs["Attribute"], station_multiply.inputs[0])
        node_group.links.new(multiply.outputs["Value"], station_multiply.inputs[1])
        store_station = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
        store_station.data_type = "FLOAT"
        store_station.domain = "FACE"
        store_station.inputs["Name"].default_value = (
            SEGMENT_STATION_FACE_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        node_group.links.new(current_geometry, store_station.inputs["Geometry"])
        node_group.links.new(station_multiply.outputs["Value"], store_station.inputs["Value"])
        current_geometry = store_station.outputs["Geometry"]
        station_squared = node_group.nodes.new("ShaderNodeMath")
        station_squared.operation = "MULTIPLY"
        node_group.links.new(named_station.outputs["Attribute"], station_squared.inputs[0])
        node_group.links.new(named_station.outputs["Attribute"], station_squared.inputs[1])
        station_squared_multiply = node_group.nodes.new("ShaderNodeMath")
        station_squared_multiply.operation = "MULTIPLY"
        node_group.links.new(
            station_squared.outputs["Value"],
            station_squared_multiply.inputs[0],
        )
        node_group.links.new(multiply.outputs["Value"], station_squared_multiply.inputs[1])
        store_station_squared = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
        store_station_squared.data_type = "FLOAT"
        store_station_squared.domain = "FACE"
        store_station_squared.inputs["Name"].default_value = (
            SEGMENT_STATION_SQUARED_FACE_ATTRIBUTE_PREFIX
            + str(segment["segment_id"])
        )
        node_group.links.new(current_geometry, store_station_squared.inputs["Geometry"])
        node_group.links.new(
            station_squared_multiply.outputs["Value"],
            store_station_squared.inputs["Value"],
        )
        current_geometry = store_station_squared.outputs["Geometry"]
    return current_geometry


# 在 source Geometry FACE 域保存 Surface Patch one-hot，使 Boundary 两侧可读但不参与 Boundary acquisition。
# node_group/source_socket/source_object: wrapper、source Geometry 与原 Object；返回带 Patch 属性的 Geometry socket。
def _store_source_patch_attributes(node_group, source_socket, source_object):
    patch_ids = _source_face_patch_ids(source_object)
    patch_face_indices = {}
    for face_index, patch_id in enumerate(patch_ids):
        patch_face_indices.setdefault(int(patch_id), []).append(face_index)
    index = node_group.nodes.new("GeometryNodeInputIndex")
    current_geometry = source_socket
    for patch_id, face_indices in sorted(patch_face_indices.items()):
        current_geometry = _store_index_membership(
            node_group,
            current_geometry,
            index.outputs["Index"],
            face_indices,
            SOURCE_PATCH_ATTRIBUTE_PREFIX + str(patch_id),
            "FACE",
        )
    return current_geometry, tuple(sorted(patch_face_indices))


# 在 Boolean Pro active Manifold Difference 输出上把输入 provenance 写成 EDGE 属性。
# boolean_node/pipe_contract/patch_ids: wrapper 中的 Boolean Pro、冻结 Pipe 合同与 source Patch IDs；返回 owned nested Node Group。
def _materialize_boolean_boundary_grouping(boolean_node, pipe_contract, patch_ids):
    boolean_tree = boolean_node.node_tree.copy()
    boolean_tree.name = f"{boolean_node.node_tree.name} :: Direct Segment Bridge"
    boolean_tree[OWNED_BOOLEAN_PRO_TAG] = True
    boolean_node.node_tree = boolean_tree
    solver_select = boolean_tree.nodes.get("Group.007")
    geometry_target = boolean_tree.nodes.get("Reroute.037")
    if (
        solver_select is None
        or geometry_target is None
        or solver_select.bl_idname != "GeometryNodeGroup"
        or "Geometry" not in solver_select.outputs
        or "Intersection Edges" not in solver_select.outputs
    ):
        raise FeatureChamferPreviewError(
            "受控 Boolean Pro 缺少 Manifold Difference grouping seam"
        )
    geometry_links = [
        link
        for link in list(boolean_tree.links)
        if link.from_node == solver_select
        and link.from_socket.name == "Geometry"
        and link.to_node == geometry_target
    ]
    if len(geometry_links) != 1:
        raise FeatureChamferPreviewError(
            "受控 Boolean Pro 的 Manifold Difference Geometry seam 不唯一"
        )
    boolean_tree.links.remove(geometry_links[0])
    current_geometry = solver_select.outputs["Geometry"]
    attribute_specs = [
        (
            PIPE_INPUT_ATTRIBUTE_PREFIX + str(pipe_record["pipe_id"]),
            PIPE_BOUNDARY_ATTRIBUTE_PREFIX + str(pipe_record["pipe_id"]),
            "BOOLEAN",
        )
        for pipe_record in pipe_contract["pipes"]
    ]
    attribute_specs.extend(
        (
            SEGMENT_FACE_ATTRIBUTE_PREFIX + str(segment["segment_id"]),
            SEGMENT_BOUNDARY_ATTRIBUTE_PREFIX + str(segment["segment_id"]),
            "FLOAT",
        )
        for segment in pipe_contract["segments"]
    )
    attribute_specs.extend(
        (
            SOURCE_PATCH_ATTRIBUTE_PREFIX + str(patch_id),
            SOURCE_PATCH_ATTRIBUTE_PREFIX + str(patch_id),
            "BOOLEAN",
        )
        for patch_id in patch_ids
    )
    for input_name, output_name, data_type in attribute_specs:
        named = boolean_tree.nodes.new("GeometryNodeInputNamedAttribute")
        named.data_type = data_type
        named.inputs["Name"].default_value = input_name
        store = boolean_tree.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type = data_type
        store.domain = "EDGE"
        store.inputs["Name"].default_value = output_name
        boolean_tree.links.new(current_geometry, store.inputs["Geometry"])
        boolean_tree.links.new(
            solver_select.outputs["Intersection Edges"],
            store.inputs["Selection"],
        )
        boolean_tree.links.new(named.outputs["Attribute"], store.inputs["Value"])
        current_geometry = store.outputs["Geometry"]
    for segment in pipe_contract["segments"]:
        named_segment = boolean_tree.nodes.new("GeometryNodeInputNamedAttribute")
        named_segment.data_type = "FLOAT"
        named_segment.inputs["Name"].default_value = (
            SEGMENT_FACE_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        store_segment_point = boolean_tree.nodes.new("GeometryNodeStoreNamedAttribute")
        store_segment_point.data_type = "FLOAT"
        store_segment_point.domain = "POINT"
        store_segment_point.inputs["Name"].default_value = (
            SEGMENT_BOUNDARY_POINT_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        boolean_tree.links.new(current_geometry, store_segment_point.inputs["Geometry"])
        boolean_tree.links.new(named_segment.outputs["Attribute"], store_segment_point.inputs["Value"])
        current_geometry = store_segment_point.outputs["Geometry"]
        named_station = boolean_tree.nodes.new("GeometryNodeInputNamedAttribute")
        named_station.data_type = "FLOAT"
        named_station.inputs["Name"].default_value = (
            SEGMENT_STATION_FACE_ATTRIBUTE_PREFIX + str(segment["segment_id"])
        )
        for domain, attribute_prefix in (
            ("POINT", SEGMENT_STATION_BOUNDARY_POINT_ATTRIBUTE_PREFIX),
            ("EDGE", SEGMENT_STATION_BOUNDARY_ATTRIBUTE_PREFIX),
        ):
            store_station = boolean_tree.nodes.new("GeometryNodeStoreNamedAttribute")
            store_station.data_type = "FLOAT"
            store_station.domain = domain
            store_station.inputs["Name"].default_value = (
                attribute_prefix + str(segment["segment_id"])
            )
            boolean_tree.links.new(current_geometry, store_station.inputs["Geometry"])
            boolean_tree.links.new(named_station.outputs["Attribute"], store_station.inputs["Value"])
            current_geometry = store_station.outputs["Geometry"]
        named_station_squared = boolean_tree.nodes.new("GeometryNodeInputNamedAttribute")
        named_station_squared.data_type = "FLOAT"
        named_station_squared.inputs["Name"].default_value = (
            SEGMENT_STATION_SQUARED_FACE_ATTRIBUTE_PREFIX
            + str(segment["segment_id"])
        )
        for domain, attribute_prefix in (
            ("POINT", SEGMENT_STATION_SQUARED_BOUNDARY_POINT_ATTRIBUTE_PREFIX),
            ("EDGE", SEGMENT_STATION_SQUARED_BOUNDARY_ATTRIBUTE_PREFIX),
        ):
            store_station_squared = boolean_tree.nodes.new("GeometryNodeStoreNamedAttribute")
            store_station_squared.data_type = "FLOAT"
            store_station_squared.domain = domain
            store_station_squared.inputs["Name"].default_value = (
                attribute_prefix + str(segment["segment_id"])
            )
            boolean_tree.links.new(current_geometry, store_station_squared.inputs["Geometry"])
            boolean_tree.links.new(
                named_station_squared.outputs["Attribute"],
                store_station_squared.inputs["Value"],
            )
            current_geometry = store_station_squared.outputs["Geometry"]
    boolean_tree.links.new(current_geometry, geometry_target.inputs["Input"])
    return boolean_tree


# 构建正式 Preview wrapper：复制受控资产，仅把 cutter seam 改为 Python Curve Pipe。
# curve_object/radius/show_cutter: owned Curve、倒角半径与 cutter 显示开关。
def _build_curve_preview_node_group(curve_object, radius, show_cutter):
    base_group = ensure_feature_chamfer_preview_node_group()
    curve_pipe_asset = ensure_feature_chamfer_curve_pipe_asset()
    node_group = base_group.copy()
    node_group.name = f"HST Feature Chamfer Curve Preview :: {curve_object.name}"
    node_group[FEATURE_CHAMFER_GN_ASSET_VERSION_TAG] = FEATURE_CHAMFER_GN_ASSET_VERSION
    node_group["hst_feature_chamfer_preview_backend"] = CURVE_PREVIEW_BACKEND
    pipe_contract = json.loads(
        curve_object[FEATURE_CHAMFER_CURVE_PIPE_CONTRACT_TAG]
    )
    source_object = bpy.data.objects.get(
        curve_object[FEATURE_CHAMFER_CURVE_OWNER_TAG]
    )
    if source_object is None or source_object.type != "MESH":
        raise FeatureChamferPreviewError("Preview Curve 对应的 source Object 不存在")
    group_input = next(node for node in node_group.nodes if node.bl_idname == "NodeGroupInput")
    boolean_node = node_group.nodes.get("Boolean Pro")
    switch_node = node_group.nodes.get("HST Boolean Result or Cutter")
    old_cutter_node = node_group.nodes.get("HST Junction-safe Pipe")
    if boolean_node is None or switch_node is None or old_cutter_node is None:
        raise FeatureChamferPreviewError("受控 Preview 资产缺少 cutter seam nodes")
    object_info = node_group.nodes.new("GeometryNodeObjectInfo")
    object_info.name = "HST Python CutterStrands"
    object_info.inputs["Object"].default_value = curve_object
    curve_circle = node_group.nodes.new("GeometryNodeCurvePrimitiveCircle")
    curve_circle.name = "HST Four-sided Chamfer Profile"
    curve_circle.inputs["Resolution"].default_value = 4
    curve_pipe = node_group.nodes.new("GeometryNodeGroup")
    curve_pipe.name = "HST Even-Thickness Curve Pipe"
    curve_pipe.node_tree = curve_pipe_asset
    curve_pipe.inputs["Fill Caps"].default_value = True
    curve_pipe.inputs["Even-Thickness"].default_value = True
    for link in list(node_group.links):
        if (
            link.from_node == old_cutter_node
            and (
                (link.to_node == boolean_node and link.to_socket.name == "Geometry B")
                or (link.to_node == switch_node and link.to_socket.name == "True")
            )
        ):
            node_group.links.remove(link)
    node_group.links.new(group_input.outputs["Radius"], curve_circle.inputs["Radius"])
    curve_geometry = _store_preview_segment_points(
        node_group,
        object_info.outputs["Geometry"],
        pipe_contract,
    )
    pipe_index = node_group.nodes.new("GeometryNodeInputIndex")
    add_one = node_group.nodes.new("ShaderNodeMath")
    add_one.operation = "ADD"
    add_one.inputs[1].default_value = 1.0
    node_group.links.new(pipe_index.outputs["Index"], add_one.inputs[0])
    store_pipe_id = node_group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_pipe_id.data_type = "INT"
    store_pipe_id.domain = "CURVE"
    store_pipe_id.inputs["Name"].default_value = "hst_feature_chamfer_pipe_id"
    node_group.links.new(curve_geometry, store_pipe_id.inputs["Geometry"])
    node_group.links.new(add_one.outputs["Value"], store_pipe_id.inputs["Value"])
    node_group.links.new(store_pipe_id.outputs["Geometry"], curve_pipe.inputs["Curve"])
    node_group.links.new(curve_circle.outputs["Curve"], curve_pipe.inputs["Profile Curve"])
    cutter_geometry = _store_cutter_grouping_attributes(
        node_group,
        curve_pipe.outputs["Geometry"],
        pipe_contract,
    )
    source_geometry, patch_ids = _store_source_patch_attributes(
        node_group,
        group_input.outputs["Geometry"],
        source_object,
    )
    for link in list(node_group.links):
        if (
            link.from_node == group_input
            and link.from_socket.name == "Geometry"
            and link.to_node == boolean_node
            and link.to_socket.name == "Geometry"
        ):
            node_group.links.remove(link)
    node_group.links.new(source_geometry, boolean_node.inputs["Geometry"])
    node_group.links.new(cutter_geometry, boolean_node.inputs["Geometry B"])
    node_group.links.new(cutter_geometry, switch_node.inputs["True"])
    _materialize_boolean_boundary_grouping(
        boolean_node,
        pipe_contract,
        patch_ids,
    )
    return node_group


# 删除本工具创建的 per-preview wrapper Node Group。
# modifier: owned Preview modifier；无返回值。
def _remove_owned_preview_node_group(modifier):
    node_group = modifier.node_group if modifier is not None else None
    owned_boolean_groups = []
    if (
        node_group is not None
        and node_group.get("hst_feature_chamfer_preview_backend") == CURVE_PREVIEW_BACKEND
    ):
        owned_boolean_groups = [
            node.node_tree
            for node in node_group.nodes
            if node.bl_idname == "GeometryNodeGroup"
            and node.node_tree is not None
            and node.node_tree.get(OWNED_BOOLEAN_PRO_TAG)
        ]
        modifier.node_group = None
        if node_group.users == 0:
            bpy.data.node_groups.remove(node_group)
        for boolean_group in owned_boolean_groups:
            if boolean_group.users == 0:
                bpy.data.node_groups.remove(boolean_group)


# 返回 Node Group 输入 socket 的 identifier 映射，避免硬编码 Socket_N。
# node_group: GeometryNodeTree；返回 input display name 到 identifier 的字典。
def _input_identifiers(node_group):
    return {
        item.name: item.identifier
        for item in node_group.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT"
    }


# 返回 modifier live sockets 中的可调参数字典。
# modifier: 本工具拥有的 Geometry Nodes modifier。
def live_preview_parameters(modifier):
    identifiers = _input_identifiers(modifier.node_group)
    return {
        "adaptivity": 0.0,
        "radius": float(modifier[identifiers["Radius"]]),
        "sample_length": 0.0,
        "show_cutter": bool(modifier[identifiers["Show Cutter"]]),
        "voxel_size": 0.0,
    }


# 读取当前 Preview 状态，并把 source、资产或 plan 不一致归类为 stale。
# source_object: Preview 所属 Mesh；Modifier sockets 是 live 参数真源。
def preview_state(source_object):
    if source_object.get(FEATURE_CHAMFER_GN_STATE_TAG) == FEATURE_CHAMFER_PATCHED:
        return FEATURE_CHAMFER_PATCHED
    modifier = owned_preview_modifier(source_object)
    if modifier is None:
        return PREVIEW_NONE
    node_group = modifier.node_group
    try:
        source_plan = read_chamfer_plan(source_object)
        modifier_plan = read_chamfer_plan(modifier)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        source_plan = None
        modifier_plan = None
    stale = (
        node_group is None
        or node_group.get("hst_feature_chamfer_preview_backend") != CURVE_PREVIEW_BACKEND
        or node_group.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_ASSET_VERSION_TAG) != FEATURE_CHAMFER_GN_ASSET_VERSION
        or modifier.get(FEATURE_CHAMFER_GN_FINGERPRINT_TAG) != source_fingerprint(source_object)
        or modifier.get(FEATURE_CHAMFER_GN_PARAMETERS_TAG)
        != json.dumps(live_preview_parameters(modifier), sort_keys=True)
        or owned_preview_curve(source_object) is None
        or owned_preview_curve(source_object).get(FEATURE_CHAMFER_CURVE_FINGERPRINT_TAG)
        != source_fingerprint(source_object)
        or source_plan is None
        or modifier_plan is None
        or source_plan != modifier_plan
    )
    state = PREVIEW_STALE if stale else PREVIEW_VALID
    source_object[FEATURE_CHAMFER_GN_STATE_TAG] = state
    return state


# 创建或幂等更新一个 procedural Feature Chamfer GN Preview。
# source_object: source Mesh；radius/sample_length/voxel_size/adaptivity: GN 参数；show_cutter: 是否显示 cutter。
def ensure_gn_feature_chamfer_preview(
    source_object,
    radius,
    show_cutter=False,
):
    modifier = source_object.modifiers.get(FEATURE_CHAMFER_GN_MODIFIER)
    if modifier is not None and (
        modifier.type != "NODES"
        or modifier.get(FEATURE_CHAMFER_GN_OWNER_TAG) != OWNER_VALUE
    ):
        raise FeatureChamferPreviewError(
            f"Modifier 名称冲突：{FEATURE_CHAMFER_GN_MODIFIER}"
        )
    curve_object = None
    node_group = None
    created_modifier = False
    old_curve_object = owned_preview_curve(source_object)
    old_node_group = modifier.node_group if modifier is not None else None
    old_owned_boolean_groups = [
        node.node_tree
        for node in old_node_group.nodes
        if node.bl_idname == "GeometryNodeGroup"
        and node.node_tree is not None
        and node.node_tree.get(OWNED_BOOLEAN_PRO_TAG)
    ] if old_node_group is not None else []
    old_modifier_reference = modifier
    old_source_plan_properties = {
        property_name: source_object.get(property_name)
        for property_name in (PLAN_PROPERTY, PLAN_ID_PROPERTY)
        if property_name in source_object
    }
    old_modifier_plan_properties = {
        property_name: modifier.get(property_name)
        for property_name in (PLAN_PROPERTY, PLAN_ID_PROPERTY)
        if modifier is not None and property_name in modifier
    }
    try:
        curve_object, graph_stats, chamfer_plan = _rebuild_owned_preview_curve(
            source_object,
            radius,
        )
        node_group = _build_curve_preview_node_group(curve_object, radius, show_cutter)
        write_chamfer_plan(source_object, chamfer_plan)
        identifiers = _input_identifiers(node_group)
        values = {
            "Radius": radius,
            "Show Cutter": show_cutter,
        }
        missing = [name for name in values if name not in identifiers]
        if missing:
            raise FeatureChamferPreviewError(
                f"Preview 资产缺少 interface sockets：{', '.join(missing)}"
            )
        if modifier is None:
            modifier = source_object.modifiers.new(FEATURE_CHAMFER_GN_MODIFIER, "NODES")
            created_modifier = True
        modifier.node_group = node_group
        modifier.show_viewport = True
        modifier.show_render = True
        for name, value in values.items():
            modifier[identifiers[name]] = value
        write_chamfer_plan(modifier, chamfer_plan)
    except Exception:
        if created_modifier and modifier is not None:
            source_object.modifiers.remove(modifier)
        elif modifier is not None:
            modifier.node_group = old_node_group
        if node_group is not None and node_group.users == 0:
            owned_boolean_groups = [
                node.node_tree
                for node in node_group.nodes
                if node.bl_idname == "GeometryNodeGroup"
                and node.node_tree is not None
                and node.node_tree.get(OWNED_BOOLEAN_PRO_TAG)
            ]
            bpy.data.node_groups.remove(node_group)
            for boolean_group in owned_boolean_groups:
                if boolean_group.users == 0:
                    bpy.data.node_groups.remove(boolean_group)
        _remove_preview_curve_object(curve_object)
        if old_curve_object is not None:
            source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG] = old_curve_object.name
        elif FEATURE_CHAMFER_CURVE_OBJECT_TAG in source_object:
            del source_object[FEATURE_CHAMFER_CURVE_OBJECT_TAG]
        for property_name in (PLAN_PROPERTY, PLAN_ID_PROPERTY):
            if property_name in source_object:
                del source_object[property_name]
        for property_name, value in old_source_plan_properties.items():
            source_object[property_name] = value
        if old_modifier_reference is not None:
            for property_name in (PLAN_PROPERTY, PLAN_ID_PROPERTY):
                if property_name in old_modifier_reference:
                    del old_modifier_reference[property_name]
            for property_name, value in old_modifier_plan_properties.items():
                old_modifier_reference[property_name] = value
        raise
    if (
        old_node_group is not None
        and old_node_group.get("hst_feature_chamfer_preview_backend") == CURVE_PREVIEW_BACKEND
        and old_node_group.users == 0
    ):
        bpy.data.node_groups.remove(old_node_group)
        for boolean_group in old_owned_boolean_groups:
            if boolean_group.users == 0:
                bpy.data.node_groups.remove(boolean_group)
    if old_curve_object is not None and old_curve_object != curve_object:
        _remove_preview_curve_object(old_curve_object)
    parameters = live_preview_parameters(modifier)

    modifier[FEATURE_CHAMFER_GN_OWNER_TAG] = OWNER_VALUE
    modifier[FEATURE_CHAMFER_GN_FINGERPRINT_TAG] = source_fingerprint(source_object)
    modifier[FEATURE_CHAMFER_GN_ASSET_VERSION_TAG] = FEATURE_CHAMFER_GN_ASSET_VERSION
    modifier[FEATURE_CHAMFER_GN_PARAMETERS_TAG] = json.dumps(parameters, sort_keys=True)
    modifier[FEATURE_CHAMFER_GN_STATE_TAG] = PREVIEW_VALID
    modifier[FEATURE_CHAMFER_GN_LAST_ACTION_TAG] = "PREVIEW"
    source_object[FEATURE_CHAMFER_GN_STATE_TAG] = PREVIEW_VALID
    source_object[FEATURE_CHAMFER_GN_LAST_ACTION_TAG] = "PREVIEW"
    bpy.context.view_layer.update()
    return {
        "modifier": modifier,
        "node_group": node_group,
        "parameters": parameters,
        "state": PREVIEW_VALID,
        "curve_object": curve_object,
        "feature_graph": graph_stats,
        "plan": chamfer_plan,
    }


# 删除本工具拥有的 Preview modifier 与 source 状态 tags。
# source_object: Preview 所属 Mesh；返回是否实际删除了 modifier。
def cancel_gn_feature_chamfer_preview(source_object):
    modifier = owned_preview_modifier(source_object)
    removed = modifier is not None
    if modifier is not None:
        _remove_owned_preview_node_group(modifier)
        source_object.modifiers.remove(modifier)
    _remove_owned_preview_curve(source_object)
    for key in (
        FEATURE_CHAMFER_GN_STATE_TAG,
        FEATURE_CHAMFER_GN_LAST_ACTION_TAG,
        PLAN_PROPERTY,
        PLAN_ID_PROPERTY,
    ):
        if key in source_object:
            del source_object[key]
    return removed
