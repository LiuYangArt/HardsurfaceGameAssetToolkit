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
            Collection.mark_hst_type(collection, "LOW")
            Object.mark_hst_type(objects, "LOW")
        case "HIGH":
            new_name = collection_name + HIGH_SUFFIX
            Collection.mark_hst_type(collection, "HIGH")
            Object.mark_hst_type(objects, "HIGH")

    collection.name = new_name

    rename_prop_meshes(objects)

    return result


class SetBakeCollectionLowOperator(bpy.types.Operator):
    bl_idname = "hst.setbakecollectionlow"
    bl_label = "HST Set Bake-Collection Low"
    bl_description = (
        "设置选中模型的整个Collection为LowPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):

        bake_collections = Collection.get_selected()
        if len(bake_collections) == 0:
            message_box(
                "No selected collection, please select collections and retry | "
                + "没有选中Collection，请选中Collection后重试"
            )
            return {"CANCELLED"}
        
        for collection in bake_collections:
            set_bake_collection(collection, type="LOW")

            static_meshes,ucx_meshes = filter_static_meshes(collection)
            if len(ucx_meshes) > 0:
                self.report({"ERROR"}, collection.name + " has UCX mesh, please check | "
                            + "collection内有UCX Mesh，请检查")

        self.report({"INFO"}, "Set bake collection to low poly")
        return {"FINISHED"}


class SetBakeCollectionHighOperator(bpy.types.Operator):
    bl_idname = "hst.setbakecollectionhigh"
    bl_label = "HST Set Bake-Collection High"
    bl_description = (
        "设置选中模型的整个Collection为HighPoly组，根据Collection名字修改命名"
    )

    def execute(self, context):

        bake_collections = Collection.get_selected()
        if len(bake_collections) == 0:
            message_box(
                "No selected collection, please select collections and retry | "
                + "没有选中Collection，请选中Collection后重试"
            )
            return {"CANCELLED"}
        
        for collection in bake_collections:
            set_bake_collection(collection, type="HIGH")
            static_meshes,ucx_meshes = filter_static_meshes(collection)
            if len(ucx_meshes) > 0:
                self.report({"ERROR"}, collection.name + " has UCX mesh, please check | "
                            + "collection内有UCX Mesh，请检查")

        self.report({"INFO"}, "Set bake collection to high poly")
        return {"FINISHED"}


class SetObjectVertexColorOperator(bpy.types.Operator):
    bl_idname = "hst.setobjectvertexcolor"
    bl_label = "Batch Set Object VertexColor"
    bl_description = "设置选中模型的顶点色,顶点色名字为BakeColor\
        用于烘焙贴图时的ColorID"

    def execute(self, context):
        parameters = context.scene.hst_params
        color = parameters.vertexcolor
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        color = get_color_data(color)

        if len(selected_meshes) == 0:
            message_box("No mesh selected | 未选择Mesh")
            return {"CANCELLED"}

        
        for mesh in selected_meshes:
            vertex_color_layer=check_vertex_color(mesh)
            if vertex_color_layer:
                # print("has vc")
                set_active_color_attribute(mesh, vertex_color_layer.name)
                set_object_vertexcolor(mesh, color, vertex_color_layer.name)
            else:
                add_vertexcolor_attribute(mesh, BAKECOLOR_ATTR)
                set_active_color_attribute(mesh, BAKECOLOR_ATTR)
                set_object_vertexcolor(mesh, color, BAKECOLOR_ATTR)

        self.report({"INFO"}, "Set vertex color")
        return {"FINISHED"}

# class SetVertexColorAlphaOperator(bpy.types.Operator):
#     bl_idname = "hst.set_vertexcolor_alpha"
#     bl_label = "Batch Set Object VertexColor Alpha Channel"
#     bl_description = "设置选中模型的顶点色,顶点色名字为BakeColor\
#         用于烘焙贴图时的ColorID"

#     def execute(self, context):
#         parameters = context.scene.hst_params
#         color = parameters.vertexcolor
#         selected_objects = bpy.context.selected_objects
#         selected_meshes = filter_type(selected_objects, "MESH")
#         color = get_color_data(color)

#         if len(selected_meshes) == 0:
#             message_box("No mesh selected | 未选择Mesh")
#             return {"CANCELLED"}

        
#         for mesh in selected_meshes:
#             vertex_color_layer=check_vertex_color(mesh)
#             if vertex_color_layer:
#                 # print("has vc")
#                 set_active_color_attribute(mesh, vertex_color_layer.name)
#                 # set_object_vertexcolor(mesh, color, vertex_color_layer.name)
#                 VertexColor.set_alpha(mesh=mesh,alpha_value=0.1,vertexcolor_name=vertex_color_layer.name)
#                 # VertexColor.set_vertexcolor_alpha(mesh, color_mode="BLACK", vertexcolor_name=vertex_color_layer.name)
#             else:
#                 add_vertexcolor_attribute(mesh, BAKECOLOR_ATTR)
#                 set_active_color_attribute(mesh, BAKECOLOR_ATTR)
#                 VertexColor.set_vertexcolor_alpha(mesh, color_mode="BLACK", vertexcolor_name=BAKECOLOR_ATTR)
#                 # set_object_vertexcolor(mesh, color, BAKECOLOR_ATTR)

#         self.report({"INFO"}, "Set vertex color")
#         return {"FINISHED"}