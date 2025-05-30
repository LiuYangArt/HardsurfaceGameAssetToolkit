import bpy

class EXAMPLE_OT_DefaultIntOperator(bpy.types.Operator):
    bl_idname = "hst.redo_operator"
    bl_label = "Example Redo Operator"
    bl_options = {'REGISTER', 'UNDO'}

    # my_prop: bpy.props.IntProperty(name = "My Property")
    origin_mode: bpy.props.EnumProperty(
        name="Origin Mode",
        description="选择Origin的位置",
        items=[
            ("WORLD_CENTER", "世界中心", "使用世界中心作为Origin"),
            ("COLLECTION_CENTER", "Collection中心", "使用Collection所有对象Pivots的中心"),
            ("COLLECTION_BOTTOM", "Collection底部", "使用Collection所有对象的底部中心"),
            ("ACTIVE_OBJECT", "Active Object中心", "使用当前激活物体的位置"),
            ("CURSOR", "3D光标位置", "使用3D光标位置"),
        ],
        default="COLLECTION_CENTER",
    )

    def execute(self, context):
        if self.origin_mode == "WORLD_CENTER":
            origin_location = "wcenter"
        elif self.origin_mode == "COLLECTION_CENTER":
            origin_location = "center"
        elif self.origin_mode == "COLLECTION_BOTTOM":
                origin_location = "Vector((center_xy.x, center_xy.y, lowest_z))"
                origin_location = "Vector((0, 0, 0))"
        elif self.origin_mode == "ACTIVE_OBJECT":
            origin_location = "active_object.location.copy()"
        elif self.origin_mode == "CURSOR":
            origin_location = bpy.context.scene.cursor.location.copy()

        print("origin_location: ", origin_location)
        # self.report({'INFO'}, f"my_prop: {self.origin_mode}")
        return {'FINISHED'}