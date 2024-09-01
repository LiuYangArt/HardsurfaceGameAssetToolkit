import bpy
from .Const import *
from .Functions.HSTFunctions import *
from .Functions.CommonFunctions import *


class ProjectDecalOperator(bpy.types.Operator):
    bl_idname = "hst.projectdecal"
    bl_label = "Project Decal"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object=bpy.context.active_object
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        

        decal_objects=Object.filter_hst_type(selected_objects,type="DECAL",mode="INCLUDE")

        selected_meshes = filter_type(selected_objects, "MESH")
        print(f"decal_objects: {decal_objects}")
        print(f"active_object: {active_object}")
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Decal Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        if active_object in decal_objects:
            self.report(
                {"ERROR"},
                "Active Object is decal object, operation cancelled | \n"
                + "最后选中的Object为Decal Object，操作取消",
            )
            return {"CANCELLED"}
        
        for object in decal_objects:
            add_subd_modifier(object)
            add_shrinkwrap_modifier(object,active_object)

        self.report({"INFO"},f"{len(decal_objects)} Decal Projected")
        return {'FINISHED'}


        

        return {'FINISHED'}



