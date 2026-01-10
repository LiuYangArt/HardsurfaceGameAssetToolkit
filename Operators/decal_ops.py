# -*- coding: utf-8 -*-
"""
Decal Collection 操作 Operators
==============================

包含 Decal Collection 创建和管理相关的操作。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *


class HST_OT_ActiveCollection(bpy.types.Operator):
    """把所选物体所在的 Collection 设为 Active"""
    bl_idname = "hst.active_current_collection"
    bl_label = "Active Collection"
    bl_description = "把所选物体所在的Collection设为Active"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        outliner_coll = Outliner.get_selected_collections()
        if outliner_coll is None:
            if len(selected_objects) == 0:
                self.report(
                    {"ERROR"},
                    "No selected object, please select objects and retry | \n"
                    + "没有选中物体，请选中物体后重试",
                )
                return {"CANCELLED"}
            collection = get_collection(selected_objects[0])
            if collection is None:
                self.report(
                    {"ERROR"},
                    "Not in Collection | \n" + "所选物体不在Collection中",
                )
                return {"CANCELLED"}
            if collection is not None:
                Collection.active(collection)
        else:
            Collection.active(outliner_coll[0])

        return {"FINISHED"}


class HST_OT_MakeDecalCollection(bpy.types.Operator):
    """为 Prop 加对应的 Decal Collection"""
    bl_idname = "hst.make_decal_collection"
    bl_label = "Make Decal Collection"
    bl_description = "为Prop加对应的Decal Collection"

    def execute(self, context):
        target_collections = Collection.get_selected()
        if target_collections is None:
            self.report(
                {"ERROR"},
                "No collection selected | \n" + "没有选中的Collection",
            )
            return {"CANCELLED"}

        selected_objects = Object.get_selected()
        if selected_objects:
            for obj in selected_objects:
                obj.select_set(False)

        for collection in target_collections:
            decal_collection = None
            current_state = None
            remove_exist_collection = False
            count_exist = 0
            count_create = 0
            origin_object = None

            # check selected collection's state:
            collection_type = Collection.get_hst_type(collection)
            parent_collection = Collection.find_parent_recur_by_type(
                collection, type=Const.TYPE_PROP_COLLECTION
            )
            if parent_collection:
                origin_objects = Object.filter_hst_type(
                    objects=parent_collection.objects, type="ORIGIN", mode="INCLUDE"
                )
                origin_object_name = Const.STATICMESH_PREFIX + parent_collection.name
            else:
                origin_objects = Object.filter_hst_type(
                    objects=collection.objects, type="ORIGIN", mode="INCLUDE"
                )
                origin_object_name = Const.STATICMESH_PREFIX + collection.name
            if origin_objects:
                origin_object = origin_objects[0]
                origin_object.name = origin_object_name

            match collection_type:
                case None:
                    if parent_collection:
                        current_state = "subobject_collection"
                    else:
                        current_state = "root_decal_collection"
                        self.report(
                            {"ERROR"},
                            f"{collection.name} is not prop collection, please check",
                        )
                        return {"CANCELLED"}

                case Const.TYPE_DECAL_COLLECTION:
                    if parent_collection:
                        current_state = "decal_collection"
                    else:
                        current_state = "root_decal_collection"
                        continue
                case Const.TYPE_PROP_COLLECTION:
                    if parent_collection:
                        self.report(
                            {"ERROR"},
                            f"{collection.name} is prop collection in prop collection, please check",
                        )
                        return {"CANCELLED"}
                    else:
                        if collection.children:
                            for child_collection in collection.children:
                                child_type = Collection.get_hst_type(child_collection)
                                if child_type == Const.TYPE_DECAL_COLLECTION:
                                    current_state = "prop_collection"
                        else:
                            current_state = "prop_collection_raw"
                case _:
                    self.report(
                        {"ERROR"},
                        f"{collection.name} has bad collection type, please check",
                    )
                    return {"CANCELLED"}

            match current_state:
                case "subobject_collection":
                    if parent_collection.children:
                        for child_collection in parent_collection.children:
                            child_type = Collection.get_hst_type(child_collection)
                            if child_type == Const.TYPE_DECAL_COLLECTION:
                                decal_collection = child_collection
                                break
                    decal_meshes = Object.filter_hst_type(
                        objects=parent_collection.all_objects,
                        type="DECAL",
                        mode="INCLUDE",
                    )
                    decal_collection_name = parent_collection.name + DECAL_SUFFIX

                case "prop_collection":
                    decal_collection = child_collection
                    decal_meshes = Object.filter_hst_type(
                        objects=collection.all_objects, type="DECAL", mode="INCLUDE"
                    )
                    decal_collection_name = collection.name + DECAL_SUFFIX
                case "prop_collection_raw":
                    decal_collection = None
                    decal_meshes = Object.filter_hst_type(
                        objects=collection.all_objects, type="DECAL", mode="INCLUDE"
                    )
                    decal_collection_name = collection.name + DECAL_SUFFIX
                case "decal_collection":
                    decal_collection = collection
                    decal_meshes = Object.filter_hst_type(
                        objects=parent_collection.all_objects,
                        type="DECAL",
                        mode="INCLUDE",
                    )
                    decal_collection_name = parent_collection.name + DECAL_SUFFIX
                case None:
                    self.report(
                        {"ERROR"},
                        f"{collection.name} has bad collection type, please check",
                    )
                    return {"CANCELLED"}

            for exist_collection in bpy.data.collections:  # collection 命名冲突时
                if (
                    exist_collection.name == decal_collection_name
                    and exist_collection is not decal_collection
                ):
                    file_c_parent = Collection.find_parent_recur_by_type(
                        exist_collection, type=Const.TYPE_PROP_COLLECTION
                    )
                    if file_c_parent:  # 有parent 时根据parent命名
                        exist_collection.name = file_c_parent.name + DECAL_SUFFIX
                    else:  # 无parent时删除并把包含的decal移入当前collection
                        ex_decal_meshes = Object.filter_hst_type(
                            objects=exist_collection.all_objects,
                            type="DECAL",
                            mode="INCLUDE",
                        )
                        if ex_decal_meshes:
                            if decal_meshes:
                                decal_meshes.extend(ex_decal_meshes)
                            else:
                                decal_meshes = ex_decal_meshes
                        exist_collection.name = "to_remove_" + exist_collection.name
                        remove_exist_collection = True
                    break

            if decal_collection:  # 修改命名
                decal_collection.name = decal_collection_name
                count_exist += 1

            elif decal_collection is None:  # 新建Decal Collection
                decal_collection = Collection.create(
                    name=decal_collection_name, type="DECAL"
                )
                collection.children.link(decal_collection)
                bpy.context.scene.collection.children.unlink(decal_collection)
                count_create += 1

            decal_collection.hide_render = True
            Collection.active(decal_collection)

            if decal_meshes:  # 将Decal添加到Decal Collection
                for decal_mesh in decal_meshes:
                    decal_mesh.users_collection[0].objects.unlink(decal_mesh)
                    decal_collection.objects.link(decal_mesh)
                    Transform.apply_scale(decal_mesh)
                    decal_mesh = Object.break_link_from_assetlib(decal_mesh)

                    if origin_object:
                        decal_mesh.select_set(True)
                        origin_object.select_set(True)
                        bpy.context.view_layer.objects.active = origin_object
                        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
                        decal_mesh.select_set(False)
                        origin_object.select_set(False)

            if remove_exist_collection:  # 删除重复Collection
                bpy.data.collections.remove(exist_collection)

            self.report(
                {"INFO"},
                f"{count_exist} Decal Collection(s) updated, {count_create} Decal Collection(s) created",
            )

        return {"FINISHED"}
