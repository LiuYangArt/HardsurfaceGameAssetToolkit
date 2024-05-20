import bpy
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *


class PrepSpaceClaimCADMeshOperator(bpy.types.Operator):
    bl_idname = "hst.prepspaceclaimcadmesh"
    bl_label = "Cleanup SpaceClaim FBX Mesh"
    bl_description = "初始化导入的CAD模型fbx，清理孤立顶点，UV初始化\
        需要保持模型水密\
        如果模型的面是分开的请先使用FixSpaceClaimObj工具修理"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        active_object = bpy.context.active_object
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        set_default_scene_units()

        collections = []
        
        for mesh in selected_meshes:
            if mesh.users_collection[0] not in collections:
                collections.append(mesh.users_collection[0])
            if Object.check_empty_mesh(mesh) is True:
                bpy.data.objects.remove(mesh)
                selected_meshes.remove(mesh)
        if active_object not in selected_meshes:
            bpy.context.view_layer.objects.active = selected_meshes[0]

        store_mode = prep_select_mode()
        if len(collections) > 0:
            for collection in collections:
                collection_type=Collection.get_hst_type(collection)
                if collection_type==Const.TYPE_DECAL_COLLECTION:
                    self.report(
                        {"ERROR"},
                        "Selected collections has decal collection, operation stop\n"
                        + "选中的Collection包含Decal Collection，操作停止",
                    )
                    return {"CANCELLED"}
                new_collection_name = clean_collection_name(collection.name)
                # collection.color_tag = "COLOR_" + PROP_COLLECTION_COLOR
                if collection.name != "Scene Collection":
                    collection.name = new_collection_name

        for mesh in selected_meshes:
            check_mesh = check_open_bondary(mesh)
            if check_mesh is True:
                self.report(
                    {"ERROR"},
                    f"Selected mesh: {mesh.name} has open boundary, please check | 选中的模型有开放边界，请检查",
                )
                return {"CANCELLED"}
            Transform.apply(mesh, location=True, rotation=True, scale=True)
            clean_mid_verts(mesh)
            clean_loose_verts(mesh)
            Object.mark_hst_type(mesh, "STATICMESH")

            has_uv = has_uv_attribute(mesh)  # 处理uv layers
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

            for edge in mesh.data.edges:  # 从锐边生成UV Seam
                edge.use_seam = True if edge.use_edge_sharp else False

        uv_unwrap(
            selected_meshes, method="ANGLE_BASED", margin=0.005, correct_aspect=True
        )
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        restore_select_mode(store_mode)
        self.report({"INFO"}, "Selected meshes prepped")
        return {"FINISHED"}


class HST_MakeSwatchUVOperator(bpy.types.Operator):
    bl_idname = "hst.makeswatchuv"
    bl_label = "HST Make Swatch UV"
    bl_description = "为CAD模型添加Swatch UV"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
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
    bl_idname = "hst.cleanvert"
    bl_label = "Clean Verts"
    bl_description = "清理模型中的孤立顶点，只能用在水密模型上，否则会造成模型损坏"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_object_mode = bpy.context.active_object.mode
        bpy.ops.object.mode_set(mode="OBJECT")
        for mesh in selected_meshes:
            check_mesh = check_open_bondary(mesh)
            if check_mesh is True:
                self.report(
                    {"ERROR"},
                    "Selected mesh has open boundary, please check\n"
                    + "选中的模型有开放边界，请检查",
                )
                return {"CANCELLED"}
            clean_mid_verts(mesh)
            clean_loose_verts(mesh)
        bpy.ops.object.mode_set(mode=store_object_mode)
        self.report({"INFO"}, "Selected meshes cleaned")
        return {"FINISHED"}


class FixSpaceClaimObjOperator(bpy.types.Operator):
    bl_idname = "hst.fixspaceclaimobj"
    bl_label = "FixSpaceClaimObj"
    bl_description = "修理spaceclaim输出的obj，以便进行后续操作\
        自动合并面，并根据角度标记锐边"

    def execute(self, context):
        SHARP_ANGLE = 0.08
        MERGE_DISTANCE = 0.01
        DISSOLVE_ANGLE = 0.00174533

        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()

        # 清理multi user
        for object in selected_objects:
            object.select_set(False)
        for mesh in selected_meshes:
            apply_modifiers(mesh)
            Transform.apply(mesh, location=True, rotation=True, scale=True)
            merge_vertes_by_distance(mesh, merge_distance=MERGE_DISTANCE)

            check_mesh = check_open_bondary(mesh)
            if check_mesh is True:
                self.report(
                    {"ERROR"},
                    "Selected mesh has open boundary, please check | 选中的模型有开放边界，请检查",
                )
                return {"CANCELLED"}

            mark_sharp_edge_by_angle(mesh, sharp_angle=SHARP_ANGLE)
            mesh.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.dissolve_limited(angle_limit=DISSOLVE_ANGLE)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Selected meshes fixed")
        return {"FINISHED"}


class SeparateMultiUserOperator(bpy.types.Operator):
    bl_idname = "hst.sepmultiuser"
    bl_label = "Clean Multi User"
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
        bpy.ops.object.make_single_user(
            type="SELECTED_OBJECTS", object=True, obdata=True
        )

        self.report({"INFO"}, "Done")
        return {"FINISHED"}


class AddSnapSocketOperator(bpy.types.Operator):
    bl_idname = "hst.addsnapsocket"
    bl_label = "Add Snap Socket"
    bl_description = "添加用于UE Modular Snap System的Socket，\
        在编辑模式下使用时，先选中用于Snap的面，会自动创建朝向正确的Socket\
        有多个同名Socket时，编号需使用下划线分割，如SOCKET_SNAP_01，SOCKET_SNAP_02"

    def execute(self, context):

        cursor = bpy.context.scene.cursor
        cursor_current_transform = cursor.matrix.copy()
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        collection = selected_objects[0].users_collection[0]

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
        socket_name = SOCKET_PREFIX + text_capitalize(parameters.socket_name)
        socket_object = bpy.data.objects.new(name=SOCKET_PREFIX, object_data=None)
        rename_alt(socket_object, socket_name, num=2)
        socket_object.location = cursor.location
        socket_object.rotation_mode = "QUATERNION"
        socket_object.rotation_quaternion = cursor.rotation_quaternion
        socket_object.empty_display_type = "ARROWS"
        socket_object.empty_display_size = SOCKET_SIZE
        socket_object.show_name = True
        collection.objects.link(socket_object)
        Object.mark_hst_type(socket_object, "SOCKET")

        bpy.context.scene.cursor.matrix = cursor_current_transform

        for object in selected_objects:
            object.select_set(False)
        socket_object.select_set(True)

        return {"FINISHED"}

class AddAssetOriginOperator(bpy.types.Operator):
    bl_idname = "hst.add_asset_origin"
    bl_label = "Add Asset Origin"
    bl_description = "选中Collection中任意模型，为此Collection添加Asset Origin"\

    def execute(self, context):

        cursor = bpy.context.scene.cursor
        cursor_current_transform = cursor.matrix.copy()
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        active_object=bpy.context.active_object
        # parameters = context.scene.hst_params

        if active_object is None:

            self.report(
                {"ERROR"},
                "No active object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        collection = active_object.users_collection[0]


        existing_origin_objects=Object.filter_hst_type(objects=collection.all_objects,type="ORIGIN",mode="INCLUDE")
        if existing_origin_objects is not None:
            existing_origin_objects[0].name=ORIGIN_PREFIX+collection.name
            self.report({"INFO"}, "Asset Origin already exists")
            return {"CANCELLED"}

        if bpy.context.mode == "EDIT_MESH":
            self.report({"INFO"}, "In edit mode, create socket from selected faces")
            rotation = get_selected_rotation_quat()
            bpy.ops.view3d.snap_cursor_to_selected()
            bpy.context.scene.cursor.rotation_mode = "QUATERNION"
            bpy.context.scene.cursor.rotation_quaternion = rotation
            bpy.ops.object.mode_set(mode="OBJECT")
        else:

            bpy.context.scene.cursor.matrix=Const.WORLD_ORIGIN_MATRIX
            self.report({"INFO"}, "In object mode, create socket from selected objects")

        # add empty, set name to SOCKET_XXX and location to cursor location
        origin_name = ORIGIN_PREFIX + collection.name
        origin_object = bpy.data.objects.new(name=origin_name, object_data=None)
        # rename_alt(origin_object, origin_name, num=2)
        origin_object.location = cursor.location
        origin_object.rotation_mode = "QUATERNION"
        origin_object.rotation_quaternion = cursor.rotation_quaternion
        origin_object.empty_display_type = "PLAIN_AXES"
        origin_object.empty_display_size = 0.4
        origin_object.show_name = True
        collection.objects.link(origin_object)
        Object.mark_hst_type(origin_object, "ORIGIN")

        bpy.context.scene.cursor.matrix = cursor_current_transform

        for object in collection.all_objects:
            if object.type == "MESH":
                object.parent = origin_object
                object.matrix_parent_inverse = origin_object.matrix_world.inverted()

        for object in selected_objects:
            object.select_set(False)
        origin_object.select_set(True)

        return {"FINISHED"}
    
class BatchAddAssetOriginOperator(bpy.types.Operator):
    bl_idname = "hst.batch_add_asset_origin"
    bl_label = "Add All Prop Asset Origin"
    bl_description = "为所有Prop Collection添加Asset Origin"\

    def execute(self, context):



        prop_collections = Collection.filter_hst_type(collections=bpy.data.collections,type="PROP",mode="INCLUDE")


        for collection in prop_collections:

            existing_origin_objects=Object.filter_hst_type(objects=collection.all_objects,type="ORIGIN",mode="INCLUDE")
            if existing_origin_objects is not None:
                existing_origin_objects[0].name=ORIGIN_PREFIX+collection.name
                print(f"{collection.name} has exsiting origin")
            else:
                origin_name = ORIGIN_PREFIX + collection.name
                origin_object = bpy.data.objects.new(name=origin_name, object_data=None)
                print(f"{collection.name} new origin object {origin_object.name}")

                origin_object.matrix_world=Const.WORLD_ORIGIN_MATRIX

                origin_object.empty_display_type = "PLAIN_AXES"
                origin_object.empty_display_size = 0.4
                origin_object.show_name = True
                collection.objects.link(origin_object)
                Object.mark_hst_type(origin_object, "ORIGIN")



                for object in collection.all_objects:
                    if object.type == "MESH":
                        object.parent = origin_object
                        object.matrix_parent_inverse = origin_object.matrix_world.inverted()



        return {"FINISHED"}


class HST_SwatchMatSetupOperator(bpy.types.Operator):
    bl_idname = "hst.swatchmatsetup"
    bl_label = "HST Swatch Edit Mode"
    bl_description = "设置Swatch材质的编辑环境，如果没有Swatch材质会自动导入"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()
        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        scene_swatch_mat = get_scene_material(SWATCH_MATERIAL)
        if scene_swatch_mat is None:  # import material if not exist
            scene_swatch_mat = import_material(PRESET_FILE_PATH, SWATCH_MATERIAL)

        for mesh in selected_meshes:
            mesh.select_set(True)
            pattern_uv = check_uv_layer(mesh, Const.UV_PATTERN)
            
            if pattern_uv is not None:
                pattern_uv.name = UV_SWATCH

            swatch_uv = check_uv_layer(mesh, UV_SWATCH)
            if swatch_uv is None:  # add uv layer if not exist
                swatch_uv = add_uv_layers(mesh, uv_name=UV_SWATCH)
                scale_uv(
                    mesh, uv_layer=swatch_uv, scale=(0.001, 0.001), pivot=(0.5, 0.5)
                )
            swatch_uv.active = True

            swatch_mat = get_object_material(mesh, SWATCH_MATERIAL)
            mat_slot = get_object_material_slots(mesh)
            if swatch_mat is None:
                if len(mat_slot) == 0:  # add material if not exist
                    mesh.data.materials.append(scene_swatch_mat)
                elif len(mat_slot) > 0:
                    mat_slot[0].material = scene_swatch_mat

        for subnode in scene_swatch_mat.node_tree.nodes:  # find swatch texture
            if subnode.type == "GROUP" and subnode.label == "BaseMat_Swatch":
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

        restore_select_mode(store_mode)

        self.report({"INFO"}, "Swatch material initialized")

        return {"FINISHED"}
    
class HST_PatternMatSetup(bpy.types.Operator):
    bl_idname = "hst.patternmatsetup"
    bl_label = "PatternUV"
    bl_description = "设置Pattern材质的编辑环境，如果没有Pattern材质会自动导入"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_mode = prep_select_mode()
        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
            uv_editor.ui_type = "UV"
        for space in uv_editor.spaces:
            if space.type == "IMAGE_EDITOR":
                uv_space = space

        scene_pattern_mat = get_scene_material(PATTERN_MATERIAL)
        if scene_pattern_mat is None:  # import material if not exist
            scene_pattern_mat = import_material(PRESET_FILE_PATH, PATTERN_MATERIAL)

        for mesh in selected_meshes:
            mesh.select_set(True)
            swatch_uv = check_uv_layer(mesh, UV_SWATCH)
            
            if swatch_uv is not None:
                swatch_uv.name = Const.UV_PATTERN

            pattern_uv = check_uv_layer(mesh, Const.UV_PATTERN)

            
            if pattern_uv is None:  # add uv layer if not exist
                pattern_uv = add_uv_layers(mesh, uv_name=Const.UV_PATTERN)
                # scale_uv(
                #     mesh, uv_layer=pattern_uv, scale=(0.001, 0.001), pivot=(0.5, 0.5)
                # )
            pattern_uv.active = True

            pattern_mat = get_object_material(mesh, PATTERN_MATERIAL)
            mat_slot = get_object_material_slots(mesh)
            if pattern_mat is None:
                if len(mat_slot) == 0:  # add material if not exist
                    mesh.data.materials.append(scene_pattern_mat)
                elif len(mat_slot) > 0:
                    mat_slot[0].material = scene_pattern_mat

        # for subnode in scene_pattern_mat.node_tree.nodes:  # find swatch texture
        #     if subnode.type == "TEX_IMAGE":
        #         pattern_texture = subnode.image

        #         break

        # setup uv editor
        uv_space.image = None
        # uv_space.display_channels = "COLOR"

        uv_editor_fit_view(uv_editor)
        bpy.context.scene.tool_settings.use_uv_select_sync = True

        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        viewport_shading_mode("VIEW_3D", "RENDERED", mode="CONTEXT")

        restore_select_mode(store_mode)

        self.report({"INFO"}, "Swatch material initialized")

        return {"FINISHED"}


class BaseUVEditModeOperator(bpy.types.Operator):
    bl_idname = "hst.baseuveditmode"
    bl_label = "HST BaseUV Edit Mode"
    bl_description = "Base UV编辑环境"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        for object in selected_objects:
            object.select_set(False)

        uv_editor = check_screen_area("IMAGE_EDITOR")
        if uv_editor is None:
            uv_editor = new_screen_area("IMAGE_EDITOR", "VERTICAL", 0.35)
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

    bl_idname = "hst.setuplookdevenv"
    bl_label = "Setup LookDev Env"
    bl_description = "设置LookDev预览环境"

    def execute(self, context):
        file_path = PRESET_FILE_PATH
        world_name = LOOKDEV_HDR
        selected_objects = bpy.context.selected_objects
        store_mode = prep_select_mode()

        import_world(file_path=file_path, world_name=world_name)
        for world in bpy.data.worlds:
            if world.name == world_name:
                world = world
                break
        if bpy.context.scene.world is not world:
            bpy.context.scene.world = world

        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        viewport_shading_mode("VIEW_3D", "RENDERED")

        restore_select_mode(store_mode)
        self.report({"INFO"}, "LookDev environment setup finished")
        return {"FINISHED"}


class PreviewWearMaskOperator(bpy.types.Operator):
    bl_idname = "hst.previewwearmask"
    bl_label = "Preview WearMask"
    bl_description = "预览WearMask效果，需要Mesh有顶点色属性'WearMask'\
        选中模型后运行，可以自动切换激活的顶点色"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        # if len(selected_meshes) == 0:
        #     print("No selected mesh object, please select mesh objects and retry | 没有选中Mesh物体，请选中Mesh物体后重试")

        for mesh in selected_meshes:
            set_active_color_attribute(mesh, WEARMASK_ATTR)

        viewports = viewport_shading_mode("VIEW_3D", "SOLID", mode="CONTEXT")

        for viewport in viewports:
            viewport.shading.color_type = "VERTEX"

        self.report(
            {"INFO"},
            "Switch preview w earMask in viewport | 在viewport切换预览WearMask",
        )

        return {"FINISHED"}


class SetTexelDensityOperator(bpy.types.Operator):
    bl_idname = "hst.setbaseuvtexeldensity"
    bl_label = "Set BaseUV TexelDensity"
    bl_description = "设置选中模型的BaseUV的Texel Density\
        选中模型后运行，可以设置模型的Texel Density\
        贴图大小和TD使用默认值即可，通常不需要设置"

    def execute(self, context):
        parameters = context.scene.hst_params
        texel_density = parameters.texture_density * 0.01  # fix unit to cm
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        texture_size_x = parameters.texture_size
        texture_size_y = parameters.texture_size

        store_mode = prep_select_mode()

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            if uv_layer is None:
                self.report(
                    {"ERROR"},
                    "Selected mesh has no UV layer named 'UV0_Base', setup uv layer first\n"
                    + "选中的模型没有名为'UV0_Base'的UV，请先正确设置UV",
                )
                return {"CANCELLED"}

        uv_average_scale(selected_objects, uv_layer_name=UV_BASE)

        for mesh in selected_meshes:
            uv_layer = check_uv_layer(mesh, UV_BASE)
            print("mesh_name: " + mesh.name)
            old_td = get_texel_density(mesh, texture_size_x, texture_size_y)
            print("old_td: " + str(old_td))
            scale_factor = texel_density / old_td
            print("scale_factor: " + str(scale_factor))
            scale_uv(mesh, uv_layer, (scale_factor, scale_factor), (0.5, 0.5))

        restore_select_mode(store_mode)
        self.report({"INFO"}, "Texel Density set to " + str(texel_density))
        return {"FINISHED"}


class AxisCheckOperator(bpy.types.Operator):
    bl_idname = "hst.axischeck"
    bl_label = "Check UE Front Axis"
    bl_description = "显示UE模型坐标轴参考"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        store_mode = prep_select_mode()
        properties = context.scene.hst_params
        axis_toggle = properties.axis_toggle
        axis_objects = []
        match axis_toggle:
            case False:
                for object in bpy.data.objects:
                    if AXIS_EMPTY in object.name:
                        bpy.data.objects.remove(object)

                for object in bpy.data.objects:
                    if object.name.startswith(AXIS_OBJECT_PREFIX):
                        axis_objects.append(object)

                if len(axis_objects) > 0:
                    for obj in axis_objects:
                        for material in obj.data.materials:
                            material.user_clear()
                            bpy.data.materials.remove(material)
                        old_mesh = obj.data
                        bpy.data.objects.remove(obj)
                        old_mesh.user_clear()
                        bpy.data.meshes.remove(old_mesh)

            case True:
                axis_arrow = import_object(PRESET_FILE_PATH, AXIS_ARROW)
                axis_objects.append(axis_arrow.parent)
                axis_objects.append(axis_arrow)
                for obj in axis_objects:
                    obj.show_in_front = True
                    obj.hide_render = True
                    obj.hide_viewport = False
                    obj.hide_select = True

        restore_select_mode(store_mode)
        return {"FINISHED"}


class HST_SetSceneUnitsOperator(bpy.types.Operator):
    bl_idname = "hst.setsceneunits"
    bl_label = "SetSceneUnits"
    bl_description = "设置场景单位为厘米"

    def execute(self, context):
        set_default_scene_units()
        self.report({"INFO"}, "Scene units set to centimeters")
        return {"FINISHED"}


class CheckAssetsOperator(bpy.types.Operator):
    bl_idname = "hst.checkassets"
    bl_label = "Check Assets"

    text = "CheckAssetsOperator"

    def draw(self, context):

        layout = self.layout
        box_column = layout.column()
        box_column.label(
            text="Scene Units: " + str(bpy.context.scene.unit_settings.system),
            icon="CHECKMARK",
        )
        box_column.label(
            text="Scene Scale: " + str(bpy.context.scene.unit_settings.scale_length),
            icon="ERROR",
        )
        box_column.label(
            text="Length Units: " + str(bpy.context.scene.unit_settings.length_unit),
            icon=show_reusult(scene_unit_check()),
        )
        # TBD
        # 检查资产功能
        # 如果Collection后缀没有_Decal,检查模型是否有Swatch UV
        # 如果Collection后缀没有_Decal,检查模型是否有Base UV
        # 如果Collection后缀没有_Decal,检查模型是否有WearMask
        # 如果Collection后缀没有_Decal,检查模型Scale是否为1
        # 如果Collection后缀没有_Decal,检查模型命名是否含有_decal
        # 场景单位是否为厘米
        # 检查文件中材质是否有重复/未使用的材质/命名后有.00x的材质
        # 如果Collection后缀为_Decal，检查是否有重复的Decal材质
        # Collection命名是否首字母大写

    def execute(self, context):
        print("CheckAssetsOperator")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MarkDecalCollectionOperator(bpy.types.Operator):
    bl_idname = "hst.markdecalcollection"
    bl_label = "Mark Decal Collection"
    bl_description = "设置所选为Decal Collection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        decal_collections = filter_collections_selection(selected_objects)
        color = "COLOR_" + DECAL_COLLECTION_COLOR
        if len(decal_collections) == 0:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )

            return {"CANCELLED"}

        for decal_collection in decal_collections:
            print("mark decal collection: " + decal_collection.name)
            # decal_objects = decal_collection.all_objects
            static_meshes, ucx_meshes = filter_static_meshes(decal_collection)
            if len(ucx_meshes) > 0:
                self.report(
                    {"ERROR"},
                    decal_collection.name
                    + " has UCX mesh, please check | "
                    + "collection内有UCX Mesh，请检查",
                )

            decal_collection_name = clean_collection_name(decal_collection.name)
            new_name = decal_collection_name + DECAL_SUFFIX
            decal_collection.name = new_name
            decal_collection.color_tag = color
            decal_collection.hide_render = True
            Collection.mark_hst_type(decal_collection, "DECAL")
            for mesh in static_meshes:
                mats=get_materials(mesh)
                for mat in mats:
                    if mat.name.endswith(MESHDECAL_SUFFIX) or mat.name.endswith(INFODECAL_SUFFIX):
                        Object.mark_hst_type(mesh, "DECAL")
                        break

            self.report(
                {"INFO"}, str(len(decal_collections)) + " Decal collection marked"
            )
        return {"FINISHED"}


class MarkPropCollectionOperator(bpy.types.Operator):
    bl_idname = "hst.markpropcollection"
    bl_label = "Mark Prop Collection"
    bl_description = "设置所选为Prop Collection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        prop_collections = filter_collections_selection(selected_objects)
        # color = "COLOR_" + PROP_COLLECTION_COLOR
        if len(prop_collections) == 0:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )
            return {"CANCELLED"}

        for prop_collection in prop_collections:
            prop_collection_name = clean_collection_name(prop_collection.name)
            new_name = prop_collection_name

            prop_collection.name = new_name
            Collection.mark_hst_type(prop_collection, "PROP")
            prop_collection.hide_render = True
        rename_prop_meshes(selected_objects)

        self.report({"INFO"}, str(len(prop_collections)) + " Prop collection marked")
        return {"FINISHED"}




class FixDuplicatedMaterialOperator(bpy.types.Operator):
    bl_idname = "hst.fixduplicatedmaterial"
    bl_label = "Fix Duplicated Material"
    bl_description = "修复选中模型中的重复材质，例如 MI_Mat.001替换为MI_Mat"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        bad_materials = []
        bad_meshes = []
        store_mode = prep_select_mode()
        for mesh in selected_meshes:
            bad_mat_index=[]
            mesh_has_good_mat=False
            for i in range(len(mesh.material_slots)):
                mat = mesh.material_slots[i].material
                if mat in bad_materials:
                    bad_mat_index.append(i)
                elif mat not in bad_materials:
                    #check if mat is bad mat
                    mat_name_split = mat.name.split(".00")
                    if len(mat_name_split) > 1:
                        mat_name = mat_name_split[0]
                        mat_good = get_scene_material(mat_name)
                        if mat_good is not None:
                            bad_mat_index.append(i)
                        else:
                            mat.name = mat_name
                        bad_materials.append(mat)



            if len(bad_mat_index)>0:
                bad_meshes.append(mesh)
                for mat_slots in mesh.material_slots:
                    mat=mat_slots.material
                    if mat_good == mat:
                        mesh_has_good_mat=True
                        break
            if mesh_has_good_mat:
                for index in bad_mat_index:
                    mesh.data.materials.pop(index = index)
            else:
                for index in bad_mat_index:
                    mesh.material_slots[i].material = mat_good


            
        restore_select_mode(store_mode)
        self.report(
            {"INFO"},
            str(len(bad_materials))
            + " Materials in "
            + str(len(bad_meshes))
            + " Meshes fixed",
        )

        return {"FINISHED"}


class SetUECollisionOperator(bpy.types.Operator):
    bl_idname = "object.adduecollision"
    bl_label = "Set UE Collision"
    bl_description = "设置选中mesh为UE碰撞体，并设置命名与collection内的mesh对应\
        例如Collection内只有Mesh_01，那么碰撞体的命名需要是UCX_Mesh_01或者UCX_Mesh_01_01\
        制作好碰撞体模型后使用本工具进行设置，如果对应模型命名有修改请重新运行本工具配置碰撞体"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        collections = filter_collections_selection(selected_objects)
        selected_meshes = filter_type(selected_objects, "MESH")

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        store_mode = prep_select_mode()

        selected_collections = filter_collections_selection(selected_objects)
        if len(selected_collections) == 0:
            self.report(
                {"ERROR"},
                "Selected object not in collection, please set collection and retry\n"
                + "选中的物体不在Collection中，请设置Collection后重试",
            )
            return {"CANCELLED"}
        for collection in selected_collections:
            collection_meshes, ucx_meshes = filter_static_meshes(collection)
            static_mesh = None
            for mesh in collection_meshes:
                if mesh not in selected_meshes:
                    static_mesh = mesh
                    break
            print("static_mesh: " + str(static_mesh))
            for mesh in selected_meshes:
                if mesh.users_collection[0] == collection:
                    if static_mesh is not None:
                        set_collision_object(mesh, static_mesh.name)
                    else:
                        self.report(
                            {"ERROR"},
                            "Collection: "
                            + collection.name
                            + " has no static mesh left in collection, UCX won't work | "
                            + "Collection内没有剩余的StaticMesh，无法设置。UCX需要对应的StaticMesh以正确命名",
                        )

        restore_select_mode(store_mode)

        return {"FINISHED"}

class HSTSortCollectionsOperator(bpy.types.Operator):
    bl_idname = "hst.sort_collections"
    bl_label = "Sort Collections"
    bl_description = "按首字母对所有Collection进行排序"

    def execute(self, context):
        for scene in bpy.data.scenes:
            Collection.sort_order(scene.collection, case_sensitive=False)
        return {'FINISHED'}


