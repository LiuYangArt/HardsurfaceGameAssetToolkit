# -*- coding: utf-8 -*-
"""
Wearmask 操作 Operators
======================

包含 Wearmask 烘焙和代理模型相关的操作。
"""

import bpy
from ..Const import *
from ..Functions.HSTFunctions import *
from ..Functions.CommonFunctions import *


def prep_wearmask_objects(selected_objects):
    """
    处理 meshes 用于 wearmask 烘焙

    Args:
        selected_objects: 选中的对象列表

    Returns:
        proxy_collection: 创建的代理 Collection
    """
    selected_meshes = filter_type(selected_objects, "MESH")
    selected_meshes = Object.filter_hst_type(selected_meshes, "PROXY", mode="EXCLUDE")
    rename_prop_meshes(selected_objects)
    target_collections = filter_collections_selection(selected_objects)
    for collection in target_collections:
        collection.hide_render = True
    print(PRESET_FILE_PATH)
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
        add_color_transfer_modifier(mesh)
        add_gn_wearmask_modifier(mesh)
        add_triangulate_modifier(mesh)
        mesh.hide_render = True

    for proxy_object in proxy_object_list:  # 处理proxy模型
        cleanup_color_attributes(proxy_object)
        add_vertexcolor_attribute(proxy_object, WEARMASK_ATTR)
        set_active_color_attribute(proxy_object, WEARMASK_ATTR)
    return proxy_collection


class HST_OT_CreateTransferVertColorProxy(bpy.types.Operator):
    """为选中的物体建立用于烘焙顶点色的代理模型"""
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
        selected_meshes = Object.filter_hst_type(
            selected_meshes, "PROXY", mode="EXCLUDE"
        )

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

        proxy_collection = prep_wearmask_objects(selected_objects)

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


class HST_OT_BakeProxyVertexColorAO(bpy.types.Operator):
    """烘焙代理模型的AO到顶点色"""
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
        selected_meshes = Object.filter_hst_type(
            selected_meshes, "PROXY", mode="EXCLUDE"
        )

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

        proxy_collection = prep_wearmask_objects(selected_objects)  # 处理proxy模型

        bpy.context.scene.render.engine = "CYCLES"
        transfer_proxy_collection = proxy_collection
        set_visibility(transfer_proxy_collection, True)
        proxy_layer_coll = Collection.find_layer_collection(proxy_collection)
        proxy_layer_coll.hide_viewport = False  # toggle eye-icon

        for object in selected_objects:
            object.hide_render = True
            object.select_set(False)

        for mesh in selected_meshes:  # find proxy mesh
            for modifier in mesh.modifiers:
                if modifier.name == COLOR_TRANSFER_MODIFIER:
                    if modifier.object is None:
                        print("modifier target object missing")
                        break
                    elif Object.check_empty_mesh(modifier.object) is True:
                        print(f"{mesh} is empty mesh for bake, skip it")
                        Modifier.remove(
                            mesh, COLOR_TRANSFER_MODIFIER, has_subobject=True
                        )
                    else:
                        bake_list.append(modifier.object)
                        break

        # 隐藏不必要烘焙的物体
        for proxy_object in transfer_proxy_collection.objects:
            set_visibility(proxy_object, False)
        # 显示需要烘焙的物体，并设置为选中
        for proxy_bake_object in bake_list:
            set_visibility(proxy_bake_object, True)
            proxy_bake_object.select_set(True)

        # 烘焙AO到顶点色
        bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
        self.report(
            {"INFO"}, "Baked " + str(len(bake_list)) + " objects' AO to vertex color"
        )
        # 重置可见性和渲染引擎
        set_visibility(transfer_proxy_collection, False)
        bpy.context.scene.render.engine = current_render_engine
        for object in selected_objects:
            object.select_set(False)

        return {"FINISHED"}


class HST_OT_CleanHSTObjects(bpy.types.Operator):
    """清理所选物体对应的HST修改器和传递模型"""
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


class HST_OT_CleanOrphanProxyMesh(bpy.types.Operator):
    """
    清理 _TransferNormal 和 _TransferProxy collection 下的冗余 proxy mesh。
    冗余判断标准：
    - 没有 parent（原始 mesh 已被删除）
    - 没有被任何 DATA_TRANSFER modifier 引用
    """
    bl_idname = "hst.cleanorphanproxymesh"
    bl_label = "Clean Orphan Proxy Mesh"
    bl_description = ("清理 _TransferNormal 和 _TransferProxy 下"
                       "无 parent 或未被 modifier 引用的冗余 mesh")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # 收集所有被 DATA_TRANSFER modifier 引用的 objects
        referenced_objects = set()
        for obj in bpy.data.objects:
            if obj.type == "MESH":
                for modifier in obj.modifiers:
                    if modifier.type == "DATA_TRANSFER" and modifier.object is not None:
                        referenced_objects.add(modifier.object)

        # 遍历两个 proxy collection
        orphan_count = 0
        removed_collections = []
        collections_to_check = [TRANSFER_COLLECTION, TRANSFER_PROXY_COLLECTION]

        for collection_name in collections_to_check:
            if collection_name not in bpy.data.collections:
                continue
            collection = bpy.data.collections[collection_name]
            orphans = []

            for obj in list(collection.objects):
                if obj.type != "MESH":
                    continue
                # 检查是否冗余：无 parent 或 未被引用
                is_orphan = (obj.parent is None) or (obj not in referenced_objects)
                if is_orphan:
                    orphans.append(obj)

            # 删除冗余 mesh
            for orphan in orphans:
                mesh_data = orphan.data
                bpy.data.objects.remove(orphan)
                if mesh_data is not None and mesh_data.users == 0:
                    bpy.data.meshes.remove(mesh_data)
                orphan_count += 1

            # 如果 collection 变空，删除 collection
            if len(collection.objects) == 0:
                removed_collections.append(collection_name)
                bpy.data.collections.remove(collection)

        # 报告结果
        if removed_collections:
            self.report(
                {"INFO"},
                f"Cleaned {orphan_count} orphan proxy mesh(es), "
                f"removed empty collection(s): {', '.join(removed_collections)}",
            )
        else:
            self.report({"INFO"}, f"Cleaned {orphan_count} orphan proxy mesh(es)")

        return {"FINISHED"}


class HST_OT_CurvatureVertexcolor(bpy.types.Operator):
    """添加曲率顶点色"""
    bl_idname = "hst.curvature_vertexcolor"
    bl_label = "Add Curvature VertexColor"
    bl_description = "Add Curvature VertexColor"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        for mesh in selected_meshes:
            VertexColor.add_curvature(mesh)
        return {"FINISHED"}


class HST_OT_ReimportWearmaskNode(bpy.types.Operator):
    """重新导入 Wearmask 节点"""
    bl_idname = "hst.reimportwearmasknode"
    bl_label = "Reimport Wearmask Node"

    def execute(self, context):
        wearmask_meshes = []
        for object in bpy.data.objects:
            if object.type == "MESH":
                for modifier in object.modifiers:
                    if modifier.name == COLOR_GNODE_MODIFIER:
                        wearmask_meshes.append(object)
                        break

        if len(wearmask_meshes) == 0:
            self.report({"ERROR"}, "No Object with Wearmask found")
        if len(wearmask_meshes) > 0:
            remove_node(WEARMASK_NODE)
            remove_node("ConcaveEdgeMask")
            remove_node("VerticleGradient")
            remove_node("EdgeMaskByNormal")
            import_node_group(PRESET_FILE_PATH, WEARMASK_NODE)
            for mesh in wearmask_meshes:
                for modifier in mesh.modifiers:
                    if modifier.name == COLOR_GNODE_MODIFIER:
                        modifier.node_group = bpy.data.node_groups[WEARMASK_NODE]
                    break
            self.report({"INFO"}, f"{len(wearmask_meshes)} Object(s) updated")

        return {"FINISHED"}
