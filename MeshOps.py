import bpy
from .Const import *
from .Functions.CommonFunctions import *


class PrepSpaceClaimCADMeshOperator(bpy.types.Operator):
    bl_idname = "object.prepspaceclaimcadmesh"
    bl_label = "CleanupSpaceClaimCADMesh"
    bl_description = "初始化导入的CAD模型fbx，清理孤立顶点，UV初始化\
        如果模型的面是分开的请先使用FixSpaceClaimObj工具修理"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")
        for object in selected_objects:
            object.select_set(False)

        for mesh in selected_meshes:
            mesh.select_set(True)
            clean_mid_verts(mesh)
            clean_loose_verts(mesh)

            has_uv = has_uv_attribute(mesh)  # 处理uv layers
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

            for edge in mesh.data.edges:  # 从锐边生成UV Seam
                edge.use_seam = True if edge.use_edge_sharp else False

        # uv unwrap
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.unwrap(
            method="CONFORMAL", fill_holes=True, correct_aspect=True, margin=0.005
        )
        bpy.ops.object.mode_set(mode="OBJECT")

        self.report({"INFO"}, "Selected meshes prepped")
        return {"FINISHED"}


class MakeSwatchUVOperator(bpy.types.Operator):
    bl_idname = "object.makeswatchuv"
    bl_label = "MakeSwatchUV"
    bl_description = "为CAD模型添加Swatch UV"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        for mesh in selected_meshes:
            mesh.select_set(True)
            uv_swatch = add_uv_layers(mesh, uv_name=UV_SWATCH)
            uv_swatch.active = True
            scale_uv(uv_layer=uv_swatch, scale=(0.001, 0.001), pivot=(0.5, 0.5))

        self.report({"INFO"}, "Swatch UV added")
        return {"FINISHED"}


class CleanVertexOperator(bpy.types.Operator):
    bl_idname = "object.cleanvert"
    bl_label = "clean vert"
    bl_description = "清理模型中的孤立顶点"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        for mesh in selected_meshes:
            clean_mid_verts(mesh)
            clean_loose_verts(mesh)

        self.report({"INFO"}, "Selected meshes cleaned")
        return {"FINISHED"}


class FixSpaceClaimObjOperator(bpy.types.Operator):
    bl_idname = "object.fixspaceclaimobj"
    bl_label = "FixSpaceClaimObj"
    bl_description = "修理spaceclaim输出的obj"

    def execute(self, context):
        SHARP_ANGLE = 0.08
        MERGE_DISTANCE = 0.01
        DISSOLVE_ANGLE = 0.00174533
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")
        # 清理multi user
        for object in selected_objects:
            clean_user(object)
            object.select_set(False)
        for mesh in selected_meshes:
            merge_vertes_by_distance(mesh, merge_distance=MERGE_DISTANCE)
            mark_sharp_edge_by_angle(mesh, sharp_angle=SHARP_ANGLE)
            mesh.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.dissolve_limited(angle_limit=DISSOLVE_ANGLE)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, "Selected meshes fixed")
        return {"FINISHED"}


class SeparateMultiUserOperator(bpy.types.Operator):
    bl_idname = "object.sepmultiuser"
    bl_label = "SeparateMultiUser"
    bl_description = "清理多用户，可用于AssetLibrary导入资产去除引用，\
        可能会造成冗余资源，请及时清除"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            message_box(
                "No selected object, please select objects and retry | "
                + "没有选中物体，请选中物体后重试"
            )
            return {"CANCELLED"}
        for object in selected_objects:
            clean_user(object)
            self.report({"INFO"}, "Multi user separated")
        return {"FINISHED"}


class AddSnapSocketOperator(bpy.types.Operator):
    bl_idname = "object.addsnapsocket"
    bl_label = "Add Snap Socket"
    bl_description = "添加用于UE Modular Snap System的Socket，\
        在编辑模式下使用时，先选中用于Snap的面，会自动创建朝向正确的Socket"

    def execute(self, context):

        cursor = bpy.context.scene.cursor
        cursor_current_transform = cursor.matrix
        selected_objects = bpy.context.selected_objects
        collection = selected_objects[0].users_collection[0]
        parameters = context.scene.hst_params
        SOCKET_SIZE = 0.3
        IN_FRONT = False

        if bpy.context.mode == "EDIT_MESH":
            self.report({"INFO"}, "In edit mode, create socket from selected faces")
            rotation = get_selected_rotation_quat()
            rotation = rotate_quaternion(rotation, -90, "Y")
            bpy.ops.view3d.snap_cursor_to_selected()
            bpy.context.scene.cursor.rotation_mode = "QUATERNION"
            bpy.context.scene.cursor.rotation_quaternion = rotation
            bpy.ops.object.mode_set(mode="OBJECT")
        else:
            bpy.ops.view3d.snap_cursor_to_selected()
            rotation = cursor.rotation_quaternion
            rotation = rotate_quaternion(rotation, 90, "Y")
            bpy.context.scene.cursor.rotation_mode = "QUATERNION"
            bpy.context.scene.cursor.rotation_quaternion = rotation
            self.report({"INFO"}, "In object mode, create socket from selected objects")
        # add empty, set name to SOCKET_XXX and location to cursor location
        socket_object = bpy.data.objects.new(
            name="SOCKET_" + parameters.socket_name, object_data=None
        )
        socket_object.location = cursor.location
        socket_object.rotation_mode = "QUATERNION"
        socket_object.rotation_quaternion = cursor.rotation_quaternion
        socket_object.empty_display_type = "ARROWS"
        socket_object.empty_display_size = SOCKET_SIZE
        socket_object.show_in_front = IN_FRONT
        collection.objects.link(socket_object)

        bpy.context.scene.cursor.matrix = cursor_current_transform

        return {"FINISHED"}


class SwatchMatSetupOperator(bpy.types.Operator):
    bl_idname = "object.swatchmatsetup"
    bl_label = "SwatchEditMode"
    bl_description = "设置Swatch材质的编辑环境"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        for object in selected_objects:
            # clean_user(object)
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL",0.4)
            uv_editor.ui_type = "UV"
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        scene_swatch_mat = get_scene_material(SWATCH_MATERIAL)
        if scene_swatch_mat is None:  # import material if not exist
            scene_swatch_mat = import_material(PRESET_FILE_PATH, SWATCH_MATERIAL)

        for mesh in selected_meshes:
            mesh.select_set(True)
            swatch_uv = check_uv_layer(mesh, UV_SWATCH)
            if swatch_uv is None:  # add uv layer if not exist
                swatch_uv = add_uv_layers(mesh, uv_name=UV_SWATCH)
                # swatch_uv.active = True
                scale_uv(uv_layer=swatch_uv, scale=(0.001, 0.001), pivot=(0.5, 0.5))
            swatch_uv.active = True

            swatch_mat = get_object_material(mesh, SWATCH_MATERIAL)
            mat_slot=get_object_material_slots(mesh)
            if swatch_mat is None:
                if len(mat_slot)==0:  # add material if not exist
                    mesh.data.materials.append(scene_swatch_mat)
                elif len(mat_slot)>0:
                    mat_slot[0].material=scene_swatch_mat

        for subnode in scene_swatch_mat.node_tree.nodes:  # find swatch texture
            if subnode.type == "GROUP":
                for nodegroup in subnode.node_tree.nodes:
                    if nodegroup.type == "TEX_IMAGE":
                        swatch_texture = nodegroup.image
                        break

        # setup uv editor
        uv_space.image = swatch_texture
        uv_space.display_channels = "COLOR"
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True

        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        viewport_shading_mode("VIEW_3D", "RENDERED", mode="CONTEXT")
        self.report({"INFO"}, "Swatch material initialized")

        return {"FINISHED"}


class BaseUVEditModeOperator(bpy.types.Operator):
    bl_idname = "object.baseuveditmode"
    bl_label = "BaseUVEditMode"
    bl_description = "Base UV编辑环境"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            message_box(
                "No selected mesh object, please select mesh objects and retry | "
                + "没有选中Mesh物体，请选中Mesh物体后重试"
            )
            return {"CANCELLED"}

        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL",0.4)
            uv_editor.ui_type = "UV"
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        for mesh in selected_meshes:
            mesh.select_set(True)
            has_uv = has_uv_attribute(mesh)  # 处理uv layers
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

        # setup uv editor
        uv_space.image = None
        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        self.report({"INFO"}, "Base UV edit mode")
        return {"FINISHED"}


class SetupLookDevEnvOperator(bpy.types.Operator):

    bl_idname = "object.setuplookdevenv"
    bl_label = "SetupLookDevEnv"
    bl_description = "设置LookDev预览环境"

    def execute(self, context):
        file_path = PRESET_FILE_PATH
        world_name = LOOKDEV_HDR
        import_world(file_path=file_path, world_name=world_name)
        for world in bpy.data.worlds:
            if world.name == world_name:
                world = world
                break
        if bpy.context.scene.world is not world:
            bpy.context.scene.world = world

        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        viewport_shading_mode("VIEW_3D", "RENDERED")
        self.report({"INFO"}, "LookDev environment setup finished")
        return {"FINISHED"}

class PreviewWearMaskOperator(bpy.types.Operator):
    bl_idname = "object.previewwearmask"
    bl_label = "PreviewWearMask"
    bl_description = "预览WearMask效果，需要Mesh有顶点色属性'WearMask'\
        选中模型后运行，可以自动切换激活的顶点色"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        if len(selected_meshes) == 0:
            self.report(
                {"INFO"},
                "No selected mesh object,"
                + " if mesh's active vertex color is not 'wearmask',"
                + " you might not be able to preview the correct result."
                + " | 没有选中Mesh物体，如果Mesh当前顶点色没有'WearMask'，"
                + "则无法预览正确结果",
            )

        for mesh in selected_meshes:
            set_active_color_attribute(mesh, VERTEXCOLOR)

        viewports = viewport_shading_mode("VIEW_3D", "SOLID", mode="CONTEXT")

        for viewport in viewports:
            viewport.shading.color_type = "VERTEX"

        self.report(
            {"INFO"},
            "Switch preview w earMask in viewport | 在viewport切换预览WearMask",
        )

        return {"FINISHED"}

# classes = (
#     PrepSpaceClaimCADMeshOperator,
#     MakeSwatchUVOperator,
#     CleanVertexOperator,
#     FixSpaceClaimObjOperator,
#     SeparateMultiUserOperator,
#     AddSnapSocketOperator,
#     SwatchMatSetupOperator,
#     SetupLookDevEnvOperator,
#     PreviewWearMaskOperator
# )
