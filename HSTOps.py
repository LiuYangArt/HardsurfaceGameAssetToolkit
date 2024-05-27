import bpy
from .Const import *
from .Functions.HSTFunctions import *
from .Functions.CommonFunctions import *


class HST_BevelTransferNormal(bpy.types.Operator):
    bl_idname = "hst.hstbeveltransfernormal"
    bl_label = "HST Batch Bevel And Transfer Normal"
    bl_description = "添加倒角并从原模型传递法线到倒角后的模型，解决复杂曲面法线问题"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        collection = get_collection(selected_objects[0])
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        parameters = context.scene.hst_params
        bevel_width = convert_length_by_scene_unit(parameters.set_bevel_width)

        if collection is None:
            self.report(
                {"ERROR"},
                "Not in collection, please put selected objects in collections and retry | \n"
                + "所选物体需要在Collections中",
            )
            return {"CANCELLED"}
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        ###=====================================================###

        rename_prop_meshes(selected_objects)
        transfer_collection = Collection.create(TRANSFER_COLLECTION, type="PROXY")
        set_visibility(transfer_collection, True)
        transfer_object_list = []
        for mesh in selected_meshes:
            Transform.apply(mesh)
            remove_modifier(mesh, WEIGHTEDNORMAL_MODIFIER)
            transfer_object_list.append(
                make_transfer_proxy_mesh(
                    mesh, TRANSFER_MESH_PREFIX, transfer_collection
                )
            )
            add_bevel_modifier(
                mesh,
                bevel_width,
                parameters.set_bevel_segments,
            )
            add_triangulate_modifier(mesh)
            add_datatransfer_modifier(mesh)
            mesh.select_set(True)

        set_visibility(transfer_collection, False)
        
        ###=====================================================###

        self.report(
            {"INFO"},
            "Added Bevel and Transfer Normal to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}


class HST_BatchBevel(bpy.types.Operator):
    bl_idname = "hst.hstbevelmods"
    bl_label = "Batch Add Bevel Modifiers"
    bl_description = "批量添加Bevel和WeightedNormal\
        在已有Bevel修改器的情况下使用会根据参数设置修改Bevel修改器宽度和段数"

    def execute(self, context):
        parameters = context.scene.hst_params
        
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        bevel_width = convert_length_by_scene_unit(parameters.set_bevel_width)
        collection = get_collection(selected_objects[0])

        if collection is not None:
            selected_collections = filter_collections_selection(selected_objects)
            for collection in selected_collections:
                collection_meshes,ucx_meshes = filter_static_meshes(collection)
                rename_meshes(collection_meshes, collection.name)

        for mesh in selected_meshes:
            # apply_transfrom(mesh)
            remove_modifier(mesh, NORMALTRANSFER_MODIFIER, has_subobject=True)
            add_bevel_modifier(
                mesh,
                bevel_width,
                parameters.set_bevel_segments,
            )
            add_weightednormal_modifier(mesh)
            add_triangulate_modifier(mesh)
            mesh.select_set(True)

        self.report(
            {"INFO"},
            "Added Bevel and WeightedNormal modifier to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}


# class HST_SetBevelParameters_Operator(bpy.types.Operator):
#     bl_idname = "hst.hstbevelsetparam"
#     bl_label = "Set HSTBevel Parameters"
#     bl_description = "修改HST Bevel修改器参数"

#     def execute(self, context):
#         parameters = context.scene.hst_params
#         selected_objects = bpy.context.selected_objects
#         if len(selected_objects) == 0:
#             self.report(
#                 {"ERROR"},
#                 "No selected object, please select objects and retry\n"
#                 + "没有选中的Object，请选中物体后重试",
#             )
#             return {"CANCELLED"}
        
#         bevel_width = convert_length_by_scene_unit(parameters.set_bevel_width)

#         success_count = 0
#         for object in selected_objects:
#             for modifier in object.modifiers:
#                 if modifier.name == BEVEL_MODIFIER:
#                     modifier.segments = parameters.set_bevel_segments
#                     modifier.width = bevel_width
#                     success_count += 1
#                     continue
#         self.report(
#             {"INFO"},
#             "Set Bevel Modifier Parameters to "
#             + str(parameters.set_bevel_segments)
#             + " segments and "
#             + str(bevel_width)
#             + " width for "
#             + str(success_count)
#             + " objects",
#         )
#         return {"FINISHED"}

def prep_wearmask_objects(selected_objects):
    """ process meshes for wearmask baking """

    selected_meshes = filter_type(selected_objects, "MESH")
    rename_prop_meshes(selected_objects)
    target_collections=filter_collections_selection(selected_objects)
    for collection in target_collections:
        collection.hide_render=True
    import_node_group(PRESET_FILE_PATH, WEARMASK_NODE)  # 导入wearmask nodegroup
    proxy_object_list = []
    proxy_collection = Collection.create(TRANSFER_PROXY_COLLECTION, type="PROXY")
    set_visibility(proxy_collection, True)
    for mesh in selected_meshes:
        Transform.apply(mesh, location=True, rotation=True, scale=True)
        cleanup_color_attributes(mesh)
        add_vertexcolor_attribute(mesh, WEARMASK_ATTR)
        # add_vertexcolor_attribute(mesh, CURVATURE_ATTR)
        set_active_color_attribute(mesh, WEARMASK_ATTR)
        remove_modifier(mesh, COLOR_GEOMETRYNODE_MODIFIER)
        remove_modifier(mesh, COLOR_TRANSFER_MODIFIER, has_subobject=True)

        proxy_mesh = make_transfer_proxy_mesh(
            mesh, TRANSFERPROXY_PREFIX, proxy_collection
        )
        proxy_object_list.append(proxy_mesh)
        add_face_weight_attribute(mesh, value=1)
        add_color_transfer_modifier(mesh)
        add_gn_wearmask_modifier(mesh)
        mesh.hide_render = True

    for proxy_object in proxy_object_list:  # 处理proxy模型
        cleanup_color_attributes(proxy_object)
        add_vertexcolor_attribute(proxy_object, WEARMASK_ATTR)
        # VertexColor.add_curvature(proxy_object)
        set_active_color_attribute(proxy_object, WEARMASK_ATTR)
    return proxy_collection


class HST_CreateTransferVertColorProxy(bpy.types.Operator):
    bl_idname = "hst.hst_addtransvertcolorproxy"
    bl_label = "HST Make Transfer VertexColor Proxy"
    bl_description = "为选中的物体建立用于烘焙顶点色的代理模型\
        代理模型通过DataTransfer修改器将顶点色传递回原始模型\
        如果原始模型有造型修改，请重新运行建立代理\
        注意其修改器顺序必须存在于Bevel修改器之后"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry\n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        collection = get_collection(selected_objects[0])
        selected_meshes = filter_type(selected_objects, type="MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")

        if collection is None:
            self.report(
                {"ERROR"},
                "Not in collection, please put selected objects in collections and retry | \n"
                + "所选物体需要在Collections中",
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}

        proxy_collection=prep_wearmask_objects(selected_objects)

        set_visibility(proxy_collection, False)
        for mesh in selected_meshes:
            mesh.select_set(True)

        self.report(
            {"INFO"},
            "Created "
            + str(len(selected_meshes))
            + " transfer vertex color proxy objects",
        )

        return {"FINISHED"}


class HST_BakeProxyVertexColorAO(bpy.types.Operator):
    bl_idname = "hst.hst_bakeproxyvertcolrao"
    bl_label = "HST Bake Proxy VertexColor AO"
    bl_description = "烘焙代理模型的AO，需要先建立Proxy\
        场景中如存在其它可渲染的物体会对AO造成影响\
        建议手动关闭其它物体的可渲染开关\
        如果遇到烘焙Crash，请尝试在注册表中修改TDRDelay"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        active_object = bpy.context.active_object
        current_render_engine = bpy.context.scene.render.engine  # 记录原渲染引擎
        bake_list = []
        collection = get_collection(active_object)
        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")

        if collection is None:
            self.report(
                {"ERROR"},
                "Not in collection, please put selected objects in collections and retry | \n"
                + "所选物体需要在Collections中",
            )
            return {"CANCELLED"}

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        proxy_collection=prep_wearmask_objects(selected_objects)


        bpy.context.scene.render.engine = "CYCLES"
        transfer_proxy_collection = proxy_collection
        set_visibility(transfer_proxy_collection, True)

        for object in selected_objects:
            object.hide_render = True
            object.select_set(False)

        for mesh in selected_meshes:
            for modifier in mesh.modifiers:
                if modifier.name == COLOR_TRANSFER_MODIFIER:
                    if modifier.object is None:
                        print("modifier target object missing")
                        continue
                    else:
                        bake_list.append(modifier.object)

        # 隐藏不必要烘焙的物体
        for proxy_object in transfer_proxy_collection.objects:
            set_visibility(proxy_object, False)
        # 显示需要烘焙的物体，并设置为选中
        for proxy_bake_object in bake_list:
            set_visibility(proxy_bake_object, True)
            # bpy.context.view_layer.objects.active = proxy_bake_object
            proxy_bake_object.select_set(True)

        # 烘焙AO到顶点色
        bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
        self.report(
            {"INFO"}, "Baked " + str(len(bake_list)) + " objects' AO to vertex color"
        )
        # # 重置可见性和渲染引擎
        set_visibility(transfer_proxy_collection, False)
        bpy.context.scene.render.engine = current_render_engine
        for object in selected_objects:
            object.select_set(False)

        return {"FINISHED"}


class HST_CleanHSTObjects(bpy.types.Operator):
    bl_idname = "hst.cleanhstobject"
    bl_label = "Clean HST Objects"
    bl_description = "清理所选物体对应的HST修改器和传递模型"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}
        delete_list = []
        selected_meshes = filter_type(selected_objects, type="MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")
        for mesh in selected_meshes:
            for modifier in mesh.modifiers:
                if (
                    modifier.name == NORMALTRANSFER_MODIFIER
                    and modifier.object is not None
                ):
                    delete_list.append(modifier.object)

                if (
                    modifier.name == COLOR_TRANSFER_MODIFIER
                    and modifier.object is not None
                ):
                    delete_list.append(modifier.object)

                if "HST" in modifier.name:
                    mesh.modifiers.remove(modifier)
            mesh.select_set(False)
        for delete_object in delete_list:
            if delete_object is None:
                continue
            else:
                bpy.data.objects.remove(delete_object)

        self.report(
            {"INFO"},
            "Cleaned "
            + str(len(selected_meshes))
            + " objects' HST modifiers， removed "
            + str(len(delete_list))
            + " modifier objects",
        )

        return {"FINISHED"}
    
class CurvatureVertexcolorOperator(bpy.types.Operator):
    bl_idname = "hst.curvature_vertexcolor"
    bl_label = "Add Curvature VertexColor"
    bl_description = "Add Curvature VertexColor"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        for mesh in selected_meshes:
            VertexColor.add_curvature(mesh)
        return {'FINISHED'}

class HSTApplyMirrorModifierOperator(bpy.types.Operator):
    bl_idname = "hst.apply_mirror_modifier"
    bl_label = "Apply Mirror Modifier"
    bl_description = "批量应用选中物体的Mirror Modifier"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes)==0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        for mesh in selected_meshes:
            has_modifiers=False
            if mesh.modifiers is not None:
                has_modifiers=True
            if has_modifiers:
                for modifier in mesh.modifiers:
                    if modifier.type == 'MIRROR':
                        mesh.select_set(True)
                        bpy.context.view_layer.objects.active = mesh
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
        return {'FINISHED'}

class HSTRemoveEmptyMesh(bpy.types.Operator):
    bl_idname = "hst.remove_empty_mesh"
    bl_label = "Remove Empty Mesh"
    bl_description = "删除空的Mesh物体"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes)==0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        empty_mesh_count=0
        for mesh in selected_meshes:
            if Object.check_empty_mesh(mesh) is True:
                empty_mesh_count+=1
                print(f"{mesh.name} is empty mesh, remove it")
                bpy.data.objects.remove(mesh)
        self.report({"INFO"}, f"Removed {empty_mesh_count} empty mesh objects")
        return {'FINISHED'}
    
class HSTDecalColName(bpy.types.Operator):
    bl_idname = "hst.make_decal_collection_name"
    bl_label = "Decal Collection Name"
    bl_description = ""


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects)==0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry | \n"
                + "没有选中物体，请选中物体后重试",
            )
        collection = get_collection(selected_objects[0])
        if collection is None:
            self.report(
                {"ERROR"},
                "Not in Collection | \n"
                + "所选物体不在Collection中",
            )
            return {"CANCELLED"}
        if collection is not None:
            if "_Decal" not in collection.name:
                decal_collection_name = collection.name + "_Decal"
                copy_to_clip(decal_collection_name)
                self.report({"INFO"}, f"copy {decal_collection_name} to clipboard")
            else:
                self.report({"INFO"}, f"{collection.name} is already a decal collection")


        return {'FINISHED'}
    
class HSTActiveCollection(bpy.types.Operator):
    bl_idname = "hst.active_current_collection"
    bl_label = "Active Collection"
    bl_description = "把所选物体所在的Collection设为Active"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        outliner_coll=Outliner.get_selected_collections()
        if outliner_coll is None:
            if len(selected_objects)==0:
                self.report(
                    {"ERROR"},
                    "No selected object, please select objects and retry | \n"
                    + "没有选中物体，请选中物体后重试",
                )
            collection = get_collection(selected_objects[0])
            if collection is None:
                self.report(
                    {"ERROR"},
                    "Not in Collection | \n"
                    + "所选物体不在Collection中",
                )
                return {"CANCELLED"}
            if collection is not None:
                Collection.active(collection)
        else:
            Collection.active(outliner_coll[0])

        return {'FINISHED'}

class MakeDecalCollection(bpy.types.Operator):
    bl_idname = "hst.make_decal_collection"
    bl_label = "Make Decal Collection"
    bl_description = "添加对应的Decal Collection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes)==0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        collection = get_collection(selected_meshes[0])
        if collection is None:
            self.report(
                {"ERROR"},
                "Not in Collection | \n"
                + "所选物体不在Collection中",
            )
            return {"CANCELLED"}
        target_collections=filter_collections_selection(selected_objects)
        for collection in target_collections:

            if collection is not None:
                collection_type=Collection.get_hst_type(collection)
                if collection_type == "DECAL":
                    self.report({"INFO"}, f"{collection.name} is already a decal collection")
                    return {'CANCELLED'}
                decal_meshes=Object.filter_hst_type(objects=collection.all_objects, type="DECAL", mode="INCLUDE")
                decal_collection_name=collection.name+"_Decal"
                decal_collection = None
                print(f"decal_collection_name: {decal_collection_name}")

                for decal_mesh in decal_meshes:
                    # Transform.apply(object=decal_mesh,location=False,rotation=False,scale=True)
                    Transform.apply_scale(decal_mesh)

                for file_collection in bpy.data.collections:
                    print(f"file_collection.name: {file_collection.name}")
                    if file_collection.name == decal_collection_name:
                        decal_collection= file_collection
                        Collection.mark_hst_type(decal_collection, "DECAL")
                        self.report({"INFO"}, f"{decal_collection_name} is already exist")
                        break


                if decal_collection is None:
                    decal_collection = Collection.create(name=decal_collection_name,type="DECAL")
                    collection.children.link(decal_collection)
                    bpy.context.scene.collection.children.unlink(decal_collection)
                    self.report({"INFO"}, f"{decal_collection_name} is created")
                decal_collection.hide_render = True
                for object in selected_objects:
                    object.select_set(False)
                if decal_meshes is not None:
                    for decal_mesh in decal_meshes:
                        if decal_mesh.users_collection[0]==collection:
                            collection.objects.unlink(decal_mesh)
                            decal_collection.objects.link(decal_mesh)
                        decal_mesh.select_set(True)
                Collection.active(decal_collection)

        return {'FINISHED'}
    

class MarkTintObjectOperator(bpy.types.Operator):
    bl_idname = "hst.mark_tint_object"
    bl_label = "Mark Tint Object"
    bl_description = "为选中的物体添加TintMask，储存于WearMask的Alpha通道"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if len(selected_meshes)==0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        

        target_collections=filter_collections_selection(selected_objects)
        for collection in target_collections:
            if collection is not None:
                collection_objects=collection.objects

                for object in collection_objects:
                    if object.type=="MESH":

                        tint_attr=MeshAttributes.add(object,attribute_name=Const.TINT_ATTRIBUTE,data_type="FLOAT",domain="POINT")
                        
                        if object not in selected_meshes:
                            MeshAttributes.fill_points(object,tint_attr,value=0.0)
                        if object in selected_meshes:

                            MeshAttributes.fill_points(object,tint_attr,value=1.0)



        return {'FINISHED'}

    


