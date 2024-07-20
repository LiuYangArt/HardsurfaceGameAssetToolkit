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



def prep_wearmask_objects(selected_objects):
    """ process meshes for wearmask baking """

    selected_meshes = filter_type(selected_objects, "MESH")
    selected_meshes=Object.filter_hst_type(selected_meshes, "PROXY", mode="EXCLUDE")
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
        mark_convex_edges(mesh)

        set_active_color_attribute(mesh, WEARMASK_ATTR)
        Modifier.remove(mesh, COLOR_GNODE_MODIFIER)
        Modifier.remove(mesh, COLOR_TRANSFER_MODIFIER, has_subobject=True)
        Modifier.remove(mesh, TRIANGULAR_MODIFIER)
        proxy_mesh = make_transfer_proxy_mesh(
            mesh, TRANSFERPROXY_PREFIX, proxy_collection
        )
        proxy_object_list.append(proxy_mesh)
        # add_face_weight_attribute(mesh, value=1)
        add_color_transfer_modifier(mesh)
        add_gn_wearmask_modifier(mesh)
        add_triangulate_modifier(mesh)
        mesh.hide_render = True

    for proxy_object in proxy_object_list:  # 处理proxy模型
        cleanup_color_attributes(proxy_object)
        add_vertexcolor_attribute(proxy_object, WEARMASK_ATTR)
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
        selected_meshes = Object.filter_hst_type(selected_meshes, "PROXY", mode="EXCLUDE")

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
        selected_meshes = Object.filter_hst_type(selected_meshes, "PROXY", mode="EXCLUDE")

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
        proxy_layer_coll=Collection.find_layer_collection(proxy_collection)
        proxy_layer_coll.hide_viewport=False #toggle eye-icon

        for object in selected_objects:
            object.hide_render = True
            object.select_set(False)

        for mesh in selected_meshes: #find proxy mesh
            for modifier in mesh.modifiers:
                if modifier.name == COLOR_TRANSFER_MODIFIER:
                    if modifier.object is None:
                        print("modifier target object missing")
                        break
                        # continue
                    else:
                        bake_list.append(modifier.object)
                        break

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
            if DECAL_SUFFIX not in collection.name:
                decal_collection_name = collection.name + DECAL_SUFFIX
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
        target_collections=Collection.get_selected()
        if target_collections is None:
            self.report(
                {"ERROR"},
                "No collection selected | \n"
                + "没有选中的Collection",
            )
            return {"CANCELLED"}
        

        selected_objects=Object.get_selected()
        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)
        

        for collection in target_collections:
            decal_collection=None
            current_state=None
            remove_exist_collection=False
            count_exist=0
            count_create=0
            origin_object=None
            
            #check selected collection's state:
            collection_type=Collection.get_hst_type(collection)
            parent_collection=Collection.find_parent_recur(collection,type=Const.TYPE_PROP_COLLECTION)
            # print(f"parent_collection:{parent_collection}")
            if parent_collection:
                origin_objects=Object.filter_hst_type(objects=parent_collection.objects, type="ORIGIN", mode="INCLUDE")
                origin_object_name=Const.STATICMESH_PREFIX+parent_collection.name
            else:
                origin_objects=Object.filter_hst_type(objects=collection.objects, type="ORIGIN", mode="INCLUDE")
                origin_object_name=Const.STATICMESH_PREFIX+collection.name
            if origin_objects:
                origin_object=origin_objects[0]
                origin_object.name=origin_object_name
            

            match collection_type:
                case None:
                    if parent_collection:
                        current_state = "subobject_collection"

                    else:
                        
                        current_state = "root_decal_collection"
                        self.report(
                        {"ERROR"},
                        f"{collection.name} is not prop collection, please check")
                        return {"CANCELLED"}

                case Const.TYPE_DECAL_COLLECTION:
                    if parent_collection:
                        current_state="decal_collection"

                    else:
                        current_state = "root_decal_collection" 
                        continue
                case Const.TYPE_PROP_COLLECTION:
                    if parent_collection:
                        self.report(
                        {"ERROR"},
                        f"{collection.name} is prop collection in prop collection, please check")
                        return {"CANCELLED"}
                    else:
                        if collection.children:
                            for child_collection in collection.children:
                                child_type=Collection.get_hst_type(child_collection)
                                if child_type == Const.TYPE_DECAL_COLLECTION:
                                    current_state="prop_collection"
                        else:
                            current_state="prop_collection_raw"
                case _:
                    self.report(
                    {"ERROR"},
                    f"{collection.name} has bad collection type, please check")
                    return {"CANCELLED"}



            match current_state:
                case "subobject_collection":
                    if parent_collection.children:
                        for child_collection in parent_collection.children:
                            child_type=Collection.get_hst_type(child_collection)
                            if child_type == Const.TYPE_DECAL_COLLECTION:
                                decal_collection=child_collection
                                break
                    decal_meshes=Object.filter_hst_type(objects=parent_collection.all_objects, type="DECAL", mode="INCLUDE")
                    decal_collection_name=parent_collection.name+DECAL_SUFFIX

                # case "root_decal_collection":
                #     decal_collection=collection
                #     decal_meshes=Object.filter_hst_type(objects=collection.all_objects, type="DECAL", mode="INCLUDE")
                #     decal_collection_name=collection.name+"_Decal"

                case "prop_collection":
                    decal_collection=child_collection
                    decal_meshes=Object.filter_hst_type(objects=collection.all_objects, type="DECAL", mode="INCLUDE")
                    decal_collection_name=collection.name+DECAL_SUFFIX
                case "prop_collection_raw":
                    decal_collection=None
                    decal_meshes=Object.filter_hst_type(objects=collection.all_objects, type="DECAL", mode="INCLUDE")
                    decal_collection_name=collection.name+DECAL_SUFFIX
                case "decal_collection":
                    decal_collection=collection
                    decal_meshes=Object.filter_hst_type(objects=parent_collection.all_objects, type="DECAL", mode="INCLUDE")
                    decal_collection_name=parent_collection.name+DECAL_SUFFIX
                case None:
                    self.report(
                    {"ERROR"},
                    f"{collection.name} has bad collection type, please check")
                    return {"CANCELLED"}



            for exist_collection in bpy.data.collections: #collection 命名冲突时
                if exist_collection.name == decal_collection_name and exist_collection is not decal_collection:
                    file_c_parent=Collection.find_parent_recur(exist_collection,type=Const.TYPE_PROP_COLLECTION)
                    if file_c_parent: #有parent 时根据parent命名
                        exist_collection.name=file_c_parent.name+DECAL_SUFFIX
                    else: #无parent时删除并把包含的decal移入当前collection
                        ex_decal_meshes=Object.filter_hst_type(objects=exist_collection.all_objects, type="DECAL", mode="INCLUDE")
                        if ex_decal_meshes:
                            if decal_meshes:
                                decal_meshes.extend(ex_decal_meshes)
                            else:
                                decal_meshes=ex_decal_meshes
                        exist_collection.name="to_remove_"+exist_collection.name
                        remove_exist_collection=True
                    break
                        


            if decal_collection: #修改命名
                decal_collection.name=decal_collection_name
                count_exist+=1

            elif decal_collection is None: #新建Decal Collection
                decal_collection = Collection.create(name=decal_collection_name,type="DECAL")
                collection.children.link(decal_collection)
                bpy.context.scene.collection.children.unlink(decal_collection)
                count_create+=1

                
            decal_collection.hide_render = True
            Collection.active(decal_collection)

            if decal_meshes: #将Decal添加到Decal Collection
                for decal_mesh in decal_meshes:
                    decal_mesh.users_collection[0].objects.unlink(decal_mesh)
                    decal_collection.objects.link(decal_mesh)
                    Transform.apply_scale(decal_mesh)
                    decal_mesh=Object.break_link_from_assetlib(decal_mesh)

                    if origin_object:
                        decal_mesh.select_set(True)
                        origin_object.select_set(True)
                        bpy.context.view_layer.objects.active = origin_object
                        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
                        decal_mesh.select_set(False)
                        origin_object.select_set(False)



            if remove_exist_collection: #删除重复Collection
                bpy.data.collections.remove(exist_collection)

            self.report({"INFO"}, f"{count_exist} Decal Collection(s) updated, {count_create} Decal Collection(s) created")

        return {'FINISHED'}
    

class MarkTintObjectOperator(bpy.types.Operator):
    bl_idname = "hst.mark_tint_object"
    bl_label = "Mark Tint Object"
    bl_description = "为选中的物体添加TintMask，储存于WearMask的Alpha通道"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        

        target_collections=filter_collections_selection(selected_objects)
        if target_collections is None:
            self.report(
                {"ERROR"},
                "Not in collection",
            )
            return {"CANCELLED"}
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
        self.report({"INFO"}, f"{len(selected_meshes)} Tint Object(s) marked")
        return {'FINISHED'}

class MarkAdditionalAttribute(bpy.types.Operator):
    bl_idname = "hst.mark_attribute"
    bl_label = "Mark Additional Attribute"
    bl_description = "为选中的物体添加额外的Attribute，用于特殊材质混合"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        

        target_collections=filter_collections_selection(selected_objects)
        if target_collections is None:
            self.report(
                {"ERROR"},
                "Not in collection",
            )
            return {"CANCELLED"}
        for collection in target_collections:
            if collection is not None:
                collection_objects=collection.objects

                for object in collection_objects:
                    if object.type=="MESH":

                        spec_attr=MeshAttributes.add(object,attribute_name=Const.SPEC_ATTRIBUTE,data_type="FLOAT",domain="POINT")
                        
                        if object not in selected_meshes:
                            MeshAttributes.fill_points(object,spec_attr,value=0.0)
                        if object in selected_meshes:

                            MeshAttributes.fill_points(object,spec_attr,value=1.0)
        self.report({"INFO"}, f"{len(selected_meshes)} Tint Object(s) marked")
        return {'FINISHED'}


class MarkNormalType(bpy.types.Operator):
    bl_idname = "hst.mark_normal_type"
    bl_label = "Mark Normal Type"
    bl_description = "为选中的物体标记Normal Type，储存于WearMask的B通道"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params
        normal_type=parameters.normal_type/NORMAL_TYPE_NUM
        print(normal_type)

        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        for mesh in selected_meshes:
            normal_attr=MeshAttributes.add(mesh,attribute_name=NORMAL_TYPE_ATTRIBUTE,data_type="FLOAT",domain="POINT")

            MeshAttributes.fill_points(mesh,normal_attr,value=normal_type)

        
        self.report({"INFO"}, f"{len(selected_meshes)} Object(s) marked")
        return {'FINISHED'}


class MarkSpecType(bpy.types.Operator):
    bl_idname = "hst.mark_spec_type"
    bl_label = "Mark Spec Type"
    bl_description = "为选中的物体标记Spec Type，用于特殊材质混合"


    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        parameters = context.scene.hst_params
        spec_type=parameters.spec_type/SPEC_TYPE_NUM
        print(spec_type)

        if selected_meshes is None:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry | \n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        for mesh in selected_meshes:
            spec_attr=MeshAttributes.add(mesh,attribute_name=SPEC_TYPE_ATTRIBUTE,data_type="FLOAT",domain="POINT")

            MeshAttributes.fill_points(mesh,spec_attr,value=spec_type)

        
        self.report({"INFO"}, f"{len(selected_meshes)} Object(s) marked")
        return {'FINISHED'}


class ReimportWearmaskNodeOperator(bpy.types.Operator):
    bl_idname = "hst.reimportwearmasknode"
    bl_label = "Reimport Wearmask Node"

    def execute(self, context):
        
        wearmask_meshes=[]
        for object in bpy.data.objects:
            if object.type=="MESH":
                for modifier in object.modifiers:
                    if modifier.name == COLOR_GNODE_MODIFIER:
                        wearmask_meshes.append(object)
                        break

        if len(wearmask_meshes)==0:
            self.report({"ERROR"}, "No Object with Wearmask found")
        if len(wearmask_meshes)>0:
            remove_node(WEARMASK_NODE)
            remove_node("ConcaveEdgeMask")
            remove_node("VerticleGradient")
            remove_node("EdgeMaskByNormal")
            import_node_group(PRESET_FILE_PATH,WEARMASK_NODE)
            for mesh in wearmask_meshes:
                for modifier in mesh.modifiers:
                    if modifier.name == COLOR_GNODE_MODIFIER:
                        modifier.node_group = bpy.data.node_groups[WEARMASK_NODE]
                    break
            self.report({"INFO"}, f"{len(wearmask_meshes)} Object(s) updated")

        return {'FINISHED'}

    


