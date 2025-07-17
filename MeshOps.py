import bpy
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *
from mathutils import Vector
import math

def check_non_solid_meshes(meshes):
    bad_mesh_count=0
    bad_meshes=[]

    for mesh in meshes:
        check_mesh=Mesh.check_open_bondary(mesh)
        if check_mesh is True:
            bad_mesh_count+=1
            bad_meshes.append(mesh)
        

    if bad_mesh_count!=0:
        bad_collection=Collection.create(name=BAD_MESHES_COLLECTION,type="MISC")
        for mesh in bad_meshes:
            mesh.users_collection[0].objects.unlink(mesh)
            bad_collection.objects.link(mesh)
        return bad_meshes
    elif bad_meshes ==0:
        return None

class PrepCADMeshOperator(bpy.types.Operator):
    bl_idname = "hst.prepcadmesh"
    bl_label = "Prep CAD FBX Mesh"
    bl_description = "初始化导入的CAD模型fbx，清理孤立顶点，UV初始化\
        需要保持模型水密\
        如果模型的面是分开的请先使用FixCADObj工具修理"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        active_object = bpy.context.active_object

        #clean up
        bad_collection=Collection.get_by_name(BAD_MESHES_COLLECTION)
        if bad_collection is not None and len(bad_collection.all_objects) == 0:
                bpy.data.collections.remove(bad_collection)

        if selected_meshes is None:
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

        # all_meshes_ok=True
        bad_meshes=check_non_solid_meshes(selected_meshes)
        if bad_meshes:
            bad_mesh_count=len(bad_meshes)
            self.report(
                    {"ERROR"},
                    f"{bad_mesh_count} selected meshes has open boundary | {bad_mesh_count}个选中的模型有开放边界",
                )

            return {"CANCELLED"}
        
        #if meshes are not all ok, continue
        

        for mesh in selected_meshes:
            Transform.apply(mesh, location=False, rotation=True, scale=True)
            Mesh.clean_mid_verts(mesh)
            Mesh.clean_loose_verts(mesh)
            Object.mark_hst_type(mesh, "STATICMESH")
            # mark_convex_edges(mesh)

            has_uv = has_uv_attribute(mesh)  # 处理uv layers
            if has_uv is True:
                uv_base = rename_uv_layers(mesh, new_name=UV_BASE, uv_index=0)
            else:
                uv_base = add_uv_layers(mesh, uv_name=UV_BASE)
            uv_base.active = True

            for edge in mesh.data.edges:  # 从锐边生成UV Seam
                edge.use_seam = True if edge.use_edge_sharp else False

        Mesh.merge_verts_ops(selected_meshes)

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
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        store_object_mode = bpy.context.active_object.mode
        bpy.ops.object.mode_set(mode="OBJECT")
        for mesh in selected_meshes:
            check_mesh = Mesh.check_open_bondary(mesh)
            if check_mesh is True:
                self.report(
                    {"ERROR"},
                    "Selected mesh has open boundary, please check\n"
                    + "选中的模型有开放边界，请检查",
                )
                return {"CANCELLED"}
            Mesh.clean_mid_verts(mesh)
            Mesh.clean_loose_verts(mesh)
        bpy.ops.object.mode_set(mode=store_object_mode)
        self.report({"INFO"}, "Selected meshes cleaned")
        return {"FINISHED"}


class FixCADObjOperator(bpy.types.Operator):
    bl_idname = "hst.fixcadobj"
    bl_label = "Fix CAD Obj"
    bl_description = "修理CAD输出的obj，以便进行后续操作\
        自动合并面，并根据顶点法线标记锐边"

    def execute(self, context):
        SHARP_ANGLE = 0.08
        MERGE_DISTANCE = 0.01
        DISSOLVE_ANGLE = 0.00174533

        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")

        if selected_meshes is None:
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
            # apply_modifiers(mesh)
            Transform.apply(mesh, location=False, rotation=True, scale=True)
        Mesh.merge_verts_ops(selected_meshes)

        bad_meshes=check_non_solid_meshes(selected_meshes)
        if bad_meshes:
            bad_mesh_count=len(bad_meshes)
            self.report(
                    {"ERROR"},
                    f"{bad_mesh_count} selected meshes has open boundary | {bad_mesh_count}个选中的模型有开放边界",
                )

            return {"CANCELLED"}

        for mesh in selected_meshes:

            mark_sharp_edges_by_split_normal(mesh)

            mesh.select_set(True)



        restore_select_mode(store_mode)
        self.report({"INFO"}, "Selected meshes fixed")
        return {"FINISHED"}


class SeparateMultiUserOperator(bpy.types.Operator):
    bl_idname = "hst.sepmultiuser"
    bl_label = "Clean Multi User"
    bl_description = "清理multi user，可能会造成冗余资源，请及时清除"
        

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

        if selected_meshes is None:
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
    

def find_objs_bb_center(objs) -> Vector:
    """Find the center of the bounding box of all objects"""

    all_coords = []
    for o in objs:
        bb = o.bound_box
        mat = o.matrix_world
        for vert in bb:
            coord = mat @ Vector(vert)
            all_coords.append(coord)

    if not all_coords:
        return Vector((0, 0, 0))

    center = sum(all_coords, Vector((0, 0, 0))) / len(all_coords)
    return center


def find_objs_bb_lowest_center(objs) -> Vector:
    """Find the lowest_center of the bounding box of all objects"""

    all_coords = []
    for o in objs:
        bb = o.bound_box
        mat = o.matrix_world
        for vert in bb:
            coord = mat @ Vector(vert)
            all_coords.append(coord)

    if not all_coords:
        return Vector((0, 0, 0))

    # Find the lowest Z value among all bounding box coordinates
    lowest_z = min(coord.z for coord in all_coords)
    # Find the center in X and Y
    center_xy = sum(
        (Vector((coord.x, coord.y, 0)) for coord in all_coords), Vector((0, 0, 0))
    ) / len(all_coords)
    center = Vector((center_xy.x, center_xy.y, lowest_z))
    return center


def find_selected_element_center() -> Vector:
    """When in object mode, find the center of the selected objects.
    When in edit mode, find the center of the selected vertices in all selected mesh objects.
    """

    selected_objects = bpy.context.selected_objects
    if len(selected_objects) == 0:
        return None

    # Check if any selected object is in edit mode and is a mesh
    edit_mode_meshes = [
        obj for obj in selected_objects if obj.type == "MESH" and obj.mode == "EDIT"
    ]
    if edit_mode_meshes:
        all_selected_verts = []
        # Switch all edit mode objects to object mode to access their mesh data
        for obj in edit_mode_meshes:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="OBJECT")
            all_selected_verts.extend(
                [obj.matrix_world @ v.co for v in obj.data.vertices if v.select]
            )
        # Restore the first object to edit mode
        bpy.context.view_layer.objects.active = edit_mode_meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        if not all_selected_verts:
            return None
        center = sum(all_selected_verts, Vector((0, 0, 0))) / len(all_selected_verts)
        return center
    else:
        # Get the center of the selected objects in object mode
        center = find_objs_bb_center(selected_objects)
        return center




class AddAssetOriginOperator(bpy.types.Operator):
    bl_idname = "hst.add_asset_origin"
    bl_label = "Add Asset Origin"
    bl_description = "选中Collection中任意模型，为此Collection添加Asset Origin"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        active_object = bpy.context.active_object
        collection = active_object.users_collection[0]
        # 直接计算目标位置
        mesh_objs = [obj for obj in collection.all_objects if obj.type == "MESH"]
        pivots = [obj.matrix_world.translation for obj in mesh_objs]
        all_same = all((pivots[0] - p).length < 1e-6 for p in pivots) if pivots else False

        if all_same and pivots:
            origin_location = pivots[0].copy()
        elif pivots:
            # 取所有mesh的中心点
            origin_location = sum(pivots, Vector((0, 0, 0))) / len(pivots)
        else:
            origin_location = active_object.location.copy()

        origin_name = ORIGIN_PREFIX + collection.name
        origin_object = bpy.data.objects.new(name=origin_name, object_data=None)
        origin_object.location = origin_location
        origin_object.empty_display_type = "PLAIN_AXES"
        origin_object.empty_display_size = 0.4
        origin_object.show_name = True
        collection.objects.link(origin_object)
        Object.mark_hst_type(origin_object, "ORIGIN")

        for object in collection.all_objects:
            if object.type == "MESH":
                obj_loc_raw=object.location.copy()
                obj_loc=obj_loc_raw-origin_object.location #计算collection objects 和 origin object的相对位置，使最后保持原始世界位置
                object.parent = origin_object
                object.location = obj_loc
        for object in selected_objects:
            object.select_set(False)
        origin_object.select_set(True)

        return {"FINISHED"}

    def invoke(self, context, event):
        selected_objects = bpy.context.selected_objects
        if not selected_objects:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}
        active_object = bpy.context.active_object
        if not active_object:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
        collection = active_object.users_collection[0]
        existing_origin_objects = Object.filter_hst_type(
            objects=collection.all_objects, type="ORIGIN", mode="INCLUDE"
        )
        if existing_origin_objects is not None:
            existing_origin_objects[0].name = ORIGIN_PREFIX + collection.name
            self.report({"INFO"}, "Asset Origin already exists")
            return {"CANCELLED"}
        mesh_objs = [obj for obj in collection.all_objects if obj.type == "MESH"]
        if not mesh_objs:
            self.report({"ERROR"}, "No mesh objects in collection")
            return {"CANCELLED"}
        pivots = [obj.matrix_world.translation for obj in mesh_objs]
        all_same = all((pivots[0] - p).length < 1e-6 for p in pivots)
        if all_same:
            return self.execute(context)
        else:
            return context.window_manager.invoke_confirm(self, event)
        
        #TODO: invoke 添加选项 ， 当pivot不一致时， 弹出菜单，多个选项: 1.世界中心 2.Collection中心 3.Collection底部 4.Active Object中心 5.Cursor位置  。 如果在Edit Mode，使用选中顶点的中心   
    
class BatchAddAssetOriginOperator(bpy.types.Operator):
    """ 为所有Prop Collection添加Asset Origin """

    bl_idname = "hst.batch_add_asset_origin"
    bl_label = "Add All Prop Asset Origins"
    bl_description = "为所有Prop Collection添加Asset Origin"
    bl_options = {"REGISTER", "UNDO"}

    # 添加属性用于invoke弹窗
    origin_mode: bpy.props.EnumProperty(
        name="Origin Mode",
        description="选择Origin的位置",
        items=[
            ("WORLD_CENTER", "World Center", "使用世界中心作为Origin"),
            ("COLLECTION_CENTER", "Collection Pivots Center", "使用Collection所有对象Pivots的中心"),
        ],
        default="COLLECTION_CENTER",
    )

    def execute(self, context):
        is_local_view = Viewport.is_local_view()
        new_origins_count = 0
        store_mode = prep_select_mode()
        selected_objects = Object.get_selected()

        

        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)

        prop_collections = Collection.filter_hst_type(
            collections=bpy.data.collections, type="PROP", mode="INCLUDE"
        )
        if prop_collections is None:
            self.report({"ERROR"}, "No Prop Collections, mark prop collections with 'Mark Prop' first")
            return {"CANCELLED"}

        for collection in prop_collections:
            collection_objs = [obj for obj in collection.all_objects]
            # 跳过没有object的collection
            if not collection_objs:
                continue

            existing_origin_objects = Object.filter_hst_type(
                objects=collection_objs, type="ORIGIN", mode="INCLUDE"
            )

            asset_objs = []
            if existing_origin_objects is not None:
                for obj in collection_objs:
                    if obj not in existing_origin_objects:
                        asset_objs.append(obj)
            else:
                asset_objs = collection_objs

            # 计算origin位置
            pivots = [obj.matrix_world.translation for obj in asset_objs if obj.type == "MESH"]

            if existing_origin_objects is not None:
                new_asset_objs = []
                for obj in asset_objs:
                    if obj.parent is None:
                        new_asset_objs.append(obj)
                    else:
                        if obj.parent != existing_origin_objects[0]:
                            new_asset_objs.append(obj)
                asset_objs = new_asset_objs
                existing_origin_objects[0].name = ORIGIN_PREFIX + collection.name
                origin_object = existing_origin_objects[0]
                self.report({"INFO"}, f"{collection.name} has Asset Origin already")
            else:
                # 新建origin
                origin_name = ORIGIN_PREFIX + collection.name
                origin_object = bpy.data.objects.new(name=origin_name, object_data=None)

                if self.origin_mode == "COLLECTION_CENTER":
                    origin_location = (
                        sum(pivots, Vector((0, 0, 0))) / len(pivots) if pivots else Vector((0, 0, 0))
                    )
                elif self.origin_mode == "WORLD_CENTER":
                    origin_location = Vector((0, 0, 0))
                print("origin_location:", origin_location,"mode:",self.origin_mode)
                
                # 移除了 COLLECTION_BOTTOM 选项

                origin_object.location = origin_location
                origin_object.empty_display_type = "PLAIN_AXES"
                origin_object.empty_display_size = 0.4
                origin_object.show_name = True
                collection.objects.link(origin_object)
                Object.mark_hst_type(origin_object, "ORIGIN")
                new_origins_count += 1

            for object in asset_objs:
                if is_local_view:
                    bpy.ops.view3d.localview(frame_selected=False)
                if object.type == "MESH":
                    obj_loc_raw = object.location.copy()
                    obj_loc = obj_loc_raw - origin_object.location
                    object.parent = origin_object
                    object.location = obj_loc

        restore_select_mode(store_mode)
        self.report({"INFO"}, f"Added {new_origins_count} Asset Origins")

        return {"FINISHED"}

    def invoke(self, context, event):
        prop_collections = Collection.filter_hst_type(
            collections=bpy.data.collections, type="PROP", mode="INCLUDE"
        )
        if prop_collections is None:
            self.report({"ERROR"}, "No Prop Collections, mark prop collections with 'Mark Prop' first")
            return {"CANCELLED"}

        # 检查是否所有prop collections都已经有origin object
        all_has_origin = True
        for collection in prop_collections:
            collection_objs = [obj for obj in collection.objects]
            existing_origin_objects = Object.filter_hst_type(
                objects=collection_objs, type="ORIGIN", mode="INCLUDE"
            )
            if not existing_origin_objects:
                all_has_origin = False
                break

        if all_has_origin:
            self.report({"INFO"}, "All prop collections already have Asset Origin")
            return {"CANCELLED"}


        return self.execute(context)
    def draw(self, context):
            # self.layout.use_property_split = True
            layout = self.layout
            box = layout.box()
            box_column = box.column()

            box_column.label(text="Choose Origin Location")
            box_column.prop(self, "origin_mode", expand=True)


    


class HST_SwatchMatSetupOperator(bpy.types.Operator):
    bl_idname = "hst.swatchmatsetup"
    bl_label = "HST Swatch Edit Mode"
    bl_description = "设置Swatch材质的编辑环境，如果没有Swatch材质会自动导入"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
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
        UV.show_uv_in_object_mode()
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
        switch_to_eevee()
        # bpy.context.scene.render.engine = "BLENDER_EEVEE"
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
        if selected_meshes is None:
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
            uv_editor.show_uv = True
            uv_editor.uv_face_opacity = 1
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
        switch_to_eevee()
        # bpy.context.scene.render.engine = "BLENDER_EEVEE"
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
        if selected_meshes is None:
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

        UV.show_uv_in_object_mode()

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

        switch_to_eevee()
        # bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
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
        if selected_meshes is not None:
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
        if selected_meshes is None:
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


    def execute(self, context):
        print("CheckAssetsOperator")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MarkDecalCollectionOperator(bpy.types.Operator):
    bl_idname = "hst.markdecalcollection"
    bl_label = "Mark Decal Collection"
    bl_description = "设置所选为Decal Collection，对collection中的Mesh，如果材质名是decal类型，则标记Mesh为decal。"

    def execute(self, context):
        selected_collections=Collection.get_selected()


        if selected_collections is None:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )

            return {"CANCELLED"}

        for decal_collection in selected_collections:

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

            decal_collection.hide_render = True
            Collection.mark_hst_type(decal_collection, "DECAL")
            for mesh in static_meshes:
                print(mesh.name)
                mats=get_materials(mesh)
                for mat in mats:
                    if mat.name.endswith(MESHDECAL_SUFFIX) or mat.name.endswith(INFODECAL_SUFFIX) or mat.name.endswith(DECAL_SUFFIX) or mat.name.startswith(DECAL_PREFIX):
                        Object.mark_hst_type(mesh, "DECAL")
                        
                        mesh.visible_shadow = False
                        mesh.display.show_shadows = False



                        

            self.report(
                {"INFO"}, str(len(selected_collections)) + " Decal collection marked"
            )
        return {"FINISHED"}


class MarkPropCollectionOperator(bpy.types.Operator):
    bl_idname = "hst.markpropcollection"
    bl_label = "Mark Prop Collection"
    bl_description = "设置所选为Prop Collection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects

        selected_collections=Collection.get_selected()

        if selected_collections is None:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )
            return {"CANCELLED"}

        for prop_collection in selected_collections:
            prop_collection_name = clean_collection_name(prop_collection.name)
            new_name = prop_collection_name

            prop_collection.name = new_name
            Collection.mark_hst_type(prop_collection, "PROP")
            prop_collection.hide_render = True
        rename_prop_meshes(selected_objects)

        self.report({"INFO"}, str(len(selected_collections)) + " Prop collection marked")
        return {"FINISHED"}






class FixDuplicatedMaterialOperator(bpy.types.Operator):
    bl_idname = "hst.fixduplicatedmaterial"
    bl_label = "Fix Duplicated Material"
    bl_description = "修复选中模型中的重复材质，例如 MI_Mat.001替换为MI_Mat"

    def execute(self, context):

        selected_objects = Object.get_selected()
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
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
            bpy.ops.object.material_slot_remove_unused() # remove unused material slot
            bad_mat_index=[]
            # is_good_mat_in_mesh=False
            # good_mats=[]
            # good_mats_in_mesh=[]
            
            
            for i in range(len(mesh.material_slots)):
                is_bad_mat=False # 记录是否为重复材质
                mat = mesh.material_slots[i].material
                if mat in bad_materials: #如果插槽内的材质在bad_materials中，则记录此插槽的index
                    is_bad_mat=True

                elif mat not in bad_materials:
                    mat_name_split = mat.name.split(".00") # 检查材质名称是否带序号
                    if len(mat_name_split) > 1:
                        mat_name = mat_name_split[0]
                        mat_good = get_scene_material(mat_name) #检查是否有原始材质（不带序号的）
                        # if mat_good not in good_mats:
                        #     good_mats.append(mat_good)
                        if mat_good is not None: #如果有原始材质，则记录此插槽的index
                            is_bad_mat=True
                        else:# 没有原始材质，则修改材质名称，去除 .00x 后缀
                            mat.name = mat_name
                if is_bad_mat:
                    bad_mat_index.append(i)
                    bad_materials.append(mat)

            if len(bad_mat_index)>0: # 有重复材质时
                bad_meshes.append(mesh)
                
                for i in bad_mat_index:
                    mat = mesh.material_slots[i].material
                    mat_name_split = mat.name.split(".00")
                    mat_name = mat_name_split[0]
                    mat_good = get_scene_material(mat_name)
                    mesh.material_slots[i].material = mat_good
            
            #检查合并后是否有重复材质
            has_duplicated_mats=False 
            mat_names=[]
            for i in range(len(mesh.material_slots)):
                mat = mesh.material_slots[i].material
                mat_name=mat.name
                if mat_name not in mat_names:
                    mat_names.append(mat_name)
                else:
                    has_duplicated_mats=True
                    break

            if has_duplicated_mats:
                # print(f"{mesh.name}has duplicated materials")
                Material.remove_duplicated_mats_ops(mesh)
                
            


            
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
        selected_meshes = filter_type(selected_objects, "MESH")

        if selected_meshes is None:
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



class IsolateCollectionsAltOperator(bpy.types.Operator):
    """ 选中collection中的任一物体，单独显示此collection """
    bl_idname = "hst.isolate_collections_alt"
    bl_label = "Isolate Collections"
    bl_description = "选中collection中的任一物体，单独显示此collection"

    def execute(self, context):
        is_local_view=Viewport.is_local_view()
        selected_collections=Collection.get_selected()
        selected_objects=Object.get_selected()
        if selected_collections is None:
            if selected_objects is None:
                if is_local_view:
                    self.report(
                        {"INFO"},
                        "Exit local view",
                    )
                    bpy.ops.view3d.localview(frame_selected=False)
                else:
                    # self.report("")
                    self.report(
                        {"INFO"},
                        "nothing selected, please select object and retry",
                    )
                    return {"CANCELLED"}
            
        else:
            store_mode = prep_select_mode()
            if selected_collections:
                for collection in selected_collections:
                    parent_coll=Collection.find_parent(collection)
                    if parent_coll:
                        if parent_coll not in selected_collections:
                            selected_collections.append(parent_coll)

                coll_objs=[]
                if selected_collections is not None:
                    for coll in selected_collections:
                        for object in coll.all_objects:
                            if object not in coll_objs:
                                coll_objs.append(object)
                
                Collection.active(selected_collections[0])


                if is_local_view is True:
                    
                    bpy.ops.view3d.localview()

                for object in bpy.data.objects:
                    object.select_set(False)
                
                for obj in coll_objs:

                    obj.select_set(True)
                

                bpy.ops.view3d.localview(frame_selected=True)
                

                restore_select_mode(store_mode)
                
            self.report({"INFO"}, "Isolate Collections")


        return {'FINISHED'}

        




class BreakLinkFromLibraryOperator(bpy.types.Operator):
    bl_idname = "hst.break_link_from_library"
    bl_label = "Break Link From Library"
    bl_description = "Break Link From Library"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes=filter_type(selected_objects,"MESH")
        count=0
        unlinked_meshes=[]
        if selected_meshes is None:
            self.report({"INFO"}, "No meshes selected, please select mesh and retry")
            return {'CANCELLED'}
        else:
            for mesh in selected_meshes:
                unlinked_mesh=Object.break_link_from_assetlib(mesh)
                unlinked_meshes.append(unlinked_mesh)
                count+=1
            for mesh in unlinked_meshes:
                mesh.select_set(True)
            self.report({"INFO"}, f"{count} meshes break link from library")
        return {'FINISHED'}

class ResetPropTransformToOriginOperator(bpy.types.Operator):
    bl_idname = "hst.reset_prop_transform_to_origin"
    bl_label = "Reset Prop Transform To Origin"
    bl_description = "Reset Prop Transform To Origin"

    def execute(self, context):
        # selected_objects = bpy.context.selected_objects
        # selected_meshes=filter_type(selected_objects,"MESH")
        selected_objects=Object.get_selected()
        selected_collection=Collection.get_selected()
        prop_collections=[]
        store_mode = prep_select_mode()
        origin_count=0
        for collection in selected_collection:
            collection_type=Collection.get_hst_type(collection)
            if collection_type==Const.TYPE_PROP_COLLECTION:
                prop_collections.append(collection)
        if len(prop_collections)==0:
            self.report({"ERROR"}, "No prop collections selected, please select prop collections and retry")
            return {'CANCELLED'}
        elif len(prop_collections)>0:
            for object in selected_objects:
                object.select_set(False)
            for collection in prop_collections:
                print(collection.name)
                origin_objects=Object.filter_hst_type(objects=collection.objects, type="ORIGIN", mode="INCLUDE")
                print(origin_objects)
                if origin_objects:
                    origin_count+=1
                    origin_object=origin_objects[0]

                    for object in collection.all_objects:
                        if object==origin_object:
                            continue
                        else:
                            object.select_set(True)
                            origin_object.select_set(True)
                            bpy.context.view_layer.objects.active = origin_object
                            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
                            Transform.apply(object)
                            object.select_set(False)
                            origin_object.select_set(False)

                else:
                    continue

        restore_select_mode(store_mode)
        self.report({"INFO"}, f"{origin_count} prop collections' objects reset transform to origin")
                    

        return {'FINISHED'}






class MarkSharpOperator(bpy.types.Operator):
    bl_idname = "hst.marksharp"
    bl_label = "Mark Sharp by Normal"
    bl_description = "Mark Sharp Edge by Split Normal"

    def execute(self, context):
        selected_objects=bpy.context.selected_objects
        for obj in selected_objects:
            mark_sharp_edges_by_split_normal(obj)

        return {'FINISHED'}
    


class ExtractUCXOperator(bpy.types.Operator):
    bl_idname = "hst.extractucx"
    bl_label = "ExtractUCX"

    def execute(self, context):
        # selected_objects=bpy.context.selected_objects
        ucx_meshes=[]
        non_ucx_meshes=[]
        #deselct all
        current_mode = bpy.context.active_object.mode
        if current_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        all_objects = bpy.data.objects
        selected_meshes = filter_type(all_objects, "MESH")
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected_meshes:
            if obj.name.startswith("UCX_") or obj.name.startswith("U_"):
                ucx_meshes.append(obj)
            else:
                non_ucx_meshes.append(obj)

        if len(ucx_meshes)==0:
            self.report({"ERROR"},"No UCX mesh selected, please select UCX mesh and retry")
            return {'CANCELLED'}
        
        for mesh in non_ucx_meshes:
            #delete them all
            bpy.data.objects.remove(mesh)

        for mesh in ucx_meshes:
            #rename them, remove ucx_ prefix
            mesh.name=mesh.name.replace("UCX_","U_")
            mesh.select_set(True)
        for mesh in ucx_meshes:
            bpy.context.view_layer.objects.active = mesh
            break

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        self.report({"INFO"},f"{len(non_ucx_meshes)} meshes removed, {len(ucx_meshes)} UCX meshes extracted")
        return {"FINISHED"}


class SnapTransformOperator(bpy.types.Operator):
    bl_idname = "hst.snap_transform"
    bl_label = "Snap Transform"
    bl_description = "把物体的位置/角度/缩放吸附到格子上"
    bl_options  = {'REGISTER', 'UNDO'}

    snap_location_toggle: bpy.props.BoolProperty(name="Snap Location",default=True)
    snap_rotation_toggle: bpy.props.BoolProperty(name="Snap Rotation",default=True)
    snap_scale_toggle: bpy.props.BoolProperty(name="Snap Scale",default=False)
    
    snap_grid: bpy.props.EnumProperty(
        name="Grid (cm)",
        items=[
            ("1", "1", "1"),
            ("5", "5", "5"),
            ("10", "10", "10"),
        ],
        default="1"
    )
    snap_angle: bpy.props.EnumProperty(
        name="Angle (deg)",
        items=[
            ("1", "1", "1"),
            ("5", "5", "5"),
            ("10", "10", "10"),
            ("15", "15", "15"),
            ("30", "30", "30"),
            ("45", "45", "45"),
            ("60", "60", "60"),
            ("90", "90", "90"),
        ],
        default="5"
    )
    snap_scale:bpy.props.EnumProperty(
        name="Scale",
        items=[
            ("1", "1", "1"),
            ("0.5", "0.5", "0.5"),
            ("0.25", "0.25", "0.25"),
            ("0.125", "0.125", "0.125"),
            ("0.0625", "0.0625", "0.0625"),
        ],default="0.125"
    )

    def execute(self, context):
        # 对于选中的对象，逐个检查 transform 的 location 和 rotation，
        # 如果 location 不是 snap_grid 的倍数（以厘米为单位），则修改 location 到最接近的 snap_grid 的倍数。
        # 如果 rotation 不是 snap_angle 的倍数，则修改 rotation 到最接近的 snap_angle 的倍数。
        
        selected_objs = context.selected_objects
        snap_grid_cm = float(self.snap_grid)  # 单位：厘米
        snap_grid = snap_grid_cm / 100.0      # Blender内部单位：米
        snap_angle = float(self.snap_angle)
        snap_scale_val = float(self.snap_scale) if hasattr(self, 'snap_scale') and self.snap_scale_toggle else None
        changed_count = 0
        for obj in selected_objs:
            # 位置吸附（以厘米为单位）
            if self.snap_location_toggle:
                loc = obj.location
                snapped_loc = [round(coord / snap_grid) * snap_grid for coord in loc]
                if any(abs(a - b) > 1e-5 for a, b in zip(loc, snapped_loc)):
                    obj.location = snapped_loc
                    changed_count += 1
            # 旋转吸附
            if self.snap_rotation_toggle:
                rot = obj.rotation_euler
                snapped_rot = [math.radians(round(math.degrees(angle) / snap_angle) * snap_angle) for angle in rot]
                if any(abs(a - b) > 1e-5 for a, b in zip(rot, snapped_rot)):
                    obj.rotation_euler = snapped_rot
                    changed_count += 1
            # 缩放吸附
            if self.snap_scale_toggle and snap_scale_val is not None:
                scale = obj.scale
                snapped_scale = [round(s / snap_scale_val) * snap_scale_val for s in scale]
                if any(abs(a - b) > 1e-5 for a, b in zip(scale, snapped_scale)):
                    obj.scale = snapped_scale
                    changed_count += 1
        self.report({'INFO'}, f"已吸附 {changed_count} 个对象的位置/旋转/缩放")
        return {"FINISHED"}
    def invoke(self, context,event):
        selected_objs = context.selected_objects
        if len(selected_objs) == 0: 
            return {"CANCELLED"}
        return self.execute(context)
