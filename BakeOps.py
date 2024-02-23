import bpy

from .Const import *
from .Functions.BTMFunctions import *
from .Functions.CommonFunctions import *


def set_bake_collection(collection, type="LOW"):
    """Set bake collection name and color tag,rename meshes in collection,types:LOW,HIGH"""
    result = False
    objects = collection.all_objects

    collection_name = (
        collection.name.replace(".", "").split(LOW_SUFFIX)[0].split(HIGH_SUFFIX)[0]
    )

    match type:
        case "LOW":
            new_name = collection_name + LOW_SUFFIX
            color = LOW_COLOR
        case "HIGH":
            new_name = collection_name + HIGH_SUFFIX
            color = HIGH_COLOR

    collection.name = new_name
    collection.color_tag = color
    rename_meshes(objects, new_name)

    return result


class SetBakeCollectionLowOperator(bpy.types.Operator):
    bl_idname = "object.setbakecollectionlow"
    bl_label = "SetBakeCollectionLow"
    bl_description = (
        "设置选中模型的整个Collection为LowPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):
        active_object = bpy.context.active_object
        collection = get_collection(active_object)

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if (
            collection.name == TRANSFER_PROXY_COLLECTION
            or collection.name == TRANSFER_COLLECTION
        ):
            message_box(
                "Selected collection is TransferProxy collection, please select other collections | "
                + "所选Collection是Transfer Collection，请选择其他Collection"
            )
            return {"CANCELLED"}

        set_bake_collection(collection, type="LOW")

        self.report({"INFO"}, "Set bake collection to low poly")
        return {"FINISHED"}


class SetBakeCollectionHighOperator(bpy.types.Operator):
    bl_idname = "object.setbakecollectionhigh"
    bl_label = "SetBakeCollectionHigh"
    bl_description = (
        "设置选中模型的整个Collection为HighPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):
        active_object = bpy.context.active_object
        collection = get_collection(active_object)

        if collection is None:
            message_box(
                "Not in collection, please put selected objects in collections and retry | "
                + "所选物体需要在Collections中"
            )
            return {"CANCELLED"}

        if (
            collection.name == TRANSFER_PROXY_COLLECTION
            or collection.name == TRANSFER_COLLECTION
        ):
            message_box(
                "Selected collection is TransferProxy collection, please select other collections | "
                + "所选Collection是Transfer Collection，请选择其他Collection"
            )
            return {"CANCELLED"}

        set_bake_collection(collection, type="HIGH")

        self.report({"INFO"}, "Set bake collection to high poly")
        return {"FINISHED"}


class SetObjectVertexColorOperator(bpy.types.Operator):
    bl_idname = "object.setobjectvertexcolor"
    bl_label = "SetObjectVertexColor"
    bl_description = "设置选中模型的顶点色,顶点色名字为BakeColor\
        用于烘焙贴图时的ColorID"

    def execute(self, context):
        parameters = context.scene.hst_params
        vertex_color = parameters.bake_color
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        color = get_color_data(vertex_color)

        if len(selected_meshes) == 0:
            message_box("No mesh selected | 未选择Mesh")
            return {"CANCELLED"}

        for mesh in selected_meshes:
            add_vertexcolor_attribute(mesh, BAKECOLOR_ATTR)
            set_active_color_attribute(mesh, BAKECOLOR_ATTR)
            set_object_vertexcolor(mesh, color, BAKECOLOR_ATTR)

        self.report({"INFO"}, "Set vertex color")
        return {"FINISHED"}
