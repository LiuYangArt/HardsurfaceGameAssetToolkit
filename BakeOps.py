import bpy

from .Const import *
from .Functions.CommonFunctions import *


def set_bake_collection(collection, type="LOW"):
    """Set bake collection name and color tag,rename meshes in collection,types:LOW,HIGH"""
    result = False
    objects = collection.all_objects

    collection_name = clean_collection_name(collection.name)

    match type:
        case "LOW":
            new_name = collection_name + LOW_SUFFIX
            color = "COLOR_" + LOW_COLLECTION_COLOR
        case "HIGH":
            new_name = collection_name + HIGH_SUFFIX
            color = "COLOR_" + HIGH_COLLECTION_COLOR

    collection.name = new_name
    collection.color_tag = color
    rename_meshes(objects, new_name)

    return result


class SetBakeCollectionLowOperator(bpy.types.Operator):
    bl_idname = "hst.setbakecollectionlow"
    bl_label = "HST Set Bake-Collection Low"
    bl_description = (
        "设置选中模型的整个Collection为LowPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        bake_collections = filter_collections_selection(selected_objects)
        if len(bake_collections) == 0:
            message_box(
                "No selected collection, please select collections and retry | "
                + "没有选中Collection，请选中Collection后重试"
            )
            return {"CANCELLED"}
        
        for collection in bake_collections:
            set_bake_collection(collection, type="LOW")

        self.report({"INFO"}, "Set bake collection to low poly")
        return {"FINISHED"}


class SetBakeCollectionHighOperator(bpy.types.Operator):
    bl_idname = "hst.setbakecollectionhigh"
    bl_label = "HST Set Bake-Collection High"
    bl_description = (
        "设置选中模型的整个Collection为HighPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        bake_collections = filter_collections_selection(selected_objects)
        if len(bake_collections) == 0:
            message_box(
                "No selected collection, please select collections and retry | "
                + "没有选中Collection，请选中Collection后重试"
            )
            return {"CANCELLED"}
        
        for collection in bake_collections:
            set_bake_collection(collection, type="HIGH")

        self.report({"INFO"}, "Set bake collection to high poly")
        return {"FINISHED"}


class SetObjectVertexColorOperator(bpy.types.Operator):
    bl_idname = "hst.setobjectvertexcolor"
    bl_label = "Batch Set Object VertexColor"
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