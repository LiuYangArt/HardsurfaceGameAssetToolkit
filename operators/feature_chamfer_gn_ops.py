# -*- coding: utf-8 -*-
"""一步式 Feature Chamfer Operator。"""

import json
import time

import bpy

from ..const import FEATURE_CHAMFER_GN_STATE_TAG
from ..const import FEATURE_CHAMFER_PATCHED
from ..const import FEATURE_CHAMFER_SOURCE_OBJECT_TAG
from ..utils.experimental_pipe_chamfer_utils import CHAMFER_FACE_ATTRIBUTE
from ..utils.feature_chamfer_diagnostic_utils import clear_feature_chamfer_diagnostics
from ..utils.feature_chamfer_diagnostic_utils import RADIUS_LIMIT_ERROR_CODES
from ..utils.feature_chamfer_diagnostic_utils import show_feature_chamfer_failure_diagnostic
from ..utils.feature_chamfer_direct_bridge_utils import FeatureChamferDirectBridgeError
from ..utils.feature_chamfer_direct_bridge_utils import build_direct_edge_loop_chamfer
from ..utils.feature_chamfer_gn_utils import FeatureChamferPreviewError
from ..utils.feature_chamfer_gn_utils import cancel_gn_feature_chamfer_preview
from ..utils.feature_chamfer_gn_utils import ensure_gn_feature_chamfer_preview
from ..utils.feature_chamfer_gn_utils import owned_preview_modifier
from ..utils.feature_chamfer_plan_utils import chamfer_plan_without_unsupported_regions
from ..utils.feature_chamfer_plan_utils import write_chamfer_plan
from ..utils.nodes_modifier_compat_utils import modifier_input_set


# 返回 source 是否有至少一条显式 sharp_edge。
# source_object: 待验证 Mesh Object。
def _has_sharp_edge(source_object):
    attribute = source_object.data.attributes.get("sharp_edge")
    return (
        attribute is not None
        and attribute.domain == "EDGE"
        and any(bool(item.value) for item in attribute.data)
    )


# 验证单个正式 Feature Chamfer source Object。
# operator/source_object: 当前 Operator 与待处理 Mesh Object；返回合法 source 或 None。
def _validated_source_object(operator, source_object):
    if source_object is None or source_object.type != "MESH":
        operator.report({"ERROR"}, "Select one or more Mesh Objects")
        return None
    if source_object.mode != "OBJECT":
        operator.report({"ERROR"}, "Feature Chamfer requires Object Mode")
        return None
    if any(abs(value - 1.0) > 1.0e-6 for value in source_object.scale):
        operator.report(
            {"ERROR"},
            f"Apply Object Scale before Feature Chamfer: {source_object.name}",
        )
        return None
    if not _has_sharp_edge(source_object):
        operator.report(
            {"ERROR"},
            f"Mesh has no explicit sharp_edge selection: {source_object.name}",
        )
        return None
    return source_object


# 从当前选择解析一批唯一 source，并保持 active source 优先的稳定顺序。
# operator/context: 当前 Blender Operator 与 Context；返回合法 source tuple 或 None。
def _validated_sources(operator, context):
    selected_meshes = [
        selected_object
        for selected_object in context.selected_objects
        if selected_object.type == "MESH"
    ]
    if not selected_meshes:
        operator.report({"ERROR"}, "Select one or more Mesh Objects")
        return None
    resolved_sources = []
    for selected_object in selected_meshes:
        source_name = selected_object.get(FEATURE_CHAMFER_SOURCE_OBJECT_TAG)
        source_object = (
            bpy.data.objects.get(source_name)
            if source_name
            else selected_object
        )
        if source_object is None or source_object.type != "MESH":
            operator.report(
                {"ERROR"},
                f"Feature Chamfer source Object no longer exists: {selected_object.name}",
            )
            return None
        if source_object not in resolved_sources:
            resolved_sources.append(source_object)
    active_object = context.active_object
    active_source_name = (
        active_object.get(FEATURE_CHAMFER_SOURCE_OBJECT_TAG)
        if active_object is not None
        else None
    )
    active_source = (
        bpy.data.objects.get(active_source_name)
        if active_source_name
        else active_object
    )
    if active_source in resolved_sources:
        resolved_sources.remove(active_source)
        resolved_sources.insert(0, active_source)
    for source_object in resolved_sources:
        if _validated_source_object(operator, source_object) is None:
            return None
    return tuple(resolved_sources)


# 从 Direct Bridge 输出建立正式 Chamfer 属性并写入 immutable plan。
# output/source_object/chamfer_plan: 输出 Object、原输入与本次计划；无返回值。
def _finalize_output(output, source_object, chamfer_plan):
    output.name = f"{source_object.name}_FeatureChamfer"
    chamfer_attribute = output.data.attributes.get("hst_feature_chamfer_face")
    if chamfer_attribute is not None:
        output.data.attributes.remove(chamfer_attribute)
    chamfer_attribute = output.data.attributes.new(
        "hst_feature_chamfer_face",
        type="BOOLEAN",
        domain="FACE",
    )
    backend_chamfer_attribute = output.data.attributes.get(CHAMFER_FACE_ATTRIBUTE)
    for polygon in output.data.polygons:
        chamfer_attribute.data[polygon.index].value = bool(
            backend_chamfer_attribute
            and backend_chamfer_attribute.data[polygon.index].value
        )
    face_weight_attribute = output.data.attributes.get(
        "__mod_weightednormals_faceweight"
    )
    if face_weight_attribute is not None:
        output.data.attributes.remove(face_weight_attribute)
    face_weight_attribute = output.data.attributes.new(
        "__mod_weightednormals_faceweight",
        type="INT",
        domain="FACE",
    )
    face_weight_attribute.data.foreach_set(
        "value",
        [
            0 if chamfer_attribute.data[polygon.index].value else 1
            for polygon in output.data.polygons
        ],
    )
    output.data.update()
    complete_plan = chamfer_plan_without_unsupported_regions(chamfer_plan)
    output[FEATURE_CHAMFER_GN_STATE_TAG] = FEATURE_CHAMFER_PATCHED
    output[FEATURE_CHAMFER_SOURCE_OBJECT_TAG] = source_object.name
    write_chamfer_plan(output, complete_plan)


# 把临时 Preview 当前显示的实际 Cutter 评估为独立 Mesh，供用户按需保留。
# source_object/transaction: 正式输入与本次事务持有的临时 ID；返回可见 Cutter Object。
def _keep_evaluated_cutter(source_object, transaction):
    modifier = owned_preview_modifier(source_object)
    if modifier is None or modifier.node_group is None:
        raise FeatureChamferPreviewError("Feature Chamfer temporary Preview is missing")
    identifiers = {
        item.name: item.identifier
        for item in modifier.node_group.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT"
    }
    show_cutter_identifier = identifiers.get("Show Cutter")
    if show_cutter_identifier is None:
        raise FeatureChamferPreviewError("Feature Chamfer Preview has no Show Cutter input")
    modifier_input_set(modifier, show_cutter_identifier, True)
    source_object.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    cutter_mesh = bpy.data.meshes.new_from_object(
        source_object.evaluated_get(depsgraph),
        depsgraph=depsgraph,
    )
    transaction["cutter_data"] = cutter_mesh
    cutter_object = bpy.data.objects.new(
        f"{source_object.name}_FeatureChamferCutter",
        cutter_mesh,
    )
    transaction["cutter"] = cutter_object
    source_object.users_collection[0].objects.link(cutter_object)
    cutter_object.matrix_world = source_object.matrix_world.copy()
    cutter_object.hide_set(False)
    cutter_object.hide_viewport = False
    cutter_object.hide_render = False
    cutter_object.show_in_front = True
    return cutter_object


# 在一次 Operator 事务内运行已验收的 Preview→Finalize 几何链，并移除临时 Preview 状态。
# source_object/radius/show_cutter/transaction: 正式输入、参数与事务引用；返回 Direct Bridge 统计。
def _build_preview_finalize_output(source_object, radius, show_cutter, transaction):
    preview_started_at = time.perf_counter()
    preview = ensure_gn_feature_chamfer_preview(
        source_object=source_object,
        radius=radius,
        show_cutter=False,
    )
    preview_seconds = time.perf_counter() - preview_started_at
    chamfer_plan = preview["plan"]
    feature_graph_stats = preview["feature_graph"]
    preview_node_group = preview["node_group"]
    pre_boolean_backend = preview_node_group.get(
        "hst_feature_chamfer_pre_boolean_backend"
    )
    pre_boolean_node_count = int(preview_node_group.get(
        "hst_feature_chamfer_pre_boolean_node_count",
        -1,
    ))
    pre_boolean_link_count = int(preview_node_group.get(
        "hst_feature_chamfer_pre_boolean_link_count",
        -1,
    ))
    pre_boolean_producer_seconds = float(preview_node_group.get(
        "hst_feature_chamfer_pre_boolean_producer_seconds",
        -1.0,
    ))
    boolean_seconds = float(preview_node_group.get(
        "hst_feature_chamfer_boolean_seconds",
        -1.0,
    ))
    post_boolean_backend = preview_node_group.get(
        "hst_feature_chamfer_post_boolean_backend"
    )
    post_boolean_materializer_seconds = float(preview_node_group.get(
        "hst_feature_chamfer_post_boolean_materializer_seconds",
        -1.0,
    ))
    post_boolean_dynamic_node_count = int(preview_node_group.get(
        "hst_feature_chamfer_post_boolean_dynamic_node_count",
        -1,
    ))
    bridge_fill_started_at = time.perf_counter()
    patch_stats = build_direct_edge_loop_chamfer(source_object, chamfer_plan)
    bridge_fill_seconds = time.perf_counter() - bridge_fill_started_at
    output = bpy.data.objects.get(patch_stats.get("output_object_name", ""))
    if output is None:
        raise FeatureChamferDirectBridgeError(
            "one_step_output_missing",
            "Feature Chamfer produced no output Object",
        )
    transaction["output"] = output
    cutter_object = None
    if show_cutter:
        cutter_object = _keep_evaluated_cutter(source_object, transaction)
    _finalize_output(output, source_object, chamfer_plan)
    cancel_gn_feature_chamfer_preview(source_object)
    patch_stats.update(
        backend="FIXED_BOOLEAN_PYTHON_IDENTITY_DIRECT_EDGE_LOOP_BRIDGE",
        runtime_path=(
            "FeatureGraph -> Python Mesh Attributes -> Fixed Boolean Boundary -> "
            "Python Identity -> Fixed Surface -> Blender Bridge/Fill"
        ),
        pre_boolean_backend=pre_boolean_backend,
        pre_boolean_node_count=pre_boolean_node_count,
        pre_boolean_link_count=pre_boolean_link_count,
        pre_boolean_producer_seconds=pre_boolean_producer_seconds,
        boolean_seconds=boolean_seconds,
        post_boolean_backend=post_boolean_backend,
        post_boolean_materializer_seconds=post_boolean_materializer_seconds,
        post_boolean_dynamic_node_count=post_boolean_dynamic_node_count,
        preview_seconds=preview_seconds,
        feature_graph_seconds=float(
            feature_graph_stats.get("feature_graph_seconds", -1.0)
        ),
        feature_graph_cache_hit=bool(
            feature_graph_stats.get("feature_graph_cache_hit", False)
        ),
        feature_graph_radius_independent=bool(
            feature_graph_stats.get("feature_graph_radius_independent", False)
        ),
        bridge_fill_seconds=bridge_fill_seconds,
        one_step_transaction=True,
        temporary_preview_removed=True,
        solver="FIXED_MANIFOLD_BOOLEAN",
        cutter_object_name=cutter_object.name if cutter_object is not None else None,
        keep_cutter_requested=bool(show_cutter),
        keep_cutter_supported=cutter_object is not None if show_cutter else True,
        source_hidden=True,
    )
    return patch_stats


# 删除无用户的临时 Mesh 或 Curve datablock。
# object_data: 本次事务创建的数据块；无返回值。
def _discard_orphan_object_data(object_data):
    if object_data is None or object_data.users != 0:
        return
    if isinstance(object_data, bpy.types.Mesh):
        if bpy.data.meshes.get(object_data.name) == object_data:
            bpy.data.meshes.remove(object_data)
    elif isinstance(object_data, bpy.types.Curve):
        if bpy.data.curves.get(object_data.name) == object_data:
            bpy.data.curves.remove(object_data)


# 删除本次事务产生的未发布结果与 Cutter，避免异常后留下伪成功对象。
# transaction: 持有 output、cutter 与可能尚未链接数据块的事务字典；无返回值。
def _discard_transaction_outputs(transaction):
    for object_key, data_key in (("cutter", "cutter_data"), ("output", None)):
        generated_object = transaction.get(object_key)
        object_data = transaction.get(data_key) if data_key is not None else None
        if (
            generated_object is not None
            and bpy.data.objects.get(generated_object.name) == generated_object
        ):
            object_data = generated_object.data
            bpy.data.objects.remove(generated_object, do_unlink=True)
        _discard_orphan_object_data(object_data)
        transaction[object_key] = None
        if data_key is not None:
            transaction[data_key] = None


# source_object: 返回 source 成功发布前的可见性快照。
def _source_visibility_state(source_object):
    return {
        "hide_set": source_object.hide_get(),
        "hide_viewport": source_object.hide_viewport,
        "hide_render": source_object.hide_render,
    }


# source_object/state: 恢复 source 的 viewport/render 可见性；无返回值。
def _restore_source_visibility(source_object, state):
    source_object.hide_set(bool(state["hide_set"]))
    source_object.hide_viewport = bool(state["hide_viewport"])
    source_object.hide_render = bool(state["hide_render"])


# source_object: 成功后从 viewport 与 render 中隐藏 source；无返回值。
def _hide_source(source_object):
    source_object.select_set(False)
    source_object.hide_set(True)
    source_object.hide_viewport = True
    source_object.hide_render = True


# transactions: 回滚整批未发布结果并恢复全部 source 可见性；无返回值。
def _rollback_batch(transactions):
    for transaction in reversed(transactions):
        _discard_transaction_outputs(transaction)
        source_object = transaction["source"]
        cancel_gn_feature_chamfer_preview(source_object)
        _restore_source_visibility(source_object, transaction["source_visibility"])


class HST_OT_FeatureChamferGN(bpy.types.Operator):
    """一次执行并直接生成最终 Feature Chamfer Mesh"""

    bl_idname = "hst.feature_chamfer_gn"
    bl_label = "Feature Chamfer"
    bl_description = "Create the final Feature Chamfer result in one operation"
    bl_options = {"REGISTER", "UNDO"}

    source_object_name: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    source_object_names: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    radius: bpy.props.FloatProperty(name="Radius", default=0.03, min=1.0e-5)
    show_cutter: bpy.props.BoolProperty(name="Keep Cutter", default=False)

    def invoke(self, context, event):
        del event
        source_objects = _validated_sources(self, context)
        if source_objects is None:
            return {"CANCELLED"}
        self.source_object_name = source_objects[0].name
        self.source_object_names = json.dumps(
            [source_object.name for source_object in source_objects],
            ensure_ascii=False,
        )
        return self.execute(context)

    def execute(self, context):
        stored_names = []
        if self.source_object_names:
            try:
                stored_names = json.loads(self.source_object_names)
            except (TypeError, ValueError, json.JSONDecodeError):
                stored_names = []
        if not stored_names and self.source_object_name:
            stored_names = [self.source_object_name]
        source_objects = tuple(
            source_object
            for source_name in stored_names
            if (source_object := bpy.data.objects.get(source_name)) is not None
        )
        if len(source_objects) != len(stored_names) or not source_objects:
            source_objects = _validated_sources(self, context)
        if source_objects is None:
            return {"CANCELLED"}
        started_at = time.perf_counter()
        transactions = []
        try:
            results = []
            for source_object in source_objects:
                transaction = {
                    "source": source_object,
                    "source_visibility": _source_visibility_state(source_object),
                    "output": None,
                    "cutter": None,
                    "cutter_data": None,
                }
                transactions.append(transaction)
                clear_feature_chamfer_diagnostics(source_object)
                patch_stats = _build_preview_finalize_output(
                    source_object,
                    self.radius,
                    self.show_cutter,
                    transaction,
                )
                results.append(patch_stats)
            total_seconds = time.perf_counter() - started_at
            outputs = [transaction["output"] for transaction in transactions]
            for source_object in source_objects:
                _hide_source(source_object)
            batch_stats = {
                "status": "finished",
                "source_object_count": len(source_objects),
                "output_object_names": [output.name for output in outputs],
                "total_seconds": total_seconds,
                "results": results,
            }
            if len(results) == 1:
                batch_stats.update(results[0])
                batch_stats["total_seconds"] = total_seconds
            context.scene["hst_pipe_chamfer_last_result"] = json.dumps(
                batch_stats,
                ensure_ascii=False,
                default=str,
            )
            for selected_object in tuple(context.selected_objects):
                selected_object.select_set(False)
            for output in outputs:
                output.hide_set(False)
                output.hide_viewport = False
                output.hide_render = False
                output.select_set(True)
            context.view_layer.objects.active = outputs[0]
            self.report(
                {"INFO"},
                (
                    f"Feature Chamfer finished {len(outputs)} object(s) "
                    f"in {total_seconds:.2f}s"
                ),
            )
            return {"FINISHED"}
        except FeatureChamferDirectBridgeError as error:
            failed_source = transactions[-1]["source"]
            _rollback_batch(transactions)
            diagnostic = show_feature_chamfer_failure_diagnostic(
                failed_source,
                error.error_code,
                error.stats,
                self.radius,
            )
            error.stats.update(
                requested_radius=float(self.radius),
                final_state="SOURCE_UNCHANGED",
                diagnostic=diagnostic,
            )
            context.scene["hst_pipe_chamfer_last_result"] = json.dumps(
                error.stats,
                ensure_ascii=False,
                default=str,
            )
            if error.error_code in RADIUS_LIMIT_ERROR_CODES and diagnostic["exists"]:
                self.report(
                    {"WARNING"},
                    f"Feature Chamfer cannot fill the marked area at Radius {self.radius:.4f}",
                )
            else:
                self.report({"WARNING"}, f"Feature Chamfer failed [{error.error_code}]: {error}")
            return {"FINISHED"} if diagnostic["exists"] else {"CANCELLED"}
        except FeatureChamferPreviewError as error:
            _rollback_batch(transactions)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except Exception:
            _rollback_batch(transactions)
            raise

    def draw(self, context):
        del context
        layout = self.layout
        layout.prop(self, "radius")
        layout.prop(self, "show_cutter")
