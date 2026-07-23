# -*- coding: utf-8 -*-
"""隐藏的 Feature Chamfer batched backend 阶段验收 Adapter。"""

import json

import bpy

from ..utils.feature_chamfer_batched_finalize_utils import BatchedChamferError
from ..utils.feature_chamfer_batched_finalize_utils import DEBUG_PHASE_A
from ..utils.feature_chamfer_batched_finalize_utils import DEBUG_PHASE_B
from ..utils.feature_chamfer_batched_finalize_utils import DEBUG_PHASE_C
from ..utils.feature_chamfer_batched_finalize_utils import build_batched_feature_chamfer
from ..utils.feature_chamfer_gn_utils import PREVIEW_VALID
from ..utils.feature_chamfer_gn_utils import live_preview_parameters
from ..utils.feature_chamfer_gn_utils import owned_preview_modifier
from ..utils.feature_chamfer_gn_utils import preview_state
from ..utils.feature_chamfer_plan_utils import read_chamfer_plan


class HST_OT_ExperimentalFeatureChamferBatchedFinalize(bpy.types.Operator):
    """从当前有效 Preview 运行 batched backend 阶段性 probe"""

    bl_idname = "hst.experimental_feature_chamfer_batched_finalize"
    bl_label = "Experimental Feature Chamfer Batched Finalize"
    bl_options = {"INTERNAL"}

    debug_stage: bpy.props.EnumProperty(
        items=(
            (DEBUG_PHASE_A, "Phase A Input Contract", "验证正式 Preview Pipe 输入合同"),
            (DEBUG_PHASE_B, "Phase B Batch Probe", "验证 overlap graph 与 batch order"),
            (DEBUG_PHASE_C, "Phase C Regular Core", "验证 owner Rail、setback 与 consumption ledger"),
        ),
        default=DEBUG_PHASE_B,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def invoke(self, context, event):
        del event
        source_object = context.active_object
        if source_object is None or source_object.type != "MESH":
            self.report({"ERROR"}, "Select one Mesh source Object")
            return {"CANCELLED"}
        if source_object.mode != "OBJECT":
            self.report({"ERROR"}, "Object Mode is required")
            return {"CANCELLED"}
        if len(context.selected_objects) != 1:
            self.report({"ERROR"}, "Select exactly one Mesh source Object")
            return {"CANCELLED"}
        if preview_state(source_object) != PREVIEW_VALID:
            self.report({"ERROR"}, "Run Feature Chamfer GN Preview first")
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        source_object = context.active_object
        preview_modifier = owned_preview_modifier(source_object)
        preview_plan = read_chamfer_plan(preview_modifier)
        preview_parameters = live_preview_parameters(preview_modifier)
        try:
            result = build_batched_feature_chamfer(
                source_object,
                preview_plan,
                preview_parameters,
                self.debug_stage,
            )
        except BatchedChamferError as error:
            failure_diagnostics = {
                "status": "FAILED",
                "failure_code": error.error_code,
                "message": str(error),
                "diagnostics": error.diagnostics,
                "topology_diagnostics": error.diagnostics,
            }
            context.scene["hst_feature_chamfer_batched_last_result"] = json.dumps(
                failure_diagnostics,
                ensure_ascii=False,
                sort_keys=True,
            )
            self.report({"WARNING"}, f"Batched probe failed [{error.error_code}]: {error}")
            return {"CANCELLED"}
        context.scene["hst_feature_chamfer_batched_last_result"] = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.report(
            {"INFO"},
            f"Batched probe: {len(result.pipe_specs)} Pipes / {len(result.color_batches)} batches",
        )
        return {"FINISHED"}
