# -*- coding: utf-8 -*-
"""管理 Feature Chamfer 安全失败时的可见问题边界。"""

import bpy

from ..const import FEATURE_CHAMFER_DIAGNOSTIC_ERROR_TAG
from ..const import FEATURE_CHAMFER_DIAGNOSTIC_OWNER_TAG
from ..const import FEATURE_CHAMFER_DIAGNOSTIC_RADIUS_TAG


DIAGNOSTIC_COLOR = (1.0, 0.08, 0.03, 1.0)
RADIUS_LIMIT_ERROR_CODES = {
    "bridge_faces_self_intersect",
    "final_geometry_self_intersects",
    "junction_fill_self_intersects",
}


# 返回指定 source 拥有的全部失败诊断 Object。
# source_object: Feature Chamfer source Mesh；返回 Object tuple。
def owned_feature_chamfer_diagnostics(source_object):
    return tuple(
        scene_object
        for scene_object in bpy.data.objects
        if scene_object.get(FEATURE_CHAMFER_DIAGNOSTIC_OWNER_TAG)
        == source_object.name
    )


# 删除 source 的旧失败诊断及其无用户 Curve/Material 数据。
# source_object: Feature Chamfer source Mesh；返回删除的 Object 数量。
def clear_feature_chamfer_diagnostics(source_object):
    diagnostic_objects = owned_feature_chamfer_diagnostics(source_object)
    for diagnostic_object in diagnostic_objects:
        curve_data = diagnostic_object.data
        materials = tuple(curve_data.materials) if hasattr(curve_data, "materials") else ()
        bpy.data.objects.remove(diagnostic_object, do_unlink=True)
        if curve_data.users == 0:
            bpy.data.curves.remove(curve_data)
        for material in materials:
            if material is not None and material.users == 0:
                bpy.data.materials.remove(material)
    return len(diagnostic_objects)


# 在真实失败坐标上创建红色粗线，复用项目 Edge 可视化的视觉约定。
# source_object/error_code/stats/radius: source、稳定错误码、后端诊断与请求半径；返回诊断摘要。
def show_feature_chamfer_failure_diagnostic(
    source_object,
    error_code,
    stats,
    radius,
):
    clear_feature_chamfer_diagnostics(source_object)
    coordinates = stats.get("coordinates", ())
    if not coordinates:
        intersections = stats.get("self_intersections", ())
        coordinates = tuple(
            intersection.get("first_center")
            for intersection in intersections
            if intersection.get("first_center") is not None
        ) + tuple(
            intersection.get("second_center")
            for intersection in intersections
            if intersection.get("second_center") is not None
        )
    cyclic = bool(stats.get("diagnostic_cyclic", True))
    if error_code not in RADIUS_LIMIT_ERROR_CODES or len(coordinates) < 2:
        return {
            "exists": False,
            "reason": "error_has_no_radius_limit_boundary",
        }

    object_name = f"{source_object.name}_FeatureChamferIssue"
    curve_data = bpy.data.curves.new(f"{object_name}_Curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 2
    curve_data.bevel_depth = max(float(radius) * 0.14, 0.0035)
    curve_data.bevel_resolution = 4
    spline = curve_data.splines.new(type="POLY")
    spline.points.add(len(coordinates) - 1)
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = cyclic and len(coordinates) >= 3

    material = bpy.data.materials.new(f"{object_name}_Material")
    material.diffuse_color = DIAGNOSTIC_COLOR
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = DIAGNOSTIC_COLOR
    principled.inputs["Emission Color"].default_value = DIAGNOSTIC_COLOR
    principled.inputs["Emission Strength"].default_value = 2.0
    curve_data.materials.append(material)

    diagnostic_object = bpy.data.objects.new(object_name, curve_data)
    diagnostic_object.matrix_world = source_object.matrix_world.copy()
    diagnostic_object.show_in_front = True
    diagnostic_object[FEATURE_CHAMFER_DIAGNOSTIC_OWNER_TAG] = source_object.name
    diagnostic_object[FEATURE_CHAMFER_DIAGNOSTIC_ERROR_TAG] = error_code
    diagnostic_object[FEATURE_CHAMFER_DIAGNOSTIC_RADIUS_TAG] = float(radius)
    target_collection = (
        source_object.users_collection[0]
        if source_object.users_collection
        else bpy.context.scene.collection
    )
    target_collection.objects.link(diagnostic_object)
    bpy.context.view_layer.update()
    return {
        "exists": True,
        "object_name": diagnostic_object.name,
        "point_count": len(coordinates),
        "cyclic": cyclic,
        "show_in_front": True,
        "color": list(DIAGNOSTIC_COLOR),
        "error_code": error_code,
        "radius": float(radius),
    }
